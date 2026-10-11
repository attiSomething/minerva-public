"""Import submission records from a spreadsheet saved as CSV.

The writer picks which column holds what (piece, venue, dates, fee, status,
notes); Minerva guesses from the headings. Each row is matched to an entry
or project by title, and the whole file is previewed before anything is
saved: rows that are ready, rows whose piece wasn't found or is ambiguous,
rows with a value Minerva can't read, and rows already recorded. Nothing
is dropped silently: every row not imported is listed with the reason.

Exports from Submittable and The Grinder have presets: their columns are
recognized and their status words ("In-Progress", "Form Rejection") are
understood. Importing a newer export of the same history updates the
status and response date of submissions already in Minerva.

Only Minerva's index changes; the spreadsheet and the library are only
read.
"""

import csv
import datetime
import io
import re

from . import submissions

FIELDS = ("piece", "venue", "submitted_on", "status", "decided_on", "deadline", "cost", "response_days", "notes")
FIELD_LABELS = {
    "piece": "Piece (title)", "venue": "Where", "submitted_on": "Date submitted", "status": "Status",
    "decided_on": "Response date", "deadline": "Deadline", "cost": "Fee", "response_days": "Expected response (days)",
    "notes": "Notes",
}
GUESSES = {
    "piece": ("title", "piece", "poem", "story", "work", "entry", "submission", "name"),
    "venue": ("venue", "where", "magazine", "journal", "publication", "publisher", "press", "market", "contest", "outlet"),
    "submitted_on": ("submitted", "date sent", "sent", "date submitted", "submission date", "date"),
    "status": ("status", "result", "outcome", "response", "decision"),
    "decided_on": ("response date", "decided", "heard", "reply date", "date heard", "responded", "decision date"),
    "deadline": ("deadline", "due"),
    "cost": ("fee", "cost", "price", "reading fee"),
    "response_days": ("response time", "days", "wait"),
    "notes": ("notes", "note", "comments", "comment", "remarks"),
}
STATUS_WORDS = [
    ("Accepted", ("accept", "acceptance", "yes", "published", "taken")),
    ("Declined", ("decline", "reject", "no", "pass", "rejection", "form rejection", "personal rejection")),
    ("Withdrawn", ("withdr", "pulled")),
    ("Shortlisted", ("shortlist", "short list", "hold", "finalist", "semi")),
    ("Planned", ("plan", "to send", "draft", "not sent")),
    ("Submitted", ("submit", "sent", "pending", "waiting", "out", "open", "in progress", "in-progress",
                   "under review", "received")),
]

# Exports from submission services. Headings and status words are matched
# without regard to case; a preset's guesses are tried before the general
# ones. Duotrope has no preset: its terms of use restrict using exported
# data to build another database (duotrope.com/about/terms-of-use.aspx).
PRESETS = {
    "submittable": {
        "label": "Submittable",
        "signature": ("organization", "organization name", "submittable"),
        "headings": {
            "piece": ("title", "submission title", "submission"),
            "venue": ("organization", "organization name", "publisher"),
            "submitted_on": ("date submitted", "submitted", "submitted date", "submission date", "date"),
            "status": ("status", "submission status"),
            "decided_on": ("status date", "last updated", "date updated", "updated", "last activity"),
            "notes": ("form", "form name", "category", "opportunity"),
        },
        "statuses": {"received": "Submitted", "new": "Submitted", "in-progress": "Submitted",
                     "in progress": "Submitted", "accepted": "Accepted", "declined": "Declined",
                     "withdrawn": "Withdrawn", "completed": "Submitted"},
    },
    "grinder": {
        "label": "The Grinder",
        "signature": ("market", "market name", "days out"),
        # how long it was out, not how long the market usually takes
        "skip": ("days out",),
        "headings": {
            "piece": ("title", "piece", "story", "work"),
            "venue": ("market", "market name"),
            "submitted_on": ("date sent", "sent", "submitted", "date submitted"),
            "status": ("response", "response type", "status", "result"),
            "decided_on": ("date received", "response date", "date responded", "responded", "received"),
            "notes": ("notes", "comments"),
        },
        "statuses": {"pending": "Submitted", "outstanding": "Submitted", "acceptance": "Accepted",
                     "accepted": "Accepted", "form rejection": "Declined", "personal rejection": "Declined",
                     "personalized rejection": "Declined", "rejection": "Declined", "rejected": "Declined",
                     "withdrawal": "Withdrawn", "withdrawn": "Withdrawn", "hold": "Shortlisted",
                     "shortlist": "Shortlisted", "further consideration": "Shortlisted",
                     "never responded": "Declined", "lost": "Declined", "no response": "Declined"},
    },
}


def _norm(h):
    return " ".join(str(h or "").lower().replace("_", " ").split())


def detect_source(headings, name=""):
    """Which service an export came from, by its headings (or file name)."""
    norm = {_norm(h) for h in headings}
    low = (name or "").lower()
    for sid, p in PRESETS.items():
        if norm & set(p["signature"]) or sid in low:
            return sid
    return ""


def sources():
    return [{"id": "", "label": "Any spreadsheet"}] + [{"id": k, "label": v["label"]} for k, v in PRESETS.items()]
MAX_ROWS = 5000


class SubImportError(ValueError):
    user_facing = True


def read_csv(data):
    """Rows of the file (a list of lists), trying UTF-8 first, then the
    Windows encoding Excel often uses, and guessing the separator."""
    if isinstance(data, bytes):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    else:
        text = data
    if not text.strip():
        raise SubImportError("That file is empty.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise SubImportError("The file needs a row of headings and at least one row of records.")
    if len(rows) > MAX_ROWS + 1:
        raise SubImportError(f"That file has more than {MAX_ROWS:,} rows. Split it into smaller files.")
    return rows


def guess_mapping(headings, source=""):
    """{field: column index} from the headings; each column used once."""
    norm = [_norm(h) for h in headings]
    out = {}
    used = {i for i, h in enumerate(norm) if h in PRESETS.get(source, {}).get("skip", ())}
    preset = PRESETS.get(source, {}).get("headings", {})
    # the export's own headings first, then exact-ish matches, so
    # "Response date" isn't taken by "status" guesses
    for words_for, exact in ((preset, True), (GUESSES, True), (GUESSES, False)):
        for field in FIELDS:
            if field in out:
                continue
            for word in words_for.get(field, ()):
                hit = next((i for i, h in enumerate(norm) if i not in used
                            and (h == word if exact else word in h)), None)
                if hit is not None:
                    out[field] = hit
                    used.add(hit)
                    break
    return out


_DATE_FORMATS_MDY = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m.%d.%Y")
_DATE_FORMATS_DMY = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")
_DATE_FORMATS_TEXT = ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y")


def parse_date(value, day_first=False):
    """ISO date string, None for blank, or raise ValueError."""
    v = " ".join(str(value or "").replace(",", ", ").split()).replace(" ,", ",")
    if not v:
        return None
    v = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", v)
    v = v.split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", v) else v  # "2024-03-01 00:00:00"
    for fmt in _DATE_FORMATS_TEXT + (_DATE_FORMATS_DMY if day_first else _DATE_FORMATS_MDY):
        try:
            return datetime.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(v)


def parse_status(value, source=""):
    """One of Minerva's statuses from words writers use, None for blank, or
    raise ValueError. Short words ("no", "out") must match the whole cell."""
    v = " ".join(str(value or "").lower().split())
    if not v:
        return None
    preset = PRESETS.get(source, {}).get("statuses", {})
    if v in preset:
        return preset[v]
    for status in submissions.STATUSES:
        if v == status.lower():
            return status
    for status, words in STATUS_WORDS:
        if any(v == w or (len(w) >= 4 and f" {w}" in f" {v}") for w in words):
            return status
    raise ValueError(value)


def parse_cost(value):
    """(amount, currency) from "$3", "3.00", "£2.50", "free"."""
    v = str(value or "").strip()
    if not v or v.lower() in ("free", "none", "no", "n/a", "-", "0"):
        return 0.0, None
    m = re.match(r"^\s*([^\d\s.,-]{1,4})?\s*(\d+(?:[.,]\d{1,2})?)\s*([^\d\s.,-]{1,4})?\s*$", v)
    if not m:
        raise ValueError(v)
    amount = float(m.group(2).replace(",", "."))
    currency = (m.group(1) or m.group(3) or "").strip() or None
    return amount, currency


def _pieces(conn):
    entries, projects = {}, {}
    for r in conn.execute("SELECT id, title, top_folder FROM entries"):
        entries.setdefault(r["title"].casefold(), []).append({"kind": "entry", "id": r["id"], "title": r["title"],
                                                              "category": r["top_folder"]})
    for r in conn.execute("SELECT id, name FROM projects"):
        projects.setdefault(r["name"].casefold(), []).append({"kind": "project", "id": r["id"], "title": r["name"]})
    return entries, projects


def _match(title, entries, projects):
    key = " ".join(title.split()).casefold()
    if not key:
        return None, "No title in this row."
    found = entries.get(key, []) + projects.get(key, [])
    if not found:
        # titles in spreadsheets often carry quotes
        key2 = key.strip("\"'“”‘’ ")
        found = entries.get(key2, []) + projects.get(key2, [])
    if len(found) == 1:
        return found[0], None
    if not found:
        return None, "No entry or project has this title."
    return None, f"{len(found)} entries or projects have this title; choose one."


def plan(conn, data, mapping, day_first=False, overrides=None, source=""):
    """Read the file and say what each row would become. `overrides` maps
    a row number to {"kind", "id"} for rows the writer matched by hand, or
    to {"skip": true}. A row already in Minerva whose status or response
    date has moved on becomes an "update"."""
    source = source if source in PRESETS else ""
    rows = read_csv(data)
    headings, body = rows[0], rows[1:]
    try:
        mapping = {f: int(c) for f, c in (mapping or {}).items() if f in FIELDS and c not in (None, "")}
    except (TypeError, ValueError):
        raise SubImportError("Choose a column for each field, or leave it out.") from None
    if any(c < 0 or c >= len(headings) for c in mapping.values()):
        raise SubImportError("One of the chosen columns isn't in this file.")
    for need in ("piece", "venue"):
        if need not in mapping:
            raise SubImportError(f'Choose the column that holds "{FIELD_LABELS[need]}".')
    overrides = {int(k): v for k, v in (overrides or {}).items()}
    entries, projects = _pieces(conn)
    existing = {(r["kind"], r["entry_id"] or r["project_id"], r["venue"].casefold(), r["submitted_on"] or ""): r
                for r in submissions.search(conn, {})}
    seen = set()
    out = []
    for n, row in enumerate(body, start=2):
        cell = lambda f: row[mapping[f]].strip() if f in mapping and mapping[f] < len(row) else ""  # noqa: E731
        item = {"row": n, "title": cell("piece"), "venue": " ".join(cell("venue").split()), "problems": []}
        ov = overrides.get(n) or {}
        if ov.get("skip"):
            item.update(state="skipped", reason="You chose to skip this row.")
            out.append(item)
            continue
        if ov.get("kind") in ("entry", "project") and ov.get("id"):
            table = "entries" if ov["kind"] == "entry" else "projects"
            col = "title" if ov["kind"] == "entry" else "name"
            r = conn.execute(f"SELECT id, {col} AS title FROM {table} WHERE id = ?", (int(ov["id"]),)).fetchone()
            piece, why = (({"kind": ov["kind"], "id": r["id"], "title": r["title"]}, None) if r
                          else (None, "The entry you chose isn't in the library any more."))
        else:
            piece, why = _match(item["title"], entries, projects)
        item["piece"] = piece
        if why:
            item["problems"].append(why)
        if not item["venue"]:
            item["problems"].append("No venue in this row.")
        rec = {"venue": item["venue"], "notes": cell("notes")}
        for f, label in (("submitted_on", "date submitted"), ("decided_on", "response date"), ("deadline", "deadline")):
            try:
                rec[f] = parse_date(cell(f), day_first)
            except ValueError:
                item["problems"].append(f'Can\'t read the {label} "{cell(f)}".')
                rec[f] = None
        try:
            rec["status"] = parse_status(cell("status"), source) or ("Submitted" if rec["submitted_on"] else "Planned")
            raw = " ".join(cell("status").split())
            if source and raw and raw.lower() != rec["status"].lower():
                # keep the service's own word ("Form Rejection") in the notes
                said = f'{PRESETS[source]["label"]}: {raw}'
                rec["notes"] = f'{rec["notes"]}\n{said}' if rec["notes"] else said
        except ValueError:
            item["problems"].append(f'Can\'t tell what status "{cell("status")}" means.')
            rec["status"] = None
        try:
            rec["cost"], cur = parse_cost(cell("cost"))
            if cur:
                rec["currency"] = cur
        except ValueError:
            item["problems"].append(f'Can\'t read the fee "{cell("cost")}".')
        rd = cell("response_days")
        if rd:
            m = re.match(r"^\s*(\d+)", rd)
            if m:
                rec["response_days"] = int(m.group(1))
            else:
                item["problems"].append(f'Can\'t read the expected response "{rd}".')
        item["record"] = rec
        if item["problems"]:
            item["state"] = "unmatched" if piece is None and len(item["problems"]) == 1 and why else "problem"
            item["reason"] = " ".join(item["problems"])
        else:
            key = (piece["kind"], piece["id"], rec["venue"].casefold(), rec["submitted_on"] or "")
            old = existing.get(key) or _near(existing, key)
            change = _changes(old, rec) if old else None
            if old and change and key not in seen:
                seen.add(key)
                item.update(state="update", update_id=old["id"], changes=change["fields"], reason=change["text"])
            elif old:
                item.update(state="duplicate", reason="This submission is already in Minerva.")
            elif key in seen:
                item.update(state="duplicate", reason="The same submission appears earlier in this file.")
            else:
                seen.add(key)
                item["state"] = "ready"
                if rec["status"] != "Planned" and not rec["submitted_on"]:
                    item["reason"] = "No date submitted, so today's date will be used."
        out.append(item)
    counts = {}
    for i in out:
        counts[i["state"]] = counts.get(i["state"], 0) + 1
    return {"headings": headings, "mapping": mapping, "rows": out, "counts": counts, "source": source,
            "sources": sources(), "sample": body[:5], "fields": [{"id": f, "label": FIELD_LABELS[f]} for f in FIELDS]}


def _near(existing, key):
    """The record a row means when its date doesn't match exactly: with no
    date, the one submission of that piece to that venue still waiting;
    with a date, the one sent within a week of it."""
    kind, pid, venue, sent = key
    same = [r for k, r in existing.items() if k[:3] == (kind, pid, venue)]
    if not sent:
        waiting = [r for r in same if r["status"] in ("Planned",) + submissions.WAITING]
        return waiting[0] if len(waiting) == 1 else None
    day = datetime.date.fromisoformat(sent)
    close = [r for r in same if r["submitted_on"]
             and abs((datetime.date.fromisoformat(r["submitted_on"]) - day).days) <= 7]
    return close[0] if len(close) == 1 else None


def _changes(old, rec):
    """What a newer export says about a submission already in Minerva: a
    later status or a response date, never an older one."""
    fields, said = {}, []
    order = {"Planned": 0, "Submitted": 1, "Shortlisted": 2, "Accepted": 3, "Declined": 3, "Withdrawn": 3}
    new = rec.get("status")
    if new and new != old["status"] and order.get(new, 0) >= order.get(old["status"], 0):
        fields["status"] = new
        said.append(f'status {old["status"]} to {new}')
    if rec.get("decided_on") and rec["decided_on"] != old.get("decided_on") and (fields.get("status") or old["status"]) in (
            "Accepted", "Declined", "Withdrawn"):
        fields["decided_on"] = rec["decided_on"]
        said.append(f'response date {rec["decided_on"]}')
    if not fields:
        return None
    return {"fields": fields, "text": "Updates the " + " and ".join(said) + "."}


def preview(conn, data, mapping=None, day_first=False, overrides=None, source=None, name=""):
    """The first look at a file: headings, a guessed mapping and the plan.
    source None means work it out from the headings."""
    rows = read_csv(data)
    if source is None:
        source = detect_source(rows[0], name)
    if mapping is None:
        mapping = guess_mapping(rows[0], source)
    if "piece" not in mapping or "venue" not in mapping:
        return {"headings": rows[0], "mapping": mapping, "rows": [], "counts": {}, "sample": rows[1:6],
                "source": source, "sources": sources(),
                "fields": [{"id": f, "label": FIELD_LABELS[f]} for f in FIELDS], "needs_mapping": True}
    return plan(conn, data, mapping, day_first, overrides, source)


def run(conn, data, mapping, day_first=False, overrides=None, source=""):
    """Save every ready row and apply every update. Returns the plan with
    what was saved."""
    p = plan(conn, data, mapping, day_first, overrides, source)
    created = updated = 0
    for item in p["rows"]:
        if item["state"] == "update":
            try:
                submissions.update(conn, item["update_id"], item["changes"])
            except submissions.SubmissionError as e:
                item.update(state="problem", reason=str(e))
                continue
            item["state"] = "updated"
            updated += 1
            continue
        if item["state"] != "ready":
            continue
        body = dict(item["record"])
        body["entry_id" if item["piece"]["kind"] == "entry" else "project_id"] = item["piece"]["id"]
        try:
            submissions.create(conn, body)
        except submissions.SubmissionError as e:
            item.update(state="problem", reason=str(e))
            continue
        item["state"] = "imported"
        created += 1
    p["imported"] = created
    p["updated"] = updated
    p["not_imported"] = [i for i in p["rows"] if i["state"] not in ("imported", "updated")]
    return p

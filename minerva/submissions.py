"""Submission records: where an entry or a project was sent, what it cost,
the dates, and how it went.

Records live in Minerva's index (they have no natural home in a filename).
Each one belongs to exactly one entry or one project, and keeps that piece's
title as it was, so a record still reads sensibly if the entry is later
renamed outside Minerva or the project is deleted.
"""

import datetime

STATUSES = ("Planned", "Submitted", "Shortlisted", "Accepted", "Declined", "Withdrawn")
WAITING = ("Submitted", "Shortlisted")
FIELDS = ("venue", "cost", "currency", "submitted_on", "deadline", "response_days", "status",
          "decided_on", "notes")


class SubmissionError(Exception):
    user_facing = True


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id INTEGER,
        project_id INTEGER,
        piece_title TEXT NOT NULL,
        venue TEXT NOT NULL,
        cost REAL DEFAULT 0,
        currency TEXT DEFAULT '$',
        submitted_on TEXT,
        deadline TEXT,
        response_days INTEGER,
        status TEXT NOT NULL DEFAULT 'Submitted',
        decided_on TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        CHECK ((entry_id IS NULL) != (project_id IS NULL)))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS venues (
        name TEXT PRIMARY KEY COLLATE NOCASE,
        website TEXT,
        reading_periods TEXT,
        cost REAL,
        currency TEXT,
        response_days INTEGER,
        notes TEXT,
        updated_at TEXT)""")
    if "max_lines" not in [r["name"] for r in conn.execute("PRAGMA table_info(venues)")]:
        conn.execute("ALTER TABLE venues ADD COLUMN max_lines INTEGER")


def _date(value, label):
    if value in (None, ""):
        return None
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise SubmissionError(f"{label} isn't a date.") from None


def _clean(body, partial=False):
    out = {}
    if not partial or "venue" in body:
        venue = " ".join(str(body.get("venue") or "").split())
        if not venue:
            raise SubmissionError("Say where it was submitted.")
        out["venue"] = venue[:200]
    if "cost" in body or not partial:
        try:
            cost = float(body.get("cost") or 0)
        except (TypeError, ValueError):
            raise SubmissionError("The fee should be a number.") from None
        if cost < 0:
            raise SubmissionError("The fee can't be negative.")
        out["cost"] = round(cost, 2)
    if "currency" in body or not partial:
        out["currency"] = (str(body.get("currency") or "$").strip() or "$")[:4]
    for key, label in (("submitted_on", "The submitted date"), ("deadline", "The deadline"),
                       ("decided_on", "The response date")):
        if key in body or not partial:
            out[key] = _date(body.get(key), label)
    if "response_days" in body or not partial:
        rd = body.get("response_days")
        if rd in (None, ""):
            out["response_days"] = None
        else:
            try:
                out["response_days"] = int(rd)
            except (TypeError, ValueError):
                raise SubmissionError("Expected response time should be a number of days.") from None
            if out["response_days"] < 0:
                raise SubmissionError("Expected response time can't be negative.")
    if "status" in body or not partial:
        status = body.get("status") or "Submitted"
        if status not in STATUSES:
            raise SubmissionError("Unknown status.")
        out["status"] = status
    if "notes" in body or not partial:
        out["notes"] = str(body.get("notes") or "")[:4000]
    return out


def create(conn, body):
    entry_id, project_id = body.get("entry_id"), body.get("project_id")
    if bool(entry_id) == bool(project_id):
        raise SubmissionError("A submission belongs to one entry or one project.")
    if entry_id:
        row = conn.execute("SELECT title FROM entries WHERE id = ?", (entry_id,)).fetchone()
    else:
        row = conn.execute("SELECT name AS title FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise SubmissionError("That entry or project no longer exists.")
    data = _clean(body)
    if data["status"] != "Planned" and not data["submitted_on"]:
        data["submitted_on"] = datetime.date.today().isoformat()
    cur = conn.execute(
        f"""INSERT INTO submissions (entry_id, project_id, piece_title, created_at, {", ".join(data)})
            VALUES (?, ?, ?, ?, {", ".join("?" for _ in data)})""",
        (entry_id or None, project_id or None, row["title"],
         datetime.datetime.now().isoformat(timespec="seconds"), *data.values()))
    conn.commit()
    return get(conn, cur.lastrowid)


def update(conn, sub_id, body):
    if get(conn, sub_id) is None:
        raise SubmissionError("That submission no longer exists.")
    data = _clean(body, partial=True)
    if data:
        conn.execute(f"UPDATE submissions SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                     (*data.values(), sub_id))
        conn.commit()
    return get(conn, sub_id)


def delete(conn, sub_id):
    conn.execute("DELETE FROM submissions WHERE id = ?", (sub_id,))
    conn.commit()


def still_waiting_elsewhere(conn, sub_id):
    """The piece's other submissions still waiting for an answer, for when
    this one is accepted (so the other venues can be told)."""
    s = get(conn, sub_id)
    if s is None:
        raise SubmissionError("That submission no longer exists.")
    key = "entry_id" if s["kind"] == "entry" else "project_id"
    return [r for r in search(conn, {key: s[key]}) if r["id"] != s["id"] and r["status"] in WAITING]


def withdraw(conn, ids, today=None):
    """Mark waiting submissions Withdrawn, dated today. Others are left alone."""
    today = (today or datetime.date.today()).isoformat()
    done = []
    for sub_id in ids:
        s = get(conn, int(sub_id))
        if s and s["status"] in WAITING:
            conn.execute("UPDATE submissions SET status = 'Withdrawn', decided_on = ? WHERE id = ?",
                         (today, s["id"]))
            done.append(s["id"])
    conn.commit()
    return done


def move_entry(conn, from_id, to_id):
    """When one entry is merged into another, its submissions follow it."""
    conn.execute("UPDATE submissions SET entry_id = ? WHERE entry_id = ?", (to_id, from_id))


SELECT = """
    SELECT s.*, e.title AS entry_title, e.top_folder AS category, e.project_tag AS entry_project,
           p.name AS project_name, p.tag AS project_tag
    FROM submissions s
    LEFT JOIN entries e ON e.id = s.entry_id
    LEFT JOIN projects p ON p.id = s.project_id
"""


def _shape(r, today):
    d = dict(r)
    is_entry = d["entry_id"] is not None
    current = d["entry_title"] if is_entry else d["project_name"]
    d["kind"] = "entry" if is_entry else "project"
    d["title"] = current or d["piece_title"]
    d["missing"] = current is None
    d["project"] = d["entry_project"] if is_entry else d["project_tag"]
    expected = None
    if d["submitted_on"] and d["response_days"] is not None:
        expected = (datetime.date.fromisoformat(d["submitted_on"])
                    + datetime.timedelta(days=d["response_days"])).isoformat()
    d["expected_by"] = expected
    d["overdue"] = bool(expected and d["status"] in WAITING and expected < today)
    for k in ("entry_title", "project_name", "entry_project", "project_tag"):
        d.pop(k)
    return d


def get(conn, sub_id):
    r = conn.execute(SELECT + " WHERE s.id = ?", (sub_id,)).fetchone()
    return _shape(r, datetime.date.today().isoformat()) if r else None


def search(conn, f=None):
    """Filters (all optional): q (title, venue or notes), status, venue,
    category, project (tag), kind (entry/project), entry_id, project_id,
    open (only ones still waiting or planned), date_from/date_to (on the
    submitted date), year."""
    f = f or {}
    where, args = [], []
    if f.get("entry_id"):
        where.append("s.entry_id = ?"); args.append(int(f["entry_id"]))
    if f.get("project_id"):
        where.append("s.project_id = ?"); args.append(int(f["project_id"]))
    if f.get("status"):
        where.append("s.status = ?"); args.append(f["status"])
    if f.get("open"):
        where.append(f"s.status IN ({', '.join('?' for _ in WAITING)}, 'Planned')"); args.extend(WAITING)
    if f.get("venue"):
        where.append("s.venue = ? COLLATE NOCASE"); args.append(f["venue"])
    if f.get("category"):
        where.append("e.top_folder = ?"); args.append(f["category"])
    if f.get("project"):
        where.append("(e.project_tag = ? OR p.tag = ?)"); args.extend([f["project"], f["project"]])
    if f.get("kind") in ("entry", "project"):
        where.append("s.entry_id IS NOT NULL" if f["kind"] == "entry" else "s.project_id IS NOT NULL")
    if f.get("date_from"):
        where.append("s.submitted_on >= ?"); args.append(_date(f["date_from"], "From"))
    if f.get("date_to"):
        where.append("s.submitted_on <= ?"); args.append(_date(f["date_to"], "To"))
    if f.get("q"):
        like = f"%{f['q']}%"
        where.append("(COALESCE(e.title, p.name, s.piece_title) LIKE ? OR s.venue LIKE ? OR s.notes LIKE ?)")
        args.extend([like, like, like])
    sql = SELECT + (" WHERE " + " AND ".join(where) if where else "") + \
        " ORDER BY COALESCE(s.submitted_on, s.deadline, s.created_at) DESC, s.id DESC"
    today = datetime.date.today().isoformat()
    return [_shape(r, today) for r in conn.execute(sql, args).fetchall()]


def summary(rows):
    """Totals for whatever rows are on screen."""
    decided = [r for r in rows if r["status"] in ("Accepted", "Declined")]
    accepted = sum(1 for r in decided if r["status"] == "Accepted")
    fees = {}
    for r in rows:
        if r["cost"]:
            fees[r["currency"]] = round(fees.get(r["currency"], 0) + r["cost"], 2)
    return {
        "count": len(rows),
        "waiting": sum(1 for r in rows if r["status"] in WAITING),
        "overdue": sum(1 for r in rows if r["overdue"]),
        "accepted": accepted,
        "acceptance_rate": round(accepted / len(decided), 3) if decided else None,
        "fees": fees,
    }


def venues(conn):
    return [r["venue"] for r in conn.execute(
        "SELECT venue FROM submissions GROUP BY venue COLLATE NOCASE ORDER BY venue COLLATE NOCASE")]


# ---- venues ---------------------------------------------------------------
#
# A venue is known once anything has been submitted there or its notes have
# been saved. Notes are kept by name (case doesn't matter); the history comes
# from the submission records themselves.

VENUE_FIELDS = ("website", "reading_periods", "cost", "currency", "response_days", "notes", "max_lines")


def _venue_name(name):
    name = " ".join(str(name or "").split())
    if not name:
        raise SubmissionError("Say which venue.")
    return name[:200]


def _history(conn, name):
    rows = search(conn, {"venue": name})
    decided = [r for r in rows if r["status"] in ("Accepted", "Declined") and r["submitted_on"] and r["decided_on"]]
    waits = sorted((datetime.date.fromisoformat(r["decided_on"])
                    - datetime.date.fromisoformat(r["submitted_on"])).days for r in decided)
    fees = [r for r in rows if r["status"] != "Planned"]
    last_fee = fees[0] if fees else None
    return rows, {
        **summary(rows),
        "median_wait": waits[len(waits) // 2] if waits else None,
        "last_fee": None if last_fee is None else {"cost": last_fee["cost"], "currency": last_fee["currency"]},
        "last_submitted": max((r["submitted_on"] for r in rows if r["submitted_on"]), default=None),
    }


def venue(conn, name):
    """A venue's saved notes, its submissions there and what they add up to.
    "suggested" is what a new submission there should start with: the saved
    fee and response time, or failing those, the last fee paid and the
    usual wait."""
    name = _venue_name(name)
    saved = conn.execute("SELECT * FROM venues WHERE name = ?", (name,)).fetchone()
    rows, stats = _history(conn, name)
    if saved is None and not rows:
        return None
    info = dict(saved) if saved else {"name": rows[0]["venue"], **{k: None for k in VENUE_FIELDS}}
    suggested = {"cost": info["cost"], "currency": info["currency"], "response_days": info["response_days"]}
    if suggested["cost"] is None and stats["last_fee"]:
        suggested.update(stats["last_fee"])
    if suggested["response_days"] is None:
        suggested["response_days"] = stats["median_wait"]
    return {**info, "saved": saved is not None, "history": rows, "stats": stats, "suggested": suggested}


def save_venue(conn, body):
    name = _venue_name(body.get("name"))
    data = {}
    for key in ("website", "reading_periods", "notes"):
        data[key] = str(body.get(key) or "").strip()[:4000 if key == "notes" else 500] or None
    cost = body.get("cost")
    if cost in (None, ""):
        data["cost"] = None
    else:
        data["cost"] = _clean({"cost": cost}, partial=True)["cost"]
    data["currency"] = (str(body.get("currency") or "").strip() or None)
    data["currency"] = data["currency"][:4] if data["currency"] else None
    rd = body.get("response_days")
    data["response_days"] = None if rd in (None, "") else _clean({"response_days": rd}, partial=True)["response_days"]
    ml = body.get("max_lines")
    try:
        data["max_lines"] = None if ml in (None, "") else int(ml)
    except (TypeError, ValueError):
        raise SubmissionError("The line limit should be a whole number of lines.") from None
    if data["max_lines"] is not None and data["max_lines"] < 1:
        raise SubmissionError("The line limit should be at least 1.")
    # keep the spelling already in use when a record exists under another case
    used = conn.execute("SELECT venue FROM submissions WHERE venue = ? COLLATE NOCASE LIMIT 1", (name,)).fetchone()
    existing = conn.execute("SELECT name FROM venues WHERE name = ?", (name,)).fetchone()
    stored = existing["name"] if existing else used["venue"] if used else name
    conn.execute(
        f"""INSERT INTO venues (name, {", ".join(VENUE_FIELDS)}, updated_at)
            VALUES (?, {", ".join("?" for _ in VENUE_FIELDS)}, ?)
            ON CONFLICT(name) DO UPDATE SET {", ".join(f"{k} = excluded.{k}" for k in VENUE_FIELDS)},
                updated_at = excluded.updated_at""",
        (stored, *(data[k] for k in VENUE_FIELDS), datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return venue(conn, stored)


def list_venues(conn):
    """Every venue with notes or submissions, with its totals."""
    names = {r["name"].casefold(): r["name"] for r in conn.execute("SELECT name FROM venues")}
    for v in venues(conn):
        names.setdefault(v.casefold(), v)
    out = []
    for name in sorted(names.values(), key=str.casefold):
        v = venue(conn, name)
        out.append({k: v[k] for k in ("name", "saved", "website", "reading_periods", "suggested", "stats")})
    return out

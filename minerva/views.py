"""Views: generated overviews of the library.

Timeline is the general form of a writer's chronology. "By journal" lists
each scanned journal in date order with the dates it covers, how many
entries it holds and where they were filed, and who it mentions most (from
People). "By year" groups every library entry by the year it was written:
the journal's date for an entry filed from a scan, otherwise the day its
oldest file was saved. None of that needs a model.

"Summarize" adds, per journal, its major events, themes, places, people and
projects, from one text-only request to the organizing model (more for a
very long journal). The answer is kept until the Master changes.

"Save as text" writes the timeline to "Timeline (Minerva).txt" in the
scans folder (or the library folder when there's no scans folder). A
previous copy is moved to .minerva/backups first; any other file, such as
an existing Chronology.txt, is never touched.

People histories follow each person in People through the entries that
mention them, in date order, with the sentences that name them. "Write
history" asks the organizing model to turn those passages into a short
account; it's kept until the person's mentions or names change. They are
saved to "People Histories (Minerva).txt" only when asked, the same way.
"""

import datetime
import hashlib
import json
import os
import re
import shutil

from . import ai, core, images, organizing, people, scanning

TIMELINE_FILE = "Timeline (Minerva).txt"
NOTE_KEYS = ("events", "themes", "places", "people", "projects")
LIST_LIMIT = 12

SUMMARY_SYSTEM = """You read part or all of a writer's transcribed journal and summarize it for their own timeline of their life and work.

Answer with a JSON object and nothing else:
{"events": ["<major things that happened, each a short phrase, with a date if the journal gives one>"],
 "themes": ["<recurring subjects or moods, a few words each>"],
 "places": ["<places that matter in it>"],
 "people": ["<the people who matter most in it>"],
 "projects": ["<writing or other projects the writer works on>"]}

Keep each list to the dozen most important items or fewer. Use the journal's own words for names. Leave a list empty rather than guess."""


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS timeline_notes (
        source TEXT PRIMARY KEY, version TEXT, notes TEXT, ran_at TEXT)""")


# --------------------------------------------------------------------------
# Building the timeline
# --------------------------------------------------------------------------

def _journal_dates():
    """{source: {entry_num: iso date}} for every Master, and the parsed
    entries of each."""
    dates, parsed = {}, {}
    for s in scanning.list_sources()["sources"]:
        if not s["has_master"]:
            continue
        path = scanning.master_path(s["name"])
        entries = scanning.parse_master(scanning._read(path))["entries"]
        parsed[s["name"]] = (entries, scanning.file_version(path))
        dates[s["name"]] = {e["num"]: images.iso_date(e["date"]) for e in entries}
    return dates, parsed


def _top_people(conn, source, limit=5):
    people.ensure_tables(conn)
    return [r["name"] for r in conn.execute(
        "SELECT p.name, COUNT(*) AS n FROM person_mentions m JOIN people p ON p.id = m.person_id "
        "WHERE m.source = ? GROUP BY p.id ORDER BY n DESC, p.name LIMIT ?", (source, limit))]


def timeline(conn):
    ensure_tables(conn)
    dates, parsed = _journal_dates()
    notes = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM timeline_notes")}
    rows = conn.execute("SELECT id, title, top_folder, word_count, started, source_journal, source_entry_num "
                        "FROM entries").fetchall()

    filed = {}
    for r in rows:
        if r["source_journal"]:
            filed.setdefault(r["source_journal"], {}).setdefault(r["top_folder"], 0)
            filed[r["source_journal"]][r["top_folder"]] += 1
    journals = []
    for name, (entries, version) in parsed.items():
        isos = sorted(d for d in dates[name].values() if d)
        note = notes.get(name)
        journals.append({
            "name": name, "entries": len(entries), "first": isos[0] if isos else "",
            "last": isos[-1] if isos else "", "dated": len(isos),
            "filed": dict(sorted(filed.get(name, {}).items())), "people": _top_people(conn, name),
            "notes": json.loads(note["notes"]) if note else None,
            "notes_current": bool(note) and note["version"] == version,
        })
    journals.sort(key=lambda j: (j["first"] or "9999", j["name"].lower()))

    years = {}
    for r in rows:
        when = ""
        if r["source_journal"] and r["source_entry_num"] is not None:
            when = dates.get(r["source_journal"], {}).get(r["source_entry_num"], "")
        when = when or r["started"] or ""
        y = years.setdefault(when[:4] or "Undated", {"year": when[:4] or "Undated", "count": 0, "words": 0,
                                                     "categories": {}, "entries": []})
        y["count"] += 1
        y["words"] += r["word_count"] or 0
        y["categories"][r["top_folder"]] = y["categories"].get(r["top_folder"], 0) + 1
        y["entries"].append({"id": r["id"], "title": r["title"], "category": r["top_folder"], "date": when,
                             "journal": r["source_journal"] or ""})
    for y in years.values():
        y["categories"] = dict(sorted(y["categories"].items(), key=lambda kv: -kv[1]))
        y["entries"].sort(key=lambda e: (e["date"], e["title"].lower()))
    return {"journals": journals, "years": sorted(years.values(), key=lambda y: y["year"])}


# --------------------------------------------------------------------------
# Summaries (AI, opt-in)
# --------------------------------------------------------------------------

def estimate(source, model):
    return people.estimate(source, model)


def _merge_notes(parts):
    out = {k: [] for k in NOTE_KEYS}
    for part in parts:
        for k in NOTE_KEYS:
            for item in part.get(k) or []:
                item = " ".join(str(item).split())[:200]
                if item and item.lower() not in {x.lower() for x in out[k]}:
                    out[k].append(item)
    return {k: v[:LIST_LIMIT * 2] for k, v in out.items()}


def summarize(conn, source, settings, key, progress=None, cancelled=None):
    ensure_tables(conn)
    entries, version = people._master_entries(source)
    batches = list(people._batches(entries))
    parts = []
    for i, batch in enumerate(batches):
        if cancelled and cancelled():
            return None
        if progress:
            progress(i, len(batches), f"Reading {source}" + (f", part {i + 1} of {len(batches)}" if len(batches) > 1 else ""))
        prompt = f"The journal is called {source!r}.\n\n" + "\n\n".join(batch)
        data = organizing._json_from(ai.complete(settings["provider"], settings["model"], key,
                                                 SUMMARY_SYSTEM, prompt, max_tokens=4000), "{")
        if isinstance(data, dict):
            parts.append(data)
    notes = _merge_notes(parts)
    conn.execute("INSERT OR REPLACE INTO timeline_notes VALUES (?, ?, ?, ?)",
                 (source, version, json.dumps(notes), datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return {"source": source, "notes": notes}


# --------------------------------------------------------------------------
# Saving as text
# --------------------------------------------------------------------------

def _range(first, last):
    if not first:
        return "undated"
    return first if first == last else f"{first} to {last}"


def timeline_text(data):
    today = datetime.date.today().isoformat()
    lines = ["TIMELINE", f"Made by Minerva on {today}. Minerva rewrites this file when you save the timeline again.", ""]
    if data["journals"]:
        lines += ["=" * 60, "JOURNALS", "=" * 60, ""]
        for j in data["journals"]:
            lines.append(f"{j['name']} ({_range(j['first'], j['last'])})")
            lines.append(f"  {j['entries']} entries" + (
                "; filed: " + ", ".join(f"{n} {c}" for c, n in j["filed"].items()) if j["filed"] else ""))
            if j["people"]:
                lines.append("  Mentions most: " + ", ".join(j["people"]))
            for k in NOTE_KEYS:
                items = (j["notes"] or {}).get(k) or []
                if items:
                    lines.append(f"  {k.capitalize()}:")
                    lines += [f"    - {x}" for x in items]
            lines.append("")
    lines += ["=" * 60, "BY YEAR", "=" * 60, ""]
    for y in data["years"]:
        cats = ", ".join(f"{n} {c}" for c, n in y["categories"].items())
        lines.append(f"{y['year']}: {y['count']} entries, {y['words']:,} words ({cats})")
        lines += [f"  {e['date'] or '          '}  {e['title']} [{e['category']}]" for e in y["entries"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_text(conn):
    return _write_generated(TIMELINE_FILE, timeline_text(timeline(conn)))


# --------------------------------------------------------------------------
# People histories
# --------------------------------------------------------------------------

HISTORIES_FILE = "People Histories (Minerva).txt"
EXCERPT_CHARS = 400
PROMPT_TOKENS_HISTORY = 250

HISTORY_SYSTEM = """You help a writer see the history of one person in their life, as their own journals tell it.

You get the person's name and, in date order, the passages from the journal entries that mention them. Write that person's history: what happened between them and the writer, in date order, in a few short paragraphs. Use only what the passages say; where they leave a gap, leave it rather than invent. Refer to the writer as "you". Plain text, no headings or lists."""


def _ensure_history_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS person_histories (
        person_id INTEGER PRIMARY KEY, basis TEXT, text TEXT, ran_at TEXT)""")


def _sentences(text):
    flat = " ".join((text or "").split())
    return [s for s in re.split(r"(?<=[.!?])\s+", flat) if s]


def excerpt(body, names):
    """The sentences of an entry that name the person, or its opening."""
    pats = [re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)", re.IGNORECASE) for n in names if n]
    hits = [s for s in _sentences(body) if any(p.search(s) for p in pats)]
    text = " … ".join(hits) if hits else " ".join((body or "").split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def _bodies(sources):
    out = {}
    for name in sources:
        try:
            entries, _ = people._master_entries(name)
        except (people.PeopleError, scanning.ScanError):
            continue
        out.update({(name, e["num"]): e["body"] for e in entries})
    return out


def _basis(person):
    key = json.dumps([person["name"], sorted(person["aliases"]),
                      [[m["source"], m["num"]] for m in person["mentions"]]])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def histories(conn):
    """Everyone in People, with whether their written history is current."""
    _ensure_history_table(conn)
    written = {r["person_id"]: dict(r) for r in conn.execute("SELECT * FROM person_histories")}
    out = []
    for p in people.list_people(conn):
        w = written.get(p["id"])
        out.append({k: p[k] for k in ("id", "name", "aliases", "count", "first", "last")}
                   | {"written": bool(w), "current": bool(w) and w["basis"] == _basis(p)})
    return out


def history(conn, pid):
    _ensure_history_table(conn)
    person = next((p for p in people.list_people(conn) if p["id"] == int(pid)), None)
    if person is None:
        raise people.PeopleError("That person isn't in People any more. Reload and try again.")
    bodies = _bodies(person["sources"])
    names = [person["name"], *person["aliases"]]
    for m in person["mentions"]:
        m["excerpt"] = excerpt(bodies.get((m["source"], m["num"]), ""), names)
    row = conn.execute("SELECT * FROM person_histories WHERE person_id = ?", (person["id"],)).fetchone()
    person["text"] = row["text"] if row else ""
    person["ran_at"] = row["ran_at"] if row else None
    person["current"] = bool(row) and row["basis"] == _basis(person)
    return person


def _history_prompt(person):
    lines = [f"The person: {person['name']}" + (f" (also called {', '.join(person['aliases'])})" if person["aliases"] else "")]
    if person["about"]:
        lines.append(f"Who they are, briefly: {person['about']}")
    lines.append("")
    for m in person["mentions"]:
        lines.append(f"[{m['date'] or 'undated'}, {m['source']} entry {m['num']}] {m['excerpt']}")
    return "\n".join(lines)


def estimate_history(conn, pid, model):
    person = history(conn, pid)
    tin = len(_history_prompt(person)) // 4 + PROMPT_TOKENS_HISTORY
    tout = 600
    price = ai.PRICES.get(model)
    return {"mentions": person["count"], "input_tokens": tin, "output_tokens": tout,
            "cost": round((tin * price[0] + tout * price[1]) / 1e6, 2) if price else None}


def write_history(conn, pid, settings, key):
    person = history(conn, pid)
    text = ai.complete(settings["provider"], settings["model"], key, HISTORY_SYSTEM,
                       _history_prompt(person), max_tokens=2000).strip()
    if not text:
        raise ai.ProviderError("The model sent back an empty history. Try again.")
    conn.execute("INSERT OR REPLACE INTO person_histories VALUES (?, ?, ?, ?)",
                 (person["id"], _basis(person), text, datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return history(conn, pid)


def histories_text(conn):
    today = datetime.date.today().isoformat()
    lines = ["PEOPLE HISTORIES", f"Made by Minerva on {today} from the journals' People list. "
             "Minerva rewrites this file when you save it again.", ""]
    for p in histories(conn):
        h = history(conn, p["id"])
        lines += ["=" * 60, h["name"].upper() + (f" (also {', '.join(h['aliases'])})" if h["aliases"] else ""), "=" * 60]
        lines.append(f"{h['count']} mentions, {_range(h['first'], h['last'])}")
        if h["about"]:
            lines.append(h["about"])
        lines.append("")
        if h["text"]:
            lines += [h["text"], ""]
        lines += [f"  {m['iso'] or m['date'] or 'undated'}  {m['source']} {m['num']}: {m['excerpt']}" for m in h["mentions"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_generated(filename, text):
    folder = core.JOURNAL_SCANS_DIR if os.path.isdir(core.JOURNAL_SCANS_DIR) else core.ARCHIVE_ROOT
    path = os.path.join(folder, filename)
    if os.path.exists(path):
        backups = os.path.join(core.META_DIR, "backups")
        os.makedirs(backups, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
        stem = os.path.splitext(filename)[0]
        shutil.move(path, os.path.join(backups, f"{stem} ({stamp}).txt"))
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(text)
    return os.path.relpath(path, core.ARCHIVE_ROOT).replace(os.sep, "/")


def save_histories(conn):
    if not histories(conn):
        raise people.PeopleError("There's no one in People yet.")
    return _write_generated(HISTORIES_FILE, histories_text(conn))

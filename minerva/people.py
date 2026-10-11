"""People: everyone the transcribed journals mention.

"Find people" sends a source's Master to the organizing model as text (one
call for most journals; a very long one is split) and asks for the people it
names, with the entries each appears in. The answers are kept in the index:
a person, the names they go by, and where they're mentioned. Two names for
the same person can be merged, and a later run on any source keeps that
merge, because every name a person has gone by stays pointed at them.

Nothing is written to the library; this lives in .minerva/index.db only.
"""

import datetime
import os

from . import ai, images, organizing, scanning

BATCH_CHARS = 80_000
PROMPT_TOKENS = 500
OUTPUT_TOKENS_PER_ENTRY = 40

FIND_SYSTEM = """You read a writer's transcribed journal and list the people it mentions.

Include every person the writer names or refers to by a clear title that works as a name (for example "Grandma", "Dr. Patel", "my sister Ana"). Skip the writer themselves, and skip public figures who are only mentioned in passing (an author quoted, a celebrity in the news).

When the same person appears under different forms (a nickname, a misspelling, first name only), list them once, under the fullest form the journal uses, with the other forms in "also".

Answer with a JSON array and nothing else:
[{"name": "<fullest form>", "also": ["<other forms used>"], "entries": [<entry numbers they appear in>], "about": "<a few words on who they are to the writer, from the text, or empty>"}]"""


class PeopleError(ValueError):
    user_facing = True


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, about TEXT NOT NULL DEFAULT '', created_at TEXT);
        CREATE TABLE IF NOT EXISTS person_aliases (
            alias TEXT PRIMARY KEY COLLATE NOCASE, person_id INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS person_mentions (
            person_id INTEGER NOT NULL, source TEXT NOT NULL, entry_num INTEGER NOT NULL,
            PRIMARY KEY (person_id, source, entry_num));
        CREATE TABLE IF NOT EXISTS people_runs (
            source TEXT PRIMARY KEY, version TEXT, ran_at TEXT, found INTEGER);
    """)


def _clean(name):
    return " ".join(str(name or "").split())[:80]


# --------------------------------------------------------------------------
# Finding people
# --------------------------------------------------------------------------

def _master_entries(source):
    path = scanning.master_path(source)
    text = scanning._read(path) if os.path.isfile(path) else ""
    if not text:
        raise PeopleError(f"{source} doesn't have a Master yet.")
    return scanning.parse_master(text)["entries"], scanning.file_version(path)


def _entry_text(e):
    head = f"ENTRY {e['num']}" + (f" — {e['title']}" if e["title"] else "")
    if e["date"] and e["date"].lower() != "none":
        head += f" ({e['date']})"
    return f"{head}\n{e['body'].strip()}"


def _batches(entries):
    batch, size = [], 0
    for e in entries:
        text = _entry_text(e)
        if batch and size + len(text) > BATCH_CHARS:
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += len(text) + 2
    if batch:
        yield batch


def estimate(source, model):
    entries, _ = _master_entries(source)
    batches = list(_batches(entries))
    chars = sum(len(t) for b in batches for t in b)
    tin = chars // 4 + PROMPT_TOKENS * len(batches)
    tout = OUTPUT_TOKENS_PER_ENTRY * len(entries)
    price = ai.PRICES.get(model)
    cost = round((tin * price[0] + tout * price[1]) / 1e6, 2) if price else None
    return {"calls": len(batches), "entries": len(entries), "input_tokens": tin,
            "output_tokens": tout, "cost": cost}


def _ask(settings, key, source, batches, progress=None, cancelled=None):
    found = []
    for i, batch in enumerate(batches):
        if cancelled and cancelled():
            return None
        if progress:
            progress(i, len(batches), f"Reading {source}" + (f", part {i + 1} of {len(batches)}" if len(batches) > 1 else ""))
        prompt = f"The journal is called {source!r}.\n\n" + "\n\n".join(batch)
        data = organizing._json_from(ai.complete(settings["provider"], settings["model"], key,
                                                 FIND_SYSTEM, prompt, max_tokens=8000), "[")
        found.extend(d for d in (data if isinstance(data, list) else []) if isinstance(d, dict))
    if progress:
        progress(len(batches), len(batches), "Saving")
    return found


def _person_for(conn, names):
    for n in names:
        row = conn.execute("SELECT person_id FROM person_aliases WHERE alias = ?", (n,)).fetchone()
        if row:
            return row["person_id"]
    return None


def record(conn, source, version, found, valid_nums):
    """Replace a source's mentions with what the model found."""
    ensure_tables(conn)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM person_mentions WHERE source = ?", (source,))
    people = set()
    for item in found:
        name = _clean(item.get("name"))
        if not name:
            continue
        names = [name] + [a for a in (_clean(x) for x in item.get("also") or [] if isinstance(x, str)) if a]
        nums = set()
        for n in item.get("entries") or []:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n in valid_nums:
                nums.add(n)
        if not nums:
            continue
        pid = _person_for(conn, names)
        about = _clean(item.get("about"))[:200] if isinstance(item.get("about"), str) else ""
        if pid is None:
            pid = conn.execute("INSERT INTO people (name, about, created_at) VALUES (?, ?, ?)",
                               (name, about, now)).lastrowid
        elif about:
            conn.execute("UPDATE people SET about = ? WHERE id = ? AND about = ''", (about, pid))
        for n in names:
            conn.execute("INSERT OR IGNORE INTO person_aliases (alias, person_id) VALUES (?, ?)", (n, pid))
        conn.executemany("INSERT OR IGNORE INTO person_mentions VALUES (?, ?, ?)",
                         [(pid, source, n) for n in nums])
        people.add(pid)
    _drop_unmentioned(conn)
    conn.execute("INSERT OR REPLACE INTO people_runs VALUES (?, ?, ?, ?)", (source, version, now, len(people)))
    conn.commit()
    return len(people)


def _drop_unmentioned(conn):
    gone = [r["id"] for r in conn.execute(
        "SELECT id FROM people WHERE id NOT IN (SELECT person_id FROM person_mentions)")]
    for pid in gone:
        conn.execute("DELETE FROM person_aliases WHERE person_id = ?", (pid,))
        conn.execute("DELETE FROM people WHERE id = ?", (pid,))


def find(conn, source, settings, key, progress=None, cancelled=None):
    entries, version = _master_entries(source)
    found = _ask(settings, key, source, list(_batches(entries)), progress, cancelled)
    if found is None:
        return None
    return {"source": source, "people": record(conn, source, version, found, {e["num"] for e in entries})}


# --------------------------------------------------------------------------
# Reading and tidying
# --------------------------------------------------------------------------

def sources(conn):
    """Sources with a Master, and whether people have been found in the
    current version of it."""
    ensure_tables(conn)
    runs = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM people_runs")}
    out = []
    for s in scanning.list_sources()["sources"]:
        if not s["has_master"]:
            continue
        run = runs.get(s["name"])
        version = scanning.file_version(scanning.master_path(s["name"]))
        out.append({"name": s["name"], "entries": s["entries"],
                    "ran_at": run["ran_at"] if run else None, "found": run["found"] if run else None,
                    "current": bool(run) and run["version"] == version})
    return out


def _entry_info(source_names):
    info = {}
    for name in source_names:
        try:
            master = scanning.read_master(name)
        except scanning.ScanError:
            continue
        for e in master["entries"]:
            info[(name, e["num"])] = {"title": e["title"], "date": e["date"], "filed": e["filed"]}
    return info


def list_people(conn):
    ensure_tables(conn)
    rows = conn.execute("SELECT * FROM people").fetchall()
    aliases = {}
    for r in conn.execute("SELECT alias, person_id FROM person_aliases ORDER BY alias"):
        aliases.setdefault(r["person_id"], []).append(r["alias"])
    mentions = {}
    for r in conn.execute("SELECT * FROM person_mentions ORDER BY source, entry_num"):
        mentions.setdefault(r["person_id"], []).append((r["source"], r["entry_num"]))
    info = _entry_info({s for ms in mentions.values() for s, _ in ms})
    out = []
    for p in rows:
        ms = []
        for source, num in mentions.get(p["id"], []):
            e = info.get((source, num), {})
            date = e.get("date") or ""
            ms.append({"source": source, "num": num, "title": e.get("title") or "",
                       "date": "" if date.lower() == "none" else date,
                       "iso": images.iso_date(date), "filed": e.get("filed")})
        isos = sorted(m["iso"] for m in ms if m["iso"])
        out.append({"id": p["id"], "name": p["name"], "about": p["about"],
                    "aliases": [a for a in aliases.get(p["id"], []) if a.lower() != p["name"].lower()],
                    "count": len(ms), "sources": sorted({m["source"] for m in ms}),
                    "first": isos[0] if isos else "", "last": isos[-1] if isos else "",
                    "mentions": sorted(ms, key=lambda m: (m["iso"] or "9999", m["source"], m["num"]))})
    out.sort(key=lambda p: (-p["count"], p["name"].lower()))
    return out


def _person(conn, pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        raise PeopleError("Choose a person.")
    row = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise PeopleError("That person isn't in the list any more. Reload and try again.")
    return row


def merge(conn, keep, others):
    """Fold other people into one; every name they went by now means them."""
    ensure_tables(conn)
    kept = _person(conn, keep)
    others = [o for o in {_person(conn, o)["id"] for o in others} if o != kept["id"]]
    if not others:
        raise PeopleError("Choose at least two people to merge.")
    for oid in others:
        other = _person(conn, oid)
        conn.execute("INSERT OR IGNORE INTO person_mentions SELECT ?, source, entry_num FROM person_mentions "
                     "WHERE person_id = ?", (kept["id"], oid))
        conn.execute("DELETE FROM person_mentions WHERE person_id = ?", (oid,))
        conn.execute("UPDATE person_aliases SET person_id = ? WHERE person_id = ?", (kept["id"], oid))
        conn.execute("INSERT OR IGNORE INTO person_aliases VALUES (?, ?)", (other["name"], kept["id"]))
        if not kept["about"] and other["about"]:
            conn.execute("UPDATE people SET about = ? WHERE id = ?", (other["about"], kept["id"]))
        conn.execute("DELETE FROM people WHERE id = ?", (oid,))
    conn.commit()


def rename(conn, pid, name):
    ensure_tables(conn)
    person = _person(conn, pid)
    name = _clean(name)
    if not name:
        raise PeopleError("Give the person a name.")
    owner = _person_for(conn, [name])
    if owner is not None and owner != person["id"]:
        other = _person(conn, owner)["name"]
        raise PeopleError(f'"{name}" is already a name for {other}. Merge the two instead.')
    conn.execute("UPDATE people SET name = ? WHERE id = ?", (name, person["id"]))
    conn.execute("INSERT OR IGNORE INTO person_aliases VALUES (?, ?)", (name, person["id"]))
    conn.commit()

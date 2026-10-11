"""Project outline: every piece in a project as a card or an outline row,
with a one-line synopsis, a status and notes, plus placeholder slots for
pieces that aren't written yet.

A piece that is an entry keeps its notes in the entry's own notes (see
notes.py); a placeholder keeps its notes here. All of this lives in
.minerva's index. The only time the outline writes to the library is when
the writer asks to start writing a placeholder, which creates that entry's
folder and an empty draft, the same as filing a new entry would.

The outline's order is the project's order: reordering here also sets the
order the project exports in.
"""

import datetime
import os

from . import core, notes

STATUSES = ("idea", "drafting", "revising", "done")


class OutlineError(ValueError):
    user_facing = True


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS outline_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        entry_id INTEGER,
        pos INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL DEFAULT '',
        synopsis TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT,
        UNIQUE (project_id, entry_id))""")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _project(conn, project_id):
    try:
        return core._project_row(conn, int(project_id))
    except (TypeError, ValueError):
        raise OutlineError("That project no longer exists.") from None


def _item(conn, project_id, item_id):
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        raise OutlineError("Choose a piece of the outline.") from None
    row = conn.execute("SELECT * FROM outline_items WHERE id = ? AND project_id = ?",
                       (item_id, project_id)).fetchone()
    if row is None:
        raise OutlineError("That piece isn't in the outline any more. Reload and try again.")
    return row


def _clean_line(text, limit):
    return " ".join(str(text or "").split())[:limit]


def get(conn, project_id):
    """The outline in order. Entries that joined the project since the
    outline was last arranged go at the end, in the project's own order."""
    ensure_table(conn)
    project = _project(conn, project_id)
    entries = core.project_entries(conn, project)
    rows = {r["entry_id"]: r for r in conn.execute(
        "SELECT * FROM outline_items WHERE project_id = ? AND entry_id IS NOT NULL", (project["id"],))}
    end = conn.execute("SELECT COALESCE(MAX(pos), -1) m FROM outline_items WHERE project_id = ?",
                       (project["id"],)).fetchone()["m"]
    added = False
    for e in entries:
        if e["id"] not in rows:
            end += 1
            conn.execute("INSERT INTO outline_items (project_id, entry_id, pos, created_at) VALUES (?, ?, ?, ?)",
                         (project["id"], e["id"], end, _now()))
            added = True
    if added:
        conn.commit()
    in_project = {e["id"]: e for e in entries}
    entry_notes = {r["entry_id"]: r["body"] for r in conn.execute(
        "SELECT entry_id, body FROM entry_notes WHERE entry_id IS NOT NULL")} if entries else {}
    items = []
    for r in conn.execute("SELECT * FROM outline_items WHERE project_id = ? ORDER BY pos, id", (project["id"],)):
        if r["entry_id"] is None:
            items.append({"id": r["id"], "kind": "placeholder", "title": r["title"], "synopsis": r["synopsis"],
                          "status": r["status"], "notes": r["notes"], "word_count": 0})
            continue
        e = in_project.get(r["entry_id"])
        if e is None:
            continue  # left the project; its synopsis and status wait in case it comes back
        items.append({"id": r["id"], "kind": "entry", "entry_id": e["id"], "title": e["title"],
                      "category": e["category"], "draft_tag": e["draft_tag"], "word_count": e["word_count"],
                      "last_edited": e["last_edited"], "published": e["published"],
                      "synopsis": r["synopsis"], "status": r["status"], "notes": entry_notes.get(e["id"], "")})
    counts = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    counts["none"] = sum(1 for i in items if not i["status"])
    return {"project_id": project["id"], "statuses": list(STATUSES), "items": items, "counts": counts}


def update(conn, project_id, item_id, fields):
    ensure_table(conn)
    project = _project(conn, project_id)
    row = _item(conn, project["id"], item_id)
    sets, args = [], []
    if "synopsis" in fields:
        sets.append("synopsis = ?"); args.append(_clean_line(fields["synopsis"], 400))
    if "status" in fields:
        status = str(fields["status"] or "")
        if status and status not in STATUSES:
            raise OutlineError("Choose idea, drafting, revising or done.")
        sets.append("status = ?"); args.append(status)
    if "title" in fields:
        if row["entry_id"] is not None:
            raise OutlineError("Rename an entry from its own page, so its folder is renamed too.")
        title = _clean_line(fields["title"], 200)
        if not title:
            raise OutlineError("Give the placeholder a title.")
        sets.append("title = ?"); args.append(title)
    if "notes" in fields:
        if row["entry_id"] is not None:
            notes.save(conn, row["entry_id"], fields["notes"])
        else:
            text = str(fields["notes"] or "").replace("\r\n", "\n")
            if len(text) > notes.MAX_CHARS:
                raise OutlineError("Those notes are too long to save.")
            sets.append("notes = ?"); args.append(text)
    if sets:
        conn.execute(f"UPDATE outline_items SET {', '.join(sets)} WHERE id = ?", (*args, row["id"]))
        conn.commit()
    return get(conn, project["id"])


def add_placeholder(conn, project_id, title, synopsis="", after=None):
    """A slot for a piece that isn't written yet, at the end or just after
    another item."""
    ensure_table(conn)
    project = _project(conn, project_id)
    title = _clean_line(title, 200)
    if not title:
        raise OutlineError("Give the placeholder a title.")
    current = get(conn, project["id"])["items"]
    ids = [i["id"] for i in current]
    new_id = conn.execute("""INSERT INTO outline_items (project_id, entry_id, pos, title, synopsis, status, created_at)
                             VALUES (?, NULL, 0, ?, ?, 'idea', ?)""",
                          (project["id"], title, _clean_line(synopsis, 400), _now())).lastrowid
    try:
        at = ids.index(int(after)) + 1 if after is not None else len(ids)
    except (TypeError, ValueError):
        at = len(ids)
    ids.insert(at, new_id)
    _write_order(conn, project, ids)
    return get(conn, project["id"]) | {"added": new_id}


def delete_placeholder(conn, project_id, item_id):
    ensure_table(conn)
    project = _project(conn, project_id)
    row = _item(conn, project["id"], item_id)
    if row["entry_id"] is not None:
        raise OutlineError("That's an entry. Use Remove to take it out of the project; the entry stays in your library.")
    conn.execute("DELETE FROM outline_items WHERE id = ?", (row["id"],))
    conn.commit()
    return get(conn, project["id"])


def _write_order(conn, project, item_ids):
    for pos, iid in enumerate(item_ids):
        conn.execute("UPDATE outline_items SET pos = ? WHERE id = ? AND project_id = ?", (pos, iid, project["id"]))
    entry_ids = [r["entry_id"] for r in conn.execute(
        "SELECT entry_id FROM outline_items WHERE project_id = ? AND entry_id IS NOT NULL ORDER BY pos, id",
        (project["id"],))]
    in_project = {e["id"] for e in core.project_entries(conn, project)}
    conn.commit()
    core.set_project_order(conn, project["id"], [e for e in entry_ids if e in in_project])


def reorder(conn, project_id, item_ids):
    ensure_table(conn)
    project = _project(conn, project_id)
    current = [i["id"] for i in get(conn, project["id"])["items"]]
    try:
        wanted = [int(i) for i in item_ids or []]
    except (TypeError, ValueError):
        raise OutlineError("That order didn't make sense. Reload and try again.") from None
    if sorted(wanted) != sorted(current):
        raise OutlineError("The outline changed while you were arranging it. Reload and try again.")
    _write_order(conn, project, wanted)
    return get(conn, project["id"])


def _to_entry(conn, row, entry_id):
    """A placeholder becomes the entry: it keeps its place, synopsis and
    status, and its notes are added to the entry's notes."""
    old = conn.execute("SELECT * FROM outline_items WHERE project_id = ? AND entry_id = ?",
                       (row["project_id"], entry_id)).fetchone()
    synopsis, status = row["synopsis"], row["status"]
    if old:
        synopsis = synopsis or old["synopsis"]
        status = old["status"] if row["status"] in ("", "idea") and old["status"] else status
        conn.execute("DELETE FROM outline_items WHERE id = ?", (old["id"],))
    conn.execute("UPDATE outline_items SET entry_id = ?, title = '', notes = '', synopsis = ?, status = ? WHERE id = ?",
                 (entry_id, synopsis, status, row["id"]))
    if row["notes"].strip():
        existing = notes.get(conn, entry_id)["body"]
        notes.save(conn, entry_id, f"{existing.rstrip()}\n\n{row['notes'].strip()}" if existing.strip() else row["notes"])
    conn.commit()


def start_writing(conn, project_id, item_id, category):
    """Create the entry for a placeholder: a folder in the chosen category
    tagged with the project, holding an empty current draft."""
    ensure_table(conn)
    project = _project(conn, project_id)
    row = _item(conn, project["id"], item_id)
    if row["entry_id"] is not None:
        raise OutlineError("That piece already has an entry.")
    if category not in core.TOP_FOLDERS:
        raise OutlineError("Choose a category for the new entry.")
    title = row["title"].strip()
    if core.INVALID_FILENAME_CHARS_RE.search(title):
        raise OutlineError(r'A title can\'t contain any of: \ / : * ? " < > |. Rename the placeholder first.')
    folder = f"{title} - [{project['tag']}]"
    path = os.path.join(core.ARCHIVE_ROOT, category, folder)
    if os.path.exists(path):
        raise OutlineError(f'There is already a folder called "{folder}" in {category}. '
                           "Rename the placeholder, or link it to that entry instead.")
    os.makedirs(path)
    with open(os.path.join(path, f"{title} [C].txt"), "w", encoding="utf-8"):
        pass
    core.scan_and_sync()
    entry = conn.execute("SELECT id FROM entries WHERE rel_path = ?", (f"{category}/{folder}",)).fetchone()
    if entry is None:
        raise OutlineError("The entry was created but Minerva couldn't find it. Press Rescan.")
    _to_entry(conn, row, entry["id"])
    if row["status"] in ("", "idea"):
        conn.execute("UPDATE outline_items SET status = 'drafting' WHERE id = ?", (row["id"],))
    _write_order(conn, project, [i["id"] for i in get(conn, project["id"])["items"]])
    return get(conn, project["id"]) | {"entry_id": entry["id"]}


def link_entry(conn, project_id, item_id, entry_id):
    """Fill a placeholder with an entry that already exists, adding the
    entry to the project if it isn't in it yet."""
    ensure_table(conn)
    project = _project(conn, project_id)
    row = _item(conn, project["id"], item_id)
    if row["entry_id"] is not None:
        raise OutlineError("That piece already has an entry.")
    entry = core.get_entry_row(conn, entry_id)
    if entry is None:
        raise OutlineError("That entry isn't in the library any more.")
    if entry["project_tag"] != project["tag"]:
        core.set_entry_project(conn, entry["id"], project["tag"])
    _to_entry(conn, row, entry["id"])
    _write_order(conn, project, [i["id"] for i in get(conn, project["id"])["items"]])
    return get(conn, project["id"])

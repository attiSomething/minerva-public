"""Notes beside a draft: revision thoughts, research and reminders that
belong with an entry but not inside its text.

Notes live in .minerva's index only; nothing is written to the library.
Each note is tied to its entry, and also remembers the entry's title and
folder so it can find the entry again if the entry is moved or renamed
outside Minerva (Minerva's own renames keep the link). A note that can't
find its entry is kept, never dropped, and shows up in the library check.
"""

import datetime

MAX_CHARS = 200_000


class NotesError(ValueError):
    user_facing = True


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS entry_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id INTEGER UNIQUE,
        title TEXT NOT NULL,
        rel_path TEXT NOT NULL,
        body TEXT NOT NULL,
        updated_at TEXT)""")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def get(conn, entry_id):
    ensure_table(conn)
    row = conn.execute("SELECT body, updated_at FROM entry_notes WHERE entry_id = ?", (entry_id,)).fetchone()
    return {"body": row["body"], "updated_at": row["updated_at"]} if row else {"body": "", "updated_at": None}


def save(conn, entry_id, body):
    ensure_table(conn)
    body = str(body or "").replace("\r\n", "\n")
    if len(body) > MAX_CHARS:
        raise NotesError("Those notes are too long to save. Keep notes under 200,000 characters.")
    entry = conn.execute("SELECT title, rel_path FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None:
        raise NotesError("That entry isn't in the library any more. Reload and try again.")
    now = _now()
    if not body.strip():
        conn.execute("DELETE FROM entry_notes WHERE entry_id = ?", (entry_id,))
    else:
        conn.execute("""INSERT INTO entry_notes (entry_id, title, rel_path, body, updated_at) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(entry_id) DO UPDATE SET title = excluded.title, rel_path = excluded.rel_path,
                        body = excluded.body, updated_at = excluded.updated_at""",
                     (entry_id, entry["title"], entry["rel_path"], body, now))
    conn.commit()
    return {"body": body if body.strip() else "", "updated_at": now}


def move_entry(conn, from_id, to_id):
    """When one entry is merged into another, its notes follow, added below
    the kept entry's own notes."""
    ensure_table(conn)
    src = conn.execute("SELECT * FROM entry_notes WHERE entry_id = ?", (from_id,)).fetchone()
    if src is None:
        return
    dst = conn.execute("SELECT * FROM entry_notes WHERE entry_id = ?", (to_id,)).fetchone()
    if dst is None:
        conn.execute("UPDATE entry_notes SET entry_id = ? WHERE id = ?", (to_id, src["id"]))
    else:
        body = f"{dst['body'].rstrip()}\n\n— From {src['title']} —\n{src['body'].strip()}"
        conn.execute("UPDATE entry_notes SET body = ?, updated_at = ? WHERE id = ?", (body, _now(), dst["id"]))
        conn.execute("DELETE FROM entry_notes WHERE id = ?", (src["id"],))


def remember(conn):
    """Copy each entry's current title and folder onto its notes, so they
    can be matched up again if the entry vanishes from the next sync."""
    ensure_table(conn)
    conn.execute("""UPDATE entry_notes SET title = (SELECT title FROM entries WHERE id = entry_notes.entry_id),
                    rel_path = (SELECT rel_path FROM entries WHERE id = entry_notes.entry_id)
                    WHERE entry_id IN (SELECT id FROM entries)""")


def reconcile(conn):
    """After a sync: keep each note's title and folder current, and re-link
    notes whose entry disappeared to the entry that took its place (same
    folder, or else the only entry with the same title). Notes that still
    can't be placed are left as they are."""
    remember(conn)
    lost = conn.execute("SELECT * FROM entry_notes WHERE entry_id IS NULL OR entry_id NOT IN (SELECT id FROM entries)").fetchall()
    for n in lost:
        taken = "id NOT IN (SELECT entry_id FROM entry_notes WHERE entry_id IS NOT NULL)"
        match = conn.execute(f"SELECT id, title, rel_path FROM entries WHERE rel_path = ? AND {taken}",
                             (n["rel_path"],)).fetchall()
        if not match:
            match = conn.execute(f"SELECT id, title, rel_path FROM entries WHERE title = ? COLLATE NOCASE AND {taken}",
                                 (n["title"],)).fetchall()
        if len(match) == 1:
            m = match[0]
            conn.execute("UPDATE entry_notes SET entry_id = ?, title = ?, rel_path = ? WHERE id = ?",
                         (m["id"], m["title"], m["rel_path"], n["id"]))
        elif n["entry_id"] is not None:
            # free the id: SQLite may hand it to a new entry later
            conn.execute("UPDATE entry_notes SET entry_id = NULL WHERE id = ?", (n["id"],))
    conn.commit()


def lost(conn):
    ensure_table(conn)
    return [dict(r) for r in conn.execute(
        "SELECT id, title, rel_path, body, updated_at FROM entry_notes WHERE entry_id IS NULL ORDER BY title")]


def attach(conn, note_id, entry_id):
    """Give a lost note to an entry, below any notes it already has."""
    ensure_table(conn)
    n = conn.execute("SELECT * FROM entry_notes WHERE id = ? AND entry_id IS NULL", (note_id,)).fetchone()
    if n is None:
        raise NotesError("Those notes have already been placed. Check again to refresh the list.")
    entry = conn.execute("SELECT title, rel_path FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None:
        raise NotesError("That entry isn't in the library any more.")
    conn.execute("UPDATE entry_notes SET entry_id = -1 WHERE id = ?", (note_id,))
    move_entry(conn, -1, entry_id)
    conn.execute("UPDATE entry_notes SET title = ?, rel_path = ? WHERE entry_id = ?",
                 (entry["title"], entry["rel_path"], entry_id))
    conn.commit()


def forget(conn, note_id):
    ensure_table(conn)
    conn.execute("DELETE FROM entry_notes WHERE id = ? AND entry_id IS NULL", (note_id,))
    conn.commit()


def search(conn, needle_folded, where_sql="", args=()):
    """Notes whose text contains the (casefolded) needle, as rows shaped
    like search_files rows, joined to their entry. Notes are few, so they
    are matched here rather than kept in a folded copy."""
    ensure_table(conn)
    rows = conn.execute(f"""
        SELECT n.body AS content, e.id AS entry_id, e.title, e.top_folder, e.project_tag
        FROM entry_notes n JOIN entries e ON e.id = n.entry_id
        WHERE 1 {where_sql}""", args).fetchall()
    return [r for r in rows if needle_folded in r["content"].casefold()]

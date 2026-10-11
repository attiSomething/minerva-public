"""Search inside drafts: every entry's current draft, the .txt drafts in
its Archive, and its notes (see notes.py).

The text lives in a plain index table, refreshed on sync (only files whose
size or date changed are re-read) and after each save in Minerva. Searching
is a case-insensitive phrase match, so "the tide" finds exactly that phrase
wherever it appears, including inside longer words.
"""

import os

from . import core

SNIPPETS_PER_FILE = 3
SNIPPET_CHARS = 180
MAX_FILES = 300


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS search_files (
        path TEXT PRIMARY KEY,
        entry_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        mtime REAL,
        size INTEGER,
        content TEXT NOT NULL,
        folded TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS search_files_entry ON search_files(entry_id)")


def _entry_files(row):
    """(absolute path, library-relative path, kind, name) for an entry's
    current draft and archived .txt drafts."""
    edir = core.entry_dir(row)
    out = []
    if row["draft_filename"]:
        out.append((os.path.join(edir, row["draft_filename"]), "current", row["draft_filename"]))
    adir = os.path.join(edir, "Archive")
    if os.path.isdir(adir):
        for name in sorted(os.listdir(adir)):
            if name.lower().endswith(".txt") and os.path.isfile(os.path.join(adir, name)):
                out.append((os.path.join(adir, name), "archive", name))
    root = core.ARCHIVE_ROOT
    return [(full, os.path.relpath(full, root).replace(os.sep, "/"), kind, name) for full, kind, name in out]


def _index_files(conn, entry_id, files, known):
    seen = set()
    for full, rel, kind, name in files:
        seen.add(rel)
        try:
            st = os.stat(full)
        except OSError:
            continue
        k = known.get(rel)
        if k and k["mtime"] == st.st_mtime and k["size"] == st.st_size:
            if k["entry_id"] != entry_id or k["kind"] != kind:
                conn.execute("UPDATE search_files SET entry_id = ?, kind = ? WHERE path = ?", (entry_id, kind, rel))
            continue
        try:
            text = core.read_text(full)
        except OSError:
            continue
        conn.execute("""INSERT OR REPLACE INTO search_files (path, entry_id, kind, name, mtime, size, content, folded)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                     (rel, entry_id, kind, name, st.st_mtime, st.st_size, text, text.casefold()))
    return seen


def refresh(conn):
    """Bring the index up to date with the library. Returns files re-read."""
    known = {r["path"]: r for r in conn.execute("SELECT path, entry_id, kind, mtime, size FROM search_files")}
    before = conn.total_changes
    seen = set()
    for row in conn.execute("SELECT * FROM entries").fetchall():
        seen |= _index_files(conn, row["id"], _entry_files(row), known)
    gone = [p for p in known if p not in seen]
    conn.executemany("DELETE FROM search_files WHERE path = ?", [(p,) for p in gone])
    conn.commit()
    return conn.total_changes - before


def index_entry(conn, row):
    """Re-index one entry right after a save."""
    known = {r["path"]: r for r in conn.execute(
        "SELECT path, entry_id, kind, mtime, size FROM search_files WHERE entry_id = ?", (row["id"],))}
    seen = _index_files(conn, row["id"], _entry_files(row), known)
    conn.executemany("DELETE FROM search_files WHERE path = ?", [(p,) for p in known if p not in seen])


def _snippets(content, folded, needle):
    """Up to SNIPPETS_PER_FILE matching lines, each as a list of
    {text, hit} pieces, plus the total number of matches in the file."""
    total = folded.count(needle)
    out = []
    starts = [0]
    for i, ch in enumerate(content):
        if ch == "\n":
            starts.append(i + 1)
    pos = folded.find(needle)
    used_lines = set()
    while pos != -1 and len(out) < SNIPPETS_PER_FILE:
        line_no = _line_of(starts, pos)
        if line_no not in used_lines:
            used_lines.add(line_no)
            ls = starts[line_no]
            le = content.find("\n", ls)
            le = len(content) if le == -1 else le
            out.append({"line": line_no + 1, "pieces": _pieces(content[ls:le], folded[ls:le], needle)})
        pos = folded.find(needle, pos + len(needle))
    return out, total


def _line_of(starts, pos):
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _pieces(line, folded_line, needle):
    # casefold can change lengths (e.g. "ß"); fall back to the plain line then
    if len(line) != len(folded_line):
        return [{"text": line[:SNIPPET_CHARS], "hit": False}]
    first = folded_line.find(needle)
    start = 0
    if len(line) > SNIPPET_CHARS and first > SNIPPET_CHARS // 3:
        start = first - SNIPPET_CHARS // 3
        start = line.rfind(" ", 0, start) + 1 or start
    end = min(len(line), start + SNIPPET_CHARS)
    pieces = []
    if start > 0:
        pieces.append({"text": "…", "hit": False})
    i = start
    while i < end:
        j = folded_line.find(needle, i, end)
        if j == -1:
            pieces.append({"text": line[i:end], "hit": False})
            break
        if j > i:
            pieces.append({"text": line[i:j], "hit": False})
        k = min(end, j + len(needle))
        pieces.append({"text": line[j:k], "hit": True})
        i = k
    if end < len(line):
        pieces.append({"text": "…", "hit": False})
    return pieces


def find(conn, q, category=None, project=None, current_only=False, tag=None):
    needle = " ".join(str(q or "").split()).casefold()
    if len(needle) < 2:
        return {"query": q, "entries": [], "files": 0, "notes": 0, "matches": 0, "truncated": False}
    entry_where, entry_args = [], []
    if category:
        entry_where.append("e.top_folder = ?"); entry_args.append(category)
    if project == "__none__":
        entry_where.append("(e.project_tag IS NULL OR e.project_tag = '')")
    elif project:
        entry_where.append("e.project_tag = ?"); entry_args.append(project)
    if tag:
        entry_where.append("e.id IN (SELECT entry_id FROM entry_tags WHERE tag = ?)"); entry_args.append(tag)
    where = ["s.folded LIKE ? ESCAPE '\\'"] + entry_where
    args = ["%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"] + entry_args
    if current_only:
        where.append("s.kind = 'current'")
    rows = conn.execute(f"""
        SELECT s.path, s.kind, s.name, s.content, s.folded, e.id AS entry_id, e.title, e.top_folder, e.project_tag
        FROM search_files s JOIN entries e ON e.id = s.entry_id
        WHERE {' AND '.join(where)}
        ORDER BY e.title COLLATE NOCASE, e.id, s.kind = 'archive', s.name DESC
        LIMIT ?""", (*args, MAX_FILES + 1)).fetchall()
    truncated = len(rows) > MAX_FILES
    entries, by_id, matches = [], {}, 0
    for r in rows[:MAX_FILES]:
        snippets, n = _snippets(r["content"], r["folded"], needle)
        matches += n
        e = by_id.get(r["entry_id"])
        if e is None:
            e = by_id[r["entry_id"]] = {"id": r["entry_id"], "title": r["title"], "category": r["top_folder"],
                                       "project": r["project_tag"], "files": []}
            entries.append(e)
        e["files"].append({"kind": r["kind"], "name": r["name"], "matches": n, "snippets": snippets})
    notes_hit = 0
    if not current_only:
        from . import notes
        for r in notes.search(conn, needle, "".join(" AND " + w for w in entry_where), entry_args):
            snippets, n = _snippets(r["content"], r["content"].casefold(), needle)
            matches += n
            e = by_id.get(r["entry_id"])
            if e is None:
                e = by_id[r["entry_id"]] = {"id": r["entry_id"], "title": r["title"], "category": r["top_folder"],
                                           "project": r["project_tag"], "files": []}
                entries.append(e)
            notes_hit += 1
            e["files"].insert(0, {"kind": "notes", "name": "Notes", "matches": n, "snippets": snippets})
        entries.sort(key=lambda e: (e["title"].casefold(), e["id"]))
    return {"query": q, "entries": entries, "files": min(len(rows), MAX_FILES), "notes": notes_hit,
            "matches": matches, "truncated": truncated}

"""Find and replace across the current drafts of the library.

A preview lists every entry whose current draft matches, with each
matching line shown before and after. Applying changes only the entries
the writer ticked, and saves each one as a new version: the old draft
goes to the entry's Archive as with any "Save (Archive current draft)".
"""

import os
import re

from . import core

MAX_ENTRIES = 1000
MAX_LINES_SHOWN = 6


class ReplaceError(ValueError):
    user_facing = True


def pattern(find, match_case=False, whole_word=False):
    find = str(find or "")
    if not find.strip():
        raise ReplaceError("Type what to find.")
    if len(find) > 500:
        raise ReplaceError("That's too long to search for.")
    p = re.escape(find)
    if whole_word:
        p = rf"(?<!\w){p}(?!\w)"
    return re.compile(p, 0 if match_case else re.IGNORECASE)


def _rows(conn, category=None, project=None, tag=None, ids=None):
    where, args = [], []
    if category:
        where.append("e.top_folder = ?"); args.append(category)
    if project == "__none__":
        where.append("(e.project_tag IS NULL OR e.project_tag = '')")
    elif project:
        where.append("e.project_tag = ?"); args.append(project)
    if tag:
        where.append("e.id IN (SELECT entry_id FROM entry_tags WHERE tag = ?)"); args.append(tag)
    if ids is not None:
        ids = [int(i) for i in ids][:MAX_ENTRIES]
        if not ids:
            return []
        where.append(f"e.id IN ({', '.join('?' for _ in ids)})"); args.extend(ids)
    sql = "SELECT e.* FROM entries e" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY e.title COLLATE NOCASE"
    return conn.execute(sql, args).fetchall()


def _read(row):
    path = os.path.join(core.entry_dir(row), row["draft_filename"])
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _pieces(line, rx, width=240, lead=60):
    """The line split into matched and unmatched pieces. A long line (a
    prose paragraph) is cut to a window around its first match, with an
    ellipsis piece where text was left out."""
    hits = [(m.start(), m.end()) for m in rx.finditer(line)]
    start, end = 0, len(line)
    if len(line) > width and hits:
        start = max(0, hits[0][0] - lead)
        end = min(len(line), start + width)
        for a, b in hits:
            if a < end < b:
                end = b  # never cut a match in half
    out, pos = [], start
    if start > 0:
        out.append({"text": "…", "hit": False, "gap": True})
    for a, b in hits:
        if a >= end:
            break
        if a > pos:
            out.append({"text": line[pos:a], "hit": False})
        out.append({"text": line[a:b], "hit": True})
        pos = b
    if pos < end:
        out.append({"text": line[pos:end], "hit": False})
    if end < len(line):
        out.append({"text": "…", "hit": False, "gap": True})
    return out


def preview(conn, find, replacement, match_case=False, whole_word=False, category=None, project=None, tag=None):
    rx = pattern(find, match_case, whole_word)
    replacement = str(replacement or "")
    entries, total = [], 0
    for row in _rows(conn, category, project, tag):
        try:
            text = _read(row)
        except OSError:
            continue
        n = len(rx.findall(text))
        if not n:
            continue
        total += n
        lines = []
        for i, line in enumerate(text.split("\n"), start=1):
            if rx.search(line):
                before = _pieces(line, rx)
                lines.append({"line": i, "before": before,
                              "after": "".join(replacement if p["hit"] else p["text"] for p in before)})
                if len(lines) >= MAX_LINES_SHOWN:
                    break
        entries.append({"id": row["id"], "title": row["title"], "category": row["top_folder"],
                        "matches": n, "lines": lines})
        if len(entries) >= MAX_ENTRIES:
            break
    return {"entries": entries, "matches": total, "truncated": len(entries) >= MAX_ENTRIES}


def apply(conn, find, replacement, entry_ids, match_case=False, whole_word=False):
    """Replace in the ticked entries. Each changed entry is saved as a new
    version, its old draft archived."""
    rx = pattern(find, match_case, whole_word)
    replacement = str(replacement or "")
    changed, replaced = [], 0
    for row in _rows(conn, ids=entry_ids or []):
        try:
            text = _read(row)
        except OSError:
            continue
        new, n = rx.subn(lambda m: replacement, text)
        if not n or new == text:
            continue
        core.save_entry_content(conn, row["id"], new, "archive")
        changed.append({"id": row["id"], "title": row["title"], "replaced": n})
        replaced += n
    return {"entries": changed, "replaced": replaced}

"""Bringing new writing into the library from inside Minerva: a blank
entry, or text pasted in (optionally split into several pieces).

A new entry is the same folder and current draft the writer would make by
hand: <Category>/<Title>/<Title> [C].txt, or <Title> - [TAG] when it belongs
to a project. Only the new entry's folder and file are written.
"""

import os
import re

from . import core

MAX_TITLE = 120
MAX_TEXT = 2_000_000
MAX_PIECES = 200
# A line of three or more *, -, _, = or # (alone, spaces allowed) separates
# pieces, as does a run of three or more blank lines.
SEPARATOR_RE = re.compile(r"^[ \t]*(?:([*\-_=#~])[ \t]*){3,}$")


class IntakeError(ValueError):
    user_facing = True


def clean_title(title):
    """A title that can be a Windows folder name, or '' when nothing's left."""
    t = core.INVALID_FILENAME_CHARS_RE.sub(" ", str(title or ""))
    t = " ".join(t.split()).strip(" .")
    return t[:MAX_TITLE].rstrip(" .")


def suggest_title(text):
    """The first line of a piece, when it reads like a title."""
    for line in str(text or "").split("\n"):
        line = line.strip().strip("#*_ ").strip()
        if not line:
            continue
        t = clean_title(line)
        if len(t) > 80:
            t = clean_title(" ".join(t.split()[:8]))
        return t
    return ""


def split_pieces(text, split=True):
    """[{"title", "text"}] from pasted text. With split, separator lines
    (*** and the like) and runs of three or more blank lines start a new
    piece."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT:
        raise IntakeError("That's more text than Minerva takes in one go. Paste it in parts.")
    chunks = [text]
    if split:
        chunks, cur, blanks = [], [], 0
        for line in text.split("\n"):
            if SEPARATOR_RE.match(line):
                chunks.append("\n".join(cur))
                cur, blanks = [], 0
                continue
            if not line.strip():
                blanks += 1
                if blanks >= 3 and any(x.strip() for x in cur):
                    chunks.append("\n".join(cur))
                    cur, blanks = [], 0
                    continue
            else:
                blanks = 0
            cur.append(line)
        chunks.append("\n".join(cur))
    pieces = []
    for c in chunks:
        body = c.strip("\n")
        if not body.strip():
            continue
        pieces.append({"title": suggest_title(body), "text": body.rstrip() + "\n"})
    if len(pieces) > MAX_PIECES:
        raise IntakeError(f"That splits into more than {MAX_PIECES} pieces. Paste it in parts.")
    return pieces


def _folder_free(category, folder):
    """Windows treats names that differ only in case as the same folder, so
    this check does too, on every system."""
    parent = os.path.join(core.ARCHIVE_ROOT, category)
    try:
        names = os.listdir(parent)
    except FileNotFoundError:
        return True
    return folder.casefold() not in {n.casefold() for n in names}


def free_title(title, category, tag=None):
    """The title, or 'Title (2)' and so on when that folder is taken."""
    def folder(t):
        return f"{t} - [{tag}]" if tag else t
    if _folder_free(category, folder(title)):
        return title
    n = 2
    while not _folder_free(category, folder(f"{title} ({n})")):
        n += 1
    return f"{title} ({n})"


def _project_tag(conn, project):
    if not project:
        return None
    row = conn.execute("SELECT tag FROM projects WHERE tag = ? COLLATE NOCASE OR id = ?",
                       (str(project), project if str(project).isdigit() else -1)).fetchone()
    if row is None:
        raise IntakeError("That project no longer exists.")
    return row["tag"]


def _write(category, folder, title, text, modified=None):
    path = os.path.join(core.ARCHIVE_ROOT, category, folder)
    os.makedirs(path)
    draft = os.path.join(path, f"{title} [C].txt")
    with open(draft, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    if modified:
        # an imported note keeps its own date, so it's filed under when it was written
        try:
            os.utime(draft, (float(modified), float(modified)))
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    return f"{category}/{folder}"


def create_entries(conn, items, category, project=None, rename_taken=True):
    """Create one entry per item ({"title", "text"}), then sync once.
    Returns [{"id", "title"}] in the same order. A taken title gets a
    number unless rename_taken is False, when it's an error."""
    if core.ARCHIVE_ROOT is None:
        raise IntakeError("Open a library first.")
    if category not in core.TOP_FOLDERS:
        raise IntakeError("Choose a category for the new entry.")
    if not items:
        raise IntakeError("There's nothing to create.")
    if len(items) > MAX_PIECES:
        raise IntakeError(f"Create at most {MAX_PIECES} entries at a time.")
    tag = _project_tag(conn, project)
    planned, used = [], set()
    for item in items:
        title = clean_title(item.get("title"))
        if not title:
            raise IntakeError("Every new entry needs a title.")
        if not rename_taken and not _folder_free(category, f"{title} - [{tag}]" if tag else title):
            raise IntakeError(f'There is already an entry called "{title}" in {category}.')
        final = free_title(title, category, tag)
        n = 2
        while final.casefold() in used:
            final = free_title(f"{title} ({n})", category, tag)
            n += 1
        used.add(final.casefold())
        text = str(item.get("text") or "")
        if len(text) > MAX_TEXT:
            raise IntakeError(f'"{title}" is too long for one entry.')
        planned.append((final, text, item.get("tags") or [], item.get("modified")))
    rels = [_write(category, f"{t} - [{tag}]" if tag else t, t, text, when) for t, text, _, when in planned]
    core.scan_and_sync()
    out = []
    for (title, _, tag_list, _when), rel in zip(planned, rels):
        row = conn.execute("SELECT id FROM entries WHERE rel_path = ?", (rel,)).fetchone()
        if row is None:
            raise IntakeError("The entry was created but Minerva couldn't find it. Press Rescan.")
        if tag_list:
            from . import tags
            try:
                tags.set_for_entry(conn, row["id"], [str(t) for t in tag_list][:tags.MAX_TAGS_PER_ENTRY])
            except tags.TagError:
                pass  # a tag Minerva can't keep doesn't stop the entry
        out.append({"id": row["id"], "title": title})
    return out

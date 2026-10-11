"""Sync from Obsidian vaults and other folders of Markdown or text notes.

A synced folder is only ever read. Each time Minerva looks (on Home, or
"Check now" in Settings) it lists notes that are new since last time and
notes that changed. Nothing happens until the writer reviews them: a new
note becomes a new entry, a changed note becomes a new version of its
entry with the old draft archived, and a note can be skipped for good. If
the entry was also edited in Minerva since the last sync, the change is
marked as a conflict and left unticked, so Minerva's edits are never
replaced without the writer choosing it (and even then they go to
Archive).

The note's top folder picks its category and its tags (front matter and
inline #tags) become Minerva tags, both through a mapping the writer can
change. What Minerva remembers about each note lives in the library's own
index.
"""

import datetime
import hashlib
import json
import os
import re

from . import core, fileimport, intake, tags

TEXT_EXTS = (".md", ".markdown", ".txt")
MAX_NOTES = 5000
INLINE_TAG_RE = re.compile(r"(?<![\w&/#])#([A-Za-z][\w/-]{0,59})")
SKIP = "__skip__"
# common vault folder names, matched to the standard categories
FOLDER_GUESSES = {
    "poem": "Poetry", "poems": "Poetry", "verse": "Poetry",
    "story": "Fiction", "stories": "Fiction", "short stories": "Fiction", "novel": "Fiction", "novels": "Fiction",
    "essay": "Nonfiction", "essays": "Nonfiction", "articles": "Nonfiction", "memoir": "Nonfiction",
}


class SyncError(ValueError):
    user_facing = True


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_sources (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        default_category TEXT NOT NULL,
        folder_map TEXT NOT NULL DEFAULT '{}',
        tag_map TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sync_notes (
        source_id INTEGER NOT NULL,
        rel_path TEXT NOT NULL,
        entry_id INTEGER,
        note_hash TEXT NOT NULL,
        note_mtime REAL,
        note_size INTEGER,
        draft_hash TEXT,
        ignored INTEGER NOT NULL DEFAULT 0,
        synced_at TEXT NOT NULL,
        PRIMARY KEY (source_id, rel_path))""")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _hash(text):
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _source(conn, source_id):
    row = conn.execute("SELECT * FROM sync_sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise SyncError("That synced folder isn't set up any more.")
    return row


def _shape(row):
    return {"id": row["id"], "path": row["path"], "name": row["name"],
            "default_category": row["default_category"],
            "folder_map": json.loads(row["folder_map"] or "{}"),
            "tag_map": json.loads(row["tag_map"] or "{}"),
            "exists": os.path.isdir(row["path"])}


def list_sources(conn):
    ensure_tables(conn)
    out = []
    for row in conn.execute("SELECT * FROM sync_sources ORDER BY name COLLATE NOCASE"):
        s = _shape(row)
        s["tracked"] = conn.execute("SELECT COUNT(*) FROM sync_notes WHERE source_id = ? AND entry_id IS NOT NULL",
                                    (row["id"],)).fetchone()[0]
        out.append(s)
    return out


def add_source(conn, path, default_category):
    ensure_tables(conn)
    path = (path or "").strip().strip('"')
    if not path or not os.path.isdir(path):
        raise SyncError("That folder doesn't exist.")
    path = os.path.abspath(path)
    lib = _norm(core.ARCHIVE_ROOT)
    here = _norm(path)
    if here == lib or here.startswith(lib + os.sep) or lib.startswith(here + os.sep):
        raise SyncError("Choose a folder outside your library. Minerva syncs from notes kept somewhere else.")
    if default_category not in core.TOP_FOLDERS:
        raise SyncError("Choose a category for notes that don't match one.")
    if conn.execute("SELECT 1 FROM sync_sources WHERE path = ?", (path,)).fetchone():
        raise SyncError("That folder is already synced.")
    name = os.path.basename(path.rstrip("\\/")) or path
    cur = conn.execute("INSERT INTO sync_sources (path, name, default_category, created_at) VALUES (?, ?, ?, ?)",
                       (path, name, default_category, _now()))
    conn.commit()
    return _shape(_source(conn, cur.lastrowid))


def remove_source(conn, source_id):
    """Stop syncing. Entries already brought in stay in the library."""
    ensure_tables(conn)
    _source(conn, source_id)
    conn.execute("DELETE FROM sync_notes WHERE source_id = ?", (source_id,))
    conn.execute("DELETE FROM sync_sources WHERE id = ?", (source_id,))
    conn.commit()


def _walk(root):
    """[(rel_path, mtime, size)] for every note under root, skipping hidden
    folders (.obsidian, .trash, .git) and anything not Markdown or text."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "node_modules")
        for f in sorted(files):
            if f.startswith(".") or not f.lower().endswith(TEXT_EXTS):
                continue
            full = os.path.join(d, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append((os.path.relpath(full, root).replace("\\", "/"), st.st_mtime, st.st_size))
            if len(out) >= MAX_NOTES:
                return out
    return out


def _top_folder(rel):
    return rel.split("/")[0] if "/" in rel else ""


def _read_note(root, rel):
    with open(os.path.join(root, *rel.split("/")), "rb") as fh:
        data = fh.read()
    raw = data.decode("utf-8", errors="replace")
    conv = fileimport.convert(rel.split("/")[-1], data)
    found = conv["fields"].get("tags") or conv["fields"].get("tag") or []
    if isinstance(found, str):
        found = [t for t in re.split(r"[,\s]+", found) if t]
    body = fileimport.front_matter(raw.replace("\r\n", "\n"))[1]
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    found = list(found) + INLINE_TAG_RE.findall(body)
    seen, note_tags = set(), []
    for t in found:
        t = str(t).lstrip("#").strip()
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            note_tags.append(t)
    return conv, _hash(raw), note_tags


def _category_for(src, rel):
    folder = _top_folder(rel)
    fmap = src["folder_map"]
    if folder in fmap:
        return fmap[folder] if fmap[folder] == SKIP or fmap[folder] in core.TOP_FOLDERS else src["default_category"]
    for c in core.TOP_FOLDERS:
        if folder and c.casefold() == folder.casefold():
            return c
    guess = FOLDER_GUESSES.get(folder.casefold())
    if guess in core.TOP_FOLDERS:
        return guess
    return src["default_category"]


def _map_tags(src, note_tags):
    out = []
    for t in note_tags:
        mapped = src["tag_map"].get(t, t)
        if mapped and mapped not in out:
            out.append(mapped)
    return out[:tags.MAX_TAGS_PER_ENTRY]


def _draft_hash(conn, entry_id):
    row = core.get_entry_row(conn, entry_id)
    if row is None:
        return None
    try:
        return _hash(core.read_entry_content(row))
    except OSError:
        return None


def overview(conn, source_id):
    """The folders and tags in a synced folder, for the mapping screen."""
    src = _shape(_source(conn, source_id))
    if not src["exists"]:
        raise SyncError(f"Minerva can't find {src['path']} right now.")
    folders, tag_counts = {}, {}
    for rel, _m, _s in _walk(src["path"]):
        f = _top_folder(rel)
        folders[f] = folders.get(f, 0) + 1
        try:
            _conv, _h, note_tags = _read_note(src["path"], rel)
        except (OSError, fileimport.ImportFileError):
            continue
        for t in note_tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    return {
        "source": src,
        "folders": [{"name": f, "notes": n, "category": _category_for(src, f + "/x" if f else "x")}
                    for f, n in sorted(folders.items(), key=lambda kv: kv[0].casefold())],
        "tags": [{"name": t, "notes": n, "maps_to": src["tag_map"].get(t, t)}
                 for t, n in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))],
    }


def save_mapping(conn, source_id, default_category=None, folder_map=None, tag_map=None):
    src = _source(conn, source_id)
    if default_category is not None:
        if default_category not in core.TOP_FOLDERS:
            raise SyncError("Choose a category for notes that don't match one.")
        conn.execute("UPDATE sync_sources SET default_category = ? WHERE id = ?", (default_category, source_id))
    if folder_map is not None:
        clean = {str(k): v for k, v in dict(folder_map).items() if v == SKIP or v in core.TOP_FOLDERS}
        conn.execute("UPDATE sync_sources SET folder_map = ? WHERE id = ?", (json.dumps(clean), source_id))
    if tag_map is not None:
        clean = {}
        for k, v in dict(tag_map).items():
            v = tags.clean(v) if str(v or "").strip() else ""
            clean[str(k)] = v
        conn.execute("UPDATE sync_sources SET tag_map = ? WHERE id = ?", (json.dumps(clean), source_id))
    conn.commit()
    return _shape(_source(conn, src["id"]))


def pending(conn, source_ids=None):
    """What's new or changed in the synced folders, without changing anything.
    Unchanged notes are recognised by size and modified time, so this stays
    quick on a large vault."""
    ensure_tables(conn)
    items, missing = [], []
    rows = conn.execute("SELECT * FROM sync_sources ORDER BY name COLLATE NOCASE").fetchall()
    for row in rows:
        if source_ids is not None and row["id"] not in source_ids:
            continue
        src = _shape(row)
        if not src["exists"]:
            missing.append(src["path"])
            continue
        known = {r["rel_path"]: r for r in conn.execute("SELECT * FROM sync_notes WHERE source_id = ?", (row["id"],))}
        for rel, mtime, size in _walk(src["path"]):
            k = known.get(rel)
            if k and k["note_mtime"] == mtime and k["note_size"] == size:
                continue
            category = _category_for(src, rel)
            if not k and category == SKIP:
                continue
            try:
                conv, h, note_tags = _read_note(src["path"], rel)
            except (OSError, fileimport.ImportFileError):
                continue
            if k and k["note_hash"] == h:
                # touched but not changed: remember the new time and move on
                conn.execute("UPDATE sync_notes SET note_mtime = ?, note_size = ? WHERE source_id = ? AND rel_path = ?",
                             (mtime, size, row["id"], rel))
                continue
            if k and k["ignored"]:
                continue
            entry = core.get_entry_row(conn, k["entry_id"]) if k and k["entry_id"] else None
            item = {"source_id": row["id"], "source": src["name"], "rel_path": rel, "title": conv["title"],
                    "words": conv["words"], "notes": conv["notes"], "tags": _map_tags(src, note_tags)}
            if entry is None:
                same = conn.execute("SELECT id FROM entries WHERE title = ? COLLATE NOCASE LIMIT 1", (conv["title"],)).fetchone()
                item.update(kind="new", category=category if category != SKIP else src["default_category"],
                            existing_id=same["id"] if same else None)
            else:
                cur = _draft_hash(conn, entry["id"])
                item.update(kind="changed", entry_id=entry["id"], entry_title=entry["title"],
                            category=entry["top_folder"], conflict=bool(k["draft_hash"]) and cur != k["draft_hash"])
            items.append(item)
    conn.commit()
    return {"items": items, "new": sum(1 for i in items if i["kind"] == "new"),
            "changed": sum(1 for i in items if i["kind"] == "changed"),
            "conflicts": sum(1 for i in items if i.get("conflict")), "missing": missing}


def _remember(conn, source_id, rel, entry_id, note_hash, ignored=False):
    src = _source(conn, source_id)
    try:
        st = os.stat(os.path.join(src["path"], *rel.split("/")))
        mtime, size = st.st_mtime, st.st_size
    except OSError:
        mtime, size = None, None
    conn.execute(
        """INSERT INTO sync_notes (source_id, rel_path, entry_id, note_hash, note_mtime, note_size, draft_hash, ignored, synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_id, rel_path) DO UPDATE SET entry_id = excluded.entry_id, note_hash = excluded.note_hash,
             note_mtime = excluded.note_mtime, note_size = excluded.note_size, draft_hash = excluded.draft_hash,
             ignored = excluded.ignored, synced_at = excluded.synced_at""",
        (source_id, rel, entry_id, note_hash, mtime, size,
         _draft_hash(conn, entry_id) if entry_id else None, 1 if ignored else 0, _now()))


def apply(conn, choices):
    """Act on the reviewed notes. Each choice: {source_id, rel_path, action}
    where action is "import" (with title and category), "update" or "ignore".
    Returns counts and the entries made or changed."""
    ensure_tables(conn)
    made, updated, ignored = [], [], 0
    by_cat = {}
    for c in choices or []:
        sid, rel, action = int(c.get("source_id") or 0), str(c.get("rel_path") or ""), c.get("action")
        src = _shape(_source(conn, sid))
        if ".." in rel.split("/"):
            raise SyncError("That note isn't inside the synced folder.")
        try:
            conv, h, note_tags = _read_note(src["path"], rel)
        except OSError:
            raise SyncError(f"Minerva can't read {rel} any more.") from None
        if action == "ignore":
            known = conn.execute("SELECT entry_id FROM sync_notes WHERE source_id = ? AND rel_path = ?", (sid, rel)).fetchone()
            _remember(conn, sid, rel, known["entry_id"] if known else None, h, ignored=True)
            ignored += 1
        elif action == "update":
            known = conn.execute("SELECT entry_id FROM sync_notes WHERE source_id = ? AND rel_path = ?", (sid, rel)).fetchone()
            if not known or not known["entry_id"] or core.get_entry_row(conn, known["entry_id"]) is None:
                raise SyncError(f"The entry for {rel} isn't in the library any more; bring it in as new instead.")
            core.save_entry_content(conn, known["entry_id"], conv["text"], "archive")
            have = tags.for_entry(conn, known["entry_id"])
            want = _map_tags(src, note_tags)
            if want and set(want) - set(have):
                tags.set_for_entry(conn, known["entry_id"], (have + [t for t in want if t not in have])[:tags.MAX_TAGS_PER_ENTRY])
            _remember(conn, sid, rel, known["entry_id"], h)
            updated.append({"id": known["entry_id"], "title": conv["title"]})
        elif action == "import":
            category = c.get("category") or _category_for(src, rel)
            if category not in core.TOP_FOLDERS:
                category = src["default_category"]
            by_cat.setdefault(category, []).append(
                (sid, rel, h, {"title": c.get("title") or conv["title"], "text": conv["text"],
                               "tags": _map_tags(src, note_tags)}))
        else:
            raise SyncError("Choose import, update or skip for each note.")
    conn.commit()  # creating entries rescans the library on its own connection
    for category, group in by_cat.items():
        for i in range(0, len(group), intake.MAX_PIECES):
            chunk = group[i:i + intake.MAX_PIECES]
            out = intake.create_entries(conn, [g[3] for g in chunk], category)
            for (sid, rel, h, _item), m in zip(chunk, out):
                _remember(conn, sid, rel, m["id"], h)
                made.append(m)
            conn.commit()
    conn.commit()
    return {"made": made, "updated": updated, "ignored": ignored}

"""
Minerva core logic: everything that touches the filesystem or the database.
server.py stays a thin Flask layer on top of this module.

A "library" is any folder the user picks during onboarding. Call
configure(library_root) before using anything else in this module; until
then the path globals below are None.
"""

import os
import re
import json
import shutil
import sqlite3
import datetime
import pathlib

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CATEGORIES = ["Fiction", "Nonfiction", "Poetry", "Misc"]
META_DIRNAME = ".minerva"
SOURCES_DIRNAME = "Sources"

# Where the first, single-archive version of Minerva kept its database and
# its journal scans, relative to the library root. Used only to carry an
# existing library over the first time it is opened.
LEGACY_DB_CANDIDATES = [os.path.join("01A - Minerva", "minerva.db"), "minerva.db"]
LEGACY_SCANS_DIR = os.path.join("0B - Reference", "Old Project", "Journal Scans")

ARCHIVE_ROOT = None
META_DIR = None
DB_PATH = None
PROJECTS_DIR = None
JOURNAL_SCANS_DIR = None
TOP_FOLDERS = list(DEFAULT_CATEGORIES)


# --------------------------------------------------------------------------
# Library setup
# --------------------------------------------------------------------------

def _library_settings_path(root):
    return os.path.join(root, META_DIRNAME, "library.json")


def read_library_settings(root):
    try:
        with open(_library_settings_path(root), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_library_settings(root, settings):
    os.makedirs(os.path.join(root, META_DIRNAME), exist_ok=True)
    with open(_library_settings_path(root), "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)


def _hide_on_windows(path):
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


def find_legacy_db(root):
    for rel in LEGACY_DB_CANDIDATES:
        candidate = os.path.join(root, rel)
        if os.path.isfile(candidate):
            return candidate
    return None


def _copy_legacy_db(src, dst):
    """Copy an earlier Minerva database without writing to it: opened
    read-only and copied with SQLite's backup API."""
    uri = pathlib.Path(os.path.abspath(src)).as_uri() + "?mode=ro"
    src_conn = sqlite3.connect(uri, uri=True)
    dst_conn = sqlite3.connect(dst)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def configure(library_root, db_path=None):
    """Point the module at a library folder. Creates the .minerva folder and
    any missing category folders, carries over an earlier Minerva database
    the first time, and runs schema migrations. Never modifies or removes
    anything that already exists in the library."""
    global ARCHIVE_ROOT, META_DIR, DB_PATH, PROJECTS_DIR, JOURNAL_SCANS_DIR, TOP_FOLDERS

    root = os.path.abspath(library_root)
    if not os.path.isdir(root):
        raise ValueError(f"library folder does not exist: {root}")

    meta = os.path.join(root, META_DIRNAME)
    fresh_meta = not os.path.isdir(meta)
    os.makedirs(meta, exist_ok=True)
    if fresh_meta:
        _hide_on_windows(meta)

    settings = read_library_settings(root)
    categories = settings.get("categories") or list(DEFAULT_CATEGORIES)
    for cat in categories:
        os.makedirs(os.path.join(root, cat), exist_ok=True)

    scans_rel = settings.get("scans_dir")
    if not scans_rel:
        scans_rel = LEGACY_SCANS_DIR if os.path.isdir(os.path.join(root, LEGACY_SCANS_DIR)) else SOURCES_DIRNAME

    ARCHIVE_ROOT = root
    META_DIR = meta
    DB_PATH = db_path or os.path.join(meta, "minerva.db")
    PROJECTS_DIR = os.path.join(root, "Projects")
    JOURNAL_SCANS_DIR = os.path.join(root, scans_rel)
    TOP_FOLDERS = categories

    imported_from = None
    if not os.path.exists(DB_PATH):
        legacy = find_legacy_db(root)
        if legacy:
            _copy_legacy_db(legacy, DB_PATH)
            imported_from = os.path.relpath(legacy, root)

    if not settings:
        write_library_settings(root, {"categories": categories, "scans_dir": scans_rel})

    init_db()
    return {"library_root": root, "imported_from": imported_from,
            "categories": categories, "scans_dir": scans_rel}


def create_library(parent, name):
    """Create a new, empty library folder with the default layout."""
    name = (name or "").strip()
    if not name or INVALID_FILENAME_CHARS_RE.search(name):
        raise ValueError("please choose a folder name without \\ / : * ? \" < > |")
    root = os.path.join(os.path.abspath(parent), name)
    if os.path.exists(root) and os.listdir(root):
        raise ValueError(f"{root} already exists and isn't empty; open it instead")
    os.makedirs(root, exist_ok=True)
    for sub in DEFAULT_CATEGORIES + ["Projects", SOURCES_DIRNAME]:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def is_configured():
    return ARCHIVE_ROOT is not None


FOLDER_TAG_RE = re.compile(r"^(?P<title>.*?)(?:\s-\s\[(?P<tag>[A-Za-z0-9]+)\])?$")
DRAFT_TAG_RE = re.compile(r"\[(C|J)\]")
INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]')

# Journal-source header parsing (for the "Journal Scan" panel). A journal-
# sourced [J] entry's own content carries this info in its header, e.g.:
#   Source: Blue Notebook Journal
#   ...
#   Source: Entry 52
# or  "Source entries: Blue Notebook - Master.txt, Entries 120-123"
_HEADER_DIVIDER_RE = re.compile(r"^=+\s*$", re.MULTILINE)
_SOURCE_JOURNAL_RE = re.compile(r"^Source:\s*(.+?)\s+Journal\s*$", re.MULTILINE)
_SOURCE_ENTRY_RE = re.compile(r"Entr(?:y|ies)\s+(\d+)(?:\s*[-\u2013\u2014]\s*(\d+))?")


# --------------------------------------------------------------------------
# DB setup
# --------------------------------------------------------------------------

def get_conn():
    if DB_PATH is None:
        raise RuntimeError("no library is open yet")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            tag TEXT UNIQUE NOT NULL,
            folder_path TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            top_folder TEXT NOT NULL,
            folder_name TEXT NOT NULL,
            title TEXT NOT NULL,
            project_tag TEXT,
            draft_filename TEXT,
            draft_tag TEXT,
            word_count INTEGER DEFAULT 0,
            rel_path TEXT UNIQUE NOT NULL,
            to_edit INTEGER DEFAULT 0,
            published INTEGER DEFAULT 0,
            published_where TEXT,
            to_record INTEGER DEFAULT 0,
            last_synced TEXT,
            has_journal_header INTEGER,
            source_journal TEXT,
            source_entry_num INTEGER
        );

        CREATE TABLE IF NOT EXISTS duplicate_pairs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_a TEXT NOT NULL,
            title_b TEXT NOT NULL,
            entry_a_id INTEGER,
            entry_b_id INTEGER,
            folder_hint TEXT,
            title_score REAL,
            content_score REAL,
            status TEXT DEFAULT 'unresolved',
            source TEXT,
            note TEXT,
            UNIQUE(title_a, title_b)
        );
        """
    )
    conn.commit()

    # migrations for databases created before these columns existed
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(entries)").fetchall()]
    for col, decl in [
        ("has_journal_header", "INTEGER"),
        ("source_journal", "TEXT"),
        ("source_entry_num", "INTEGER"),
        ("source_entry_last", "INTEGER"),
        ("draft_modified", "TEXT"),
        ("started", "TEXT"),
        ("line_count", "INTEGER DEFAULT 0"),
        ("stanza_count", "INTEGER DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {col} {decl}")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
    for col, decl in [("description", "TEXT"), ("created_at", "TEXT"), ("target_words", "INTEGER")]:
        if col not in cols:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col} {decl}")
    # writing activity per day, rebuilt from file dates on every sync, and a
    # daily snapshot of the library's size (for the Home page trends)
    conn.execute("""CREATE TABLE IF NOT EXISTS activity_days (
        day TEXT PRIMARY KEY, drafts INTEGER DEFAULT 0, revisions INTEGER DEFAULT 0,
        started INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS library_days (
        day TEXT PRIMARY KEY, entries INTEGER, words INTEGER)""")
    # the library's size when each day began, for word goals
    if "start_words" not in [r["name"] for r in conn.execute("PRAGMA table_info(library_days)")]:
        conn.execute("ALTER TABLE library_days ADD COLUMN start_words INTEGER")
    # the order a project's entries are read in (for later publishing tools)
    conn.execute("""CREATE TABLE IF NOT EXISTS project_order (
        project_id INTEGER NOT NULL, entry_id INTEGER NOT NULL, pos INTEGER NOT NULL,
        PRIMARY KEY (project_id, entry_id))""")
    from . import notes, outline, search, submissions, tags
    submissions.ensure_table(conn)
    search.ensure_table(conn)
    notes.ensure_table(conn)
    outline.ensure_table(conn)
    tags.ensure_tables(conn)
    conn.commit()

    conn.close()


# --------------------------------------------------------------------------
# Filesystem parsing helpers
# --------------------------------------------------------------------------

def parse_folder_name(folder_name):
    m = FOLDER_TAG_RE.match(folder_name)
    if not m:
        return folder_name, None
    return m.group("title"), m.group("tag")


def find_current_draft(entry_path):
    """Return the top-level draft filename for an entry folder, or None."""
    candidates = []
    try:
        names = os.listdir(entry_path)
    except OSError:
        return None
    for name in names:
        full = os.path.join(entry_path, name)
        if os.path.isfile(full) and name.lower().endswith(".txt"):
            candidates.append(name)
    if not candidates:
        return None
    tagged = [n for n in candidates if DRAFT_TAG_RE.search(n)]
    if len(tagged) == 1:
        return tagged[0]
    if len(tagged) > 1:
        # ambiguous - prefer [C] if present, else first
        c_tagged = [n for n in tagged if "[C]" in n]
        return c_tagged[0] if c_tagged else tagged[0]
    if len(candidates) == 1:
        return candidates[0]
    return candidates[0]


def parse_draft_tag(filename):
    m = DRAFT_TAG_RE.search(filename or "")
    return m.group(1) if m else None


def word_count_of(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return len(fh.read().split())
    except OSError:
        return 0


def safe_join(*parts):
    return os.path.normpath(os.path.join(*parts))


def unique_archive_name(archive_dir, base_name):
    """base_name already includes extension; append (2), (3)... on collision."""
    candidate = base_name
    stem, ext = os.path.splitext(base_name)
    n = 2
    while os.path.exists(os.path.join(archive_dir, candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


# --------------------------------------------------------------------------
# Scan / sync
# --------------------------------------------------------------------------

def _day(ts):
    return datetime.date.fromtimestamp(ts).isoformat()


def _entry_activity(entry_path, draft):
    """File dates for one entry: when its current draft was last saved, when
    it was started (its oldest file), and when each archived draft was saved.
    Only reads directory listings, never file contents."""
    def mtimes(path):
        try:
            with os.scandir(path) as it:
                return [e.stat().st_mtime for e in it if e.is_file()]
        except OSError:
            return []
    try:
        draft_ts = os.stat(os.path.join(entry_path, draft)).st_mtime
    except OSError:
        draft_ts = None
    archived = mtimes(os.path.join(entry_path, "Archive"))
    every = mtimes(entry_path) + archived + mtimes(os.path.join(entry_path, "Final"))
    return draft_ts, (min(every) if every else draft_ts), archived


def _carry_over_moved(conn, gone, before_ids):
    """An entry moved or re-tagged outside Minerva disappears from the index
    and comes back under a new id. When a vanished entry's title matches
    exactly one entry that is new in this sync, Minerva's own records for
    it (submissions, notes, tags, outline and project order) follow it."""
    from . import notes, submissions, tags
    new = conn.execute("SELECT id, title FROM entries").fetchall()
    new = [r for r in new if r["id"] not in before_ids]
    if not gone or not new:
        return
    by_title = {}
    for r in new:
        by_title.setdefault(r["title"].casefold(), []).append(r["id"])
    gone_titles = {}
    for g in gone:
        gone_titles[g["title"].casefold()] = gone_titles.get(g["title"].casefold(), 0) + 1
    for g in gone:
        key = g["title"].casefold()
        match = by_title.get(key, [])
        if len(match) != 1 or gone_titles[key] != 1:
            continue
        old_id, new_id = g["id"], match[0]
        submissions.move_entry(conn, old_id, new_id)
        notes.move_entry(conn, old_id, new_id)
        tags.move_entry(conn, old_id, new_id)
        conn.execute("UPDATE outline_items SET entry_id = ? WHERE entry_id = ?", (new_id, old_id))
        conn.execute("UPDATE project_order SET entry_id = ? WHERE entry_id = ?", (new_id, old_id))


def scan_and_sync(progress=None):
    """Index every entry folder. progress, if given, is called as
    progress(done, total) while the folders are read."""
    conn = get_conn()
    before_ids = {r["id"] for r in conn.execute("SELECT id FROM entries")}
    seen_rel_paths = set()
    scanned_any = False
    now = datetime.datetime.now().isoformat(timespec="seconds")
    activity = {}

    def bump(ts, key):
        if ts:
            activity.setdefault(_day(ts), {"drafts": 0, "revisions": 0, "started": 0})[key] += 1

    folders = []
    for top in TOP_FOLDERS:
        top_path = os.path.join(ARCHIVE_ROOT, top)
        if not os.path.isdir(top_path):
            continue
        scanned_any = True
        folders += [(top, top_path, name) for name in sorted(os.listdir(top_path))]
    if progress:
        progress(0, len(folders))
    for done, (top, top_path, folder_name) in enumerate(folders, 1):
        if progress and (done % 25 == 0 or done == len(folders)):
            progress(done, len(folders))
        entry_path = os.path.join(top_path, folder_name)
        if not os.path.isdir(entry_path):
            continue
        draft = find_current_draft(entry_path)
        if draft is None:
            continue
        title, tag = parse_folder_name(folder_name)
        draft_tag = parse_draft_tag(draft)
        try:
            with open(os.path.join(entry_path, draft), "r", encoding="utf-8", errors="ignore") as fh:
                draft_text = fh.read()
        except OSError:
            draft_text = ""
        wc = len(draft_text.split())
        lines, stanzas = text_counts(draft_text)

        # journal-source bridge: try the current draft first; if it's not
        # there (promoted to [C] and cleaned up, or a journal original was
        # merged in as this entry's archived draft), fall back to scanning
        # this entry's own Archive history for it. The upsert below only
        # ever overwrites the stored value with a freshly-found one - once
        # captured, it survives edits that don't happen to carry it.
        detected_journal, detected_entry_num, detected_last = parse_journal_source(draft_text)
        if not detected_journal:
            detected_journal, detected_entry_num, detected_last = _find_journal_source_in_archive(
                os.path.join(entry_path, "Archive")
            )

        rel_path = f"{top}/{folder_name}"
        seen_rel_paths.add(rel_path)

        draft_ts, started_ts, archived = _entry_activity(entry_path, draft)
        bump(draft_ts, "drafts")
        bump(started_ts, "started")
        for ts in archived:
            bump(ts, "revisions")
        draft_modified = _day(draft_ts) if draft_ts else None
        started = _day(started_ts) if started_ts else None

        conn.execute(
            """
            INSERT INTO entries
                (top_folder, folder_name, title, project_tag, draft_filename,
                 draft_tag, word_count, rel_path, last_synced,
                 source_journal, source_entry_num, source_entry_last, draft_modified, started,
                 line_count, stanza_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rel_path) DO UPDATE SET
                top_folder=excluded.top_folder,
                folder_name=excluded.folder_name,
                title=excluded.title,
                project_tag=excluded.project_tag,
                draft_filename=excluded.draft_filename,
                draft_tag=excluded.draft_tag,
                word_count=excluded.word_count,
                last_synced=excluded.last_synced,
                source_journal=COALESCE(excluded.source_journal, source_journal),
                source_entry_num=COALESCE(excluded.source_entry_num, source_entry_num),
                source_entry_last=CASE WHEN excluded.source_entry_num IS NULL THEN source_entry_last
                                       ELSE excluded.source_entry_last END,
                draft_modified=excluded.draft_modified,
                started=excluded.started,
                line_count=excluded.line_count,
                stanza_count=excluded.stanza_count
            """,
            (top, folder_name, title, tag, draft, draft_tag, wc, rel_path, now,
             detected_journal, detected_entry_num, detected_last, draft_modified, started,
             lines, stanzas),
        )
    conn.commit()

    # has_journal_header is purely derived from source_journal - only meaningful
    # for [J]-tagged entries (NULL = n/a for [C] entries, never journal-sourced
    # to begin with vs. bridge-lost is not a distinction we can make for those).
    # Recomputed in one pass so it can never drift out of sync with source_journal.
    conn.execute(
        """
        UPDATE entries
        SET has_journal_header = CASE
            WHEN draft_tag = 'J' THEN (source_journal IS NOT NULL)
            ELSE NULL
        END
        """
    )
    conn.commit()

    removed = 0
    if scanned_any:
        from . import notes
        notes.remember(conn)
        rows = conn.execute("SELECT id, title, rel_path FROM entries").fetchall()
        gone = []
        for row in rows:
            if row["rel_path"] not in seen_rel_paths:
                conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
                gone.append(row)
                removed += 1
        _carry_over_moved(conn, gone, before_ids)
        from . import tags
        tags.forget_missing(conn)
        conn.commit()

    if scanned_any:
        # file dates only show each draft's latest save, so a day stays in the
        # history once seen: overwriting a draft today mustn't erase the day
        # it was last written (and with it a streak)
        conn.executemany(
            """INSERT INTO activity_days (day, drafts, revisions, started) VALUES (?, ?, ?, ?)
               ON CONFLICT(day) DO UPDATE SET drafts = MAX(drafts, excluded.drafts),
                   revisions = MAX(revisions, excluded.revisions), started = MAX(started, excluded.started)""",
            [(d, a["drafts"], a["revisions"], a["started"]) for d, a in activity.items()])
    totals = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(word_count), 0) w FROM entries").fetchone()
    total = totals["c"]
    if scanned_any:
        today = datetime.date.today().isoformat()
        prev = conn.execute("SELECT words FROM library_days WHERE day < ? ORDER BY day DESC LIMIT 1",
                            (today,)).fetchone()
        # start_words is set once, by the day's first sync: the size the
        # library had at the end of the last day Minerva saw it
        conn.execute("""INSERT INTO library_days (day, entries, words, start_words) VALUES (?, ?, ?, ?)
                        ON CONFLICT(day) DO UPDATE SET entries = excluded.entries, words = excluded.words""",
                     (today, total, totals["w"], prev["words"] if prev else totals["w"]))
    conn.commit()
    if scanned_any:
        from . import notes, search
        search.refresh(conn)
        notes.reconcile(conn)
    conn.close()
    return {"total_entries": total, "removed": removed, "synced_at": now}


# --------------------------------------------------------------------------
# Entry read/save
# --------------------------------------------------------------------------

def get_entry_row(conn, entry_id):
    return conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()


def entry_dir(row):
    return os.path.join(ARCHIVE_ROOT, row["top_folder"], row["folder_name"])


def read_entry_content(row):
    path = os.path.join(entry_dir(row), row["draft_filename"])
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def list_archive(row):
    """Return list of {name, size, is_text} for the entry's Archive folder."""
    adir = os.path.join(entry_dir(row), "Archive")
    out = []
    if not os.path.isdir(adir):
        return out
    for name in sorted(os.listdir(adir)):
        full = os.path.join(adir, name)
        if not os.path.isfile(full):
            continue
        out.append(
            {
                "name": name,
                "size": os.path.getsize(full),
                "is_text": name.lower().endswith(".txt"),
                "modified": _iso(os.path.getmtime(full)),
            }
        )
    return out


def read_text(path):
    """A draft's text. Drafts that aren't UTF-8 are read as Windows-1252,
    the usual encoding of older Notepad files, so accents survive."""
    with open(path, "rb") as fh:
        data = fh.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def compare_drafts(row, a, b):
    """Word-level differences between two of an entry's drafts. a and b are
    archive filenames, or "" for the current draft."""
    from .organizing import word_diff

    def load(name):
        if name:
            adir = os.path.join(entry_dir(row), "Archive")
            path = os.path.normpath(os.path.join(adir, name))
            if not path.startswith(os.path.normpath(adir) + os.sep) or not name.lower().endswith(".txt"):
                raise ValueError("invalid archive filename")
        else:
            path = os.path.join(entry_dir(row), row["draft_filename"])
        text = read_text(path)
        return text, {"name": name or row["draft_filename"], "current": not name,
                      "words": len(text.split()), "modified": _iso(os.path.getmtime(path))}

    ta, ia = load(a)
    tb, ib = load(b)
    changes = word_diff(ta, tb)
    added = sum(len(t.split()) for op, t in changes if op == "ins")
    removed = sum(len(t.split()) for op, t in changes if op == "del")
    return {"a": ia, "b": ib, "changes": changes, "added": added, "removed": removed,
            "same": not added and not removed and ta == tb}


def read_archive_file(row, filename):
    adir = os.path.join(entry_dir(row), "Archive")
    full = os.path.normpath(os.path.join(adir, filename))
    if not full.startswith(os.path.normpath(adir)):
        raise ValueError("invalid archive filename")
    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _archive_current_draft(row):
    """Move the entry's current draft file into Archive/, timestamped.
    Returns the archive filename used."""
    edir = entry_dir(row)
    adir = os.path.join(edir, "Archive")
    os.makedirs(adir, exist_ok=True)
    today = datetime.date.today().isoformat()
    base_name = f"{row['title']} (edited {today}).txt"
    archive_name = unique_archive_name(adir, base_name)
    src = os.path.join(edir, row["draft_filename"])
    dst = os.path.join(adir, archive_name)
    if os.path.exists(src):
        shutil.move(src, dst)
    return archive_name


def _note_save(conn, row, archived):
    """Keep the Home page's activity current after a save in Minerva, without
    waiting for the next sync. When the old draft is archived it becomes that
    day's revision; when it's overwritten, its day keeps the credit."""
    today = datetime.date.today().isoformat()
    old = row["draft_modified"]

    def add(day, col, n):
        conn.execute("INSERT OR IGNORE INTO activity_days (day) VALUES (?)", (day,))
        conn.execute(f"UPDATE activity_days SET {col} = MAX(0, {col} + ?) WHERE day = ?", (n, day))

    if old and (archived or old == today):
        add(old, "drafts", -1)  # it's now an archived revision, or saved again the same day
    if old and archived:
        add(old, "revisions", 1)
    add(today, "drafts", 1)
    conn.execute("UPDATE entries SET draft_modified = ? WHERE id = ?", (today, row["id"]))


def text_counts(text):
    """(lines, stanzas) of a draft, not counting a transcription header:
    lines with any words on them, and groups of lines between blank ones."""
    from . import sharing
    body = sharing.strip_header(text or "")
    lines = [ln for ln in body.split("\n") if ln.strip()]
    stanzas = len([b for b in re.split(r"\n\s*\n", body.strip("\n")) if b.strip()])
    return len(lines), stanzas


def _reindex(conn, entry_id):
    from . import search
    row = get_entry_row(conn, entry_id)
    lines, stanzas = text_counts(read_entry_content(row))
    conn.execute("UPDATE entries SET line_count = ?, stanza_count = ? WHERE id = ?", (lines, stanzas, entry_id))
    search.index_entry(conn, row)


def save_entry_content(conn, entry_id, content, mode):
    """mode: 'overwrite' or 'archive'."""
    row = get_entry_row(conn, entry_id)
    if row is None:
        raise ValueError("entry not found")
    edir = entry_dir(row)

    if mode == "overwrite":
        path = os.path.join(edir, row["draft_filename"])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        conn.execute(
            "UPDATE entries SET word_count = ? WHERE id = ?",
            (len(content.split()), entry_id),
        )
        _note_save(conn, row, archived=False)
        _reindex(conn, entry_id)
        conn.commit()
        return {"draft_filename": row["draft_filename"], "draft_tag": row["draft_tag"]}

    if mode == "archive":
        _archive_current_draft(row)
        new_filename = f"{row['title']} [C].txt"
        path = os.path.join(edir, new_filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        conn.execute(
            "UPDATE entries SET draft_filename = ?, draft_tag = 'C', word_count = ? WHERE id = ?",
            (new_filename, len(content.split()), entry_id),
        )
        _note_save(conn, row, archived=True)
        _reindex(conn, entry_id)
        conn.commit()
        return {"draft_filename": new_filename, "draft_tag": "C"}

    raise ValueError("mode must be 'overwrite' or 'archive'")


def restore_from_archive(conn, entry_id, archive_filename):
    row = get_entry_row(conn, entry_id)
    if row is None:
        raise ValueError("entry not found")
    content = read_archive_file(row, archive_filename)
    # archive the current draft first (non-destructive), then write the restored
    # content as the new current draft, promoted to [C].
    return save_entry_content(conn, entry_id, content, mode="archive")


# --------------------------------------------------------------------------
# Flags
# --------------------------------------------------------------------------

def update_flags(conn, entry_id, fields):
    allowed = {"to_edit", "published", "published_where", "to_record"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("to_edit", "published", "to_record"):
            v = 1 if v else 0
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return
    vals.append(entry_id)
    conn.execute(f"UPDATE entries SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


# --------------------------------------------------------------------------
# Projects / tagging / category
# --------------------------------------------------------------------------

def _entry_mtime(row):
    """When the entry's current draft was last changed, or None."""
    try:
        return os.path.getmtime(os.path.join(ARCHIVE_ROOT, row["top_folder"], row["folder_name"],
                                             row["draft_filename"] or ""))
    except (OSError, TypeError):
        return None


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def project_entries(conn, project):
    """A project's entries in the order the user set; entries added since
    then follow, by title."""
    rows = conn.execute("SELECT * FROM entries WHERE project_tag = ? ORDER BY title COLLATE NOCASE",
                        (project["tag"],)).fetchall()
    pos = {r["entry_id"]: r["pos"] for r in conn.execute(
        "SELECT entry_id, pos FROM project_order WHERE project_id = ?", (project["id"],))}
    rows = sorted(rows, key=lambda r: (r["id"] not in pos, pos.get(r["id"], 0)))
    out = []
    for r in rows:
        mtime = _entry_mtime(r)
        out.append({"id": r["id"], "title": r["title"], "category": r["top_folder"],
                    "word_count": r["word_count"] or 0, "draft_tag": r["draft_tag"],
                    "published": r["published"], "to_edit": r["to_edit"],
                    "last_edited": _iso(mtime)})
    return out


def _project_summary(conn, r):
    entries = project_entries(conn, r)
    cats = {}
    for e in entries:
        cats[e["category"]] = cats.get(e["category"], 0) + 1
    edits = [e["last_edited"] for e in entries if e["last_edited"]]
    return dict(r) | {
        "entry_count": len(entries),
        "word_count": sum(e["word_count"] for e in entries),
        "categories": dict(sorted(cats.items(), key=lambda kv: -kv[1])),
        "last_edited": max(edits) if edits else None,
        "published_count": sum(1 for e in entries if e["published"]),
    }, entries


def list_projects(conn):
    rows = conn.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE").fetchall()
    return [_project_summary(conn, r)[0] for r in rows]


def _project_row(conn, project_id):
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ValueError("That project no longer exists.")
    return row


def get_project(conn, project_id):
    summary, entries = _project_summary(conn, _project_row(conn, project_id))
    return summary | {"entries": entries}


def create_project(conn, name, tag, description=""):
    name = name.strip()
    tag = tag.strip().upper()
    if not name or not tag:
        raise ValueError("name and tag are required")
    if INVALID_FILENAME_CHARS_RE.search(name):
        raise ValueError(r'a project name cannot contain any of: \ / : * ? " < > |')
    if not re.fullmatch(r"[A-Z0-9]+", tag):
        raise ValueError("a tag can only use letters and numbers")
    folder_path = os.path.join("Projects", name)
    full = os.path.join(ARCHIVE_ROOT, folder_path)
    os.makedirs(full, exist_ok=True)
    conn.execute(
        "INSERT INTO projects (name, tag, folder_path, description, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, tag, folder_path, (description or "").strip(),
         datetime.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def update_project(conn, project_id, name=None, description=None, target_words=False):
    """Rename a project or change its description. Renaming also renames its
    folder under Projects, when that folder exists and the new name is free.
    The tag stays, since every tagged entry's folder name carries it."""
    row = _project_row(conn, project_id)
    if description is not None:
        conn.execute("UPDATE projects SET description = ? WHERE id = ?", (description.strip(), project_id))
    if target_words is not False:
        try:
            target = int(target_words) if target_words not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("the target should be a number of words") from None
        if target is not None and target < 0:
            raise ValueError("the target can't be negative")
        conn.execute("UPDATE projects SET target_words = ? WHERE id = ?", (target or None, project_id))
    if name is not None and name.strip() != row["name"]:
        name = name.strip()
        if not name:
            raise ValueError("a project needs a name")
        if INVALID_FILENAME_CHARS_RE.search(name):
            raise ValueError(r'a project name cannot contain any of: \ / : * ? " < > |')
        if conn.execute("SELECT 1 FROM projects WHERE name = ? AND id != ?", (name, project_id)).fetchone():
            raise ValueError(f'there is already a project called "{name}"')
        folder_path = row["folder_path"]
        old_full = os.path.join(ARCHIVE_ROOT, folder_path)
        new_rel = os.path.join("Projects", name)
        new_full = os.path.join(ARCHIVE_ROOT, new_rel)
        if os.path.isdir(old_full) and not os.path.exists(new_full):
            shutil.move(old_full, new_full)
            folder_path = new_rel
        elif not os.path.exists(old_full):
            folder_path = new_rel
        conn.execute("UPDATE projects SET name = ?, folder_path = ? WHERE id = ?", (name, folder_path, project_id))
    conn.commit()
    return get_project(conn, project_id)


def set_project_order(conn, project_id, entry_ids):
    _project_row(conn, project_id)
    conn.execute("DELETE FROM project_order WHERE project_id = ?", (project_id,))
    conn.executemany("INSERT INTO project_order VALUES (?, ?, ?)",
                     [(project_id, int(eid), i) for i, eid in enumerate(entry_ids)])
    conn.commit()


def delete_project(conn, project_id):
    """Remove a project but keep every entry: each tagged entry's folder loses
    its " - [TAG]" suffix and stays in its category. The project's folder
    under Projects is left on disk untouched. Refuses up front, changing
    nothing, if any untagged folder name is already taken."""
    row = _project_row(conn, project_id)
    entries = conn.execute("SELECT * FROM entries WHERE project_tag = ?", (row["tag"],)).fetchall()
    clashes = [f"{e['top_folder']}/{e['title']}" for e in entries
               if os.path.exists(os.path.join(ARCHIVE_ROOT, e["top_folder"], e["title"]))]
    if clashes:
        raise ValueError("Nothing was changed. These entries can't drop the project tag because a folder "
                         "with the plain name already exists: " + ", ".join(clashes))
    for e in entries:
        set_entry_project(conn, e["id"], None)
    conn.execute("DELETE FROM project_order WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM outline_items WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return {"untagged": len(entries), "folder_kept": row["folder_path"]}


def set_entry_project(conn, entry_id, tag):
    """tag = a project tag string, or None/'' to untag."""
    row = get_entry_row(conn, entry_id)
    if row is None:
        raise ValueError("entry not found")
    tag = (tag or "").strip().upper() or None

    old_dir = entry_dir(row)
    new_folder_name = row["title"] if not tag else f"{row['title']} - [{tag}]"
    if new_folder_name == row["folder_name"]:
        conn.execute("UPDATE entries SET project_tag = ? WHERE id = ?", (tag, entry_id))
        conn.commit()
        return

    new_dir = os.path.join(ARCHIVE_ROOT, row["top_folder"], new_folder_name)
    if os.path.exists(new_dir):
        raise ValueError(f"a folder named '{new_folder_name}' already exists")
    shutil.move(old_dir, new_dir)

    new_rel_path = f"{row['top_folder']}/{new_folder_name}"
    conn.execute(
        "UPDATE entries SET folder_name = ?, project_tag = ?, rel_path = ? WHERE id = ?",
        (new_folder_name, tag, new_rel_path, entry_id),
    )
    conn.commit()


def set_entry_category(conn, entry_id, new_category):
    if new_category not in TOP_FOLDERS:
        raise ValueError(f"category must be one of {TOP_FOLDERS}")
    row = get_entry_row(conn, entry_id)
    if row is None:
        raise ValueError("entry not found")
    if new_category == row["top_folder"]:
        return

    old_dir = entry_dir(row)
    new_dir = os.path.join(ARCHIVE_ROOT, new_category, row["folder_name"])
    if os.path.exists(new_dir):
        raise ValueError(f"a folder named '{row['folder_name']}' already exists in {new_category}")
    os.makedirs(os.path.join(ARCHIVE_ROOT, new_category), exist_ok=True)
    shutil.move(old_dir, new_dir)

    new_rel_path = f"{new_category}/{row['folder_name']}"
    conn.execute(
        "UPDATE entries SET top_folder = ?, rel_path = ? WHERE id = ?",
        (new_category, new_rel_path, entry_id),
    )
    conn.commit()


class CategoryError(ValueError):
    user_facing = True


def _reserved_top_names():
    names = {META_DIRNAME, "Projects", "Archive"}
    if JOURNAL_SCANS_DIR:
        names.add(os.path.relpath(JOURNAL_SCANS_DIR, ARCHIVE_ROOT).split(os.sep)[0])
    return {n.casefold() for n in names}


def _clean_category(name):
    name = " ".join(str(name or "").split()).rstrip(" .")
    if not name:
        raise CategoryError("Give the category a name.")
    if name.startswith("."):
        raise CategoryError("A category name can't start with a dot.")
    if INVALID_FILENAME_CHARS_RE.search(name) or len(name) > 60:
        raise CategoryError('A category name can\'t be longer than 60 characters or use \\ / : * ? " < > |.')
    if name.casefold() in _reserved_top_names():
        raise CategoryError(f'"{name}" is already used by Minerva for something else.')
    return name


def _save_categories(categories):
    global TOP_FOLDERS
    settings = read_library_settings(ARCHIVE_ROOT)
    settings["categories"] = categories
    write_library_settings(ARCHIVE_ROOT, settings)
    TOP_FOLDERS = categories


def add_category(name):
    """Add a category. Its folder is created, or an existing folder of that
    name becomes a category (its entries appear at the next sync)."""
    name = _clean_category(name)
    if any(c.casefold() == name.casefold() for c in TOP_FOLDERS):
        raise CategoryError(f'There is already a category called "{name}".')
    path = os.path.join(ARCHIVE_ROOT, name)
    if os.path.exists(path) and not os.path.isdir(path):
        raise CategoryError(f'A file called "{name}" is in the way.')
    os.makedirs(path, exist_ok=True)
    _save_categories(TOP_FOLDERS + [name])
    return name


def rename_category(conn, old, new):
    """Rename a category's folder and keep every entry in it (and everything
    attached to them) by updating their paths in place."""
    if old not in TOP_FOLDERS:
        raise CategoryError(f'There is no category called "{old}".')
    new = _clean_category(new)
    if new == old:
        return new
    if any(c.casefold() == new.casefold() and c != old for c in TOP_FOLDERS):
        raise CategoryError(f'There is already a category called "{new}".')
    src, dst = os.path.join(ARCHIVE_ROOT, old), os.path.join(ARCHIVE_ROOT, new)
    case_only = old.casefold() == new.casefold()
    if os.path.exists(dst) and not case_only:
        raise CategoryError(f'A folder called "{new}" already exists in your library.')
    if os.path.isdir(src):
        if case_only:  # Windows can't rename "poetry" to "Poetry" in one step
            tmp = src + ".renaming"
            os.rename(src, tmp)
            os.rename(tmp, dst)
        else:
            os.rename(src, dst)
    else:
        os.makedirs(dst, exist_ok=True)
    rows = conn.execute("SELECT id, folder_name FROM entries WHERE top_folder = ?", (old,)).fetchall()
    for r in rows:
        conn.execute("UPDATE entries SET top_folder = ?, rel_path = ? WHERE id = ?",
                     (new, f"{new}/{r['folder_name']}", r["id"]))
    conn.commit()
    _save_categories([new if c == old else c for c in TOP_FOLDERS])
    return new


def remove_category(conn, name):
    """Stop treating a folder as a category. Only allowed when it holds no
    entries; the (empty) folder itself is left where it is."""
    if name not in TOP_FOLDERS:
        raise CategoryError(f'There is no category called "{name}".')
    if len(TOP_FOLDERS) == 1:
        raise CategoryError("A library needs at least one category.")
    n = conn.execute("SELECT COUNT(*) c FROM entries WHERE top_folder = ?", (name,)).fetchone()["c"]
    if n:
        raise CategoryError(f'"{name}" still has {n} entr{"y" if n == 1 else "ies"}. Move them to another category first.')
    _save_categories([c for c in TOP_FOLDERS if c != name])


def _retitle_filename(filename, old_title, new_title):
    """Swap a leading old_title for new_title, preserving whatever tag/suffix
    follows (' [C].txt', ' (edited 2026-01-01).txt', etc). Filenames that
    don't start with old_title (unexpected naming) are left untouched."""
    if filename.startswith(old_title):
        return new_title + filename[len(old_title):]
    return filename


def rename_entry(conn, entry_id, new_title):
    """Renames an entry's title, which renames its folder, its current draft
    file, and any Archive files that still carry the old title as a prefix.
    Non-destructive: this only ever renames files in place, nothing is deleted."""
    new_title = (new_title or "").strip()
    if not new_title:
        raise ValueError("title cannot be empty")
    if INVALID_FILENAME_CHARS_RE.search(new_title):
        raise ValueError(r'title cannot contain any of: \ / : * ? " < > |')

    row = get_entry_row(conn, entry_id)
    if row is None:
        raise ValueError("entry not found")

    old_title = row["title"]
    if new_title == old_title:
        result = dict(row)
        result["warnings"] = []
        return result

    new_folder_name = new_title if not row["project_tag"] else f"{new_title} - [{row['project_tag']}]"
    old_dir = entry_dir(row)
    new_dir = os.path.join(ARCHIVE_ROOT, row["top_folder"], new_folder_name)

    if os.path.normpath(new_dir) != os.path.normpath(old_dir) and os.path.exists(new_dir):
        raise ValueError(f"a folder named '{new_folder_name}' already exists in {row['top_folder']}")

    shutil.move(old_dir, new_dir)

    warnings = []

    # rename the current draft file to match, preserving its [C]/[J] tag
    new_draft_filename = row["draft_filename"]
    if row["draft_filename"]:
        candidate = _retitle_filename(row["draft_filename"], old_title, new_title)
        if candidate != row["draft_filename"]:
            old_draft_path = os.path.join(new_dir, row["draft_filename"])
            new_draft_path = os.path.join(new_dir, candidate)
            if os.path.exists(old_draft_path):
                os.rename(old_draft_path, new_draft_path)
                new_draft_filename = candidate
        else:
            # the draft filename didn't start with the old title as expected -
            # something (a past manual rename, an odd import) broke the usual
            # convention, so we can't safely retitle it. Surface this instead
            # of quietly leaving a now-mismatched filename behind.
            warnings.append(
                f'current draft file "{row["draft_filename"]}" didn\'t start with '
                f'the old title, so it was left unrenamed and no longer matches the new title'
            )

    # rename any archived files that still carry the old title as their prefix,
    # so they stay consistent with the entry's new name (silently skips anything
    # that doesn't match, e.g. "Merged - <other title>" folders from past merges -
    # that's expected, not a warning)
    archive_dir = os.path.join(new_dir, "Archive")
    if os.path.isdir(archive_dir):
        for name in os.listdir(archive_dir):
            new_name = _retitle_filename(name, old_title, new_title)
            if new_name == name:
                continue
            src = os.path.join(archive_dir, name)
            dst = os.path.join(archive_dir, new_name)
            if os.path.exists(dst):
                new_name = unique_archive_name(archive_dir, new_name)
                dst = os.path.join(archive_dir, new_name)
            try:
                os.rename(src, dst)
            except OSError as exc:
                # leave this one file under its old name rather than abort the whole
                # rename, but say so - a silently-stale archive filename is exactly
                # the kind of thing that's easy to miss later.
                warnings.append(f'could not rename archive file "{name}": {exc}')

    new_rel_path = f"{row['top_folder']}/{new_folder_name}"
    conn.execute(
        "UPDATE entries SET title = ?, folder_name = ?, draft_filename = ?, rel_path = ? WHERE id = ?",
        (new_title, new_folder_name, new_draft_filename, new_rel_path, entry_id),
    )
    conn.commit()
    result = dict(get_entry_row(conn, entry_id))
    result["warnings"] = warnings
    return result


# --------------------------------------------------------------------------
# Journal scan lookup (for journal-sourced [J] entries)
# --------------------------------------------------------------------------

def parse_journal_source(content):
    """Pull (journal_name, entry_num) out of a [J] entry's own header text,
    e.g. 'Source: Blue Notebook Journal' + 'Source: Entry 52' (or
    'Source entries: Blue Notebook - Master.txt, Entries 120-123'). Only the
    header block (before the first '====' divider) is searched, so a title or
    body that happens to contain the word "Entry" can't be mistaken for this.
    Returns (journal, first entry, last entry); the last is None unless the
    entry joins a range of Master entries. (None, None, None) if the entry
    isn't journal-sourced or the header doesn't match the convention."""
    if not content:
        return None, None, None
    divider = _HEADER_DIVIDER_RE.search(content)
    header = content[: divider.start()] if divider else content[:600]

    jm = _SOURCE_JOURNAL_RE.search(header)
    if not jm:
        return None, None, None
    journal = jm.group(1).strip()

    em = _SOURCE_ENTRY_RE.search(header)
    entry_num = int(em.group(1)) if em else None
    last = int(em.group(2)) if em and em.group(2) else None
    if last is not None and not entry_num < last <= entry_num + 500:
        last = None
    return journal, entry_num, last


def _find_journal_source_in_archive(archive_dir):
    """Fallback for when an entry's current draft no longer carries a
    journal-source header - recursively check its own Archive history for the
    first .txt file that still has one. Covers a [J]->[C] promotion that
    cleaned the header out of the new draft, and a journal original folded in
    later via merge (which nests it under Archive/Merged - <title>/...)."""
    if not archive_dir or not os.path.isdir(archive_dir):
        return None, None, None
    for root, _dirs, files in os.walk(archive_dir):
        for name in sorted(files):
            if not name.lower().endswith(".txt"):
                continue
            try:
                with open(os.path.join(root, name), "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            journal, entry_num, last = parse_journal_source(text)
            if journal:
                return journal, entry_num, last
    return None, None, None


def find_journal_scan(journal, entry_num, last_num=None):
    """Given a journal name and its entry number (as parsed from an entry's
    own header), locate the scan PDF and a short OCR excerpt from that
    journal's Master transcript under References/Old Project/Journal Scans.
    last_num, for an entry joined from a run of Master entries, adds the
    pages of every entry through it. Always returns a dict; check
    ["available"] before using pdf_rel_path."""
    result = {"journal": journal, "entry_num": entry_num, "available": False}
    if last_num:
        result["entry_last"] = last_num
    if not journal or not entry_num:
        return result

    jdir = os.path.normpath(os.path.join(JOURNAL_SCANS_DIR, journal))
    if not jdir.startswith(os.path.normpath(JOURNAL_SCANS_DIR) + os.sep) or not os.path.isdir(jdir):
        result["reason"] = "no journal folder found for this entry in the library's scans folder"
        return result

    master_path = os.path.join(jdir, f"{journal} - Master.txt")
    if not os.path.isfile(master_path):
        result["reason"] = f'"{journal}" hasn\'t been transcribed yet (no Master.txt for it)'
        return result

    with open(master_path, "r", encoding="utf-8", errors="ignore") as fh:
        master_text = fh.read()

    m = re.search(rf"^ENTRY\s+{entry_num}\s*\(([^)]*)\)", master_text, re.MULTILINE)
    if not m:
        result["reason"] = f"entry {entry_num} not found in \"{journal} - Master.txt\""
        return result

    label = m.group(1).strip()
    result["label"] = label

    from . import pagelinks, scanning  # both build on this module

    try:
        scans = scanning.list_scans(journal)
    except scanning.ScanError:
        scans = []
    by_num = {s["num"]: s for s in scans}
    # The pages come from Minerva's page links (rebuilt from the text), not
    # the label, whose page numbers are often off in older Masters.
    entries = scanning.parse_master(master_text)["entries"]
    links = pagelinks.links_for(journal, entries, list(by_num))
    link = links.get(int(entry_num))
    pages = [[s, p] for s, p in (link["pages"] if link else []) if s in by_num]
    for n in range(int(entry_num) + 1, int(last_num or 0) + 1):
        more = links.get(n)
        pages += [[s, p] for s, p in (more["pages"] if more else []) if s in by_num and [s, p] not in pages]
    result["pages"] = [{"scan": s, "page": p, "filename": by_num[s]["filename"]} for s, p in pages]
    result["link_note"] = pagelinks.describe(link)
    pdf_path = None
    if pages:
        result["scan_num"], result["page"] = pages[0]
        pdf_path = by_num[pages[0][0]]["path"]
    else:
        scan_m = re.search(r"Scan\s+(\d+)", label)
        if scan_m and int(scan_m.group(1)) in by_num:
            result["scan_num"] = int(scan_m.group(1))
        elif len(scans) == 1:
            result["scan_num"] = scans[0]["num"]
        if result.get("scan_num"):
            pdf_path = by_num[result["scan_num"]]["path"]

    if pdf_path is None:
        result["reason"] = "could not locate the scan PDF for this entry"
        return result

    last = int(last_num or entry_num)
    excerpt = "\n\n".join(e["body"].strip() for e in entries if int(entry_num) <= e["num"] <= last)
    if len(excerpt) > 1200:
        excerpt = excerpt[:1200].rstrip() + "…"

    result.update({
        "available": True,
        "pdf_name": os.path.basename(pdf_path),
        "pdf_rel_path": os.path.relpath(pdf_path, ARCHIVE_ROOT),
        "excerpt": excerpt,
    })
    return result


def find_journal_scan_for_entry(row):
    """Look up the scan for an entry using its stored source_journal /
    source_entry_num (captured at sync time - see scan_and_sync - and sticky
    across edits, promotions, and merges). Returns None if this entry has no
    known journal source at all (so the UI can hide the panel entirely, vs.
    showing an explanatory 'not available' message)."""
    journal = row["source_journal"]
    entry_num = row["source_entry_num"]
    if not journal:
        return None
    last = row["source_entry_last"] if "source_entry_last" in row.keys() else None
    return find_journal_scan(journal, entry_num, last)


# --------------------------------------------------------------------------
# Docs (in-app documentation, read-only)
# --------------------------------------------------------------------------

DOCS_DIR = os.path.join(HERE, "docs")


def list_docs():
    """Returns [{name, title, size}] for every .txt file in the docs/ folder
    next to this script, alphabetically. 'title' strips the .txt extension
    for display."""
    if not os.path.isdir(DOCS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(DOCS_DIR)):
        if not name.lower().endswith(".txt"):
            continue
        full = os.path.join(DOCS_DIR, name)
        if not os.path.isfile(full):
            continue
        out.append({
            "name": name,
            "title": os.path.splitext(name)[0],
            "size": os.path.getsize(full),
        })
    return out


def read_doc(name):
    full = os.path.normpath(os.path.join(DOCS_DIR, name))
    if not full.startswith(os.path.normpath(DOCS_DIR) + os.sep):
        raise ValueError("invalid doc name")
    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


HOWTO_DIR = os.path.join(DOCS_DIR, "howto")
_HOWTO_TITLE_RE = re.compile(r"<h1>(.*?)</h1>", re.S)
_HOWTO_SUMMARY_RE = re.compile(r'data-summary="([^"]*)"')
_HOWTO_COVER_RE = re.compile(r'<svg class="howto-cover".*?</svg>', re.S)


def list_howtos():
    """The illustrated how-tos (docs/howto/*.html), in number order, with
    the title, one-line summary and cover art the Home page previews use."""
    if not os.path.isdir(HOWTO_DIR):
        return []
    out = []
    def order(name):
        num = re.match(r"\d+", name)
        return (int(num.group(0)) if num else 10 ** 6, name.lower())

    for name in sorted(os.listdir(HOWTO_DIR), key=order):
        if not name.lower().endswith(".html"):
            continue
        html = read_howto(name)
        title = _HOWTO_TITLE_RE.search(html)
        summary = _HOWTO_SUMMARY_RE.search(html)
        art = _HOWTO_COVER_RE.search(html)
        out.append({
            "name": name,
            "title": title.group(1).strip() if title else os.path.splitext(name)[0],
            "summary": summary.group(1) if summary else "",
            "cover": art.group(0) if art else "",
        })
    return out


def read_howto(name):
    full = os.path.normpath(os.path.join(HOWTO_DIR, name))
    if not full.startswith(os.path.normpath(HOWTO_DIR) + os.sep) or not full.endswith(".html"):
        raise ValueError("invalid how-to name")
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Duplicate pairs
# --------------------------------------------------------------------------

def list_duplicates(conn, status=None):
    q = "SELECT * FROM duplicate_pairs"
    params = ()
    if status:
        q += " WHERE status = ?"
        params = (status,)
    q += " ORDER BY (status = 'unresolved') DESC, COALESCE(content_score, 0) DESC, COALESCE(title_score, 0) DESC"
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    for r in rows:
        r["entry_a"] = dict(get_entry_row(conn, r["entry_a_id"])) if r["entry_a_id"] else None
        r["entry_b"] = dict(get_entry_row(conn, r["entry_b_id"])) if r["entry_b_id"] else None
    return rows


def set_duplicate_status(conn, pair_id, status):
    if status not in ("unresolved", "confirmed", "not_duplicate", "merged"):
        raise ValueError("invalid status")
    conn.execute("UPDATE duplicate_pairs SET status = ? WHERE id = ?", (status, pair_id))
    conn.commit()


def _merge_entry_folders(conn, winner, loser):
    """Core non-destructive merge, shared by merge_duplicate (pre-seeded pairs)
    and merge_entries (ad-hoc, any two entries): moves the loser's whole
    folder - including its own Archive - into the winner's Archive as
    'Merged - <title>', then drops the loser from the entries index.

    If the loser brings a journal-source bridge the winner doesn't already
    have (e.g. folding a raw journal entry in as another entry's original
    draft), it's picked up immediately rather than waiting for the next
    Rescan. Returns the archive folder name used."""
    winner_archive = os.path.join(entry_dir(winner), "Archive")
    os.makedirs(winner_archive, exist_ok=True)
    dest_name = unique_archive_name(winner_archive, f"Merged - {loser['title']}")
    dest_path = os.path.join(winner_archive, dest_name)
    shutil.move(entry_dir(loser), dest_path)

    from . import notes, submissions, tags
    submissions.move_entry(conn, loser["id"], winner["id"])
    notes.move_entry(conn, loser["id"], winner["id"])
    tags.move_entry(conn, loser["id"], winner["id"])
    conn.execute("DELETE FROM entries WHERE id = ?", (loser["id"],))

    if not winner["source_journal"]:
        journal, entry_num, last = _find_journal_source_in_archive(winner_archive)
        if journal:
            conn.execute(
                """
                UPDATE entries
                SET source_journal = ?, source_entry_num = ?, source_entry_last = ?,
                    has_journal_header = CASE WHEN draft_tag = 'J' THEN 1 ELSE has_journal_header END
                WHERE id = ?
                """,
                (journal, entry_num, last, winner["id"]),
            )

    conn.commit()
    return dest_name


def merge_duplicate(conn, pair_id, keep):
    """keep: 'a' or 'b'. Moves the loser's whole entry folder into the winner's
    Archive/ (non-destructively) and drops the loser from the entries index."""
    if keep not in ("a", "b"):
        raise ValueError("keep must be 'a' or 'b'")
    pair = conn.execute("SELECT * FROM duplicate_pairs WHERE id = ?", (pair_id,)).fetchone()
    if pair is None:
        raise ValueError("pair not found")

    winner_id = pair["entry_a_id"] if keep == "a" else pair["entry_b_id"]
    loser_id = pair["entry_b_id"] if keep == "a" else pair["entry_a_id"]
    if not winner_id or not loser_id:
        raise ValueError("both sides of this pair must be linked to a current entry to merge")

    winner = get_entry_row(conn, winner_id)
    loser = get_entry_row(conn, loser_id)
    if winner is None or loser is None:
        raise ValueError("linked entry no longer exists - try rescanning")

    dest_name = _merge_entry_folders(conn, winner, loser)
    conn.execute("UPDATE duplicate_pairs SET status = 'merged' WHERE id = ?", (pair_id,))
    conn.commit()
    return {"kept": dict(get_entry_row(conn, winner_id)), "archived_as": dest_name}


def merge_entries(conn, keep_entry_id, other_entry_id):
    """Ad-hoc merge of two arbitrary entries - not necessarily a pre-seeded
    duplicate pair. E.g. folding a raw journal entry in as another entry's
    original draft. Same non-destructive mechanics as merge_duplicate."""
    if keep_entry_id == other_entry_id:
        raise ValueError("can't merge an entry into itself")
    keep = get_entry_row(conn, keep_entry_id)
    other = get_entry_row(conn, other_entry_id)
    if keep is None or other is None:
        raise ValueError("both entries must exist")

    dest_name = _merge_entry_folders(conn, keep, other)
    return {"kept": dict(get_entry_row(conn, keep_entry_id)), "archived_as": dest_name}

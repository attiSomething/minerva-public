"""Tags and saved collections.

An entry has one category and at most one project, but any number of tags
("elegy", "submission-ready", a person's name), so a piece can sit in many
groups at once. A collection is a saved set of Entries filters (a tag, a
category, a search...) that stays one click away.

Both live in .minerva's index only; nothing is written to the library.
"""

import datetime
import json

MAX_TAG = 40
MAX_TAGS_PER_ENTRY = 30
FILTER_KEYS = ("search", "mode", "category", "project", "published", "to_edit", "to_record",
               "needs_review", "tag", "current")


class TagError(ValueError):
    user_facing = True


def ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS entry_tags (
        entry_id INTEGER NOT NULL,
        tag TEXT NOT NULL COLLATE NOCASE,
        PRIMARY KEY (entry_id, tag))""")
    conn.execute("CREATE INDEX IF NOT EXISTS entry_tags_tag ON entry_tags(tag)")
    conn.execute("""CREATE TABLE IF NOT EXISTS collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        filters TEXT NOT NULL,
        created_at TEXT)""")


def clean(tag):
    tag = " ".join(str(tag or "").replace(",", " ").split()).lstrip("#").strip()
    return tag[:MAX_TAG].strip()


def _entry(conn, entry_id):
    row = conn.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise TagError("That entry isn't in the library any more. Reload and try again.")
    return row


def for_entry(conn, entry_id):
    ensure_tables(conn)
    return [r["tag"] for r in conn.execute(
        "SELECT tag FROM entry_tags WHERE entry_id = ? ORDER BY tag COLLATE NOCASE", (entry_id,))]


def for_entries(conn, entry_ids):
    """{entry id: [tags]} for a page of entries."""
    ensure_tables(conn)
    ids = list(entry_ids)
    out = {i: [] for i in ids}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        q = f"SELECT entry_id, tag FROM entry_tags WHERE entry_id IN ({','.join('?' * len(chunk))}) ORDER BY tag COLLATE NOCASE"
        for r in conn.execute(q, chunk):
            out[r["entry_id"]].append(r["tag"])
    return out


def _existing_spelling(conn, tag):
    """Reuse the spelling a tag already has, so "Elegy" and "elegy" stay one tag."""
    row = conn.execute("SELECT tag FROM entry_tags WHERE tag = ? LIMIT 1", (tag,)).fetchone()
    return row["tag"] if row else tag


def set_for_entry(conn, entry_id, tags):
    ensure_tables(conn)
    _entry(conn, entry_id)
    wanted, seen = [], set()
    for t in tags or []:
        t = clean(t)
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            wanted.append(_existing_spelling(conn, t))
    if len(wanted) > MAX_TAGS_PER_ENTRY:
        raise TagError(f"An entry can have up to {MAX_TAGS_PER_ENTRY} tags.")
    conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
    conn.executemany("INSERT INTO entry_tags VALUES (?, ?)", [(entry_id, t) for t in wanted])
    conn.commit()
    return for_entry(conn, entry_id)


def all_tags(conn):
    ensure_tables(conn)
    return [{"tag": r["tag"], "count": r["n"]} for r in conn.execute(
        """SELECT MIN(t.tag) AS tag, COUNT(*) AS n FROM entry_tags t JOIN entries e ON e.id = t.entry_id
           GROUP BY t.tag ORDER BY t.tag COLLATE NOCASE""")]


def rename(conn, old, new):
    """Rename a tag everywhere; renaming onto an existing tag merges them."""
    ensure_tables(conn)
    old, new = clean(old), clean(new)
    if not new:
        raise TagError("Give the tag a name.")
    if not conn.execute("SELECT 1 FROM entry_tags WHERE tag = ?", (old,)).fetchone():
        raise TagError(f'No entry is tagged "{old}".')
    new = new if new.casefold() == old.casefold() else _existing_spelling(conn, new)
    ids = [r["entry_id"] for r in conn.execute("SELECT entry_id FROM entry_tags WHERE tag = ?", (old,))]
    conn.execute("DELETE FROM entry_tags WHERE tag = ?", (old,))
    conn.executemany("INSERT OR IGNORE INTO entry_tags VALUES (?, ?)", [(i, new) for i in ids])
    _rewrite_collections(conn, old, new)
    conn.commit()
    return all_tags(conn)


def remove(conn, tag):
    """Take a tag off every entry. The entries themselves are untouched."""
    ensure_tables(conn)
    conn.execute("DELETE FROM entry_tags WHERE tag = ?", (clean(tag),))
    conn.commit()
    return all_tags(conn)


def move_entry(conn, from_id, to_id):
    """When one entry is merged into another, or turns up again under a
    new id, its tags follow it."""
    ensure_tables(conn)
    conn.execute("INSERT OR IGNORE INTO entry_tags SELECT ?, tag FROM entry_tags WHERE entry_id = ?", (to_id, from_id))
    conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (from_id,))


def forget_missing(conn):
    """Drop tags for entries that have left the index."""
    ensure_tables(conn)
    conn.execute("DELETE FROM entry_tags WHERE entry_id NOT IN (SELECT id FROM entries)")


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------

def _clean_filters(filters):
    if not isinstance(filters, dict):
        raise TagError("A collection needs at least one filter.")
    out = {}
    for k in FILTER_KEYS:
        v = filters.get(k)
        if v in (None, "", False):
            continue
        out[k] = v if isinstance(v, bool) else str(v)[:400]
    if not [k for k in out if k != "mode"]:
        raise TagError("Choose a filter or type a search first; a collection saves what you've chosen.")
    return out


def list_collections(conn):
    ensure_tables(conn)
    return [{"id": r["id"], "name": r["name"], "filters": json.loads(r["filters"])}
            for r in conn.execute("SELECT * FROM collections ORDER BY name COLLATE NOCASE")]


def save_collection(conn, name, filters):
    ensure_tables(conn)
    name = " ".join(str(name or "").split())[:60]
    if not name:
        raise TagError("Give the collection a name.")
    data = json.dumps(_clean_filters(filters))
    conn.execute("""INSERT INTO collections (name, filters, created_at) VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET filters = excluded.filters""",
                 (name, data, datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return list_collections(conn)


def delete_collection(conn, collection_id):
    ensure_tables(conn)
    conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    return list_collections(conn)


def _rewrite_collections(conn, old, new):
    for r in conn.execute("SELECT id, filters FROM collections").fetchall():
        f = json.loads(r["filters"])
        if str(f.get("tag", "")).casefold() == old.casefold():
            f["tag"] = new
            conn.execute("UPDATE collections SET filters = ? WHERE id = ?", (json.dumps(f), r["id"]))

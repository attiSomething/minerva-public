import os

from conftest import write
from minerva import core, search


def _lib(library):
    core.configure(library)
    write(os.path.join(library, "Poetry", "Morning Tide", "Archive", "Morning Tide v1.txt"),
          "First line.\nThe Gulls ARGUE at dawn.\n")
    with open(os.path.join(library, "Misc", "Old Letter [C].txt"), "wb"):
        pass
    os.makedirs(os.path.join(library, "Misc", "Old Letter"), exist_ok=True)
    with open(os.path.join(library, "Misc", "Old Letter", "Old Letter [C].txt"), "wb") as fh:
        fh.write("Dear friend, the café was closed.".encode("cp1252"))
    core.scan_and_sync()
    return core.get_conn()


def test_finds_phrases_in_current_and_archived_drafts(library):
    conn = _lib(library)
    r = search.find(conn, "gulls argue")
    assert [e["title"] for e in r["entries"]] == ["Morning Tide"]
    files = r["entries"][0]["files"]
    assert [f["kind"] for f in files] == ["current", "archive"]
    hit = [p["text"] for p in files[1]["snippets"][0]["pieces"] if p["hit"]]
    assert hit == ["Gulls ARGUE"] and files[1]["snippets"][0]["line"] == 2
    assert r["matches"] == 2
    assert [f["kind"] for f in search.find(conn, "gulls argue", current_only=True)["entries"][0]["files"]] == ["current"]
    # older encodings are read, filters apply, short or wildcard queries match nothing extra
    assert search.find(conn, "CAFÉ")["entries"][0]["title"] == "Old Letter"
    assert search.find(conn, "gulls", category="Fiction")["entries"] == []
    assert search.find(conn, "x")["entries"] == []
    assert search.find(conn, "%")["entries"] == []


def test_index_follows_saves_and_deletions(library):
    conn = _lib(library)
    tide = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    core.save_entry_content(conn, tide, "Herons stand in the shallows.", "archive")
    assert search.find(conn, "herons stand")["entries"][0]["id"] == tide
    # the old current draft is now in Archive and still searchable
    assert {f["kind"] for f in search.find(conn, "tide comes in")["entries"][0]["files"]} == {"archive"}

    assert search.refresh(conn) == 0  # nothing changed, nothing re-read
    path = os.path.join(library, "Poetry", "Morning Tide", "Archive", "Morning Tide v1.txt")
    os.remove(path)
    core.scan_and_sync()
    conn = core.get_conn()
    assert search.find(conn, "argue at dawn")["entries"] == []


def test_search_route(client, library):
    _lib(library)
    r = client.get("/api/search?q=gulls&current=1").get_json()
    assert r["files"] == 1 and r["entries"][0]["files"][0]["kind"] == "current"

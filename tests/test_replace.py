import os

import pytest

from minerva import core, replace


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def test_preview_shows_lines_before_and_after(library):
    conn = _open(library)
    p = replace.preview(conn, "THE", "a")
    titles = sorted(e["title"] for e in p["entries"])
    assert "Morning Tide" in titles
    tide = next(e for e in p["entries"] if e["title"] == "Morning Tide")
    # only the current draft is searched, not the archived one
    assert tide["matches"] == 2
    assert tide["lines"][0]["after"] == "a tide comes in"
    assert [x["text"] for x in tide["lines"][0]["before"] if x["hit"]] == ["The"]
    # match case and whole words
    assert replace.preview(conn, "THE", "a", match_case=True)["matches"] == 0
    assert all(e["title"] != "Field Notes" for e in replace.preview(conn, "rain", "x", whole_word=True, category="Poetry")["entries"])
    assert replace.preview(conn, "keep", "x", whole_word=True)["matches"] == 0
    assert replace.preview(conn, "keep", "x")["matches"] == 1
    with pytest.raises(replace.ReplaceError):
        replace.preview(conn, "  ", "x")


def test_apply_archives_the_old_draft(library):
    conn = _open(library)
    tide, lh = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    r = replace.apply(conn, "the", "a", [tide])
    assert r == {"entries": [{"id": tide, "title": "Morning Tide", "replaced": 2}], "replaced": 2}
    row = core.get_entry_row(conn, tide)
    path = os.path.join(core.entry_dir(row), row["draft_filename"])
    assert open(path, encoding="utf-8").read() == "a tide comes in\nand a gulls argue.\n"
    archived = os.listdir(os.path.join(core.entry_dir(row), "Archive"))
    assert len(archived) == 2  # the old one plus the draft just replaced
    # an entry that wasn't ticked is untouched
    row = core.get_entry_row(conn, lh)
    assert open(os.path.join(core.entry_dir(row), row["draft_filename"]), encoding="utf-8").read() == "Once there was a keeper.\n"
    assert replace.apply(conn, "the", "a", [])["replaced"] == 0


def test_replace_routes(client, library):
    _open(library)
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    p = client.post("/api/replace/preview", json={"find": "gulls", "replace": "terns"}).get_json()
    assert p["matches"] == 1
    ids = [e["id"] for e in p["entries"]]
    r = client.post("/api/replace/apply", json={"find": "gulls", "replace": "terns", "ids": ids}).get_json()
    assert r["replaced"] == 1
    assert "terns" in client.get(f"/api/entries/{ids[0]}").get_json()["content"]
    assert client.post("/api/replace/preview", json={"find": ""}).status_code == 400


def test_long_lines_are_cut_around_the_match():
    import re
    line = "x " * 200 + "needle" + " y" * 200
    pieces = replace._pieces(line, re.compile("needle"))
    text = "".join(p["text"] for p in pieces)
    assert text.startswith("…") and text.endswith("…") and "needle" in text
    assert len(text) < 260
    assert replace._pieces("short needle line", re.compile("needle"))[0] == {"text": "short ", "hit": False}

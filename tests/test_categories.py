import os

import pytest

from minerva import core, submissions

from conftest import write


@pytest.fixture
def lib(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    yield library, conn
    conn.close()


def _entry(conn, title):
    return conn.execute("SELECT * FROM entries WHERE title = ?", (title,)).fetchone()


def test_add_category_creates_or_adopts_a_folder(lib):
    root, conn = lib
    assert core.add_category("  Essays ") == "Essays"
    assert os.path.isdir(os.path.join(root, "Essays")) and "Essays" in core.TOP_FOLDERS
    assert core.read_library_settings(root)["categories"][-1] == "Essays"
    # an existing folder full of entries becomes a category
    write(os.path.join(root, "Letters", "To Mara", "To Mara [C].txt"), "Dear Mara,\n")
    core.add_category("Letters")
    core.scan_and_sync()
    assert _entry(conn, "To Mara")["top_folder"] == "Letters"
    for bad in ("", "poetry", "Sources", "Projects", ".minerva", "A/B", "x" * 61):
        with pytest.raises(core.CategoryError):
            core.add_category(bad)
    # the list survives reopening the library
    core.configure(root)
    assert core.TOP_FOLDERS[-2:] == ["Essays", "Letters"]


def test_rename_category_keeps_entries_and_their_records(lib):
    root, conn = lib
    tide = _entry(conn, "Morning Tide")
    sub = submissions.create(conn, {"entry_id": tide["id"], "venue": "Harbor Review"})
    core.rename_category(conn, "Poetry", "Verse")
    assert not os.path.exists(os.path.join(root, "Poetry"))
    assert os.path.isfile(os.path.join(root, "Verse", "Morning Tide", "Morning Tide [C].txt"))
    core.scan_and_sync()
    after = _entry(conn, "Morning Tide")
    assert (after["id"], after["top_folder"], after["rel_path"]) == (tide["id"], "Verse", "Verse/Morning Tide")
    assert submissions.get(conn, sub["id"])["category"] == "Verse"
    assert core.TOP_FOLDERS.index("Verse") == core.read_library_settings(root)["categories"].index("Verse")
    # changing only the case works too
    core.rename_category(conn, "Verse", "verse")
    assert "verse" in os.listdir(root) and _entry(conn, "Morning Tide")["top_folder"] == "verse"
    with pytest.raises(core.CategoryError):
        core.rename_category(conn, "verse", "Fiction")
    with pytest.raises(core.CategoryError):
        core.rename_category(conn, "Nope", "Other")


def test_remove_only_an_empty_category(lib):
    root, conn = lib
    core.add_category("Essays")
    with pytest.raises(core.CategoryError):
        core.remove_category(conn, "Poetry")
    core.remove_category(conn, "Essays")
    assert "Essays" not in core.TOP_FOLDERS and os.path.isdir(os.path.join(root, "Essays"))


def test_category_routes(client, lib):
    _, conn = lib
    r = client.post("/api/categories", json={"name": "Essays"})
    assert {"name": "Essays", "entries": 0} in r.get_json()
    assert client.post("/api/categories", json={"name": "essays"}).status_code == 400
    tide = _entry(conn, "Morning Tide")["id"]
    assert client.post(f"/api/entries/{tide}/category", json={"category": "Essays"}).status_code == 200
    details = client.post("/api/categories/rename", json={"old": "Essays", "new": "Prose"}).get_json()
    assert {"name": "Prose", "entries": 1} in details
    assert client.post("/api/categories/remove", json={"name": "Prose"}).status_code == 400
    assert client.get("/api/categories").get_json()[-1] == "Prose"

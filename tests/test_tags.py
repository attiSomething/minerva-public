import os
import shutil

import pytest

from minerva import core, notes, search, submissions, tags


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def test_tags_on_entries(library):
    conn = _open(library)
    tide, keeper = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    assert tags.set_for_entry(conn, tide, ["#Elegy", "sea,  salt", "elegy", "  "]) == ["Elegy", "sea salt"]
    # an existing tag keeps its spelling
    assert tags.set_for_entry(conn, keeper, ["ELEGY"]) == ["Elegy"]
    assert tags.all_tags(conn) == [{"tag": "Elegy", "count": 2}, {"tag": "sea salt", "count": 1}]
    assert tags.for_entries(conn, [tide, keeper]) == {tide: ["Elegy", "sea salt"], keeper: ["Elegy"]}
    with pytest.raises(tags.TagError):
        tags.set_for_entry(conn, tide, [f"t{i}" for i in range(31)])
    # renaming onto an existing tag joins them; removing takes it off entries
    tags.rename(conn, "sea salt", "elegy")
    assert tags.for_entry(conn, tide) == ["Elegy"]
    tags.remove(conn, "Elegy")
    assert tags.all_tags(conn) == []


def test_tag_filters_for_entries_and_search(client, library):
    conn = _open(library)
    tide = _id(conn, "Morning Tide")
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    r = client.post(f"/api/entries/{tide}/tags", json={"tags": ["harbor"]}).get_json()
    assert r["tags"] == ["harbor"] and r["all"] == [{"tag": "harbor", "count": 1}]
    rows = client.get("/api/entries?tag=HARBOR").get_json()["rows"]
    assert [x["title"] for x in rows] == ["Morning Tide"] and rows[0]["tags"] == ["harbor"]
    assert client.get(f"/api/entries/{tide}").get_json()["tags"] == ["harbor"]
    assert search.find(conn, "tide", tag="harbor")["entries"][0]["id"] == tide
    assert search.find(conn, "keeper", tag="harbor")["entries"] == []


def test_collections(client, library):
    conn = _open(library)
    with pytest.raises(tags.TagError):
        tags.save_collection(conn, "Nothing", {"mode": "titles"})
    cols = tags.save_collection(conn, "Elegies", {"tag": "elegy", "to_edit": True, "mode": "titles", "bogus": 1})
    assert cols[0]["filters"] == {"tag": "elegy", "to_edit": True, "mode": "titles"}
    # saving again under the same name replaces it
    cols = tags.save_collection(conn, "elegies", {"category": "Poetry"})
    assert len(cols) == 1 and cols[0]["filters"] == {"category": "Poetry"}
    tags.save_collection(conn, "Sea", {"tag": "sea"})
    tags.set_for_entry(conn, _id(conn, "Morning Tide"), ["sea"])
    tags.rename(conn, "sea", "ocean")
    assert [c["filters"].get("tag") for c in tags.list_collections(conn)] == [None, "ocean"]
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    cid = client.get("/api/collections").get_json()[0]["id"]
    assert len(client.post(f"/api/collections/{cid}/delete", json={}).get_json()) == 1


def test_records_follow_an_entry_moved_outside_minerva(library):
    conn = _open(library)
    tide = _id(conn, "Morning Tide")
    tags.set_for_entry(conn, tide, ["sea"])
    notes.save(conn, tide, "Moved notes.")
    submissions.create(conn, {"entry_id": tide, "venue": "Harbor Review", "status": "Submitted"})
    conn.close()
    shutil.move(os.path.join(library, "Poetry", "Morning Tide"), os.path.join(library, "Misc", "Morning Tide"))
    core.scan_and_sync()
    conn = core.get_conn()
    moved = _id(conn, "Morning Tide")
    assert moved != tide
    assert tags.for_entry(conn, moved) == ["sea"]
    assert notes.get(conn, moved)["body"] == "Moved notes."
    assert conn.execute("SELECT entry_id FROM submissions").fetchone()["entry_id"] == moved
    # an entry that's simply gone takes its tags with it
    shutil.rmtree(os.path.join(library, "Misc", "Morning Tide"))
    core.scan_and_sync()
    conn = core.get_conn()
    assert tags.all_tags(conn) == []

import os
import shutil

from conftest import sha
from minerva import core, notes, search


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def _files(library):
    out = {}
    for d, _, names in os.walk(library):
        if ".minerva" in d:
            continue
        for n in names:
            out[os.path.relpath(os.path.join(d, n), library)] = sha(os.path.join(d, n))
    return out


def test_notes_save_without_touching_the_library(client, library):
    conn = _open(library)
    before = _files(library)
    tide = _id(conn, "Morning Tide")
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    assert client.get(f"/api/entries/{tide}").get_json()["notes"] == {"body": "", "updated_at": None}
    r = client.post(f"/api/entries/{tide}/notes", json={"body": "Second stanza drags.\r\nCut the gulls?"}).get_json()
    assert r["body"] == "Second stanza drags.\nCut the gulls?"
    assert client.get(f"/api/entries/{tide}").get_json()["notes"]["body"] == r["body"]
    assert _files(library) == before
    # clearing notes removes them
    client.post(f"/api/entries/{tide}/notes", json={"body": "  "})
    assert notes.get(conn, tide)["body"] == ""
    assert client.post("/api/entries/99999/notes", json={"body": "x"}).status_code == 400


def test_notes_are_searchable_and_follow_filters(library):
    conn = _open(library)
    tide = _id(conn, "Morning Tide")
    notes.save(conn, tide, "Look up the HERON's call.")
    r = search.find(conn, "heron's call")
    assert r["entries"][0]["id"] == tide and r["entries"][0]["files"][0]["kind"] == "notes"
    assert search.find(conn, "heron's call", category="Fiction")["entries"] == []
    assert search.find(conn, "heron's call", current_only=True)["entries"] == []
    # a draft match and a notes match land on the same entry, notes first
    notes.save(conn, tide, "the gulls argue too much")
    kinds = [f["kind"] for f in search.find(conn, "gulls argue")["entries"][0]["files"]]
    assert kinds[0] == "notes" and "current" in kinds


def test_notes_survive_renames_moves_and_merges(library):
    conn = _open(library)
    tide = _id(conn, "Morning Tide")
    notes.save(conn, tide, "Tide notes.")
    # a rename in Minerva keeps the entry
    core.rename_entry(conn, tide, "Evening Tide")
    conn.close()
    # a move to another category outside Minerva makes a new entry; notes find it by title
    shutil.move(os.path.join(library, "Poetry", "Evening Tide"), os.path.join(library, "Misc", "Evening Tide"))
    core.scan_and_sync()
    conn = core.get_conn()
    moved = _id(conn, "Evening Tide")
    assert notes.get(conn, moved)["body"] == "Tide notes."
    # merging another entry in brings its notes along, below the kept ones
    keeper = _id(conn, "The Lighthouse")
    notes.save(conn, keeper, "Keeper notes.")
    core.merge_entries(conn, keeper, moved)
    body = notes.get(conn, keeper)["body"]
    assert body.startswith("Keeper notes.") and "From Evening Tide" in body and body.endswith("Tide notes.")


def test_notes_that_lose_their_entry_are_kept_until_placed(client, library):
    conn = _open(library)
    notes.save(conn, _id(conn, "Morning Tide"), "Orphan-to-be.")
    conn.close()
    # renamed outside Minerva: nothing to match, so the notes wait in the library check
    os.rename(os.path.join(library, "Poetry", "Morning Tide"), os.path.join(library, "Poetry", "Low Water"))
    core.scan_and_sync()
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    lost = client.get("/api/library/check").get_json()["lost_notes"]
    assert [(n["title"], n["body"]) for n in lost] == [("Morning Tide", "Orphan-to-be.")]
    conn = core.get_conn()
    target = _id(conn, "Low Water")
    assert client.post(f"/api/notes/lost/{lost[0]['id']}/attach", json={"entry_id": target}).get_json()["ok"]
    assert notes.get(conn, target)["body"] == "Orphan-to-be."
    assert notes.lost(conn) == []
    # a second sync doesn't disturb a placed note
    core.scan_and_sync()
    assert notes.get(core.get_conn(), target)["body"] == "Orphan-to-be."


def test_forgetting_lost_notes(library):
    conn = _open(library)
    notes.save(conn, _id(conn, "Morning Tide"), "Gone soon.")
    conn.close()
    os.rename(os.path.join(library, "Poetry", "Morning Tide"), os.path.join(library, "Poetry", "Low Water"))
    core.scan_and_sync()
    conn = core.get_conn()
    [n] = notes.lost(conn)
    notes.forget(conn, n["id"])
    assert notes.lost(conn) == []

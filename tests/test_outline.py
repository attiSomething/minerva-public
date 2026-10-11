import os

import pytest

from minerva import core, notes, outline


def _setup(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    core.create_project(conn, "Harbor Poems", "HP")
    pid = conn.execute("SELECT id FROM projects WHERE tag = 'HP'").fetchone()["id"]
    for title in ("Morning Tide", "Field Notes"):
        eid = conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]
        core.set_entry_project(conn, eid, "HP")
    return conn, pid


def _titles(o):
    return [i["title"] for i in o["items"]]


def test_outline_lists_entries_and_placeholders_in_one_order(library):
    conn, pid = _setup(library)
    o = outline.get(conn, pid)
    assert _titles(o) == ["Field Notes", "Morning Tide"]
    assert all(i["kind"] == "entry" and i["status"] == "" for i in o["items"])
    first = o["items"][0]["id"]
    o = outline.add_placeholder(conn, pid, "  Storm  Sequence ", "Three poems about the night of the storm.", after=first)
    assert _titles(o) == ["Field Notes", "Storm Sequence", "Morning Tide"]
    storm = o["items"][1]
    assert storm["kind"] == "placeholder" and storm["status"] == "idea"
    # reordering moves placeholders too, and sets the export order for entries
    ids = [i["id"] for i in o["items"]]
    o = outline.reorder(conn, pid, [ids[2], ids[1], ids[0]])
    assert _titles(o) == ["Morning Tide", "Storm Sequence", "Field Notes"]
    proj = core.get_project(conn, pid)
    assert [e["title"] for e in proj["entries"]] == ["Morning Tide", "Field Notes"]
    with pytest.raises(outline.OutlineError):
        outline.reorder(conn, pid, ids[:2])
    assert o["counts"]["idea"] == 1 and o["counts"]["none"] == 2


def test_synopsis_status_and_notes(library):
    conn, pid = _setup(library)
    items = outline.get(conn, pid)["items"]
    entry = items[0]
    o = outline.update(conn, pid, entry["id"], {"synopsis": "Rain\nall week.", "status": "revising",
                                                 "notes": "Check the dates."})
    e = o["items"][0]
    assert (e["synopsis"], e["status"], e["notes"]) == ("Rain all week.", "revising", "Check the dates.")
    # an entry's outline notes are its own notes
    assert notes.get(conn, entry["entry_id"])["body"] == "Check the dates."
    with pytest.raises(outline.OutlineError):
        outline.update(conn, pid, entry["id"], {"status": "finished"})
    with pytest.raises(outline.OutlineError):
        outline.update(conn, pid, entry["id"], {"title": "New name"})
    ph = outline.add_placeholder(conn, pid, "Coda")["added"]
    o = outline.update(conn, pid, ph, {"title": "Last Coda", "notes": "End on the lighthouse."})
    assert o["items"][-1]["title"] == "Last Coda" and o["items"][-1]["notes"] == "End on the lighthouse."
    outline.delete_placeholder(conn, pid, ph)
    assert "Last Coda" not in _titles(outline.get(conn, pid))
    with pytest.raises(outline.OutlineError):
        outline.delete_placeholder(conn, pid, entry["id"])


def test_start_writing_creates_the_entry_in_place(library):
    conn, pid = _setup(library)
    first = outline.get(conn, pid)["items"][0]["id"]
    ph = outline.add_placeholder(conn, pid, "Storm Sequence", "Night of the storm.", after=first)["added"]
    outline.update(conn, pid, ph, {"notes": "Start with the bell buoy."})
    o = outline.start_writing(conn, pid, ph, "Poetry")
    draft = os.path.join(library, "Poetry", "Storm Sequence - [HP]", "Storm Sequence [C].txt")
    assert os.path.isfile(draft) and open(draft, encoding="utf-8").read() == ""
    item = o["items"][1]
    assert item["kind"] == "entry" and item["entry_id"] == o["entry_id"] and item["title"] == "Storm Sequence"
    assert item["synopsis"] == "Night of the storm." and item["notes"] == "Start with the bell buoy."
    assert item["status"] == "drafting"
    assert [e["title"] for e in core.get_project(conn, pid)["entries"]][1] == "Storm Sequence"
    # the same title again would clash with that folder
    again = outline.add_placeholder(conn, pid, "Storm Sequence")["added"]
    with pytest.raises(outline.OutlineError):
        outline.start_writing(conn, pid, again, "Poetry")
    with pytest.raises(outline.OutlineError):
        outline.start_writing(conn, pid, again, "Nowhere")


def test_link_placeholder_to_existing_entry(library):
    conn, pid = _setup(library)
    ph = outline.add_placeholder(conn, pid, "Keeper", "The keeper's story.")["added"]
    keeper = conn.execute("SELECT id FROM entries WHERE title = 'The Lighthouse'").fetchone()["id"]
    o = outline.link_entry(conn, pid, ph, keeper)
    item = [i for i in o["items"] if i["id"] == ph][0]
    assert item["kind"] == "entry" and item["title"] == "The Lighthouse" and item["synopsis"] == "The keeper's story."
    assert core.get_entry_row(conn, keeper)["project_tag"] == "HP"
    assert len(o["items"]) == 3


def test_outline_routes(client, library):
    _, pid = _setup(library)
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    o = client.get(f"/api/projects/{pid}/outline").get_json()
    assert len(o["items"]) == 2
    r = client.post(f"/api/projects/{pid}/outline/add", json={"title": "Coda"}).get_json()
    assert r["items"][-1]["title"] == "Coda"
    bad = client.post(f"/api/projects/{pid}/outline/{r['added']}", json={"status": "nope"})
    assert bad.status_code == 400 and "idea" in bad.get_json()["error"]
    assert client.get("/api/projects/9999/outline").status_code == 400

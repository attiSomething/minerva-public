import os

from minerva import core

from conftest import sha, write


def _setup(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    core.create_project(conn, "Lighthouse", "LH", "Stories about the keeper")
    return conn


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def test_project_cards_carry_details(library):
    conn = _setup(library)
    core.set_entry_project(conn, _id(conn, "Morning Tide"), "LH")
    (p,) = core.list_projects(conn)
    assert (p["name"], p["description"], p["entry_count"]) == ("Lighthouse", "Stories about the keeper", 2)
    assert p["word_count"] == 13
    assert p["categories"] == {"Fiction": 1, "Poetry": 1}
    assert p["last_edited"] and p["created_at"]
    conn.close()


def test_project_order_is_kept_and_new_entries_follow(library):
    conn = _setup(library)
    pid = core.list_projects(conn)[0]["id"]
    tide, light = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    core.set_entry_project(conn, tide, "LH")
    assert [e["title"] for e in core.get_project(conn, pid)["entries"]] == ["Morning Tide", "The Lighthouse"]
    core.set_project_order(conn, pid, [light, tide])
    assert [e["title"] for e in core.get_project(conn, pid)["entries"]] == ["The Lighthouse", "Morning Tide"]
    core.set_entry_project(conn, _id(conn, "Field Notes"), "LH")
    assert [e["title"] for e in core.get_project(conn, pid)["entries"]][-1] == "Field Notes"
    conn.close()


def test_deleting_a_project_keeps_its_entries(library):
    conn = _setup(library)
    pid = core.list_projects(conn)[0]["id"]
    draft = os.path.join(library, "Fiction", "The Lighthouse - [LH]", "The Lighthouse [C].txt")
    before = sha(draft)
    r = core.delete_project(conn, pid)
    assert r == {"untagged": 1, "folder_kept": os.path.join("Projects", "Lighthouse")}
    assert core.list_projects(conn) == []
    assert sha(os.path.join(library, "Fiction", "The Lighthouse", "The Lighthouse [C].txt")) == before
    assert os.path.isdir(os.path.join(library, "Projects", "Lighthouse"))
    row = conn.execute("SELECT * FROM entries WHERE title = 'The Lighthouse'").fetchone()
    assert row["project_tag"] is None and row["folder_name"] == "The Lighthouse"
    conn.close()


def test_delete_refuses_without_changing_anything_when_a_name_is_taken(library):
    write(os.path.join(library, "Fiction", "The Lighthouse", "The Lighthouse [C].txt"), "another one\n")
    conn = _setup(library)
    pid = core.list_projects(conn)[0]["id"]
    try:
        core.delete_project(conn, pid)
        assert False, "should refuse"
    except ValueError as e:
        assert "Nothing was changed" in str(e)
    assert os.path.isdir(os.path.join(library, "Fiction", "The Lighthouse - [LH]"))
    assert len(core.list_projects(conn)) == 1
    conn.close()


def test_renaming_a_project_moves_its_folder(library):
    conn = _setup(library)
    pid = core.list_projects(conn)[0]["id"]
    p = core.update_project(conn, pid, name="The Keeper", description="")
    assert (p["name"], p["tag"], p["description"]) == ("The Keeper", "LH", "")
    assert os.path.isdir(os.path.join(library, "Projects", "The Keeper"))
    assert not os.path.exists(os.path.join(library, "Projects", "Lighthouse"))
    conn.close()


def test_project_routes(client, library):
    conn = _setup(library)
    pid = core.list_projects(conn)[0]["id"]
    tide = _id(conn, "Morning Tide")
    conn.close()
    r = client.post(f"/api/projects/{pid}/entries", json={"add": [tide]})
    assert r.status_code == 200 and r.get_json()["entry_count"] == 2
    assert os.path.isdir(os.path.join(library, "Poetry", "Morning Tide - [LH]"))
    r = client.post(f"/api/projects/{pid}/entries", json={"remove": [tide]})
    assert r.get_json()["entry_count"] == 1
    assert os.path.isdir(os.path.join(library, "Poetry", "Morning Tide"))
    assert client.post(f"/api/projects/{pid}/delete", json={}).get_json()["untagged"] == 1
    assert client.get(f"/api/projects/{pid}").status_code == 400

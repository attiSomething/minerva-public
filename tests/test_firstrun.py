import os

from minerva import config as app_config
from minerva import core, sample
from conftest import sha


def _tree(root):
    out = {}
    for d, dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = sha(p)
    return out


def test_sample_library_is_separate_and_full(client, library):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    mine = {k: v for k, v in _tree(library).items() if not k.startswith(".minerva")}
    r = client.post("/api/setup/sample", json={}).get_json()
    assert r["is_sample"] and r["total_entries"] == len(sample.PIECES)
    root = r["library_root"]
    assert root.startswith(app_config.config_dir())
    assert os.path.isfile(os.path.join(root, sample.MARKER))
    st = client.get("/api/setup/status").get_json()
    assert st["is_sample"] and st["library_before_sample"] == library
    subs = client.get("/api/submissions").get_json()["rows"]
    assert len(subs) == len(sample.SUBMISSIONS)
    projects = client.get("/api/projects").get_json()
    assert any(p["tag"] == "TW" for p in projects)
    # opening it again reuses it without doubling anything
    client.post("/api/setup/sample", json={})
    assert len(client.get("/api/submissions").get_json()["rows"]) == len(sample.SUBMISSIONS)
    # starting over makes it fresh
    client.post("/api/setup/sample", json={"start_over": True})
    assert len(client.get("/api/submissions").get_json()["rows"]) == len(sample.SUBMISSIONS)
    # going back reopens the writer's library, which was never touched
    back = client.post("/api/setup/sample/leave").get_json()
    assert back["library_root"] == library
    assert {k: v for k, v in _tree(library).items() if not k.startswith(".minerva")} == mine
    assert client.get("/api/setup/status").get_json()["is_sample"] is False


def test_sample_never_overwrites_a_folder_it_did_not_make(client):
    os.makedirs(sample.sample_path())
    with open(os.path.join(sample.sample_path(), "mine.txt"), "w") as fh:
        fh.write("keep")
    r = client.post("/api/setup/sample", json={"start_over": True})
    assert r.status_code == 400
    assert open(os.path.join(sample.sample_path(), "mine.txt")).read() == "keep"


def test_first_run_steps(client, library):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    s = client.get("/api/firstrun").get_json()
    assert s["steps"] == {"draft": False, "edit": False, "submission": False, "pdf": False}
    assert s["latest"]["id"]
    made = client.post("/api/entries/new", json={"title": "Brand New", "category": "Poetry"}).get_json()
    s = client.get("/api/firstrun").get_json()
    assert s["steps"]["draft"] and s["latest"]["id"] == made[0]["id"]
    client.post("/api/submissions", json={"entry_id": made[0]["id"], "venue": "Somewhere"})
    s = client.post("/api/firstrun", json={"done": "edit"}).get_json()
    assert s["steps"] == {"draft": True, "edit": True, "submission": True, "pdf": False}
    s = client.post("/api/firstrun", json={"done": "nonsense", "dismissed": True}).get_json()
    assert s["dismissed"] and not s["steps"]["pdf"]

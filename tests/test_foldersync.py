import os
import time

import pytest

from conftest import sha, write
from minerva import core, foldersync, tags


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "Vault"
    write(str(root / "Poems" / "Gull Song.md"), "---\ntags: [sea, draft]\n---\n# Gull Song\nthe gulls\nargue #salt\n")
    write(str(root / "Stories" / "The Pier.md"), "Once on the pier.\n")
    write(str(root / "Inbox.txt"), "a loose note\n")
    write(str(root / ".obsidian" / "app.json"), "{}")
    write(str(root / ".trash" / "Old.md"), "gone")
    write(str(root / "Daily" / "2026-10-01.md"), "daily note")
    return str(root)


def _tree(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            out[os.path.relpath(os.path.join(d, f), root)] = sha(os.path.join(d, f))
    return out


def test_new_and_changed_notes(library, vault):
    conn = _open(library)
    before = _tree(vault)
    src = foldersync.add_source(conn, vault, "Misc")
    foldersync.save_mapping(conn, src["id"], folder_map={"Daily": "__skip__"},
                            tag_map={"draft": ""})
    p = foldersync.pending(conn)
    by = {i["rel_path"]: i for i in p["items"]}
    assert set(by) == {"Poems/Gull Song.md", "Stories/The Pier.md", "Inbox.txt"}
    assert by["Poems/Gull Song.md"]["category"] == "Poetry" and by["Inbox.txt"]["category"] == "Misc"
    assert by["Poems/Gull Song.md"]["tags"] == ["sea", "salt"]
    r = foldersync.apply(conn, [{"source_id": src["id"], "rel_path": rel, "action": "import"} for rel in by if rel != "Inbox.txt"]
                         + [{"source_id": src["id"], "rel_path": "Inbox.txt", "action": "ignore"}])
    assert len(r["made"]) == 2 and r["ignored"] == 1
    gull = next(m for m in r["made"] if m["title"] == "Gull Song")
    row = core.get_entry_row(conn, gull["id"])
    assert row["top_folder"] == "Poetry" and core.read_entry_content(row) == "the gulls\nargue #salt\n"
    assert tags.for_entry(conn, gull["id"]) == ["salt", "sea"]
    assert foldersync.pending(conn)["items"] == []

    # the note changes: offered as a new version, not a conflict
    time.sleep(0.01)
    write(os.path.join(vault, "Poems", "Gull Song.md"), "# Gull Song\nthe gulls\nargue louder\n")
    p = foldersync.pending(conn)
    assert [(i["kind"], i["conflict"]) for i in p["items"]] == [("changed", False)]
    foldersync.apply(conn, [{"source_id": src["id"], "rel_path": "Poems/Gull Song.md", "action": "update"}])
    row = core.get_entry_row(conn, gull["id"])
    assert core.read_entry_content(row) == "the gulls\nargue louder\n"
    assert os.listdir(os.path.join(core.entry_dir(row), "Archive"))  # the old draft was kept

    # edited in Minerva and in the vault: a conflict
    core.save_entry_content(conn, gull["id"], "my own edit\n", "overwrite")
    time.sleep(0.01)
    write(os.path.join(vault, "Poems", "Gull Song.md"), "# Gull Song\nvault edit\n")
    p = foldersync.pending(conn)
    assert p["conflicts"] == 1
    # the ignored note stays quiet even after it changes
    write(os.path.join(vault, "Inbox.txt"), "changed loose note\n")
    assert [i["rel_path"] for i in foldersync.pending(conn)["items"]] == ["Poems/Gull Song.md"]
    # the vault was only ever read
    after = _tree(vault)
    assert set(after) == set(before)


def test_source_rules(library, vault, tmp_path):
    conn = _open(library)
    with pytest.raises(foldersync.SyncError):
        foldersync.add_source(conn, library, "Misc")
    with pytest.raises(foldersync.SyncError):
        foldersync.add_source(conn, os.path.join(library, "Poetry"), "Misc")
    with pytest.raises(foldersync.SyncError):
        foldersync.add_source(conn, str(tmp_path / "nope"), "Misc")
    src = foldersync.add_source(conn, vault, "Misc")
    with pytest.raises(foldersync.SyncError):
        foldersync.add_source(conn, vault, "Misc")
    ov = foldersync.overview(conn, src["id"])
    assert [f["name"] for f in ov["folders"]] == ["", "Daily", "Poems", "Stories"]
    assert {t["name"] for t in ov["tags"]} == {"sea", "draft", "salt"}
    with pytest.raises(foldersync.SyncError):
        foldersync.apply(conn, [{"source_id": src["id"], "rel_path": "../x.md", "action": "import"}])
    foldersync.remove_source(conn, src["id"])
    assert foldersync.list_sources(conn) == []


def test_sync_routes(client, library, vault):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    s = client.post("/api/sync/sources", json={"path": vault, "category": "Poetry"}).get_json()
    assert client.get("/api/sync/sources").get_json()[0]["id"] == s["id"]
    p = client.get("/api/sync/pending").get_json()
    assert p["new"] == 4
    r = client.post("/api/sync/apply", json={"choices": [
        {"source_id": s["id"], "rel_path": "Stories/The Pier.md", "action": "import", "title": "Pier", "category": "Fiction"}]}).get_json()
    assert r["made"][0]["title"] == "Pier"
    assert client.get("/api/sync/pending").get_json()["new"] == 3
    assert client.post("/api/sync/sources", json={"path": "", "category": "Poetry"}).status_code == 400

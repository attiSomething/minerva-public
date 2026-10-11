import datetime
import os
import time
import zipfile

import pytest

from minerva import backup, core, jobs


@pytest.fixture
def lib(library, tmp_path):
    core.configure(library)
    core.scan_and_sync()
    dest = tmp_path / "Backups"
    dest.mkdir()
    return library, str(dest)


def _names(path):
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        return set(zf.namelist())


def test_settings_validate_folder(lib):
    library, dest = lib
    assert backup.status()["due"] and not backup.status()["folder"]
    with pytest.raises(backup.BackupError):
        backup.set_settings(folder=os.path.join(dest, "nope"))
    with pytest.raises(backup.BackupError):
        backup.set_settings(folder=os.path.join(library, "Poetry"))  # inside the library
    with pytest.raises(backup.BackupError):
        backup.set_settings(remind_days=5)
    s = backup.set_settings(folder=dest, remind_days=3)
    assert (s["folder"], s["remind_days"], s["folder_ok"]) == (dest, 3, True)


def test_full_backup_copies_everything_and_never_overwrites(lib):
    library, dest = lib
    backup.set_settings(folder=dest)
    now = datetime.datetime(2026, 10, 7, 21, 30)
    before = {os.path.join(d, f) for d, _, fs in os.walk(library) for f in fs}

    r = backup.run(now=now)
    name = os.path.basename(library)
    assert os.path.basename(r["file"]) == f"{name} backup 2026-10-07 2130.zip"
    names = _names(r["file"])
    assert f"{name}/Poetry/Morning Tide/Morning Tide [C].txt" in names
    assert f"{name}/Poetry/Morning Tide/Archive/Morning Tide (old).txt" in names
    assert f"{name}/.minerva/minerva.db" in names  # the index, as a snapshot
    assert not any(n.endswith(("-wal", "-shm")) for n in names)

    again = backup.run(now=now)
    assert again["file"] != r["file"] and os.path.exists(r["file"])
    assert sorted(os.listdir(dest)) == sorted(os.path.basename(p) for p in (r["file"], again["file"]))
    # the library itself is untouched
    assert {os.path.join(d, f) for d, _, fs in os.walk(library) for f in fs} == before

    s = backup.status(now=now + datetime.timedelta(days=8))
    assert s["last"]["file"] == again["file"] and s["due"]
    assert not backup.status(now=now + datetime.timedelta(days=2))["due"]


def test_changes_only_needs_a_full_backup_first(lib):
    library, dest = lib
    backup.set_settings(folder=dest)
    with pytest.raises(backup.BackupError):
        backup.run(changes_only=True)
    past = time.time() - 3600
    for d, _, fs in os.walk(library):
        for f in fs:
            os.utime(os.path.join(d, f), (past, past))
    backup.run()
    path = os.path.join(library, "Poetry", "Morning Tide", "Morning Tide [C].txt")
    future = time.time() + 5
    os.utime(path, (future, future))
    r = backup.run(changes_only=True)
    names = _names(r["file"])
    name = os.path.basename(library)
    assert r["changes_only"] and "(changes)" in r["file"]
    assert f"{name}/Poetry/Morning Tide/Morning Tide [C].txt" in names
    assert f"{name}/Fiction/The Lighthouse - [LH]/The Lighthouse [C].txt" not in names


def test_backup_routes(client, lib):
    _, dest = lib
    assert client.post("/api/backup/run", json={}).status_code == 400
    assert client.post("/api/backup/settings", json={"folder": dest + "x"}).status_code == 400
    assert client.post("/api/backup/settings", json={"folder": dest}).get_json()["folder_ok"]
    job = client.post("/api/backup/run", json={}).get_json()
    for _ in range(100):
        j = jobs.get(job["id"]).to_dict()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["files"] > 0
    data = client.get("/api/backup").get_json()
    assert data["last"]["file"] == j["result"]["file"] and data["running"] == [] and not data["due"]

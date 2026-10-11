import json
import os
import time

import pytest

from minerva import core, jobs, scanintake, scanning

from conftest import sha, write


class FakeJob:
    def __init__(self):
        self.steps = []
        self.stop = False

    def progress(self, done, total, message=""):
        self.steps.append((done, total, message))

    def cancelled(self):
        return self.stop


@pytest.fixture
def lib(library):
    core.configure(library)
    core.scan_and_sync()
    return library


@pytest.fixture
def drive(tmp_path):
    """A synced cloud folder outside the library, as a scanner app leaves it."""
    root = tmp_path / "Google Drive" / "My Drive" / "Phone Scans"
    write(str(root / "page 1.jpg"), "jpg one")
    write(str(root / "page 2.pdf"), "%PDF-1.4 two")
    write(str(root / "notes.txt"), "not a scan")
    write(str(root / ".hidden.jpg"), "skip me")
    write(str(root / "March" / "page 1.jpg"), "march one")
    return str(root)


def test_preview_counts_scans_and_names_the_source(lib, drive):
    p = scanintake.preview(drive)
    assert p["source"] == "Phone Scans"
    assert p["source_exists"] is False
    assert p["files"] == 3 and p["new"] == 3 and p["already"] == 0
    assert p["sample"] == ["March/page 1.jpg".replace("/", os.sep), "page 1.jpg", "page 2.pdf"]
    assert scanintake.preview(drive, subfolders=False)["files"] == 2


def test_bring_in_copies_without_touching_the_folder(lib, drive):
    before = {f: sha(os.path.join(dp, f)) for dp, _, fs in os.walk(drive) for f in fs}
    r = scanintake.bring_in(FakeJob(), drive)
    assert r == {"source": "Phone Scans", "copied": 3, "skipped": 0, "failed": []}
    after = {f: sha(os.path.join(dp, f)) for dp, _, fs in os.walk(drive) for f in fs}
    assert before == after
    dest = os.path.join(lib, "Sources", "Phone Scans", "Scans")
    assert sorted(os.listdir(dest)) == ["March - page 1.jpg", "page 1.jpg", "page 2.pdf"]
    assert [s["filename"] for s in scanning.list_scans("Phone Scans")] == ["March - page 1.jpg", "page 1.jpg", "page 2.pdf"]
    assert scanintake.origins()["Phone Scans"] == {"folder": drive, "subfolders": True}


def test_bringing_in_again_copies_only_new_scans(lib, drive):
    scanintake.bring_in(FakeJob(), drive)
    write(os.path.join(drive, "page 3.jpg"), "three")
    p = scanintake.preview(drive)
    assert p["source_exists"] and p["new"] == 1 and p["already"] == 3
    r = scanintake.bring_in(FakeJob(), drive)
    assert r["copied"] == 1 and r["skipped"] == 3


def test_changed_file_with_same_name_is_kept_alongside(lib, drive):
    scanintake.bring_in(FakeJob(), drive)
    write(os.path.join(drive, "page 1.jpg"), "a rescan, longer than before")
    r = scanintake.bring_in(FakeJob(), drive)
    assert r["copied"] == 1
    dest = os.path.join(lib, "Sources", "Phone Scans", "Scans")
    assert "page 1 (2).jpg" in os.listdir(dest)
    with open(os.path.join(dest, "page 1.jpg")) as fh:
        assert fh.read() == "jpg one"


def test_into_an_existing_source_with_another_name(lib, drive):
    r = scanintake.bring_in(FakeJob(), drive, source="Blue Notebook", subfolders=False)
    assert r["source"] == "Blue Notebook" and r["copied"] == 2
    names = [s["filename"] for s in scanning.list_scans("Blue Notebook")]
    assert "Blue Notebook 1.pdf" in names and "page 2.pdf" in names


@pytest.mark.parametrize("bad", ["..", "a/b", "..\\x", ".hidden", "x:y"])
def test_source_names_that_could_escape_are_refused(lib, drive, bad):
    with pytest.raises(scanintake.IntakeError):
        scanintake.bring_in(FakeJob(), drive, source=bad)
    with pytest.raises(scanintake.IntakeError):
        scanintake.preview(drive, source=bad)


def test_folder_inside_the_library_is_refused(lib):
    with pytest.raises(scanintake.IntakeError):
        scanintake.preview(os.path.join(lib, "Sources"))
    with pytest.raises(scanintake.IntakeError):
        scanintake.preview(os.path.join(lib, "nope"))


def test_stopping_part_way(lib, drive):
    job = FakeJob()
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    job.cancelled = cancelled
    r = scanintake.bring_in(job, drive)
    assert r["copied"] == 1


def test_cloud_only_files_are_counted(lib, drive, monkeypatch):
    monkeypatch.setattr(scanintake, "is_cloud_only", lambda path, st=None: path.endswith(".pdf"))
    assert scanintake.preview(drive)["cloud_only"] == 1


def test_cloud_only_attribute_checks():
    class St:
        st_file_attributes = 0x400000
    assert scanintake.is_cloud_only("x", St())

    class Mac:
        st_flags = 0x40000000
    assert scanintake.is_cloud_only("x", Mac())

    class Local:
        st_file_attributes = 0x20
    assert not scanintake.is_cloud_only("x", Local())


def test_cloud_folders_found(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Dropbox").mkdir(parents=True)
    (home / "OneDrive").mkdir()
    business = tmp_path / "Work Dropbox"
    business.mkdir()
    appdata = tmp_path / "appdata"
    write(str(appdata / "Dropbox" / "info.json"), json.dumps({"business": {"path": str(business)}}))
    cs = home / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com" / "My Drive"
    cs.mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home), 1))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(var, raising=False)
    found = scanintake.cloud_folders()
    assert {"label": "Google Drive", "path": str(cs)} in found
    assert {"label": "Dropbox (work)", "path": str(business)} in found
    assert {"label": "Dropbox", "path": str(home / "Dropbox")} in found
    assert {"label": "OneDrive", "path": str(home / "OneDrive")} in found
    assert len(found) == 4


def test_api_preview_and_run(lib, drive, client):
    r = client.post("/api/scan-intake/preview", json={"folder": drive})
    assert r.status_code == 200 and r.get_json()["new"] == 3
    assert client.post("/api/scan-intake/preview", json={"folder": drive + "-missing"}).status_code == 400
    job = client.post("/api/scan-intake/run", json={"folder": drive, "source": "From Drive"}).get_json()
    for _ in range(100):
        j = client.get(f"/api/jobs/{job['id']}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["copied"] == 3
    data = client.get("/api/scans").get_json()
    assert "From Drive" in [s["name"] for s in data["sources"]]
    assert data["origins"]["From Drive"]["folder"] == drive
    assert "cloud" in client.get("/api/scan-intake/folders").get_json()

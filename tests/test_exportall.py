import csv
import io
import json
import os
import time
import zipfile

import pytest

from minerva import config as app_config, core, exportall, jobs, notes, submissions, tags


class Job:
    def __init__(self, stop_after=None):
        self.stop_after = stop_after
        self.calls = 0

    def progress(self, done, total, message=""):
        pass

    def cancelled(self):
        self.calls += 1
        return self.stop_after is not None and self.calls > self.stop_after


@pytest.fixture
def lib(library, tmp_path):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    try:
        tide = conn.execute("SELECT id FROM entries WHERE title='Morning Tide'").fetchone()["id"]
        notes.save(conn, tide, "Try ending on the gulls.")
        tags.set_for_entry(conn, tide, ["sea", "spring"])
        submissions.create(conn, {"entry_id": tide, "piece_title": "Morning Tide", "venue": "The Harbor Review",
                                  "submitted_on": "2026-09-01"})
        conn.commit()
    finally:
        conn.close()
    cfg = app_config.load()
    cfg["extra"] = {"api_key": "sk-should-not-leak", "model": "m"}
    cfg["github_token"] = "ghp_nope"
    app_config.save(cfg)
    dest = tmp_path / "Out"
    dest.mkdir()
    return library, str(dest)


def _zip(result):
    z = zipfile.ZipFile(result["path"])
    assert z.testzip() is None
    return z


def test_zip_holds_the_writing_and_the_records(lib):
    library, dest = lib
    r = exportall.export(Job(), dest)
    assert r["zip"] and r["name"].startswith("Library export ") and r["name"].endswith(".zip")
    assert not [n for n in os.listdir(dest) if n.endswith(".partial")]
    z = _zip(r)
    base = r["name"][:-4]
    names = set(z.namelist())
    assert f"{base}/README.txt" in names
    assert f"{base}/Writing/Poetry/Morning Tide/Morning Tide [C].txt" in names
    assert f"{base}/Writing/Poetry/Morning Tide/Archive/Morning Tide (old).txt" in names
    assert not [n for n in names if "/.minerva/" in n]
    # scans are left out unless asked for
    assert not [n for n in names if n.endswith(".pdf")]
    assert "left out" in z.read(f"{base}/README.txt").decode()

    rec = f"{base}/Minerva records/"
    entries = list(csv.DictReader(io.StringIO(z.read(rec + "entries.csv").decode("utf-8-sig"))))
    assert {e["Title"] for e in entries} >= {"Morning Tide", "The Lighthouse", "Field Notes"}
    assert z.read(rec + "Notes/Poetry/Morning Tide.md").decode().strip().endswith("Try ending on the gulls.")
    tag_rows = list(csv.DictReader(io.StringIO(z.read(rec + "tags.csv").decode("utf-8-sig"))))
    assert sorted(t["Tag"] for t in tag_rows) == ["sea", "spring"]
    subs = z.read(rec + "submissions.csv").decode("utf-8-sig")
    assert "The Harbor Review" in subs
    settings = z.read(rec + "settings.json").decode()
    assert "sk-should-not-leak" not in settings and "ghp_nope" not in settings
    assert json.loads(settings)["app"]["extra"]["model"] == "m"
    # the library itself is untouched
    assert not os.path.exists(os.path.join(library, "Exports"))
    assert exportall.prefs() == {"folder": dest, "zip": True, "media": False}


def test_folder_with_media(lib):
    _, dest = lib
    r = exportall.export(Job(), dest, as_zip=False, media=True)
    assert os.path.isdir(r["path"]) and not r["zip"]
    assert os.path.isfile(os.path.join(r["path"], "Writing", "Sources", "Blue Notebook", "Scans", "Blue Notebook 1.pdf"))
    assert os.path.isfile(os.path.join(r["path"], "Minerva records", "entries.csv"))
    assert "are included" in open(os.path.join(r["path"], "README.txt"), encoding="utf-8").read()
    # a second export the same minute doesn't overwrite the first
    again = exportall.export(Job(), dest, as_zip=False)
    assert again["path"] != r["path"] and again["name"].endswith("(2)")


def test_refuses_bad_destinations_and_cleans_up_when_stopped(lib):
    library, dest = lib
    with pytest.raises(exportall.ExportError, match="outside your library"):
        exportall.export(Job(), os.path.join(library, "Poetry"))
    with pytest.raises(exportall.ExportError, match="exists"):
        exportall.export(Job(), os.path.join(dest, "missing"))
    for as_zip in (True, False):
        with pytest.raises(exportall.ExportError, match="Stopped"):
            exportall.export(Job(stop_after=1), dest, as_zip=as_zip)
    assert os.listdir(dest) == []


def test_routes(client, lib):
    _, dest = lib
    exportall.LAST["path"] = None
    assert client.post("/api/export-all/reveal").status_code == 404
    job = client.post("/api/export-all", json={"folder": dest, "zip": True}).get_json()
    for _ in range(200):
        j = jobs.get(job["id"]).to_dict()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["files"] > 0
    s = client.get("/api/export-all").get_json()
    assert s["folder"] == dest and s["last"] == j["result"]["path"] and s["running"] == []
    bad = client.post("/api/export-all", json={"folder": ""}).get_json()
    for _ in range(100):
        b = jobs.get(bad["id"]).to_dict()
        if b["status"] != "running":
            break
        time.sleep(0.05)
    assert b["status"] == "failed" and "folder" in b["error"]

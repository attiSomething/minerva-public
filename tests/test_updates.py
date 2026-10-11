import datetime
import hashlib
import json
import os

import pytest

from minerva import __version__, backup, core, updates

NEW = b"MZ new minerva"


class Job:
    def __init__(self):
        self.messages = []

    def progress(self, done, total, message=""):
        self.messages.append(message)

    def cancelled(self):
        return False


def feed(tmp_path, version="99.0.0", data=NEW, digest=True, assets=True):
    exe = tmp_path / "dl" / "Minerva.exe"
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(data)
    release = {"tag_name": f"v{version}", "name": f"Minerva v{version}", "body": "## What's Changed\n* EPUB export by @a",
               "published_at": "2026-10-01T10:00:00Z", "html_url": "https://github.com/x/releases/tag/v99",
               "assets": [{"name": "Minerva.exe", "browser_download_url": exe.as_uri(), "size": len(NEW),
                           **({"digest": "sha256:" + hashlib.sha256(NEW).hexdigest()} if digest else {})}] if assets else []}
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(release))
    updates._store(feed=path.as_uri())
    return path


def test_versions():
    assert updates.newer("v0.8.0", "0.7.0") and updates.newer("0.7.1", "0.7") and updates.newer("1.0", "0.99.9")
    assert not updates.newer("v0.7.0", "0.7.0") and not updates.newer("0.7", "0.7.0") and not updates.newer("junk", "0.1")


def test_check_once_a_day_and_only_when_on(tmp_path):
    feed(tmp_path)
    now = datetime.datetime(2026, 10, 8, 9, 0)
    s = updates.check(now=now)
    assert s["available"] and s["latest"]["version"] == "99.0.0" and s["latest"]["notes"].startswith("## What")
    assert s["latest"]["sha256"] == hashlib.sha256(NEW).hexdigest()
    feed(tmp_path, version="100.0.0")
    assert updates.check(now=now + datetime.timedelta(hours=2))["latest"]["version"] == "99.0.0"
    assert updates.check(now=now + datetime.timedelta(hours=21))["latest"]["version"] == "100.0.0"
    updates.set_prefs(auto=False)
    feed(tmp_path, version="101.0.0")
    assert updates.check(now=now + datetime.timedelta(days=5))["latest"]["version"] == "100.0.0"
    assert updates.check(force=True)["latest"]["version"] == "101.0.0"
    assert updates.set_prefs(skipped="101.0.0")["skipped"]
    # an older or equal version isn't offered
    feed(tmp_path, version=__version__)
    assert not updates.check(force=True)["available"]


def test_check_quietly_survives_no_network(tmp_path):
    updates._store(feed=(tmp_path / "missing.json").as_uri())
    assert not updates.check()["available"]
    with pytest.raises(updates.UpdateError):
        updates.check(force=True)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    exe = app / "Minerva.exe"
    exe.write_bytes(b"MZ old minerva")
    monkeypatch.setattr(updates.sys, "executable", str(exe))
    monkeypatch.setattr(updates, "can_install", lambda: True)
    ran = []

    class R:
        returncode = 0
    monkeypatch.setattr(updates.subprocess, "run", lambda args, **k: ran.append(args) or R())
    return exe, ran


def test_install_backs_up_downloads_and_checks(tmp_path, frozen, library):
    exe, ran = frozen
    core.configure(library)
    core.scan_and_sync()
    folder = tmp_path / "backups"
    folder.mkdir()
    backup.set_settings(folder=str(folder))
    feed(tmp_path)
    r = updates.install(Job())
    assert r == {"version": "99.0.0", "ready": True, "backup": "done"}
    assert open(str(exe) + ".new", "rb").read() == NEW and open(exe, "rb").read() == b"MZ old minerva"
    assert ran == [[str(exe) + ".new", "--selftest"]]
    assert [n for n in os.listdir(folder) if n.endswith(".zip")]


def test_install_refuses_a_bad_download(tmp_path, frozen, monkeypatch):
    exe, ran = frozen
    feed(tmp_path, data=b"MZ tampered!!!")  # the same size, a different file
    with pytest.raises(updates.UpdateError, match="didn't match"):
        updates.install(Job())
    assert not os.path.exists(str(exe) + ".new")

    class Bad:
        returncode = 1
    feed(tmp_path)
    monkeypatch.setattr(updates.subprocess, "run", lambda args, **k: Bad())
    with pytest.raises(updates.UpdateError, match="its own check"):
        updates.install(Job())
    assert not os.path.exists(str(exe) + ".new")


def test_install_only_where_it_can(tmp_path, monkeypatch):
    feed(tmp_path)
    with pytest.raises(updates.UpdateError, match="can't update itself"):
        updates.install(Job())
    assert not updates.status()["can_install"]


def test_restart_writes_the_swap_script(tmp_path, frozen, monkeypatch):
    exe, ran = frozen
    with pytest.raises(updates.UpdateError):
        updates.restart()
    (exe.parent / "Minerva.exe.new").write_bytes(NEW)
    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **k: started.append(args))
    assert updates.restart()
    script = (exe.parent / "minerva-update.cmd").read_text()
    assert f'move /y "{exe}.new" "{exe}"' in script and f"PID eq {os.getpid()}" in script
    assert started[0][:2] == ["cmd.exe", "/c"]


def test_routes(client, tmp_path):
    feed(tmp_path)
    assert client.get("/api/updates").get_json()["current"] == __version__
    assert client.post("/api/updates/check", json={"force": True}).get_json()["available"]
    assert client.post("/api/updates/prefs", json={"auto": False}).get_json()["auto"] is False
    assert client.post("/api/updates/restart").status_code == 400


def test_restart_waits_for_the_window_process(tmp_path, frozen, monkeypatch):
    exe, ran = frozen
    (exe.parent / "Minerva.exe.new").write_bytes(NEW)
    monkeypatch.setenv("MINERVA_APP_PID", "4242")
    monkeypatch.setenv("PYINSTALLER_SUPPRESS_SPLASH_SCREEN", "1")
    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **k: started.append(k))
    updates.restart()
    assert "PID eq 4242" in (exe.parent / "minerva-update.cmd").read_text()
    # the new copy is started without this copy's process markers
    assert "MINERVA_APP_PID" not in started[0]["env"]
    assert "PYINSTALLER_SUPPRESS_SPLASH_SCREEN" not in started[0]["env"]

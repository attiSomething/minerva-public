import logging
import os
import sys
import threading
import time
import zipfile

import pytest

from minerva import launch, logs, server


@pytest.fixture
def logfile(monkeypatch):
    """Logging set up into this test's own config folder, then taken down."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logs.faulthandler, "enable", lambda **kw: None)
    monkeypatch.setattr(logs, "_watch", lambda: None)
    monkeypatch.setattr(logs.setup, "done", False, raising=False)
    before = {name: list(logging.getLogger(name).handlers) for name in ("minerva", "pywebview", "werkzeug")}
    logs.setup()
    yield os.path.join(logs.logs_dir(), logs.LOG_NAME)
    for name, handlers in before.items():
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            if h not in handlers:
                lg.removeHandler(h)
                h.close()
    if logs._crash_file:
        logs._crash_file.close()
        logs._crash_file = None


def _read(path):
    for h in logs.log.handlers:
        h.flush()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _wait_done():
    for _ in range(200):
        s = launch.status()
        if s["done"] or s["error"]:
            return s
        time.sleep(0.02)
    raise AssertionError("launch never finished")


def test_open_library_reports_each_step(client, library):
    steps = []
    info = server.open_library(library, lambda label, pct: steps.append((label, pct)))
    assert info["total_entries"] == 3
    labels = [label for label, _ in steps]
    assert labels[0] == "Opening your library"
    assert any(label.startswith("Reading your library") for label in labels)
    assert labels[-1].startswith("Checking your library")
    pcts = [p for _, p in steps]
    assert pcts == sorted(pcts) and pcts[-1] < 100


def test_launch_reopens_the_last_library_in_the_background(client, library, logfile):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    from minerva import core
    core.ARCHIVE_ROOT = core.DB_PATH = None

    server.start_launch()
    s = _wait_done()
    assert s["done"] and s["percent"] == 100 and s["error"] is None
    assert core.ARCHIVE_ROOT == os.path.abspath(library)
    text = _read(logfile)
    assert "now Opening your library" in text and "Launch finished" in text


def test_launch_status_needs_no_library(client):
    # the launch screen asks before any library is open
    r = client.get("/api/launch")
    assert r.status_code == 200
    assert {"label", "percent", "done", "error"} <= set(r.get_json())


def test_a_failed_launch_is_shown_and_can_be_retried(logfile):
    calls = []

    def work(step):
        calls.append(1)
        step("Opening your library", 10)
        if len(calls) == 1:
            raise OSError("The network path was not found")

    launch.start(work)
    s = _wait_done()
    assert s["error"] == "The network path was not found" and not s["done"]
    assert "Launch failed" in _read(logfile)

    launch.start(work)
    assert _wait_done()["done"]


def test_a_stalled_step_dumps_every_thread(monkeypatch, logfile):
    release = threading.Event()
    monkeypatch.setattr(launch, "STALL_SECONDS", 0)
    launch.start(lambda step: (step("Reading your library", 40), release.wait(5)))
    time.sleep(0.05)
    launch.status()
    release.set()
    _wait_done()
    text = _read(logfile)
    assert "Launch has been on 'Reading your library'" in text
    assert "Thread launch:" in text


def test_page_errors_and_slow_requests_are_logged(client, logfile, monkeypatch):
    client.post("/api/log", json={"level": "error", "message": "TypeError: x is undefined (home.js:12)"})
    monkeypatch.setattr(logs, "SLOW_SECONDS", 0)
    client.get("/api/setup/status?secret=shh")
    text = _read(logfile)
    assert "ERROR" in text and "Page: TypeError: x is undefined" in text
    assert "GET /api/setup/status took" in text
    assert "shh" not in text  # query strings stay out of the log


def test_unhandled_route_errors_are_logged(client, logfile, monkeypatch):
    def boom():
        raise RuntimeError("kaboom")
    monkeypatch.setattr(server.launch, "status", boom)
    server.app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        assert client.get("/api/launch").status_code == 500
    finally:
        server.app.config["PROPAGATE_EXCEPTIONS"] = None
    text = _read(logfile)
    assert "kaboom" in text and "GET /api/launch -> 500" in text


def test_save_logs_makes_a_zip(client, logfile, tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "downloads_dir", lambda: str(tmp_path))
    monkeypatch.setattr(server, "_reveal", lambda path: None)
    logs.log.info("something worth seeing")
    r = client.post("/api/logs/save").get_json()
    assert os.path.dirname(r["path"]) == str(tmp_path)
    with zipfile.ZipFile(r["path"]) as zf:
        names = zf.namelist()
        assert "system.txt" in names and logs.LOG_NAME in names
        assert b"something worth seeing" in zf.read(logs.LOG_NAME)
        assert b"Minerva " in zf.read("system.txt")
    recent = client.get("/api/logs").get_json()
    assert "something worth seeing" in recent["recent"]


def test_the_library_runs_in_its_own_process(monkeypatch):
    import urllib.request

    from minerva import desktop
    monkeypatch.delenv("MINERVA_APP_PID", raising=False)
    monkeypatch.delenv("PYINSTALLER_SUPPRESS_SPLASH_SCREEN", raising=False)
    proc, pipe, port = desktop._start_library_process(0, launch=False, log=False)
    try:
        assert proc.pid != os.getpid()
        assert os.environ["MINERVA_APP_PID"] == str(os.getpid())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
            assert b'"ok"' in resp.read()
    finally:
        desktop._stop_library_process(proc, pipe)
    assert proc.exitcode == 0


def test_a_hang_writes_every_stack_to_crash_log(logfile):
    if not logs._crash_file:
        pytest.skip("crash.log couldn't be opened")
    logs.watch_for_hang(0.2, 5)
    time.sleep(0.6)
    logs.cancel_hang_watch()
    logs._crash_file.flush()
    with open(os.path.join(logs.logs_dir(), logs.CRASH_NAME), encoding="utf-8") as fh:
        assert "Thread" in fh.read()

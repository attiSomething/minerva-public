"""Minerva's log, kept on this computer so a problem can be looked into after
the fact: each launch step and how long it took, requests that were slow or
failed, errors from the page, and a stack dump of anything stuck.

The library work runs in its own process (see desktop.py) and logs to
minerva.log; the window's process logs to window.log. Both sit in the logs
folder beside Minerva's settings, rotated at 1 MB with four older files
kept. A hard crash, or a hang during launch, writes every thread's stack to
crash.log, even when the stuck code is holding Python's lock. Request
lines carry the path only, never query strings or bodies, so the log has no
writing in it, though an error message can name a file.
"""

import datetime
import faulthandler
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
import traceback
import zipfile

from . import __version__
from . import config as app_config

log = logging.getLogger("minerva")

LOG_NAME = "minerva.log"
WINDOW_LOG_NAME = "window.log"
CRASH_NAME = "crash.log"
SLOW_SECONDS = 2.0    # a request taking longer is logged
STUCK_SECONDS = 20.0  # a request taking longer gets its stack dumped

_crash_file = None
_inflight = {}  # thread id -> [path, started, dumped]
_inflight_lock = threading.Lock()


def logs_dir():
    return os.path.join(app_config.config_dir(), "logs")


def setup(filename=LOG_NAME):
    """Start logging to the file. Safe to call more than once."""
    global _crash_file
    if getattr(setup, "done", False):
        return
    setup.done = True
    folder = logs_dir()
    try:
        os.makedirs(folder, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(folder, filename), maxBytes=1_000_000, backupCount=4, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-7s [%(threadName)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # pywebview and werkzeug report their own trouble (WebView2 missing, a
    # socket error) through these
    for name in ("pywebview", "werkzeug"):
        other = logging.getLogger(name)
        other.addHandler(handler)
        other.setLevel(logging.WARNING)
        other.propagate = False

    try:
        _crash_file = open(os.path.join(folder, CRASH_NAME), "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except (OSError, ValueError, RuntimeError):
        pass

    def on_error(kind, info):
        log.error("Unhandled error in %s:\n%s", kind, "".join(traceback.format_exception(*info)).rstrip())

    sys.excepthook = lambda *info: on_error("the main thread", info)
    threading.excepthook = lambda a: on_error(
        f"thread {a.thread.name if a.thread else '?'}", (a.exc_type, a.exc_value, a.exc_traceback))

    log.info("---- Minerva %s %s starting: Python %s on %s (%s)", __version__,
             "window" if filename == WINDOW_LOG_NAME else "library process", platform.python_version(),
             platform.platform(), "packaged" if getattr(sys, "frozen", False) else "from source")
    threading.Thread(target=_watch, name="log-watchdog", daemon=True).start()


# ---- requests ---------------------------------------------------------------

def request_started(path):
    with _inflight_lock:
        _inflight[threading.get_ident()] = [path, time.monotonic(), False]


def request_finished(method, path, status):
    with _inflight_lock:
        item = _inflight.pop(threading.get_ident(), None)
    if not item:
        return
    took = time.monotonic() - item[1]
    if status >= 500:
        log.error("%s %s -> %s after %.1fs", method, path, status, took)
    elif took >= SLOW_SECONDS:
        log.warning("%s %s took %.1fs (%s)", method, path, took, status)


def _thread_stack(ident):
    frame = sys._current_frames().get(ident)
    return "".join(traceback.format_stack(frame)).rstrip() if frame else "(no stack)"


def _watch():
    while True:
        time.sleep(5)
        now = time.monotonic()
        with _inflight_lock:
            stuck = [(i, p, now - t) for i, (p, t, dumped) in _inflight.items() if not dumped and now - t > STUCK_SECONDS]
            for i, _, _ in stuck:
                _inflight[i][2] = True
        for ident, path, took in stuck:
            log.warning("%s is still running after %.0fs. Where it is:\n%s", path, took, _thread_stack(ident))


def watch_for_hang(seconds, give_up_after):
    """Until cancel_hang_watch(), write every thread's stack to crash.log
    each `seconds`, for at most `give_up_after` seconds. This runs in C, so
    it works even when the stuck code is holding Python's lock and the
    log-watchdog thread can't run."""
    if not _crash_file:
        return
    try:
        faulthandler.dump_traceback_later(seconds, repeat=True, file=_crash_file)
    except (ValueError, RuntimeError):
        return
    t = threading.Timer(give_up_after, cancel_hang_watch)
    t.daemon = True
    t.start()


def cancel_hang_watch():
    try:
        faulthandler.cancel_dump_traceback_later()
    except (ValueError, RuntimeError):
        pass


def reveal(path):
    """Show a folder, or a file selected in its folder, in Explorer."""
    import subprocess
    if sys.platform == "win32":
        args = ["explorer", os.path.normpath(path)] if os.path.isdir(path) else ["explorer", "/select,", os.path.normpath(path)]
    elif sys.platform == "darwin":
        args = ["open", "-R", path]
    else:
        args = ["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)]
    subprocess.Popen(args)


def dump_all_threads(reason):
    """Write every thread's stack to the log: used when launch stalls."""
    names = {t.ident: t.name for t in threading.enumerate()}
    parts = [f"Thread {names.get(i, i)}:\n{_thread_stack(i)}" for i in sys._current_frames()]
    log.warning("%s. All threads:\n%s", reason, "\n\n".join(parts))


# ---- sharing the logs ---------------------------------------------------------

def _files():
    folder = logs_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names
            if n.startswith((LOG_NAME, WINDOW_LOG_NAME, CRASH_NAME)) and os.path.isfile(os.path.join(folder, n))]


def recent(lines=400):
    """The end of the current log, for showing in the app."""
    path = os.path.join(logs_dir(), LOG_NAME)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return ""


def _system_info(extra):
    rows = [
        f"Minerva {__version__}",
        f"Saved {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Windows/OS: {platform.platform()}",
        f"Python {platform.python_version()} ({'packaged' if getattr(sys, 'frozen', False) else 'from source'})",
        f"Settings folder: {app_config.config_dir()}",
    ]
    rows += [f"{k}: {v}" for k, v in (extra or {}).items()]
    return "\n".join(rows) + "\n"


def downloads_dir():
    home = os.path.expanduser("~")
    folder = os.path.join(home, "Downloads")
    return folder if os.path.isdir(folder) else home


def save_zip(dest_folder=None, extra=None):
    """Zip the logs with a short system summary and return the zip's path."""
    for h in log.handlers:
        h.flush()
    folder = dest_folder or downloads_dir()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
    path = os.path.join(folder, f"Minerva logs {stamp}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system.txt", _system_info(extra))
        for f in _files():
            zf.write(f, os.path.basename(f))
    log.info("Saved the logs to %s", path)
    return path

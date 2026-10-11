"""What Minerva is doing while it starts, for the launch screen.

The window opens straight away and the library is opened behind it, in a
thread, so the page can show each step and how far along it is instead of a
blank window. Every step is logged with how long it took, and a step that
stalls gets every thread's stack written to the log.
"""

import threading
import time

from .logs import cancel_hang_watch, dump_all_threads, log, watch_for_hang

STALL_SECONDS = 30
HANG_DUMP_SECONDS = 25   # crash.log gets every stack this often...
HANG_WATCH_LIMIT = 300   # ...until Home is up, or for at most this long

_lock = threading.Lock()
_state = {}
_thread = None


def _reset():
    _state.clear()
    _state.update(label="Starting Minerva", percent=0, done=False, error=None, step_started=time.monotonic(),
                  phase_started=time.monotonic(), dumped=False)


_reset()
_state.update(done=True, percent=100, label="Ready")  # nothing to do until start() is called


def step(label, percent):
    """Report progress. A label's part before any colon names the step
    ("Reading your library: 40 of 600 folders"): only a new step is logged,
    but any change counts as moving, for the stall check."""
    with _lock:
        prev = _state["label"]
        took = time.monotonic() - _state["phase_started"]
        new_phase = label.split(":")[0] != prev.split(":")[0]
        _state.update(label=label, percent=max(0, min(100, int(percent))))
        if label != prev:
            _state.update(step_started=time.monotonic(), dumped=False)
        if new_phase:
            _state["phase_started"] = time.monotonic()
    if new_phase:
        log.info("Launch: %s took %.1fs; now %s", prev.split(":")[0], took, label)


def status():
    with _lock:
        s = dict(_state)
    stalled = time.monotonic() - s.pop("step_started")
    s.pop("phase_started")
    if not s["done"] and stalled > STALL_SECONDS and not s["dumped"]:
        with _lock:
            _state["dumped"] = True
        dump_all_threads(f"Launch has been on '{s['label']}' for {stalled:.0f}s")
    s.pop("dumped")
    s["seconds_on_step"] = round(stalled, 1)
    return s


def start(work):
    """Run work(step) in a thread. work gets step() to report with."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _reset()
    started = time.monotonic()
    watch_for_hang(HANG_DUMP_SECONDS, HANG_WATCH_LIMIT)

    def run():
        try:
            work(step)
        except Exception as e:  # shown on the launch screen with a Try again button
            log.exception("Launch failed")
            with _lock:
                _state.update(error=str(e) or e.__class__.__name__)
            return
        step("Ready", 100)
        with _lock:
            _state["done"] = True
        log.info("Launch finished in %.1fs", time.monotonic() - started)

    _thread = threading.Thread(target=run, name="launch", daemon=True)
    _thread.start()


def home_ready(seconds):
    """The page has drawn Home (or first-time setup): launch is over."""
    cancel_hang_watch()
    log.info("Launch: the page was ready %.1fs after it opened", seconds)

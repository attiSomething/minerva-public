"""Start Minerva: the local server plus a native window (or a browser tab
with --browser). This is what Minerva.exe runs.

There are two processes. The library process runs the server and does all
the reading, indexing and saving. The window's process only draws the
window. In one process, a long stretch of library work could hold Python's
lock and leave the window frozen ("Not responding"), so the window couldn't
even show what was happening.
"""

import argparse
import json
import multiprocessing
import os
import sys
import threading
import time
import urllib.request
import webbrowser

from . import __version__
from . import logs


class _ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        from werkzeug.serving import make_server

        from . import server
        self.httpd = make_server("127.0.0.1", port, server.app, threaded=True)
        self.port = self.httpd.server_port

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


class Bridge:
    """Functions the page can call through window.pywebview.api."""

    def __init__(self):
        self.window = None

    def pick_folder(self):
        import webview

        dialog = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if dialog is None:
            dialog = webview.FOLDER_DIALOG
        result = self.window.create_file_dialog(dialog)
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def open_external(self, url):
        webbrowser.open(url)

    # Save logs / Open logs folder: done here, in the window's process, so
    # they work even while the library process is busy or stuck
    def save_logs(self):
        try:
            path = logs.save_zip(extra={"Saved from": "the window"})
            logs.reveal(path)
        except OSError as e:
            return {"error": f"Couldn't save the logs: {e}"}
        return {"path": path}

    def open_logs(self):
        os.makedirs(logs.logs_dir(), exist_ok=True)
        logs.reveal(logs.logs_dir())
        return {"ok": True}


# ---- the library process ------------------------------------------------------

def _serve(conn, port, launch, log):
    """Run the server until the window's process says stop, or goes away."""
    if log:
        logs.setup()
    srv = _ServerThread(port)
    srv.start()
    conn.send(srv.port)
    logs.log.info("Server listening on port %s", srv.port)
    if launch:
        from . import server
        server.start_launch()
    try:
        conn.recv()
        logs.log.info("Closing: the window asked")
    except (EOFError, OSError):
        logs.log.warning("Closing: the window's process went away")
    srv.stop()
    from . import grammar
    grammar.stop()
    import logging
    logging.shutdown()
    os._exit(0)


def _start_library_process(port, launch=True, log=True):
    """Start the library process; returns (process, pipe, port)."""
    # an update waits for this process, the one holding Minerva.exe open, to
    # close; and a child of the packaged app mustn't show the splash again
    os.environ["MINERVA_APP_PID"] = str(os.getpid())
    os.environ["PYINSTALLER_SUPPRESS_SPLASH_SCREEN"] = "1"
    ctx = multiprocessing.get_context("spawn")  # Windows' only way; the same everywhere
    ours, theirs = ctx.Pipe()
    proc = ctx.Process(target=_serve, args=(theirs, port, launch, log), name="minerva-library")
    proc.start()
    theirs.close()
    if not ours.poll(60):
        proc.terminate()
        raise RuntimeError("Minerva's library process didn't start within a minute.")
    return proc, ours, ours.recv()


def _stop_library_process(proc, pipe):
    try:
        pipe.send("stop")
    except OSError:
        pass
    proc.join(15)
    if proc.is_alive():
        proc.terminate()


def _selftest_bundled_libraries():
    """Scanning renders PDF pages with pdfium and Pillow, and talks to
    Anthropic through its SDK; exports use python-docx and ReportLab. Make
    sure all of them made it into the bundle."""
    import tempfile

    import anthropic
    from PIL import Image

    from . import scanning

    assert hasattr(anthropic.Anthropic(api_key="selftest").messages, "stream")
    with tempfile.TemporaryDirectory() as tmp:
        pdf = os.path.join(tmp, "page.pdf")
        Image.new("RGB", (200, 300), "white").save(pdf)
        jpeg = scanning.render_page({"path": pdf, "filename": "page.pdf", "is_pdf": True}, 1)
        assert jpeg[:2] == b"\xff\xd8", "PDF page didn't render"
        # exports: Word through python-docx, PDF through ReportLab
        import docx
        from reportlab.pdfgen import canvas

        from . import sharing
        docx.Document().save(os.path.join(tmp, "out.docx"))
        sharing._fonts()
        c = canvas.Canvas(os.path.join(tmp, "out.pdf"))
        c.setFont(sharing._fonts()["regular"], 12)
        c.drawString(72, 72, "Minerva \u2014 \u201cself-test\u201d")
        c.save()


def _selftest(url):
    """Used by CI on the built app: start the server and check that the page,
    its scripts, and the help docs are all inside the bundle."""
    for _ in range(50):
        try:
            urllib.request.urlopen(url + "api/health", timeout=2).close()
            break
        except OSError:
            time.sleep(0.1)
    try:
        page = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
        assert "onboarding.js" in page
        for asset in ("static/app.js", "static/launch.js", "static/onboarding.js", "static/scanning.js", "static/scanintake.js", "static/sharing.js",
                      "static/home.js", "static/submissions.js", "static/backup.js", "static/libcheck.js", "static/search.js", "static/compare.js", "static/goals.js", "static/focus.js", "static/venues.js", "static/categories.js", "static/images.js", "static/people.js", "static/views.js", "static/outline.js", "static/tags.js", "static/readaloud.js", "static/newentry.js", "static/fileimport.js", "static/findreplace.js", "static/firstrun.js", "static/help.js", "static/foldersync.js", "static/localai.js", "static/comingup.js", "static/snippets.js", "static/narration.js", "static/video.js", "static/grammar.js", "static/updates.js", "static/exportall.js", "static/research.js", "static/style.css",
                      "static/owl.svg", "static/owl-small.svg"):
            urllib.request.urlopen(url + asset, timeout=5).close()
        with urllib.request.urlopen(url + "api/docs", timeout=5) as resp:
            assert json.loads(resp.read().decode("utf-8")), "help docs missing"
        with urllib.request.urlopen(url + "api/howtos", timeout=5) as resp:
            assert len(json.loads(resp.read().decode("utf-8"))) >= 8, "how-tos missing"
        _selftest_bundled_libraries()
    except Exception as e:
        print(f"Minerva {__version__} self-test failed: {e!r}")
        return 1
    print(f"Minerva {__version__} self-test: ok")
    return 0


def _close_splash():
    """The packaged app shows a splash while it unpacks (see
    packaging/build.py); close it once the window is up."""
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:  # not the packaged app, or already closed
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(prog="Minerva")
    parser.add_argument("--browser", action="store_true", help="open in your web browser instead of a window")
    parser.add_argument("--port", type=int, default=0, help="port for the local server (default: any free port)")
    parser.add_argument("--logs", action="store_true", help="open the folder with Minerva's logs")
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.logs:
        os.makedirs(logs.logs_dir(), exist_ok=True)
        logs.reveal(logs.logs_dir())
        return 0

    started = time.monotonic()
    if args.selftest:
        # the self-test is also run on a downloaded update while this copy
        # is open, so it leaves the log files to the running app; it checks
        # the bundle, not a library, so it doesn't open one
        _close_splash()
        proc, pipe, port = _start_library_process(args.port, launch=False, log=False)
        code = _selftest(f"http://127.0.0.1:{port}/")
        _stop_library_process(proc, pipe)
        return code

    logs.setup(logs.WINDOW_LOG_NAME)
    try:
        proc, pipe, port = _start_library_process(args.port)
    except Exception:
        logs.log.exception("Couldn't start the library process")
        _close_splash()
        raise
    url = f"http://127.0.0.1:{port}/"
    logs.log.info("Library process %s is serving on port %s (%.1fs after start)", proc.pid, port,
                  time.monotonic() - started)

    if not args.browser:
        try:
            import webview

            bridge = Bridge()
            window = bridge.window = webview.create_window(
                "Minerva", url, js_api=bridge, width=1320, height=880, min_size=(960, 640)
            )
            try:
                window.events.loaded += lambda: logs.log.info(
                    "Window loaded the page (%.1fs after start)", time.monotonic() - started)
            except AttributeError:  # an older pywebview: just no line in the log
                pass

            closing = threading.Event()

            def watch_library():
                # it closes itself to install an update; the window goes too
                proc.join()
                if not closing.is_set():
                    logs.log.warning("The library process ended (exit code %s); closing the window", proc.exitcode)
                    window.destroy()

            def on_start():
                _close_splash()
                threading.Thread(target=watch_library, name="watch-library", daemon=True).start()

            logs.log.info("Opening the window")
            webview.start(on_start)
            closing.set()
            logs.log.info("Window closed")
            _stop_library_process(proc, pipe)
            return 0
        except Exception as e:  # no WebView2 runtime, missing GUI libs, etc.
            logs.log.exception("Couldn't open the Minerva window; using the browser instead")
            print(f"Couldn't open the Minerva window ({e}); opening your browser instead.")

    _close_splash()
    print(f"Minerva is running at {url}  (close this window to stop it)")
    webbrowser.open(url)
    try:
        proc.join()
    except KeyboardInterrupt:
        pass
    _stop_library_process(proc, pipe)
    return 0


if __name__ == "__main__":
    sys.exit(main())

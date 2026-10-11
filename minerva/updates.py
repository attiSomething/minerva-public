"""Updates: tell the writer when a new Minerva is out, show what changed,
and install it when asked.

New versions are published as GitHub releases (see .github/workflows),
each with Minerva.exe attached. Minerva asks GitHub at most once a day,
when automatic checks are on (Settings). Installing backs the library up
first when a backup folder is set, downloads the new Minerva.exe beside
the running one, checks it (its size and GitHub's SHA-256, then its own
self-test), and swaps it in once this copy has closed. The old one is
kept as Minerva.exe.old until the next update, so it can be put back by
hand. The library itself is never touched by an update.
"""

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

from . import __version__, backup, config as app_config

FEED = "https://api.github.com/repos/attiSomething/Minerva-public/releases/latest"
RELEASES_PAGE = "https://github.com/attiSomething/Minerva-public/releases"
ASSET = "Minerva.exe"
CHECK_EVERY = datetime.timedelta(hours=20)
MB = 1024 * 1024


class UpdateError(Exception):
    user_facing = True


def _version(tag):
    """'v0.8.1' -> (0, 8, 1); anything unreadable sorts lowest."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)", (tag or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def newer(tag, than=__version__):
    a, b = _version(tag), _version(than)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def prefs():
    u = dict(app_config.load().get("updates") or {})
    return {"auto": u.get("auto", True) is not False, "skipped": u.get("skipped") or "",
            "checked_at": u.get("checked_at") or "", "latest": u.get("latest") or None,
            "feed": u.get("feed") or FEED}


def _store(**changes):
    cfg = app_config.load()
    u = dict(cfg.get("updates") or {})
    u.update(changes)
    cfg["updates"] = u
    app_config.save(cfg)


def set_prefs(auto=None, skipped=None):
    if auto is not None:
        _store(auto=bool(auto))
    if skipped is not None:
        _store(skipped=str(skipped))
    return status()


def can_install():
    """Only the packaged Windows app replaces itself; running from source
    is updated with git."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt" and os.path.basename(sys.executable).lower().endswith(".exe")


def _fetch(feed):
    req = urllib.request.Request(feed, headers={"Accept": "application/vnd.github+json", "User-Agent": f"Minerva/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("No published Minerva versions were found to check against.") from None
        raise UpdateError(f"Couldn't check for updates (GitHub said {e.code}).") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(f"Couldn't check for updates ({getattr(e, 'reason', e)}). Check your internet connection.") from None
    asset = next((a for a in d.get("assets") or [] if a.get("name") == ASSET), None)
    digest = (asset or {}).get("digest") or ""
    return {"version": (d.get("tag_name") or "").lstrip("v"), "name": d.get("name") or d.get("tag_name") or "",
            "notes": d.get("body") or "", "published": d.get("published_at") or "", "page": d.get("html_url") or RELEASES_PAGE,
            "url": (asset or {}).get("browser_download_url") or "", "size": (asset or {}).get("size") or 0,
            "sha256": digest[7:] if digest.startswith("sha256:") else ""}


def status():
    p = prefs()
    latest = p["latest"]
    available = bool(latest) and newer(latest["version"])
    return {"current": __version__, "auto": p["auto"], "checked_at": p["checked_at"], "latest": latest,
            "available": available, "skipped": available and p["skipped"] == latest["version"],
            "can_install": can_install(), "releases_page": RELEASES_PAGE,
            "ready": can_install() and available and os.path.isfile(sys.executable + ".new")}


def check(force=False, now=None):
    """Ask GitHub for the newest version (at most once a day unless forced,
    and never when automatic checks are off and it isn't forced)."""
    p = prefs()
    now = now or datetime.datetime.now()
    if not force:
        if not p["auto"]:
            return status()
        if p["checked_at"]:
            try:
                if now - datetime.datetime.fromisoformat(p["checked_at"]) < CHECK_EVERY:
                    return status()
            except ValueError:
                pass
    try:
        latest = _fetch(p["feed"])
    except UpdateError:
        _store(checked_at=now.isoformat(timespec="seconds"))
        if force:
            raise
        return status()
    _store(checked_at=now.isoformat(timespec="seconds"), latest=latest)
    return status()


# --------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------

_SWAP = r"""@echo off
rem Written by Minerva to finish an update: wait for Minerva to close,
rem put the new version in place, keep the old one beside it, and start it.
set tries=0
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  set /a tries+=1
  if %tries% lss 60 (timeout /t 1 /nobreak >nul & goto wait)
)
del /f /q "{old}" >nul 2>&1
move /y "{exe}" "{old}" >nul || goto failed
move /y "{new}" "{exe}" >nul || (move /y "{old}" "{exe}" >nul & goto failed)
start "" "{exe}"
del "%~f0" & exit /b 0
:failed
start "" "{exe}"
del "%~f0"
"""


def _no_window():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def _backup(job):
    s = backup.status()
    if not s["folder"]:
        return "skipped"
    if not s["folder_ok"]:
        raise UpdateError("The backup folder isn't available, so Minerva didn't update. Plug in the drive, or update after "
                          "choosing another folder in Settings.")
    job.progress(0, 0, "Backing up your library first")
    backup.run(job, changes_only=bool(s["last"]))
    return "done"


def _download(latest, dest, job):
    if not latest.get("url"):
        raise UpdateError(f"That version has no {ASSET} to download. Get it from {RELEASES_PAGE}.")
    digest = hashlib.sha256()
    done = 0
    req = urllib.request.Request(latest["url"], headers={"User-Agent": f"Minerva/{__version__}", "Accept": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or latest.get("size") or 0)
            while True:
                if job.cancelled():
                    raise UpdateError("Stopped.")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                job.progress(done, total, f"Downloading Minerva {latest['version']}: {done // MB} of {total // MB} MB")
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"Couldn't download the update ({getattr(e, 'reason', e)}). Check your internet connection.") from None
    if latest.get("size") and done != latest["size"]:
        raise UpdateError("The download was cut short. Try again.")
    if latest.get("sha256") and digest.hexdigest() != latest["sha256"].lower():
        raise UpdateError("The download didn't match what GitHub published, so it wasn't used.")


def install(job):
    """The background job: back up, download, check. Returns what restart()
    needs; nothing is replaced until then."""
    if not can_install():
        raise UpdateError(f"This copy of Minerva can't update itself. Download the new version from {RELEASES_PAGE}.")
    latest = check(force=True)["latest"]
    if not latest or not newer(latest["version"]):
        raise UpdateError("This is already the newest Minerva.")
    exe = sys.executable
    if not os.access(os.path.dirname(exe), os.W_OK):
        raise UpdateError(f"Minerva is in a folder it isn't allowed to change ({os.path.dirname(exe)}). "
                          f"Download the new version from {RELEASES_PAGE}, or move Minerva.exe to a folder of your own.")
    backed_up = _backup(job)
    new = exe + ".new"
    try:
        _download(latest, new, job)
        job.progress(0, 0, "Checking the new version")
        try:
            ok = subprocess.run([new, "--selftest"], timeout=180, capture_output=True, **_no_window()).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if not ok:
            raise UpdateError("The new version didn't pass its own check, so Minerva kept this one. Try again later.")
    except Exception:
        if os.path.exists(new):
            os.remove(new)
        raise
    return {"version": latest["version"], "ready": True, "backup": backed_up}


def restart():
    """Hand over to the swap script and close; the new version opens."""
    exe = sys.executable
    new = exe + ".new"
    if not can_install() or not os.path.isfile(new):
        raise UpdateError("There's no downloaded update to install.")
    script = os.path.join(os.path.dirname(exe), "minerva-update.cmd")
    with open(script, "w", encoding="ascii", errors="replace") as fh:
        # wait for the window's process (it holds Minerva.exe open), which
        # closes when this library process does
        pid = os.environ.get("MINERVA_APP_PID") or os.getpid()
        fh.write(_SWAP.format(pid=pid, exe=exe, new=new, old=exe + ".old"))
    # the new copy starts like any other launch, splash and all
    env = {k: v for k, v in os.environ.items() if k not in ("MINERVA_APP_PID", "PYINSTALLER_SUPPRESS_SPLASH_SCREEN")}
    subprocess.Popen(["cmd.exe", "/c", script], close_fds=True, env=env,
                     creationflags=0x08000000 | 0x00000008 | 0x00000200)  # no window, detached, new group
    return True

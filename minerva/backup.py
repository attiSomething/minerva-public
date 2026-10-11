"""Backups: copy the whole library into a zip in a folder the user picks
(another drive, OneDrive, a USB stick).

A backup never touches the library itself and never overwrites or prunes an
earlier backup; each run writes a new, dated zip. Minerva's index is copied
with SQLite's backup API so the zip holds a consistent snapshot even while
the app is using it.

"Changes only" backups hold just the files modified since the last backup
of any kind. They are quick, but restoring needs the last full backup too.
"""

import datetime
import os
import sqlite3
import tempfile
import zipfile

from . import config as app_config
from . import core

# already-compressed formats are stored as is; deflating them only costs time
_STORED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".pdf", ".zip", ".docx", ".mp3", ".m4a", ".mp4"}
_SKIP_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".partial")
REMIND_CHOICES = (0, 1, 3, 7, 14, 30)


class BackupError(Exception):
    user_facing = True


def _settings(cfg, root):
    s = (cfg.get("backups") or {}).get(root) or {}
    return {"folder": s.get("folder") or "", "remind_days": s.get("remind_days", 7),
            "last": s.get("last")}


def _store(root, **changes):
    cfg = app_config.load()
    allb = cfg.setdefault("backups", {})
    cur = allb.setdefault(root, {})
    cur.update(changes)
    app_config.save(cfg)
    return _settings(cfg, root)


def status(now=None):
    root = core.ARCHIVE_ROOT
    s = _settings(app_config.load(), root)
    now = now or datetime.datetime.now()
    due = False
    if s["remind_days"]:
        if not s["last"]:
            due = True
        else:
            when = datetime.datetime.fromisoformat(s["last"]["at"])
            due = (now - when).days >= s["remind_days"]
    s["due"] = due
    s["remind_choices"] = list(REMIND_CHOICES)
    s["folder_ok"] = bool(s["folder"]) and os.path.isdir(s["folder"])
    return s


def _inside(path, parent):
    path, parent = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def set_settings(folder=None, remind_days=None):
    root = core.ARCHIVE_ROOT
    changes = {}
    if folder is not None:
        folder = str(folder).strip().strip('"')
        if folder:
            folder = os.path.abspath(os.path.expanduser(folder))
            if not os.path.isdir(folder):
                raise BackupError("That folder doesn't exist.")
            if _inside(folder, root):
                raise BackupError("Pick a folder outside your library, ideally on another drive.")
        changes["folder"] = folder
    if remind_days is not None:
        try:
            remind_days = int(remind_days)
        except (TypeError, ValueError):
            raise BackupError("Pick how often to be reminded.") from None
        if remind_days not in REMIND_CHOICES:
            raise BackupError("Pick how often to be reminded.")
        changes["remind_days"] = remind_days
    _store(root, **changes)
    return status()


def _files(root, since=None):
    """Every file in the library, as (absolute path, path inside the zip).
    The live index database is left out; it is added separately as a
    snapshot."""
    db = os.path.normcase(os.path.abspath(core.DB_PATH)) if core.DB_PATH else None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            if name.endswith(_SKIP_SUFFIXES) or os.path.normcase(os.path.abspath(full)) == db:
                continue
            if since is not None:
                try:
                    if os.path.getmtime(full) <= since:
                        continue
                except OSError:
                    continue
            yield full, os.path.relpath(full, root)


def _unique(folder, base):
    path = os.path.join(folder, base + ".zip")
    n = 2
    while os.path.exists(path) or os.path.exists(path + ".partial"):
        path = os.path.join(folder, f"{base} ({n}).zip")
        n += 1
    return path


def run(job=None, changes_only=False, now=None):
    root = core.ARCHIVE_ROOT
    s = status()
    if not s["folder"]:
        raise BackupError("Choose a backup folder first.")
    if not os.path.isdir(s["folder"]):
        raise BackupError("The backup folder isn't available. Is the drive plugged in?")
    since = None
    if changes_only:
        if not s["last"]:
            raise BackupError("Make a full backup first; a changes-only backup builds on it.")
        since = datetime.datetime.fromisoformat(s["last"]["at"]).timestamp()

    now = now or datetime.datetime.now()
    libname = os.path.basename(root.rstrip(os.sep)) or "Library"
    stamp = now.strftime("%Y-%m-%d %H%M")
    base = f"{libname} backup {stamp}" + (" (changes)" if changes_only else "")
    dest = _unique(s["folder"], base)
    partial = dest + ".partial"

    files = list(_files(root, since))
    total = len(files) + 1
    count, size = 0, 0
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for i, (full, rel) in enumerate(files):
                if job is not None:
                    if job.cancelled():
                        break
                    job.progress(i, total, rel)
                try:
                    kind = zipfile.ZIP_STORED if os.path.splitext(full)[1].lower() in _STORED else zipfile.ZIP_DEFLATED
                    zf.write(full, os.path.join(libname, rel), compress_type=kind)
                except OSError:
                    continue  # a file that vanished or is locked mid-backup
                count += 1
                size += os.path.getsize(full)
            if job is None or not job.cancelled():
                _add_index_snapshot(zf, root, libname)
        if job is not None and job.cancelled():
            os.remove(partial)
            return None
        os.replace(partial, dest)
    except Exception:
        if os.path.exists(partial):
            os.remove(partial)
        raise
    if job is not None:
        job.progress(total, total, "Done")
    record = {"at": now.isoformat(timespec="seconds"), "file": dest, "files": count, "bytes": size,
              "zip_bytes": os.path.getsize(dest), "changes_only": changes_only}
    _store(root, last=record)
    return record


def _add_index_snapshot(zf, root, libname):
    if not core.DB_PATH or not os.path.exists(core.DB_PATH):
        return
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(core.DB_PATH)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        rel = os.path.relpath(core.DB_PATH, root)
        if rel.startswith(".."):
            rel = os.path.join(core.META_DIRNAME, "minerva.db")
        zf.write(tmp, os.path.join(libname, rel))
    finally:
        os.remove(tmp)

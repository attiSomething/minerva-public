"""Bringing scans in from a folder outside the library, usually one that
Google Drive, Dropbox or OneDrive keeps in sync (a phone's scanner app
saving straight to the cloud, say).

The chosen folder is only read. Its scans are copied into a source's Scans
folder under the library's scans folder, keeping their names; a file that's
already there (same name and size) is skipped, so bringing in the same
folder again picks up only the new scans. Each source remembers the folder
it came from in .minerva/scan_origins.json for "Check for new scans".

Files the cloud app hasn't downloaded yet ("online-only" in OneDrive and
Dropbox, "streamed" in Google Drive) are fetched by the cloud app when
Minerva reads them, which can be slow, so they're counted in the preview.
"""

import json
import os
import shutil
import stat
import sys

from . import core, scanning

MAX_FILES = 5000
MAX_DEPTH = 6

# Windows file attributes that mark a file as not on this computer yet
_WIN_CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000  # OFFLINE, RECALL_ON_OPEN, RECALL_ON_DATA_ACCESS
_MAC_DATALESS = 0x40000000  # SF_DATALESS


class IntakeError(ValueError):
    user_facing = True


# --------------------------------------------------------------------------
# Finding the cloud folders on this computer
# --------------------------------------------------------------------------

def _home():
    return os.path.expanduser("~")


def _dropbox_paths():
    """Dropbox writes where it keeps its folder to info.json."""
    found = []
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), os.path.join(_home(), ".dropbox")):
        if not base:
            continue
        info = os.path.join(base, "Dropbox", "info.json") if not base.endswith(".dropbox") else os.path.join(base, "info.json")
        try:
            with open(info, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for kind in ("personal", "business"):
            path = (data.get(kind) or {}).get("path")
            if path:
                found.append(("Dropbox" if kind == "personal" else "Dropbox (work)", path))
    found.append(("Dropbox", os.path.join(_home(), "Dropbox")))
    return found


def _google_drive_paths():
    found = []
    if sys.platform == "win32":
        # Drive for desktop shows up as its own drive letter, usually G:
        for letter in "GHIJKLMNOPQRSTUVWXYZDEF":
            for sub in ("My Drive", "Shared drives"):
                found.append(("Google Drive" if sub == "My Drive" else "Google Drive (shared)", f"{letter}:\\{sub}"))
    found.append(("Google Drive", os.path.join(_home(), "Google Drive")))
    found.append(("Google Drive", os.path.join(_home(), "My Drive")))
    return found


def _onedrive_paths():
    found = []
    for var, label in (("OneDriveConsumer", "OneDrive"), ("OneDriveCommercial", "OneDrive (work)"), ("OneDrive", "OneDrive")):
        if os.environ.get(var):
            found.append((label, os.environ[var]))
    found.append(("OneDrive", os.path.join(_home(), "OneDrive")))
    return found


def _mac_cloud_storage():
    """macOS keeps every cloud app's folder in ~/Library/CloudStorage."""
    root = os.path.join(_home(), "Library", "CloudStorage")
    found = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        low = name.lower()
        label = ("Google Drive" if low.startswith("googledrive") else
                 "Dropbox" if low.startswith("dropbox") else
                 "OneDrive" if low.startswith("onedrive") else None)
        if not label:
            continue
        path = os.path.join(root, name)
        my_drive = os.path.join(path, "My Drive")
        found.append((label, my_drive if os.path.isdir(my_drive) else path))
    return found


def cloud_folders():
    """[{"label", "path"}] for each cloud folder found on this computer."""
    candidates = _mac_cloud_storage() + _google_drive_paths() + _dropbox_paths() + _onedrive_paths()
    seen, out = set(), []
    for label, path in candidates:
        try:
            if not os.path.isdir(path):
                continue
            key = os.path.normcase(os.path.realpath(path))
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": label, "path": path})
    return out


# --------------------------------------------------------------------------
# Reading a folder
# --------------------------------------------------------------------------

def is_cloud_only(path, st=None):
    """True when the file's contents aren't on this computer yet."""
    try:
        st = st or os.stat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & _WIN_CLOUD_ATTRS:
        return True
    if getattr(st, "st_flags", 0) & _MAC_DATALESS:
        return True
    return False


def _check_folder(folder):
    folder = os.path.abspath(os.path.expanduser(str(folder or "").strip().strip('"')))
    if not folder or not os.path.isdir(folder):
        raise IntakeError("That folder can't be found. Is it spelled right, and is the drive or cloud app running?")
    if core.ARCHIVE_ROOT:
        lib = os.path.normcase(os.path.realpath(core.ARCHIVE_ROOT))
        here = os.path.normcase(os.path.realpath(folder))
        if here == lib or here.startswith(lib + os.sep):
            raise IntakeError("That folder is already inside your library. Pick a folder from outside it.")
    return folder


def find_scans(folder, subfolders=True):
    """Scan files in folder (and its subfolders), in name order, as
    [{"path", "rel", "size", "cloud_only"}]."""
    folder = _check_folder(folder)
    found = []

    def walk(path, depth):
        try:
            entries = sorted(os.scandir(path), key=lambda e: scanning._natural_key(e.name))
        except OSError:
            return
        for e in entries:
            if len(found) >= MAX_FILES:
                return
            if e.name.startswith((".", "~$")):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if subfolders and depth < MAX_DEPTH:
                        walk(e.path, depth + 1)
                    continue
                if os.path.splitext(e.name)[1].lower() not in scanning.SCAN_EXTS:
                    continue
                st = e.stat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            found.append({"path": e.path, "rel": os.path.relpath(e.path, folder),
                          "size": st.st_size, "cloud_only": is_cloud_only(e.path, st)})

    walk(folder, 0)
    return folder, found


def _target_name(rel):
    """A flat file name for a scan found at rel: files in subfolders get the
    subfolder's name in front, so "March/page 1.jpg" stays distinct from
    "April/page 1.jpg"."""
    parts = rel.replace("\\", "/").split("/")
    name = " - ".join(parts)
    return core.INVALID_FILENAME_CHARS_RE.sub(" ", name).strip()


def _source_folder_name(folder):
    name = os.path.basename(os.path.normpath(folder)) or "Scans"
    name = core.INVALID_FILENAME_CHARS_RE.sub(" ", name).strip(" .")
    return name or "Scans"


def _source_name(source, folder):
    source = (source or "").strip() or _source_folder_name(folder)
    if core.INVALID_FILENAME_CHARS_RE.search(source) or source.startswith(".") or source.endswith("."):
        raise IntakeError('Choose a source name without \\ / : * ? " < > | or a leading dot.')
    return source


def preview(folder, source=None, subfolders=True):
    folder, found = find_scans(folder, subfolders)
    source = _source_name(source, folder)
    existing = _existing(source)
    new = [f for f in found if existing.get(_target_name(f["rel"]).lower()) != f["size"]]
    return {
        "folder": folder,
        "source": source,
        "source_exists": source in existing_sources(),
        "files": len(found),
        "new": len(new),
        "already": len(found) - len(new),
        "bytes": sum(f["size"] for f in new),
        "cloud_only": sum(1 for f in new if f["cloud_only"]),
        "capped": len(found) >= MAX_FILES,
        "sample": [f["rel"] for f in new[:8]],
    }


def existing_sources():
    try:
        return {s["name"] for s in scanning.list_sources()["sources"]}
    except OSError:
        return set()


def _scans_dir(source):
    return os.path.join(scanning.scans_root(), source, "Scans")


def _existing(source):
    """{lower-case file name: size} already in the source's Scans folder."""
    folder = _scans_dir(source)
    try:
        return {e.name.lower(): e.stat().st_size for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return {}


# --------------------------------------------------------------------------
# Copying
# --------------------------------------------------------------------------

def _origins_path():
    return os.path.join(core.META_DIR, "scan_origins.json")


def origins():
    try:
        with open(_origins_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(source, folder, subfolders):
    data = origins()
    data[source] = {"folder": folder, "subfolders": bool(subfolders)}
    os.makedirs(core.META_DIR, exist_ok=True)
    tmp = _origins_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, _origins_path())


def bring_in(job, folder, source=None, subfolders=True):
    """Copy a folder's new scans into a source, creating it when needed.
    Never changes or removes anything in the chosen folder."""
    folder, found = find_scans(folder, subfolders)
    source = _source_name(source, folder)
    if not os.path.isdir(os.path.join(scanning.scans_root(), source)):
        scanning.create_source(source)
    dest = _scans_dir(source)
    os.makedirs(dest, exist_ok=True)
    existing = _existing(source)
    todo = [f for f in found if existing.get(_target_name(f["rel"]).lower()) != f["size"]]
    copied, skipped, failed = 0, len(found) - len(todo), []
    job.progress(0, len(todo), "Starting")
    for i, f in enumerate(todo):
        if job.cancelled():
            break
        name = _target_name(f["rel"])
        job.progress(i, len(todo), ("Downloading " if f["cloud_only"] else "Copying ") + f["rel"])
        target = os.path.join(dest, name)
        if os.path.exists(target):
            # same name, different size: keep both
            stem, ext = os.path.splitext(name)
            n = 2
            while os.path.exists(os.path.join(dest, f"{stem} ({n}){ext}")):
                n += 1
            target = os.path.join(dest, f"{stem} ({n}){ext}")
        part = target + ".part"
        try:
            shutil.copyfile(f["path"], part)
            os.replace(part, target)
            copied += 1
        except OSError as e:
            failed.append({"file": f["rel"], "error": e.strerror or str(e)})
            try:
                os.remove(part)
            except OSError:
                pass
    job.progress(len(todo), len(todo), "Done")
    _remember(source, folder, subfolders)
    return {"source": source, "copied": copied, "skipped": skipped, "failed": failed}

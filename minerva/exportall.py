"""Export everything: all of a writer's work and what Minerva knows about
it, in open formats anything can read, so nothing is ever locked in.

This is not a backup. A backup (backup.py) is for restoring into Minerva;
this export is for reading anywhere else: the library's own files as
they are, plus "Minerva records" (notes as Markdown; entries, tags,
collections, projects, outlines, submissions, venues and people as CSV;
goals and settings as JSON with no keys) and a README saying what each
file is. Scans and other pictures and recordings are included when asked.
"""

import csv
import datetime
import io
import json
import os
import re
import shutil
import zipfile

from . import __version__, config as app_config, core, sharing

MEDIA = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".heic", ".bmp",
         ".mp3", ".wav", ".m4a", ".mp4", ".mov"}
SECRET_RE = re.compile(r"key|token|secret|password|credential", re.IGNORECASE)
RECORDS = "Minerva records"


class ExportError(Exception):
    user_facing = True


LAST = {"path": None}  # the export just made, the only one "Show it" may open


def prefs():
    e = dict(app_config.load().get("export_all") or {})
    return {"folder": e.get("folder") or "", "zip": e.get("zip", True) is not False, "media": bool(e.get("media"))}


def save_prefs(folder, as_zip, media):
    cfg = app_config.load()
    cfg["export_all"] = {"folder": folder, "zip": bool(as_zip), "media": bool(media)}
    app_config.save(cfg)


def _inside(path, parent):
    p, q = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(parent))
    return p == q or p.startswith(q + os.sep)


def library_files(media):
    """(absolute path, path in the export) for the library's own files:
    everything but Minerva's .minerva folder and Exports (things Minerva
    made from the writing), with scans, pictures and recordings only when
    media is on."""
    root = core.ARCHIVE_ROOT
    skip = {os.path.normcase(os.path.realpath(p)) for p in (core.META_DIR, os.path.join(root, "Exports")) if p}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if os.path.normcase(os.path.realpath(os.path.join(dirpath, d))) not in skip and d != ".minerva")
        for name in sorted(filenames):
            if not media and os.path.splitext(name)[1].lower() in MEDIA:
                continue
            if name.startswith("~$") or name.lower() in ("desktop.ini", "thumbs.db", ".ds_store"):
                continue
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root)


def _csv(rows, headings):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(headings)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return "﻿" + buf.getvalue()  # the byte-order mark makes Excel read it as UTF-8


def _table(conn, name):
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _safe(name):
    return core.INVALID_FILENAME_CHARS_RE.sub("", name or "").strip(" .")[:90] or "Untitled"


def _clean_config(value):
    """Settings with anything secret-sounding left out (keys themselves are
    in Windows Credential Manager, never in settings)."""
    if isinstance(value, dict):
        return {k: _clean_config(v) for k, v in value.items() if not SECRET_RE.search(str(k))}
    if isinstance(value, list):
        return [_clean_config(v) for v in value]
    return value


def records(conn):
    """{path in the export: text} for everything Minerva keeps about the
    writing."""
    out = {}
    entries = conn.execute("SELECT * FROM entries ORDER BY top_folder, title").fetchall()
    by_id = {e["id"]: e for e in entries}
    path_of = lambda eid: by_id[eid]["rel_path"] if eid in by_id else ""  # noqa: E731
    title_of = lambda eid: by_id[eid]["title"] if eid in by_id else ""  # noqa: E731
    out["entries.csv"] = _csv(
        [(e["title"], e["top_folder"], e["rel_path"], e["draft_filename"], e["word_count"], e["project_tag"],
          "yes" if e["to_edit"] else "", "yes" if e["to_record"] else "", "yes" if e["published"] else "",
          e["published_where"], "yes" if sharing.has_final(e) else "") for e in entries],
        ["Title", "Category", "Folder", "Current draft", "Words", "Project tag", "To edit", "To record",
         "Published", "Published where", "Has a final draft"])

    if _table(conn, "entry_notes"):
        for n in conn.execute("SELECT * FROM entry_notes ORDER BY title"):
            if not (n["body"] or "").strip():
                continue
            folder = by_id[n["entry_id"]]["top_folder"] if n["entry_id"] in by_id else "Notes without an entry"
            path = f"Notes/{_safe(folder)}/{_safe(n['title'])}.md"
            k = 2
            while path in out:
                path = f"Notes/{_safe(folder)}/{_safe(n['title'])} ({k}).md"
                k += 1
            where = path_of(n["entry_id"]) or n["rel_path"]
            out[path] = f"# Notes: {n['title']}\n\n_Entry: {where}. Last changed {n['updated_at'] or 'unknown'}._\n\n{n['body'].strip()}\n"

    if _table(conn, "entry_tags"):
        out["tags.csv"] = _csv([(title_of(r["entry_id"]), path_of(r["entry_id"]), r["tag"])
                                for r in conn.execute("SELECT * FROM entry_tags ORDER BY tag, entry_id")],
                               ["Title", "Folder", "Tag"])
    if _table(conn, "collections"):
        out["collections.csv"] = _csv([(r["name"], r["filters"], r["created_at"])
                                       for r in conn.execute("SELECT * FROM collections ORDER BY name")],
                                      ["Collection", "What it shows (filters)", "Made"])

    projects = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    order = {}
    if _table(conn, "project_order"):
        for r in conn.execute("SELECT * FROM project_order ORDER BY project_id, pos"):
            order.setdefault(r["project_id"], []).append(r["entry_id"])
    out["projects.csv"] = _csv(
        [(p["name"], p["tag"], p["folder_path"], " | ".join(title_of(e) for e in order.get(p["id"], [])))
         for p in projects], ["Project", "Tag", "Folder", "Entries in order"])
    pub = {}
    for p in projects:
        try:
            pub[p["name"]] = sharing.project_settings(conn, p["id"])
        except Exception:  # a project with unreadable settings still exports the rest
            continue
    out["project publishing details.json"] = json.dumps(pub, indent=2, ensure_ascii=False)
    if _table(conn, "outline_items"):
        names = {p["id"]: p["name"] for p in projects}
        out["outlines.csv"] = _csv(
            [(names.get(r["project_id"], ""), r["pos"] + 1, r["title"] or title_of(r["entry_id"]), path_of(r["entry_id"]),
              "placeholder" if r["entry_id"] is None else "", r["synopsis"], r["status"], r["notes"])
             for r in conn.execute("SELECT * FROM outline_items ORDER BY project_id, pos")],
            ["Project", "Position", "Title", "Folder", "Placeholder", "Synopsis", "Status", "Notes"])

    if _table(conn, "submissions"):
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(submissions)")]
        want = [c for c in ("piece_title", "venue", "status", "submitted_on", "decided_on", "deadline", "response_days",
                            "cost", "currency", "notes", "created_at") if c in cols]
        out["submissions.csv"] = _csv([[r[c] for c in want] for r in conn.execute("SELECT * FROM submissions ORDER BY submitted_on, id")],
                                      [c.replace("_", " ").capitalize() for c in want])
    if _table(conn, "venues"):
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(venues)")]
        out["venues.csv"] = _csv([[r[c] for c in cols] for r in conn.execute("SELECT * FROM venues ORDER BY name")],
                                 [c.replace("_", " ").capitalize() for c in cols])
    if _table(conn, "people"):
        aliases = {}
        if _table(conn, "person_aliases"):
            for r in conn.execute("SELECT * FROM person_aliases ORDER BY alias"):
                aliases.setdefault(r["person_id"], []).append(r["alias"])
        out["people.csv"] = _csv([(r["name"], " | ".join(aliases.get(r["id"], [])), r["about"])
                                  for r in conn.execute("SELECT * FROM people ORDER BY name")],
                                 ["Name", "Also called", "About"])

    lib = core.read_library_settings(core.ARCHIVE_ROOT)
    out["goals.json"] = json.dumps(lib.get("goals") or {}, indent=2)
    cfg = _clean_config(app_config.load())
    snippets = cfg.pop("snippets", None) or []
    out["settings.json"] = json.dumps({"app": cfg, "library": _clean_config({k: v for k, v in lib.items() if k != "goals"})},
                                      indent=2, ensure_ascii=False, default=str)
    if snippets:
        out["snippets.md"] = "# Snippets\n\n" + "\n\n".join(
            f"## {s.get('name', '')}\n\n_{s.get('kind', '')}_\n\n{s.get('body', '')}" for s in snippets) + "\n"
    return out


README = """What's in this export
=====================

Made by Minerva {version} on {date}, from the library "{library}".
Everything here is in open formats that open without Minerva.

{writing}/
  Your library's own files, in the same folders, exactly as they are on
  disk: each entry's current draft, its Archive of earlier drafts, Final
  copies, and anything else you keep there.{media}
  Not included: Minerva's hidden .minerva folder (its index, which this
  export spells out below) and Exports (files Minerva made from your
  writing, which you can make again).

{records}/
  What Minerva knows about your writing.
  entries.csv        every entry: title, category, folder, current draft,
                     words, project, flags and where it was published
  Notes/             the Notes beside each entry, as Markdown (.md)
  tags.csv           each tag on each entry
  collections.csv    saved views, with the filters each one uses
  projects.csv       projects, their tags, folders and running order
  project publishing details.json
                     each project's subtitle, author, copyright line,
                     dedication, acknowledgments and other publishing details
  outlines.csv       project outlines: synopses, statuses, notes and
                     placeholders for pieces still to write
  submissions.csv    where each piece went, when, and what happened
  venues.csv         your notes on magazines and presses
  people.csv         the people in your journals, as you recorded them
  snippets.md        cover letters, bios and other snippets
  goals.json         your word goals
  settings.json      Minerva's settings, with no keys or passwords

CSV files open in Excel, Google Sheets, Numbers or LibreOffice. Markdown
and JSON files are plain text: Notepad or any text editor reads them.

This isn't a backup for Minerva itself. To restore into Minerva, use a
backup (Settings > Backups).
"""


def export(job, dest_folder, as_zip=True, media=False, now=None):
    """Write the export into dest_folder as a .zip or a folder; returns
    where it went."""
    if not core.ARCHIVE_ROOT:
        raise ExportError("Open a library first.")
    dest_folder = (dest_folder or "").strip()
    if not dest_folder or not os.path.isabs(os.path.expanduser(dest_folder)) or not os.path.isdir(os.path.expanduser(dest_folder)):
        raise ExportError("Choose a folder that exists for the export.")
    dest_folder = os.path.abspath(os.path.expanduser(dest_folder))
    if _inside(dest_folder, core.ARCHIVE_ROOT):
        raise ExportError("Choose a folder outside your library, so the export doesn't end up inside itself.")
    now = now or datetime.datetime.now()
    library = os.path.basename(core.ARCHIVE_ROOT.rstrip("\\/")) or "Library"
    base = f"{_safe(library)} export {now.strftime('%Y-%m-%d %H%M')}"
    target = os.path.join(dest_folder, base + (".zip" if as_zip else ""))
    n = 2
    while os.path.exists(target) or os.path.exists(target + ".partial"):
        target = os.path.join(dest_folder, f"{base} ({n})" + (".zip" if as_zip else ""))
        n += 1

    job.progress(0, 0, "Gathering Minerva's records")
    conn = core.get_conn()
    try:
        recs = records(conn)
    finally:
        conn.close()
    files = list(library_files(media))
    writing = "Writing"
    readme = README.format(version=__version__, date=now.strftime("%B %d, %Y").replace(" 0", " "), library=library,
                           writing=writing, records=RECORDS,
                           media="\n  Scans, pictures and recordings are included." if media
                           else "\n  Scans, pictures and recordings were left out (tick the box to include them).")
    partial = target + ".partial"
    total = len(files)
    try:
        if as_zip:
            with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                z.writestr(f"{base}/README.txt", readme.replace("\n", "\r\n"))
                for path, text in recs.items():
                    z.writestr(f"{base}/{RECORDS}/{path}", text)
                for i, (full, rel) in enumerate(files):
                    if job.cancelled():
                        raise ExportError("Stopped.")
                    if i % 20 == 0:
                        job.progress(i, total, f"Copying {rel}")
                    try:
                        z.write(full, f"{base}/{writing}/{rel}".replace(os.sep, "/"))
                    except OSError:
                        continue  # a file that vanished or is locked
        else:
            os.makedirs(partial)
            with open(os.path.join(partial, "README.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
                fh.write(readme)
            for path, text in recs.items():
                out = os.path.join(partial, RECORDS, *path.split("/"))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            for i, (full, rel) in enumerate(files):
                if job.cancelled():
                    raise ExportError("Stopped.")
                if i % 20 == 0:
                    job.progress(i, total, f"Copying {rel}")
                out = os.path.join(partial, writing, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                try:
                    shutil.copy2(full, out)
                except OSError:
                    continue
        os.replace(partial, target)
    except BaseException:
        if os.path.isdir(partial):
            shutil.rmtree(partial, ignore_errors=True)
        elif os.path.exists(partial):
            os.remove(partial)
        raise
    job.progress(total, total, "Done")
    LAST["path"] = target
    save_prefs(dest_folder, as_zip, media)
    return {"path": target, "name": os.path.basename(target), "files": total, "records": len(recs), "zip": as_zip}

"""Exports from notes apps, opened up into one draft per note.

- Evernote: an .enex file (one notebook, many notes).
- Google Keep: the Google Takeout zip (Takeout/Keep/*.json), or a single
  note's .json from it.
- Notion: the "Markdown & CSV" export zip; the long ID Notion adds to each
  file name is dropped.
- Anything else zipped up (Bear, Apple Notes through an exporter app, a
  folder of notes) is read file by file like Import files.

Labels and tags become tags; a notebook (Evernote) or parent page (Notion)
becomes a tag too, and is offered as the category when it has a
category's name. The note's own date is kept as the draft's date. Files
are only read; creating entries is intake.create_entries as for every
other import.
"""

import datetime
import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET

from . import fileimport, intake

MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_NOTES = 2000
NOTION_ID_RE = re.compile(r"\s+[0-9a-f]{32}$", re.I)
ARCHIVE_EXTS = (".enex", ".zip", ".json")


class NotesExportError(fileimport.ImportFileError):
    pass


def _item(name, title, text, tags=(), modified=None, notes=None, notebook=None):
    text = fileimport._normalize(text or "")
    title = intake.clean_title(title or "") or intake.clean_title(intake.suggest_title(text) if text.strip() else "") or "Untitled"
    seen, clean_tags = set(), []
    for t in list(tags) + ([notebook] if notebook else []):
        t = " ".join(str(t or "").split()).lstrip("#")
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            clean_tags.append(t)
    fields = {"tags": clean_tags}
    if modified:
        fields["modified"] = modified
    if notebook:
        fields["notebook"] = notebook
    return {"name": name, "title": title, "text": text + "\n" if text else "", "words": len(text.split()),
            "notes": list(notes or []), "fields": fields}


# ---- Evernote ------------------------------------------------------------------

def _enex_time(s):
    try:
        return datetime.datetime.strptime((s or "").strip(), "%Y%m%dT%H%M%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def _enex(name, data):
    notebook = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]
    try:
        # .enex is plain XML; the parser doesn't fetch external entities
        root = ET.fromstring(data)
    except ET.ParseError:
        raise NotesExportError("This Evernote file couldn't be read. Export the notebook again as .enex.") from None
    out = []
    for i, note in enumerate(root.iter("note")):
        title = (note.findtext("title") or "").strip()
        content = note.findtext("content") or ""
        # Evernote writes an empty line as <div><br/></div>
        content = re.sub(r"<div>\s*<br\s*/?>\s*</div>", "<div></div>", content, flags=re.I)
        text, _t, notes = fileimport._html(content.encode("utf-8"))
        if note.find("resource") is not None:
            notes = ["attachments left out"]
        when = _enex_time(note.findtext("updated")) or _enex_time(note.findtext("created"))
        tags = [t.text for t in note.findall("tag") if t.text]
        out.append(_item(f"{name} #{i + 1}", title, text, tags, when, notes, notebook))
        if len(out) >= MAX_NOTES:
            break
    if not out:
        raise NotesExportError("No notes found in this Evernote file.")
    return out


# ---- Google Keep ------------------------------------------------------------------

def _keep_note(name, data):
    try:
        n = json.loads(fileimport._decode(data))
    except ValueError:
        return None
    if not isinstance(n, dict) or not ("textContent" in n or "listContent" in n) or "userEditedTimestampUsec" not in n and "createdTimestampUsec" not in n:
        return None
    if n.get("isTrashed"):
        return []
    text = n.get("textContent") or ""
    if n.get("listContent"):
        lines = [("[x] " if li.get("isChecked") else "[ ] ") + (li.get("text") or "") for li in n["listContent"]]
        text = (text + "\n" if text else "") + "\n".join(lines)
    usec = n.get("userEditedTimestampUsec") or n.get("createdTimestampUsec")
    when = usec / 1e6 if isinstance(usec, (int, float)) and usec > 0 else None
    tags = [lab.get("name") for lab in n.get("labels") or [] if lab.get("name")]
    if n.get("isArchived"):
        tags.append("Keep archive")
    notes = ["attachments left out"] if n.get("attachments") else []
    stem = os.path.splitext(os.path.basename(name))[0]
    return [_item(name, n.get("title") or stem, text, tags, when, notes)]


# ---- zips: Takeout, Notion, anything else -------------------------------------------

def _zip(name, data, depth=0):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise NotesExportError("This zip file couldn't be opened.") from None
    out = []
    names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n
             and not os.path.basename(n).startswith(".")]
    keep_json = {n for n in names if "/Keep/" in "/" + n and n.lower().endswith(".json")}
    keep_stems = {os.path.splitext(n)[0] for n in keep_json}
    if keep_json:
        # a Takeout zip: only the Keep notes, not Takeout's own index pages
        names = [n for n in names if "/Keep/" in "/" + n]
    for inner in sorted(names):
        low = inner.lower()
        info = z.getinfo(inner)
        if info.file_size > fileimport.MAX_FILE_BYTES and not low.endswith(".zip"):
            continue
        if low.endswith(".zip") and depth == 0:
            out.extend(_zip(f"{name}/{inner}", z.read(inner), depth + 1))
            continue
        if inner in keep_json:
            got = _keep_note(f"{name}/{inner}", z.read(inner))
            if got:
                out.extend(got)
            continue
        if os.path.splitext(inner)[0] in keep_stems:
            continue  # Keep's .html copy of a note already read from its .json
        if low.endswith(".enex"):
            out.extend(_enex(f"{name}/{inner}", z.read(inner)))
            continue
        ext = os.path.splitext(low)[1]
        if ext not in fileimport.EXTENSIONS:
            continue
        parts = inner.split("/")
        try:
            item = fileimport.convert(parts[-1], z.read(inner))
        except fileimport.ImportFileError:
            continue
        # Notion: "Title 0123abcd....md", inside folders named after parent pages
        title = NOTION_ID_RE.sub("", item["title"]) or item["title"]
        parent = NOTION_ID_RE.sub("", parts[-2]) if len(parts) > 1 else None
        if parent and parent.lower().startswith("export-"):
            parent = None
        when = datetime.datetime(*info.date_time).timestamp() if info.date_time[0] > 1980 else None
        tags = item["fields"].get("tags") or []
        if isinstance(tags, str):
            tags = [t for t in re.split(r"[,\s]+", tags) if t]
        out.append(_item(f"{name}/{inner}", title, item["text"], tags, when, item["notes"], parent))
        if len(out) >= MAX_NOTES:
            break
    if not out and depth == 0:
        raise NotesExportError("Nothing Minerva can read was found in this zip.")
    return out


def expand(name, data):
    """A list of preview items for an export file, or None when the file
    isn't one (so it's handled as an ordinary file)."""
    low = name.lower()
    if not low.endswith(ARCHIVE_EXTS):
        return None
    if len(data) > MAX_ARCHIVE_BYTES:
        raise NotesExportError("This export is too large to read in one go. Split it, or export one notebook at a time.")
    if low.endswith(".enex"):
        return _enex(name, data)
    if low.endswith(".zip"):
        return _zip(name, data)
    got = _keep_note(name, data)
    if got is None:
        raise NotesExportError("This .json file isn't a Google Keep note.")
    if not got:
        raise NotesExportError("This Keep note is in the trash, so it's left out.")
    return got

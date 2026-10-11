"""Images: the drawings and diagrams found in transcribed scans.

Transcription describes a drawing, diagram or decoration in [square brackets]
on its own line. A Master entry with such a line is listed here with a
suggested kind and file name, and "Save images" copies its pages into
"<Source>/Images/<Kind>/". Nothing here calls a model, and nothing in the
source folder is overwritten: a name that is taken gets a number added.
"""

import datetime
import os
import re

from . import core, scanning

KINDS = ("Diagram", "Drawing", "Uncategorized")

_DIAGRAM_WORDS = ("diagram", "chart", "graph", "map", "table", "grid", "schematic", "geometric",
                  "geometry", "cube", "circle", "triangle", "symbol", "sigil", "flowchart", "arrow",
                  "floor plan", "layout", "blueprint", "equation", "formula", "mandala", "timeline")
_DRAWING_WORDS = ("drawing", "drawn", "sketch", "doodle", "illustration", "picture", "portrait",
                  "painting", "cartoon", "face", "flower", "tree", "landscape", "figure")
_KIND_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _DIAGRAM_WORDS + _DRAWING_WORDS) + r")s?\b",
                      re.IGNORECASE)
_BRACKET_LINE_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
_LEAD_RE = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:(?:small|large|simple|rough|hand-drawn|detailed|ink|pencil|geometric|labell?ed)\s+)*"
    r"(?:drawing|sketch|doodle|diagram|illustration|chart|map|picture|image)s?"
    r"(?:\s+(?:of|showing|depicting|labell?ed|with))?\s*[:\-–—]?\s*(?:(?:a|an|the)\s+)?",
    re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%m-%d-%y", "%m-%d-%Y", "%m.%d.%y", "%m.%d.%Y",
                 "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y")


def descriptions(body):
    """The bracketed description lines of an entry, and whether it has any
    written lines besides them."""
    found, other = [], False
    for line in (body or "").splitlines():
        if not line.strip():
            continue
        m = _BRACKET_LINE_RE.match(line)
        inner = m.group(1).strip() if m else ""
        if m and inner.lower().rstrip(".") != "blank page" and (len(inner.split()) >= 3 or _KIND_RE.search(inner)):
            found.append(inner)
        else:
            other = True
    return found, other


def guess_kind(text):
    m = _KIND_RE.search(text or "")
    if not m:
        return "Uncategorized"
    return "Diagram" if m.group(1).lower() in _DIAGRAM_WORDS else "Drawing"


def iso_date(raw):
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", (raw or "").strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _short(desc, words=6):
    text = _LEAD_RE.sub("", desc.strip()).strip(" .,;:")
    parts = text.split()[:words]
    return " ".join(p[:1].upper() + p[1:] for p in parts).rstrip(" .,;:")


def safe_name(name):
    name = core.INVALID_FILENAME_CHARS_RE.sub("", re.sub(r"\s+", " ", name or "")).strip(" .")
    return name[:100].rstrip(" .")


def suggested_name(entry, desc, kind):
    raw = _clean(entry.get("date"))
    date = iso_date(raw) or safe_name(raw) or "Undated"
    what = _clean(entry.get("title")) or _short(desc) or kind
    name = f"{date} {what}"
    loc = _clean(entry.get("location"))
    if loc and len(loc) <= 30:
        name += f" ({loc})"
    return safe_name(name)


def _clean(s):
    s = (s or "").strip()
    return "" if s.lower() in ("none", "unknown", "n/a") else s


def _ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS saved_images (
        source TEXT NOT NULL, entry_num INTEGER NOT NULL, path TEXT NOT NULL, saved_at TEXT,
        PRIMARY KEY (source, entry_num, path))""")


def _saved(name):
    conn = core.get_conn()
    try:
        _ensure_table(conn)
        out = {}
        for r in conn.execute("SELECT entry_num, path FROM saved_images WHERE source = ?", (name,)):
            out.setdefault(r["entry_num"], []).append(r["path"])
        return out
    finally:
        conn.close()


def for_source(name):
    master = scanning.read_master(name)
    saved = _saved(name)
    counts = {int(k): v for k, v in master["scan_pages"].items()}
    out = []
    for e in master["entries"]:
        found, has_text = descriptions(e["body"])
        if not found:
            continue
        desc = found[0]
        kind = guess_kind(" ".join(found))
        out.append({"source": name, "num": e["num"], "title": e["title"], "date": e["date"],
                    "location": e["location"], "description": desc, "more": found[1:],
                    "has_text": has_text, "kind": kind, "name": suggested_name(e, desc, kind),
                    # only pages that exist; a label can name a scan that isn't there
                    "pages": [[n, p] for n, p in e["pages"] if 1 <= p <= counts.get(n, 0)],
                    "saved": [p.replace(os.sep, "/") for p in saved.get(e["num"], [])]})
    return out


def list_all():
    """Every image across the sources that have a Master."""
    sources = [s["name"] for s in scanning.list_sources()["sources"] if s["has_master"]]
    return {"kinds": list(KINDS), "images": [img for s in sources for img in for_source(s)]}


def _free_path(folder, stem):
    path = os.path.join(folder, stem + ".jpg")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({n}).jpg")
        n += 1
    return path


def save(name, items):
    """Copy each chosen entry's pages into <Source>/Images/<Kind>/. Returns
    the files written, relative to the source folder."""
    src = scanning.source_dir(name)
    found = {img["num"]: img for img in for_source(name)}
    plan = []
    for item in items or []:
        img = found.get(int(item.get("num", 0)))
        if img is None:
            raise scanning.ScanError(f"Entry {item.get('num')} isn't an image in {name}.")
        if not img["pages"]:
            raise scanning.ScanError(f"Entry {img['num']} isn't matched to a page yet.")
        kind = item.get("kind") or img["kind"]
        if kind not in KINDS:
            raise scanning.ScanError(f'"{kind}" isn\'t one of {", ".join(KINDS)}.')
        stem = safe_name(item.get("name") or img["name"])
        if not stem:
            raise scanning.ScanError(f"Entry {img['num']} needs a file name.")
        plan.append((img, kind, stem))
    written = []
    conn = core.get_conn()
    try:
        _ensure_table(conn)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for img, kind, stem in plan:
            folder = os.path.join(src, "Images", kind)
            os.makedirs(folder, exist_ok=True)
            many = len(img["pages"]) > 1
            for i, (num, page) in enumerate(img["pages"], 1):
                path = _free_path(folder, f"{stem} - {i}" if many else stem)
                data = scanning.cached_page_image(name, num, page)
                with open(path, "xb") as fh:
                    fh.write(data)
                rel = os.path.relpath(path, src)
                conn.execute("INSERT OR REPLACE INTO saved_images VALUES (?, ?, ?, ?)",
                             (name, img["num"], rel, now))
                written.append(rel.replace(os.sep, "/"))
        conn.commit()
    finally:
        conn.close()
    return written

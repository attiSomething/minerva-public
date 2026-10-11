"""AI-assisted scanning: from scanned pages to filed entries.

The steps follow the process Minerva's first version was built around:

1. Transcribe. Each scan (a PDF of several pages, or a single image) is read
   page by page by the user's chosen model. Results are cached per page in
   .minerva/scans/ and written out as "<Source> N - Text.txt" in the source's
   "Text Output" folder.
2. Master. Transcribed scans are combined into "<Source> - Master.txt": one
   numbered ENTRY per piece of writing (a page that continues the previous
   one is joined to it), with every note about uncertain words collected in
   an OCR AMBIGUITY NOTES section at the end.
3. Proofread. Each Master entry is checked side by side with its page.
4. File. Reviewed entries become ordinary library entries: a folder in a
   category holding "<Title> [J].txt", whose header names the source and
   entry number so the entry's Journal Scan panel can find the page again.

A "source" is a folder inside the library's scans folder (Sources, or the
first version's Journal Scans). Its scans live in a "Scans" subfolder when
there is one, otherwise directly inside it. Minerva never overwrites or
deletes a file here; edits to a Master are preceded by a backup copy in
.minerva/backups/.
"""

import datetime
import hashlib
import io
import json
import os
import re
import shutil

from . import ai, core, pagelinks

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic"}
SCAN_EXTS = PDF_EXTS | IMAGE_EXTS
MAX_EDGE = 2000
SEP = "=" * 60

ENTRY_RE = re.compile(r"^ENTRY\s+(\d+)\s*\(([^)]*)\)[ \t]*(?:[\u2014\u2013-][ \t]*)?(.*?)[ \t]*$", re.MULTILINE)
NOTES_HEADER_RE = re.compile(r"^OCR AMBIGUITY(?: & CONTEXT)? NOTES\s*$", re.MULTILINE)
SEP_LINE_RE = re.compile(r"^=+[ \t]*$", re.MULTILINE)
SECTION_BOX_RE = re.compile(r"^=+[ \t]*\n(?!ENTRY\b)[A-Z][A-Z0-9 &/(),.'\u2019-]{3,}\n=+[ \t]*$", re.MULTILINE)
META_LINE_RE = re.compile(r"^\s*(Date|Time|Location|Place)\s*:\s*(.*)$", re.IGNORECASE)
NOTE_START_RE = re.compile(r"^Entr(?:y|ies)\s+([\d,\s–—&and-]+?)\s*:", re.IGNORECASE)
SCAN_LABEL_RE = re.compile(r"Scan\s+(\d+)", re.IGNORECASE)
SEGMENT_LABEL_RE = re.compile(r"(?:Segment|Page)s?\s+(\d+)", re.IGNORECASE)


class ScanError(Exception):
    user_facing = True


# --------------------------------------------------------------------------
# Sources and scan files
# --------------------------------------------------------------------------

def scans_root():
    if not core.is_configured():
        raise ScanError("No library is open.")
    return core.JOURNAL_SCANS_DIR


def source_dir(name):
    root = scans_root()
    path = os.path.normpath(os.path.join(root, name))
    if os.path.dirname(path) != os.path.normpath(root) or not os.path.isdir(path):
        raise ScanError(f'No source folder called "{name}".')
    return path


def _scan_folder(src_path):
    sub = os.path.join(src_path, "Scans")
    return sub if os.path.isdir(sub) else src_path


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_scans(name):
    """Scan files of a source, numbered the way Master labels refer to them:
    "<Source> 3.pdf" is scan 3; other files are numbered in name order after
    the highest such number."""
    folder = _scan_folder(source_dir(name))
    files = sorted((f for f in os.listdir(folder)
                    if os.path.splitext(f)[1].lower() in SCAN_EXTS
                    and os.path.isfile(os.path.join(folder, f))), key=_natural_key)
    numbered, rest = {}, []
    pat = re.compile(rf"^{re.escape(name)}\s+(\d+)\.\w+$", re.IGNORECASE)
    for f in files:
        m = pat.match(f)
        if m and int(m.group(1)) not in numbered:
            numbered[int(m.group(1))] = f
        else:
            rest.append(f)
    nxt = max(numbered, default=0) + 1
    for f in rest:
        numbered[nxt] = f
        nxt += 1
    return [{"num": n, "filename": f, "path": os.path.join(folder, f),
             "is_pdf": os.path.splitext(f)[1].lower() in PDF_EXTS}
            for n, f in sorted(numbered.items())]


def get_scan(name, num):
    for s in list_scans(name):
        if s["num"] == int(num):
            return s
    raise ScanError(f"{name} has no scan {num}.")


def page_count(scan):
    if not scan["is_pdf"]:
        return 1
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(scan["path"])
    except Exception:
        raise ScanError(f'Couldn\'t open "{scan["filename"]}" as a PDF.')
    try:
        return len(pdf)
    finally:
        pdf.close()


def render_page(scan, page):
    """Return one page of a scan as JPEG bytes, longest edge at most MAX_EDGE."""
    from PIL import Image, ImageOps

    if scan["is_pdf"]:
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(scan["path"])
        except Exception:
            raise ScanError(f'Couldn\'t open "{scan["filename"]}" as a PDF.')
        try:
            if not 1 <= page <= len(pdf):
                raise ScanError(f'"{scan["filename"]}" has no page {page}.')
            pg = pdf[page - 1]
            w, h = pg.get_size()
            scale = min(MAX_EDGE / max(w, h, 1), 4.0)
            img = pg.render(scale=scale).to_pil()
        finally:
            pdf.close()
    else:
        if page != 1:
            raise ScanError(f'"{scan["filename"]}" is a single image.')
        try:
            img = ImageOps.exif_transpose(Image.open(scan["path"]))
        except Exception:
            raise ScanError(f'Couldn\'t open "{scan["filename"]}" as an image.')
        img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def cached_page_image(name, num, page):
    """Rendered pages are cached in .minerva/cache so the proofreader is quick."""
    scan = get_scan(name, num)
    cache = os.path.join(core.META_DIR, "cache", "pages", _slug(name))
    os.makedirs(cache, exist_ok=True)
    mtime = int(os.path.getmtime(scan["path"]))
    path = os.path.join(cache, f"{num}-{page}-{mtime}.jpg")
    if not os.path.isfile(path):
        data = render_page(scan, page)
        with open(path, "wb") as fh:
            fh.write(data)
        return data
    with open(path, "rb") as fh:
        return fh.read()


def _slug(name):
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12] + "-" + re.sub(r"[^A-Za-z0-9]+", "_", name)[:40]


def master_path(name):
    return os.path.join(source_dir(name), f"{name} - Master.txt")


def list_sources():
    root = scans_root()
    if not os.path.isdir(root):
        return {"root": root, "exists": False, "sources": [], "loose_files": 0}
    sources, loose = [], 0
    for entry in sorted(os.listdir(root), key=_natural_key):
        path = os.path.join(root, entry)
        if os.path.isfile(path):
            if os.path.splitext(entry)[1].lower() in SCAN_EXTS:
                loose += 1
            continue
        if entry.startswith(".") or not os.path.isdir(path):
            continue
        scans = list_scans(entry)
        mpath = master_path(entry)
        has_master = os.path.isfile(mpath)
        if not scans and not has_master:
            continue
        transcribed = sum(1 for s in scans if _cache_complete(entry, s["num"]))
        info = {"name": entry, "scans": len(scans), "transcribed": transcribed,
                "has_master": has_master, "entries": 0, "reviewed": 0, "filed": 0}
        if has_master:
            nums = [e["num"] for e in parse_master(_read(mpath))["entries"]]
            info["entries"] = len(nums)
            info["reviewed"] = len(reviewed_set(entry) & set(nums))
            info["filed"] = len(filed_map(entry).keys() & set(nums))
        sources.append(info)
    return {"root": root, "exists": True, "sources": sources, "loose_files": loose}


def create_source(name):
    name = (name or "").strip()
    if not name or core.INVALID_FILENAME_CHARS_RE.search(name) or name.startswith("."):
        raise ScanError('Choose a name without \\ / : * ? " < > |')
    path = os.path.join(scans_root(), name)
    if os.path.exists(path):
        raise ScanError(f'"{name}" already exists.')
    os.makedirs(os.path.join(path, "Scans"))
    return path


# --------------------------------------------------------------------------
# Transcription
# --------------------------------------------------------------------------

TRANSCRIBE_SYSTEM = """You transcribe scanned pages of a writer's work for their personal archive. Pages may be handwritten or printed: journals, notebooks, letters, typed drafts or old documents.

Rules:
- Transcribe only the main page in the image. Ignore any part of a neighbouring page visible at the edges.
- Keep the writer's own words, line breaks, spelling and punctuation. Do not correct, modernise or summarise.
- When you can't read a word with confidence, write your best guess in [square brackets] and list it under UNCERTAIN.
- Describe drawings, diagrams, stickers or decorations briefly in [square brackets] on their own line.
- If the page is blank, say [Blank page] as the text.

Answer in exactly this format, with nothing before or after it:
DATE: <date written on the page, as written, or none>
LOCATION: <place written on the page (often top right), or none>
TITLE: <the piece's title if the page shows one, or none>
CONTINUES: <yes if this page carries on the piece from the previous page instead of starting something new, otherwise no>
TEXT:
<the transcription>
UNCERTAIN:
<the words or passages you were unsure of, with your best guess, or none>"""

_FIELD_RE = re.compile(r"^(DATE|LOCATION|TITLE|CONTINUES)\s*:\s*(.*)$", re.IGNORECASE)


def _none(v):
    v = (v or "").strip()
    return "" if v.lower() in ("none", "n/a", "unknown", "-", "") else v


def parse_transcription(reply):
    """Read the tagged reply format back into a dict. Tolerates extra
    whitespace, a code fence around the reply, and fields in any order."""
    text = (reply or "").strip()
    text = re.sub(r"^```\w*\n|\n```$", "", text)
    lines = text.splitlines()
    out = {"date": "", "location": "", "title": "", "continues": False, "text": "", "uncertain": ""}
    body, unsure, mode = [], [], None
    for line in lines:
        stripped = line.strip()
        if mode is None or mode == "fields":
            m = _FIELD_RE.match(stripped)
            if m:
                key, val = m.group(1).lower(), m.group(2)
                if key == "continues":
                    out["continues"] = val.strip().lower().startswith("y")
                else:
                    out[key] = _none(val)
                mode = "fields"
                continue
        if re.match(r"^TEXT\s*:", stripped, re.IGNORECASE) and mode != "text":
            mode = "text"
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                body.append(rest)
            continue
        if re.match(r"^UNCERTAIN\s*:", stripped, re.IGNORECASE):
            mode = "uncertain"
            rest = stripped.split(":", 1)[1].strip()
            if rest:
                unsure.append(rest)
            continue
        if mode == "text":
            body.append(line.rstrip())
        elif mode == "uncertain":
            unsure.append(line.rstrip())
    if mode is None:
        # The model ignored the format; keep everything as the text.
        body = [ln.rstrip() for ln in lines]
    out["text"] = "\n".join(body).strip("\n")
    out["uncertain"] = _none("\n".join(unsure).strip())
    return out


def _cache_dir(name, num):
    return os.path.join(core.META_DIR, "scans", _slug(name), f"scan-{int(num)}")


def _page_cache_path(name, num, page):
    return os.path.join(_cache_dir(name, num), f"page-{int(page)}.json")


def cached_pages(name, num):
    d = _cache_dir(name, num)
    pages = {}
    if os.path.isdir(d):
        for f in os.listdir(d):
            m = re.match(r"page-(\d+)\.json$", f)
            if m:
                with open(os.path.join(d, f), "r", encoding="utf-8") as fh:
                    pages[int(m.group(1))] = json.load(fh)
    return pages


def _scan_meta_path(name, num):
    return os.path.join(_cache_dir(name, num), "scan.json")


def _cache_complete(name, num):
    try:
        with open(_scan_meta_path(name, num), "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return False
    return len(cached_pages(name, num)) >= meta.get("pages", 1 << 30)


def scan_status(name):
    """Every scan of a source, with its page count and how far along it is."""
    out = []
    master = _read(master_path(name)) if os.path.isfile(master_path(name)) else ""
    in_master = {int(n) for label in re.findall(r"^ENTRY\s+\d+\s*\(([^)]*)\)", master, re.MULTILINE)
                 for n in SCAN_LABEL_RE.findall(label)}
    for s in list_scans(name):
        try:
            pages = page_count(s)
            err = None
        except ScanError as e:
            pages, err = 0, str(e)
        done = len(cached_pages(name, s["num"]))
        text_out = _existing_text_output(name, s["num"])
        out.append({"num": s["num"], "filename": s["filename"], "pages": pages,
                    "transcribed_pages": min(done, pages) if pages else done,
                    "text_output": text_out, "in_master": s["num"] in in_master,
                    "error": err})
    return out


def text_output_dir(name):
    """The source's "Text Output" folder (some older sources say "Text Outputs")."""
    src = source_dir(name)
    for sub in ("Text Output", "Text Outputs"):
        if os.path.isdir(os.path.join(src, sub)):
            return os.path.join(src, sub)
    return os.path.join(src, "Text Output")


def _existing_text_output(name, num):
    folder = text_output_dir(name)
    if not os.path.isdir(folder):
        return None
    pat = re.compile(rf"^{re.escape(name)}\s+{int(num)}\s+-\s+Text.*\.txt$", re.IGNORECASE)
    hits = sorted(f for f in os.listdir(folder) if pat.match(f))
    return hits[0] if hits else None


def _continues(previous_tail, text):
    """For a page read without a model: does it carry on the last one? Yes
    when the last page stopped mid-sentence or this one starts in lower case."""
    if not previous_tail.strip():
        return False
    first = text.lstrip()[:1]
    return first.islower() or not previous_tail.rstrip()[-1:] in '.!?"\u201d)'


def transcribe_scan(name, num, provider, model, key, progress=None, cancelled=None, redo=False,
                    ocr=False, stats=None):
    """Transcribe every page of one scan that isn't already cached, then
    write its Text Output file. Returns the Text Output filename, or None
    when no page could be read.

    With ocr, each page is first read by Windows' own text recognition, and
    a page that reads like typed text is kept as it is, for free. Other
    pages go to the model; with no provider they're left for later. stats,
    if given, counts pages by how they were read: "free", "ai", "left"."""
    if stats is None:
        stats = {}
    for k in ("free", "ai", "left"):
        stats.setdefault(k, 0)
    scan = get_scan(name, num)
    pages = page_count(scan)
    os.makedirs(_cache_dir(name, num), exist_ok=True)
    with open(_scan_meta_path(name, num), "w", encoding="utf-8") as fh:
        json.dump({"filename": scan["filename"], "pages": pages}, fh)
    done = {} if redo else cached_pages(name, num)
    previous_tail = ""
    for page in range(1, pages + 1):
        if cancelled and cancelled():
            raise ScanError("Stopped.")
        if progress:
            progress(page - 1, pages, f"{scan['filename']}: reading page {page} of {pages}")
        if page in done:
            previous_tail = done[page]["text"][-400:]
            continue
        image = render_page(scan, page)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        result = None
        if ocr:
            from . import winocr

            got = winocr.read_page(image)
            if got and got["typed"]:
                result = {"date": "", "location": "", "title": "",
                          "continues": _continues(previous_tail, got["text"]),
                          "text": got["text"], "uncertain": "", "page": page,
                          "model": "windows/ocr", "at": now}
                stats["free"] += 1
        if result is None:
            if not provider:
                stats["left"] += 1
                previous_tail = ""
                continue
            prompt = (f'This is page {page} of {pages} of "{scan["filename"]}" from the source "{name}".\n')
            if previous_tail:
                prompt += ("The previous page ended like this, to help you decide CONTINUES:\n"
                           f"<<<\n{previous_tail}\n>>>\n")
            prompt += "Transcribe this page."
            usage = {}
            reply = ai.complete(provider, model, key, TRANSCRIBE_SYSTEM, prompt,
                                images=[("image/jpeg", image)], max_tokens=8000, usage=usage)
            result = parse_transcription(reply)
            result.update({"page": page, "model": f"{provider}/{model}", "at": now})
            if usage:
                result["usage"] = usage
            stats["ai"] += 1
        with open(_page_cache_path(name, num, page), "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
        done[page] = result
        previous_tail = result["text"][-400:]
    if progress:
        progress(pages, pages, f"{scan['filename']}: all {pages} pages looked at")
    if not cached_pages(name, num):
        return None
    return write_text_output(name, num)


# What a page costs before any page has been read with this model: the
# image, the instructions and the previous page's ending going in; the
# transcription (about 800 characters on a typical journal page) and the
# model's thinking coming out.
PROMPT_TOKENS = 600
OUTPUT_TOKENS = 1500
# Ask before starting a job bigger than this.
CONFIRM_DOLLARS = 1.0
CONFIRM_PAGES = 100


def _page_sizes(scan):
    """(width, height) of each page as Minerva sends it, without rendering."""
    if scan["is_pdf"]:
        import pypdfium2 as pdfium
        try:
            pdf = pdfium.PdfDocument(scan["path"])
        except Exception:
            raise ScanError(f'Couldn\'t open "{scan["filename"]}" as a PDF.')
        try:
            sizes = []
            for i in range(len(pdf)):
                w, h = pdf[i].get_size()
                scale = min(MAX_EDGE / max(w, h, 1), 4.0)
                sizes.append((w * scale, h * scale))
            return sizes
        finally:
            pdf.close()
    from PIL import Image
    try:
        with Image.open(scan["path"]) as img:
            w, h = img.size
    except Exception:
        raise ScanError(f'Couldn\'t open "{scan["filename"]}" as an image.')
    scale = min(MAX_EDGE / max(w, h, 1), 1.0)
    return [(w * scale, h * scale)]


def _image_tokens(w, h, model):
    edge = ai.IMAGE_EDGE.get(model)
    if edge and max(w, h) > edge:
        scale = edge / max(w, h)
        w, h = w * scale, h * scale
    return int(w * h / 750) + 1


def _measured(name, model_id):
    """Average tokens per page the provider reported for this model on
    pages of this source already read, if there are enough to go on."""
    seen = []
    for s in list_scans(name):
        for p in cached_pages(name, s["num"]).values():
            u = p.get("usage")
            if p.get("model") == model_id and u:
                seen.append(u)
    if len(seen) < 3:
        return None
    return {"input": sum(u["input"] for u in seen) / len(seen),
            "output": sum(u["output"] for u in seen) / len(seen), "pages": len(seen)}


def estimate(name, nums, provider, model, redo=False):
    """How many pages a transcription job would send, about how many tokens,
    and what that costs on the chosen model (None when Minerva doesn't know
    the provider's prices)."""
    pages = image_tokens = 0
    for n in nums:
        scan = get_scan(name, n)
        done = set() if redo else set(cached_pages(name, n))
        for i, (w, h) in enumerate(_page_sizes(scan), 1):
            if i not in done:
                pages += 1
                image_tokens += _image_tokens(w, h, model)
    measured = _measured(name, f"{provider}/{model}")
    if measured:
        tokens_in = int(measured["input"] * pages)
        tokens_out = int(measured["output"] * pages)
    else:
        tokens_in = image_tokens + PROMPT_TOKENS * pages
        tokens_out = OUTPUT_TOKENS * pages
    price = ai.PRICES.get(model) if provider == "anthropic" else None
    cost = None
    if price:
        cost = round((tokens_in * price[0] + tokens_out * price[1]) / 1_000_000, 2)
    confirm = (cost is not None and cost >= CONFIRM_DOLLARS) or (cost is None and pages >= CONFIRM_PAGES)
    return {"pages": pages, "input_tokens": tokens_in, "output_tokens": tokens_out,
            "cost": cost, "measured_pages": measured["pages"] if measured else 0,
            "confirm": confirm}


def write_text_output(name, num):
    scan = get_scan(name, num)
    pages = cached_pages(name, num)
    folder = text_output_dir(name)
    os.makedirs(folder, exist_ok=True)
    base = f"{name} {int(num)} - Text"
    filename = base + ".txt"
    i = 2
    while os.path.exists(os.path.join(folder, filename)):
        filename = f"{base} ({i}).txt"
        i += 1
    rel_scan = os.path.relpath(scan["path"], scans_root()).replace(os.sep, "/")
    lines = [f"{name.upper()} {int(num)} — TEXT TRANSCRIPTION",
             f"Source: {rel_scan} ({len(pages)} page{'s' if len(pages) != 1 else ''})",
             f"Transcribed by Minerva on {datetime.date.today().isoformat()}. Each segment is one scanned page.",
             ""]
    for page in sorted(pages):
        p = pages[page]
        lines += [SEP, f"SEGMENT {page} — Page {page}", f"Date: {p['date'] or 'none'}"]
        if p["location"]:
            lines.append(f"Location: {p['location']}")
        if p["title"]:
            lines.append(f"Title: {p['title']}")
        if p["continues"]:
            lines.append("Continues the previous page")
        lines += [SEP, p["text"], ""]
        if p["uncertain"]:
            lines += [f"Uncertain words: {p['uncertain']}", ""]
    lines += [SEP, f"END OF {name.upper()} {int(num)} — TEXT TRANSCRIPTION", SEP, ""]
    with open(os.path.join(folder, filename), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return filename


# --------------------------------------------------------------------------
# The Master file
# --------------------------------------------------------------------------

def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def file_version(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def parse_master(text):
    """Split a Master into entries. Each entry keeps the character span of
    its body so a proofread edit can replace exactly that text."""
    notes_m = NOTES_HEADER_RE.search(text)
    notes_start = notes_m.start() if notes_m else len(text)
    matches = [m for m in ENTRY_RE.finditer(text) if m.start() < notes_start]
    entries = []
    for i, m in enumerate(matches):
        block_end = matches[i + 1].start() if i + 1 < len(matches) else notes_start
        # a boxed ALL-CAPS heading (e.g. closing notes) ends the entry too
        box = SECTION_BOX_RE.search(text, m.end(), block_end)
        if box:
            block_end = box.start()
        # Metadata (Date:, Time:, Location:) sits either between the ENTRY
        # line and the first ==== line, or in its own ==== box right after it.
        sep_m = SEP_LINE_RE.search(text, m.end(), block_end)
        meta_text = text[m.end():sep_m.start()] if sep_m else ""
        body_start = sep_m.end() if sep_m else m.end()
        if not meta_text.strip() and sep_m:
            sep2 = SEP_LINE_RE.search(text, sep_m.end(), block_end)
            boxed = text[sep_m.end():sep2.start()] if sep2 else ""
            lines = [ln for ln in boxed.splitlines() if ln.strip()]
            if lines and all(META_LINE_RE.match(ln) for ln in lines):
                meta_text, body_start = boxed, sep2.end()
        if body_start < len(text) and text[body_start] == "\n":
            body_start += 1
        # the body ends before the trailing blank lines and ==== lines that
        # open the next entry (or the notes)
        body_end = body_start + len(_strip_trailing_separators(text[body_start:block_end]))
        meta = {}
        for line in meta_text.splitlines():
            mm = META_LINE_RE.match(line)
            if mm:
                meta.setdefault(mm.group(1).lower(), mm.group(2).strip())
        label = m.group(2).strip()
        scan_m, seg_m = SCAN_LABEL_RE.search(label), SEGMENT_LABEL_RE.search(label)
        entries.append({
            "num": int(m.group(1)), "label": label, "title": (m.group(3) or "").strip(),
            "date": meta.get("date", ""), "location": meta.get("location") or meta.get("place", ""),
            "scan": int(scan_m.group(1)) if scan_m else None,
            "page": int(seg_m.group(1)) if seg_m else None,
            "body": text[body_start:body_end],
            "span": [body_start, body_end], "line_span": [m.start(), m.end()],
        })
    notes = {}
    if notes_m:
        current = None
        for line in text[notes_m.end():].splitlines():
            nm = NOTE_START_RE.match(line.strip())
            if nm:
                nums = _expand_nums(nm.group(1))
                current = line.strip()
                for n in nums:
                    notes.setdefault(n, []).append(current)
            elif re.match(r"^=+\s*$", line.strip()):
                current = None
    return {"entries": entries, "notes": notes, "has_notes_section": bool(notes_m),
            "notes_start": notes_m.start() if notes_m else None}


def _strip_trailing_separators(tail):
    """Drop the blank lines and ==== lines that close an entry's block."""
    while True:
        tail = tail.rstrip()
        head, _, last = tail.rpartition("\n")
        if last.strip() and set(last.strip()) == {"="}:
            tail = head
        else:
            return tail


def _expand_nums(spec):
    nums = set()
    for a, b in re.findall(r"(\d+)\s*(?:[–—-]\s*(\d+))?", spec):
        a = int(a)
        b = int(b) if b else a
        if b >= a and b - a < 500:
            nums.update(range(a, b + 1))
    return nums


def _clean_title(t):
    return re.sub(r"\s+", " ", (t or "").replace("\n", " ")).strip()


def entries_from_pages(name, scan_nums, start_num):
    """Group transcribed pages into Master entries. A page marked as
    continuing the previous one is joined to it."""
    entries = []
    for num in scan_nums:
        pages = cached_pages(name, num)
        for page in sorted(pages):
            p = pages[page]
            if p["continues"] and entries:
                prev = entries[-1]
                prev["body"] = prev["body"].rstrip() + "\n\n" + p["text"].strip()
                prev["pages"].append([num, page])
                if p["uncertain"]:
                    prev["uncertain"].append(p["uncertain"])
                continue
            entries.append({"scan": num, "page": page, "pages": [[num, page]],
                            "title": _clean_title(p["title"]), "date": p["date"],
                            "location": p["location"], "body": p["text"].strip(),
                            "uncertain": [p["uncertain"]] if p["uncertain"] else []})
    for i, e in enumerate(entries):
        e["num"] = start_num + i
    return entries


def _entry_block(e):
    (s1, p1), (s2, p2) = e["pages"][0], e["pages"][-1]
    if len(e["pages"]) == 1:
        where = f"Scan {s1}, Segment {p1}"
    elif s1 == s2:
        where = f"Scan {s1}, Segments {p1}-{p2}"
    else:
        where = f"Scan {s1}, Segment {p1} to Scan {s2}, Segment {p2}"
    head = f"ENTRY {e['num']} ({where})"
    if e["title"]:
        head += f" — {e['title']}"
    lines = [SEP, head, f"Date: {e['date'] or 'none'}"]
    if e["location"]:
        lines.append(f"Location: {e['location']}")
    lines += [SEP, e["body"], ""]
    return "\n".join(lines)


def _note_lines(entries):
    return [f"Entry {e['num']}: " + " ".join(u.replace("\n", " ") for u in e["uncertain"])
            for e in entries if e["uncertain"]]


def build_master(name, scan_nums=None):
    """Create the Master from transcribed scans, or add scans that aren't in
    it yet to an existing one. Returns what was added."""
    statuses = {s["num"]: s for s in scan_status(name)}
    if scan_nums is None:
        scan_nums = [n for n, s in statuses.items()
                     if not s["in_master"] and s["pages"] and s["transcribed_pages"] >= s["pages"]]
    scan_nums = sorted(int(n) for n in scan_nums)
    for n in scan_nums:
        s = statuses.get(n)
        if not s:
            raise ScanError(f"{name} has no scan {n}.")
        if s["in_master"]:
            raise ScanError(f"Scan {n} is already in the Master.")
        if s["transcribed_pages"] < s["pages"]:
            raise ScanError(f"Scan {n} isn't fully transcribed yet.")
    if not scan_nums:
        raise ScanError("There are no newly transcribed scans to add.")

    path = master_path(name)
    if not os.path.isfile(path):
        new = entries_from_pages(name, scan_nums, 1)
        parts = [f"{name.upper()} — MASTER TRANSCRIPT",
                 f"Built by Minerva on {datetime.date.today().isoformat()} from "
                 f"{len(scan_nums)} scan{'s' if len(scan_nums) != 1 else ''}. "
                 "Notes on words that were hard to read are at the end.", ""]
        parts += [_entry_block(e) for e in new]
        parts += [SEP, "OCR AMBIGUITY NOTES", SEP]
        parts += _note_lines(new) or ["None."]
        parts.append("")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
        _record_pages(name, new)
        return {"created": True, "added": len(new), "scans": scan_nums}

    text = _read(path)
    parsed = parse_master(text)
    start = max((e["num"] for e in parsed["entries"]), default=0) + 1
    new = entries_from_pages(name, scan_nums, start)
    backup_master(name)
    blocks = "\n".join(_entry_block(e) for e in new) + "\n"
    if parsed["notes_start"] is not None:
        # insert before the ==== line that opens the notes section
        cut = text.rfind(SEP[:10], 0, parsed["notes_start"])
        cut = text.rfind("\n", 0, cut) + 1 if cut > 0 else parsed["notes_start"]
        notes = _note_lines(new)
        updated = text[:cut] + blocks + text[cut:].rstrip("\n") + "\n"
        if notes:
            updated += "\n" + "\n\n".join(notes) + "\n"
    else:
        updated = text.rstrip("\n") + "\n\n" + blocks
        notes = _note_lines(new)
        if notes:
            updated += "\n".join([SEP, "OCR AMBIGUITY NOTES", SEP] + notes) + "\n"
    _write_atomic(path, updated)
    _record_pages(name, new)
    return {"created": False, "added": len(new), "scans": scan_nums}


def _record_pages(name, entries):
    pagelinks.save(name, {e["num"]: {"pages": e["pages"], "method": "transcribed", "confidence": 1.0}
                          for e in entries})


def _write_atomic(path, text):
    tmp = path + ".minerva-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def backup_master(name):
    """Copy the Master into .minerva/backups before Minerva changes it.
    Keeps one copy per day so a day of proofreading doesn't pile them up."""
    src = master_path(name)
    if not os.path.isfile(src):
        return None
    folder = os.path.join(core.META_DIR, "backups")
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, f"{name} - Master ({datetime.date.today().isoformat()}).txt")
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
    return dst


def read_master(name):
    path = master_path(name)
    if not os.path.isfile(path):
        raise ScanError(f"{name} doesn't have a Master yet.")
    text = _read(path)
    parsed = parse_master(text)
    reviewed = reviewed_set(name)
    filed = filed_map(name)
    scans = list_scans(name)
    links = pagelinks.links_for(name, parsed["entries"], [s["num"] for s in scans])
    entries = []
    for e in parsed["entries"]:
        link = links.get(e["num"])
        entries.append({k: e[k] for k in ("num", "label", "title", "date", "location", "scan", "page", "body")}
                       | {"notes": parsed["notes"].get(e["num"], []),
                          "reviewed": e["num"] in reviewed,
                          "filed": filed.get(e["num"]),
                          "pages": link["pages"] if link else [],
                          "link": {"method": link["method"], "note": pagelinks.describe(link)} if link
                          else {"method": None, "note": pagelinks.describe(None)}})
    return {"name": name, "version": file_version(path), "entries": entries,
            "scans": {s["num"]: s["filename"] for s in scans},
            "scan_pages": {s["num"]: _safe_page_count(s) for s in scans}}


def _safe_page_count(scan):
    try:
        return page_count(scan)
    except ScanError:
        return 0


def save_master_entry(name, num, version, body, title=None, date=None):
    """Replace one entry's text (and optionally its title and date) in the
    Master. Refuses if the file changed since the page loaded it."""
    path = master_path(name)
    if file_version(path) != version:
        raise ScanError("The Master changed since you opened it. Reload and try again.")
    text = _read(path)
    entry = next((e for e in parse_master(text)["entries"] if e["num"] == int(num)), None)
    if entry is None:
        raise ScanError(f"Entry {num} isn't in the Master.")
    body = (body or "").replace("\r\n", "\n").strip("\n")
    if re.search(r"^ENTRY\s+\d+\s*\(", body, re.MULTILINE) or NOTES_HEADER_RE.search(body):
        raise ScanError("An entry's text can't contain a line that looks like an ENTRY heading.")
    if re.search(r"^=+[ \t]*$", body, re.MULTILINE):
        raise ScanError("An entry's text can't contain a line made only of = signs.")
    s, e = entry["span"]
    updated = text[:s] + body + text[e:]
    if title is not None or date is not None:
        updated = _replace_entry_meta(updated, int(num), title, date)
    backup_master(name)
    _write_atomic(path, updated)
    return file_version(path)


def _replace_entry_meta(text, num, title, date):
    entry = next(e for e in parse_master(text)["entries"] if e["num"] == num)
    ls, le = entry["line_span"]
    if title is not None:
        title = _clean_title(title)
        head = f"ENTRY {num} ({entry['label']})" + (f" — {title}" if title else "")
        text = text[:ls] + head + text[le:]
        le = ls + len(head)
    if date is not None:
        date = _clean_title(date) or "none"
        sep_m = SEP_LINE_RE.search(text, le)
        stop = sep_m.start() if sep_m else le
        if not META_LINE_RE.search(text[le:stop]) and sep_m:
            # metadata in its own ==== box (see parse_master)
            sep2 = SEP_LINE_RE.search(text, sep_m.end())
            if sep2 and all(META_LINE_RE.match(ln) for ln in text[sep_m.end():sep2.start()].splitlines() if ln.strip()):
                le, stop = sep_m.end(), sep2.start()
        meta = text[le:stop]
        dm = re.search(r"^Date\s*:.*$", meta, re.MULTILINE | re.IGNORECASE)
        if dm:
            meta = meta[:dm.start()] + f"Date: {date}" + meta[dm.end():]
        else:
            meta = f"\nDate: {date}" + meta
        text = text[:le] + meta + text[stop:]
    return text


# --------------------------------------------------------------------------
# Review state and filing
# --------------------------------------------------------------------------

def _ensure_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS scan_reviews (
        source TEXT NOT NULL, entry_num INTEGER NOT NULL, reviewed_at TEXT,
        PRIMARY KEY (source, entry_num))""")


def reviewed_set(name):
    conn = core.get_conn()
    try:
        _ensure_tables(conn)
        return {r["entry_num"] for r in conn.execute(
            "SELECT entry_num FROM scan_reviews WHERE source = ?", (name,))}
    finally:
        conn.close()


def set_reviewed(name, num, reviewed):
    conn = core.get_conn()
    try:
        _ensure_tables(conn)
        if reviewed:
            conn.execute("INSERT OR REPLACE INTO scan_reviews VALUES (?, ?, ?)",
                         (name, int(num), datetime.datetime.now().isoformat(timespec="seconds")))
        else:
            conn.execute("DELETE FROM scan_reviews WHERE source = ? AND entry_num = ?", (name, int(num)))
        conn.commit()
    finally:
        conn.close()


def filed_map(name):
    """Master entry number -> the library entry already made from it. Every
    entry of a joined run maps to the one library entry."""
    conn = core.get_conn()
    try:
        rows = conn.execute("SELECT id, title, top_folder, source_entry_num, source_entry_last FROM entries "
                            "WHERE source_journal = ? AND source_entry_num IS NOT NULL", (name,)).fetchall()
    finally:
        conn.close()
    out = {}
    for r in rows:
        info = {"id": r["id"], "title": r["title"], "category": r["top_folder"]}
        first = r["source_entry_num"]
        last = r["source_entry_last"] or first
        if last > first:
            info["joined"] = [first, last]
        for n in range(first, last + 1):
            out.setdefault(n, info)
    return out


def safe_title(title, fallback):
    t = core.INVALID_FILENAME_CHARS_RE.sub("", _clean_title(title)).strip(" .")
    return (t or fallback)[:80].rstrip(" .")


def suggested_title(entry):
    if entry.get("title"):
        return entry["title"]
    for line in (entry.get("body") or "").splitlines():
        line = line.strip()
        if line and not (line.startswith("[") and line.endswith("]")):
            words = line.split()
            return " ".join(words[:8]) + ("…" if len(words) > 8 else "")
    return f"Entry {entry['num']}"


def joined_entry(run):
    """One entry made from a run of consecutive Master entries."""
    first, last = run[0], run[-1]
    if len(run) == 1:
        return first
    label = first["label"] if first["label"] == last["label"] else f"{first['label']} to {last['label']}"
    return first | {"num": first["num"], "last": last["num"], "label": label,
                    "body": "\n\n".join(e["body"].strip() for e in run)}


def journal_draft_text(name, entry, title, category):
    which = f"Entries {entry['num']}-{entry['last']}" if entry.get("last") else f"Entry {entry['num']}"
    lines = [f"Source: {name} Journal", f"Source: {which} ({entry['label']})",
             title, f"Category: {category}", f"Date: {entry.get('date') or 'none'}"]
    if entry.get("location"):
        lines.append(f"Location: {entry['location']}")
    lines += [SEP, "", entry["body"].strip(), ""]
    return "\n".join(lines)


def file_entries(name, items):
    """Create a library entry for each {num, title, category}. With
    "through", the entries from num to through are joined into one (a piece
    that runs across several Master entries). Skips entries already filed.
    Returns what was created."""
    master = read_master(name)
    by_num = {e["num"]: e for e in master["entries"]}
    created, skipped, taken = [], [], set()
    for item in items:
        num = int(item["num"])
        entry = by_num.get(num)
        if entry is None:
            skipped.append({"num": num, "reason": "not in the Master"})
            continue
        through = int(item.get("through") or num)
        run = [by_num.get(n) for n in range(num, through + 1)] if through > num else [entry]
        if through - num > 200 or any(e is None for e in run):
            skipped.append({"num": num, "reason": f"entries {num}-{through} aren't all in the Master"})
            continue
        if any(e["filed"] or e["num"] in taken for e in run):
            skipped.append({"num": num, "reason": "already filed"})
            continue
        taken.update(e["num"] for e in run)
        entry = joined_entry(run)
        category = item.get("category")
        if category not in core.TOP_FOLDERS:
            skipped.append({"num": num, "reason": f"unknown category {category!r}"})
            continue
        title = safe_title(item.get("title") or suggested_title(entry), f"Entry {num}")
        cat_dir = os.path.join(core.ARCHIVE_ROOT, category)
        folder, i = title, 2
        while os.path.exists(os.path.join(cat_dir, folder)):
            folder = f"{title} ({i})"
            i += 1
        path = os.path.join(cat_dir, folder)
        os.makedirs(path)
        with open(os.path.join(path, f"{folder} [J].txt"), "w", encoding="utf-8") as fh:
            fh.write(journal_draft_text(name, entry, title, category))
        created.append({"num": num, "through": through, "title": folder, "category": category})
    if created:
        core.scan_and_sync()
    return {"created": created, "skipped": skipped}

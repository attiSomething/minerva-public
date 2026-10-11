"""Simple videos from a narration: the words shown a stanza at a time over
a background, with the line being read picked out, saved as MP4.

Everything happens on this computer. Each screen is drawn with Pillow from
the line timings narration keeps in .minerva/narrations, then the audio
and video tool (FFmpeg) joins the screens to the narration's audio.
"""

import glob
import io
import json
import os
import re
import shutil
import tempfile

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from . import core, mediatools, narration, sharing

SIZES = {
    "square": (1080, 1080, "Square", "Instagram and Facebook posts"),
    "vertical": (1080, 1920, "Vertical", "Reels, TikTok and YouTube Shorts"),
    "wide": (1920, 1080, "Widescreen", "YouTube and websites"),
}
BACKGROUNDS = ("cover", "plain", "image")
FPS = 24
INK = (255, 255, 255)
DIM = (255, 255, 255, 120)
PLAIN = ((27, 42, 74), (31, 63, 136))  # the app's navy, top to bottom
MAX_IMAGE = 30 * 1024 * 1024


class VideoError(Exception):
    user_facing = True


def narrations(kind=None, item_id=None):
    """Narrations whose audio is still in Exports, newest first; those
    made from kind/item_id first of all."""
    out = []
    for path in glob.glob(os.path.join(narration._timings_dir(), "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                t = json.load(fh)
        except (OSError, ValueError):
            continue
        audio = os.path.join(sharing.exports_dir(), t.get("audio") or "")
        if not t.get("audio") or not os.path.isfile(audio):
            continue
        out.append({"name": t["audio"], "title": t.get("title") or t["audio"], "seconds": round(t.get("seconds") or 0),
                    "kind": t.get("kind"), "id": t.get("id"), "made": os.path.getmtime(audio),
                    "mine": bool(kind) and t.get("kind") == kind and t.get("id") == item_id,
                    "has_cover": t.get("kind") == "project" and bool(t.get("id")) and bool(sharing.cover_file(t["id"], "front"))})
    return sorted(out, key=lambda n: (not n["mine"], -n["made"]))


def _load(name):
    t = narration.timings(name)
    if not t or not t.get("lines"):
        raise VideoError("That narration's timings are missing. Make the narration again.")
    audio = os.path.join(sharing.exports_dir(), os.path.basename(t["audio"]))
    if not os.path.isfile(audio):
        raise VideoError(f"{t['audio']} is no longer in Exports.")
    return t, audio


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def _font_files():
    windir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    import reportlab
    rl = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for regular, italic in [
        (os.path.join(windir, "georgia.ttf"), os.path.join(windir, "georgiai.ttf")),
        (os.path.join(windir, "times.ttf"), os.path.join(windir, "timesi.ttf")),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
        (os.path.join(rl, "Vera.ttf"), os.path.join(rl, "VeraIt.ttf")),
    ]:
        if os.path.isfile(regular) and os.path.isfile(italic):
            return regular, italic
    return None, None


_font_cache = {}


def _font(size, italic=False):
    key = (size, italic)
    if key not in _font_cache:
        regular, ital = _font_files()
        path = ital if italic else regular
        _font_cache[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    return _font_cache[key]


def background(size_key, source=None):
    """The backdrop: a picture filling the frame, darkened so white words
    read over it, or the plain navy."""
    w, h = SIZES[size_key][:2]
    if source is not None:
        img = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (w, h), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=max(2, w // 400)))
        return ImageEnhance.Brightness(img).enhance(0.42)
    top, bottom = PLAIN
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        f = y / max(1, h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(3)))
    return grad.resize((w, h))


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if cur and draw.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else []) or [""]


def _fit(draw, lines, width, height, start, prose=False):
    """The biggest font size (down to a floor) at which the lines fit."""
    size = start
    while True:
        font = _font(size)
        # a wrapped line carries on indented, as a poem is set in print
        rows = [(i, row, k > 0) for i, line in enumerate(lines)
                for k, row in enumerate(_wrap(draw, line, font, width - (0 if prose else int(size * 1.2))))]
        if len(rows) * size * 1.45 <= height or size <= start * 0.55:
            return font, size, rows
        size = int(size * 0.92)


def frame(bg, size_key, lines, current, header="", title_card=None, prose=False):
    """One screen: the stanza with the current line in full white, a few
    sentences of prose (centered, like subtitles), or a title card."""
    w, h = SIZES[size_key][:2]
    img = bg.copy().convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    margin = int(w * 0.09)
    base = int(min(w, h) * 0.05)
    if title_card is not None:
        font = _font(int(base * 1.6), italic=True)
        rows = _wrap(draw, title_card, font, w - 2 * margin)
        line_h = int(font.size * 1.3)
        y = (h - line_h * len(rows)) // 2
        for row in rows:
            draw.text((w // 2, y), row, font=font, fill=INK, anchor="ma")
            y += line_h
        if header:
            draw.text((w // 2, y + base), header, font=_font(int(base * 0.75)), fill=DIM, anchor="ma")
        return Image.alpha_composite(img, layer).convert("RGB")
    if header:
        draw.text((w // 2, int(h * 0.07)), header, font=_font(int(base * 0.62), italic=True), fill=DIM, anchor="ma")
    area_h = int(h * 0.72)
    font, size, rows = _fit(draw, lines, w - 2 * margin, area_h, base, prose)
    line_h = int(size * 1.45)
    if len(rows) * line_h > area_h:  # still too long: show the rows around the current line
        keep = max(1, area_h // line_h)
        first = next(k for k, (i, _r, _c) in enumerate(rows) if i == current)
        start = max(0, min(first - keep // 3, len(rows) - keep))
        rows = rows[start:start + keep]
    y = (h - line_h * len(rows)) // 2 + int(size * 0.2)
    left = margin
    for i, row, carried in rows:
        if prose:
            draw.text((w // 2, y), row, font=font, fill=INK, anchor="ma")
        else:
            draw.text((left + (int(size * 1.2) if carried else 0), y), row, font=font, fill=INK if i == current else DIM)
        y += line_h
    return Image.alpha_composite(img, layer).convert("RGB")


LONG_LINE = 200  # a prose paragraph: shown a few sentences at a time instead
CHUNK = 150


def _display_chunks(text):
    """A long paragraph as sentence groups short enough to read at a glance."""
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        words = sentence.split()
        while words:  # a sentence longer than a chunk breaks between words
            piece = ""
            while words and (not piece or len(piece) + 1 + len(words[0]) <= CHUNK):
                piece = f"{piece} {words.pop(0)}".strip()
            if cur and len(cur) + 1 + len(piece) > CHUNK:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur} {piece}".strip()
    return out + ([cur] if cur else [])


def screens(t):
    """[(start seconds, stanza lines, current, header, title, prose)] from the
    timings: a title card for each title read, else the stanza with the
    line being read."""
    lines = t["lines"]
    chapters = t.get("chapters") or []
    stanzas = {}
    for n, ln in enumerate(lines):
        if not ln.get("title"):
            stanzas.setdefault((ln.get("chapter", 0), ln["stanza"]), []).append(n)
    out = []
    for n, ln in enumerate(lines):
        start = ln["start"] if n else 0.0
        if ln.get("title"):
            out.append((start, None, None, t.get("author") or "", ln["text"], False))
            continue
        chapter = ln.get("chapter", 0)
        header = chapters[chapter]["title"] if len(chapters) > 1 and chapter < len(chapters) else t.get("title") or ""
        if len(ln["text"]) > LONG_LINE:
            chunks = _display_chunks(ln["text"])
            span = max(0.0, ln["end"] - ln["start"])
            total = sum(len(c) for c in chunks) or 1
            at = start
            for c in chunks:
                out.append((at, [c], 0, header, None, True))
                at = round(at + span * len(c) / total, 3)
            continue
        group = [k for k in stanzas[(chapter, ln["stanza"])] if len(lines[k]["text"]) <= LONG_LINE]
        out.append((start, [lines[k]["text"] for k in group], group.index(n), header, None, False))
    return out


def _source_image(t, background_kind, image_bytes):
    if background_kind == "image":
        if not image_bytes:
            raise VideoError("Choose a picture for the background.")
        if len(image_bytes) > MAX_IMAGE:
            raise VideoError("That picture is too large.")
        try:
            img = Image.open(io.BytesIO(image_bytes))
            img.load()
            return img
        except (OSError, ValueError, Image.DecompressionBombError):
            raise VideoError("That file isn't a picture Minerva can read.") from None
    if background_kind == "cover" and t.get("kind") == "project" and t.get("id"):
        path = sharing.cover_file(t["id"], "front")
        if path:
            return Image.open(path)
    return None


def preview(name, size_key, background_kind, image_bytes=None):
    """PNG bytes of a screen partway in, for the dialog."""
    if size_key not in SIZES:
        raise VideoError("Choose a size.")
    t, _audio = _load(name)
    bg = background(size_key, _source_image(t, background_kind, image_bytes))
    s = screens(t)
    pick = next((x for x in s if x[1] is not None and x[2] == min(1, len(x[1]) - 1)), s[0])
    img = frame(bg, size_key, *pick[1:])
    img.thumbnail((540, 540))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make(job, name, size_key, background_kind, image_bytes=None):
    """The background job: draw every screen and join them to the audio."""
    if size_key not in SIZES:
        raise VideoError("Choose a size.")
    if background_kind not in BACKGROUNDS:
        raise VideoError("Choose a background.")
    if not mediatools.ffmpeg():
        raise VideoError("Making a video needs the audio and video tool. Set it up first.")
    t, audio = _load(name)
    bg = background(size_key, _source_image(t, background_kind, image_bytes))
    s = screens(t)
    total = float(t.get("seconds") or s[-1][0] + 1)
    folder = tempfile.mkdtemp(prefix="minerva-video-")
    try:
        listing = ["ffconcat version 1.0"]
        for n, (start, *screen) in enumerate(s):
            if job.cancelled():
                raise VideoError("Stopped.")
            job.progress(n, len(s), f"Drawing screen {n + 1} of {len(s)}")
            path = os.path.join(folder, f"{n:05d}.png")
            frame(bg, size_key, *screen).save(path)
            end = s[n + 1][0] if n + 1 < len(s) else total
            listing += [f"file '{os.path.basename(path)}'", f"duration {max(1 / FPS, end - start):.3f}"]
        listing.append(f"file '{os.path.basename(path)}'")  # the last screen's duration needs it listed again
        with open(os.path.join(folder, "screens.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(listing) + "\n")
        stem = os.path.splitext(t["audio"])[0]
        out = sharing._unique_path(f"{stem} - video ({size_key})", "mp4")
        tmp = out + ".minerva-tmp.mp4"
        try:
            mediatools.run_with_progress(
                ["-f", "concat", "-safe", "0", "-i", os.path.join(folder, "screens.txt"), "-i", audio,
                 "-map", "0:v", "-map", "1:a", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
                 "-tune", "stillimage", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
                 "-metadata", f"title={t.get('title') or stem}", "-movflags", "+faststart", tmp],
                total, job, "Making the video")
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {"name": os.path.basename(out), "folder": os.path.relpath(os.path.dirname(out), core.ARCHIVE_ROOT),
            "seconds": round(total), "size": size_key}

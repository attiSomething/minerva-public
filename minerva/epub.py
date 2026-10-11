"""EPUB 3 export of a project, for ebook stores and readers.

Built by hand from the same document Minerva makes PDFs and Word files
from: an optional cover, a title page, the copyright page, dedication and
epigraph, contents, one chapter per entry, then acknowledgments and about
the author. Line breaks inside stanzas are kept and indented lines stay
indented. An EPUB 2 table of contents (toc.ncx) is included as well, for
older readers.
"""

import datetime
import mimetypes
import os
import re
import uuid
import zipfile
from xml.sax.saxutils import escape, quoteattr

CSS = """body { font-family: Georgia, serif; line-height: 1.5; margin: 0 5%; }
h1 { font-size: 1.5em; margin: 2em 0 1.2em; font-weight: normal; }
p { margin: 0 0 1em; text-indent: 0; }
.title-page { text-align: center; margin-top: 30%; }
.title-page h1 { font-size: 2.2em; margin: 0 0 .4em; }
.subtitle { font-style: italic; font-size: 1.2em; }
.author { margin-top: 3em; font-size: 1.15em; }
.copyright { margin-top: 50%; font-size: .85em; }
.copyright p { margin: 0 0 .3em; }
.dedication, .epigraph { margin-top: 30%; text-align: center; font-style: italic; }
.contents p { margin: 0 0 .4em; }
.cover { margin: 0; padding: 0; text-align: center; }
.cover img { max-width: 100%; max-height: 100%; }
"""


def _id(n):
    return f"s{n:03d}"


def _lines(body):
    """Stanzas or paragraphs as XHTML, keeping line breaks and indents."""
    out = []
    for block in [b.split("\n") for b in re.split(r"\n\s*\n", (body or "").strip("\n")) if b.strip()]:
        lines = []
        for line in block:
            stripped = line.lstrip(" ")
            lines.append("&#160;" * (len(line) - len(stripped)) + escape(stripped))
        out.append("<p>" + "<br/>".join(lines) + "</p>")
    return "\n".join(out)


def _page(title, body, lang, css_class=""):
    cls = f' class="{css_class}"' if css_class else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang}" lang="{lang}">
<head><meta charset="utf-8"/><title>{escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body{cls}>
{body}
</body>
</html>
"""


def write(doc, path, lang="en"):
    """Write doc (sharing's project document) to path as an EPUB."""
    title = doc["title"]
    author = doc.get("author") or ""
    isbn = (doc.get("isbn") or "").strip()
    ident = f"urn:isbn:{re.sub(r'[^0-9Xx]', '', isbn)}" if isbn else \
        f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'minerva:' + title + ':' + author)}"
    modified = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    items = []   # (id, href, media type, properties)
    spine = []   # (id, linear)
    files = {}   # href -> bytes
    toc = []     # (href, label) for the contents
    n = 0

    def add_page(label, body, css_class="", in_toc=False, properties=""):
        nonlocal n
        n += 1
        href = f"{_id(n)}.xhtml"
        files[href] = _page(label, body, lang, css_class).encode("utf-8")
        items.append((_id(n), href, "application/xhtml+xml", properties))
        spine.append(_id(n))
        if in_toc:
            toc.append((href, label))
        return href

    cover_href = None
    if doc.get("front"):
        ext = os.path.splitext(doc["front"])[1].lower()
        cover_href = "cover" + (".png" if ext == ".png" else ".jpg")
        with open(doc["front"], "rb") as fh:
            files[cover_href] = fh.read()
        items.append(("cover-image", cover_href, mimetypes.types_map.get(os.path.splitext(cover_href)[1], "image/jpeg"),
                      "cover-image"))
        add_page("Cover", f'<div class="cover"><img src="{cover_href}" alt={quoteattr(title)}/></div>', "cover")

    if doc.get("title_page", True):
        body = f'<div class="title-page"><h1>{escape(title)}</h1>'
        if doc.get("subtitle"):
            body += f'<p class="subtitle">{escape(doc["subtitle"])}</p>'
        if author:
            body += f'<p class="author">{escape(author)}</p>'
        add_page(title, body + "</div>")
    fm = doc.get("front_matter_lines") or []
    if fm:
        add_page("Copyright", '<div class="copyright">' + "".join(
            f"<p>{escape(line) or '&#160;'}</p>" for line in fm) + "</div>")
    for label, text, css in doc.get("front_pages") or []:
        add_page(label, f'<div class="{css}">{_lines(text)}</div>')

    contents_at = len(spine)  # the contents page goes here once hrefs are known
    piece_pages = []
    for p in doc["pieces"]:
        piece_pages.append(add_page(p["title"], f"<h1>{escape(p['title'])}</h1>\n{_lines(p['body'])}", in_toc=True))
    for label, text, _css in doc.get("back_pages") or []:
        add_page(label, f"<h1>{escape(label)}</h1>\n{_lines(text)}", in_toc=True)

    nav_list = "\n".join(f'<li><a href="{h}">{escape(lbl)}</a></li>' for h, lbl in toc)
    files["nav.xhtml"] = _page("Contents", f'<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>\n{nav_list}\n</ol></nav>',
                               lang, "contents").encode("utf-8")
    items.append(("nav", "nav.xhtml", "application/xhtml+xml", "nav"))
    if doc.get("contents", True):
        spine.insert(contents_at, "nav")
    files["style.css"] = CSS.encode("utf-8")
    items.append(("css", "style.css", "text/css", ""))

    ncx_points = "\n".join(
        f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{escape(lbl)}</text></navLabel><content src="{h}"/></navPoint>'
        for i, (h, lbl) in enumerate(toc, 1))
    files["toc.ncx"] = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content={quoteattr(ident)}/></head>
<docTitle><text>{escape(title)}</text></docTitle>
<navMap>
{ncx_points}
</navMap>
</ncx>
""".encode("utf-8")
    items.append(("ncx", "toc.ncx", "application/x-dtbncx+xml", ""))

    manifest = "\n".join(
        f'<item id="{i}" href="{h}" media-type="{mt}"{f" properties={quoteattr(pr)}" if pr else ""}/>'
        for i, h, mt, pr in items)
    spine_xml = "\n".join(f'<itemref idref="{i}"/>' for i in spine)
    meta = [f'<dc:identifier id="bookid">{escape(ident)}</dc:identifier>',
            f"<dc:title>{escape(title)}</dc:title>", f"<dc:language>{lang}</dc:language>",
            f'<meta property="dcterms:modified">{modified}</meta>']
    if author:
        meta.append(f"<dc:creator>{escape(author)}</dc:creator>")
    if doc.get("copyright"):
        meta.append(f"<dc:rights>{escape(doc['copyright'])}</dc:rights>")
    if cover_href:
        meta.append('<meta name="cover" content="cover-image"/>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{lang}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
{chr(10).join(meta)}
</metadata>
<manifest>
{manifest}
</manifest>
<spine toc="ncx">
{spine_xml}
</spine>
</package>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""
    with zipfile.ZipFile(path, "w") as z:
        # the mimetype must come first and not be compressed
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for href, data in files.items():
            z.writestr(f"OEBPS/{href}", data, compress_type=zipfile.ZIP_DEFLATED)

"""Reusable snippets: cover letters, bios and acknowledgments, with
placeholders such as {venue} and {title} filled in when one is used.

Snippets are about the writer rather than any one library, so they're kept
with the app's settings (like the manuscript contact details), not in the
library.
"""

import datetime
import re
import uuid

from . import config as app_config, manuscript

KINDS = {
    "cover": "Cover letter",
    "bio_short": "Short bio",
    "bio_long": "Long bio",
    "ack": "Acknowledgments",
    "other": "Other",
}
PLACEHOLDERS = {
    "venue": "where it's going",
    "title": "the piece's title",
    "name": "your name, from Settings > Manuscript details",
    "email": "your email, from the same place",
    "website": "your website, from the same place",
    "date": "today's date",
}
STARTERS = [
    {"name": "Cover letter", "kind": "cover", "body":
        "Dear Editors of {venue},\n\n"
        "Please consider \"{title}\" for publication in {venue}. "
        "[A sentence on the piece, or why it suits them.]\n\n"
        "[Your short bio.]\n\n"
        "Thank you for your time and consideration.\n\n"
        "{name}\n{email}"},
    {"name": "Short bio", "kind": "bio_short", "body":
        "{name} writes [what you write] in [where you live]. [Their work appears in ...]"},
]
MAX_SNIPPETS = 200
MAX_LENGTH = 20000
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class SnippetError(ValueError):
    user_facing = True


def all_snippets():
    return list(app_config.load().get("snippets") or [])


def _save_all(items):
    cfg = app_config.load()
    cfg["snippets"] = items
    app_config.save(cfg)


def save(body):
    """Add a snippet, or change one when body has its id."""
    name = " ".join(str(body.get("name") or "").split())[:80]
    text = str(body.get("body") or "").replace("\r\n", "\n").strip()
    kind = body.get("kind") if body.get("kind") in KINDS else "other"
    if not name:
        raise SnippetError("Give the snippet a name.")
    if len(text) > MAX_LENGTH:
        raise SnippetError("That snippet is too long.")
    items = all_snippets()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    sid = body.get("id")
    if sid:
        for s in items:
            if s["id"] == sid:
                s.update(name=name, kind=kind, body=text, updated_at=now)
                _save_all(items)
                return s
        raise SnippetError("That snippet no longer exists.")
    if len(items) >= MAX_SNIPPETS:
        raise SnippetError("That's as many snippets as Minerva keeps. Delete one first.")
    s = {"id": uuid.uuid4().hex[:10], "name": name, "kind": kind, "body": text, "updated_at": now}
    items.append(s)
    _save_all(items)
    return s


def delete(sid):
    _save_all([s for s in all_snippets() if s["id"] != sid])


def add_starters():
    have = {s["name"].casefold() for s in all_snippets()}
    return [save(dict(s)) for s in STARTERS if s["name"].casefold() not in have]


def get(sid):
    return next((s for s in all_snippets() if s["id"] == sid), None)


def fill(text, values):
    """Replace {placeholders} with values; ones without a value are left
    as written so the gap is easy to see."""
    c = manuscript.contact()
    known = {"name": c.get("name") or app_config.load().get("username") or "", "email": c.get("email") or "",
             "website": c.get("website") or "",
             "date": datetime.date.today().strftime("%B %d, %Y").replace(" 0", " ")}
    known.update({k: str(v) for k, v in (values or {}).items() if v not in (None, "") and k in PLACEHOLDERS})
    return _PLACEHOLDER_RE.sub(lambda m: known.get(m.group(1).lower(), m.group(0)) or m.group(0), text)


def by_kind(kind):
    return [s for s in all_snippets() if s["kind"] == kind]

"""Library check: spot folders and files Minerva can't make sense of, so
they surface early instead of quietly going missing (an entry folder with no
draft simply doesn't appear in Entries) or failing later during an export.

Read-only: this only reports. The user fixes things in the library folder
or in Minerva, then rescans.
"""

import os

from . import core

KINDS = {
    "no_draft": ("No current draft", "This folder has no .txt draft at its top level, so it doesn't appear in Entries."),
    "several_current": ("More than one current draft", "Several drafts are tagged [C]; Minerva shows the one named here."),
    "several_tagged": ("Unclear which draft is current", "There are several tagged drafts but none is [C]; Minerva shows the one named here."),
    "several_untagged": ("Unclear which draft is current", "There are several .txt files and none is tagged [C] or [J]; Minerva shows the one named here."),
    "not_utf8": ("Unusual text encoding", "This draft isn't saved as UTF-8, so some characters (like curly quotes or accents) may show wrong. Re-saving it as UTF-8 fixes it."),
    "unreadable": ("Can't be read", "Minerva couldn't open this file. It may be locked by another program, still downloading from the cloud, or blocked by permissions."),
    "empty": ("Empty draft", "The current draft has no words in it."),
    "loose_file": ("File outside an entry", "This file sits directly in a category folder, so it isn't part of any entry. Move it into an entry folder (or into Sources)."),
}

_cache = {"root": None, "issues": None}


def _issue(kind, rel, detail=""):
    title, help_text = KINDS[kind]
    return {"kind": kind, "title": title, "help": help_text, "path": rel.replace(os.sep, "/"), "detail": detail}


def _read_check(full):
    """None if the file reads fine as UTF-8 text, else the issue kind."""
    try:
        with open(full, "rb") as fh:
            data = fh.read()
    except OSError:
        return "unreadable"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "not_utf8"
    return None


def run(progress=None):
    """progress, if given, is called as progress(done, total) along the way."""
    root = core.ARCHIVE_ROOT
    issues = []
    tops = [(top, os.path.join(root, top)) for top in core.TOP_FOLDERS]
    tops = [(top, path, sorted(os.listdir(path))) for top, path in tops if os.path.isdir(path)]
    total = sum(len(names) for _, _, names in tops)
    done = 0
    for top, top_path, names in tops:
        for name in names:
            done += 1
            if progress and (done % 25 == 0 or done == total):
                progress(done, total)
            full = os.path.join(top_path, name)
            rel = os.path.join(top, name)
            if os.path.isfile(full):
                if not name.startswith(".") and name.lower() not in ("desktop.ini", "thumbs.db"):
                    issues.append(_issue("loose_file", rel))
                continue
            if not os.path.isdir(full):
                continue
            try:
                txts = sorted(n for n in os.listdir(full)
                              if n.lower().endswith(".txt") and os.path.isfile(os.path.join(full, n)))
            except OSError:
                issues.append(_issue("unreadable", rel))
                continue
            if not txts:
                issues.append(_issue("no_draft", rel))
                continue
            draft = core.find_current_draft(full)
            tagged = [n for n in txts if core.DRAFT_TAG_RE.search(n)]
            current = [n for n in tagged if "[C]" in n]
            if len(current) > 1:
                issues.append(_issue("several_current", rel, f"Showing {draft}"))
            elif not current and len(tagged) > 1:
                issues.append(_issue("several_tagged", rel, f"Showing {draft}"))
            elif not tagged and len(txts) > 1:
                issues.append(_issue("several_untagged", rel, f"Showing {draft}"))
            problem = _read_check(os.path.join(full, draft))
            if problem:
                issues.append(_issue(problem, os.path.join(rel, draft)))
            elif core.word_count_of(os.path.join(full, draft)) == 0:
                issues.append(_issue("empty", os.path.join(rel, draft)))
    _cache.update(root=root, issues=issues)
    return issues


def issues():
    if _cache["root"] != core.ARCHIVE_ROOT or _cache["issues"] is None:
        return run()
    return _cache["issues"]


def entry_ids(conn, found):
    """Attach the entry id to each issue that belongs to a listed entry."""
    rows = {r["rel_path"]: r["id"] for r in conn.execute("SELECT id, rel_path FROM entries")}
    out = []
    for i in found:
        parts = i["path"].split("/")
        out.append(i | {"entry_id": rows.get("/".join(parts[:2]))})
    return out

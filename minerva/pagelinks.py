"""Which scanned pages each Master entry is written on.

A page (a scan file and a page number in it) is the unit. An entry is linked
to an ordered list of pages, which may run from one scan file into the next,
and a page can hold several short entries. Links live in Minerva's index
(the entry_pages table), never in the Master text.

Links come from one of four places, recorded as their "method":

  transcribed  Minerva built the entry from those pages itself.
  matched      The entry's text was found on those pages of the source's
               transcriptions (Minerva's own, or a "Text Output" file).
  label        Nothing matched, so the page named in the entry's
               "(Scan X, Segment Y)" label is used as a best guess.
  manual       The user chose the pages. Re-matching never changes these.

The first version's labels often name the wrong page even when the scan is
right, which is why links are rebuilt from the text rather than read from
the label.
"""

import collections
import datetime
import json
import os
import re

from . import core

SEGMENT_HEAD_RE = re.compile(r"^SEGMENT\s+(\d+)\b.*$", re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9]+")
SCAN_RE = re.compile(r"Scan\s+(\d+)", re.IGNORECASE)
SEGMENTS_RE = re.compile(r"(?:Segment|Page)s?\s+(\d+)(?:\s*[-–—]\s*(\d+))?", re.IGNORECASE)

# a match is trusted when the chosen pages hold this much of the entry's text
GOOD_COVERAGE = 0.6
WEAK_COVERAGE = 0.3
# bumped when matching improves: links Minerva only guessed (from the label)
# or matched weakly under an older version are worked out again, once
MATCH_VERSION = 2


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def _ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS entry_pages (
        source TEXT NOT NULL, entry_num INTEGER NOT NULL,
        pages TEXT NOT NULL, method TEXT NOT NULL, confidence REAL,
        updated_at TEXT, PRIMARY KEY (source, entry_num))""")


def stored(name):
    """{entry_num: {"pages": [[scan, page], ...], "method", "confidence"}}"""
    conn = core.get_conn()
    try:
        _ensure_table(conn)
        rows = conn.execute("SELECT entry_num, pages, method, confidence FROM entry_pages "
                            "WHERE source = ?", (name,)).fetchall()
    finally:
        conn.close()
    return {r["entry_num"]: {"pages": json.loads(r["pages"]), "method": r["method"],
                             "confidence": r["confidence"]} for r in rows}


def save(name, links, replace_manual=False):
    """links: {entry_num: {"pages", "method", "confidence"}}"""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn = core.get_conn()
    try:
        _ensure_table(conn)
        manual = set() if replace_manual else {r["entry_num"] for r in conn.execute(
            "SELECT entry_num FROM entry_pages WHERE source = ? AND method = 'manual'", (name,))}
        for num, link in links.items():
            if int(num) in manual:
                continue
            conn.execute("INSERT OR REPLACE INTO entry_pages VALUES (?, ?, ?, ?, ?, ?)",
                         (name, int(num), json.dumps(_clean_pages(link["pages"])), link["method"],
                          link.get("confidence"), now))
        conn.commit()
    finally:
        conn.close()


def _clean_pages(pages):
    out = []
    for p in pages or []:
        sp = [int(p[0]), int(p[1])]
        if sp[0] < 1 or sp[1] < 1:
            raise ValueError("Scan and page numbers start at 1.")
        if sp not in out:
            out.append(sp)
    return out


def set_manual(name, num, pages):
    from . import scanning

    pages = _clean_pages(pages)
    if not pages:
        raise ValueError("An entry needs at least one page.")
    counts = {s["num"]: s for s in scanning.list_scans(name)}
    for scan, page in pages:
        if scan not in counts:
            raise ValueError(f"{name} has no scan {scan}.")
        if page > scanning._safe_page_count(counts[scan]):
            raise ValueError(f'"{counts[scan]["filename"]}" has no page {page}.')
    save(name, {int(num): {"pages": pages, "method": "manual", "confidence": 1.0}},
         replace_manual=True)
    return pages


def forget(name, nums=None):
    """Drop links that weren't set by hand so they are matched again."""
    conn = core.get_conn()
    try:
        _ensure_table(conn)
        if nums is None:
            conn.execute("DELETE FROM entry_pages WHERE source = ? AND method != 'manual'", (name,))
        else:
            conn.executemany("DELETE FROM entry_pages WHERE source = ? AND entry_num = ? "
                             "AND method != 'manual'", [(name, int(n)) for n in nums])
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Page text: Minerva's own transcriptions, else the Text Output files
# --------------------------------------------------------------------------

def parse_text_output(text):
    """{page: text} from a Text Output file, one SEGMENT per scanned page."""
    heads = list(SEGMENT_HEAD_RE.finditer(text))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.setdefault(int(m.group(1)), text[m.end():end])
    return out


def page_texts(name):
    """[(scan, page, text)] for every page that has been transcribed, in
    reading order."""
    from . import scanning

    out = []
    folder = scanning.text_output_dir(name)
    for s in scanning.list_scans(name):
        pages = {p: v["text"] for p, v in scanning.cached_pages(name, s["num"]).items()}
        if not pages:
            fn = scanning._existing_text_output(name, s["num"])
            if fn:
                pages = parse_text_output(scanning._read(os.path.join(folder, fn)))
        out += [(s["num"], p, t) for p, t in sorted(pages.items())]
    return out


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _words(text, notes=False):
    """The words of a text, lowercased. Square-bracketed transcriber's notes
    are left out unless notes=True: for prose they're guesses that differ
    between transcriptions, but for a drawing or diagram the description is
    the only text there is, and it's copied word for word into the Master."""
    text = text.lower().replace("’", "").replace("'", "")
    if not notes:
        text = re.sub(r"\[[^\]]*\]", " ", text)
    return WORD_RE.findall(text)


def _shingles(text, n=3, notes=False):
    w = _words(text, notes)
    if len(w) < n:
        return {tuple(w)} if w else set()
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def label_pages(label, scan_nums):
    """The pages an entry's label names, e.g. "Scan 3, Segments 4-5"."""
    scan_m = SCAN_RE.search(label or "")
    if scan_m:
        scan = int(scan_m.group(1))
    elif len(scan_nums) == 1:
        scan = scan_nums[0]
    else:
        return []
    seg = SEGMENTS_RE.search(label or "")
    if not seg:
        return [[scan, 1]]
    a = int(seg.group(1))
    b = int(seg.group(2)) if seg.group(2) else a
    if b < a or b - a > 20:
        b = a
    return [[scan, p] for p in range(a, b + 1)]


class Matcher:
    """Finds an entry's pages by the three-word phrases it shares with them.

    The page sharing the most phrases is the start; neighbouring pages
    (across scan files too) are added while they hold text of the entry
    that the pages chosen so far don't, so a long entry gets every page it
    runs over and a short one stays on its own page."""

    def __init__(self, pages):
        pages = list(pages)
        self.where = [(s, p) for s, p, _ in pages]
        # two views of each page: prose only, and prose plus bracketed notes
        self.views = {}
        for notes in (False, True):
            shingles = [_shingles(t, notes=notes) for _, _, t in pages]
            index = collections.defaultdict(list)
            for i, sh in enumerate(shingles):
                for x in sh:
                    index[x].append(i)
            self.views[notes] = (shingles, index)
        self.pages = self.where

    def match(self, body, label_scan=None):
        """Match on the prose; when that finds little (a drawing, a diagram,
        a page that's mostly notes), try again with the notes included and
        keep whichever covers more of the entry."""
        best = self._match(body, label_scan, notes=False)
        if best is None or best["coverage"] < GOOD_COVERAGE:
            with_notes = self._match(body, label_scan, notes=True)
            if with_notes and (best is None or with_notes["coverage"] > best["coverage"]):
                best = with_notes
        return best

    def _match(self, body, label_scan, notes):
        shingles, index = self.views[notes]
        sh = _shingles(body, notes=notes)
        if not sh:
            return None
        hits = collections.Counter()
        for x in sh:
            for i in index.get(x, ()):
                hits[i] += 1
        if not hits:
            return None
        best = max(hits, key=lambda i: (hits[i], self.where[i][0] == label_scan, -i))
        chosen, covered = [best], sh & shingles[best]

        def adds(k):
            gain = len((sh & shingles[k]) - covered)
            return gain >= 6 or (gain >= 3 and gain >= 0.2 * len(shingles[k]))

        for step in (-1, 1):
            k = best + step
            while 0 <= k < len(shingles) and adds(k):
                covered |= sh & shingles[k]
                if step < 0:
                    chosen.insert(0, k)
                else:
                    chosen.append(k)
                k += step
        return {"pages": [list(self.where[i]) for i in chosen],
                "coverage": len(covered) / len(sh)}


def match_entries(name, entries, scan_nums, pages=None):
    """Work out links for Master entries ({num, label, body, scan})."""
    matcher = Matcher(page_texts(name) if pages is None else pages)
    out = {}
    for e in entries:
        m = matcher.match(e["body"], e.get("scan")) if matcher.pages else None
        if m and m["coverage"] >= WEAK_COVERAGE:
            out[e["num"]] = {"pages": m["pages"], "method": "matched",
                             "confidence": round(m["coverage"], 2)}
            continue
        guess = label_pages(e.get("label"), scan_nums)
        if guess:
            out[e["num"]] = {"pages": guess, "method": "label", "confidence": 0.0}
        elif m:
            out[e["num"]] = {"pages": m["pages"], "method": "matched",
                             "confidence": round(m["coverage"], 2)}
    return out


def _upgrade(name, have):
    """Drop guessed and weak links made by an older matcher, once per source,
    so they're matched again. Links set by hand are never touched."""
    settings = core.read_library_settings(core.ARCHIVE_ROOT)
    versions = settings.get("page_match_versions") or {}
    if versions.get(name, 1) >= MATCH_VERSION:
        return have
    redo = [n for n, l in have.items() if l["method"] == "label"
            or (l["method"] == "matched" and (l.get("confidence") or 0) < GOOD_COVERAGE)]
    if redo:
        forget(name, redo)
    versions[name] = MATCH_VERSION
    settings["page_match_versions"] = versions
    core.write_library_settings(core.ARCHIVE_ROOT, settings)
    return {n: l for n, l in have.items() if n not in redo}


def links_for(name, entries, scan_nums):
    """Links for every entry, matching (and storing) any not yet linked."""
    have = _upgrade(name, stored(name))
    missing = [e for e in entries if e["num"] not in have]
    if missing:
        new = match_entries(name, missing, scan_nums)
        if new:
            save(name, new)
            have.update(new)
    return have


def describe(link):
    """A short note for the page about how sure a link is, or None."""
    if not link:
        return "Minerva couldn't tell which page this entry is on."
    if link["method"] == "label":
        return ("Minerva couldn't find this entry's text in the transcriptions, so this is "
                "the page its label names. Check it, and add or remove pages if it's wrong.")
    if link["method"] == "matched" and (link.get("confidence") or 0) < GOOD_COVERAGE:
        return "Only part of this entry's text was found on these pages. Check them."
    return None

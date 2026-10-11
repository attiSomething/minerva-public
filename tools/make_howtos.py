"""Writes minerva/docs/howto/*.html: the how-tos, each with a cover
illustration and diagrams. All colors come from CSS classes (style.css,
"How-tos") so themes apply. Edit the text here and run:

    python tools/make_howtos.py
"""
import math
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "minerva", "docs", "howto")
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------- covers

def laurel(cx, cy, r, side, n=8):
    """One branch of a laurel wreath: a stem curving up one side of the
    emblem from the bottom, with paired leaves pointing up the stem."""
    sgn = -1 if side == "left" else 1
    angles = [math.radians(-80 + i * 17) for i in range(n + 1)]  # from bottom to upper side
    pts = [(cx + sgn * r * math.cos(a), cy - r * math.sin(a)) for a in angles]
    out = ['<path class="hc-line hc-stem" d="M' + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + '"/>']
    for i in range(1, n + 1):
        a = angles[i]
        x, y = pts[i]
        tx, ty = -sgn * math.sin(a), -math.cos(a)        # along the stem, upward
        nx, ny = sgn * math.cos(a), -math.sin(a)         # outward from the centre
        size = 12 - i * 0.5
        for side_k in (1, -0.75):
            lx = x + (tx * 0.75 + nx * 0.65 * side_k) * size
            ly = y + (ty * 0.75 + ny * 0.65 * side_k) * size
            mx, my = (x + lx) / 2, (y + ly) / 2
            px, py = -(ly - y), (lx - x)
            k = 0.3
            out.append(f'<path class="hc-leaf" d="M{x:.1f} {y:.1f} Q{mx + px * k:.1f} {my + py * k:.1f} {lx:.1f} {ly:.1f} '
                       f'Q{mx - px * k:.1f} {my - py * k:.1f} {x:.1f} {y:.1f}Z"/>')
    tip_x, tip_y = pts[-1]
    a = angles[-1]
    out.append(f'<path class="hc-leaf" d="M{tip_x:.1f} {tip_y:.1f} q{-sgn * math.sin(a) * 3:.1f} {-6 - math.cos(a) * 3:.1f} {-sgn * math.sin(a) * 9:.1f} {-math.cos(a) * 9 - 3:.1f} q{sgn * 4:.1f} {4:.1f} {sgn * math.sin(a) * 9:.1f} {math.cos(a) * 9 + 3:.1f}Z"/>')
    return "".join(out)


def cover(key, label, emblem):
    corners = "".join(
        f'<path class="hc-fill" d="M{x} {y - 5} L{x + 5} {y} L{x} {y + 5} L{x - 5} {y}Z"/>'
        for x, y in ((13, 13), (307, 13), (13, 167), (307, 167)))
    return f'''<svg class="howto-cover" viewBox="0 0 320 180" role="img" aria-label="{label}">
<defs><linearGradient id="hc-bg-{key}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" class="hc-stop-a"/><stop offset="1" class="hc-stop-b"/></linearGradient>
<radialGradient id="hc-glow-{key}" cx=".5" cy=".5" r=".55"><stop offset="0" class="hc-glow"/><stop offset="1" class="hc-glow-none"/></radialGradient></defs>
<rect width="320" height="180" fill="url(#hc-bg-{key})"/>
<rect width="320" height="180" fill="url(#hc-glow-{key})"/>
<rect class="hc-frame" x="13" y="13" width="294" height="154"/>
<rect class="hc-frame hc-thin" x="19" y="19" width="282" height="142"/>
{corners}
{laurel(160, 88, 60, "left")}{laurel(160, 88, 60, "right")}<path class="hc-fill" d="M156 150 L164 150 L160 156Z"/>
<g transform="translate(160 90)">{emblem}</g>
</svg>'''


EMBLEMS = {
    # an open notebook with a scanning beam across it
    "scan": '''<path class="hc-line" d="M-34 -22 Q-17 -28 0 -22 Q17 -28 34 -22 L34 24 Q17 18 0 24 Q-17 18 -34 24Z"/>
<path class="hc-line" d="M0 -22 L0 24"/>
<path class="hc-thinline" d="M-28 -12 Q-15 -16 -5 -12 M-28 -4 Q-15 -8 -5 -4 M-28 4 Q-15 0 -5 4 M5 -12 Q16 -16 28 -12 M5 -4 Q16 -8 28 -4"/>
<rect class="hc-beam" x="-40" y="6" width="80" height="5" rx="2.5"/>
<path class="hc-line" d="M-44 2 L-44 15 M44 2 L44 15"/>''',
    # three labelled folders on a shelf
    "organize": '''<path class="hc-line" d="M-36 26 L36 26"/>
<path class="hc-line" d="M-32 26 L-32 -12 L-24 -12 L-21 -8 L-14 -8 L-14 26"/>
<path class="hc-line" d="M-9 26 L-9 -22 L-1 -22 L2 -18 L9 -18 L9 26"/>
<path class="hc-line" d="M14 26 L14 -6 L22 -6 L25 -2 L32 -2 L32 26"/>
<rect class="hc-fill" x="-29" y="2" width="12" height="4" rx="1"/>
<rect class="hc-fill" x="-6" y="-8" width="12" height="4" rx="1"/>
<rect class="hc-fill" x="17" y="8" width="12" height="4" rx="1"/>
<path class="hc-fill" d="M-4 -28 L4 -28 L4 -20 L0 -23 L-4 -20Z"/>''',
    # a quill over a stack of pages
    "drafts": '''<path class="hc-line" d="M-30 -10 L14 -10 L14 26 L-30 26Z"/>
<path class="hc-thinline" d="M-26 -14 L18 -14 L18 22 M-22 -18 L22 -18 L22 18"/>
<path class="hc-thinline" d="M-24 -2 L6 -2 M-24 6 L8 6 M-24 14 L2 14"/>
<path class="hc-fill" d="M34 -30 Q20 -22 6 4 L4 12 L10 6 Q30 -12 34 -30Z"/>
<path class="hc-line" d="M6 4 L22 -14"/>''',
    # an open book with a ribbon and a seal
    "share": '''<path class="hc-line" d="M-38 -18 Q-18 -26 0 -16 Q18 -26 38 -18 L38 20 Q18 12 0 22 Q-18 12 -38 20Z"/>
<path class="hc-line" d="M0 -16 L0 22"/>
<path class="hc-thinline" d="M-32 -8 Q-18 -14 -6 -8 M-32 0 Q-18 -6 -6 0 M-32 8 Q-18 2 -6 8 M6 -8 Q18 -14 32 -8 M6 0 Q18 -6 32 0"/>
<path class="hc-fill" d="M10 -20 L16 -20 L16 4 L13 0 L10 4Z"/>
<circle class="hc-fill" cx="26" cy="16" r="8"/>
<path class="hc-seal" d="M26 10 L27.8 14 L32 14.4 L28.8 17.2 L29.8 21.4 L26 19.2 L22.2 21.4 L23.2 17.2 L20 14.4 L24.2 14Z"/>''',
    # loose pages dropping into a tray
    "intake": '''<path class="hc-line" d="M-36 14 L-36 28 L36 28 L36 14"/>
<path class="hc-line" d="M-36 14 L-22 14 L-18 20 L18 20 L22 14 L36 14"/>
<path class="hc-line" d="M-26 -30 L-6 -30 L-6 -4 L-26 -4Z" transform="rotate(-12 -16 -17)"/>
<path class="hc-line" d="M4 -34 L24 -34 L24 -8 L4 -8Z" transform="rotate(10 14 -21)"/>
<path class="hc-thinline" d="M-22 -22 L-10 -24 M-21 -16 L-9 -18 M8 -27 L20 -25 M7 -21 L19 -19"/>
<path class="hc-fill" d="M-4 2 L4 2 L4 8 L8 8 L0 15 L-8 8 L-4 8Z"/>''',
    # a stapled booklet with a numbered spine
    "chapbook": '''<path class="hc-line" d="M-34 -26 L0 -20 L34 -26 L34 24 L0 30 L-34 24Z"/>
<path class="hc-line" d="M0 -20 L0 30"/>
<rect class="hc-fill" x="-2" y="-8" width="4" height="6" rx="1"/>
<rect class="hc-fill" x="-2" y="12" width="4" height="6" rx="1"/>
<path class="hc-thinline" d="M-28 -12 L-8 -9 M-28 -4 L-8 -1 M-28 4 L-12 7 M8 -9 L28 -12 M8 -1 L28 -4 M8 7 L22 5"/>''',
    # an envelope with a small clock
    "track": '''<path class="hc-line" d="M-36 -20 L26 -20 L26 22 L-36 22Z"/>
<path class="hc-line" d="M-36 -20 L-5 6 L26 -20"/>
<circle class="hc-fill" cx="26" cy="20" r="14"/>
<path class="hc-seal" d="M25 11 L27 11 L27 19 L33 22 L32 24 L25 21Z"/>''',
    # a manuscript page with a header block and a centred title
    "manuscript": '''<path class="hc-line" d="M-26 -32 L26 -32 L26 32 L-26 32Z"/>
<path class="hc-thinline" d="M-20 -26 L-4 -26 M-20 -21 L-6 -21 M-20 -16 L-8 -16 M12 -26 L20 -26"/>
<rect class="hc-fill" x="-10" y="-8" width="20" height="4" rx="1"/>
<path class="hc-thinline" d="M-18 2 L14 2 M-18 8 L10 8 M-18 14 L16 14 M-18 22 L8 22"/>''',
    # a computer with a shield on its screen
    "local": '''<path class="hc-line" d="M-34 -26 L34 -26 L34 16 L-34 16Z"/>
<path class="hc-line" d="M-44 26 L44 26 L36 16 M-44 26 L-36 16"/>
<path class="hc-fill" d="M0 -18 L14 -13 Q14 2 0 10 Q-14 2 -14 -13Z"/>
<path class="hc-seal" d="M-6 -5 L-1 0 L7 -9" style="fill:none;stroke-width:2.5"/>''',
    # a cloud with a coin
    "service": '''<path class="hc-line" d="M-30 14 Q-44 14 -42 0 Q-40 -12 -26 -10 Q-22 -28 -2 -26 Q16 -24 18 -10 Q34 -12 36 2 Q36 14 22 14Z"/>
<circle class="hc-fill" cx="22" cy="18" r="13"/>
<path class="hc-seal" d="M19 11 L26 11 L26 13 L21 13 L21 17 L25 17 Q28 17 28 21 Q28 25 24 25 L18 25 L18 23 L24 23 Q26 23 26 21 Q26 19 24 19 L19 19Z"/>''',
    # a microphone with sound rings
    "voice": '''<rect class="hc-fill" x="-9" y="-30" width="18" height="34" rx="9"/>
<path class="hc-line" d="M-17 -4 Q-17 14 0 14 Q17 14 17 -4"/>
<path class="hc-line" d="M0 14 L0 26 M-11 26 L11 26"/>
<path class="hc-line" d="M-27 -20 Q-35 -6 -27 8 M27 -20 Q35 -6 27 8"/>''',
}


# ---------------------------------------------------------------- diagrams

def arrow_defs(key):
    return (f'<defs><marker id="ar-{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path class="d-arrowhead" d="M0 0 L10 5 L0 10Z"/></marker></defs>')


def box(x, y, w, h, title, sub="", kind="d-box"):
    lines = [f'<rect class="{kind}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>']
    ty = y + (h / 2 + 5 if not sub else h / 2 - 3)
    lines.append(f'<text class="d-title" x="{x + w / 2}" y="{ty}" text-anchor="middle">{title}</text>')
    if sub:
        for i, s in enumerate(sub.split("|")):
            lines.append(f'<text class="d-sub" x="{x + w / 2}" y="{ty + 17 + i * 14}" text-anchor="middle">{s}</text>')
    return "".join(lines)


def arrow(key, x1, y1, x2, y2, label=""):
    s = f'<path class="d-arrow" d="M{x1} {y1} L{x2} {y2}" marker-end="url(#ar-{key})"/>'
    if label:
        s += f'<text class="d-sub" x="{(x1 + x2) / 2}" y="{min(y1, y2) - 7}" text-anchor="middle">{label}</text>'
    return s


def figure(key, w, h, body, caption, label):
    return (f'<figure class="howto-figure"><svg viewBox="0 0 {w} {h}" role="img" aria-label="{label}">'
            f'{arrow_defs(key)}{body}</svg><figcaption>{caption}</figcaption></figure>')


def tree(lines, x=24, y=30, step=24):
    """A folder tree. lines: (depth, name, note, kind) with kind in folder/file/key."""
    out = []
    for i, (depth, name, note, kind) in enumerate(lines):
        yy = y + i * step
        xx = x + depth * 26
        if depth:
            out.append(f'<path class="d-tree" d="M{xx - 16} {yy - step + 8} L{xx - 16} {yy - 4} L{xx - 4} {yy - 4}"/>')
        if kind == "file":
            out.append(f'<path class="d-file" d="M{xx} {yy - 13} L{xx + 9} {yy - 13} L{xx + 13} {yy - 9} L{xx + 13} {yy + 3} L{xx} {yy + 3}Z"/>')
        else:
            out.append(f'<path class="{"d-folder-key" if kind == "key" else "d-folder"}" d="M{xx} {yy - 11} L{xx + 6} {yy - 11} L{xx + 8} {yy - 8} L{xx + 16} {yy - 8} L{xx + 16} {yy + 3} L{xx} {yy + 3}Z"/>')
        out.append(f'<text class="d-title" x="{xx + 22}" y="{yy}">{name}</text>')
        if note:
            out.append(f'<text class="d-note" x="{x + 330}" y="{yy}">{note}</text>')
    return "".join(out)


# ---------------------------------------------------------------- pages

def page(name, title, summary, key, emblem_label, body):
    html = f'''<article class="howto" data-summary="{summary}">
{cover(key, emblem_label, EMBLEMS[key])}
<h1>{title}</h1>
{body}
</article>
'''
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)


k = "scan"
page("1 - Scanning and Sorting.html", "Scanning and Sorting for Minerva",
     "Turn photographed or scanned notebooks into proofread, filed entries.", k,
     "An open notebook under a scanning beam, framed in laurels", f'''
<p class="lede">Minerva can read your handwritten or typed pages, split them into separate pieces of writing, and file each one as an entry in your library. You check every word before anything is filed.</p>

<div class="howto-note"><strong>Before you start:</strong> reading pages needs AI-assisted scanning, turned on in <em>Settings</em> with your own provider and key. Proofreading and filing work without it.</div>

{figure(k + "1", 680, 124,
        box(10, 20, 140, 84, "Sources", "your scans and|photos", "d-box")
        + arrow(k + "1", 150, 62, 182, 62)
        + box(184, 20, 140, 84, "Transcribe", "pages become|a Master", "d-box-key")
        + arrow(k + "1", 324, 62, 356, 62)
        + box(358, 20, 140, 84, "Proofread", "fix words, check|the pages", "d-box-key")
        + arrow(k + "1", 498, 62, 530, 62)
        + box(532, 20, 138, 84, "File entries", "each piece gets|its own folder", "d-gold"),
        "From scans to entries: the three tabs on the Scans page, in order.",
        "Flow diagram: Sources, then Transcribe, Proofread, and File entries")}

<h2>1. Put your scans in the Sources folder</h2>
<p>Give each notebook, letter bundle or stack of printouts its own folder inside <code>Sources</code>, with the files in a <code>Scans</code> folder inside it. PDFs and photos (.jpg, .png, .heic and others) both work.</p>
{figure(k + "2", 680, 140, tree([
    (0, "Sources", "", "folder"),
    (1, "Blue Notebook", "one folder per source", "key"),
    (2, "Scans", "", "folder"),
    (3, "Blue Notebook 1.pdf", "numbered in reading order", "file"),
    (3, "Blue Notebook 2.pdf", "", "file"),
]), "Number the files the way you'd read them; Minerva keeps that order.", "Folder tree for a source")}

<h2>2. Transcribe and build the Master</h2>
<p>Open <em>Scans</em>, pick the source on the left, and choose the scans to read on the <em>Transcribe</em> tab. Each page is read once and kept, so you can stop and come back without paying for a page twice. Then press <em>Build the Master</em>: Minerva gathers everything into one file of numbered entries, joining a piece that runs onto the next page.</p>
<p><strong>Typed pages are free.</strong> On Windows, Minerva first reads each page with the text recognition built into Windows, offline and at no cost. A page that comes back reading like typed or printed text is kept from that; handwriting goes on to your AI model. With AI turned off, the button reads <em>Read typed pages</em> and handwritten pages are left for later. You can turn this off in <em>Settings</em> under AI-assisted scanning.</p>

<h2>3. Proofread each entry</h2>
<p>The <em>Proofread</em> tab puts the entry's pages beside its text. Fix any misread words, read the notes about hard-to-read spots, and save. The chips above the page show which pages the entry is on; use <em>Add page</em> or <em>Remove page</em> if a piece starts or ends somewhere else.</p>

<h2>4. File entries into your library</h2>
<p>On <em>File entries</em>, tick the entries you're happy with, give each a title and category (or press <em>Suggest titles and categories</em> and check what comes back), then press <em>File selected</em>. Each one becomes its own folder with a <code>[J]</code> draft, and the table marks it <em>Filed</em>. If a poem or story runs across several entries, press <em>join next</em> under each entry number except the last, and they're filed as one piece.</p>

<h2>5. Keep the drawings</h2>
<p>Drawings and diagrams in your scans collect under <em>Entries</em> &rarr; <em>Images</em>. Check the suggested kind and name for each, tick the ones to keep, and press <em>Save images</em>. Their pages are copied into the source's <code>Images</code> folder, sorted by kind.</p>

<div class="howto-tip"><strong>Good to know:</strong> filed entries remember their pages. Open one from <em>Entries</em> and its Scanned Pages panel shows the original handwriting next to your text.</div>
''')

k = "organize"
page("2 - Organizing Files.html", "Using Minerva to Organize Files",
     "Categories, entry folders, projects and flags: where everything lives.", k,
     "Three folders on a shelf with a ribbon, framed in laurels", f'''
<p class="lede">Your library is ordinary folders and text files. Minerva reads that layout, adds a few things a folder can't hold (like flags), and gives you tools to tidy it without ever deleting anything.</p>

{figure(k + "1", 680, 230, tree([
    (0, "Poetry", "a category", "folder"),
    (1, "The Cold Front Came - [MB]", "one folder per entry; [MB] is its project", "key"),
    (2, "The Cold Front Came [C].txt", "the current draft", "file"),
    (2, "Final", "the final draft, once you mark one", "folder"),
    (2, "Archive", "every older draft", "folder"),
    (2, "Images", "pictures that belong to it", "folder"),
    (0, "Sources", "scans to work from", "folder"),
    (0, ".minerva", "Minerva's own index (hidden)", "folder"),
]), "A library on disk. Everything stays readable without Minerva.", "Folder tree of a Minerva library")}

<h2>1. Categories</h2>
<p>Each top-level folder (Fiction, Nonfiction, Poetry, Misc) is a category. To move an entry, open it and change its <em>Category</em>; Minerva moves the folder for you.</p>

<h2>2. Find anything on the Entries page</h2>
<p>Search by title, and filter by category, project, published or the To Edit and To Record flags. Click a row to open the entry.</p>

<h2>3. Group entries into projects</h2>
<p>A project is a collection, like a chapbook or a series. Create one on <em>Projects</em>, then add entries from the project page or from an entry's <em>Project</em> panel. The entry's folder gets a short tag such as <code>- [MB]</code>, so the grouping shows in Explorer too. Put a project's entries in reading order on its page.</p>

<h2>4. Flag what needs doing</h2>
<p>Tick <em>To Edit</em> or <em>To Record</em>, or mark an entry <em>Published</em> and note where. Flags live in Minerva's index, and the Entries page can filter by them.</p>

<h2>5. Clear up duplicates</h2>
<p><em>Duplicates</em>, at the top of the Entries page, lists pieces that look alike. Read both side by side, then mark them as not duplicates, confirm them, or merge them. Merging moves the other entry's whole folder into this one's Archive, so nothing is lost.</p>

<div class="howto-tip"><strong>Good to know:</strong> rename and move entries through Minerva rather than Explorer. Minerva keeps their flags and links; a folder renamed outside it looks like a new entry.</div>
''')

k = "drafts"
d_body = (
    box(10, 30, 150, 70, "Current draft", "Title [C].txt", "d-box-key")
    + arrow(k + "1", 160, 65, 262, 65, "Save (Archive)")
    + box(264, 30, 150, 70, "New draft", "your edit, now [C]", "d-box-key")
    + arrow(k + "1", 85, 100, 85, 140)
    + box(10, 142, 150, 60, "Archive", "the old version, kept", "d-box")
    + arrow(k + "1", 414, 65, 506, 65, "Mark as final")
    + box(508, 30, 162, 70, "Final", "Title (final).txt", "d-gold")
)
page("3 - Managing Drafts.html", "Using Minerva to Manage Drafts",
     "Edit safely, keep every version, and mark the one that's finished.", k,
     "A quill over a stack of pages, framed in laurels", f'''
<p class="lede">Every entry has one current draft. When you change it, the version before can go into the entry's Archive, so you can always go back. When a piece is done, mark that draft as final.</p>

{figure(k + "1", 680, 212, d_body,
        "Saving with Archive keeps the old version; marking final keeps a copy of the finished one.",
        "Diagram: the current draft moves to Archive when saved with Archive; marking final copies it to Final")}

<h2>1. Open an entry and edit</h2>
<p>Click any entry to open it. The text on the left is the current draft. <code>[J]</code> means it's still the original from a journal or scan; <code>[C]</code> means it's been composed or edited.</p>

<h2>2. Choose how to save</h2>
<ul>
<li><strong>Save (Overwrite draft)</strong> replaces the draft in place. Use it for small fixes.</li>
<li><strong>Save (Archive current draft)</strong> moves the old version into Archive first, then saves your edit as the new <code>[C]</code> draft. Use it for real revisions.</li>
</ul>

<h2>3. Go back to an older version</h2>
<p>The <em>Old Drafts</em> panel lists everything in Archive. <em>View</em> reads one; <em>Restore</em> brings it back as the current draft, after archiving the one you have now.</p>

<h2>4. Mark the final draft</h2>
<p>When the piece is finished, press <em>Mark as final</em> in the <em>Share</em> panel. Minerva keeps a copy in the entry's <code>Final</code> folder and shows a Final badge in the list. You can keep editing; the panel tells you when the current draft no longer matches the final. Marking a new final moves the old one into Archive with its date.</p>

<h2>5. Get a second opinion</h2>
<p>With AI-assisted organizing turned on, <em>Ask Minerva</em> can suggest a title, category and project, or proofread the draft. Nothing changes until you apply a suggestion and save.</p>
''')

k = "share"
s_body = (
    box(10, 20, 150, 64, "Entry", "its final draft", "d-gold")
    + arrow(k + "1", 160, 52, 236, 52, "Export")
    + box(238, 20, 170, 64, ".txt  .docx  .pdf", "optional template", "d-box-key")
    + arrow(k + "1", 408, 52, 484, 52)
    + box(486, 20, 184, 64, "Exports folder", "never overwritten", "d-box")
    + box(10, 120, 150, 64, "Project", "entries in order", "d-gold")
    + arrow(k + "1", 160, 152, 236, 152, "Publish")
    + "".join(
        f'<rect class="{"d-gold" if i in (0, 6) else "d-box"}" x="{240 + i * 62}" y="112" width="56" height="80" rx="4"/>'
        f'<text class="d-small" x="{268 + i * 62}" y="156" text-anchor="middle">{t}</text>'
        for i, t in enumerate(["Cover", "Title", "©", "Contents", "Pieces", "…", "Back"]))
)
page("4 - Sharing Final Drafts.html", "Using Minerva to Share Final Drafts",
     "Export entries and put whole projects together as proofs.", k,
     "An open book with a ribbon and a seal, framed in laurels", f'''
<p class="lede">When a piece is ready, export it to send or submit. When a collection is ready, Minerva puts the whole project together as a proof with covers, a title page and contents.</p>

{figure(k + "1", 680, 205, s_body,
        "Top: one entry exported. Bottom: a project's proof, page by page.",
        "Diagram: an entry exports to txt, docx or pdf; a project publishes as cover, title, copyright, contents, pieces and back cover")}

<h2>1. Mark your finals</h2>
<p>Exports use an entry's final draft when it has one, and the current draft otherwise. See <em>Using Minerva to Manage Drafts</em> for marking finals.</p>

<h2>2. Export one entry</h2>
<p>In the entry's <em>Share</em> panel, choose a format (text, Word or PDF), which draft, and a template if you have one, then press <em>Export</em>. The file goes into the <code>Exports</code> folder in your library; a second export is saved alongside as "(2)" rather than replacing the first. Use <em>Open</em> or <em>Show in folder</em> to find it.</p>

<h2>3. Use your own layout</h2>
<p>In <em>Settings</em>, add a Word template with <code>{{{{title}}}}</code> and <code>{{{{body}}}}</code> where they belong (also <code>{{{{category}}}}</code>, <code>{{{{date}}}}</code> and <code>{{{{author}}}}</code>), or a PDF to use as letterhead. Pick it when you export.</p>

<h2>4. Publish a project</h2>
<p>Open the project, put its entries in order, and fill in the <em>Publish</em> panel: page size (6×9, 5×8, A5 and others), subtitle, author, copyright line, ISBN and any other details, plus front and back cover images. Then export a <em>PDF proof</em>, a Word manuscript or plain text.</p>

<div class="howto-tip"><strong>Good to know:</strong> covers are scaled to fill the page, so use images in the same shape as your page size. Every export is a new file; your drafts are never changed by exporting.</div>
''')

def mock_window(x, y, w, h, title):
    """A small stand-in for a Minerva screen: a framed panel with a title bar."""
    return (f'<rect class="d-box" x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>'
            f'<path class="d-tree" d="M{x} {y + 24} L{x + w} {y + 24}"/>'
            f'<text class="d-title" x="{x + 12}" y="{y + 17}">{title}</text>')


def mock_row(x, y, w, text, sub="", kind="d-box"):
    return (f'<rect class="{kind}" x="{x}" y="{y}" width="{w}" height="22" rx="4"/>'
            f'<text class="d-small" x="{x + 8}" y="{y + 15}">{text}</text>'
            + (f'<text class="d-small" x="{x + w - 8}" y="{y + 15}" text-anchor="end">{sub}</text>' if sub else ""))


def mock_button(x, y, w, text, kind="d-gold"):
    return (f'<rect class="{kind}" x="{x}" y="{y}" width="{w}" height="22" rx="5"/>'
            f'<text class="d-small" x="{x + w / 2}" y="{y + 15}" text-anchor="middle">{text}</text>')


k = "intake"
i_body = (
    box(10, 10, 150, 46, "Paste", "one piece or many", "d-box")
    + box(10, 66, 150, 46, "Files", ".docx .md .rtf .pdf …", "d-box")
    + box(10, 122, 150, 46, "Notebooks", "see Scanning", "d-box")
    + arrow(k + "1", 160, 33, 236, 70) + arrow(k + "1", 160, 89, 236, 89)
    + mock_window(238, 10, 250, 160, "Import files")
    + mock_row(250, 44, 226, "☑ Salt Hymn", "Poetry · 212")
    + mock_row(250, 72, 226, "☑ Night Ferry", "Poetry · 98")
    + mock_row(250, 100, 226, "☐ Low Water  (already there)", "", "d-box-key")
    + mock_button(386, 136, 90, "Import 2")
    + arrow(k + "1", 488, 89, 530, 89)
    + box(532, 56, 138, 66, "Entries", "one folder each", "d-gold")
)
page("5 - Bringing In Old Drafts.html", "Bringing In Old Drafts",
     "Paste, type or import the drafts you already have, a few or a few hundred.", k,
     "Loose pages dropping into a tray, framed in laurels", f'''
<p class="lede">Most writers arrive with drafts scattered across Word files, notes apps and old folders. Minerva can take them a piece at a time or all at once, shows you everything before it's created, and never changes the files you bring in.</p>

{figure(k + "1", 680, 180, i_body,
        "Every file is previewed first; anything that already has an entry is left unticked.",
        "Diagram: pasted text, files and notebooks go through the Import files preview into Entries")}

<h2>1. One piece: New entry</h2>
<p>Press <em>New entry</em> (on Home, or at the top of Entries). Give it a title, pick a category and, if you like, a project, then type or paste the text. Leave the title blank and Minerva uses the first line. It opens in the editor, ready to work on.</p>

<h2>2. Many pieces in one paste</h2>
<p>Paste a long document with the pieces separated by a line of <code>***</code>, <code>---</code> or <code>===</code>, or by three blank lines, and tick <em>Split into separate entries</em>. The preview lists each piece with its title, so you can check the cut before anything is made. One or two blank lines are treated as a stanza break and kept.</p>

<h2>3. Files: Import files</h2>
<p>Press <em>Import files</em> and choose files or a whole folder. Minerva reads Word (.docx), OpenDocument (.odt), Rich Text, Markdown (including Obsidian notes and their tags), web pages, text files and PDFs that have real text in them. From Google Docs, use <em>File &gt; Download &gt; Microsoft Word</em> first. Each file becomes a row with its title, category, length and anything that couldn't be kept (tables, images, footnotes). Untick what you don't want and press <em>Import</em>.</p>

<h2>4. From notes apps</h2>
<p>Import files also opens whole exports, one entry per note, with labels and notebooks carried over as tags and each note's date kept:</p>
<ul>
<li><strong>Evernote:</strong> select a notebook, choose <em>Export notebook</em>, save as .enex, and import that file.</li>
<li><strong>Google Keep:</strong> at <code>takeout.google.com</code>, choose only Keep and download the zip. Import the zip as it is; checklists come in as [ ] and [x] lines, and trashed notes are left out.</li>
<li><strong>Notion:</strong> <em>Export</em> from a page's ••• menu, as <em>Markdown &amp; CSV</em> with subpages included, and import the zip. Notion's long page IDs are dropped from the titles, and a subpage's parent becomes a tag.</li>
<li><strong>Obsidian, Bear and other Markdown apps:</strong> import the files or folder, or, to keep bringing in new notes as you write them, set the folder up under <em>Settings &gt; Synced folders</em>.</li>
<li><strong>Apple Notes:</strong> Apple has no export for all your notes at once. A handful can be pasted into New entry (put <code>***</code> between notes and tick <em>Split</em>). On a Mac, <em>File &gt; Export as PDF</em> saves one note at a time, and those PDFs import as text. For many notes, a free exporter app from the Mac App Store can save them all as Markdown files to import. On Windows, open the notes at <code>icloud.com</code> and paste them in.</li>
</ul>

<h2>5. Handwritten notebooks and scans</h2>
<p>Pages that are photos or scans go through the Scans page instead; see <em>Scanning and Sorting for Minerva</em>. A PDF with no text in it is pointed there too.</p>

<div class="howto-tip"><strong>Good to know:</strong> importing copies the words into your library; the original files are only read. If a title is already in use, the new entry gets a number, like "Low Water (2)", so nothing is overwritten.</div>
''')

k = "chapbook"
c_body = (
    mock_window(10, 10, 230, 170, "Tidewater  [TW]")
    + mock_row(22, 44, 206, "1  Low Water", "final")
    + mock_row(22, 70, 206, "2  Night Ferry", "")
    + mock_row(22, 96, 206, "3  Bell Buoy", "")
    + mock_row(22, 122, 206, "4  (placeholder) Ebb", "to write", "d-box-key")
    + f'<text class="d-small" x="22" y="166">2,140 of 6,000 words</text>'
    + arrow(k + "1", 240, 95, 316, 95, "Publish")
    + "".join(
        f'<rect class="{"d-gold" if i in (0, 5) else "d-box"}" x="{318 + i * 59}" y="55" width="53" height="80" rx="4"/>'
        f'<text class="d-small" x="{344 + i * 59}" y="99" text-anchor="middle">{t}</text>'
        for i, t in enumerate(["Cover", "Title", "Contents", "Pieces", "…", "Back"]))
)
page("6 - Putting a Chapbook Together.html", "Putting a Chapbook Together",
     "Gather pieces into a project, put them in order, and print a proof.", k,
     "A stapled booklet, framed in laurels", f'''
<p class="lede">A chapbook, collection or manuscript is a project in Minerva: a named group of entries with an order, a target length and a publish panel that lays the whole thing out as a book.</p>

{figure(k + "1", 680, 190, c_body,
        "A project's outline (with a placeholder for a piece still to write) becomes a proof, page by page.",
        "Diagram: a project outline of four pieces publishes to cover, title page, contents, pieces and back cover")}

<h2>1. Make the project</h2>
<p>On <em>Projects</em>, give the collection a name and a short tag of letters or numbers, like <code>TW</code>. The tag goes on each member's folder as <code>- [TW]</code>, so the grouping is visible in Explorer too.</p>

<h2>2. Add the pieces</h2>
<p>From the project page, search and add entries; or open any entry and pick the project in its <em>Project</em> panel. A piece can belong to one project, and any number of tags if it fits several ideas.</p>

<h2>3. Put them in order</h2>
<p>The project's outline is the running order. Drag pieces up and down, give each a short synopsis or status, and add placeholders for pieces you plan to write. Set a target length on the project page and Home shows how close you are.</p>

<h2>4. Settle the finals</h2>
<p>Open each piece, finish it, and press <em>Mark current draft as final</em> in its Share panel. The proof uses each piece's final draft when it has one, so later tinkering doesn't slip in by accident.</p>

<h2>5. Print a proof</h2>
<p>In the project's <em>Publish</em> panel choose a page size, fill in the subtitle, author and copyright line, add cover images if you have them, and export a PDF proof, a Word manuscript or plain text. Every export is a new file in the <code>Exports</code> folder.</p>

<h2>6. Dedication, acknowledgments and about the author</h2>
<p>Open <em>Dedication, epigraph, acknowledgments, about the author</em> in the Publish panel. Whatever you write goes in every format: the dedication and epigraph on their own pages before the contents, acknowledgments and a page about you after the last piece. Leave one empty and its page is left out. If you keep an acknowledgments list or a bio as a snippet (Submissions &gt; Snippets), pick it from the list beside the box; your name fills in from the Author line.</p>

<h2>7. Make an ebook</h2>
<p>Press <em>EPUB</em> for an ebook with the same pages, a clickable contents and the front cover, if you added one. Line breaks and indents in poems are kept, though an e-reader will still wrap a long line to fit its screen. The file opens in Apple Books, Kobo and Calibre, and is the format Amazon KDP, Draft2Digital and IngramSpark ask for when you upload an ebook.</p>

<div class="howto-tip"><strong>Good to know:</strong> a project can be submitted as a whole, too. Its own Submissions panel tracks where the manuscript has gone, separately from the single poems.</div>
''')

k = "track"
t_body = (
    mock_window(10, 10, 420, 170, "Submissions")
    + mock_row(22, 44, 396, "Night Ferry · The Lantern Review", "Submitted · 40 days")
    + mock_row(22, 70, 396, "Bell Buoy · The Lantern Review", "Submitted · 40 days")
    + mock_row(22, 96, 396, "Rope Work · Saltmarsh Quarterly", "Accepted", "d-gold")
    + mock_row(22, 122, 396, "Low Water · Saltmarsh Quarterly", "Declined")
    + f'<text class="d-small" x="22" y="166">2 waiting · 1 accepted of 2 replies · fees $6</text>'
    + arrow(k + "1", 430, 107, 488, 107, "Accepted")
    + box(490, 50, 180, 50, "Mark Published?", "where: Saltmarsh Q.", "d-box-key")
    + box(490, 112, 180, 50, "Withdraw elsewhere?", "for simultaneous subs", "d-box-key")
)
page("7 - Tracking Where a Poem Is Out.html", "Tracking Where a Poem Is Out",
     "Record every submission, see what's waiting, and clean up when one is taken.", k,
     "An envelope with a small clock, framed in laurels", f'''
<p class="lede">The Submissions tab is a log of every piece you've sent out: where, when, the fee, and what came back. It reminds you what's overdue and, when something is accepted, helps you tidy up the rest.</p>

{figure(k + "1", 680, 190, t_body,
        "When a piece is accepted, Minerva offers to mark it Published and to withdraw it from anywhere else it's waiting.",
        "Diagram: the Submissions list, with an accepted piece leading to two offers")}

<h2>1. Record a submission</h2>
<p>Open the entry and press <em>Add</em> in its Submissions panel, or use <em>Add submission</em> on the Submissions tab. Fill in where it went, the date, the fee and, if you know it, how long they usually take to reply. A submission can be <em>Planned</em> before you send it.</p>

<h2>2. Bring in the log you already keep</h2>
<p>If you've been tracking in a spreadsheet, save it as CSV and use <em>Import...</em> on the Submissions tab. Minerva guesses which column is which, matches each row to an entry by title, and shows every row before saving: ready, not found, unclear, or already recorded. Nothing is skipped without a reason.</p>

<h2>3. From Submittable or The Grinder</h2>
<p>Neither service lets other apps sign in on your behalf, but both let you download your history as a CSV file, and Minerva reads their files as they come:</p>
<ul>
<li><strong>Submittable:</strong> sign in, open the <em>Submissions</em> tab, and press the download button (a folder with an arrow).</li>
<li><strong>The Grinder:</strong> sign in, go to <em>my account</em> then <em>manage submissions</em>, tick every box under <em>by status</em>, press <em>show submissions</em>, then <em>generate export</em>.</li>
</ul>
<p>Choose the file with <em>Import...</em>; Minerva recognizes where it's from, and you can change that at the top of the preview. Their status words are understood ("In-Progress" is waiting, "Form Rejection" is declined), and the service's own word is kept in the notes. Download a fresh export now and then and import it again: submissions already in Minerva get their new status and response date instead of being added twice.</p>
<p><strong>From your email.</strong> To keep up without exporting again, bring in the emails instead: the "we received your submission" confirmations and the decisions that come through Submittable (and Moksha, Duosuma and Chill Subs). Put them in their own label or folder, export that as an .mbox file (Gmail: Google Takeout, choosing just that label; Apple Mail: <em>Mailbox &gt; Export Mailbox</em>; Thunderbird: the ImportExportTools add-on) or save the messages as .eml files, and choose the file or files in <em>Import...</em>. Minerva finds the venue, the piece (by its title) and what happened, combines a confirmation with its later decision, and shows the same preview: new records, updates to ones you already have, and emails whose piece it couldn't tell, which you can match by hand. Minerva doesn't sign in to your email.</p>
<p>Duotrope's terms of use say data downloaded from it is for your personal use and can't be used to create another database, so Minerva doesn't offer a Duotrope import.</p>

<p><strong>Cover letters and bios.</strong> <em>Snippets</em> on the Submissions tab keeps the text you paste again and again: a cover letter, a short and a long bio, acknowledgments. Write <code>{{venue}}</code> or <code>{{title}}</code> where the magazine's name or the piece's title goes, and <code>{{name}}</code> or <code>{{email}}</code> for your details from <em>Settings &gt; Manuscript details</em>. In a submission, pick a snippet and press <em>Copy</em> to paste it, filled in, into the magazine's form, or <em>Add to notes</em> to keep a copy of what you sent.</p>

<h2>4. Check what's waiting</h2>
<p>Tick <em>Still waiting</em> to see only open submissions. Ones past their expected reply date are marked overdue, and Home counts them. Filters for status, venue, category, project and dates narrow the list, and the tiles add up fees and your acceptance rate for what's shown.</p>

<h2>5. When a reply comes</h2>
<p>Change the status. An acceptance offers to mark the entry Published (with where) and to withdraw it from any other place it's still waiting, so simultaneous submissions don't get forgotten.</p>

<h2>6. Keep notes on venues</h2>
<p>The <em>Venues</em> view keeps reading periods, fees, typical response time, line limits and your own notes for each magazine or press, with the history of everything you've sent there. When a piece is longer than a venue's line limit, the submission form says so.</p>
<p><em>Coming up</em> on Home gathers what needs you in the next 30 days: deadlines for submissions you've planned, venues whose reading period opens or closes (written the way magazines write them, like "Sep to Nov, Feb to Apr"), submissions past the date a reply was expected, and pieces with a final draft that aren't out anywhere. Click any of them to open it.</p>

<h2>7. Find places to send it</h2>
<p>In a piece's or project's edit view, <em>Find places to send it</em> under Submissions starts with <em>Your venues</em>: the places you already keep notes on, best fit first. A venue whose line limit the piece is over drops to the bottom, a place that has taken your work before rises, and places you've already sent it to are listed apart. This part is free and never leaves your computer.</p>
<p><em>Suggest places</em> asks the AI you chose in Settings (under organizing and editing) for magazines, presses and contests that publish this kind of work. Open <em>What the AI is told</em> to see exactly what is sent. It's the kind of writing and its length, and the tags. You can add a line about what it's about, and the title if you tick it. The writing itself goes only if you tick <em>Let the AI read the writing itself</em>.</p>
<p>What the AI says about a venue is from its memory and can be out of date, so each suggestion is marked "not checked". <em>Check their website</em> reads the venue's own home page and its guidelines page. It shows the reading period, fee, response time, line limit, payment and how to submit, each with the sentence it came from and a link to the page. A detail goes in only when that sentence is really on their page. <em>Add to Venues</em> saves the venue, with what was checked and where it came from in its notes.</p>
<div class="howto-tip"><strong>Good to know:</strong> Minerva doesn't read submission directories such as Duotrope, Submittable or Chill Subs, whose terms don't allow automated reading. Use them in your browser, and add what you find with <em>Add venue</em>. Always read a venue's guidelines yourself before you send.</div>
<div class="howto-tip"><strong>Good to know:</strong> submissions live in Minerva's index, not in your text files, and follow an entry through renames and merges.</div>
''')

k = "manuscript"
m_body = (
    '<rect class="d-box" x="40" y="10" width="190" height="180" rx="4"/>'
    + '<text class="d-small" x="52" y="30">A. Writer</text><text class="d-small" x="52" y="44">12 Harbour Row</text>'
    + '<text class="d-small" x="52" y="58">writer@example.com</text><text class="d-small" x="218" y="30" text-anchor="end">14 lines</text>'
    + '<text class="d-title" x="135" y="90" text-anchor="middle">LOW WATER</text>'
    + "".join(f'<path class="d-tree" d="M58 {108 + i * 12} L{190 - (i % 3) * 18} {108 + i * 12}"/>' for i in range(6))
    + arrow(k + "1", 240, 100, 316, 100, "Export")
    + box(318, 30, 170, 56, "PDF or Word", "Standard manuscript", "d-box-key")
    + box(318, 112, 170, 56, "Settings", "Manuscript details", "d-box")
    + arrow(k + "1", 403, 112, 403, 88)
    + box(520, 60, 150, 70, "Exports folder", "ready to attach", "d-gold")
    + arrow(k + "1", 488, 58, 518, 80)
)
page("8 - Making a Standard Manuscript.html", "Making a Standard Manuscript",
     "The plain, submission-ready layout most magazines ask for, as a PDF or Word file.", k,
     "A manuscript page with a header block, framed in laurels", f'''
<p class="lede">Most magazines and contests ask for poems in standard manuscript format: your contact details at the top, the line count, the title in capitals and the poem in plain 12 pt type. Minerva lays it out for you.</p>

{figure(k + "1", 680, 200, m_body,
        "Your details go at the top left and the line count at the top right, on every piece.",
        "Diagram: a manuscript page, exported as PDF or Word using your manuscript details, saved in the Exports folder")}

<h2>1. Add your details once</h2>
<p>In <em>Settings &gt; Manuscript details</em>, fill in your name, address, email, phone and website. They're kept with Minerva's settings on this computer, never in your library.</p>

<h2>2. Export the piece</h2>
<p>Open the entry, and in its <em>Share</em> panel choose PDF or Word, then <em>Standard manuscript</em> as the layout, and press <em>Export</em>. If the entry has a final draft, you can choose it or the current one.</p>

<h2>3. Check it</h2>
<p>Press <em>Open</em> to look it over. Each piece starts on a new page; a stanza is kept together on one page when it fits, and later pages carry a running header with your surname, the title and the page number.</p>

<h2>4. Send it</h2>
<p>The file is in your library's <code>Exports</code> folder; <em>Show in folder</em> takes you there to attach it. Then record the submission (see <em>Tracking Where a Poem Is Out</em>).</p>

<div class="howto-tip"><strong>Good to know:</strong> a magazine with its own rules always wins. If they want something different, a Word template of your own (Settings &gt; Templates) can match it.</div>
''')


AS_OF = "October 2026"

k = "local"
l_body = (
    mock_window(10, 10, 300, 170, "This computer")
    + box(26, 50, 120, 56, "Minerva", "your library", "d-box")
    + arrow(k + "1", 146, 78, 176, 78)
    + box(178, 50, 118, 56, "Ollama", "a model you chose", "d-box-key")
    + f'<text class="d-small" x="26" y="140">Pages and drafts never leave the computer.</text>'
    + f'<text class="d-small" x="26" y="158">No account, no key, nothing to pay per use.</text>'
    + box(360, 30, 310, 56, "Scanning", "a vision model, e.g. qwen3-vl:8b (6 GB)", "d-gold")
    + box(360, 104, 310, 56, "Organizing and proofreading", "a text model, e.g. gemma3:12b (8 GB)", "d-gold")
    + arrow(k + "1", 310, 78, 358, 58) + arrow(k + "1", 310, 90, 358, 130)
)
page("9 - Running AI on Your Computer.html", "Running AI on Your Computer",
     "Free and private: set up a local model for scanning, organizing and proofreading.", k,
     "A computer with a shield on its screen, framed in laurels", f'''
<p class="lede">Minerva's AI features can use a model that runs on your own computer, through a free program called Ollama. Nothing you write is sent anywhere, there's no account or key, and it costs nothing per use. The trade-offs are speed, a large download, and accuracy that's a step behind the paid services, especially on handwriting.</p>

{figure(k + "1", 680, 190, l_body,
        "Everything stays on this computer. Pick one model for reading pages and one for working with text, or one that does both.",
        "Diagram: Minerva talks to Ollama on the same computer; a vision model for scanning and a text model for organizing")}

<h2>The easy way: let Minerva set it up</h2>
<p>Press <em>Set up free local AI</em>: it's in <em>Settings</em> under <em>Free and private AI</em>, on the AI steps of first-time setup, and on the panel that appears when you try an AI feature that isn't set up. Minerva looks at this computer's memory, graphics card and free disk space, suggests a model sized to it, and tells you the download size and roughly how fast it will be before anything starts. Then, when you say go, it:</p>
<ol>
<li>installs Ollama, if it isn't already (on Windows; Windows may ask you to allow the installer),</li>
<li>downloads the model,</li>
<li>reads a typed test page with it, so you can see it work and how long a page takes,</li>
<li>and turns on the AI features you ticked, using that model.</li>
</ol>
<p>You can close the window and keep writing while it downloads. If it's stopped partway, starting again picks up where it left off. If the test page comes back garbled, nothing is turned on until you say so. The rest of this guide is the same thing done by hand, for anyone who wants a different model.</p>

<h2>1. Check your computer</h2>
<p>A local model needs memory more than anything. With 16 GB of RAM (or a graphics card with 8 GB of its own), an 8 billion-parameter model runs comfortably. With 8 GB of RAM, use the smaller sizes noted below and expect it to be slow. A page that takes a paid service a few seconds can take a minute or more on a laptop without a graphics card. Plan on 5 to 10 GB of disk space per model.</p>

<h2>2. Install Ollama</h2>
<p>Download Ollama for Windows from <code>ollama.com</code> and install it. It runs quietly in the background and starts with Windows. Minerva talks to it at <code>localhost</code>, on this computer only.</p>

<h2>3. Pull a model</h2>
<p>Open a Command Prompt and type <code>ollama pull</code> followed by a model name. Good starting points as of {AS_OF}:</p>
<ul>
<li><strong>For scanning</strong> (reading pages), a vision model: <code>qwen3-vl:8b</code> (a 6 GB download), or <code>qwen3-vl:4b</code> (3 GB) on a smaller computer.</li>
<li><strong>For organizing and proofreading</strong>, a text model: <code>gemma3:12b</code> (8 GB), or <code>gemma3:4b</code> (3 GB). The vision models above can do this job too, if you'd rather download one model.</li>
</ul>
<p>New models come out often; the list at <code>ollama.com/library</code> shows which can read images.</p>

<h2>4. Point Minerva at it</h2>
<p>In <em>Settings</em>, under AI-assisted scanning or organizing, turn the feature on, choose <em>Local model (Ollama)</em>, and press <em>Test connection</em>. The models you've pulled appear in the Model list; pick one and press <em>Save</em>.</p>

<h2>5. Know what to expect</h2>
<p>Local models read typed and neatly printed pages well. Joined-up handwriting is still unreliable on local models, by most accounts, so plan on more proofreading, or use a paid service for a notebook you care about and keep the local model for organizing and proofreading. Cost estimates in Minerva show tokens but no price for a local model, because there isn't one.</p>

<div class="howto-tip"><strong>Good to know:</strong> you can mix: a local model for organizing (which sees all your drafts) and a paid service just for scanning, or the other way round. Each feature has its own setting.</div>
''')

k = "service"
v_body = (
    box(10, 60, 130, 60, "Minerva", "this computer", "d-box")
    + arrow(k + "1", 140, 90, 230, 90, "page or draft")
    + box(232, 50, 200, 80, "AI service", "Anthropic, OpenAI|or Google", "d-box-key")
    + arrow(k + "1", 432, 90, 512, 90, "per use")
    + box(514, 60, 156, 60, "Your account", "bill and spend limit", "d-gold")
    + f'<text class="d-small" x="232" y="152">Paid API use: not used for training by</text>'
    + f'<text class="d-small" x="232" y="168">default; kept up to 30 days, then deleted.</text>'
)
page("10 - Using an AI Service.html", "Using an AI Service",
     "What Anthropic, OpenAI and Google charge, how to cap it, and what happens to your writing.", k,
     "A cloud with a coin, framed in laurels", f'''
<p class="lede">An AI service is the quickest way to good results, and the best at handwriting. You pay the provider directly for what you use, usually pennies, and your writing goes to their servers to be read. Here is what that costs and what they do with it, checked against each provider's own pages in {AS_OF}.</p>

{figure(k + "1", 680, 180, v_body,
        "Minerva sends only what a job needs: a page image to read, or the draft you asked about.",
        "Diagram: Minerva sends a page or draft to an AI service, which bills your account per use")}

<h2>1. Pick a provider and get a key</h2>
<p>Minerva works with Anthropic (Claude), OpenAI and Google Gemini. Make an account on the provider's developer site (<code>console.anthropic.com</code>, <code>platform.openai.com</code> or <code>aistudio.google.com</code>), add a payment method, and create an API key. Paste it in <em>Settings</em>; Minerva keeps it in Windows Credential Manager, never in your library or anywhere else.</p>

<h2>2. What it costs</h2>
<p>Services charge per "token", roughly three-quarters of a word, with separate prices for what goes in and what comes back. Some rough figures at {AS_OF} list prices:</p>
<ul>
<li><strong>Reading one notebook page</strong>: 2 to 3 cents with Claude Sonnet 5.5, about 5 cents with Claude Opus 5.5, and about a tenth of a cent with Claude Haiku 5.5. A 200-page notebook comes to about $5 on Sonnet.</li>
<li><strong>Proofreading a one-page poem</strong>: a cent or two on Sonnet or a similar model.</li>
<li><strong>OpenAI and Google</strong> price their models in the same range, from a fraction of a cent to a few cents per page, depending on the model.</li>
</ul>
<p>Before any job that sends more than a page or two, Minerva shows an estimate and waits for you to say yes. Pages already read are kept, so stopping and restarting never pays twice.</p>

<h2>3. Set a spending limit</h2>
<p>Each provider's billing page lets you prepay a set amount or set a monthly limit, and email you as you approach it. Setting a limit of a few dollars before your first big scan is a good habit.</p>

<h2>4. What happens to your writing</h2>
<p>All three say that writing sent through their paid API is <strong>not used to train their models</strong> unless you opt in. Anthropic and OpenAI keep it for up to 30 days to check for abuse, then delete it. Google's free tier is different: its pricing page says content sent on the free tier is used to improve Google's products, so Minerva doesn't suggest free tiers for unpublished work.</p>

<h2>5. Choosing a model</h2>
<p>For handwriting, a provider's most capable model is worth the extra cents; for printed pages and for organizing, the mid-range model is plenty. You can set scanning and organizing separately, and change either at any time in <em>Settings</em>.</p>

<div class="howto-tip"><strong>Good to know:</strong> prices and policies change. Your provider's own pricing and privacy pages are the final word; if you'd rather nothing leave your computer at all, see <em>Running AI on Your Computer</em>.</div>
''')

k = "voice"
n_body = (
    box(10, 60, 130, 56, "Entry or project", "final drafts, in order", "d-box")
    + arrow(k + "1", 140, 80, 210, 50) + arrow(k + "1", 140, 96, 210, 126)
    + box(212, 22, 200, 56, "This computer's voices", "free · stays on the computer", "d-box-key")
    + box(212, 98, 200, 56, "ElevenLabs", "your key · credits per character", "d-box")
    + arrow(k + "1", 412, 50, 480, 80) + arrow(k + "1", 412, 126, 480, 96)
    + box(482, 60, 188, 56, "MP3 in Exports", "a chapter per piece", "d-gold")
)
page("11 - Narration and Video.html", "Narration and Video",
     "Turn an entry or a whole project into an audio file, and a narration into a video.", k,
     "A microphone, framed in laurels", f'''
<p class="lede">Hearing a poem read back is one of the best ways to catch what the eye skips, and a recording is something to share. Minerva can read an entry, or a whole chapbook, into an MP3: free with the voices already on your computer, or with ElevenLabs if you want a more natural voice and have an account.</p>

{figure(k + "1", 680, 176, n_body,
        "Each line is read in turn, with a short pause between lines and a longer one between stanzas.",
        "Diagram: an entry or project is read by this computer's voices or ElevenLabs into an MP3 in the Exports folder")}

<h2>1. Make a narration</h2>
<p>Open an entry and press <em>Narrate</em> in its Share panel, or open a project and press <em>Audio</em> in its Publish panel. Choose a voice and a pace, whether each title is read, and press <em>Make audio</em>. You can close the window and keep writing while it works. The file goes into the <code>Exports</code> folder like any other export, and a project uses each entry's final draft, as the proof does.</p>

<h2>2. One file or one per piece</h2>
<p>A project can become one file with a chapter for each piece, which audiobook and podcast players show as a list you can skip through, or a separate file for each piece. A pause separates one piece from the next.</p>

<h2>3. The free audio and video tool</h2>
<p>Minerva puts the recording together itself, as a WAV file. To make the smaller MP3 that phones, players and websites expect, it uses FFmpeg, a free tool used by most video and audio programs. The first time you choose MP3, Minerva offers to download it once (about 31 MB). It's kept in Minerva's own settings folder and nothing is installed elsewhere. You can always choose WAV instead.</p>

<h2>4. This computer's voices</h2>
<p>These are the voices <em>Read aloud</em> uses, built into Windows. They cost nothing and the writing never leaves your computer. Windows has more voices for more languages in <em>Settings &gt; Time &amp; language &gt; Speech</em>; after adding one, it appears in Minerva's list.</p>

<h2>5. ElevenLabs: cost and privacy</h2>
<p>ElevenLabs makes voices that sound much closer to a person reading. You need an account at <code>elevenlabs.io</code> and an API key from its developer settings; paste the key in the Narrate window and Minerva keeps it in Windows Credential Manager, like an AI key.</p>
<ul>
<li><strong>Cost.</strong> ElevenLabs plans come with a monthly allowance of credits, and the voice Minerva uses takes one credit per character, spaces included. A one-page poem is a few hundred credits; a 40-page chapbook is roughly 40,000 to 60,000. Before anything is sent, Minerva shows how many credits a narration will use and how many your account has left this month.</li>
<li><strong>Privacy.</strong> The text is sent to ElevenLabs to be read, and the audio is kept in your account's history there. Read ElevenLabs' privacy policy before narrating unpublished work, or use this computer's voices, which send nothing anywhere.</li>
<li><strong>Using the audio.</strong> ElevenLabs' plans differ on whether you can sell or publish what you make, and the free plan asks for credit to ElevenLabs. Check your plan's terms before posting or selling a recording.</li>
</ul>

<h2>6. Make a video</h2>
<p>A narration can become a video that shows the words a stanza at a time, with the line being read in bright white. Press <em>Video</em> next to <em>Narrate</em> or <em>Audio</em>, or <em>Make a video from it</em> when a narration finishes. Choose a shape (square for Instagram and Facebook posts, vertical for Reels, TikTok and Shorts, widescreen for YouTube) and a background: the project's front cover, a picture of your own, or plain navy. Pictures are darkened and softened so the words stay readable, and the preview shows a real screen before you start.</p>
<p>The video is made on this computer, with the same free audio and video tool, and saved as an MP4 in <code>Exports</code>. Nothing is uploaded anywhere.</p>

<div class="howto-tip"><strong>Good to know:</strong> the video follows the timing Minerva noted when the narration was made (kept in the hidden <code>.minerva</code> folder), so make the narration in Minerva first. Editing the poem afterwards doesn't change an existing narration or its video; narrate it again to pick up the changes.</div>
''')

print("wrote", sorted(os.listdir(OUT)))

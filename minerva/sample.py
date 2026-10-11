"""The sample library: made-up writing to explore Minerva with.

It lives in its own folder beside Minerva's settings, never inside the
writer's own library, and carries a marker file so Minerva only ever
starts over a folder it made itself. Every piece, venue and person in it
is invented.
"""

import datetime
import os
import shutil

from . import config as app_config
from . import core, notes, submissions, tags

MARKER = ".minerva-sample"
FOLDER_NAME = "Sample Library"

PROJECT = ("Tidewater", "TW", "A short chapbook of harbour poems, still being ordered.")

# (category, title, current text, older drafts, project?, tags, flags)
PIECES = [
    ("Poetry", "Low Water", """At low water the harbour shows its bones:
the chain, the bottle-green stones,
a boot that walked out years ago
and never thought to come back in.

The gulls take inventory.
Nothing is missing that was ever ours.
""", ["At low water the harbour shows its bones,\nthe chain, the stones.\n"], True, ["harbour"], {"to_edit": True}),
    ("Poetry", "Night Ferry", """The ferry hums across the dark
like someone who has forgotten the words
but kept the tune.

Lights on the far shore
lean down to the water
to see if they are still there.
""", [], True, ["harbour", "night"], {}),
    ("Poetry", "Bell Buoy", """It rings when no one asks it to,
it rings because the sea is moving
and that is reason enough.

I have known people like that.
I have tried to be one.
""", ["It rings when no one asks.\n", "It rings when no one asks it to,\nbecause the sea moves.\n"], True, ["harbour"], {"to_record": True}),
    ("Poetry", "Rope Work", """My grandmother could tie a bowline
with her eyes closed and her mind
on supper. The rabbit comes out of the hole,
round the tree, back down the hole.

I learned it from her hands, not her words.
Most of what I know came that way.
""", [], True, ["family"], {"published": True, "published_where": "Saltmarsh Quarterly"}),
    ("Poetry", "Fog Index", """Visibility: a hundred yards, then fifty,
then the length of my own arm.
The foghorn counts to two and starts again.
""", [], False, ["weather"], {}),
    ("Poetry", "Inventory of a Kitchen Drawer", """Three keys to doors that no longer exist.
A birthday candle, used once.
String, because you never know.
A recipe in handwriting
I would know anywhere.
""", [], False, ["family"], {"to_edit": True}),
    ("Fiction", "The Lighthouse Keeper's Ledger", """The ledger began in a neat hand: weather, ships, oil used. By the third winter the entries had grown longer. Wind from the north-east, the keeper wrote, and then, under it, a list of the things his wife had said that day, as if they too were conditions he was responsible for recording.

When the inspector came in spring he read the whole book standing up, and at the end he closed it carefully and said only that the oil figures were in order.
""", ["The ledger began in a neat hand: weather, ships, oil used.\n"], False, ["draft"], {"to_edit": True}),
    ("Fiction", "Second Tide", """Mara counted the boats the way her father had taught her, left to right, and came up one short. She counted again. Still one short. Out on the breakwater a figure in a yellow coat was waving, and it took her a long moment to understand that it was waving at her.
""", [], False, [], {}),
    ("Nonfiction", "Notes on Salt", """Salt was money once, and still is, in the way it holds things. Fish kept a winter. Roads kept clear. A wound kept clean, if you could stand it.

My uncle salted cod in the shed every November. The smell got into the wood and never left. I can still find it if I close my eyes.
""", [], False, ["essay"], {}),
    ("Misc", "Lines to Use Somewhere", """- the sea has no opinions, only habits
- a harbour is a promise the land makes to the water
- the gull's complaint, filed in triplicate
""", [], False, [], {}),
]

VENUES = [
    {"name": "The Lantern Review", "website": "", "reading_periods": "September to November",
     "response_days": 90, "max_lines": 40, "notes": "A made-up magazine for trying things out. Likes short lyric poems."},
    {"name": "Saltmarsh Quarterly", "website": "", "reading_periods": "Year round",
     "response_days": 60, "notes": "Also made up. Took Rope Work."},
]

# (entry title, venue, days ago submitted, status, fee, days ago decided)
SUBMISSIONS = [
    ("Rope Work", "Saltmarsh Quarterly", 120, "Accepted", 0, 70),
    ("Night Ferry", "The Lantern Review", 40, "Submitted", 3, None),
    ("Bell Buoy", "The Lantern Review", 40, "Submitted", 3, None),
    ("Low Water", "Saltmarsh Quarterly", 95, "Declined", 0, 30),
    ("The Lighthouse Keeper's Ledger", "The Lantern Review", 0, "Planned", 0, None),
]

NOTE = ("Low Water", "Try ending on the gulls. Read it aloud before deciding.")


def sample_path():
    return os.path.join(app_config.config_dir(), FOLDER_NAME)


def is_sample(root):
    return bool(root) and os.path.isfile(os.path.join(root, MARKER))


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_files(root):
    """Lay down the sample's folders and drafts."""
    for sub in core.DEFAULT_CATEGORIES + ["Projects", core.SOURCES_DIRNAME]:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    _write(os.path.join(root, MARKER), "This folder is Minerva's sample library. Everything in it is made up.\n")
    for category, title, text, older, in_project, _tags, _flags in PIECES:
        folder = f"{title} - [{PROJECT[1]}]" if in_project else title
        d = os.path.join(root, category, folder)
        for i, old in enumerate(older, start=1):
            _write(os.path.join(d, "Archive", f"{title} (draft {i}).txt"), old)
        _write(os.path.join(d, f"{title} [C].txt"), text)


def fill(conn):
    """Add the project, tags, flags, venues, submissions and a note once
    the files have been scanned in."""
    if not conn.execute("SELECT 1 FROM projects WHERE tag = ?", (PROJECT[1],)).fetchone():
        core.create_project(conn, *PROJECT)
    ids = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM entries")}
    for _cat, title, _text, _older, _p, entry_tags, flags in PIECES:
        if title not in ids:
            continue
        if entry_tags:
            tags.set_for_entry(conn, ids[title], entry_tags)
        if flags:
            core.update_flags(conn, ids[title], flags)
    submissions.ensure_table(conn)
    for v in VENUES:
        submissions.save_venue(conn, v)
    today = datetime.date.today()
    for title, venue, ago, status, fee, decided in SUBMISSIONS:
        if title not in ids:
            continue
        submissions.create(conn, {
            "entry_id": ids[title], "venue": venue, "status": status, "cost": fee,
            "submitted_on": (today - datetime.timedelta(days=ago)).isoformat() if status != "Planned" else None,
            "decided_on": (today - datetime.timedelta(days=decided)).isoformat() if decided is not None else None,
            "response_days": 90 if venue == "The Lantern Review" else 60,
        })
    if NOTE[0] in ids:
        notes.ensure_table(conn)
        notes.save(conn, ids[NOTE[0]], NOTE[1])


def create(start_over=False):
    """Make the sample library (or reuse it) and return its folder."""
    root = sample_path()
    if os.path.exists(root):
        if not is_sample(root):
            raise ValueError(f"{root} exists but isn't Minerva's sample library, so it's left alone.")
        if not start_over:
            return root, False
        shutil.rmtree(root)
    write_files(root)
    return root, True

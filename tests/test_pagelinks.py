import os

import pytest

from minerva import core, pagelinks, scanning

from conftest import write
from test_scanning import fake_model, make_pdf, notebook, post  # noqa: F401  (fixtures)

SEP = "=" * 60

# Three scans of a made-up journal. The first version's labels name the
# wrong page for entries 2 and 3; entry 3 runs from scan 1 into scan 2.
PAGES = {
    (1, 1): "The lantern swings above the quiet harbor and the gulls are sleeping on the pier tonight",
    (1, 2): "Grocery list: apples, bread, lamp oil, string for the kite we never fly",
    (1, 3): "Letter to Mara. I have been thinking about the winter we spent mending nets by the stove",
    (2, 1): "and how your hands knew the knots before your eyes did. Write back when the ice breaks.",
    (2, 2): "A sketch of the lighthouse with its door painted red",
}


def text_output(scan):
    parts = [f"SKETCHBOOK {scan} - TEXT TRANSCRIPTION", ""]
    for (s, p), text in sorted(PAGES.items()):
        if s == scan:
            parts += [SEP, f"SEGMENT {p} — Page {p}", "Date: none", SEP, text, ""]
    return "\n".join(parts)


def master(entries):
    out = ["SKETCHBOOK — MASTER TRANSCRIPT", ""]
    for num, label, body in entries:
        out += [SEP, f"ENTRY {num} ({label})", "Date: none", SEP, body, ""]
    return "\n".join(out)


@pytest.fixture
def sketchbook(library):
    """A source as the first version left it: PDFs, Text Output files and a
    Master whose page labels are partly wrong."""
    core.configure(library)
    core.scan_and_sync()
    src = os.path.join(library, "Sources", "Sketchbook")
    make_pdf(os.path.join(src, "Scans", "Sketchbook 1.pdf"), 3)
    make_pdf(os.path.join(src, "Scans", "Sketchbook 2.pdf"), 2)
    for scan in (1, 2):
        write(os.path.join(src, "Text Output", f"Sketchbook {scan} - Text.txt"), text_output(scan))
    write(os.path.join(src, "Sketchbook - Master.txt"), master([
        (1, "Scan 1, Segment 1", PAGES[(1, 1)]),
        (2, "Scan 1, Segment 3", PAGES[(1, 2)]),
        (3, "Scan 1, Segment 2", PAGES[(1, 3)] + "\n" + PAGES[(2, 1)]),
        (4, "Scan 2, Segment 2", "A doodle of a whale, no words."),
    ]))
    return library


def test_parse_text_output_gives_one_text_per_page():
    pages = pagelinks.parse_text_output(text_output(1))
    assert sorted(pages) == [1, 2, 3]
    assert "Grocery list" in pages[2] and "Letter to Mara" not in pages[2]


def test_entries_are_linked_by_their_text_not_their_label(sketchbook):
    entries = {e["num"]: e for e in scanning.read_master("Sketchbook")["entries"]}
    assert entries[1]["pages"] == [[1, 1]]
    assert entries[2]["pages"] == [[1, 2]]
    assert entries[3]["pages"] == [[1, 3], [2, 1]]
    assert entries[3]["link"] == {"method": "matched", "note": None}
    # no text to match: the label's page is used, and the page says so
    assert entries[4]["pages"] == [[2, 2]] and entries[4]["link"]["method"] == "label"
    assert "label" in entries[4]["link"]["note"]
    assert scanning.read_master("Sketchbook")["scan_pages"] == {1: 3, 2: 2}


def test_a_filed_entry_finds_all_its_pages(sketchbook):
    write(os.path.join(sketchbook, "Nonfiction", "Letter to Mara", "Letter to Mara [J].txt"),
          "Source: Sketchbook Journal\nSource: Entry 3 (Scan 1, Segment 2)\nLetter to Mara\n"
          "Category: Nonfiction\nDate: none\n" + SEP + "\n\n" + PAGES[(1, 3)] + "\n")
    core.scan_and_sync()
    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE folder_name = 'Letter to Mara'").fetchone()
    conn.close()
    scan = core.find_journal_scan_for_entry(row)
    assert scan["available"] and (scan["scan_num"], scan["page"]) == (1, 3)
    assert [(p["filename"], p["page"]) for p in scan["pages"]] == [("Sketchbook 1.pdf", 3), ("Sketchbook 2.pdf", 1)]
    assert scan["pdf_name"] == "Sketchbook 1.pdf"


def test_pages_chosen_by_hand_survive_matching_again(client, sketchbook):
    scanning.read_master("Sketchbook")
    r = post(client, "/api/scans/Sketchbook/master/4/pages", {"pages": [[2, 2], [1, 1]]})
    assert r.status_code == 200 and r.get_json()["pages"] == [[2, 2], [1, 1]]
    bad = post(client, "/api/scans/Sketchbook/master/4/pages", {"pages": [[2, 9]]})
    assert bad.status_code == 400 and "no page 9" in bad.get_json()["error"]
    assert post(client, "/api/scans/Sketchbook/master/4/pages", {"pages": []}).status_code == 400

    r = post(client, "/api/scans/Sketchbook/rematch")
    assert r.get_json() == {"entries": 4, "methods": {"matched": 3, "manual": 1}}
    entries = {e["num"]: e for e in scanning.read_master("Sketchbook")["entries"]}
    assert entries[4]["pages"] == [[2, 2], [1, 1]] and entries[4]["link"]["note"] is None


def test_new_masters_record_the_pages_they_were_built_from(notebook, fake_model):
    # page 1 of scan 2 continues the last page of scan 1
    make_pdf(os.path.join(notebook, "Sources", "Green Notebook", "Scans", "Green Notebook 2.pdf"), 1)
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    cache = scanning._page_cache_path("Green Notebook", 1, 1)
    scanning.transcribe_scan("Green Notebook", 2, "anthropic", "m", "k")
    # the fake model reads scan 2's only page like page 1 ("Harbor Song");
    # make it a continuation instead
    import json
    p2 = scanning._page_cache_path("Green Notebook", 2, 1)
    data = json.load(open(p2, encoding="utf-8"))
    data.update({"continues": True, "title": "", "text": "and the tide goes out."})
    json.dump(data, open(p2, "w", encoding="utf-8"))
    assert os.path.isfile(cache)

    scanning.build_master("Green Notebook")
    entries = scanning.read_master("Green Notebook")["entries"]
    assert [e["pages"] for e in entries] == [[[1, 1], [1, 2]], [[1, 3], [2, 1]]]
    assert entries[1]["label"] == "Scan 1, Segment 3 to Scan 2, Segment 1"
    assert all(e["link"]["method"] == "transcribed" for e in entries)
    assert scanning.scan_status("Green Notebook")[1]["in_master"] is True


def test_label_pages_reads_ranges():
    assert pagelinks.label_pages("Scan 3, Segments 4-6 — merged", [1, 2, 3]) == [[3, 4], [3, 5], [3, 6]]
    assert pagelinks.label_pages("Page 7 — inside cover", [1]) == [[1, 7]]
    assert pagelinks.label_pages("Page 7", [1, 2]) == []


DRAWING = "[A pen drawing of a lighthouse on a rock, its door painted red, with three gulls overhead. No accompanying text.]"


def test_drawings_and_diagrams_match_on_their_descriptions():
    pages = [(1, 1, "The lantern swings above the quiet harbor and the gulls are sleeping"),
             (1, 2, "Date: none\n" + DRAWING + "\n\nNote: a drawing, no prose."),
             (1, 3, "[Diagram: three circles labeled Body, Mind and Soul joined by arrows.]\nBalance first")]
    entries = [{"num": 1, "label": "Scan 1, Segment 3", "body": DRAWING},
               {"num": 2, "label": "Scan 1, Segment 1",
                "body": "Balance first\n\n[Diagram: three circles labeled Body, Mind and Soul joined by arrows.]"},
               {"num": 3, "label": "Scan 1, Segment 2", "body": "The lantern swings above the quiet harbor [uncertain]"}]
    links = pagelinks.match_entries("Sketchbook", entries, [1], pages=pages)
    assert links[1] == {"pages": [[1, 2]], "method": "matched", "confidence": 1.0}
    assert links[2]["pages"] == [[1, 3]] and links[2]["confidence"] >= 0.6
    # prose still matches on its words alone, ignoring transcriber's notes
    assert links[3]["pages"] == [[1, 1]] and links[3]["confidence"] == 1.0


def test_guessed_links_from_an_older_matcher_are_redone_once(sketchbook):
    pagelinks.save("Sketchbook", {4: {"pages": [[1, 1]], "method": "label", "confidence": 0.0},
                                  1: {"pages": [[2, 2]], "method": "manual", "confidence": 1.0}})
    entries = scanning.parse_master(scanning._read(scanning.master_path("Sketchbook")))["entries"]
    links = pagelinks.links_for("Sketchbook", entries, [1, 2])
    assert links[4]["pages"] == [[2, 2]]          # the label's own page, worked out afresh
    assert links[1]["pages"] == [[2, 2]]          # chosen by hand: untouched
    settings = core.read_library_settings(core.ARCHIVE_ROOT)
    assert settings["page_match_versions"]["Sketchbook"] == pagelinks.MATCH_VERSION
    # once upgraded, a stored guess is left alone
    pagelinks.save("Sketchbook", {4: {"pages": [[1, 1]], "method": "label", "confidence": 0.0}})
    assert pagelinks.links_for("Sketchbook", entries, [1, 2])[4]["pages"] == [[1, 1]]

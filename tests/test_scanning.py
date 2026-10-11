import os
import time

import pytest
from PIL import Image

from minerva import ai, config as app_config, core, organizing, scanning, secrets_store, server

from conftest import sha, write

REPLIES = {
    1: "DATE: 3/4/21\nLOCATION: none\nTITLE: Harbor Song\nCONTINUES: no\nTEXT:\nThe boats come home\nat [dusk]\nUNCERTAIN:\n\"dusk\" could be \"dust\"",
    2: "DATE: none\nLOCATION: none\nTITLE: none\nCONTINUES: yes\nTEXT:\nand the nets dry slow.\nUNCERTAIN:\nnone",
    3: "DATE: 3/5/21\nLOCATION: Pier 9\nTITLE: none\nCONTINUES: no\nTEXT:\nWind from the east today.\nUNCERTAIN: none",
}


def make_pdf(path, pages):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    imgs = [Image.new("RGB", (400, 600), (255, 255, 255 - 40 * i)) for i in range(pages)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:])


@pytest.fixture
def notebook(library):
    """A source with one real three-page PDF and no Master yet."""
    core.configure(library)
    core.scan_and_sync()
    make_pdf(os.path.join(library, "Sources", "Green Notebook", "Scans", "Green Notebook 1.pdf"), 3)
    return library


@pytest.fixture
def fake_model(monkeypatch):
    calls = []

    def complete(provider, model, key, system, prompt, images=(), max_tokens=8000, usage=None):
        calls.append({"provider": provider, "model": model, "key": key, "prompt": prompt, "images": images})
        page = int(prompt.split("This is page ")[1].split(" ")[0])
        if usage is not None:
            usage.update({"input": 3000 + page, "output": 400})
        return REPLIES[page]

    monkeypatch.setattr(ai, "complete", complete)
    return calls


def test_parse_transcription_reads_tagged_reply():
    r = scanning.parse_transcription(REPLIES[1])
    assert r == {"date": "3/4/21", "location": "", "title": "Harbor Song", "continues": False,
                 "text": "The boats come home\nat [dusk]", "uncertain": '"dusk" could be "dust"'}
    assert scanning.parse_transcription("```\n" + REPLIES[2] + "\n```")["continues"] is True


def test_parse_transcription_keeps_untagged_reply_as_text():
    r = scanning.parse_transcription("Just the words\non a page")
    assert r["text"] == "Just the words\non a page"


def test_list_scans_numbers_like_master_labels(notebook):
    folder = os.path.join(notebook, "Sources", "Green Notebook", "Scans")
    write(os.path.join(folder, "photo.jpg"))
    nums = {s["filename"]: s["num"] for s in scanning.list_scans("Green Notebook")}
    assert nums == {"Green Notebook 1.pdf": 1, "photo.jpg": 2}


def test_source_names_cannot_escape_the_scans_folder(notebook):
    with pytest.raises(scanning.ScanError):
        scanning.source_dir("..")
    with pytest.raises(scanning.ScanError):
        scanning.source_dir("../Poetry")


def test_render_page_gives_a_jpeg(notebook):
    scan = scanning.get_scan("Green Notebook", 1)
    assert scanning.page_count(scan) == 3
    assert scanning.render_page(scan, 2)[:2] == b"\xff\xd8"


def test_transcribe_then_build_master(notebook, fake_model):
    out = scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    assert out == "Green Notebook 1 - Text.txt"
    assert len(fake_model) == 3 and fake_model[0]["images"][0][0] == "image/jpeg"
    # page 2 gets the end of page 1 to judge whether it continues
    assert "at [dusk]" in fake_model[1]["prompt"]

    text_out = open(os.path.join(notebook, "Sources", "Green Notebook", "Text Output", out), encoding="utf-8").read()
    assert "SEGMENT 2" in text_out and "Uncertain words: \"dusk\"" in text_out

    # a second run costs nothing: every page is cached
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    assert len(fake_model) == 3

    r = scanning.build_master("Green Notebook")
    assert r == {"created": True, "added": 2, "scans": [1]}
    master = scanning.read_master("Green Notebook")
    first, second = master["entries"]
    assert (first["num"], first["title"], first["date"], first["label"]) == (1, "Harbor Song", "3/4/21", "Scan 1, Segments 1-2")
    assert first["body"] == "The boats come home\nat [dusk]\n\nand the nets dry slow."
    assert first["notes"] == ['Entry 1: "dusk" could be "dust"']
    assert (second["location"], second["page"]) == ("Pier 9", 3)

    with pytest.raises(scanning.ScanError):
        scanning.build_master("Green Notebook")


def test_adding_a_scan_to_an_existing_master(notebook, fake_model):
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    scanning.build_master("Green Notebook")
    make_pdf(os.path.join(notebook, "Sources", "Green Notebook", "Scans", "Green Notebook 2.pdf"), 1)
    scanning.transcribe_scan("Green Notebook", 2, "anthropic", "m", "k")
    before = open(scanning.master_path("Green Notebook"), encoding="utf-8").read()

    assert scanning.build_master("Green Notebook")["added"] == 1
    entries = scanning.read_master("Green Notebook")["entries"]
    assert [e["num"] for e in entries] == [1, 2, 3]
    assert entries[2]["label"] == "Scan 2, Segment 1" and entries[2]["title"] == "Harbor Song"
    backups = os.listdir(os.path.join(notebook, ".minerva", "backups"))
    assert len(backups) == 1
    assert open(os.path.join(notebook, ".minerva", "backups", backups[0]), encoding="utf-8").read() == before


def test_parse_master_handles_first_version_layouts():
    text = (
        "HEADER\n" + "=" * 60 + "\nENTRY 1 (Scan 1, Segment 1) (torn page; partly legible)\n" + "=" * 60 +
        "\nDate: 1/14/20\nTime: 12:30pm\n" + "=" * 60 + "\nFirst body\n\n" + "=" * 60 +
        "\nENTRY 2 (Page 2) — Second\nDate: none\n" + "=" * 60 + "\nSecond body\n\n" + "=" * 60 +
        "\nCLOSING SUMMARY\n" + "=" * 60 + "\nnot an entry\n\n" + "=" * 60 +
        "\nOCR AMBIGUITY & CONTEXT NOTES\n" + "=" * 60 + "\nEntries 1-2: smudges\n")
    p = scanning.parse_master(text)
    a, b = p["entries"]
    assert (a["date"], a["body"], a["title"]) == ("1/14/20", "First body", "(torn page; partly legible)")
    assert (b["title"], b["body"], b["scan"], b["page"]) == ("Second", "Second body", None, 2)
    assert p["notes"] == {1: ["Entries 1-2: smudges"], 2: ["Entries 1-2: smudges"]}


def test_proofreading_saves_one_entry_and_guards_against_stale_edits(notebook, fake_model):
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    scanning.build_master("Green Notebook")
    m = scanning.read_master("Green Notebook")
    v2 = scanning.save_master_entry("Green Notebook", 2, m["version"], "Wind from the east all day.",
                                    title="East Wind", date="5 March 2021")
    entries = scanning.read_master("Green Notebook")["entries"]
    assert entries[0]["body"] == m["entries"][0]["body"]
    assert (entries[1]["body"], entries[1]["title"], entries[1]["date"]) == (
        "Wind from the east all day.", "East Wind", "5 March 2021")
    with pytest.raises(scanning.ScanError):
        scanning.save_master_entry("Green Notebook", 1, m["version"], "stale")
    with pytest.raises(scanning.ScanError):
        scanning.save_master_entry("Green Notebook", 1, v2, "ENTRY 9 (Scan 1, Segment 1)\nsneaky")


def test_filing_creates_journal_entries_linked_to_their_page(notebook, fake_model):
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    scanning.build_master("Green Notebook")
    before = sha(os.path.join(notebook, "Poetry", "Morning Tide", "Morning Tide [C].txt"))

    r = scanning.file_entries("Green Notebook", [
        {"num": 1, "title": "Harbor Song", "category": "Poetry"},
        {"num": 2, "title": "Morning Tide", "category": "Poetry"},  # name already taken
    ])
    assert [c["title"] for c in r["created"]] == ["Harbor Song", "Morning Tide (2)"]
    assert sha(os.path.join(notebook, "Poetry", "Morning Tide", "Morning Tide [C].txt")) == before

    draft = open(os.path.join(notebook, "Poetry", "Harbor Song", "Harbor Song [J].txt"), encoding="utf-8").read()
    assert draft.startswith("Source: Green Notebook Journal\nSource: Entry 1 (Scan 1, Segments 1-2)\nHarbor Song\n")

    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE folder_name = 'Harbor Song'").fetchone()
    conn.close()
    assert (row["source_journal"], row["source_entry_num"], row["draft_tag"], row["has_journal_header"]) == (
        "Green Notebook", 1, "J", 1)
    scan = core.find_journal_scan_for_entry(row)
    assert scan["available"] and (scan["scan_num"], scan["page"]) == (1, 1)

    again = scanning.file_entries("Green Notebook", [{"num": 1, "title": "x", "category": "Poetry"}])
    assert again["created"] == [] and again["skipped"][0]["reason"] == "already filed"
    assert scanning.list_sources()["sources"][-1]["filed"] == 2


def test_filing_can_join_a_run_of_entries_into_one(notebook, fake_model):
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k")
    scanning.build_master("Green Notebook")  # entry 1 is pages 1-2, entry 2 is page 3
    r = scanning.file_entries("Green Notebook", [
        {"num": 1, "through": 2, "title": "Harbor Days", "category": "Nonfiction"},
        {"num": 2, "title": "overlaps the join", "category": "Poetry"},
        {"num": 2, "through": 5, "title": "x", "category": "Poetry"}])
    assert [(c["num"], c["through"]) for c in r["created"]] == [(1, 2)]
    assert [s["reason"] for s in r["skipped"]] == ["already filed", "entries 2-5 aren't all in the Master"]
    draft = open(os.path.join(notebook, "Nonfiction", "Harbor Days", "Harbor Days [J].txt"), encoding="utf-8").read()
    assert draft.startswith("Source: Green Notebook Journal\n"
                            "Source: Entries 1-2 (Scan 1, Segments 1-2 to Scan 1, Segment 3)\nHarbor Days\n")
    assert "and the nets dry slow.\n\nWind from the east today." in draft

    master = scanning.read_master("Green Notebook")
    assert [e["filed"]["title"] for e in master["entries"]] == ["Harbor Days", "Harbor Days"]
    assert master["entries"][0]["filed"]["joined"] == [1, 2]
    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE folder_name = 'Harbor Days'").fetchone()
    conn.close()
    assert (row["source_entry_num"], row["source_entry_last"]) == (1, 2)
    scan = core.find_journal_scan_for_entry(row)
    assert [(p["scan"], p["page"]) for p in scan["pages"]] == [(1, 1), (1, 2), (1, 3)]
    assert scan["excerpt"].endswith("Wind from the east today.")
    assert core.parse_journal_source("Source: Old Journal\nSource entries: Entries 120-123\n====") == ("Old", 120, 123)

def test_word_diff_marks_only_changed_words():
    ops = organizing.word_diff("The tied comes in\n", "The tide comes in\n")
    assert ["del", "tied"] in ops and ["ins", "tide"] in ops
    assert "".join(t for op, t in ops if op != "del") == "The tide comes in\n"


# ---- through the server -------------------------------------------------

def _enable(feature, provider="anthropic"):
    cfg = app_config.load()
    cfg["ai"][feature] = {"enabled": True, "provider": provider, "model": "m"}
    app_config.save(cfg)
    secrets_store.set_key(provider, "sk-test")


def post(client, path, body=None):
    return client.post(path, json=body or {}, headers={"X-Minerva-Token": server.SESSION_TOKEN})


def test_ai_routes_explain_when_a_feature_is_off(client, notebook):
    r = post(client, "/api/scans/Green Notebook/transcribe", {"scans": [1]})
    assert r.status_code == 400 and r.get_json()["ai_off"]
    assert r.get_json()["feature"] == "scanning"
    r = post(client, "/api/entries/1/ai/suggest")
    assert r.get_json()["ai_off"] and r.get_json()["feature"] == "organizing"
    assert "turned off" in r.get_json()["error"]
    status = client.get("/api/ai/status").get_json()
    assert status["scanning"]["ready"] is False


def test_transcribe_job_runs_in_the_background(client, notebook, fake_model):
    _enable("scanning")
    r = post(client, "/api/scans/Green Notebook/transcribe", {"scans": [1]})
    assert r.status_code == 200
    job_id = r.get_json()["id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert fake_model[0]["key"] == "sk-test"
    assert post(client, "/api/scans/Green Notebook/master").get_json()["added"] == 2
    page = client.get("/api/scans/Green Notebook/page/1/1.jpg")
    assert page.status_code == 200 and page.mimetype == "image/jpeg"
    sources = client.get("/api/scans").get_json()["sources"]
    assert {"name": "Green Notebook", "entries": 2}.items() <= [s for s in sources if s["name"] == "Green Notebook"][0].items()


def test_proofread_route_returns_a_diff(client, notebook, monkeypatch):
    _enable("organizing")
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "The tide comes in\nand the gulls argue.\n")
    conn = core.get_conn()
    eid = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    conn.close()
    r = post(client, f"/api/entries/{eid}/ai/proofread", {"content": "The tied comes in\nand the gulls argue.\n"})
    data = r.get_json()
    assert data["text"] == "The tide comes in\nand the gulls argue.\n"
    assert ["ins", "tide"] in data["changes"]


def test_suggest_route_keeps_answers_inside_known_choices(client, notebook, monkeypatch):
    _enable("organizing")
    monkeypatch.setattr(ai, "complete", lambda *a, **k:
                        'Sure: {"title": "Gulls", "category": "Recipes", "project": "NOPE", "reason": "short"}')
    conn = core.get_conn()
    eid = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    conn.close()
    data = post(client, f"/api/entries/{eid}/ai/suggest").get_json()
    assert data == {"title": "Gulls", "category": "Poetry", "project": None, "reason": "short"}


def test_estimate_counts_unread_pages_and_prices_known_models(notebook, fake_model):
    est = scanning.estimate("Green Notebook", [1], "anthropic", "claude-opus-5-5")
    # three 400x600 pt pages, sent at 1333x2000
    assert est["pages"] == 3 and est["measured_pages"] == 0
    assert est["input_tokens"] == 3 * (scanning._image_tokens(1333.3, 2000, "claude-opus-5-5") + scanning.PROMPT_TOKENS)
    assert est["output_tokens"] == 3 * scanning.OUTPUT_TOKENS
    assert est["cost"] == round((est["input_tokens"] * 4 + est["output_tokens"] * 20) / 1e6, 2)
    assert not est["confirm"]
    # Haiku reads a smaller image, so the same pages cost fewer tokens
    assert scanning.estimate("Green Notebook", [1], "anthropic", "claude-haiku-4-5")["input_tokens"] < est["input_tokens"]
    # other providers get counts but no price
    assert scanning.estimate("Green Notebook", [1], "ollama", "llava")["cost"] is None

    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "claude-opus-5-5", "k")
    assert scanning.cached_pages("Green Notebook", 1)[2]["usage"] == {"input": 3002, "output": 400}
    assert scanning.estimate("Green Notebook", [1], "anthropic", "claude-opus-5-5")["pages"] == 0
    # once pages have been read, the estimate uses what the provider reported
    redo = scanning.estimate("Green Notebook", [1], "anthropic", "claude-opus-5-5", redo=True)
    assert (redo["pages"], redo["measured_pages"]) == (3, 3)
    assert (redo["input_tokens"], redo["output_tokens"]) == (9006, 1200)


def test_estimate_asks_before_a_big_job(notebook, monkeypatch):
    monkeypatch.setattr(scanning, "CONFIRM_DOLLARS", 0.01)
    monkeypatch.setattr(scanning, "CONFIRM_PAGES", 3)
    assert scanning.estimate("Green Notebook", [1], "anthropic", "claude-opus-5-5")["confirm"]
    assert scanning.estimate("Green Notebook", [1], "gemini", "x")["confirm"]
    monkeypatch.setattr(scanning, "CONFIRM_PAGES", 4)
    assert not scanning.estimate("Green Notebook", [1], "gemini", "x")["confirm"]


def test_estimate_route(client, notebook):
    _enable("scanning")
    r = post(client, "/api/scans/Green Notebook/estimate", {"scans": [1]})
    assert r.status_code == 200 and r.get_json()["pages"] == 3
    assert post(client, "/api/scans/Green Notebook/estimate", {"scans": [9]}).status_code == 400

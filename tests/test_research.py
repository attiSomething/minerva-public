import json

import pytest

from minerva import ai, core, research, submissions, tags

PAGE = """<html><head><title>The Harbor Review</title><style>.x{}</style><script>var a=1</script></head>
<body><nav><a href="/about">About</a> <a href="/submission-guidelines">Submit</a> <a href="https://elsewhere.org/submit">Other</a>
<a href="mailto:eds@harbor.example">Email</a></nav><p>A journal of poems about the sea.</p></body></html>"""
GUIDE = """<html><body><h1>Guidelines</h1><p>We read from September 1 to November 30 each year.</p>
<p>Send up to 5 poems, no more than 40 lines each.</p><p>There is no reading fee &mdash; it&rsquo;s free.</p>
<p>We usually respond within 90 days.</p></body></html>"""


@pytest.fixture
def lib(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    tide = conn.execute("SELECT id FROM entries WHERE title='Morning Tide'").fetchone()["id"]
    tags.set_for_entry(conn, tide, ["sea"])
    submissions.ensure_table(conn)
    submissions.create(conn, {"entry_id": tide, "piece_title": "Morning Tide", "venue": "Gull Quarterly", "submitted_on": "2026-09-01"})
    submissions.save_venue(conn, {"name": "Tiny Lines", "max_lines": 1})
    submissions.save_venue(conn, {"name": "Open Sea", "cost": 0, "reading_periods": "all year"})
    conn.commit()
    yield conn, tide
    conn.close()


def test_fit_and_own_venues(lib):
    conn, tide = lib
    f = research.fit(conn, entry_id=tide)
    assert f["kind"] == "poetry" and f["lines"] == 2 and f["tags"] == ["sea"]
    own = research.own_venues(conn, f)
    assert [v["name"] for v in own] == ["Open Sea", "Tiny Lines", "Gull Quarterly"]
    assert own[-1]["sent"] == "Submitted" and "Takes up to 1 lines" in own[1]["reasons"][0]
    b = research.brief(f)
    assert "poetry" in b and "Morning Tide" not in b and "tide comes in" not in b
    assert "Title: Morning Tide" in research.brief(f, include_title=True)
    assert "the gulls argue" in research.brief(f, text=research.piece_text(conn, f))


def test_suggest_sends_only_the_brief(lib, monkeypatch):
    conn, tide = lib
    f = research.fit(conn, entry_id=tide)
    sent = {}

    def fake(provider, model, key, system, prompt, images=(), max_tokens=0, usage=None):
        sent["prompt"] = prompt
        return "```json\n" + json.dumps([
            {"name": "The Harbor Review", "website": "harbor.example", "type": "magazine", "why": "Sea poems.", "fee": "free"},
            {"name": "Open Sea", "website": "opensea.example"},
            {"name": "Directory", "website": "https://duotrope.com/listing/1"},
            {"nonsense": True}]) + "\n```"
    monkeypatch.setattr(ai, "complete", fake)
    out = research.suggest({"provider": "x", "model": "m"}, "k", f, about="tides", avoid=["Open Sea"])
    assert [v["name"] for v in out] == ["The Harbor Review", "Directory"]
    assert out[0]["website"] == "https://harbor.example/" and out[0]["remembered"]["fee"] == "free"
    assert out[1]["directory"] and out[1]["website"] == ""
    assert "tides" in sent["prompt"] and "Open Sea" in sent["prompt"] and "gulls" not in sent["prompt"]


def test_page_text_and_guideline_links():
    text, links = research.page_text(PAGE)
    assert "poems about the sea" in text and "var a" not in text and ".x{}" not in text
    assert research._guideline_links("https://harbor.example/", links) == ["https://harbor.example/submission-guidelines"]


def test_check_keeps_only_quoted_facts(monkeypatch):
    pages = {"https://harbor.example/": PAGE, "https://harbor.example/submission-guidelines": GUIDE}
    monkeypatch.setattr(research, "_fetch", lambda url: (url, pages[url]))
    seen = {}

    def fake(provider, model, key, system, prompt, images=(), max_tokens=0, usage=None):
        seen["prompt"] = prompt
        return json.dumps({
            "reading_periods": {"value": "September 1 to November 30", "quote": "We read from September 1 to November 30 each year.", "page": 2},
            "fee": {"amount": 0, "currency": "$", "value": "free", "quote": "There is no reading fee — it’s free.", "page": 2},
            "response_days": {"value": "90", "quote": "We usually respond within 90 days", "page": 1},
            "line_limit": {"value": 40, "quote": "no more than 40 lines each", "page": 2},
            "pays": {"value": "$500 a poem", "quote": "We pay $500 per poem.", "page": 2},
            "simultaneous": {"value": "yes", "quote": ""}})
    monkeypatch.setattr(ai, "complete", fake)
    r = research.check({"provider": "x", "model": "m"}, "k", "The Harbor Review", "harbor.example")
    assert r["pages"] == ["https://harbor.example/", "https://harbor.example/submission-guidelines"]
    assert set(r["facts"]) == {"reading_periods", "fee", "response_days", "line_limit"}
    assert r["facts"]["response_days"]["value"] == 90 and r["facts"]["response_days"]["url"].endswith("guidelines")
    assert r["facts"]["fee"]["amount"] == 0.0
    assert "pays" in r["dropped"]  # the model made it up; it's not on the page
    assert "[Page 2: https://harbor.example/submission-guidelines]" in seen["prompt"]


def test_never_reads_private_addresses_or_directories():
    for host in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "localhost"):
        with pytest.raises(research.ResearchError):
            research._public_host(host)
    with pytest.raises(research.ResearchError, match="directory"):
        research._fetch("https://www.duotrope.com/listing/1")
    assert research._clean_url("javascript:alert(1)") == "" and research._clean_url("file:///c:/x") == ""
    assert research._clean_url("ftp://x.org") == ""


def test_add_venue_fills_only_empty_fields(lib):
    conn, _ = lib
    checked = {"website": "https://opensea.example/", "checked_on": "2026-10-08", "facts": {
        "reading_periods": {"value": "Jan to Mar", "quote": "We read January to March.", "url": "https://opensea.example/g"},
        "line_limit": {"value": 30, "quote": "Up to 30 lines.", "url": "https://opensea.example/g"}}}
    v = research.add_venue(conn, "open sea", "https://opensea.example/", checked, "Publishes sea poems.")
    assert v["name"] == "Open Sea" and v["reading_periods"] == "all year" and v["max_lines"] == 30 and v["cost"] == 0
    assert "Suggested by submission research" in v["notes"] and '"Up to 30 lines." https://opensea.example/g' in v["notes"] and "30 lines (" in v["notes"]
    new = research.add_venue(conn, "The Harbor Review", "https://harbor.example/")
    assert new["saved"] and new["website"] == "https://harbor.example/"


def test_routes(client, lib, monkeypatch):
    conn, tide = lib
    d = client.get(f"/api/research/fit?entry_id={tide}").get_json()
    assert d["fit"]["title"] == "Morning Tide" and d["own"][0]["name"] == "Open Sea" and not d["ai"]["ready"]
    r = client.post("/api/research/suggest", json={"entry_id": tide})
    assert r.status_code == 400 and r.get_json()["ai_off"]
    p = client.post("/api/research/preview", json={"entry_id": tide, "include_text": True, "about": "tides"}).get_json()
    assert "about: tides" in p["brief"] and "words of it" in p["brief"]
    assert client.get("/api/research/fit").status_code == 400
    assert client.post("/api/research/add", json={"name": "Brine"}).get_json()["name"] == "Brine"

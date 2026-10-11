import datetime
import os
import time

import pytest

from minerva import core, stats

from conftest import write

TODAY = datetime.date.today()


def _age(path, days):
    ts = time.mktime((TODAY - datetime.timedelta(days=days)).timetuple()) + 12 * 3600
    os.utime(path, (ts, ts))


@pytest.fixture
def dated(library):
    """The synthetic library with file dates spread over a few weeks."""
    poem = os.path.join(library, "Poetry", "Morning Tide")
    _age(os.path.join(poem, "Morning Tide [C].txt"), 0)
    _age(os.path.join(poem, "Archive", "Morning Tide (old).txt"), 1)
    light = os.path.join(library, "Fiction", "The Lighthouse - [LH]")
    _age(os.path.join(light, "The Lighthouse [C].txt"), 2)
    notes = os.path.join(library, "Nonfiction", "Field Notes")
    _age(os.path.join(notes, "Field Notes [J].txt"), 40)
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    yield library, conn
    conn.close()


def _day(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def test_sync_records_activity_from_file_dates(dated):
    _, conn = dated
    rows = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM activity_days")}
    assert rows[_day(0)]["drafts"] == 1
    assert rows[_day(1)]["revisions"] == 1
    assert rows[_day(2)]["drafts"] == 1 and rows[_day(40)]["drafts"] == 1
    tide = conn.execute("SELECT * FROM entries WHERE title = 'Morning Tide'").fetchone()
    # started = its oldest file, the archived draft
    assert (tide["draft_modified"], tide["started"]) == (_day(0), _day(1))
    snap = conn.execute("SELECT * FROM library_days").fetchall()
    assert [(s["day"], s["entries"]) for s in snap] == [(_day(0), 3)]


def test_stats_streaks_weeks_and_recent(dated):
    _, conn = dated
    s = stats.build(conn)
    assert s["totals"]["entries"] == 3 and s["totals"]["words"] > 0
    assert s["streak"] == {"current": 3, "longest": 3}  # today, yesterday, the day before
    assert len(s["weeks"]) == 12 and s["weeks"][-1]["start"] <= TODAY.isoformat()
    assert sum(w["saves"] for w in s["weeks"]) == 4
    assert [r["title"] for r in s["recent"]] == ["Morning Tide", "The Lighthouse", "Field Notes"]
    assert s["milestone"]["words"] == 1000 and s["milestone"]["to_go"] == 1000 - s["totals"]["words"]
    assert {c["name"] for c in s["categories"]} == {"Poetry", "Fiction", "Nonfiction"}
    # no snapshot from before this month yet
    assert s["month"]["words_added"] is None


def test_week_comparison_and_month_growth(dated):
    _, conn = dated
    conn.execute("INSERT INTO library_days (day, entries, words) VALUES (?, 3, 1)", ((TODAY.replace(day=1) - datetime.timedelta(days=3)).isoformat(),))
    conn.execute("INSERT OR REPLACE INTO activity_days (day, drafts, revisions, started) VALUES (?, 5, 0, 0)",
                 ((TODAY - datetime.timedelta(days=TODAY.weekday() + 3)).isoformat(),))
    conn.commit()
    s = stats.build(conn)
    assert s["week"]["last"] == 5
    assert s["month"]["words_added"] == s["totals"]["words"] - 1


def test_saving_in_minerva_moves_the_activity_to_today(dated):
    _, conn = dated
    eid = conn.execute("SELECT id FROM entries WHERE title = 'The Lighthouse'").fetchone()["id"]
    core.save_entry_content(conn, eid, "Twice there was a keeper.\n", "archive")
    rows = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM activity_days")}
    assert rows[_day(2)]["drafts"] == 0 and rows[_day(2)]["revisions"] == 1
    assert rows[_day(0)]["drafts"] == 2
    # a full sync agrees with the quick update
    core.scan_and_sync()
    again = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM activity_days")}
    assert again[_day(2)]["revisions"] == 1 and again[_day(0)]["drafts"] == 2


def test_streak_allows_a_gap_of_only_yesterday():
    rows = {d: {"drafts": 1, "revisions": 0} for d in ("2026-03-01", "2026-03-02", "2026-03-04")}
    assert stats._streaks(rows, datetime.date(2026, 3, 5)) == (1, 2)
    assert stats._streaks(rows, datetime.date(2026, 3, 6)) == (0, 2)


def test_howtos_are_bundled_with_art_and_summaries():
    howtos = core.list_howtos()
    assert [h["title"] for h in howtos] == [
        "Scanning and Sorting for Minerva", "Using Minerva to Organize Files",
        "Using Minerva to Manage Drafts", "Using Minerva to Share Final Drafts",
        "Bringing In Old Drafts", "Putting a Chapbook Together", "Tracking Where a Poem Is Out",
        "Making a Standard Manuscript", "Running AI on Your Computer", "Using an AI Service", "Narration and Video"]
    for h in howtos:
        assert h["summary"] and h["cover"].startswith('<svg class="howto-cover"')
        html = core.read_howto(h["name"])
        assert html.count('class="howto-figure"') >= 1
        # covers and diagrams take their colors from the theme, not fixed values
        assert "#" not in html.split("<h1>")[0].replace("url(#", "")
    with pytest.raises(ValueError):
        core.read_howto("../1 - Getting Started.txt")


def test_home_routes(client, library):
    # the how-tos are there before any library is open (first-run help)
    assert len(client.get("/api/howtos").get_json()) == 11
    core.configure(library)
    core.scan_and_sync()
    assert client.get("/api/howtos/nope.html").status_code == 404
    s = client.get("/api/stats").get_json()
    assert s["totals"]["entries"] == 3 and len(s["weeks"]) == 12


def test_profile_saves_name_and_style(client):
    from minerva import config
    assert client.get("/api/settings/profile").get_json()["theme"] == "athena"
    r = client.post("/api/settings/profile", json={"username": "  Ada\n\tLovelace\x07 ", "theme": "liched-up"})
    assert r.get_json() == {"username": "Ada Lovelace", "theme": "liched-up"}
    assert config.load()["theme"] == "liched-up"
    assert client.post("/api/settings/profile", json={"theme": "neon"}).status_code == 400
    assert client.post("/api/settings/profile", json={"username": "x" * 100}).get_json()["username"] == "x" * 40
    # the page opens in the saved style, with no flash of the default
    page = client.get("/").get_data(as_text=True)
    assert 'data-theme="liched-up"' in page and 'content="xxxxxxxxxx' in page


def test_every_style_defines_every_color():
    css = open(os.path.join(os.path.dirname(core.__file__), "static", "style.css"), encoding="utf-8").read()
    root = css[css.index(":root {"):css.index("}", css.index(":root {"))]
    colors = {line.split(":")[0].strip() for line in root.splitlines()
              if line.strip().startswith("--") and ("#" in line or "rgba" in line)}
    from minerva import config
    for theme in config.THEMES[1:]:
        start = css.index(f':root[data-theme="{theme}"] {{')
        block = css[start:css.index("}", start)]
        missing = {c for c in colors if c + ":" not in block}
        assert not missing, (theme, sorted(missing))


def test_overwriting_an_old_draft_keeps_its_day_in_the_streak(dated):
    _, conn = dated
    eid = conn.execute("SELECT id FROM entries WHERE title = 'The Lighthouse'").fetchone()["id"]
    before = stats.build(conn)["streak"]
    core.save_entry_content(conn, eid, "Twice there was a keeper.\n", "overwrite")
    core.scan_and_sync()
    rows = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM activity_days")}
    assert rows[_day(2)]["drafts"] == 1 and rows[_day(0)]["drafts"] >= 1
    assert stats.build(conn)["streak"]["longest"] >= before["longest"]


def test_every_help_link_points_at_a_real_page_and_heading():
    """static/help.js maps each screen's "How this works" link to a page and
    heading; a renamed how-to or guide heading would break it silently."""
    import re
    js = open(os.path.join(os.path.dirname(core.__file__), "static", "help.js"), encoding="utf-8").read()
    consts = dict(re.findall(r'const (GUIDE|BASICS) = "([^"]+)"', js))
    topics = re.findall(r'(\w+): \{ kind: "(howto|doc)", name: ([A-Z]+|"[^"]+")(?:, anchor: "([^"]+)")? \}', js)
    assert len(topics) >= 15
    for topic, kind, name, anchor in topics:
        name = consts.get(name, name.strip('"'))
        if kind == "howto":
            html = core.read_howto(name)
            if anchor:
                assert re.search(r"<h2>\d+\. " + re.escape(anchor) + "</h2>", html), (topic, anchor)
        else:
            text = open(os.path.join(core.DOCS_DIR, name), encoding="utf-8").read()
            if anchor:
                assert "\n" + anchor + "\n" in text, (topic, anchor)

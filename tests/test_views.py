import json
import os

import pytest

from minerva import ai, core, people, scanning, views

from test_scanning import _enable, notebook, post  # noqa: F401  (fixture)

SEP = "=" * 60
MASTER = "\n".join([
    SEP, "ENTRY 1 (Scan 1, Segment 1) — Harbor Song", "Date: 3/4/21", SEP, "The boats come home.", "",
    SEP, "ENTRY 2 (Scan 1, Segment 2)", "Date: 6/1/22", SEP, "Ana left for the city.", "",
    SEP, "ENTRY 3 (Scan 1, Segment 3)", "Date: none", SEP, "Undated notes.", "",
])


@pytest.fixture
def journal(notebook):  # noqa: F811
    with open(os.path.join(notebook, "Sources", "Green Notebook", "Green Notebook - Master.txt"), "w", encoding="utf-8") as fh:
        fh.write(MASTER)
    conn = core.get_conn()
    yield conn
    conn.close()


@pytest.fixture
def model(monkeypatch):
    replies = []
    def complete(*a, **k):
        r = replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)

    monkeypatch.setattr(ai, "complete", complete)
    return replies


def _green(data):
    return next(j for j in data["journals"] if j["name"] == "Green Notebook")


def test_timeline_by_journal_and_year_needs_no_model(journal):
    scanning.file_entries("Green Notebook", [{"num": 2, "title": "City", "category": "Nonfiction"}])
    core.scan_and_sync()
    people.record(journal, "Green Notebook", "v", [{"name": "Ana", "entries": [2]}], {1, 2, 3})
    data = views.timeline(journal)
    g = _green(data)
    assert (g["entries"], g["first"], g["last"], g["dated"]) == (3, "2021-03-04", "2022-06-01", 2)
    assert g["filed"] == {"Nonfiction": 1} and g["people"] == ["Ana"] and g["notes"] is None
    # the filed journal entry is placed by the journal's date, not the day it was filed
    y2022 = next(y for y in data["years"] if y["year"] == "2022")
    assert [e["title"] for e in y2022["entries"]] == ["City"] and y2022["categories"] == {"Nonfiction": 1}
    assert sum(y["count"] for y in data["years"]) == journal.execute("SELECT COUNT(*) FROM entries").fetchone()[0]


def test_summaries_are_kept_until_the_master_changes(journal, model):
    model.append({"events": ["Ana moved away (June 2022)"], "themes": ["leaving", "Leaving"], "places": [],
                  "people": ["Ana"], "projects": None})
    out = views.summarize(journal, "Green Notebook", {"provider": "anthropic", "model": "m"}, "k")
    assert out["notes"]["themes"] == ["leaving"] and out["notes"]["projects"] == []
    g = _green(views.timeline(journal))
    assert g["notes"]["events"] == ["Ana moved away (June 2022)"] and g["notes_current"]
    path = os.path.join(scanning.source_dir("Green Notebook"), "Green Notebook - Master.txt")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n")
    assert not _green(views.timeline(journal))["notes_current"]


def test_saving_the_timeline_keeps_other_files(journal):
    chron = os.path.join(core.JOURNAL_SCANS_DIR, "Chronology.txt")
    with open(chron, "w", encoding="utf-8") as fh:
        fh.write("mine")
    rel = views.save_text(journal)
    assert rel.endswith("/Timeline (Minerva).txt")
    text = open(os.path.join(core.ARCHIVE_ROOT, rel), encoding="utf-8").read()
    assert "Green Notebook (2021-03-04 to 2022-06-01)" in text and "BY YEAR" in text
    views.save_text(journal)
    backups = os.listdir(os.path.join(core.META_DIR, "backups"))
    assert any(b.startswith("Timeline (Minerva) (") for b in backups)
    assert open(chron, encoding="utf-8").read() == "mine"


def test_timeline_routes(client, journal, model):
    assert _green(client.get("/api/views/timeline").get_json())["entries"] == 3
    assert post(client, "/api/views/timeline/summarize", {"source": "Green Notebook"}).get_json()["ai_off"]
    assert post(client, "/api/views/timeline/estimate", {"source": "Green Notebook"}).get_json()["entries"] == 3
    _enable("organizing")
    model.append({"events": ["x"]})
    job = post(client, "/api/views/timeline/summarize", {"source": "Green Notebook"}).get_json()
    import time
    for _ in range(50):
        j = client.get(f"/api/jobs/{job['id']}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", j
    assert post(client, "/api/views/timeline/save").get_json()["path"].endswith("Timeline (Minerva).txt")


def _people(conn):
    people.record(conn, "Green Notebook", "v",
                  [{"name": "Ana Reyes", "also": ["Ana"], "entries": [2, 1], "about": "my sister"}], {1, 2, 3})
    return next(p for p in views.histories(conn))


def test_history_lists_dated_passages_naming_the_person(journal):
    p = _people(journal)
    assert (p["name"], p["written"]) == ("Ana Reyes", False)
    h = views.history(journal, p["id"])
    assert [m["num"] for m in h["mentions"]] == [1, 2]
    # entry 2 names her ("Ana"); entry 1 doesn't, so its opening is shown
    assert h["mentions"][1]["excerpt"] == "Ana left for the city."
    assert h["mentions"][0]["excerpt"] == "The boats come home."
    assert views.excerpt("x " * 400, ["Ana"]).endswith(" …")
    assert views.excerpt("Banana bread. Ana came.", ["Ana"]) == "Ana came."


def test_written_history_is_kept_until_mentions_change(journal, model):
    p = _people(journal)
    model.append("You and Ana walked the pier in 2021.")
    h = views.write_history(journal, p["id"], {"provider": "anthropic", "model": "m"}, "k")
    assert h["text"].startswith("You and Ana") and h["current"]
    people.record(journal, "Green Notebook", "v", [{"name": "Ana", "entries": [2]}], {1, 2, 3})
    again = views.history(journal, p["id"])
    assert again["text"] and not again["current"]
    assert views.estimate_history(journal, p["id"], "claude-sonnet-5-5")["mentions"] == 1


def test_saving_histories(journal, model):
    with pytest.raises(people.PeopleError):
        views.save_histories(journal)
    _people(journal)
    rel = views.save_histories(journal)
    text = open(os.path.join(core.ARCHIVE_ROOT, rel), encoding="utf-8").read()
    assert "ANA REYES (also Ana)" in text and "2022-06-01  Green Notebook 2: Ana left for the city." in text


def test_history_routes(client, journal, model):
    p = _people(journal)
    assert client.get("/api/views/people").get_json()[0]["id"] == p["id"]
    assert client.get(f"/api/views/people/{p['id']}").get_json()["count"] == 2
    assert client.get("/api/views/people/9999").status_code == 400
    assert post(client, f"/api/views/people/{p['id']}/write").get_json()["ai_off"]
    _enable("organizing")
    model.append("A short history.")
    assert post(client, f"/api/views/people/{p['id']}/write").get_json()["text"] == "A short history."
    assert post(client, "/api/views/people/save").get_json()["path"].endswith("People Histories (Minerva).txt")

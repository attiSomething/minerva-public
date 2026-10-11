import datetime
import shutil
import os

import pytest

from minerva import core, stats, submissions as subs

TODAY = datetime.date.today()


def _d(days_ago):
    return (TODAY - datetime.timedelta(days=days_ago)).isoformat()


@pytest.fixture
def lib(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    core.create_project(conn, "Lighthouse", "LH")
    yield library, conn
    conn.close()


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def _pid(conn):
    return conn.execute("SELECT id FROM projects WHERE tag = 'LH'").fetchone()["id"]


def test_create_validates_and_defaults(lib):
    _, conn = lib
    tide = _id(conn, "Morning Tide")
    s = subs.create(conn, {"entry_id": tide, "venue": "  Harbor   Review ", "cost": "3.5", "response_days": "60"})
    assert (s["venue"], s["status"], s["submitted_on"], s["cost"]) == ("Harbor Review", "Submitted", TODAY.isoformat(), 3.5)
    assert s["expected_by"] == (TODAY + datetime.timedelta(days=60)).isoformat() and not s["overdue"]
    assert (s["kind"], s["title"], s["category"]) == ("entry", "Morning Tide", "Poetry")
    planned = subs.create(conn, {"entry_id": tide, "venue": "Spring Contest", "status": "Planned", "deadline": _d(-20)})
    assert planned["submitted_on"] is None
    for bad in ({"entry_id": tide}, {"entry_id": tide, "venue": "X", "cost": "-1"},
                {"entry_id": tide, "venue": "X", "deadline": "soon"}, {"entry_id": tide, "venue": "X", "status": "Lost"},
                {"venue": "X"}, {"entry_id": tide, "project_id": _pid(conn), "venue": "X"},
                {"entry_id": 9999, "venue": "X"}):
        with pytest.raises(subs.SubmissionError):
            subs.create(conn, bad)


def test_search_filters_summary_and_overdue(lib):
    _, conn = lib
    tide, light = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    subs.create(conn, {"entry_id": tide, "venue": "Harbor Review", "submitted_on": _d(100), "response_days": 30, "cost": 3})
    subs.create(conn, {"entry_id": tide, "venue": "Salt Quarterly", "submitted_on": _d(50), "status": "Accepted"})
    subs.create(conn, {"entry_id": light, "venue": "Harbor Review", "submitted_on": _d(10), "status": "Declined", "cost": 2})
    subs.create(conn, {"project_id": _pid(conn), "venue": "Small Press", "submitted_on": _d(5), "cost": 25, "currency": "£"})

    rows = subs.search(conn)
    assert [r["venue"] for r in rows] == ["Small Press", "Harbor Review", "Salt Quarterly", "Harbor Review"]
    s = subs.summary(rows)
    assert (s["waiting"], s["overdue"], s["accepted"], s["acceptance_rate"]) == (2, 1, 1, 0.5)
    assert s["fees"] == {"$": 5, "£": 25}

    assert len(subs.search(conn, {"venue": "harbor review"})) == 2
    assert [r["title"] for r in subs.search(conn, {"category": "Fiction"})] == ["The Lighthouse"]
    # the project filter finds the project's own record and its entries' records
    assert {r["title"] for r in subs.search(conn, {"project": "LH"})} == {"Lighthouse", "The Lighthouse"}
    assert len(subs.search(conn, {"open": "1"})) == 2
    assert len(subs.search(conn, {"date_from": _d(60), "date_to": _d(6)})) == 2
    assert [r["venue"] for r in subs.search(conn, {"q": "quarterly"})] == ["Salt Quarterly"]
    assert [r["kind"] for r in subs.search(conn, {"kind": "project"})] == ["project"]
    assert stats.build(conn)["submissions"] == {"waiting": 2, "overdue": 1}


def test_records_survive_merges_deletes_and_lost_entries(lib):
    library, conn = lib
    tide, light = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    a = subs.create(conn, {"entry_id": light, "venue": "Harbor Review"})
    p = subs.create(conn, {"project_id": _pid(conn), "venue": "Small Press"})

    core.merge_entries(conn, tide, light)
    assert subs.get(conn, a["id"])["entry_id"] == tide

    core.delete_project(conn, _pid(conn))
    gone = subs.get(conn, p["id"])
    assert (gone["title"], gone["missing"]) == ("Lighthouse", True)

    # an entry removed outside Minerva keeps its record, by its old title
    b = subs.create(conn, {"entry_id": _id(conn, "Field Notes"), "venue": "Notes Journal"})
    shutil.rmtree(os.path.join(library, "Nonfiction", "Field Notes"))
    core.scan_and_sync()
    lost = subs.get(conn, b["id"])
    assert (lost["title"], lost["missing"]) == ("Field Notes", True)


def test_update_is_partial(lib):
    _, conn = lib
    s = subs.create(conn, {"entry_id": _id(conn, "Morning Tide"), "venue": "Harbor Review", "notes": "first read"})
    u = subs.update(conn, s["id"], {"status": "Accepted", "decided_on": TODAY.isoformat()})
    assert (u["status"], u["venue"], u["notes"]) == ("Accepted", "Harbor Review", "first read")
    with pytest.raises(subs.SubmissionError):
        subs.update(conn, s["id"], {"venue": "  "})


def test_submission_routes(client, lib):
    _, conn = lib
    tide = _id(conn, "Morning Tide")
    r = client.post("/api/submissions", json={"entry_id": tide, "venue": "Harbor Review"})
    sid = r.get_json()["id"]
    assert client.post("/api/submissions", json={"entry_id": tide}).status_code == 400
    assert client.post(f"/api/submissions/{sid}", json={"status": "Shortlisted"}).get_json()["status"] == "Shortlisted"
    data = client.get(f"/api/submissions?entry_id={tide}").get_json()
    assert data["summary"]["waiting"] == 1 and data["rows"][0]["status"] == "Shortlisted"
    opts = client.get("/api/submissions/options").get_json()
    assert opts["venues"] == ["Harbor Review"] and opts["projects"][0]["tag"] == "LH" and "Accepted" in opts["statuses"]
    assert client.post(f"/api/submissions/{sid}/delete").get_json() == {"ok": True}
    assert client.get("/api/submissions").get_json()["rows"] == []


def test_venue_notes_history_and_suggestions(lib):
    _, conn = lib
    tide, light = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    assert subs.venue(conn, "Harbor Review") is None
    subs.create(conn, {"entry_id": tide, "venue": "Harbor Review", "cost": 3, "submitted_on": _d(100),
                       "status": "Declined", "decided_on": _d(40)})
    subs.create(conn, {"entry_id": light, "venue": "harbor review", "cost": 5, "submitted_on": _d(30),
                       "status": "Accepted", "decided_on": _d(10)})
    subs.create(conn, {"entry_id": light, "venue": "Harbor Review", "status": "Planned"})
    v = subs.venue(conn, "HARBOR REVIEW")
    assert not v["saved"] and len(v["history"]) == 3
    assert (v["stats"]["accepted"], v["stats"]["acceptance_rate"], v["stats"]["median_wait"]) == (1, 0.5, 60)
    # nothing saved yet: start from the last fee paid and the usual wait
    assert v["suggested"] == {"cost": 5, "currency": "$", "response_days": 60}

    saved = subs.save_venue(conn, {"name": "harbor review", "website": "harbor.example", "cost": "",
                                   "response_days": "90", "reading_periods": "Sep–Nov", "notes": "Likes sea poems"})
    assert saved["name"] == "Harbor Review" and saved["saved"]
    assert saved["suggested"] == {"cost": 5, "currency": "$", "response_days": 90}
    assert subs.save_venue(conn, {"name": "Harbor Review", "cost": "0", "currency": "£"})["suggested"]["cost"] == 0
    # a venue can have notes before anything is sent there
    subs.save_venue(conn, {"name": "Tidewater Press", "reading_periods": "All year"})
    assert [v["name"] for v in subs.list_venues(conn)] == ["Harbor Review", "Tidewater Press"]
    for bad in ({"name": " "}, {"name": "X", "cost": "-2"}, {"name": "X", "response_days": "soon"}):
        with pytest.raises(subs.SubmissionError):
            subs.save_venue(conn, bad)


def test_venue_routes(client, lib):
    assert client.get("/api/venue?name=Nowhere").status_code == 404
    r = client.post("/api/venue", json={"name": "Tidewater Press", "response_days": 30})
    assert r.get_json()["suggested"]["response_days"] == 30
    assert client.get("/api/venue?name=tidewater press").get_json()["name"] == "Tidewater Press"
    assert [v["name"] for v in client.get("/api/venues").get_json()] == ["Tidewater Press"]


def test_acceptance_finds_and_withdraws_the_other_waiting_submissions(lib):
    _, conn = lib
    tide, light = _id(conn, "Morning Tide"), _id(conn, "The Lighthouse")
    won = subs.create(conn, {"entry_id": tide, "venue": "Harbor Review"})
    a = subs.create(conn, {"entry_id": tide, "venue": "Salt Quarterly", "status": "Shortlisted"})
    b = subs.create(conn, {"entry_id": tide, "venue": "Tidewater Press"})
    subs.create(conn, {"entry_id": tide, "venue": "Old Contest", "status": "Declined"})
    subs.create(conn, {"entry_id": tide, "venue": "Next Year", "status": "Planned"})
    subs.create(conn, {"entry_id": light, "venue": "Salt Quarterly"})
    subs.update(conn, won["id"], {"status": "Accepted"})
    others = subs.still_waiting_elsewhere(conn, won["id"])
    assert sorted(r["venue"] for r in others) == ["Salt Quarterly", "Tidewater Press"]
    assert subs.withdraw(conn, [a["id"], won["id"]], datetime.date(2026, 5, 1)) == [a["id"]]
    assert (subs.get(conn, a["id"])["status"], subs.get(conn, a["id"])["decided_on"]) == ("Withdrawn", "2026-05-01")
    assert subs.get(conn, won["id"])["status"] == "Accepted"
    assert [r["id"] for r in subs.still_waiting_elsewhere(conn, won["id"])] == [b["id"]]


def test_acceptance_routes(client, lib):
    _, conn = lib
    tide = _id(conn, "Morning Tide")
    won = client.post("/api/submissions", json={"entry_id": tide, "venue": "Harbor Review"}).get_json()
    other = client.post("/api/submissions", json={"entry_id": tide, "venue": "Salt Quarterly"}).get_json()
    assert [r["id"] for r in client.get(f"/api/submissions/{won['id']}/elsewhere").get_json()] == [other["id"]]
    assert client.post("/api/submissions/withdraw", json={"ids": [other["id"]]}).get_json() == {"withdrawn": [other["id"]]}
    assert client.get(f"/api/submissions/{won['id']}/elsewhere").get_json() == []

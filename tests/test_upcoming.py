import datetime
import os

from conftest import write
from minerva import core, submissions, upcoming

TODAY = datetime.date(2026, 10, 8)


def test_reading_periods_as_venues_write_them():
    assert upcoming.parse_periods("Sep to Nov, Feb to Apr") == [((9, 1), (11, 0)), ((2, 1), (4, 0))]
    assert upcoming.parse_periods("September 1 - November 30") == [((9, 1), (11, 30))]
    assert upcoming.parse_periods("Sept. through Dec.") == [((9, 1), (12, 0))]
    assert upcoming.parse_periods("March") == [((3, 1), (3, 0))]
    assert upcoming.parse_periods("Year-round") == "always"
    assert upcoming.parse_periods("closed for now") == []
    assert upcoming.parse_periods("") == []


def test_opens_and_closes_in_the_window():
    ev = upcoming.period_events("Oct 15 – Jan 15", TODAY)
    assert ev == [{"event": "opens", "on": datetime.date(2026, 10, 15)}]
    assert upcoming.period_events("August 1 to October 31", TODAY) == [{"event": "closes", "on": datetime.date(2026, 10, 31)}]
    # a period that wraps the new year closes in the next one
    assert upcoming.period_events("Nov 1 - Jan 31", datetime.date(2027, 1, 10)) == [
        {"event": "closes", "on": datetime.date(2027, 1, 31)}]
    assert upcoming.period_events("Feb to Apr", TODAY) == []
    assert upcoming.period_events("all year", TODAY) == []
    assert upcoming.is_open("Sep to Nov", TODAY) and not upcoming.is_open("Feb to Apr", TODAY)
    assert upcoming.is_open("Nov 1 - Jan 31", datetime.date(2027, 1, 10))


def test_coming_up(library, client):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    ids = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM entries")}
    write(os.path.join(library, "Poetry", "Morning Tide", "Final", "Morning Tide - Final.txt"), "The tide.\n")
    write(os.path.join(library, "Fiction", "The Lighthouse - [LH]", "Final", "The Lighthouse - Final.txt"), "Keeper.\n")
    d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()  # noqa: E731
    submissions.create(conn, {"entry_id": ids["Field Notes"], "venue": "Salt Quarterly", "status": "Planned", "deadline": d(5)})
    submissions.create(conn, {"entry_id": ids["Field Notes"], "venue": "Far Off", "status": "Planned", "deadline": d(90)})
    submissions.create(conn, {"entry_id": ids["The Lighthouse"], "venue": "Harbor Review", "submitted_on": d(-100),
                              "response_days": 60})
    submissions.save_venue(conn, {"name": "Harbor Review", "reading_periods": "Oct 15 to Dec 31"})
    submissions.save_venue(conn, {"name": "Tidewater", "reading_periods": "rolling"})
    conn.commit()

    c = upcoming.coming_up(conn, TODAY)
    assert [(x["sub"]["venue"], x["days"]) for x in c["deadlines"]] == [("Salt Quarterly", 5)]
    assert [(x["sub"]["title"], x["days"]) for x in c["overdue"]] == [("The Lighthouse", 40)]
    assert [(r["venue"], r["event"], r["days"]) for r in c["reading"]] == [("Harbor Review", "opens", 7)]
    # The Lighthouse has a final draft but is out at Harbor Review
    assert [r["title"] for r in c["ready"]] == ["Morning Tide"] and c["ready_total"] == 1
    conn.close()

    r = client.get("/api/home/coming-up").get_json()
    assert r["window_days"] == 30 and r["ready"][0]["title"] == "Morning Tide"

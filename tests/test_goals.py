import datetime
import pytest

from minerva import core, goals, stats


@pytest.fixture
def lib(library):
    core.configure(library)
    core.scan_and_sync()
    return library, core.get_conn()


def test_words_added_today_count_saves_and_cuts(lib):
    library, conn = lib
    p = goals.progress(conn)
    assert p["daily"] == {"goal": 0, "words": 0} and p["weekly"]["words"] == 0
    tide = conn.execute("SELECT * FROM entries WHERE title = 'Morning Tide'").fetchone()
    core.save_entry_content(conn, tide["id"], tide["word_count"] * "word " + "one two three", "overwrite")
    assert goals.progress(conn)["daily"]["words"] == 3
    core.save_entry_content(conn, tide["id"], "short", "overwrite")
    assert goals.progress(conn)["daily"]["words"] == 1 - tide["word_count"]
    # a later sync the same day keeps the day's starting point
    core.scan_and_sync()
    assert goals.progress(conn)["daily"]["words"] == 1 - tide["word_count"]


def test_baseline_is_last_known_size_before_the_day(lib):
    _, conn = lib
    today = datetime.date.today()
    total = conn.execute("SELECT SUM(word_count) w FROM entries").fetchone()["w"]
    conn.execute("DELETE FROM library_days")
    conn.execute("INSERT INTO library_days (day, entries, words) VALUES (?, 1, ?)",
                 ((today - datetime.timedelta(days=9)).isoformat(), total - 40))
    # the day's first sync recorded the size Minerva last saw
    conn.execute("INSERT INTO library_days (day, entries, words, start_words) VALUES (?, 1, ?, ?)",
                 (today.isoformat(), total, total - 40))
    conn.commit()
    p = goals.progress(conn, today)
    assert p["daily"]["words"] == 40 and p["weekly"]["words"] == 40
    # rows from before start_words existed fall back to the previous day's size
    conn.execute("UPDATE library_days SET start_words = NULL")
    assert goals.progress(conn, today)["daily"]["words"] == 40


def test_goal_settings_and_project_targets(client, lib):
    library, conn = lib
    assert client.post("/api/goals", json={"daily_words": "abc"}).status_code == 400
    assert client.post("/api/goals", json={"daily_words": -5}).status_code == 400
    r = client.post("/api/goals", json={"daily_words": "500", "weekly_words": ""}).get_json()
    assert (r["daily"]["goal"], r["weekly"]["goal"]) == (500, 0)
    assert goals.get() == {"daily_words": 500, "weekly_words": 0}
    core.create_project(conn, "Lighthouse", "LH")
    pid = conn.execute("SELECT id FROM projects WHERE tag = 'LH'").fetchone()["id"]
    assert client.post(f"/api/projects/{pid}", json={"target_words": "x"}).status_code == 400
    client.post(f"/api/projects/{pid}", json={"target_words": 60000})
    p = stats.build(conn)["goals"]["projects"]
    assert p == [{"id": pid, "name": "Lighthouse", "tag": "LH", "target": 60000, "words": 5}]
    client.post(f"/api/projects/{pid}", json={"target_words": ""})
    assert goals.progress(conn)["projects"] == []
    # editing the description alone leaves the target alone
    client.post(f"/api/projects/{pid}", json={"target_words": 100})
    client.post(f"/api/projects/{pid}", json={"description": "Sea stories"})
    assert goals.progress(conn)["projects"][0]["target"] == 100

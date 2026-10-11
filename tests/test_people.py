import json
import os

import pytest

from minerva import ai, core, people

from test_scanning import _enable, notebook, post  # noqa: F401  (fixture)

SEP = "=" * 60
MASTER = "\n".join([
    SEP, "ENTRY 1 (Scan 1, Segment 1) — Harbor Song", "Date: 3/4/21", SEP, "Ana and I walked the pier.", "",
    SEP, "ENTRY 2 (Scan 1, Segment 2)", "Date: 3/9/21", SEP, "Grandma called. Annie says hello.", "",
    SEP, "ENTRY 3 (Scan 1, Segment 3)", "Date: none", SEP, "Dr. Patel, again.", "",
])
FIRST = [{"name": "Ana Reyes", "also": ["Ana"], "entries": [1], "about": "my sister"},
         {"name": "Annie", "entries": [2]},
         {"name": "Grandma", "entries": [2, 99], "about": ""},
         {"name": "Dr. Patel", "entries": ["3"]},
         {"name": "Nobody", "entries": []}]


@pytest.fixture
def journal(notebook):  # noqa: F811
    path = os.path.join(notebook, "Sources", "Green Notebook", "Green Notebook - Master.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(MASTER)
    conn = core.get_conn()
    yield conn
    conn.close()


@pytest.fixture
def model(monkeypatch):
    replies, calls = [], []

    def complete(provider, model, key, system, prompt, images=(), max_tokens=8000, usage=None):
        calls.append(prompt)
        return "```json\n" + json.dumps(replies.pop(0)) + "\n```"

    monkeypatch.setattr(ai, "complete", complete)
    return replies, calls


SETTINGS = {"provider": "anthropic", "model": "claude-sonnet-5-5"}


def _names(conn):
    return {p["name"]: p for p in people.list_people(conn)}


def test_find_people_records_mentions_with_dates(journal, model):
    replies, calls = model
    replies.append(FIRST)
    assert people.find(journal, "Green Notebook", SETTINGS, "k") == {"source": "Green Notebook", "people": 4}
    assert len(calls) == 1 and "ENTRY 2 (3/9/21)" in calls[0] and "Dr. Patel, again." in calls[0]
    found = _names(journal)
    assert set(found) == {"Ana Reyes", "Annie", "Grandma", "Dr. Patel"}
    ana = found["Ana Reyes"]
    assert (ana["about"], ana["aliases"], ana["first"]) == ("my sister", ["Ana"], "2021-03-04")
    # entry 99 isn't in the Master, so it's dropped
    assert [m["num"] for m in found["Grandma"]["mentions"]] == [2]
    assert found["Grandma"]["mentions"][0]["date"] == "3/9/21"
    src = next(s for s in people.sources(journal) if s["name"] == "Green Notebook")
    assert src["current"] and src["found"] == 4


def test_merges_and_renames_survive_another_run(journal, model):
    replies, _ = model
    replies.append(FIRST)
    people.find(journal, "Green Notebook", SETTINGS, "k")
    found = _names(journal)
    people.merge(journal, found["Ana Reyes"]["id"], [found["Annie"]["id"]])
    people.rename(journal, found["Dr. Patel"]["id"], "Dr. Mira Patel")
    with pytest.raises(people.PeopleError):
        people.rename(journal, found["Grandma"]["id"], "annie")
    with pytest.raises(people.PeopleError):
        people.merge(journal, found["Grandma"]["id"], [found["Grandma"]["id"]])
    merged = _names(journal)["Ana Reyes"]
    assert merged["count"] == 2 and set(merged["aliases"]) == {"Ana", "Annie"}

    # a second run names them the old way; they land on the merged and renamed people
    replies.append([{"name": "Annie", "entries": [1, 2]}, {"name": "Dr. Patel", "entries": [3]}])
    people.find(journal, "Green Notebook", SETTINGS, "k")
    after = _names(journal)
    assert set(after) == {"Ana Reyes", "Dr. Mira Patel"}  # Grandma wasn't found this time
    assert after["Ana Reyes"]["count"] == 2


def test_estimate_prices_a_known_model(journal):
    e = people.estimate("Green Notebook", "claude-sonnet-5-5")
    assert (e["calls"], e["entries"]) == (1, 3) and e["cost"] is not None
    assert people.estimate("Green Notebook", "llama3")["cost"] is None


def test_long_journals_are_split(journal, model, monkeypatch):
    replies, calls = model
    monkeypatch.setattr(people, "BATCH_CHARS", 60)
    replies.extend([[], [], []])
    people.find(journal, "Green Notebook", SETTINGS, "k")
    assert len(calls) == 3


def test_people_routes(client, journal, model):
    replies, _ = model
    assert post(client, "/api/people/find", {"source": "Green Notebook"}).get_json()["ai_off"]
    _enable("organizing")
    replies.append(FIRST)
    job = post(client, "/api/people/find", {"source": "Green Notebook"}).get_json()
    for _ in range(50):
        j = client.get(f"/api/jobs/{job['id']}").get_json()
        if j["status"] != "running":
            break
        import time; time.sleep(0.05)
    assert j["status"] == "done", j
    data = client.get("/api/people").get_json()
    ids = {p["name"]: p["id"] for p in data["people"]}
    r = post(client, "/api/people/merge", {"keep": ids["Ana Reyes"], "others": [ids["Annie"]]})
    assert len(r.get_json()["people"]) == 3
    assert post(client, "/api/people/merge", {"keep": None, "others": []}).status_code == 400
    assert post(client, f"/api/people/{ids['Grandma']}/rename", {"name": "Nana"}).status_code == 200
    assert post(client, "/api/people/estimate", {"source": "Green Notebook"}).get_json()["calls"] == 1

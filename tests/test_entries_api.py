"""The editing features carried over from the first Minerva, exercised
through the HTTP API the page uses."""

import os

import pytest


@pytest.fixture
def opened(client, library):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    rows = client.get("/api/entries?page_size=0").get_json()["rows"]
    ids = {r["title"]: r["id"] for r in rows}
    return client, library, ids


def test_filters_and_pagination(opened):
    client, _, _ = opened
    assert client.get("/api/entries?category=Poetry").get_json()["total"] == 1
    assert client.get("/api/entries?project=LH").get_json()["total"] == 1
    assert client.get("/api/entries?project=__none__").get_json()["total"] == 2
    page = client.get("/api/entries?page_size=2&page=2").get_json()
    assert len(page["rows"]) == 1 and page["total"] == 3


def test_entry_detail_includes_archive_and_scan(opened):
    client, _, ids = opened
    d = client.get(f"/api/entries/{ids['Morning Tide']}").get_json()
    assert "gulls" in d["content"]
    assert [a["name"] for a in d["archive"]] == ["Morning Tide (old).txt"]
    d = client.get(f"/api/entries/{ids['Field Notes']}").get_json()
    assert d["journal_scan"]["available"]
    pdf = client.get(f"/api/entries/{ids['Field Notes']}/scan/pdf")
    assert pdf.status_code == 200


def test_rename_category_project_and_flags(opened):
    client, library, ids = opened
    eid = ids["Morning Tide"]
    r = client.post(f"/api/entries/{eid}/rename", json={"title": "Evening Tide"}).get_json()
    assert r["title"] == "Evening Tide"
    assert os.path.isfile(os.path.join(library, "Poetry", "Evening Tide", "Evening Tide [C].txt"))

    client.post("/api/projects", json={"name": "Seaside", "tag": "SEA"})
    r = client.post(f"/api/entries/{eid}/project", json={"tag": "SEA"}).get_json()
    assert r["folder_name"] == "Evening Tide - [SEA]"

    r = client.post(f"/api/entries/{eid}/category", json={"category": "Misc"}).get_json()
    assert r["top_folder"] == "Misc"
    assert os.path.isdir(os.path.join(library, "Misc", "Evening Tide - [SEA]"))

    r = client.post(f"/api/entries/{eid}/flags", json={"to_record": True}).get_json()
    assert r["to_record"] == 1


def test_restore_old_draft_archives_current(opened):
    client, library, ids = opened
    eid = ids["Morning Tide"]
    client.post(f"/api/entries/{eid}/archive/Morning Tide (old).txt/restore")
    d = client.get(f"/api/entries/{eid}").get_json()
    assert d["content"] == "The tide came in.\n"
    assert len(d["archive"]) >= 1


def test_merge_moves_other_entry_into_archive(opened):
    client, library, ids = opened
    r = client.post(f"/api/entries/{ids['Morning Tide']}/merge_from",
                    json={"other_id": ids["Field Notes"]})
    assert r.status_code == 200
    assert not os.path.exists(os.path.join(library, "Nonfiction", "Field Notes"))
    merged = os.path.join(library, "Poetry", "Morning Tide", "Archive", "Merged - Field Notes")
    assert os.path.isdir(merged)
    assert client.get("/api/entries").get_json()["total"] == 2

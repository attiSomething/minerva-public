import os

import pytest

from minerva import core, intake


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


def test_split_pasted_text():
    text = "Salt Hymn\nline one\n\nline two\n\n***\n\nGull Psalm\nwings\n\n\n\n# Third: a/b?\nend\n"
    pieces = intake.split_pieces(text)
    assert [p["title"] for p in pieces] == ["Salt Hymn", "Gull Psalm", "Third a b"]
    # a stanza break (one or two blank lines) keeps a poem together
    assert pieces[0]["text"] == "Salt Hymn\nline one\n\nline two\n"
    assert len(intake.split_pieces(text, split=False)) == 1
    assert intake.split_pieces("   \n\n") == []
    long = "word " * 30
    assert len(intake.suggest_title(long).split()) == 8


def test_create_entries_in_the_library(library):
    conn = _open(library)
    made = intake.create_entries(conn, [{"title": "New: Poem?", "text": "First line\n"}], "Poetry")
    assert made[0]["title"] == "New Poem"
    path = os.path.join(library, "Poetry", "New Poem", "New Poem [C].txt")
    assert open(path, encoding="utf-8").read() == "First line\n"
    row = core.get_entry_row(conn, made[0]["id"])
    assert row["title"] == "New Poem" and row["top_folder"] == "Poetry"
    # a taken title gets a number, also within one batch
    again = intake.create_entries(conn, [{"title": "New Poem"}, {"title": "new poem"}], "Poetry")
    assert [m["title"] for m in again] == ["New Poem (2)", "new poem (3)"]
    with pytest.raises(intake.IntakeError):
        intake.create_entries(conn, [{"title": "New Poem"}], "Poetry", rename_taken=False)


def test_create_in_a_project_and_errors(library):
    conn = _open(library)
    core.create_project(conn, "Harbor Poems", "HP")
    made = intake.create_entries(conn, [{"title": "Breakwater", "text": ""}], "Poetry", project="hp")
    row = core.get_entry_row(conn, made[0]["id"])
    assert row["project_tag"] == "HP" and row["folder_name"] == "Breakwater - [HP]"
    with pytest.raises(intake.IntakeError):
        intake.create_entries(conn, [{"title": "X"}], "Nowhere")
    with pytest.raises(intake.IntakeError):
        intake.create_entries(conn, [{"title": " ? "}], "Poetry")
    with pytest.raises(intake.IntakeError):
        intake.create_entries(conn, [{"title": "X"}], "Poetry", project="ZZ")


def test_new_entry_routes(client, library):
    _open(library)
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    p = client.post("/api/entries/paste/preview", json={"text": "A\nx\n***\nB\ny\n"}).get_json()
    assert [x["title"] for x in p] == ["A", "B"]
    r = client.post("/api/entries/new", json={"items": p, "category": "Fiction"}).get_json()
    assert [x["title"] for x in r] == ["A", "B"]
    r = client.post("/api/entries/new", json={"title": "Blank", "category": "Fiction"})
    assert r.status_code == 200
    eid = r.get_json()[0]["id"]
    assert client.get(f"/api/entries/{eid}").get_json()["title"] == "Blank"
    assert client.post("/api/entries/new", json={"title": "", "category": "Fiction"}).status_code == 400

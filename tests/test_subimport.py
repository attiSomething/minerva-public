import pytest

from minerva import core, submissions, subimport

CSV = """Poem,Magazine,Date Sent,Result,Heard Back,Fee,Notes
Morning Tide,Harbor Review,3/14/2024,Rejected,5/2/2024,$3,form letter
"The Lighthouse",Salt Quarterly,2024-04-01,pending,,free,
Lost Poem,Harbor Review,4/1/2024,sent,,,
Morning Tide,Gull Press,04/05/24,maybe?,,,
Morning Tide,Harbor Review,3/14/2024,Rejected,5/2/2024,$3,same row twice
Field Notes,,4/9/2024,,,,
"""


def _open(library):
    core.configure(library)
    core.scan_and_sync()
    return core.get_conn()


def test_reading_values():
    assert subimport.parse_date("March 4th, 2024") == "2024-03-04"
    assert subimport.parse_date("4/3/2024") == "2024-04-03"
    assert subimport.parse_date("4/3/2024", day_first=True) == "2024-03-04"
    assert subimport.parse_date("2024-03-01 00:00:00") == "2024-03-01"
    with pytest.raises(ValueError):
        subimport.parse_date("someday")
    assert subimport.parse_status("Form rejection") == "Declined"
    assert subimport.parse_status("not sent") == "Planned"
    assert subimport.parse_status("no") == "Declined"
    assert subimport.parse_status("Under review") == "Submitted"
    assert subimport.parse_status("") is None
    assert subimport.parse_cost("£2.50") == (2.5, "£")
    assert subimport.parse_cost("free") == (0.0, None)
    # Excel's semicolons and Windows encoding
    rows = subimport.read_csv("Title;Venue\nCafé Poem;Réview\n".encode("cp1252"))
    assert rows == [["Title", "Venue"], ["Café Poem", "Réview"]]


def test_guessed_columns():
    m = subimport.guess_mapping(["Poem", "Magazine", "Date Sent", "Result", "Heard Back", "Fee", "Notes"])
    assert m == {"piece": 0, "venue": 1, "submitted_on": 2, "status": 3, "decided_on": 4, "cost": 5, "notes": 6}
    assert "piece" not in subimport.guess_mapping(["Col A", "Col B"])


def test_preview_says_what_each_row_becomes(library):
    conn = _open(library)
    p = subimport.preview(conn, CSV)
    states = {r["row"]: (r["state"], r.get("reason")) for r in p["rows"]}
    assert states[2][0] == "ready" and states[3][0] == "ready"
    assert states[4] == ("unmatched", "No entry or project has this title.")
    assert states[5][0] == "problem" and "maybe?" in states[5][1]
    assert states[6] == ("duplicate", "The same submission appears earlier in this file.")
    assert states[7][0] == "problem" and "No venue" in states[7][1]
    # a status other than Planned with no date gets today's, and the preview says so
    p2 = subimport.preview(conn, "Title,Venue,Status\nMorning Tide,Harbor Review,Accepted\n")
    assert p2["rows"][0]["state"] == "ready" and "today" in p2["rows"][0]["reason"]
    first = p["rows"][0]["record"]
    assert first["status"] == "Declined" and first["decided_on"] == "2024-05-02" and first["cost"] == 3.0
    assert p["counts"] == {"ready": 2, "unmatched": 1, "problem": 2, "duplicate": 1}
    # nothing is saved by a preview
    assert submissions.search(conn, {}) == []


def test_import_with_a_hand_match_and_a_skip(library):
    conn = _open(library)
    m = subimport.guess_mapping(CSV.splitlines()[0].split(","))
    tide = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    r = subimport.run(conn, CSV, m, overrides={"4": {"kind": "entry", "id": tide}, "7": {"skip": True}})
    assert r["imported"] == 3
    left = {x["row"]: x["state"] for x in r["not_imported"]}
    assert left == {5: "problem", 6: "duplicate", 7: "skipped"}
    rows = submissions.search(conn, {})
    assert sorted((x["title"], x["venue"], x["status"]) for x in rows) == [
        ("Morning Tide", "Harbor Review", "Declined"), ("Morning Tide", "Harbor Review", "Submitted"),
        ("The Lighthouse", "Salt Quarterly", "Submitted")]
    # importing the same file again adds nothing
    again = subimport.run(conn, CSV, m, overrides={"4": {"kind": "entry", "id": tide}})
    assert again["imported"] == 0
    assert [x["state"] for x in again["not_imported"]].count("duplicate") == 4


def test_import_routes(client, library):
    _open(library)
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    p = client.post("/api/submissions/import/preview", json={"text": "A,B\nx,y\n"}).get_json()
    assert p["needs_mapping"] is True and p["headings"] == ["A", "B"]
    r = client.post("/api/submissions/import", json={"text": "A,B\nx,y\n", "mapping": {"piece": 0}})
    assert r.status_code == 400 and "Where" in r.get_json()["error"]
    r = client.post("/api/submissions/import", json={"text": CSV, "mapping": {"piece": 0, "venue": 1, "submitted_on": 2}})
    assert r.status_code == 200 and r.get_json()["imported"] == 3
    assert client.post("/api/submissions/import/preview", json={"text": ""}).status_code == 400


SUBMITTABLE = """Title,Organization,Form,Date Submitted,Status,Status Date
Morning Tide,Harbor Review,Poetry 2024,03/14/2024,In-Progress,
The Lighthouse,Salt Quarterly,Fiction,04/01/2024,Received,
"""

GRINDER = """Title,Market,Date Sent,Date Received,Response,Days Out
Morning Tide,Gull Press,2024-02-01,2024-03-10,Form Rejection,38
The Lighthouse,Tidewater,2024-02-03,,Pending,
"""


def test_presets_are_recognized(library):
    conn = _open(library)
    p = subimport.preview(conn, SUBMITTABLE)
    assert p["source"] == "submittable"
    heads = p["headings"]
    assert {f: heads[c] for f, c in p["mapping"].items()} == {
        "piece": "Title", "venue": "Organization", "notes": "Form", "submitted_on": "Date Submitted",
        "status": "Status", "decided_on": "Status Date"}
    assert [r["record"]["status"] for r in p["rows"]] == ["Submitted", "Submitted"]
    assert p["rows"][0]["record"]["notes"] == "Poetry 2024\nSubmittable: In-Progress"

    g = subimport.preview(conn, GRINDER)
    assert g["source"] == "grinder"
    assert {f: g["headings"][c] for f, c in g["mapping"].items()} == {
        "piece": "Title", "venue": "Market", "submitted_on": "Date Sent", "decided_on": "Date Received",
        "status": "Response"}
    assert [r["record"]["status"] for r in g["rows"]] == ["Declined", "Submitted"]
    # the writer can say where a file is from
    assert subimport.preview(conn, GRINDER, source="")["source"] == ""
    assert subimport.detect_source(["Title", "Venue"], "grinder-export.csv") == "grinder"


def test_a_newer_export_updates_what_is_there(library):
    conn = _open(library)
    first = subimport.run(conn, SUBMITTABLE, subimport.preview(conn, SUBMITTABLE)["mapping"], source="submittable")
    assert first["imported"] == 2
    later = SUBMITTABLE.replace("In-Progress,", "Declined,05/20/2024").replace("Received,", "Accepted,06/01/2024")
    p = subimport.preview(conn, later)
    assert [r["state"] for r in p["rows"]] == ["update", "update"]
    assert "status Submitted to Declined" in p["rows"][0]["reason"]
    r = subimport.run(conn, later, p["mapping"], source="submittable")
    assert r["updated"] == 2 and r["imported"] == 0 and not r["not_imported"]
    got = {s["venue"]: (s["status"], s["decided_on"]) for s in submissions.search(conn, {})}
    assert got == {"Harbor Review": ("Declined", "2024-05-20"), "Salt Quarterly": ("Accepted", "2024-06-01")}
    # an older export never walks a decision back
    again = subimport.preview(conn, SUBMITTABLE)
    assert [r["state"] for r in again["rows"]] == ["duplicate", "duplicate"]

import os

from minerva import core


def _entry(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE title = 'Morning Tide'").fetchone()
    return conn, row


def test_compare_current_with_archive(library):
    conn, row = _entry(library)
    r = core.compare_drafts(row, "Morning Tide (old).txt", "")
    assert r["a"]["name"] == "Morning Tide (old).txt" and r["b"]["current"]
    assert ["del", "came"] in r["changes"] and ["ins", "comes"] in r["changes"]
    assert r["added"] > 0 and r["removed"] > 0 and not r["same"]
    assert core.compare_drafts(row, "", "")["same"]
    # archived files list their dates for the picker
    assert core.list_archive(row)[0]["modified"]


def test_compare_rejects_paths_outside_archive(library):
    conn, row = _entry(library)
    for bad in ("../Morning Tide [C].txt", "../../Fiction/The Lighthouse - [LH]/The Lighthouse [C].txt", "missing.txt"):
        try:
            core.compare_drafts(row, bad, "")
        except (ValueError, OSError):
            continue
        raise AssertionError(bad)


def test_compare_route_and_old_encodings(client, library):
    conn, row = _entry(library)
    with open(os.path.join(library, "Poetry", "Morning Tide", "Archive", "Morning Tide cp.txt"), "wb") as fh:
        fh.write("The café tide.".encode("cp1252"))
    r = client.get(f"/api/entries/{row['id']}/compare?a=Morning Tide cp.txt").get_json()
    assert any("café" in t for op, t in r["changes"] if op == "del")
    assert client.get(f"/api/entries/{row['id']}/compare?a=../x.txt").status_code == 400
    assert client.get("/api/entries/9999/compare").status_code == 404

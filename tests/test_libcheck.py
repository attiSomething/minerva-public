import os

from conftest import write
from minerva import core, libcheck


def _kinds(found):
    return {(i["kind"], i["path"]) for i in found}


def test_check_reports_problems_without_changing_anything(library):
    core.configure(library)
    write(os.path.join(library, "Poetry", "No Draft", "Images", "pic.txt.bak"), "x")
    write(os.path.join(library, "Poetry", "Two Current", "Two Current [C].txt"), "one")
    write(os.path.join(library, "Poetry", "Two Current", "Two Current v2 [C].txt"), "two")
    write(os.path.join(library, "Fiction", "Loose", "a.txt"), "a")
    write(os.path.join(library, "Fiction", "Loose", "b.txt"), "b")
    write(os.path.join(library, "Misc", "Blank", "Blank [C].txt"), "  \n")
    write(os.path.join(library, "Misc", "stray note.txt"), "stray")
    with open(os.path.join(library, "Misc", "Old Letter [C].txt"), "wb"):
        pass
    os.makedirs(os.path.join(library, "Misc", "Old Letter"))
    with open(os.path.join(library, "Misc", "Old Letter", "Old Letter [C].txt"), "wb") as fh:
        fh.write("caf\xe9 ’quoted’".encode("cp1252"))
    before = sorted(os.path.join(d, f) for d, _, fs in os.walk(library) for f in fs)

    core.scan_and_sync()
    found = libcheck.run()
    assert _kinds(found) >= {
        ("no_draft", "Poetry/No Draft"),
        ("several_current", "Poetry/Two Current"),
        ("several_untagged", "Fiction/Loose"),
        ("empty", "Misc/Blank/Blank [C].txt"),
        ("loose_file", "Misc/stray note.txt"),
        ("not_utf8", "Misc/Old Letter/Old Letter [C].txt"),
    }
    # healthy entries aren't mentioned
    assert not any(i["path"].startswith("Poetry/Morning Tide") for i in found)
    two = next(i for i in found if i["kind"] == "several_current")
    assert two["detail"].startswith("Showing ")
    after = sorted(os.path.join(d, f) for d, _, fs in os.walk(library) for f in fs if ".minerva" not in d)
    assert after == [p for p in before if ".minerva" not in p]


def test_check_routes(client, library):
    core.configure(library)
    write(os.path.join(library, "Poetry", "Two Current", "A [C].txt"), "one")
    write(os.path.join(library, "Poetry", "Two Current", "B [C].txt"), "two")
    assert client.post("/api/sync").get_json()["issues"] == 1
    issues = client.get("/api/library/check").get_json()["issues"]
    assert issues[0]["kind"] == "several_current" and issues[0]["entry_id"]
    assert client.post("/api/library/reveal", json={"path": "../outside"}).status_code == 404
    assert client.post("/api/library/reveal", json={"path": ""}).status_code == 404

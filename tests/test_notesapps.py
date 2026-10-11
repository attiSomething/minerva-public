import io
import json
import os
import zipfile

import pytest

from minerva import core, notesapps

ENEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">
<en-export>
<note><title>Harbor Lines</title>
<content><![CDATA[<?xml version="1.0" encoding="UTF-8"?><en-note><div>the boats lean</div><div>into the wind</div><div><br/></div><div>second stanza</div></en-note>]]></content>
<created>20240301T101500Z</created><updated>20240302T080000Z</updated><tag>poems</tag><tag>sea</tag></note>
<note><title></title><content><![CDATA[<en-note><div>untitled thought here</div></en-note>]]></content></note>
</en-export>"""


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_evernote():
    items = notesapps.expand("Poetry.enex", ENEX)
    assert [i["title"] for i in items] == ["Harbor Lines", "untitled thought here"]
    assert items[0]["text"] == "the boats lean\ninto the wind\n\nsecond stanza\n"
    assert items[0]["fields"]["tags"] == ["poems", "sea", "Poetry"]
    assert items[0]["fields"]["notebook"] == "Poetry"
    assert items[0]["fields"]["modified"] == 1709366400.0
    with pytest.raises(notesapps.NotesExportError):
        notesapps.expand("bad.enex", b"<nope")


def test_google_keep_takeout():
    note = {"title": "Gulls", "textContent": "they argue", "labels": [{"name": "birds"}],
            "userEditedTimestampUsec": 1700000000000000, "isTrashed": False}
    todo = {"title": "", "listContent": [{"text": "buy rope", "isChecked": True}, {"text": "call Mara", "isChecked": False}],
            "createdTimestampUsec": 1600000000000000}
    trash = {"title": "Gone", "textContent": "x", "isTrashed": True, "createdTimestampUsec": 1}
    data = _zip({"Takeout/Keep/Gulls.json": json.dumps(note), "Takeout/Keep/Gulls.html": "<p>dup</p>",
                 "Takeout/Keep/List.json": json.dumps(todo), "Takeout/Keep/Gone.json": json.dumps(trash),
                 "Takeout/archive_browser.html": "<p>index</p>"})
    items = notesapps.expand("takeout-2026.zip", data)
    assert [i["title"] for i in items] == ["Gulls", "List"]
    assert items[0]["fields"]["tags"] == ["birds"] and items[0]["fields"]["modified"] == 1700000000.0
    assert items[1]["text"] == "[x] buy rope\n[ ] call Mara\n"
    # a single note's .json works too; any other .json doesn't
    assert notesapps.expand("Gulls.json", json.dumps(note).encode())[0]["title"] == "Gulls"
    with pytest.raises(notesapps.NotesExportError):
        notesapps.expand("package.json", b'{"name": "x"}')


def test_notion_and_plain_zips():
    data = _zip({
        "Export-1a2b/Poems 0123456789abcdef0123456789abcdef.md": "# Poems\nAn index page\n",
        "Export-1a2b/Poems 0123456789abcdef0123456789abcdef/Tide fedcba9876543210fedcba9876543210.md": "# Tide\nwater comes\n",
        "Export-1a2b/Poems 0123456789abcdef0123456789abcdef/table.csv": "a,b\n",
        "__MACOSX/._junk.md": "x",
    })
    items = notesapps.expand("Notion.zip", data)
    by = {i["title"]: i for i in items}
    assert set(by) == {"Poems", "Tide"}
    assert by["Tide"]["fields"]["tags"] == ["Poems"] and by["Tide"]["text"] == "water comes\n"
    assert "notebook" not in by["Poems"]["fields"]
    with pytest.raises(notesapps.NotesExportError):
        notesapps.expand("empty.zip", _zip({"pic.png": b"\x89PNG"}))
    assert notesapps.expand("story.docx", b"") is None


def test_import_route_and_dates(client, library):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    r = client.post("/api/import/files/preview", data={"files": [(io.BytesIO(ENEX), "Poetry.enex")]},
                    content_type="multipart/form-data").get_json()
    assert [i["title"] for i in r] == ["Harbor Lines", "untitled thought here"]
    made = client.post("/api/entries/new", json={"items": [{"title": r[0]["title"], "text": r[0]["text"], "tags": r[0]["fields"]["tags"],
                                                             "modified": r[0]["fields"]["modified"]}], "category": "Poetry"}).get_json()
    row = core.get_entry_row(core.get_conn(), made[0]["id"])
    path = os.path.join(core.entry_dir(row), row["draft_filename"])
    assert os.path.getmtime(path) == 1709366400.0
    assert row["started"] == "2024-03-02" or row["started"].startswith("2024-03")

import os
import sqlite3

import pytest

from minerva import core
from conftest import sha


def test_configure_indexes_existing_library(library):
    info = core.configure(library)
    assert info["imported_from"] is None
    assert info["scans_dir"] == "Sources"
    result = core.scan_and_sync()
    assert result["total_entries"] == 3
    assert os.path.isfile(os.path.join(library, ".minerva", "minerva.db"))
    # missing category folder is created, nothing else touched
    assert os.path.isdir(os.path.join(library, "Misc"))


def test_legacy_database_is_copied_not_modified(legacy_library):
    library, legacy_db = legacy_library
    before = sha(legacy_db)
    info = core.configure(library)
    assert info["imported_from"] == os.path.join("01A - Minerva", "minerva.db")
    core.scan_and_sync()
    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE title = 'Morning Tide'").fetchone()
    assert row["to_edit"] == 1 and row["published"] == 1
    assert row["published_where"] == "Harbor Review"
    assert [p["tag"] for p in core.list_projects(conn)] == ["LH"]
    conn.close()
    assert sha(legacy_db) == before


def test_legacy_import_happens_only_once(legacy_library):
    library, _ = legacy_library
    core.configure(library)
    conn = core.get_conn()
    conn.execute("UPDATE entries SET to_record = 1")
    conn.commit()
    conn.close()
    assert core.configure(library)["imported_from"] is None
    conn = core.get_conn()
    assert conn.execute("SELECT MIN(to_record) m FROM entries").fetchone()["m"] == 1
    conn.close()


def test_legacy_scans_folder_is_detected(tmp_path):
    root = tmp_path / "Old"
    (root / "0B - Reference" / "Old Project" / "Journal Scans").mkdir(parents=True)
    assert core.configure(str(root))["scans_dir"] == core.LEGACY_SCANS_DIR


def test_create_library(tmp_path):
    root = core.create_library(str(tmp_path), "My Writing")
    for sub in ["Fiction", "Nonfiction", "Poetry", "Misc", "Projects", "Sources"]:
        assert os.path.isdir(os.path.join(root, sub))
    with pytest.raises(ValueError):
        core.create_library(str(tmp_path), "bad:name")


def test_create_library_refuses_non_empty_folder(tmp_path):
    (tmp_path / "Existing").mkdir()
    (tmp_path / "Existing" / "note.txt").write_text("x")
    with pytest.raises(ValueError):
        core.create_library(str(tmp_path), "Existing")


def test_journal_scan_found_in_sources(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    row = conn.execute("SELECT * FROM entries WHERE title = 'Field Notes'").fetchone()
    scan = core.find_journal_scan_for_entry(row)
    conn.close()
    assert scan["available"]
    assert scan["pdf_name"] == "Blue Notebook 1.pdf"
    assert "Rain all week" in scan["excerpt"]


def test_save_with_archive_promotes_to_current(library):
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    eid = conn.execute("SELECT id FROM entries WHERE title = 'Field Notes'").fetchone()["id"]
    core.save_entry_content(conn, eid, "Rain all week, cleaned up.\n", "archive")
    row = core.get_entry_row(conn, eid)
    assert row["draft_tag"] == "C"
    archived = [a["name"] for a in core.list_archive(row)]
    conn.close()
    assert any(name.startswith("Field Notes") for name in archived)
    # the scan link survives the promotion
    core.scan_and_sync()
    conn = core.get_conn()
    assert core.get_entry_row(conn, eid)["source_journal"] == "Blue Notebook"
    conn.close()


def test_get_conn_before_configure_fails_clearly():
    with pytest.raises(RuntimeError):
        core.get_conn()

import hashlib
import os
import sqlite3

import keyring
import keyring.backend
import pytest

from minerva import core, server, winocr


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own app-config dir, an in-memory credential store,
    and a core module with no library open."""
    monkeypatch.setenv("MINERVA_CONFIG_DIR", str(tmp_path / "appconfig"))
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    for name in ("ARCHIVE_ROOT", "META_DIR", "DB_PATH", "PROJECTS_DIR", "JOURNAL_SCANS_DIR"):
        monkeypatch.setattr(core, name, None)
    monkeypatch.setattr(core, "TOP_FOLDERS", list(core.DEFAULT_CATEGORIES))
    # Windows' own OCR is off unless a test turns it on, so scanning tests
    # behave the same on every machine
    monkeypatch.setattr(winocr, "_available", {"ok": False, "language": ""})
    yield kr


@pytest.fixture
def library(tmp_path):
    """A small synthetic library. No real writing ever goes in the repo."""
    root = tmp_path / "Library"
    write(str(root / "Poetry" / "Morning Tide" / "Morning Tide [C].txt"), "The tide comes in\nand the gulls argue.\n")
    write(str(root / "Poetry" / "Morning Tide" / "Archive" / "Morning Tide (old).txt"), "The tide came in.\n")
    write(str(root / "Fiction" / "The Lighthouse - [LH]" / "The Lighthouse [C].txt"), "Once there was a keeper.\n")
    write(str(root / "Nonfiction" / "Field Notes" / "Field Notes [J].txt"),
          "Source: Blue Notebook Journal\nSource: Entry 2\n====\nRain all week.\n")
    write(str(root / "Sources" / "Blue Notebook" / "Blue Notebook - Master.txt"),
          "ENTRY 1 (Scan 1, Segment 1) - First\nhello\nENTRY 2 (Scan 1, Segment 2) - Second\nRain all week.\n")
    write(str(root / "Sources" / "Blue Notebook" / "Scans" / "Blue Notebook 1.pdf"), "%PDF-1.4 fake")
    return str(root)


@pytest.fixture
def legacy_library(library, tmp_path):
    """The library as the first Minerva left it: a database in
    '01A - Minerva/minerva.db' holding flags and a project."""
    legacy_db = os.path.join(library, "01A - Minerva", "minerva.db")
    os.makedirs(os.path.dirname(legacy_db))
    core.configure(library, db_path=legacy_db)
    core.scan_and_sync()
    conn = core.get_conn()
    conn.execute("INSERT INTO projects (name, tag, folder_path) VALUES ('Lighthouse', 'LH', 'Projects/Lighthouse')")
    eid = conn.execute("SELECT id FROM entries WHERE title = 'Morning Tide'").fetchone()["id"]
    core.update_flags(conn, eid, {"to_edit": True, "published": True, "published_where": "Harbor Review"})
    conn.commit()
    conn.close()
    # Undo what configure() wrote, so the folder looks like the old layout.
    os.remove(os.path.join(library, ".minerva", "library.json"))
    os.rmdir(os.path.join(library, ".minerva"))
    return library, legacy_db


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    c = server.app.test_client()
    c.environ_base["HTTP_X_MINERVA_TOKEN"] = server.SESSION_TOKEN
    return c

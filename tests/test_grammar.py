import json
import os
import stat
import threading
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from minerva import grammar


class FakeLT(BaseHTTPRequestHandler):
    """A stand-in LanguageTool server: flags "are" after "This", "teh",
    and lower-case line starts, the way the real one reports them."""
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send([{"name": "English (US)", "code": "en", "longCode": "en-US"}])

    def do_POST(self):
        form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        FakeLT.seen.append(form)
        text, off = form["text"], set((form.get("disabledRules") or "").split(","))
        matches = []
        for word, rule, issue, cat, fix in [("This are", "THIS_NNS", "grammatical", "GRAMMAR", "This is"),
                                            ("teh", "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS", "the")]:
            at = text.find(word)
            while at >= 0 and rule not in off:
                matches.append({"message": f"Did you mean {fix}?", "offset": at, "length": len(word),
                                "replacements": [{"value": fix}],
                                "rule": {"id": rule, "description": rule, "issueType": issue, "category": {"id": cat, "name": cat}}})
                at = text.find(word, at + 1)
        for i, ch in enumerate(text):
            if ch.isupper() and i and text[i - 1] == "\n" and "LINE_CAPS" not in off:
                matches.append({"message": "Capital in mid-sentence.", "offset": i, "length": 1, "replacements": [{"value": ch.lower()}],
                                "rule": {"id": "LINE_CAPS", "issueType": "typographical", "category": {"id": "CASING", "name": "Capitalization"}}})
        self._send({"language": {"name": "English (US)"}, "matches": matches})


@pytest.fixture
def lt():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeLT.seen = []
    grammar.save_settings({"server": f"http://127.0.0.1:{srv.server_port}"})
    yield srv
    srv.shutdown()


def test_check_and_offsets(lt):
    text = "This are fine.\nAnd teh tide\n"
    r = grammar.check(text)
    got = [(m["text"], m["replacements"], m["kind"]) for m in r["matches"]]
    assert ("This are", ["This is"], "grammar") in got and ("teh", ["the"], "spelling") in got
    assert all(text[m["offset"]:m["offset"] + m["length"]] == m["text"] for m in r["matches"])
    assert r["language"] == "English (US)" and FakeLT.seen[-1]["language"] == "en-US"
    assert "disabledRules" not in FakeLT.seen[-1]
    # a poem: line-start capitals aren't flagged, and verse rules are off
    poem = grammar.check(text, poem=True)
    assert "And" not in [m["text"] for m in poem["matches"]] and any(m["text"] == "A" for m in r["matches"])
    assert "UPPERCASE_SENTENCE_START" in FakeLT.seen[-1]["disabledRules"]


def test_header_isnt_checked_and_long_text_is_split(lt):
    text = "Source: Blue Notebook\nThis are header\n=====\n\nThis are body.\n"
    r = grammar.check(text)
    assert [m["offset"] for m in r["matches"] if m["text"] == "This are"] == [text.rindex("This are")]
    long = ("This are a stanza line.\n" * 40 + "\n") * 30
    r = grammar.check(long)
    assert len(FakeLT.seen) > 2 and all(len(f["text"]) <= grammar.CHUNK for f in FakeLT.seen[-3:])
    assert len([m for m in r["matches"] if m["text"] == "This are"]) == long.count("This are")
    assert all(long[m["offset"]:m["offset"] + m["length"]] == m["text"] for m in r["matches"])


def test_word_list_and_ignored_rules(lt):
    grammar.add_word("teh")
    grammar.ignore_rule("THIS_NNS")
    r = grammar.check("This are teh tide.")
    assert r["matches"] == [] and "THIS_NNS" in FakeLT.seen[-1]["disabledRules"]
    with pytest.raises(grammar.GrammarError):
        grammar.save_settings({"server": "ftp://nope"})
    with pytest.raises(grammar.GrammarError):
        grammar.save_settings({"language": "xx"})


def test_routes(client, lt):
    s = client.get("/api/grammar").get_json()
    assert s["ready"] and s["own_server"].startswith("http://127.0.0.1")
    r = client.post("/api/grammar/check", json={"text": "This are fine.", "poem": True}).get_json()
    assert r["matches"][0]["replacements"] == ["This is"]
    assert client.post("/api/grammar/check", json={"text": "  "}).status_code == 400
    assert "teh" in client.post("/api/grammar/ignore", json={"word": "teh"}).get_json()["words"]
    assert client.post("/api/grammar", json={"server": "nope"}).status_code == 400


def test_not_set_up(monkeypatch):
    monkeypatch.setattr(grammar, "server_jar", lambda: None)
    assert not grammar.status()["ready"]
    with pytest.raises(grammar.GrammarError, match="isn't set up"):
        grammar.check("Hello")


def test_java_version(monkeypatch):
    class R:
        def __init__(self, err):
            self.stderr = err.encode()
    for err, want in [('openjdk version "21.0.5" 2024-10-15', 21), ('java version "1.8.0_401"', 8),
                      ('openjdk version "17" 2021-09-14', 17), ("nonsense", 0)]:
        monkeypatch.setattr(grammar.subprocess, "run", lambda *a, **k: R(err))
        assert grammar._java_version("java") == want


@pytest.mark.skipif(os.name == "nt", reason="uses a shell script as a stand-in java")
def test_install(tmp_path, monkeypatch):
    fake_java = "#!/bin/sh\necho 'openjdk version \"21.0.5\" 2024-10-15' >&2\n"
    jre = tmp_path / "jre.zip"
    with zipfile.ZipFile(jre, "w") as z:
        info = zipfile.ZipInfo("jdk-21.0.5+11-jre/bin/java")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        z.writestr(info, fake_java)
    lt_zip = tmp_path / "lt.zip"
    with zipfile.ZipFile(lt_zip, "w") as z:
        z.writestr("LanguageTool-6.8/languagetool-server.jar", b"PK fake")
    monkeypatch.setattr(grammar, "JRE_URL", jre.as_uri())
    monkeypatch.setattr(grammar, "JRE_CHECKSUM_URL", (tmp_path / "missing.txt").as_uri())
    monkeypatch.setattr(grammar, "LT_URL", lt_zip.as_uri())
    monkeypatch.setattr(grammar, "can_install", lambda: True)
    monkeypatch.setattr(grammar.shutil, "which", lambda name: None)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    grammar._java_cache.clear()
    monkeypatch.setattr(grammar, "check", lambda *a, **k: {"matches": [{"text": "This are"}], "language": "English"})

    class Job:
        def progress(self, *a):
            pass

        def cancelled(self):
            return False
    assert grammar.status()["download_mb"] == 305
    # zip extraction keeps the permission bits only on some platforms
    orig_extract = grammar._extract

    def extract(*a):
        orig_extract(*a)
        for p in grammar.glob.glob(os.path.join(grammar._tools(), "jre", "*", "bin", "java")):
            os.chmod(p, 0o755)
    monkeypatch.setattr(grammar, "_extract", extract)
    r = grammar.install(Job())
    assert r["installed"] and r["java"] and r["test"] == [{"text": "This are"}]
    assert grammar.server_jar().endswith(os.path.join("LanguageTool-6.8", "languagetool-server.jar"))
    assert grammar.remove()["installed"] is False


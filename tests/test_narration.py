import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
import wave
import zipfile

import pytest

from conftest import write
from minerva import core, mediatools, narration, secrets_store, sharing

RATE = 16000


class FakeJob:
    def __init__(self):
        self.messages = []

    def progress(self, done, total, message=""):
        self.messages.append(message)

    def cancelled(self):
        return False


def _tone(seconds):
    return b"\x10\x00" * int(RATE * seconds)


def fake_system(lines, voice, rate, folder, job):
    """Windows' voice stand-in: a tenth of a second per word."""
    paths = []
    for i, line in enumerate(lines, 1):
        path = os.path.join(folder, f"{i:05d}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(_tone(0.1 * len(line.split())))
        paths.append(path)
    return paths


@pytest.fixture
def lib(library, monkeypatch):
    write(os.path.join(library, "Poetry", "Salt Hymn", "Salt Hymn [C].txt"),
          "Salt on the sill\n  salt in the hymn.\n\nA second stanza\nends here.\n")
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    monkeypatch.setattr(narration, "_system_synth", fake_system)
    yield library, conn
    conn.close()


def _id(conn, title):
    return conn.execute("SELECT id FROM entries WHERE title = ?", (title,)).fetchone()["id"]


def _project(conn):
    core.create_project(conn, "Tide Book", "TB")
    pid = next(p["id"] for p in core.list_projects(conn) if p["name"] == "Tide Book")
    core.set_entry_project(conn, _id(conn, "Salt Hymn"), "TB")
    core.set_entry_project(conn, _id(conn, "Morning Tide"), "TB")
    core.set_project_order(conn, pid, [_id(conn, "Salt Hymn"), _id(conn, "Morning Tide")])
    sharing.save_project_settings(conn, pid, {"author": "A. Writer"})
    return pid


def test_script_keeps_stanzas_and_splits_long_paragraphs():
    parts = narration.script([{"title": "Salt Hymn", "body": "Salt on the sill\n  salt in the hymn.\n\nA second\n"}])
    assert parts[0]["stanzas"] == [["Salt Hymn"], ["Salt on the sill", "salt in the hymn."], ["A second"]]
    assert narration.characters(parts) == len("Salt Hymn") + len("Salt on the sill") + len("salt in the hymn.") + 8
    assert narration.script([{"title": "T", "body": "x"}], titles=False)[0]["stanzas"] == [["x"]]
    long = " ".join(["A sentence that runs on."] * 200)
    pieces = narration._split_long(long, 2500)
    assert len(pieces) > 1 and all(len(p) <= 2500 for p in pieces) and " ".join(pieces) == long


def test_entry_with_this_computers_voice(lib):
    library, conn = lib
    r = narration.narrate(FakeJob(), conn, "entry", _id(conn, "Salt Hymn"), {"engine": "system", "format": "wav"})
    [f] = r["files"]
    assert f["name"] == "Salt Hymn - narration.wav" and f["folder"] == "Exports"
    with wave.open(os.path.join(library, "Exports", f["name"])) as w:
        seconds = w.getnframes() / w.getframerate()
    # 2 + 4 + 4 + 3 + 2 words, a title gap, a stanza gap and two line gaps
    assert seconds == pytest.approx(1.5 + narration.TITLE_GAP + narration.STANZA_GAP + 2 * narration.LINE_GAP, abs=0.01)
    t = narration.timings(f["name"])
    assert [x["text"] for x in t["lines"]] == ["Salt Hymn", "Salt on the sill", "salt in the hymn.", "A second stanza", "ends here."]
    assert t["lines"][0]["title"] and not t["lines"][1]["title"]
    assert t["lines"][1]["start"] == pytest.approx(0.2 + narration.TITLE_GAP, abs=0.01)
    # kept in .minerva, not next to the audio
    assert os.path.isfile(os.path.join(library, ".minerva", "narrations", f["name"] + ".json"))


def test_project_as_one_file_or_one_per_piece(lib):
    library, conn = lib
    pid = _project(conn)
    r = narration.narrate(FakeJob(), conn, "project", pid, {"engine": "system", "format": "wav", "split": "one"})
    [f] = r["files"]
    assert f["name"] == "Tide Book - audiobook.wav"
    t = narration.timings(f["name"])
    assert [c["title"] for c in t["chapters"]] == ["Salt Hymn", "Morning Tide"] and t["author"] == "A. Writer"
    second = [x for x in t["lines"] if x["chapter"] == 1]
    assert second[0]["text"] == "Morning Tide" and second[0]["start"] == pytest.approx(t["chapters"][1]["start"])
    r = narration.narrate(FakeJob(), conn, "project", pid, {"engine": "system", "format": "wav", "split": "each"})
    assert [f["name"] for f in r["files"]] == ["Salt Hymn - narration.wav", "Morning Tide - narration.wav"]


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")
def test_mp3_with_chapters(lib):
    library, conn = lib
    pid = _project(conn)
    r = narration.narrate(FakeJob(), conn, "project", pid, {"engine": "system", "format": "mp3", "split": "one"})
    path = os.path.join(library, "Exports", r["files"][0]["name"])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json", path],
                                      capture_output=True).stdout)
    assert [c["tags"]["title"] for c in probe["chapters"]] == ["Salt Hymn", "Morning Tide"]
    assert probe["format"]["tags"]["title"] == "Tide Book" and probe["format"]["tags"]["artist"] == "A. Writer"
    assert not [n for n in os.listdir(os.path.join(library, "Exports")) if "minerva-tmp" in n]


def test_mp3_needs_the_tool(lib, monkeypatch):
    library, conn = lib
    monkeypatch.setattr(mediatools, "ffmpeg", lambda: None)
    with pytest.raises(narration.NarrationError, match="audio and video tool"):
        narration.narrate(FakeJob(), conn, "entry", _id(conn, "Salt Hymn"), {"engine": "system", "format": "mp3"})


def test_elevenlabs(lib, monkeypatch):
    library, conn = lib
    sent = []

    def fake_el(path, key, body=None, timeout=60):
        assert key == "el-key"
        if path == "/v1/voices":
            return {"voices": [{"voice_id": "v2", "name": "Rachel"}, {"voice_id": "v1", "name": "Adam"}]}
        if path == "/v1/user/subscription":
            return {"character_limit": 10000, "character_count": 2500, "tier": "starter"}
        assert path == "/v1/text-to-speech/v1/with-timestamps?output_format=pcm_24000"
        sent.append(body)
        text = body["text"]
        # a fiftieth of a second per character
        return {"audio_base64": base64.b64encode(b"\x01\x00" * int(len(text) * 0.02 * 24000)).decode(),
                "alignment": {"characters": list(text),
                              "character_start_times_seconds": [i * 0.02 for i in range(len(text))],
                              "character_end_times_seconds": [(i + 1) * 0.02 for i in range(len(text))]}}
    monkeypatch.setattr(narration, "_el", fake_el)
    with pytest.raises(narration.NarrationError, match="key"):
        narration.narrate(FakeJob(), conn, "entry", _id(conn, "Salt Hymn"), {"engine": "elevenlabs", "format": "wav"})
    narration.save_key(" el-key ")
    assert secrets_store.get_key("elevenlabs") == "el-key"
    assert [v["name"] for v in narration.el_voices()] == ["Adam", "Rachel"]
    est = narration.estimate(conn, "entry", _id(conn, "Salt Hymn"), engine="elevenlabs")
    assert est["credits"] == est["characters"] and est["account"]["left"] == 7500

    r = narration.narrate(FakeJob(), conn, "entry", _id(conn, "Salt Hymn"),
                          {"engine": "elevenlabs", "el_voice": "v1", "format": "wav", "pace": "slower"})
    assert len(sent) == 1 and sent[0]["text"] == "Salt Hymn\n\nSalt on the sill\nsalt in the hymn.\n\nA second stanza\nends here."
    assert sent[0]["voice_settings"]["speed"] == 0.85 and sent[0]["model_id"] == narration.EL_MODEL
    lines = narration.timings(r["files"][0]["name"])["lines"]
    third = sent[0]["text"].index("salt in")
    assert lines[2]["text"] == "salt in the hymn." and lines[2]["start"] == pytest.approx(third * 0.02)
    assert lines[2]["end"] == pytest.approx((third + len("salt in the hymn.")) * 0.02)


def test_elevenlabs_splits_long_work_with_context(monkeypatch):
    stanzas = [[f"Line {i} " + "word " * 60] for i in range(40)]
    chunks = list(narration._chunks(stanzas))
    assert len(chunks) > 1 and all(sum(len(x) + 2 for s in c for x in s) <= narration.EL_CHUNK + 400 for c in chunks)
    assert [s for c in chunks for s in c] == stanzas


def test_routes(client, lib, monkeypatch):
    library, conn = lib
    monkeypatch.setattr(narration, "_voices", {"available": True, "voices": [{"name": "Microsoft Zira"}], "default": "Microsoft Zira"})
    o = client.get("/api/narration/options").get_json()
    assert o["system"]["voices"][0]["name"] == "Microsoft Zira" and o["prefs"]["engine"] == "system"
    assert not o["elevenlabs"]["has_key"]
    sid = _id(conn, "Salt Hymn")
    e = client.post("/api/narration/estimate", json={"kind": "entry", "id": sid}).get_json()
    assert e["pieces"] == 1 and e["minutes"] == 1
    assert client.post("/api/narration/estimate", json={"kind": "nope", "id": sid}).status_code == 400
    j = client.post("/api/narration/start", json={"kind": "entry", "id": sid, "engine": "system", "format": "wav",
                                                  "voice": "Microsoft Zira", "title": "Salt Hymn"}).get_json()
    for _ in range(100):
        j = client.get(f"/api/jobs/{j['id']}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", j
    assert j["result"]["files"][0]["name"] == "Salt Hymn - narration.wav"
    # the choices are remembered
    assert narration.prefs()["voice"] == "Microsoft Zira" and narration.prefs()["format"] == "wav"


def test_installing_the_tool(tmp_path, monkeypatch):
    exe = b"MZ fake ffmpeg"
    wheel = tmp_path / "w.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe", exe)
    data = wheel.read_bytes()
    monkeypatch.setattr(mediatools, "WHEEL", mediatools.WHEEL | {"url": wheel.as_uri(), "sha256": hashlib.sha256(data).hexdigest()})
    monkeypatch.setattr(mediatools, "can_install", lambda: True)
    monkeypatch.setattr(mediatools.shutil, "which", lambda name: None)
    assert not mediatools.status()["ffmpeg"]
    mediatools.install(FakeJob())
    assert open(os.path.join(mediatools._tools_dir(), "ffmpeg.exe"), "rb").read() == exe
    # a download that doesn't match is thrown away
    os.remove(os.path.join(mediatools._tools_dir(), "ffmpeg.exe"))
    monkeypatch.setattr(mediatools, "WHEEL", mediatools.WHEEL | {"sha256": "0" * 64})
    with pytest.raises(mediatools.MediaError, match="didn't match"):
        mediatools.install(FakeJob())
    assert not os.path.exists(os.path.join(mediatools._tools_dir(), "ffmpeg.exe"))


@pytest.mark.skipif(os.name != "nt", reason="Windows' own voices")
def test_real_windows_voices(tmp_path, monkeypatch):
    monkeypatch.setattr(narration, "_voices", None)
    v = narration.system_voices()
    if not v["available"]:
        pytest.skip("no voices installed on this machine")
    paths = narration._system_synth(["The heron stands.", "Patient as a question."], v["voices"][0]["name"], 1.2,
                                    str(tmp_path), FakeJob())
    track = narration.Track()
    for p in paths:
        track.add_wav(p)
    assert track.rate and track.seconds() > 0.5

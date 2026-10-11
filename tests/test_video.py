import io
import json
import os
import shutil
import subprocess
import time

import pytest
from PIL import Image

from minerva import core, narration, sharing, video

from test_narration import FakeJob, _project, fake_system
from conftest import write


@pytest.fixture
def made(library, monkeypatch):
    write(os.path.join(library, "Poetry", "Salt Hymn", "Salt Hymn [C].txt"),
          "Salt on the sill\n  salt in the hymn.\n\nA second stanza\nends here.\n")
    core.configure(library)
    core.scan_and_sync()
    conn = core.get_conn()
    monkeypatch.setattr(narration, "_system_synth", fake_system)
    pid = _project(conn)
    r = narration.narrate(FakeJob(), conn, "project", pid, {"engine": "system", "format": "wav", "split": "one"})
    yield library, conn, pid, r["files"][0]["name"]
    conn.close()


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 120, 40)).save(buf, "PNG")
    return buf.getvalue()


def test_screens_follow_the_lines(made):
    library, conn, pid, name = made
    t = narration.timings(name)
    s = video.screens(t)
    assert len(s) == len(t["lines"])
    # a title card, then the stanza with each line picked out in turn
    assert s[0][4] == "Salt Hymn" and s[0][3] == "A. Writer" and s[0][0] == 0.0
    assert s[1][1] == ["Salt on the sill", "salt in the hymn."] and (s[1][2], s[2][2]) == (0, 1)
    assert s[1][3] == "Salt Hymn"  # the chapter's title heads its screens
    assert [x[0] for x in s] == sorted(x[0] for x in s)
    found = video.narrations("project", pid)
    assert found[0]["name"] == name and found[0]["mine"] and not found[0]["has_cover"]


def test_frames_and_backgrounds(made):
    library, conn, pid, name = made
    for size, (w, h, *_rest) in video.SIZES.items():
        bg = video.background(size, Image.open(io.BytesIO(_png())))
        assert bg.size == (w, h)
        f = video.frame(bg, size, ["A line", "the second, which is a good deal longer and has to wrap " * 3], 1, "Salt Hymn")
        assert f.size == (w, h) and f.mode == "RGB"
    plain = video.background("square")
    assert plain.getpixel((0, 0)) == video.PLAIN[0]
    # a stanza far too long for the screen still fits, around the current line
    many = [f"Line number {i} of a long stanza" for i in range(80)]
    assert video.frame(video.background("wide"), "wide", many, 70).size == (1920, 1080)
    png = video.preview(name, "vertical", "image", _png())
    assert Image.open(io.BytesIO(png)).size == (304, 540)
    with pytest.raises(video.VideoError, match="picture"):
        video.preview(name, "square", "image", b"not an image")


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")
def test_make_video(made):
    library, conn, pid, name = made
    sharing.set_cover(pid, "front", "cover.png", _png())
    r = video.make(FakeJob(), name, "square", "cover")
    assert r["name"] == "Tide Book - audiobook - video (square).mp4"
    path = os.path.join(library, "Exports", r["name"])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                                      capture_output=True).stdout)
    v = next(x for x in probe["streams"] if x["codec_type"] == "video")
    assert (v["width"], v["height"], v["codec_name"]) == (1080, 1080, "h264")
    assert any(x["codec_type"] == "audio" for x in probe["streams"])
    assert abs(float(probe["format"]["duration"]) - narration.timings(name)["seconds"]) < 0.5
    assert not [n for n in os.listdir(os.path.join(library, "Exports")) if "minerva-tmp" in n]


def test_routes(client, made, monkeypatch):
    library, conn, pid, name = made
    o = client.get(f"/api/video/options?kind=project&id={pid}").get_json()
    assert o["narrations"][0]["name"] == name and set(o["sizes"]) == {"square", "vertical", "wide"}
    r = client.post("/api/video/preview", data={"name": name, "size": "wide", "background": "image",
                                                "image": (io.BytesIO(_png()), "bg.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert client.post("/api/video/preview", json={"name": name, "size": "huge"}).status_code == 400
    assert client.post("/api/video/start", json={"name": "nope.wav", "size": "square"}).status_code == 400
    monkeypatch.setattr(video.mediatools, "ffmpeg", lambda: None)
    j = client.post("/api/video/start", json={"name": name, "size": "square", "background": "plain"}).get_json()
    for _ in range(100):
        j = client.get(f"/api/jobs/{j['id']}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "failed" and "audio and video tool" in j["error"]


def test_prose_paragraphs_show_a_few_sentences_at_a_time():
    para = " ".join(f"Sentence number {i} goes on for a little while." for i in range(30))
    t = {"title": "Notes", "lines": [{"text": para, "start": 1.0, "end": 31.0, "stanza": 0}]}
    s = video.screens(t)
    assert len(s) > 5 and all(len(x[1][0]) <= video.CHUNK for x in s)
    assert " ".join(x[1][0] for x in s) == para
    assert s[0][0] == 0.0 and s[-1][0] < 31.0 and [x[0] for x in s] == sorted(x[0] for x in s)
    # one enormous word-free run still breaks between words
    assert all(len(c) <= video.CHUNK for c in video._display_chunks("word " * 400))

import os
import time

import pytest
from PIL import Image, ImageDraw, ImageFont

from minerva import ai, config as app_config, scanning, winocr
from test_scanning import _enable, make_pdf, notebook, post  # noqa: F401  (fixture)

TYPED = ["The heron stands in the shallows and waits,", "patient as a question that nobody has thought",
         "to ask of the river, or of the morning, or of me."]


def _line(text, y, h=30, jitter=0):
    x, out = 50, []
    for i, word in enumerate(text.split()):
        out.append({"t": word, "x": x, "y": y, "w": 12 * len(word), "h": h + (jitter * (i % 3))})
        x += 12 * len(word) + 10
    return out


def test_typed_lines_read_as_typed():
    lines = [_line(t, 100 + 50 * i) for i, t in enumerate(TYPED)]
    assert winocr.looks_typed(lines, "en-US")
    assert winocr.looks_typed(lines, "fr-FR")


def test_handwriting_fragments_do_not():
    garbled = [_line("tlie lwr0n st@nds iu ~ sliallows wa1ts", 100), _line("pa% ient a$ qu3stion", 150, 80),
               _line("u0b0dy l|as tlrought", 230, 18)]
    assert not winocr.looks_typed(garbled, "en-US")
    # real-looking words in wildly uneven lines are handwriting too
    uneven = [_line(TYPED[0], 100, 20), _line(TYPED[1], 150, 60), _line(TYPED[2], 260, 25), _line("and more of it", 300, 90)]
    assert not winocr.looks_typed(uneven, "en-US")
    assert not winocr.looks_typed([_line("too few words", 100)], "en-US")


def test_powershell_single_items_are_unwrapped():
    one_word = {"lines": {"words": {"t": "Hello", "x": 1, "y": 1, "w": 5, "h": 9}}}
    got = winocr._page(one_word, "en-US")
    assert got["text"] == "Hello" and got["words"] == 1 and not got["typed"]
    assert winocr._page({"lines": None}, "en-US")["text"] == ""


def test_typed_pages_are_read_free_and_handwriting_waits(notebook, monkeypatch):
    def read_page(image):
        read_page.n += 1
        if read_page.n == 2 or read_page.n > 3:
            return {"text": "sc@wl", "words": 1, "typed": False, "language": "en-US"}
        return {"text": TYPED[0] if read_page.n == 1 else "and the nets dry slow.", "words": 9, "typed": True,
                "language": "en-US"}
    read_page.n = 0
    monkeypatch.setattr(winocr, "read_page", read_page)
    monkeypatch.setattr(ai, "complete", lambda *a, **k: pytest.fail("no model is set up"))
    stats = {}
    out = scanning.transcribe_scan("Green Notebook", 1, None, None, None, ocr=True, stats=stats)
    assert stats == {"free": 2, "ai": 0, "left": 1}
    pages = scanning.cached_pages("Green Notebook", 1)
    assert set(pages) == {1, 3} and pages[1]["model"] == "windows/ocr"
    # page 3 follows a page left unread, so it starts something new
    assert not pages[3]["continues"]
    assert out and "SEGMENT 2" not in open(os.path.join(scanning.text_output_dir("Green Notebook"), out), encoding="utf-8").read()

    # with a model turned on later, only the handwritten page goes to it
    sent = []

    def complete(provider, model, key, system, prompt, images=(), **kw):
        sent.append(prompt)
        return "TEXT:\nin my own hand\nUNCERTAIN: none"
    monkeypatch.setattr(ai, "complete", complete)
    stats = {}
    scanning.transcribe_scan("Green Notebook", 1, "anthropic", "m", "k", ocr=True, stats=stats)
    assert stats == {"free": 0, "ai": 1, "left": 0} and "page 2 of 3" in sent[0]


def test_continues_guess():
    assert scanning._continues("the boats come home", "and the nets dry")
    assert scanning._continues("the boats come home,", "And the nets dry")
    assert not scanning._continues("the boats came home.", "Wind from the east.")
    assert not scanning._continues("", "and so")


def test_route_works_with_ai_off_only_when_ocr_can(client, notebook, monkeypatch):
    monkeypatch.setattr(winocr, "available", lambda: {"ok": False, "language": ""})
    assert post(client, "/api/scans/Green Notebook/transcribe", {"scans": [1]}).get_json()["ai_off"]
    assert client.get("/api/ai/status").get_json()["scanning"]["builtin_ocr"] is False

    monkeypatch.setattr(winocr, "available", lambda: {"ok": True, "language": "en-US"})
    monkeypatch.setattr(winocr, "read_page", lambda image: {"text": TYPED[0], "words": 9, "typed": True, "language": "en-US"})
    j = post(client, "/api/scans/Green Notebook/transcribe", {"scans": [1]}).get_json()
    for _ in range(100):
        j = client.get(f"/api/jobs/{j['id']}").get_json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["pages"] == {"free": 3, "ai": 0, "left": 0}

    assert client.get("/api/settings/ocr").get_json() == {"enabled": True, "available": True, "language": "en-US"}
    post(client, "/api/settings/ocr", {"enabled": False})
    assert app_config.load()["builtin_ocr"] is False
    assert post(client, "/api/scans/Green Notebook/transcribe", {"scans": [1], "redo": True}).get_json()["ai_off"]
    _enable("scanning")
    assert not post(client, "/api/scans/Green Notebook/estimate", {"scans": [1]}).get_json()["builtin_ocr"]


@pytest.mark.skipif(os.name != "nt", reason="Windows' own text recognition")
def test_windows_reads_a_typed_page(monkeypatch):
    monkeypatch.setattr(winocr, "_available", None)  # really look
    if not winocr.available()["ok"]:
        pytest.skip("no OCR language installed on this Windows")
    img = Image.new("RGB", (1400, 500), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("times.ttf", 40)
    except OSError:
        font = ImageFont.load_default(size=40)
    for i, line in enumerate(TYPED):
        draw.text((60, 80 + i * 90), line, fill="black", font=font)
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    got = winocr.read_page(buf.getvalue())
    assert got and got["typed"], got
    assert "heron" in got["text"].lower() and "river" in got["text"].lower()

import os

import pytest

from minerva import images, scanning

from test_scanning import make_pdf, notebook, post  # noqa: F401  (fixture)

SEP = "=" * 60
MASTER = "\n".join([
    SEP, "ENTRY 1 (Scan 1, Segment 1) — Harbor Song", "Date: 3/4/21", SEP,
    "The boats come home", "at [dusk]", "",
    SEP, "ENTRY 2 (Scan 1, Segment 2)", "Date: February 23rd, 2018", "Location: Pier 9", SEP,
    "[Drawing of a lighthouse with three gulls]", "",
    SEP, "ENTRY 3 (Scan 1, Segment 3)", "Date: none", SEP,
    "Notes on the tide.", "[Small diagram of the harbor mouth]", "",
    SEP, "ENTRY 4 (Scan 2, Segment 1)", "Date: 2018-03-01", SEP,
    "[Blank page]", "",
    SEP, "ENTRY 5 (Scan 9, Segment 1)", "Date: none", SEP,
    "[Stamp from the post office in Salem]", "",
])


@pytest.fixture
def drawn(notebook):  # noqa: F811
    src = os.path.join(notebook, "Sources", "Green Notebook")
    make_pdf(os.path.join(src, "Scans", "Green Notebook 2.pdf"), 1)
    with open(os.path.join(src, "Green Notebook - Master.txt"), "w", encoding="utf-8") as fh:
        fh.write(MASTER)
    return src


def test_bracketed_descriptions_become_images_with_kinds_and_names(drawn):
    found = {i["num"]: i for i in images.for_source("Green Notebook")}
    # the uncertain word "[dusk]" and the blank page aren't drawings
    assert sorted(found) == [2, 3, 5]
    # scan 9 doesn't exist, so there's no page to save
    assert (found[5]["kind"], found[5]["pages"]) == ("Uncategorized", [])
    gulls, harbor = found[2], found[3]
    assert (gulls["kind"], gulls["has_text"], gulls["pages"]) == ("Drawing", False, [[1, 2]])
    assert gulls["name"] == "2018-02-23 Lighthouse With Three Gulls (Pier 9)"
    assert (harbor["kind"], harbor["has_text"]) == ("Diagram", True)
    assert harbor["name"] == "Undated Harbor Mouth"


def test_guessing_and_naming_helpers():
    assert images.guess_kind("a doodle in the margin") == "Drawing"
    assert images.guess_kind("a stamp") == "Uncategorized"
    assert images.iso_date("3/4/21") == "2021-03-04" and images.iso_date("spring") == ""
    assert images.safe_name('a/b: "c"?') == "ab c"


def test_saving_copies_pages_and_never_overwrites(drawn):
    first = images.save("Green Notebook", [{"num": 2}, {"num": 3, "kind": "Drawing", "name": "Mouth"}])
    assert first == ["Images/Drawing/2018-02-23 Lighthouse With Three Gulls (Pier 9).jpg",
                     "Images/Drawing/Mouth.jpg"]
    with open(os.path.join(drawn, first[0]), "rb") as fh:
        assert fh.read(2) == b"\xff\xd8"
    again = images.save("Green Notebook", [{"num": 3, "name": "Mouth"}])
    assert again == ["Images/Diagram/Mouth.jpg"]
    third = images.save("Green Notebook", [{"num": 3, "kind": "Drawing", "name": "Mouth"}])
    assert third == ["Images/Drawing/Mouth (2).jpg"]
    saved = {i["num"]: i["saved"] for i in images.for_source("Green Notebook")}
    assert len(saved[3]) == 3 and saved[2] == first[:1]
    for bad in ([{"num": 1}], [{"num": 5}], [{"num": 2, "kind": "Photo"}], [{"num": 2, "name": "///"}]):
        with pytest.raises(scanning.ScanError):
            images.save("Green Notebook", bad)


def test_image_routes(client, drawn):
    data = client.get("/api/images").get_json()
    assert data["kinds"] == ["Diagram", "Drawing", "Uncategorized"]
    assert [i["num"] for i in data["images"]] == [2, 3, 5]
    r = post(client, "/api/images/save", {"source": "Green Notebook", "items": [{"num": 2}]})
    assert r.get_json()["written"][0].startswith("Images/Drawing/")
    assert post(client, "/api/images/save", {"source": "../x", "items": [{"num": 2}]}).status_code == 400

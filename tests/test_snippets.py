import pytest

from minerva import manuscript, snippets


def test_save_fill_delete(client):
    manuscript.save_contact({"name": "A. Writer", "email": "a@example.com"})
    s = snippets.save({"name": "Cover", "kind": "cover", "body": "Dear {venue},\r\nPlease read {title}.\n{name} {email} {editor}"})
    assert snippets.fill(s["body"], {"venue": "Harbor Review", "title": "Low Water"}) == \
        "Dear Harbor Review,\nPlease read Low Water.\nA. Writer a@example.com {editor}"
    # a missing value leaves the placeholder showing
    assert snippets.fill("Dear {venue}", {"venue": ""}) == "Dear {venue}"
    snippets.save({"id": s["id"], "name": "Cover letter", "kind": "nonsense", "body": "Hi"})
    assert [(x["name"], x["kind"]) for x in snippets.all_snippets()] == [("Cover letter", "other")]
    with pytest.raises(snippets.SnippetError):
        snippets.save({"name": " ", "body": "x"})
    snippets.delete(s["id"])
    assert snippets.all_snippets() == []


def test_routes(client):
    r = client.post("/api/snippets", json={"starters": True}).get_json()
    assert [s["kind"] for s in r["snippets"]] == ["cover", "bio_short"] and "venue" in r["placeholders"]
    # starters aren't added twice
    assert len(client.post("/api/snippets", json={"starters": True}).get_json()["snippets"]) == 2
    sid = r["snippets"][0]["id"]
    text = client.post(f"/api/snippets/{sid}/fill", json={"venue": "Salt Quarterly", "title": "Gull Song"}).get_json()["text"]
    assert text.startswith("Dear Editors of Salt Quarterly,") and '"Gull Song"' in text
    # a book's Author line can stand in for {name}
    bio = r["snippets"][1]["id"]
    assert client.post(f"/api/snippets/{bio}/fill", json={"name": "A. Writer"}).get_json()["text"].startswith("A. Writer writes")
    assert client.post("/api/snippets", json={"name": ""}).status_code == 400
    assert len(client.delete(f"/api/snippets/{sid}").get_json()["snippets"]) == 1

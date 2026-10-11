import os

from minerva import ai, config, server


def test_post_without_token_is_rejected(library):
    c = server.app.test_client()
    r = c.post("/api/setup/library", json={"mode": "open", "path": library})
    assert r.status_code == 403


def test_library_routes_wait_for_setup(client):
    assert client.get("/api/entries").status_code == 409


def test_onboarding_flow(client, legacy_library):
    library, _ = legacy_library
    status = client.get("/api/setup/status").get_json()
    assert status["onboarded"] is False

    info = client.post("/api/setup/inspect", json={"path": library}).get_json()
    assert info["earlier_minerva_found"] is True
    assert "Poetry" in info["categories_present"]

    r = client.post("/api/setup/library", json={"mode": "open", "path": library}).get_json()
    assert r["total_entries"] == 3
    assert r["imported_from"]

    assert client.post("/api/setup/complete").status_code == 200
    status = client.get("/api/setup/status").get_json()
    assert status["onboarded"] is True
    assert config.load()["library_root"] == os.path.abspath(library)

    entries = client.get("/api/entries").get_json()
    assert entries["total"] == 3
    morning = next(e for e in entries["rows"] if e["title"] == "Morning Tide")
    assert morning["to_edit"] == 1


def test_create_library_via_api(client, tmp_path):
    r = client.post("/api/setup/library",
                    json={"mode": "create", "parent": str(tmp_path), "name": "Fresh"})
    assert r.status_code == 200
    assert r.get_json()["total_entries"] == 0


def test_restore_last_library(client, library):
    client.post("/api/setup/library", json={"mode": "open", "path": library})
    from minerva import core
    core.ARCHIVE_ROOT = core.DB_PATH = None
    assert server.restore_last_library()["total_entries"] == 3


def test_ai_key_is_stored_but_never_returned(client, isolated):
    r = client.post("/api/settings/ai", json={
        "feature": "scanning", "enabled": True, "provider": "anthropic",
        "model": "claude-opus-5-5", "api_key": "sk-ant-test-123",
    }).get_json()
    assert r["features"]["scanning"]["has_key"] is True
    assert "sk-ant-test-123" not in str(r)
    assert isolated.store[("Minerva", "anthropic")] == "sk-ant-test-123"
    saved = open(os.path.join(config.config_dir(), "config.json")).read()
    assert "sk-ant" not in saved
    client.delete("/api/settings/ai/key/anthropic")
    assert ("Minerva", "anthropic") not in isolated.store


def test_ai_test_reports_failures_as_messages(client, monkeypatch):
    def boom(provider, key):
        raise ai.ProviderError("The key was rejected.")
    monkeypatch.setattr(ai, "list_models", boom)
    r = client.post("/api/settings/ai/test", json={"provider": "openai", "api_key": "x"}).get_json()
    assert r == {"ok": False, "error": "The key was rejected."}


def test_key_required_for_hosted_providers():
    try:
        ai.list_models("anthropic", None)
    except ai.ProviderError as e:
        assert "key" in str(e)
    else:
        raise AssertionError("expected ProviderError")


def test_index_page_carries_token(client):
    html = client.get("/").get_data(as_text=True)
    assert server.SESSION_TOKEN in html
    assert "onboarding.js" in html


def test_ai_errors_include_provider_message():
    import anthropic
    from minerva import ai

    err = anthropic.BadRequestError.__new__(anthropic.BadRequestError)
    err.status_code = 400
    err.body = {"type": "error", "error": {"type": "invalid_request_error",
                                           "message": "Explain the problem"}}

    class Models:
        def list(self, **kw):
            raise err

    class Client:
        def __init__(self, **kw):
            self.models = Models()

    orig = anthropic.Anthropic
    anthropic.Anthropic = Client
    try:
        try:
            ai.list_models("anthropic", " sk-ant-x\n")
        except ai.ProviderError as e:
            assert "(400): Explain the problem" in str(e)
        else:
            raise AssertionError("expected ProviderError")
    finally:
        anthropic.Anthropic = orig


def test_clean_key_strips_whitespace():
    from minerva import ai
    assert ai.clean_key("  sk-ant-\tabc\r\n") == "sk-ant-abc"

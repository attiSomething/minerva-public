import time

import pytest

from minerva import ai, config as app_config, jobs, localai


class FakeJob:
    def __init__(self):
        self.steps = []

    def progress(self, done, total, message=""):
        self.steps.append(message)

    def cancelled(self):
        return False


def _machine(monkeypatch, memory, gpu=None, disk=200.0, running=True, models=()):
    monkeypatch.setattr(localai, "_memory_gb", lambda: memory)
    monkeypatch.setattr(localai, "_gpu", lambda: gpu)
    monkeypatch.setattr(localai, "_disk_free_gb", lambda: disk)
    monkeypatch.setattr(localai, "ollama_version", lambda: "0.12.0" if running else None)
    monkeypatch.setattr(localai, "ollama_models", lambda: list(models))


@pytest.mark.parametrize("memory,gpu,want", [
    (32, None, "qwen3-vl:8b"),
    (8, {"name": "RTX", "memory_gb": 12}, "qwen3-vl:8b"),
    (12, None, "qwen3-vl:4b"),
    (6, None, "qwen3-vl:2b"),
])
def test_recommends_a_model_sized_to_the_computer(monkeypatch, memory, gpu, want):
    _machine(monkeypatch, memory, gpu)
    c = localai.check()
    assert c["recommendation"]["model"] == want
    pick = next(m for m in c["recommendation"]["choices"] if m["name"] == want)
    assert pick["fits"] and pick["room"] and pick["size_gb"] > 0 and pick["speed"]
    if gpu:
        assert "graphics card" in pick["speed"]
    if memory < 8:
        assert any("memory" in w for w in c["recommendation"]["warnings"])


def test_low_disk_steps_down_and_says_why(monkeypatch):
    _machine(monkeypatch, 32, disk=5.0)
    rec = localai.check()["recommendation"]
    assert rec["model"] == "qwen3-vl:4b"
    assert any("disk space" in w for w in rec["warnings"])
    assert not next(m for m in rec["choices"] if m["name"] == "qwen3-vl:8b")["room"]


def test_a_downloaded_model_needs_no_room(monkeypatch):
    _machine(monkeypatch, 32, disk=1.0, models=["qwen3-vl:8b"])
    rec = localai.check()["recommendation"]
    assert rec["model"] == "qwen3-vl:8b" and not rec["warnings"]
    assert next(m for m in rec["choices"] if m["name"] == "qwen3-vl:8b")["downloaded"]


def test_setup_pulls_tests_and_turns_features_on(monkeypatch):
    _machine(monkeypatch, 16)
    pulled = []

    def pull_lines(model):
        pulled.append(model)
        yield {"status": "pulling manifest"}
        yield {"status": "pulling abc", "digest": "sha256:abc", "total": 100, "completed": 40}
        yield {"status": "pulling abc", "digest": "sha256:abc", "total": 100, "completed": 100}
        yield {"status": "success"}

    monkeypatch.setattr(localai, "_pull_lines", pull_lines)
    seen = {}

    def complete(provider, model, key, system, prompt, images=(), **kw):
        seen.update(provider=provider, model=model, image=images[0][1][:8])
        return "\n".join(localai.TEST_LINES)

    monkeypatch.setattr(ai, "complete", complete)
    job = FakeJob()
    result = localai.setup(job, "qwen3-vl:4b", ["scanning"])
    assert pulled == ["qwen3-vl:4b"]
    assert seen["provider"] == "ollama" and seen["image"].startswith(b"\x89PNG")
    assert result["ok"] and result["features"] == ["scanning"]
    assert any("Downloading qwen3-vl:4b" in s for s in job.steps)
    cfg = app_config.load()["ai"]
    assert cfg["scanning"] == {"enabled": True, "provider": "ollama", "model": "qwen3-vl:4b"}
    assert not cfg["organizing"]["enabled"]


def test_a_misread_test_page_leaves_settings_alone(monkeypatch):
    _machine(monkeypatch, 16, models=["qwen3-vl:2b"])
    monkeypatch.setattr(localai, "_pull_lines", lambda m: pytest.fail("already downloaded"))
    monkeypatch.setattr(ai, "complete", lambda *a, **k: "The hen stands in the shadows")
    result = localai.setup(FakeJob(), "qwen3-vl:2b", ["scanning", "organizing"])
    assert not result["ok"] and result["features"] == []
    assert not app_config.load()["ai"]["scanning"]["enabled"]


def test_ollama_missing_off_windows_points_to_the_download(monkeypatch):
    _machine(monkeypatch, 16, running=False)
    monkeypatch.setattr(localai, "ollama_exe", lambda: None)
    monkeypatch.setattr(localai, "can_install", lambda: False)
    with pytest.raises(localai.LocalAiError, match="ollama.com"):
        localai.setup(FakeJob(), "qwen3-vl:4b", ["scanning"])


def test_pull_errors_are_reported(monkeypatch):
    monkeypatch.setattr(localai, "_pull_lines", lambda m: iter([{"error": "file does not exist"}]))
    with pytest.raises(localai.LocalAiError, match="file does not exist"):
        localai.pull_model(FakeJob(), "qwen3-vl:4b")


def test_routes(client, monkeypatch):
    _machine(monkeypatch, 16, models=["qwen3-vl:4b"])
    r = client.get("/api/localai/check").get_json()
    assert r["recommendation"]["model"] == "qwen3-vl:8b" and r["jobs"] == []
    assert client.post("/api/localai/setup", json={"model": "llama-something"}).status_code == 400
    assert client.post("/api/localai/use", json={"model": "qwen3-vl:8b", "features": ["scanning"]}).status_code == 400

    monkeypatch.setattr(ai, "complete", lambda *a, **k: "\n".join(localai.TEST_LINES))
    j = client.post("/api/localai/setup", json={"model": "qwen3-vl:4b", "features": ["organizing"]}).get_json()
    for _ in range(50):
        j = jobs.get(j["id"]).to_dict()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["ok"]
    assert app_config.load()["ai"]["organizing"]["provider"] == "ollama"

    s = client.post("/api/localai/use", json={"model": "qwen3-vl:4b", "features": ["scanning"]}).get_json()
    assert s["features"]["scanning"]["enabled"] and s["features"]["scanning"]["model"] == "qwen3-vl:4b"

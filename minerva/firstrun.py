"""The Getting started card on Home: one piece taken from a draft to a
submission and a PDF. Each step is marked done when the writer does it
anywhere in Minerva, or skipped from the card. The state is an app
setting, kept with Minerva's other settings and never in the library."""

from . import config as app_config

STEPS = ("draft", "edit", "submission", "pdf")


def _state(cfg):
    fr = cfg.get("first_run") or {}
    return {"done": [s for s in fr.get("done", []) if s in STEPS], "dismissed": bool(fr.get("dismissed"))}


def mark(step):
    """Note that a step was done (or skipped). Cheap to call repeatedly."""
    if step not in STEPS:
        return
    cfg = app_config.load()
    fr = _state(cfg)
    if step in fr["done"]:
        return
    fr["done"].append(step)
    cfg["first_run"] = fr
    app_config.save(cfg)


def dismiss(dismissed=True):
    cfg = app_config.load()
    fr = _state(cfg)
    fr["dismissed"] = bool(dismissed)
    cfg["first_run"] = fr
    app_config.save(cfg)


def status(conn):
    fr = _state(app_config.load())
    latest = conn.execute("SELECT id, title FROM entries ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "steps": {s: s in fr["done"] for s in STEPS},
        "dismissed": fr["dismissed"],
        "latest": {"id": latest["id"], "title": latest["title"]} if latest else None,
    }

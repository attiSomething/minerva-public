"""App-level settings (which library is open, which AI features are on).

Stored as JSON in the user's app-data folder, never inside the library or
the repo. API keys are not kept here; see secrets_store.py.
"""

import json
import os
import sys

FEATURES = ("scanning", "organizing")
# the styles in Settings > Customization; the first is the default
THEMES = ("athena", "dark-athena", "tarofied", "fifth-impact", "liched-up")
USERNAME_MAX = 40


def config_dir():
    override = os.environ.get("MINERVA_CONFIG_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Minerva")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Minerva")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "minerva")


def _path():
    return os.path.join(config_dir(), "config.json")


def default_config():
    return {
        "library_root": None,
        "onboarded": False,
        "theme": THEMES[0],
        "username": "",
        # read typed scan pages with Windows' own text recognition first
        "builtin_ocr": True,
        "ai": {
            feature: {"enabled": False, "provider": "anthropic", "model": ""}
            for feature in FEATURES
        },
    }


def load():
    cfg = default_config()
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        return cfg
    cfg.update({k: v for k, v in saved.items() if k != "ai"})
    for feature in FEATURES:
        cfg["ai"][feature].update((saved.get("ai") or {}).get(feature) or {})
    if cfg.get("theme") not in THEMES:
        cfg["theme"] = THEMES[0]
    return cfg


def clean_username(name):
    """A display name only (Minerva has no accounts): printable, one line,
    at most USERNAME_MAX characters."""
    name = "".join(" " if ch.isspace() else ch for ch in str(name or "") if ch.isspace() or ch.isprintable())
    name = " ".join(name.split())
    return name[:USERNAME_MAX]


def save(cfg):
    os.makedirs(config_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.replace(tmp, _path())

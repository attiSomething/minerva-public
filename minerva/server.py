"""
Minerva's local web server. The desktop window (desktop.py) and the
browser fallback both talk to this over 127.0.0.1 only.
"""

import logging
import os
import secrets

from flask import Flask, abort, jsonify, request, render_template, send_file

from . import __version__
from . import ai
from . import backup
from . import config as app_config
from . import core
from . import exportall
from . import goals
from . import images
from . import intake
from . import replace as replacing
from . import research
from . import fileimport
from . import firstrun
from . import foldersync
from . import notesapps
from . import sample as sample_lib
from . import jobs
from . import launch
from . import logs
from . import libcheck
from . import grammar
from . import localai
from . import mediatools
from . import narration
from . import updates
from . import video
from . import organizing
from . import manuscript, notes, outline, pagelinks, people, scanning
from . import scanintake
from . import search
from . import secrets_store
from . import sharing
from . import snippets
from . import stats
from . import submissions
from . import subimport
from . import subemail
from . import tags
from . import upcoming
from . import views
from . import winocr

app = Flask(__name__)

# Every state-changing request must carry this per-run token, which only
# Minerva's own page knows. It stops other web pages open in a browser from
# poking at the local server.
SESSION_TOKEN = secrets.token_urlsafe(24)


@app.before_request
def _guard():
    if not request.path.startswith("/api/"):
        return None
    logs.request_started(request.path)
    if request.method != "GET" and request.headers.get("X-Minerva-Token") != SESSION_TOKEN:
        abort(403)
    if request.path.startswith(("/api/setup", "/api/settings", "/api/localai", "/api/grammar", "/api/updates", "/api/snippets", "/api/health", "/api/docs", "/api/howtos", "/api/launch", "/api/log")):
        return None
    if not core.is_configured():
        return jsonify({"error": "no library is open yet"}), 409
    return None


@app.after_request
def _log_request(resp):
    if request.path.startswith("/api/"):
        logs.request_finished(request.method, request.path, resp.status_code)
    return resp


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
def index():
    cfg = app_config.load()
    return render_template("index.html", token=SESSION_TOKEN, version=__version__,
                           theme=cfg["theme"], username=cfg["username"])


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "version": __version__})


# --------------------------------------------------------------------------
# Library + onboarding
# --------------------------------------------------------------------------

def open_library(path, step=None):
    """Open a library and index it. step(label, percent), if given, hears
    how far along it is: 10% for opening, up to 85% while reading entry
    folders, then up to 99% for the library check."""
    step = step or (lambda label, percent: None)
    step("Opening your library", 10)
    info = core.configure(path)

    def reading(done, total):
        step(f"Reading your library: {done:,} of {total:,} folders" if total else "Reading your library",
             15 + (70 * done / total if total else 70))

    sync = core.scan_and_sync(progress=reading)
    libcheck.run(progress=lambda done, total: step(
        f"Checking your library: {done:,} of {total:,} folders", 85 + 14 * done / max(total, 1)))
    cfg = app_config.load()
    cfg["library_root"] = info["library_root"]
    app_config.save(cfg)
    return info | {"total_entries": sync["total_entries"]}


def restore_last_library(step=None):
    """Re-open whatever library was open last time, if it's still there."""
    step = step or (lambda label, percent: None)
    step("Reading your settings", 3)
    cfg = app_config.load()
    root = cfg.get("library_root")
    if not root:
        return None
    step(f"Looking for your library at {root}", 6)
    if not os.path.isdir(root):
        logs.log.warning("The last library, %s, isn't there now", root)
        return None
    try:
        return open_library(root, step)
    except Exception:
        logs.log.exception("Couldn't reopen the library at %s", root)
        return None


def start_launch():
    """Open the last library behind the launch screen."""
    launch.start(restore_last_library)


# --------------------------------------------------------------------------
# Launch progress and logs
# --------------------------------------------------------------------------

@app.route("/api/launch")
def api_launch():
    return jsonify(launch.status())


@app.route("/api/launch/retry", methods=["POST"])
def api_launch_retry():
    logs.log.info("Launch: Try again pressed")
    start_launch()
    return jsonify(launch.status())


@app.route("/api/launch/ready", methods=["POST"])
def api_launch_ready():
    body = request.get_json(force=True, silent=True) or {}
    try:
        seconds = float(body.get("seconds") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    launch.home_ready(seconds)
    return jsonify({"ok": True})


@app.route("/api/log", methods=["POST"])
def api_log():
    """Lines from the page: errors it caught and how long Home took."""
    body = request.get_json(force=True, silent=True) or {}
    level = {"error": logging.ERROR, "warning": logging.WARNING}.get(body.get("level"), logging.INFO)
    logs.log.log(level, "Page: %s", str(body.get("message") or "")[:4000])
    return jsonify({"ok": True})


@app.route("/api/logs")
def api_logs():
    return jsonify({"folder": logs.logs_dir(), "recent": logs.recent()})


@app.route("/api/logs/save", methods=["POST"])
def api_logs_save():
    extra = {"Library": core.ARCHIVE_ROOT or "none open", "Launch": launch.status()}
    try:
        path = logs.save_zip(extra=extra)
    except OSError as e:
        return jsonify({"error": f"Couldn't save the logs: {e}"}), 400
    _reveal(path)
    return jsonify({"path": path})


@app.route("/api/logs/reveal", methods=["POST"])
def api_logs_reveal():
    os.makedirs(logs.logs_dir(), exist_ok=True)
    return _reveal(logs.logs_dir())


@app.route("/api/setup/status")
def api_setup_status():
    cfg = app_config.load()
    return jsonify({
        "onboarded": bool(cfg.get("onboarded")) and core.is_configured(),
        "library_root": core.ARCHIVE_ROOT,
        "remembered_library": cfg.get("library_root"),
        "categories": core.TOP_FOLDERS,
        "version": __version__,
        "is_sample": sample_lib.is_sample(core.ARCHIVE_ROOT),
        "library_before_sample": cfg.get("library_before_sample"),
    })


@app.route("/api/setup/inspect", methods=["POST"])
def api_setup_inspect():
    """Describe a folder before the user commits to it."""
    path = (request.get_json(force=True).get("path") or "").strip()
    if not path or not os.path.isdir(path):
        return jsonify({"error": "That folder doesn't exist."}), 400
    present = [c for c in core.DEFAULT_CATEGORIES if os.path.isdir(os.path.join(path, c))]
    return jsonify({
        "path": os.path.abspath(path),
        "categories_present": present,
        "has_minerva_data": os.path.isdir(os.path.join(path, core.META_DIRNAME)),
        "earlier_minerva_found": bool(core.find_legacy_db(path)),
    })


@app.route("/api/setup/library", methods=["POST"])
def api_setup_library():
    body = request.get_json(force=True)
    mode = body.get("mode", "open")
    try:
        if mode == "create":
            path = core.create_library(body.get("parent", ""), body.get("name", ""))
        else:
            path = (body.get("path") or "").strip()
        result = open_library(path)
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route("/api/setup/sample", methods=["POST"])
def api_setup_sample():
    """Open the sample library (made-up writing in its own folder beside
    Minerva's settings), creating it the first time or when asked to start
    over. The writer's own library is remembered, never touched."""
    body = request.get_json(force=True, silent=True) or {}
    before = core.ARCHIVE_ROOT
    try:
        root, fresh = sample_lib.create(start_over=bool(body.get("start_over")))
        result = open_library(root)
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    if fresh:
        conn = core.get_conn()
        try:
            sample_lib.fill(conn)
        finally:
            conn.close()
    cfg = app_config.load()
    if before and not sample_lib.is_sample(before):
        cfg["library_before_sample"] = before
        app_config.save(cfg)
    return jsonify(result | {"is_sample": True})


@app.route("/api/setup/sample/leave", methods=["POST"])
def api_setup_sample_leave():
    """Go back from the sample to the library that was open before it."""
    cfg = app_config.load()
    back = cfg.get("library_before_sample")
    if not back or not os.path.isdir(back):
        return jsonify({"error": "Minerva doesn't know which library to go back to. Open it from Settings > Library."}), 400
    try:
        result = open_library(back)
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@app.route("/api/firstrun")
def api_firstrun():
    return _with_conn(lambda conn: jsonify(firstrun.status(conn)))


@app.route("/api/firstrun", methods=["POST"])
def api_firstrun_update():
    body = request.get_json(force=True, silent=True) or {}
    if body.get("done"):
        firstrun.mark(body["done"])
    if "dismissed" in body:
        firstrun.dismiss(body["dismissed"])
    return _with_conn(lambda conn: jsonify(firstrun.status(conn)))


@app.route("/api/setup/complete", methods=["POST"])
def api_setup_complete():
    if not core.is_configured():
        return jsonify({"error": "choose a library folder first"}), 400
    cfg = app_config.load()
    cfg["onboarded"] = True
    app_config.save(cfg)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# AI settings (keys go to the OS credential store, never back to the page)
# --------------------------------------------------------------------------

def _ai_settings_payload():
    cfg = app_config.load()
    features = {}
    for feature, settings in cfg["ai"].items():
        features[feature] = settings | {"has_key": secrets_store.has_key(settings.get("provider", ""))}
    return {"features": features, "providers": ai.public_providers()}


@app.route("/api/settings/profile")
def api_get_profile():
    cfg = app_config.load()
    return jsonify({"username": cfg["username"], "theme": cfg["theme"], "themes": list(app_config.THEMES)})


@app.route("/api/settings/profile", methods=["POST"])
def api_set_profile():
    body = request.get_json(force=True) or {}
    cfg = app_config.load()
    if "theme" in body:
        if body["theme"] not in app_config.THEMES:
            return jsonify({"error": "That style isn't available."}), 400
        cfg["theme"] = body["theme"]
    if "username" in body:
        cfg["username"] = app_config.clean_username(body["username"])
    app_config.save(cfg)
    return jsonify({"username": cfg["username"], "theme": cfg["theme"]})


@app.route("/api/settings/contact")
def api_get_contact():
    return jsonify(manuscript.contact())


@app.route("/api/settings/contact", methods=["POST"])
def api_set_contact():
    return jsonify(manuscript.save_contact(request.get_json(force=True) or {}))


@app.errorhandler(snippets.SnippetError)
def _snippet_error(e):
    return jsonify({"error": str(e)}), 400


def _snippets_payload():
    return {"snippets": snippets.all_snippets(), "kinds": snippets.KINDS, "placeholders": snippets.PLACEHOLDERS}


@app.route("/api/snippets")
def api_snippets():
    return jsonify(_snippets_payload())


@app.route("/api/snippets", methods=["POST"])
def api_save_snippet():
    body = request.get_json(force=True) or {}
    if body.get("starters"):
        snippets.add_starters()
    else:
        snippets.save(body)
    return jsonify(_snippets_payload())


@app.route("/api/snippets/<sid>", methods=["DELETE"])
def api_delete_snippet(sid):
    snippets.delete(sid)
    return jsonify(_snippets_payload())


@app.route("/api/snippets/<sid>/fill", methods=["POST"])
def api_fill_snippet(sid):
    s = snippets.get(sid)
    if s is None:
        return jsonify({"error": "That snippet no longer exists."}), 404
    body = request.get_json(force=True) or {}
    return jsonify({"text": snippets.fill(s["body"], {k: body.get(k) for k in ("venue", "title", "name")})})


@app.route("/api/settings/ai")
def api_get_ai_settings():
    return jsonify(_ai_settings_payload())


@app.route("/api/settings/ai", methods=["POST"])
def api_set_ai_settings():
    body = request.get_json(force=True)
    feature = body.get("feature")
    if feature not in app_config.FEATURES:
        return jsonify({"error": "unknown feature"}), 400
    provider = body.get("provider") or "anthropic"
    if provider not in ai.PROVIDERS:
        return jsonify({"error": "unknown provider"}), 400
    key = ai.clean_key(body.get("api_key"))
    if key:
        try:
            secrets_store.set_key(provider, key)
        except Exception as e:
            return jsonify({"error": f"Couldn't save the key to the system credential store: {e}"}), 500
    cfg = app_config.load()
    cfg["ai"][feature] = {
        "enabled": bool(body.get("enabled")),
        "provider": provider,
        "model": (body.get("model") or "").strip(),
    }
    app_config.save(cfg)
    return jsonify(_ai_settings_payload())


@app.route("/api/settings/ai/test", methods=["POST"])
def api_test_ai():
    body = request.get_json(force=True)
    provider = body.get("provider") or "anthropic"
    key = ai.clean_key(body.get("api_key")) or secrets_store.get_key(provider)
    try:
        models = ai.list_models(provider, key)
    except ai.ProviderError as e:
        return jsonify({"ok": False, "error": str(e)}), 200
    return jsonify({"ok": True, "models": models})


@app.route("/api/localai/check")
def api_localai_check():
    return jsonify(localai.check() | {"jobs": jobs.active("localai")})


@app.route("/api/localai/setup", methods=["POST"])
def api_localai_setup():
    body = request.get_json(force=True) or {}
    model = body.get("model") or ""
    features = [f for f in body.get("features") or app_config.FEATURES if f in app_config.FEATURES]
    if model not in {m["name"] for m in localai.MODELS}:
        return jsonify({"error": "Pick one of the suggested models."}), 400
    try:
        job = jobs.start("localai", model, lambda job: localai.setup(job, model, features))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/localai/use", methods=["POST"])
def api_localai_use():
    """Turn the features on with a local model whose test page came back
    wrong, when the user says to use it anyway."""
    body = request.get_json(force=True) or {}
    model = body.get("model") or ""
    if model not in localai.ollama_models():
        return jsonify({"error": "That model isn't downloaded."}), 400
    localai.use(model, [f for f in body.get("features") or [] if f in app_config.FEATURES])
    return jsonify(_ai_settings_payload())


# ---- narration -------------------------------------------------------------

@app.route("/api/narration/options")
def api_narration_options():
    return jsonify({
        "engines": narration.ENGINES, "paces": narration.PACE_LABELS, "prefs": narration.prefs(),
        "system": narration.system_voices(), "elevenlabs": {"has_key": bool(narration.el_key())},
        "tools": mediatools.status(), "jobs": jobs.active("narration") + jobs.active("mediatools"),
    })


@app.route("/api/narration/voices")
def api_narration_voices():
    """ElevenLabs voices on the writer's account (asks ElevenLabs)."""
    try:
        return jsonify({"voices": narration.el_voices(), "account": narration.el_credits()})
    except narration.NarrationError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/narration/key", methods=["POST", "DELETE"])
def api_narration_key():
    if request.method == "DELETE":
        secrets_store.delete_key(narration.EL_KEY)
        return jsonify({"has_key": False})
    try:
        narration.save_key((request.get_json(force=True) or {}).get("key"))
    except narration.NarrationError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"has_key": True})


def _narration_target(body):
    kind = body.get("kind")
    try:
        item_id = int(body.get("id"))
    except (TypeError, ValueError):
        item_id = 0
    if kind not in ("entry", "project") or not item_id:
        abort(400)
    return kind, item_id


@app.route("/api/narration/estimate", methods=["POST"])
def api_narration_estimate():
    body = request.get_json(force=True) or {}
    kind, item_id = _narration_target(body)
    conn = core.get_conn()
    try:
        return jsonify(narration.estimate(conn, kind, item_id, body.get("which") or "final",
                                          body.get("engine") or "system", body.get("titles", True) is not False))
    except narration.NarrationError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/narration/start", methods=["POST"])
def api_narration_start():
    body = request.get_json(force=True) or {}
    kind, item_id = _narration_target(body)
    opts = {k: body.get(k) for k in ("engine", "voice", "el_voice", "pace", "split", "format", "titles", "which")}
    narration.save_prefs(narration.prefs() | {k: v for k, v in opts.items() if v is not None})

    def work(job):
        conn = core.get_conn()
        try:
            return narration.narrate(job, conn, kind, item_id, opts)
        finally:
            conn.close()
    try:
        job = jobs.start("narration", body.get("title") or "a narration", work)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/video/options")
def api_video_options():
    kind = request.args.get("kind")
    try:
        item_id = int(request.args.get("id") or 0)
    except ValueError:
        item_id = 0
    return jsonify({"narrations": video.narrations(kind, item_id),
                    "sizes": {k: {"label": v[2], "for": v[3], "width": v[0], "height": v[1]} for k, v in video.SIZES.items()},
                    "tools": mediatools.status(), "jobs": jobs.active("video") + jobs.active("mediatools")})


def _video_request():
    form = request.form if request.files or request.form else (request.get_json(silent=True) or {})
    upload = request.files.get("image")
    return form.get("name") or "", form.get("size") or "", form.get("background") or "plain", \
        upload.read() if upload else None


@app.route("/api/video/preview", methods=["POST"])
def api_video_preview():
    name, size, bg, image = _video_request()
    try:
        png = video.preview(name, size, bg, image)
    except video.VideoError as e:
        return jsonify({"error": str(e)}), 400
    return app.response_class(png, mimetype="image/png")


@app.route("/api/video/start", methods=["POST"])
def api_video_start():
    name, size, bg, image = _video_request()
    if not narration.timings(name):
        return jsonify({"error": "Choose a narration."}), 400
    try:
        job = jobs.start("video", name, lambda job: video.make(job, name, size, bg, image))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


# ---- updates -------------------------------------------------------------------

@app.route("/api/updates")
def api_updates():
    return jsonify(updates.status() | {"jobs": jobs.active("update")})


@app.route("/api/updates/check", methods=["POST"])
def api_updates_check():
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(updates.check(force=bool(body.get("force"))))
    except updates.UpdateError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/updates/prefs", methods=["POST"])
def api_updates_prefs():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(updates.set_prefs(body.get("auto"), body.get("skipped")))


@app.route("/api/updates/install", methods=["POST"])
def api_updates_install():
    try:
        job = jobs.start("update", "the update", updates.install)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/updates/restart", methods=["POST"])
def api_updates_restart():
    try:
        updates.restart()
    except updates.UpdateError as e:
        return jsonify({"error": str(e)}), 400
    import threading

    def leave():
        grammar.stop()
        os._exit(0)
    threading.Timer(1.0, leave).start()
    return jsonify({"ok": True})


# ---- grammar and style (LanguageTool) -----------------------------------------

@app.route("/api/grammar", methods=["GET", "POST"])
def api_grammar():
    if request.method == "POST":
        try:
            grammar.save_settings(request.get_json(force=True) or {})
        except grammar.GrammarError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify(grammar.status() | {"jobs": jobs.active("grammar")})


@app.route("/api/grammar/setup", methods=["POST"])
def api_grammar_setup():
    try:
        job = jobs.start("grammar", "LanguageTool", grammar.install)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/grammar/remove", methods=["POST"])
def api_grammar_remove():
    return jsonify(grammar.remove())


@app.route("/api/grammar/check", methods=["POST"])
def api_grammar_check():
    body = request.get_json(force=True) or {}
    text = body.get("text") or ""
    if not text.strip():
        return jsonify({"error": "There's no text to check."}), 400
    try:
        return jsonify(grammar.check(text, body.get("language"), bool(body.get("poem"))))
    except grammar.GrammarError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/grammar/ignore", methods=["POST"])
def api_grammar_ignore():
    body = request.get_json(force=True) or {}
    try:
        s = grammar.add_word(body["word"]) if body.get("word") else grammar.ignore_rule(body.get("rule") or "")
    except grammar.GrammarError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(s)


@app.route("/api/media/tools", methods=["GET", "POST"])
def api_media_tools():
    if request.method == "GET":
        return jsonify(mediatools.status())
    try:
        job = jobs.start("mediatools", "the audio and video tool", mediatools.install)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/settings/ai/key/<provider>", methods=["DELETE"])
def api_forget_key(provider):
    secrets_store.delete_key(provider)
    return jsonify(_ai_settings_payload())


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------

@app.route("/api/sync", methods=["POST"])
def api_sync():
    result = core.scan_and_sync()
    result["issues"] = len(libcheck.run())
    return jsonify(result)


@app.route("/api/goals")
def api_get_goals():
    conn = core.get_conn()
    try:
        return jsonify(goals.progress(conn))
    finally:
        conn.close()


@app.route("/api/goals", methods=["POST"])
def api_set_goals():
    try:
        goals.set_goals(request.get_json(force=True) or {})
    except goals.GoalError as e:
        return jsonify({"error": str(e)}), 400
    return api_get_goals()


@app.route("/api/search")
def api_search():
    a = request.args
    conn = core.get_conn()
    try:
        return jsonify(search.find(conn, a.get("q", ""), category=a.get("category") or None,
                                   project=a.get("project") or None, current_only=a.get("current") == "1",
                                   tag=a.get("tag") or None))
    finally:
        conn.close()


@app.route("/api/library/check")
def api_library_check():
    conn = core.get_conn()
    try:
        found = libcheck.entry_ids(conn, libcheck.issues())
        lost = notes.lost(conn)
    finally:
        conn.close()
    return jsonify({"issues": found, "lost_notes": lost})


@app.route("/api/library/reveal", methods=["POST"])
def api_library_reveal():
    """Show a file or folder from the library in Explorer (never runs it)."""
    body = request.get_json(force=True, silent=True) or {}
    rel = str(body.get("path") or "")
    path = os.path.normpath(os.path.join(core.ARCHIVE_ROOT, rel))
    if not path.startswith(os.path.normpath(core.ARCHIVE_ROOT) + os.sep) or not os.path.exists(path):
        return jsonify({"error": "That isn't in your library anymore. Try Rescan."}), 404
    return _reveal(path)


def _reveal(path):
    try:
        logs.reveal(path)
    except OSError as e:
        return jsonify({"error": f"Couldn't open it: {e}"}), 400
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------

@app.errorhandler(intake.IntakeError)
def _intake_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/entries/new", methods=["POST"])
def api_new_entries():
    """Create entries from the New entry dialog: one blank or pasted piece,
    or several pieces split from a paste."""
    body = request.get_json(force=True) or {}
    items = body.get("items")
    if not isinstance(items, list):
        items = [{"title": body.get("title"), "text": body.get("text") or ""}]
    made = _with_conn(lambda conn: jsonify(intake.create_entries(
        conn, items, body.get("category"), body.get("project") or None)))
    if made.status_code == 200:
        firstrun.mark("draft")
    return made


@app.errorhandler(foldersync.SyncError)
def _sync_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/sync/sources")
def api_sync_sources():
    return _with_conn(lambda conn: jsonify(foldersync.list_sources(conn)))


@app.route("/api/sync/sources", methods=["POST"])
def api_sync_add():
    body = request.get_json(force=True, silent=True) or {}
    return _with_conn(lambda conn: jsonify(foldersync.add_source(conn, body.get("path"), body.get("category"))))


@app.route("/api/sync/sources/<int:source_id>/delete", methods=["POST"])
def api_sync_remove(source_id):
    def run(conn):
        foldersync.remove_source(conn, source_id)
        return jsonify({"ok": True})
    return _with_conn(run)


@app.route("/api/sync/sources/<int:source_id>/mapping")
def api_sync_overview(source_id):
    return _with_conn(lambda conn: jsonify(foldersync.overview(conn, source_id)))


@app.route("/api/sync/sources/<int:source_id>/mapping", methods=["POST"])
def api_sync_mapping(source_id):
    body = request.get_json(force=True, silent=True) or {}
    return _with_conn(lambda conn: jsonify(foldersync.save_mapping(
        conn, source_id, body.get("default_category"), body.get("folder_map"), body.get("tag_map"))))


@app.route("/api/sync/pending")
def api_sync_pending():
    return _with_conn(lambda conn: jsonify(foldersync.pending(conn)))


@app.route("/api/sync/apply", methods=["POST"])
def api_sync_apply():
    body = request.get_json(force=True, silent=True) or {}
    return _with_conn(lambda conn: jsonify(foldersync.apply(conn, body.get("choices"))))


@app.route("/api/import/files/preview", methods=["POST"])
def api_import_files_preview():
    """Read the uploaded files and say what each would become. Nothing is
    written."""
    files = request.files.getlist("files")
    if not files:
        raise intake.IntakeError("Choose one or more files.")
    if len(files) > intake.MAX_PIECES:
        raise intake.IntakeError(f"Choose at most {intake.MAX_PIECES} files at a time.")

    def run(conn):
        titles = {r["title"].casefold(): r["id"] for r in conn.execute("SELECT id, title FROM entries")}
        out = []
        for f in files:
            name = f.filename or "untitled"
            data = f.read()
            try:
                items = notesapps.expand(name, data) or [fileimport.convert(name, data)]
            except fileimport.ImportFileError as e:
                out.append({"name": name, "error": str(e)})
                continue
            for item in items:
                item["existing_id"] = titles.get(item["title"].casefold())
                out.append(item)
        return jsonify(out)
    return _with_conn(run)


@app.errorhandler(replacing.ReplaceError)
def _replace_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/replace/preview", methods=["POST"])
def api_replace_preview():
    b = request.get_json(force=True) or {}
    return _with_conn(lambda conn: jsonify(replacing.preview(
        conn, b.get("find"), b.get("replace"), bool(b.get("match_case")), bool(b.get("whole_word")),
        b.get("category") or None, b.get("project") or None, b.get("tag") or None)))


@app.route("/api/replace/apply", methods=["POST"])
def api_replace_apply():
    b = request.get_json(force=True) or {}
    return _with_conn(lambda conn: jsonify(replacing.apply(
        conn, b.get("find"), b.get("replace"), b.get("ids") or [], bool(b.get("match_case")), bool(b.get("whole_word")))))


@app.route("/api/entries/paste/preview", methods=["POST"])
def api_paste_preview():
    body = request.get_json(force=True) or {}
    return jsonify(intake.split_pieces(body.get("text"), bool(body.get("split", True))))


@app.route("/api/entries")
def api_list_entries():
    conn = core.get_conn()
    conditions = []
    params = []

    search = request.args.get("search", "").strip()
    if search:
        conditions.append("title LIKE ?")
        params.append(f"%{search}%")

    category = request.args.get("category", "").strip()
    if category:
        conditions.append("top_folder = ?")
        params.append(category)

    project = request.args.get("project", "").strip()
    if project == "__none__":
        conditions.append("(project_tag IS NULL OR project_tag = '')")
    elif project:
        conditions.append("project_tag = ?")
        params.append(project)

    to_edit = request.args.get("to_edit", "").strip()
    if to_edit == "1":
        conditions.append("to_edit = 1")

    to_record = request.args.get("to_record", "").strip()
    if to_record == "1":
        conditions.append("to_record = 1")

    published = request.args.get("published", "").strip()
    if published == "1":
        conditions.append("published = 1")
    elif published == "0":
        conditions.append("published = 0")

    if request.args.get("needs_review", "").strip() == "1":
        conditions.append("draft_tag = 'J' AND has_journal_header = 0")

    tag = request.args.get("tag", "").strip()
    if tag:
        tags.ensure_tables(conn)
        conditions.append("id IN (SELECT entry_id FROM entry_tags WHERE tag = ?)")
        params.append(tag)

    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) c FROM entries{where_sql}", params).fetchone()["c"]

    page = request.args.get("page", 1, type=int) or 1
    page = max(1, page)
    page_size = request.args.get("page_size", 25, type=int)

    q = f"SELECT * FROM entries{where_sql} ORDER BY title COLLATE NOCASE"
    row_params = list(params)
    if page_size and page_size > 0:
        row_params += [page_size, (page - 1) * page_size]
        q += " LIMIT ? OFFSET ?"
    else:
        page_size = total
        page = 1

    rows = [dict(r) | {"has_final": sharing.has_final(r)} for r in conn.execute(q, row_params).fetchall()]
    row_tags = tags.for_entries(conn, [r["id"] for r in rows])
    for r in rows:
        r["tags"] = row_tags[r["id"]]
    conn.close()
    return jsonify({"rows": rows, "total": total, "page": page, "page_size": page_size})


@app.route("/api/entries/<int:entry_id>")
def api_get_entry(entry_id):
    conn = core.get_conn()
    row = core.get_entry_row(conn, entry_id)
    if row is None:
        conn.close()
        return jsonify({"error": "not found"}), 404
    data = dict(row)
    data["content"] = core.read_entry_content(row)
    data["archive"] = core.list_archive(row)
    data["journal_scan"] = core.find_journal_scan_for_entry(row)
    data["final"] = sharing.get_final(row)
    data["notes"] = notes.get(conn, entry_id)
    data["tags"] = tags.for_entry(conn, entry_id)
    conn.close()
    return jsonify(data)


@app.route("/api/entries/<int:entry_id>/tags", methods=["POST"])
def api_set_tags(entry_id):
    conn = core.get_conn()
    try:
        return jsonify({"tags": tags.set_for_entry(conn, entry_id, (request.get_json(force=True) or {}).get("tags")),
                        "all": tags.all_tags(conn)})
    finally:
        conn.close()


@app.route("/api/tags")
def api_tags():
    conn = core.get_conn()
    try:
        return jsonify(tags.all_tags(conn))
    finally:
        conn.close()


@app.route("/api/tags/rename", methods=["POST"])
def api_rename_tag():
    body = request.get_json(force=True) or {}
    conn = core.get_conn()
    try:
        return jsonify(tags.rename(conn, body.get("old"), body.get("new")))
    finally:
        conn.close()


@app.route("/api/tags/remove", methods=["POST"])
def api_remove_tag():
    conn = core.get_conn()
    try:
        return jsonify(tags.remove(conn, (request.get_json(force=True) or {}).get("tag")))
    finally:
        conn.close()


@app.route("/api/collections")
def api_collections():
    conn = core.get_conn()
    try:
        return jsonify(tags.list_collections(conn))
    finally:
        conn.close()


@app.route("/api/collections", methods=["POST"])
def api_save_collection():
    body = request.get_json(force=True) or {}
    conn = core.get_conn()
    try:
        return jsonify(tags.save_collection(conn, body.get("name"), body.get("filters")))
    finally:
        conn.close()


@app.route("/api/collections/<int:collection_id>/delete", methods=["POST"])
def api_delete_collection(collection_id):
    conn = core.get_conn()
    try:
        return jsonify(tags.delete_collection(conn, collection_id))
    finally:
        conn.close()


@app.errorhandler(tags.TagError)
def _tag_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/entries/<int:entry_id>/notes", methods=["POST"])
def api_save_notes(entry_id):
    conn = core.get_conn()
    try:
        return jsonify(notes.save(conn, entry_id, (request.get_json(force=True) or {}).get("body")))
    finally:
        conn.close()


@app.route("/api/notes/lost/<int:note_id>/attach", methods=["POST"])
def api_attach_lost_notes(note_id):
    conn = core.get_conn()
    try:
        notes.attach(conn, note_id, (request.get_json(force=True) or {}).get("entry_id"))
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/notes/lost/<int:note_id>/forget", methods=["POST"])
def api_forget_lost_notes(note_id):
    conn = core.get_conn()
    try:
        notes.forget(conn, note_id)
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.errorhandler(notes.NotesError)
def _notes_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/entries/<int:entry_id>/scan/pdf")
def api_get_entry_scan_pdf(entry_id):
    conn = core.get_conn()
    row = core.get_entry_row(conn, entry_id)
    conn.close()
    if row is None:
        return jsonify({"error": "not found"}), 404
    scan = core.find_journal_scan_for_entry(row)
    if not scan or not scan.get("available"):
        return jsonify({"error": "scan not available for this entry"}), 404
    full_path = os.path.join(core.ARCHIVE_ROOT, scan["pdf_rel_path"])
    return send_file(full_path)


@app.route("/api/entries/<int:entry_id>/merge_from", methods=["POST"])
def api_merge_entry_from(entry_id):
    """Ad-hoc merge: folds another entry (other_id) into this one, e.g. a raw
    journal entry as this entry's original draft. Not tied to a pre-seeded
    duplicate pair."""
    body = request.get_json(force=True)
    other_id = body.get("other_id")
    conn = core.get_conn()
    try:
        result = core.merge_entries(conn, entry_id, other_id)
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify(result)


@app.route("/api/entries/<int:entry_id>/compare")
def api_compare_drafts(entry_id):
    conn = core.get_conn()
    try:
        row = core.get_entry_row(conn, entry_id)
    finally:
        conn.close()
    if row is None:
        return jsonify({"error": "not found"}), 404
    try:
        return jsonify(core.compare_drafts(row, request.args.get("a", ""), request.args.get("b", "")))
    except (ValueError, OSError) as e:
        return jsonify({"error": f"Couldn't read that draft: {e}"}), 400


@app.route("/api/entries/<int:entry_id>/archive/<path:filename>")
def api_get_archive_file(entry_id, filename):
    conn = core.get_conn()
    row = core.get_entry_row(conn, entry_id)
    if row is None:
        conn.close()
        return jsonify({"error": "not found"}), 404
    try:
        content = core.read_archive_file(row, filename)
    except (ValueError, OSError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify({"filename": filename, "content": content})


@app.route("/api/entries/<int:entry_id>/archive/<path:filename>/restore", methods=["POST"])
def api_restore_archive_file(entry_id, filename):
    conn = core.get_conn()
    try:
        result = core.restore_from_archive(conn, entry_id, filename)
    except (ValueError, OSError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify(result)


@app.route("/api/entries/<int:entry_id>/save", methods=["POST"])
def api_save_entry(entry_id):
    body = request.get_json(force=True)
    content = body.get("content", "")
    mode = body.get("mode", "overwrite")
    conn = core.get_conn()
    try:
        result = core.save_entry_content(conn, entry_id, content, mode)
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify(result)


@app.route("/api/entries/<int:entry_id>/flags", methods=["POST"])
def api_update_flags(entry_id):
    body = request.get_json(force=True)
    conn = core.get_conn()
    core.update_flags(conn, entry_id, body)
    row = core.get_entry_row(conn, entry_id)
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/entries/<int:entry_id>/project", methods=["POST"])
def api_set_entry_project(entry_id):
    body = request.get_json(force=True)
    tag = body.get("tag")
    conn = core.get_conn()
    try:
        core.set_entry_project(conn, entry_id, tag)
    except (ValueError, OSError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    row = core.get_entry_row(conn, entry_id)
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/entries/<int:entry_id>/category", methods=["POST"])
def api_set_entry_category(entry_id):
    body = request.get_json(force=True)
    category = body.get("category")
    conn = core.get_conn()
    try:
        core.set_entry_category(conn, entry_id, category)
    except (ValueError, OSError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    row = core.get_entry_row(conn, entry_id)
    conn.close()
    return jsonify(dict(row) if row else {})


@app.route("/api/entries/<int:entry_id>/rename", methods=["POST"])
def api_rename_entry(entry_id):
    body = request.get_json(force=True)
    conn = core.get_conn()
    try:
        row = core.rename_entry(conn, entry_id, body.get("title", ""))
    except (ValueError, OSError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify(row)


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

@app.route("/api/projects")
def api_list_projects():
    conn = core.get_conn()
    projects = core.list_projects(conn)
    conn.close()
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    body = request.get_json(force=True)
    conn = core.get_conn()
    try:
        core.create_project(conn, body.get("name", ""), body.get("tag", ""), body.get("description", ""))
    except (ValueError, OSError, Exception) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    projects = core.list_projects(conn)
    conn.close()
    return jsonify(projects)


def _project_call(fn, *args):
    conn = core.get_conn()
    try:
        return jsonify(fn(conn, *args))
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/projects/<int:project_id>")
def api_get_project(project_id):
    return _project_call(core.get_project, project_id)


@app.route("/api/projects/<int:project_id>", methods=["POST"])
def api_update_project(project_id):
    body = request.get_json(force=True)
    return _project_call(core.update_project, project_id, body.get("name"), body.get("description"),
                         body["target_words"] if "target_words" in body else False)


@app.route("/api/projects/<int:project_id>/outline")
def api_outline(project_id):
    return _project_call(outline.get, project_id)


@app.route("/api/projects/<int:project_id>/outline/<int:item_id>", methods=["POST"])
def api_outline_update(project_id, item_id):
    return _project_call(outline.update, project_id, item_id, request.get_json(force=True) or {})


@app.route("/api/projects/<int:project_id>/outline/add", methods=["POST"])
def api_outline_add(project_id):
    body = request.get_json(force=True) or {}
    return _project_call(outline.add_placeholder, project_id, body.get("title"), body.get("synopsis"), body.get("after"))


@app.route("/api/projects/<int:project_id>/outline/<int:item_id>/delete", methods=["POST"])
def api_outline_delete(project_id, item_id):
    return _project_call(outline.delete_placeholder, project_id, item_id)


@app.route("/api/projects/<int:project_id>/outline/order", methods=["POST"])
def api_outline_order(project_id):
    return _project_call(outline.reorder, project_id, (request.get_json(force=True) or {}).get("item_ids"))


@app.route("/api/projects/<int:project_id>/outline/<int:item_id>/start", methods=["POST"])
def api_outline_start(project_id, item_id):
    return _project_call(outline.start_writing, project_id, item_id, (request.get_json(force=True) or {}).get("category"))


@app.route("/api/projects/<int:project_id>/outline/<int:item_id>/link", methods=["POST"])
def api_outline_link(project_id, item_id):
    return _project_call(outline.link_entry, project_id, item_id, (request.get_json(force=True) or {}).get("entry_id"))


@app.route("/api/projects/<int:project_id>/delete", methods=["POST"])
def api_delete_project(project_id):
    return _project_call(core.delete_project, project_id)


@app.route("/api/projects/<int:project_id>/order", methods=["POST"])
def api_order_project(project_id):
    body = request.get_json(force=True)

    def run(conn, pid):
        core.set_project_order(conn, pid, body.get("entry_ids") or [])
        return core.get_project(conn, pid)
    return _project_call(run, project_id)


@app.route("/api/projects/<int:project_id>/entries", methods=["POST"])
def api_project_entries(project_id):
    """{"add": [entry ids]} tags entries with the project; {"remove": [...]}
    takes them out (the entries themselves stay where they are)."""
    body = request.get_json(force=True)

    def run(conn, pid):
        tag = core.get_project(conn, pid)["tag"]
        problems = []
        for eid in body.get("add") or []:
            try:
                core.set_entry_project(conn, int(eid), tag)
            except (ValueError, OSError) as e:
                problems.append(str(e))
        for eid in body.get("remove") or []:
            row = core.get_entry_row(conn, int(eid))
            if row is None or row["project_tag"] != tag:
                continue
            try:
                core.set_entry_project(conn, int(eid), None)
            except (ValueError, OSError) as e:
                problems.append(str(e))
        return core.get_project(conn, pid) | {"problems": problems}
    return _project_call(run, project_id)


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------

@app.route("/api/duplicates")
def api_list_duplicates():
    status = request.args.get("status", "").strip() or None
    conn = core.get_conn()
    rows = core.list_duplicates(conn, status)
    conn.close()
    return jsonify(rows)


@app.route("/api/duplicates/<int:pair_id>/status", methods=["POST"])
def api_set_duplicate_status(pair_id):
    body = request.get_json(force=True)
    conn = core.get_conn()
    try:
        core.set_duplicate_status(conn, pair_id, body.get("status"))
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/duplicates/<int:pair_id>/merge", methods=["POST"])
def api_merge_duplicate(pair_id):
    body = request.get_json(force=True)
    conn = core.get_conn()
    try:
        result = core.merge_duplicate(conn, pair_id, body.get("keep"))
    except ValueError as e:
        conn.close()
        return jsonify({"error": str(e)}), 400
    conn.close()
    return jsonify(result)


# --------------------------------------------------------------------------
# Docs
# --------------------------------------------------------------------------

@app.route("/api/docs")
def api_list_docs():
    return jsonify(core.list_docs())


@app.route("/api/howtos")
def api_list_howtos():
    return jsonify(core.list_howtos())


@app.route("/api/howtos/<path:name>")
def api_read_howto(name):
    try:
        html = core.read_howto(name)
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"name": name, "html": html})


@app.route("/api/stats")
def api_stats():
    conn = core.get_conn()
    try:
        return jsonify(stats.build(conn))
    finally:
        conn.close()


@app.route("/api/home/coming-up")
def api_coming_up():
    conn = core.get_conn()
    try:
        return jsonify(upcoming.coming_up(conn))
    finally:
        conn.close()


@app.route("/api/docs/<path:name>")
def api_read_doc(name):
    try:
        content = core.read_doc(name)
    except (ValueError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"name": name, "content": content})


# --------------------------------------------------------------------------
# AI features (opt-in; each uses the provider and key chosen in Settings)
# --------------------------------------------------------------------------

class _AiOff(Exception):
    def __init__(self, message, feature=""):
        super().__init__(message)
        self.feature = feature


def _ai_for(feature):
    """(settings, key) for a feature, or raise _AiOff with a message."""
    settings = app_config.load()["ai"][feature]
    name = "scanning" if feature == "scanning" else "organizing and editing"
    if not settings.get("enabled"):
        raise _AiOff(f"AI-assisted {name} is turned off.", feature)
    key = secrets_store.get_key(settings["provider"]) if ai.PROVIDERS.get(
        settings["provider"], {}).get("needs_key") else None
    if ai.PROVIDERS.get(settings["provider"], {}).get("needs_key") and not key:
        raise _AiOff(f"No API key is saved for AI-assisted {name}. Add one in Settings.", feature)
    return settings, key


@app.errorhandler(_AiOff)
def _ai_off(e):
    return jsonify({"error": str(e), "ai_off": True, "feature": e.feature}), 400


@app.errorhandler(ai.ProviderError)
def _provider_error(e):
    return jsonify({"error": str(e)}), 502


@app.errorhandler(scanning.ScanError)
def _scan_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/ai/status")
def api_ai_status():
    cfg = app_config.load()["ai"]
    out = {}
    for feature in app_config.FEATURES:
        try:
            _ai_for(feature)
            out[feature] = {"ready": True}
        except _AiOff as e:
            out[feature] = {"ready": False, "reason": str(e)}
        out[feature]["provider"] = cfg[feature]["provider"]
        out[feature]["provider_label"] = ai.PROVIDERS.get(cfg[feature]["provider"], {}).get("label", "")
        out[feature]["model"] = cfg[feature]["model"]
    out["scanning"]["builtin_ocr"] = _builtin_ocr()
    return jsonify(out)


@app.route("/api/entries/<int:entry_id>/ai/suggest", methods=["POST"])
def api_entry_suggest(entry_id):
    settings, key = _ai_for("organizing")
    conn = core.get_conn()
    row = core.get_entry_row(conn, entry_id)
    projects = core.list_projects(conn)
    conn.close()
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(organizing.suggest_metadata(
        settings, key, row["title"], row["top_folder"], row["project_tag"],
        core.read_entry_content(row), core.TOP_FOLDERS, projects))


@app.route("/api/entries/<int:entry_id>/ai/proofread", methods=["POST"])
def api_entry_proofread(entry_id):
    settings, key = _ai_for("organizing")
    body = request.get_json(force=True, silent=True) or {}
    content = body.get("content")
    if content is None:
        conn = core.get_conn()
        row = core.get_entry_row(conn, entry_id)
        conn.close()
        if row is None:
            return jsonify({"error": "not found"}), 404
        content = core.read_entry_content(row)
    if not content.strip():
        return jsonify({"error": "There's no text to proofread."}), 400
    return jsonify(organizing.proofread(settings, key, content))


# --------------------------------------------------------------------------
# Submission research: find venues that fit a piece
# --------------------------------------------------------------------------

def _research_fit(conn, body):
    entry_id, project_id = body.get("entry_id"), body.get("project_id")
    try:
        entry_id = int(entry_id) if entry_id not in (None, "") else None
        project_id = int(project_id) if project_id not in (None, "") else None
    except (TypeError, ValueError):
        entry_id = project_id = None
    if not entry_id and not project_id:
        raise research.ResearchError("Say which piece or project.")
    return research.fit(conn, entry_id=entry_id, project_id=project_id)


@app.route("/api/research/fit")
def api_research_fit():
    conn = core.get_conn()
    try:
        f = _research_fit(conn, request.args)
        own = research.own_venues(conn, f)
    finally:
        conn.close()
    try:
        _ai_for("organizing")
        ready = {"ready": True}
    except _AiOff as e:
        ready = {"ready": False, "reason": str(e)}
    cfg = app_config.load()["ai"]["organizing"]
    ready["provider_label"] = ai.PROVIDERS.get(cfg["provider"], {}).get("label", "")
    return jsonify({"fit": f, "own": own, "ai": ready})


@app.route("/api/research/preview", methods=["POST"])
def api_research_preview():
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        f = _research_fit(conn, body)
        b = research.brief(f, body.get("about") or "", bool(body.get("include_title")))
        if body.get("include_text"):
            words = len(research.piece_text(conn, f).split())
            b += f"\nThe writing itself: about {words:,} words of it"
    finally:
        conn.close()
    return jsonify({"brief": b})


@app.route("/api/research/suggest", methods=["POST"])
def api_research_suggest():
    settings, key = _ai_for("organizing")
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        f = _research_fit(conn, body)
        text = research.piece_text(conn, f) if body.get("include_text") else None
        own = [v["name"] for v in research.own_venues(conn, f)]
    finally:
        conn.close()
    avoid = own + [str(a) for a in (body.get("avoid") or [])][:60]
    return jsonify({"venues": research.suggest(settings, key, f, body.get("about") or "", bool(body.get("include_title")),
                                               text, avoid)})


@app.route("/api/research/check", methods=["POST"])
def api_research_check():
    settings, key = _ai_for("organizing")
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(research.check(settings, key, str(body.get("name") or "").strip() or "this venue", body.get("website")))


@app.route("/api/research/add", methods=["POST"])
def api_research_add():
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Say which venue."}), 400
    conn = core.get_conn()
    try:
        submissions.ensure_table(conn)
        v = research.add_venue(conn, name, body.get("website") or "", body.get("checked"), body.get("why") or "")
    finally:
        conn.close()
    return jsonify(v)


@app.errorhandler(research.ResearchError)
def _research_error(e):
    return jsonify({"error": str(e)}), 400


# --------------------------------------------------------------------------
# Scans: transcribe, build the Master, proofread, file
# --------------------------------------------------------------------------

@app.route("/api/scans")
def api_scan_sources():
    data = scanning.list_sources()
    data["scans_dir"] = os.path.relpath(data["root"], core.ARCHIVE_ROOT)
    data["jobs"] = jobs.active("transcribe")
    data["origins"] = scanintake.origins()
    return jsonify(data)


@app.route("/api/scans", methods=["POST"])
def api_create_source():
    body = request.get_json(force=True)
    scanning.create_source(body.get("name"))
    return jsonify(scanning.list_sources())


@app.errorhandler(scanintake.IntakeError)
def _scan_intake_error(e):
    return jsonify({"error": str(e)}), 400


# Bring in scans from a folder outside the library (a cloud folder, often)
@app.route("/api/scan-intake/folders")
def api_scan_intake_folders():
    return jsonify({"cloud": scanintake.cloud_folders(), "origins": scanintake.origins()})


@app.route("/api/scan-intake/preview", methods=["POST"])
def api_scan_intake_preview():
    body = request.get_json(force=True) or {}
    return jsonify(scanintake.preview(body.get("folder"), body.get("source"), body.get("subfolders", True) is not False))


@app.route("/api/scan-intake/run", methods=["POST"])
def api_scan_intake_run():
    body = request.get_json(force=True) or {}
    folder, source = body.get("folder"), body.get("source")
    subfolders = body.get("subfolders", True) is not False
    scanintake.find_scans(folder, subfolders)  # a bad folder is reported now, not from the job
    try:
        job = jobs.start("scan-intake", source or "scans", lambda job: scanintake.bring_in(job, folder, source, subfolders))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/scans/<name>/status")
def api_scan_status(name):
    return jsonify({"name": name, "scans": scanning.scan_status(name),
                    "has_master": os.path.isfile(scanning.master_path(name)),
                    "folder": os.path.relpath(scanning.source_dir(name), core.ARCHIVE_ROOT),
                    "jobs": jobs.active("transcribe")})


@app.route("/api/scans/<name>/page/<int:num>/<int:page>.jpg")
def api_scan_page(name, num, page):
    data = scanning.cached_page_image(name, num, page)
    return app.response_class(data, mimetype="image/jpeg",
                              headers={"Cache-Control": "private, max-age=3600"})


@app.route("/api/scans/<name>/estimate", methods=["POST"])
def api_transcribe_estimate(name):
    settings = app_config.load()["ai"]["scanning"]
    body = request.get_json(force=True)
    nums = [int(n) for n in body.get("scans") or []]
    provider = settings.get("provider") or ""
    model = settings.get("model") or ai.PROVIDERS.get(provider, {}).get("default_model", "")
    return jsonify(scanning.estimate(name, nums, provider, model, redo=bool(body.get("redo")))
                   | {"builtin_ocr": _builtin_ocr()})


def _builtin_ocr():
    """Whether scanning should try Windows' own text recognition first."""
    return bool(app_config.load().get("builtin_ocr", True)) and winocr.available()["ok"]


@app.route("/api/settings/ocr")
def api_get_ocr():
    a = winocr.available()
    return jsonify({"enabled": bool(app_config.load().get("builtin_ocr", True)),
                    "available": a["ok"], "language": a["language"]})


@app.route("/api/settings/ocr", methods=["POST"])
def api_set_ocr():
    cfg = app_config.load()
    cfg["builtin_ocr"] = bool((request.get_json(force=True) or {}).get("enabled"))
    app_config.save(cfg)
    return api_get_ocr()


@app.route("/api/scans/<name>/transcribe", methods=["POST"])
def api_transcribe(name):
    ocr = _builtin_ocr()
    try:
        settings, key = _ai_for("scanning")
    except _AiOff:
        # typed pages can still come in free; handwritten ones wait for AI
        if not ocr:
            raise
        settings, key = {"provider": None, "model": None}, None
    body = request.get_json(force=True)
    nums = [int(n) for n in body.get("scans") or []]
    if not nums:
        return jsonify({"error": "Choose at least one scan."}), 400
    for n in nums:
        scanning.get_scan(name, n)
    redo = bool(body.get("redo"))

    def work(job):
        written, stats = [], {}
        for i, n in enumerate(nums):
            def progress(done, total, msg, i=i):
                job.progress(done, total, f"Scan {i + 1} of {len(nums)}. {msg}")
            out = scanning.transcribe_scan(
                name, n, settings["provider"], settings["model"], key,
                progress=progress, cancelled=job.cancelled, redo=redo, ocr=ocr, stats=stats)
            if out:
                written.append(out)
        return {"text_outputs": written, "pages": stats}

    try:
        job = jobs.start("transcribe", name, work)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/backup")
def api_backup_status():
    s = backup.status()
    s["running"] = jobs.active("backup")
    return jsonify(s)


@app.route("/api/backup/settings", methods=["POST"])
def api_backup_settings():
    body = request.get_json(force=True) or {}
    try:
        return jsonify(backup.set_settings(body.get("folder"), body.get("remind_days")))
    except backup.BackupError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/backup/run", methods=["POST"])
def api_backup_run():
    body = request.get_json(force=True, silent=True) or {}
    changes_only = bool(body.get("changes_only"))
    s = backup.status()
    if not s["folder_ok"]:
        msg = "Choose a backup folder first." if not s["folder"] else \
            "The backup folder isn't available. Is the drive plugged in?"
        return jsonify({"error": msg}), 400
    try:
        job = jobs.start("backup", "a backup", lambda job: backup.run(job, changes_only=changes_only))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/export-all")
def api_export_all_status():
    return jsonify({**exportall.prefs(), "running": jobs.active("exportall"), "last": exportall.LAST["path"]})


@app.route("/api/export-all", methods=["POST"])
def api_export_all():
    body = request.get_json(force=True, silent=True) or {}
    folder = str(body.get("folder") or "").strip()
    as_zip = body.get("zip", True) is not False
    media = bool(body.get("media"))
    try:
        job = jobs.start("exportall", "an export", lambda job: exportall.export(job, folder, as_zip, media))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/export-all/reveal", methods=["POST"])
def api_export_all_reveal():
    path = exportall.LAST["path"]
    if not path or not os.path.exists(path):
        return jsonify({"error": "That export isn't there anymore."}), 404
    return _reveal(path)


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(job.to_dict())


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def api_job_cancel(job_id):
    job = jobs.cancel(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(job.to_dict())


@app.route("/api/scans/<name>/master", methods=["POST"])
def api_build_master(name):
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(scanning.build_master(name, body.get("scans")))


@app.route("/api/scans/<name>/master")
def api_read_master(name):
    return jsonify(scanning.read_master(name))


@app.route("/api/scans/<name>/master/<int:num>", methods=["POST"])
def api_save_master_entry(name, num):
    body = request.get_json(force=True)
    version = scanning.save_master_entry(name, num, body.get("version"), body.get("body"),
                                         title=body.get("title"), date=body.get("date"))
    if "reviewed" in body:
        scanning.set_reviewed(name, num, bool(body["reviewed"]))
    return jsonify({"version": version})


@app.route("/api/scans/<name>/master/<int:num>/reviewed", methods=["POST"])
def api_set_reviewed(name, num):
    body = request.get_json(force=True)
    scanning.set_reviewed(name, num, bool(body.get("reviewed")))
    return jsonify({"ok": True})


@app.route("/api/scans/<name>/master/<int:num>/pages", methods=["POST"])
def api_set_entry_pages(name, num):
    body = request.get_json(force=True)
    try:
        pages = pagelinks.set_manual(name, num, body.get("pages") or [])
    except (TypeError, ValueError, IndexError) as e:
        return jsonify({"error": str(e) or "Those pages aren't valid."}), 400
    return jsonify({"pages": pages})


@app.route("/api/scans/<name>/rematch", methods=["POST"])
def api_rematch_pages(name):
    """Match every entry's pages again, keeping the ones set by hand."""
    scanning.source_dir(name)
    pagelinks.forget(name)
    master = scanning.read_master(name)
    methods = {}
    for e in master["entries"]:
        methods[e["link"]["method"]] = methods.get(e["link"]["method"], 0) + 1
    return jsonify({"entries": len(master["entries"]), "methods": methods})


@app.route("/api/scans/<name>/suggest", methods=["POST"])
def api_suggest_filing(name):
    settings, key = _ai_for("organizing")
    body = request.get_json(force=True)
    wanted = {int(n) for n in body.get("nums") or []}
    master = scanning.read_master(name)
    entries = [e for e in master["entries"] if e["num"] in wanted and not e["filed"]]
    if not entries:
        return jsonify({"error": "Choose entries that haven't been filed yet."}), 400
    if len(entries) > 60:
        return jsonify({"error": "Ask for suggestions on 60 entries or fewer at a time."}), 400
    result = organizing.suggest_filing(settings, key, entries, core.TOP_FOLDERS)
    return jsonify({str(k): v for k, v in result.items()})


@app.route("/api/scans/<name>/file", methods=["POST"])
def api_file_entries(name):
    body = request.get_json(force=True)
    return jsonify(scanning.file_entries(name, body.get("items") or []))


@app.route("/api/images")
def api_images():
    if not core.is_configured():
        return jsonify({"kinds": list(images.KINDS), "images": []})
    return jsonify(images.list_all())


@app.errorhandler(people.PeopleError)
def _people_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/people")
def api_people():
    if not core.is_configured():
        return jsonify({"people": [], "sources": []})
    conn = core.get_conn()
    try:
        return jsonify({"people": people.list_people(conn), "sources": people.sources(conn),
                        "jobs": jobs.active("people")})
    finally:
        conn.close()


@app.route("/api/people/estimate", methods=["POST"])
def api_people_estimate():
    body = request.get_json(force=True)
    model = app_config.load()["ai"]["organizing"].get("model", "")
    return jsonify(people.estimate(body.get("source") or "", model))


@app.route("/api/people/find", methods=["POST"])
def api_people_find():
    settings, key = _ai_for("organizing")
    source = (request.get_json(force=True) or {}).get("source") or ""
    scanning.source_dir(source)

    def work(job):
        conn = core.get_conn()
        try:
            return people.find(conn, source, settings, key, progress=job.progress, cancelled=job.cancelled)
        finally:
            conn.close()

    try:
        job = jobs.start("people", source, work)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/people/merge", methods=["POST"])
def api_people_merge():
    body = request.get_json(force=True)
    conn = core.get_conn()
    try:
        people.merge(conn, body.get("keep"), body.get("others") or [])
        return jsonify({"people": people.list_people(conn)})
    finally:
        conn.close()


@app.route("/api/people/<int:pid>/rename", methods=["POST"])
def api_people_rename(pid):
    conn = core.get_conn()
    try:
        people.rename(conn, pid, (request.get_json(force=True) or {}).get("name"))
        return jsonify({"people": people.list_people(conn)})
    finally:
        conn.close()


@app.route("/api/views/timeline")
def api_timeline():
    if not core.is_configured():
        return jsonify({"journals": [], "years": [], "jobs": []})
    conn = core.get_conn()
    try:
        return jsonify(views.timeline(conn) | {"jobs": jobs.active("summary")})
    finally:
        conn.close()


@app.route("/api/views/timeline/estimate", methods=["POST"])
def api_timeline_estimate():
    body = request.get_json(force=True)
    model = app_config.load()["ai"]["organizing"].get("model", "")
    return jsonify(views.estimate(body.get("source") or "", model))


@app.route("/api/views/timeline/summarize", methods=["POST"])
def api_timeline_summarize():
    settings, key = _ai_for("organizing")
    source = (request.get_json(force=True) or {}).get("source") or ""
    scanning.source_dir(source)

    def work(job):
        conn = core.get_conn()
        try:
            return views.summarize(conn, source, settings, key, progress=job.progress, cancelled=job.cancelled)
        finally:
            conn.close()

    try:
        job = jobs.start("summary", source, work)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job.to_dict())


@app.route("/api/views/timeline/save", methods=["POST"])
def api_timeline_save():
    conn = core.get_conn()
    try:
        return jsonify({"path": views.save_text(conn)})
    finally:
        conn.close()


@app.route("/api/views/people")
def api_histories():
    if not core.is_configured():
        return jsonify([])
    conn = core.get_conn()
    try:
        return jsonify(views.histories(conn))
    finally:
        conn.close()


@app.route("/api/views/people/<int:pid>")
def api_history(pid):
    conn = core.get_conn()
    try:
        return jsonify(views.history(conn, pid))
    finally:
        conn.close()


@app.route("/api/views/people/<int:pid>/estimate", methods=["POST"])
def api_history_estimate(pid):
    model = app_config.load()["ai"]["organizing"].get("model", "")
    conn = core.get_conn()
    try:
        return jsonify(views.estimate_history(conn, pid, model))
    finally:
        conn.close()


@app.route("/api/views/people/<int:pid>/write", methods=["POST"])
def api_history_write(pid):
    settings, key = _ai_for("organizing")
    conn = core.get_conn()
    try:
        return jsonify(views.write_history(conn, pid, settings, key))
    finally:
        conn.close()


@app.route("/api/views/people/save", methods=["POST"])
def api_histories_save():
    conn = core.get_conn()
    try:
        return jsonify({"path": views.save_histories(conn)})
    finally:
        conn.close()


@app.route("/api/images/save", methods=["POST"])
def api_save_images():
    body = request.get_json(force=True)
    return jsonify({"written": images.save(body.get("source") or "", body.get("items") or [])})


# --------------------------------------------------------------------------
# Sharing: final drafts, templates, exports
# --------------------------------------------------------------------------

@app.errorhandler(sharing.ShareError)
def _share_error(e):
    return jsonify({"error": str(e)}), 400


@app.errorhandler(submissions.SubmissionError)
def _submission_error(e):
    return jsonify({"error": str(e)}), 400


@app.errorhandler(subimport.SubImportError)
def _subimport_error(e):
    return jsonify({"error": str(e)}), 400


# --------------------------------------------------------------------------
# Submissions
# --------------------------------------------------------------------------

def _with_conn(fn):
    conn = core.get_conn()
    try:
        return fn(conn)
    finally:
        conn.close()


@app.route("/api/submissions")
def api_list_submissions():
    def run(conn):
        rows = submissions.search(conn, request.args.to_dict())
        return jsonify({"rows": rows, "summary": submissions.summary(rows)})
    return _with_conn(run)


@app.route("/api/submissions/options")
def api_submission_options():
    return _with_conn(lambda conn: jsonify({
        "statuses": list(submissions.STATUSES),
        "venues": submissions.venues(conn),
        "categories": list(core.TOP_FOLDERS),
        "projects": [{"id": p["id"], "tag": p["tag"], "name": p["name"]} for p in core.list_projects(conn)],
    }))


@app.route("/api/submissions", methods=["POST"])
def api_create_submission():
    made = _with_conn(lambda conn: jsonify(submissions.create(conn, request.get_json(force=True) or {})))
    if made.status_code == 200:
        firstrun.mark("submission")
    return made


@app.route("/api/submissions/<int:sub_id>", methods=["POST"])
def api_update_submission(sub_id):
    return _with_conn(lambda conn: jsonify(submissions.update(conn, sub_id, request.get_json(force=True) or {})))


def _import_args():
    body = request.get_json(force=True) or {}
    text = body.get("text")
    if not isinstance(text, str):
        raise subimport.SubImportError("Choose a spreadsheet saved as CSV.")
    return text, body.get("mapping"), bool(body.get("day_first")), body.get("overrides") or {}, body


@app.errorhandler(subemail.EmailImportError)
def _subemail_error(e):
    return jsonify({"error": str(e)}), 400


@app.route("/api/submissions/import/emails", methods=["POST"])
def api_submission_emails():
    """Read exported emails into a CSV the import preview understands.
    Nothing is saved here."""
    files = request.files.getlist("files")
    if not files:
        raise subemail.EmailImportError("Choose an .mbox file or some .eml files.")

    def run(conn):
        titles = [r["title"] for r in conn.execute("SELECT title FROM entries")]
        titles += [r["name"] for r in conn.execute("SELECT name FROM projects")]
        return jsonify(subemail.read(((f.filename or "mail", f.read()) for f in files), titles))
    return _with_conn(run)


@app.route("/api/submissions/import/preview", methods=["POST"])
def api_preview_submission_import():
    text, mapping, day_first, overrides, body = _import_args()
    return _with_conn(lambda conn: jsonify(subimport.preview(
        conn, text, mapping, day_first, overrides, body.get("source"), body.get("name") or "")))


@app.route("/api/submissions/import", methods=["POST"])
def api_submission_import():
    text, mapping, day_first, overrides, body = _import_args()
    return _with_conn(lambda conn: jsonify(subimport.run(
        conn, text, mapping, day_first, overrides, body.get("source") or "")))


@app.route("/api/submissions/<int:sub_id>/elsewhere")
def api_submission_elsewhere(sub_id):
    return _with_conn(lambda conn: jsonify(submissions.still_waiting_elsewhere(conn, sub_id)))


@app.route("/api/submissions/withdraw", methods=["POST"])
def api_withdraw_submissions():
    ids = (request.get_json(force=True) or {}).get("ids") or []
    return _with_conn(lambda conn: jsonify({"withdrawn": submissions.withdraw(conn, ids)}))


@app.route("/api/submissions/<int:sub_id>/delete", methods=["POST"])
def api_delete_submission(sub_id):
    def run(conn):
        submissions.delete(conn, sub_id)
        return jsonify({"ok": True})
    return _with_conn(run)


@app.route("/api/venues")
def api_venues():
    return _with_conn(lambda conn: jsonify(submissions.list_venues(conn)))


@app.route("/api/venue")
def api_venue():
    def run(conn):
        v = submissions.venue(conn, request.args.get("name"))
        return (jsonify(v), 200) if v else (jsonify({"error": "No notes or submissions for that venue yet."}), 404)
    return _with_conn(run)


@app.route("/api/venue", methods=["POST"])
def api_save_venue():
    return _with_conn(lambda conn: jsonify(submissions.save_venue(conn, request.get_json(force=True) or {})))


def _entry_or_404(conn, entry_id):
    row = core.get_entry_row(conn, entry_id)
    if row is None:
        conn.close()
        abort(404)
    return row


@app.route("/api/share/options")
def api_share_options():
    return jsonify({"formats": list(sharing.FORMATS),
                    "trims": [{"id": k, "label": v[0]} for k, v in sharing.TRIM_SIZES.items()]
                    + [{"id": sharing.MANUSCRIPT, "label": sharing.MANUSCRIPT_LABEL}],
                    "contact_set": bool(manuscript.contact()["name"]),
                    "templates": sharing.list_templates()})


@app.route("/api/entries/<int:entry_id>/final", methods=["POST"])
def api_mark_final(entry_id):
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        _entry_or_404(conn, entry_id)
        return jsonify(sharing.mark_final(conn, entry_id, body.get("archive_name")))
    finally:
        conn.close()


@app.route("/api/entries/<int:entry_id>/final/remove", methods=["POST"])
def api_unmark_final(entry_id):
    conn = core.get_conn()
    try:
        _entry_or_404(conn, entry_id)
        sharing.unmark_final(conn, entry_id)
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/entries/<int:entry_id>/export", methods=["POST"])
def api_export_entry(entry_id):
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        _entry_or_404(conn, entry_id)
        r = sharing.export_entry(conn, entry_id, body.get("format"), body.get("which") or "final",
                                 body.get("template_id") or None)
    finally:
        conn.close()
    if body.get("format") == "pdf":
        firstrun.mark("pdf")
    return jsonify(r | {"folder": os.path.relpath(os.path.dirname(r.pop("path")), core.ARCHIVE_ROOT)})


@app.route("/api/templates", methods=["POST"])
def api_add_template():
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "Choose a .docx or .pdf file."}), 400
    return jsonify(sharing.add_template(f.filename, f.read(), request.form.get("name")))


@app.route("/api/templates/<tid>/delete", methods=["POST"])
def api_remove_template(tid):
    sharing.remove_template(tid)
    return jsonify({"ok": True})


@app.route("/api/projects/<int:project_id>/share")
def api_project_share(project_id):
    conn = core.get_conn()
    try:
        return jsonify(sharing.project_settings(conn, project_id))
    finally:
        conn.close()


@app.route("/api/projects/<int:project_id>/share", methods=["POST"])
def api_save_project_share(project_id):
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        return jsonify(sharing.save_project_settings(conn, project_id, body))
    finally:
        conn.close()


@app.route("/api/projects/<int:project_id>/cover/<side>", methods=["POST"])
def api_set_cover(project_id, side):
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "Choose a .jpg or .png image."}), 400
    sharing.set_cover(project_id, side, f.filename, f.read())
    return jsonify({"ok": True})


@app.route("/api/projects/<int:project_id>/cover/<side>/delete", methods=["POST"])
def api_remove_cover(project_id, side):
    sharing.remove_cover(project_id, side)
    return jsonify({"ok": True})


@app.route("/api/projects/<int:project_id>/cover/<side>")
def api_get_cover(project_id, side):
    path = sharing.cover_file(project_id, side) if side in ("front", "back") else None
    if not path:
        abort(404)
    return send_file(path, max_age=0)


@app.route("/api/projects/<int:project_id>/export", methods=["POST"])
def api_export_project(project_id):
    body = request.get_json(force=True, silent=True) or {}
    conn = core.get_conn()
    try:
        r = sharing.export_project(conn, project_id, body.get("format"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
    return jsonify(r | {"folder": os.path.relpath(os.path.dirname(r.pop("path")), core.ARCHIVE_ROOT)})


def _export_file(name):
    path = os.path.join(sharing.exports_dir(), os.path.basename(name or ""))
    if not sharing.export_path_ok(path):
        abort(404)
    return path


@app.route("/api/exports/file")
def api_export_file():
    return send_file(_export_file(request.args.get("name")), as_attachment=True)


@app.route("/api/exports/open", methods=["POST"])
def api_open_export():
    """Open an export with its usual program, or show it in its folder."""
    body = request.get_json(force=True, silent=True) or {}
    path = _export_file(body.get("name"))
    import subprocess
    import sys
    try:
        if sys.platform == "win32":
            if body.get("reveal"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # noqa: S606 (a file Minerva just wrote)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if body.get("reveal") else ["open", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if body.get("reveal") else path])
    except OSError as e:
        return jsonify({"error": f"Couldn't open it: {e}"}), 400
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

@app.route("/api/categories")
def api_categories():
    return jsonify(core.TOP_FOLDERS)


@app.errorhandler(core.CategoryError)
def _category_error(e):
    return jsonify({"error": str(e)}), 400


def _categories_after_change():
    core.scan_and_sync()
    libcheck.run()
    return api_category_details()


@app.route("/api/categories/details")
def api_category_details():
    def run(conn):
        counts = {r["top_folder"]: r["c"] for r in conn.execute(
            "SELECT top_folder, COUNT(*) c FROM entries GROUP BY top_folder")}
        return jsonify([{"name": c, "entries": counts.get(c, 0)} for c in core.TOP_FOLDERS])
    return _with_conn(run)


@app.route("/api/categories", methods=["POST"])
def api_add_category():
    core.add_category((request.get_json(force=True) or {}).get("name"))
    return _categories_after_change()


@app.route("/api/categories/rename", methods=["POST"])
def api_rename_category():
    body = request.get_json(force=True) or {}
    _with_conn(lambda conn: core.rename_category(conn, body.get("old"), body.get("new")))
    return _categories_after_change()


@app.route("/api/categories/remove", methods=["POST"])
def api_remove_category():
    name = (request.get_json(force=True) or {}).get("name")
    _with_conn(lambda conn: core.remove_category(conn, name))
    return _categories_after_change()

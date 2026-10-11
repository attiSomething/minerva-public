"""Grammar and style suggestions with LanguageTool, on this computer.

LanguageTool is open source (LGPL) and runs as a small server that only
this computer can reach. Minerva downloads it once on request (about
300 MB with the Java runtime it needs, which is skipped when Java 17 or
later is already installed), keeps it in Minerva's settings folder, starts
it when a check is asked for and stops it when Minerva closes. Nothing is
sent anywhere else. A writer who already runs a LanguageTool server can
point Minerva at it instead.

Poems get a gentler check: capitals at the start of lines, missing end
punctuation and fragments aren't flagged.
"""

import atexit
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import config as app_config, sharing

LT_URL = "https://languagetool.org/download/LanguageTool-stable.zip"
JRE_URL = "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"
JRE_CHECKSUM_URL = "https://api.adoptium.net/v3/checksum/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"
DOWNLOAD_MB = {"languagetool": 260, "java": 45}
LANGUAGES = {
    "en-US": "English (US)", "en-GB": "English (UK)", "en-CA": "English (Canada)", "en-AU": "English (Australia)",
    "de-DE": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt-PT": "Portuguese",
    "pt-BR": "Portuguese (Brazil)", "nl": "Dutch", "auto": "Work it out from the text",
}
# Rules that don't suit verse: lines start with capitals or don't, stanzas
# end without stops, and spacing is a choice
POETRY_OFF = ["UPPERCASE_SENTENCE_START", "PUNCTUATION_PARAGRAPH_END", "WHITESPACE_RULE", "SENTENCE_WHITESPACE",
              "COMMA_PARENTHESIS_WHITESPACE", "DOUBLE_PUNCTUATION", "EN_UNPAIRED_QUOTES", "EN_UNPAIRED_BRACKETS",
              "ENGLISH_WORD_REPEAT_BEGINNING_RULE", "SENTENCE_FRAGMENT", "EN_QUOTES", "DASH_RULE"]
CHUNK = 20000
MB = 1024 * 1024


class GrammarError(Exception):
    user_facing = True


def _tools():
    return os.path.join(app_config.config_dir(), "tools")


def _no_window():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def settings():
    g = dict(app_config.load().get("grammar") or {})
    return {"language": g.get("language") if g.get("language") in LANGUAGES else "en-US",
            "server": (g.get("server") or "").strip().rstrip("/"), "picky": bool(g.get("picky")),
            "words": list(g.get("words") or []), "rules": list(g.get("rules") or [])}


def save_settings(values):
    cfg = app_config.load()
    g = settings() | {k: v for k, v in values.items() if k in ("language", "server", "picky", "words", "rules")}
    g["words"] = sorted({str(w).strip() for w in g["words"] if str(w).strip()}, key=str.casefold)[:2000]
    g["rules"] = sorted({str(r).strip() for r in g["rules"] if re.match(r"^[A-Za-z0-9_]+$", str(r).strip())})[:500]
    if g["language"] not in LANGUAGES:
        raise GrammarError("Choose a language from the list.")
    server = (g.get("server") or "").strip().rstrip("/")
    if server and not re.match(r"^https?://[^\s/]+", server):
        raise GrammarError("A LanguageTool server address starts with http:// or https://.")
    g["server"] = server
    cfg["grammar"] = g
    app_config.save(cfg)
    return settings()


# --------------------------------------------------------------------------
# Finding Java and LanguageTool
# --------------------------------------------------------------------------

def _java_version(exe):
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, timeout=30, **_no_window())
    except (OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out.stderr.decode("utf-8", errors="replace"))
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


_java_cache = {}


def java():
    """A Java 17+ to run LanguageTool with: Minerva's own, else JAVA_HOME's,
    else the one on the PATH."""
    exe_name = "java.exe" if os.name == "nt" else "java"
    candidates = glob.glob(os.path.join(_tools(), "jre", "*", "bin", exe_name)) + \
        glob.glob(os.path.join(_tools(), "jre", "bin", exe_name))
    if os.environ.get("JAVA_HOME"):
        candidates.append(os.path.join(os.environ["JAVA_HOME"], "bin", exe_name))
    if shutil.which("java"):
        candidates.append(shutil.which("java"))
    for exe in candidates:
        if not os.path.isfile(exe):
            continue
        if exe not in _java_cache:
            _java_cache[exe] = _java_version(exe)
        if _java_cache[exe] >= 17:
            return exe
    return None


def server_jar():
    found = glob.glob(os.path.join(_tools(), "languagetool", "*", "languagetool-server.jar")) + \
        glob.glob(os.path.join(_tools(), "languagetool", "languagetool-server.jar"))
    return found[0] if found else None


def can_install():
    return os.name == "nt"


def status():
    s = settings()
    jar, j = server_jar(), java()
    return {"ready": bool(s["server"]) or bool(jar and j), "installed": bool(jar), "java": bool(j),
            "own_server": s["server"], "running": _proc is not None and _proc.poll() is None,
            "can_install": can_install(),
            "download_mb": DOWNLOAD_MB["languagetool"] + (0 if j else DOWNLOAD_MB["java"]),
            "settings": s, "languages": list(LANGUAGES.items())}


# --------------------------------------------------------------------------
# Setting it up (a background job)
# --------------------------------------------------------------------------

def _download(url, dest, job, label):
    req = urllib.request.Request(url, headers={"User-Agent": "Minerva"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if job.cancelled():
                    raise GrammarError("Stopped.")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                job.progress(done, total, f"{label}: {done // MB} of {total // MB} MB" if total else f"{label}: {done // MB} MB")
    except (urllib.error.URLError, OSError) as e:
        raise GrammarError(f"Couldn't download {label.lower().replace('downloading ', '')} ({getattr(e, 'reason', e)}). "
                           "Check your internet connection.") from None


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _extract(zip_path, dest, job, label):
    tmp = dest + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            members = z.infolist()
            for n, m in enumerate(members):
                if job.cancelled():
                    raise GrammarError("Stopped.")
                target = os.path.realpath(os.path.join(tmp, m.filename))
                if not target.startswith(os.path.realpath(tmp) + os.sep):
                    raise GrammarError(f"The {label} download looks wrong, so it wasn't used.")
                z.extract(m, tmp)
                if n % 50 == 0:
                    job.progress(n, len(members), f"Unpacking {label}")
    except zipfile.BadZipFile:
        raise GrammarError(f"The {label} download was damaged. Try again.") from None
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)


def install(job):
    if not can_install():
        raise GrammarError("Install LanguageTool yourself and enter its address under Settings, then try again.")
    os.makedirs(_tools(), exist_ok=True)
    folder = tempfile.mkdtemp(prefix="minerva-lt-")
    try:
        if not java():
            z = os.path.join(folder, "jre.zip")
            _download(JRE_URL, z, job, "Downloading Java")
            try:
                with urllib.request.urlopen(urllib.request.Request(JRE_CHECKSUM_URL, headers={"User-Agent": "Minerva"}),
                                            timeout=30) as resp:
                    expected = resp.read().decode("ascii", errors="replace").split()[0].lower()
            except (urllib.error.URLError, OSError, IndexError):
                expected = ""
            if expected and len(expected) == 64 and _sha256(z) != expected:
                raise GrammarError("The Java download didn't match what Adoptium published, so it wasn't used.")
            _extract(z, os.path.join(_tools(), "jre"), job, "Java")
            _java_cache.clear()
            if not java():
                raise GrammarError("Java was downloaded but won't start on this computer.")
        if not server_jar():
            z = os.path.join(folder, "languagetool.zip")
            _download(LT_URL, z, job, "Downloading LanguageTool")
            _extract(z, os.path.join(_tools(), "languagetool"), job, "LanguageTool")
            if not server_jar():
                shutil.rmtree(os.path.join(_tools(), "languagetool"), ignore_errors=True)
                raise GrammarError("The LanguageTool download didn't have what Minerva needs.")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    job.progress(0, 0, "Starting LanguageTool for a first check")
    r = check("This are a test.", "en-US", poem=False)
    return status() | {"test": r["matches"][:1]}


def remove():
    stop()
    shutil.rmtree(os.path.join(_tools(), "languagetool"), ignore_errors=True)
    shutil.rmtree(os.path.join(_tools(), "jre"), ignore_errors=True)
    _java_cache.clear()
    return status()


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------

_proc = None
_port = None
_lock = threading.Lock()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def stop():
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _proc.kill()
        _proc = None


atexit.register(stop)


def _base():
    """The server to ask, starting Minerva's own when needed."""
    global _proc, _port
    own = settings()["server"]
    if own:
        return own
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return f"http://127.0.0.1:{_port}"
        jar, exe = server_jar(), java()
        if not jar or not exe:
            raise GrammarError("Grammar checking isn't set up yet.")
        _port = _free_port()
        _proc = subprocess.Popen([exe, "-Xmx1g", "-cp", jar, "org.languagetool.server.HTTPServer",
                                  "--port", str(_port)], cwd=os.path.dirname(jar),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_no_window())
        base = f"http://127.0.0.1:{_port}"
        deadline = time.time() + 90
        while time.time() < deadline:
            if _proc.poll() is not None:
                _proc = None
                raise GrammarError("LanguageTool stopped as it started. Try again, or remove and set it up again in Settings.")
            try:
                _get(base + "/v2/languages", timeout=2)
                return base
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.5)
        raise GrammarError("LanguageTool is taking too long to start. Try again in a minute.")


def _blank_header(text):
    """The text with a transcription header replaced by spaces, so offsets
    still match the editor but the header isn't checked."""
    body = sharing.strip_header(text)
    if body == text.strip("\n") or not body:
        return text
    at = text.find(body)
    if at <= 0:
        return text
    return re.sub(r"[^\n]", " ", text[:at]) + text[at:]


def _chunks(text):
    """(offset, piece) pairs under CHUNK characters, split at blank lines."""
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK)
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut > start:
                end = cut + 2
        yield start, text[start:end]
        start = end


def _dictionary_miss(rule, word):
    """A word the dictionary doesn't know (rather than a confusable pair
    like "too ask"), which can go on the writer's own list."""
    return rule.get("issueType") == "misspelling" and bool(re.search(r"MORFOLOGIK|SPELLER|HUNSPELL", rule.get("id") or "")) \
        and " " not in word.strip()


def _line_start(text, offset):
    return offset == 0 or text[offset - 1] == "\n"


def check(text, language=None, poem=False):
    """Suggestions for text, as {"matches": [...], "language"}; offsets
    refer to text as given."""
    s = settings()
    language = language or s["language"]
    base = _base()
    checked = _blank_header(text)
    out, detected = [], ""
    words = {w.casefold() for w in s["words"]}
    for offset, piece in _chunks(checked):
        if not piece.strip():
            continue
        form = {"text": piece, "language": language, "level": "picky" if s["picky"] else "default"}
        if language == "auto":
            form["preferredVariants"] = "en-US,de-DE,pt-PT"
        off = (POETRY_OFF if poem else []) + s["rules"]
        if off:
            form["disabledRules"] = ",".join(off)
        req = urllib.request.Request(base + "/v2/check", data=urllib.parse.urlencode(form).encode("utf-8"),
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Minerva"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                d = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise GrammarError(f"LanguageTool couldn't check this: {e.read().decode('utf-8', errors='replace')[:200]}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise GrammarError(f"Couldn't reach LanguageTool ({getattr(e, 'reason', e)}).") from None
        detected = detected or ((d.get("language") or {}).get("detectedLanguage") or {}).get("name") or \
            (d.get("language") or {}).get("name") or ""
        for m in d.get("matches") or []:
            rule = m.get("rule") or {}
            category = (rule.get("category") or {}).get("id") or ""
            at = offset + int(m.get("offset") or 0)
            length = int(m.get("length") or 0)
            # in a poem, a capital at the start of a line is the poet's choice
            if poem and category == "CASING" and _line_start(text, at):
                continue
            # a word added to the writer's own list
            if _dictionary_miss(rule, text[at:at + length]) and text[at:at + length].casefold() in words:
                continue
            out.append({"offset": at, "length": length, "text": text[at:at + length],
                        "message": m.get("message") or "", "short": m.get("shortMessage") or "",
                        "replacements": [r.get("value") for r in (m.get("replacements") or [])[:5] if r.get("value") is not None],
                        "rule": rule.get("id") or "", "rule_name": rule.get("description") or "",
                        "category": (rule.get("category") or {}).get("name") or "",
                        "kind": "spelling" if _dictionary_miss(rule, text[at:at + length]) else
                                "style" if rule.get("issueType") in ("style", "locale-violation", "register") else "grammar"})
    return {"matches": out, "language": detected}


def add_word(word):
    word = " ".join(str(word or "").split())
    if not word or len(word) > 60:
        raise GrammarError("That isn't a word Minerva can add.")
    return save_settings({"words": settings()["words"] + [word]})


def ignore_rule(rule):
    return save_settings({"rules": settings()["rules"] + [rule]})

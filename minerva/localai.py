"""One-click free, private AI: a vision model running on this computer
through Ollama.

check() looks at the computer (memory, graphics card, free disk space) and
at Ollama (installed? running? which models?), and recommends a model sized
to the machine with its download size and a rough speed. setup() is a
background job that, after the user says go, installs Ollama when it's
missing (Windows), starts it, downloads the model, reads a test page with
it, and only then turns on the AI features the user picked.

Nothing here runs without the user starting it, and nothing leaves the
computer except the downloads from ollama.com.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from . import ai, config as app_config

INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
DOWNLOAD_PAGE = "https://ollama.com/download"

GB = 1024 ** 3

# Vision models, biggest first. size_gb is the download (and disk) size;
# memory_gb is what the model wants free to run at a usable speed.
MODELS = [
    {"name": "qwen3-vl:8b", "label": "Qwen3-VL 8B", "size_gb": 6.1, "memory_gb": 16,
     "about": "Best of the three at reading pages. Wants 16 GB of memory or a graphics card with 8 GB."},
    {"name": "qwen3-vl:4b", "label": "Qwen3-VL 4B", "size_gb": 3.3, "memory_gb": 8,
     "about": "Good on typed pages and neat handwriting. Runs on most computers with 8 GB of memory."},
    {"name": "qwen3-vl:2b", "label": "Qwen3-VL 2B", "size_gb": 1.9, "memory_gb": 4,
     "about": "The smallest. Fine for typed pages; often wrong on handwriting."},
]

TEST_LINES = [
    "The heron stands in the shallows,",
    "patient as a question",
    "nobody has thought to ask.",
]
TEST_SYSTEM = "You read text from images. Reply with only the text in the image, line by line, and nothing else."


class LocalAiError(Exception):
    user_facing = True


# --------------------------------------------------------------------------
# Looking at the computer
# --------------------------------------------------------------------------

def _memory_gb():
    if os.name == "nt":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys / GB
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / GB
    except (ValueError, OSError, AttributeError):
        return None


def _no_window():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW


def _gpu():
    """The NVIDIA card Ollama would use, as {"name", "memory_gb"}, or None.
    Other cards may work too, but there's no dependable way to ask them."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, **_no_window()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    best = None
    for line in out.splitlines():
        name, _, mem = line.rpartition(",")
        try:
            gb = float(mem.strip()) / 1024
        except ValueError:
            continue
        if best is None or gb > best["memory_gb"]:
            best = {"name": name.strip(), "memory_gb": round(gb, 1)}
    return best


def _disk_free_gb():
    """Free space where Ollama keeps models (the home drive, unless moved)."""
    where = os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~")
    try:
        return shutil.disk_usage(where).free / GB
    except OSError:
        return None


def ollama_exe():
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        guess = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
        if os.path.isfile(guess):
            return guess
    return None


def ollama_version():
    """Ollama's version when it's running and answering, else None."""
    try:
        with urllib.request.urlopen(f"{ai.OLLAMA_URL}/api/version", timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8")).get("version") or "?"
    except (OSError, ValueError, urllib.error.URLError):
        return None


def ollama_models():
    try:
        return ai.list_models("ollama")
    except ai.ProviderError:
        return []


def can_install():
    return os.name == "nt"


def system_check():
    running = ollama_version()
    return {
        "memory_gb": _round(_memory_gb()),
        "gpu": _gpu(),
        "disk_free_gb": _round(_disk_free_gb()),
        "ollama": {
            "installed": bool(running or ollama_exe()),
            "running": bool(running),
            "version": running,
            "models": ollama_models() if running else [],
        },
        "can_install": can_install(),
        "download_page": DOWNLOAD_PAGE,
    }


def _round(v):
    return round(v, 1) if v is not None else None


def _speed(model, check):
    gpu = check.get("gpu")
    if gpu and gpu["memory_gb"] >= model["size_gb"] + 1:
        return "A few seconds a page, on your graphics card."
    mem = check.get("memory_gb") or 0
    if mem >= model["memory_gb"] - 1:
        return "Around a minute a page, on the processor. A scan of 30 pages is a coffee break."
    return "Several minutes a page, since the model barely fits in memory. Leave it running and do something else."


def recommend(check):
    """The model to suggest, and every choice with whether it fits."""
    mem = check.get("memory_gb") or 0
    vram = (check.get("gpu") or {}).get("memory_gb") or 0
    disk = check.get("disk_free_gb")
    have = set(check.get("ollama", {}).get("models") or [])
    # a "16 GB" computer reports a little under 16
    if mem >= 15 or vram >= 8:
        pick = "qwen3-vl:8b"
    elif mem >= 7:
        pick = "qwen3-vl:4b"
    else:
        pick = "qwen3-vl:2b"
    choices = []
    for m in MODELS:
        downloaded = m["name"] in have
        room = downloaded or disk is None or disk >= m["size_gb"] + 1
        choices.append(m | {"speed": _speed(m, check), "downloaded": downloaded, "room": room,
                            "fits": mem >= m["memory_gb"] - 1 or vram >= m["size_gb"] + 1})
    warnings = []
    if mem and mem < 7:
        warnings.append(f"This computer has {mem:g} GB of memory. Local models will be slow, and the small one "
                        "makes mistakes on handwriting. An AI service may suit you better.")
    if not next(c for c in choices if c["name"] == pick)["room"]:
        warnings.append(f"There isn't enough free disk space for this model ({disk:g} GB free). "
                        "Free some space or pick a smaller model.")
        smaller = [c for c in choices if c["room"]]
        if smaller:
            pick = smaller[0]["name"]
    return {"model": pick, "choices": choices, "warnings": warnings}


def check():
    c = system_check()
    return c | {"recommendation": recommend(c)}


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
                    raise LocalAiError("Stopped.")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                job.progress(done, total, f"{label}: {done / GB:.2f} of {total / GB:.2f} GB" if total else label)
    except (urllib.error.URLError, OSError) as e:
        raise LocalAiError(f"Couldn't download Ollama ({getattr(e, 'reason', e)}). Check your internet connection.") from None


def install_ollama(job):
    if not can_install():
        raise LocalAiError(f"Install Ollama from {DOWNLOAD_PAGE}, then check again.")
    folder = tempfile.mkdtemp(prefix="minerva-ollama-")
    setup_exe = os.path.join(folder, "OllamaSetup.exe")
    try:
        _download(INSTALLER_URL, setup_exe, job, "Downloading Ollama")
        job.progress(0, 0, "Installing Ollama (Windows may ask you to allow it)")
        # Ollama's installer is an Inno Setup program: these flags install it
        # for this user without questions
        try:
            result = subprocess.run([setup_exe, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES"],
                                    timeout=900, **_no_window())
        except (OSError, subprocess.SubprocessError) as e:
            raise LocalAiError(f"The Ollama installer didn't run ({e}). You can install it from {DOWNLOAD_PAGE}.") from None
        if result.returncode != 0 or not ollama_exe():
            raise LocalAiError(f"The Ollama installer stopped before finishing. You can install it from {DOWNLOAD_PAGE}.")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def start_ollama(job, wait=60):
    if ollama_version():
        return
    exe = ollama_exe()
    if not exe:
        raise LocalAiError("Ollama isn't installed.")
    job.progress(0, 0, "Starting Ollama")
    app = os.path.join(os.path.dirname(exe), "ollama app.exe")
    cmd = [app] if os.name == "nt" and os.path.isfile(app) else [exe, "serve"]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, **({"creationflags": 0x08000000 | 0x00000008} if os.name == "nt"
                                            else {"start_new_session": True}))
    except OSError as e:
        raise LocalAiError(f"Couldn't start Ollama ({e}).") from None
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if job.cancelled():
            raise LocalAiError("Stopped.")
        if ollama_version():
            return
        time.sleep(1)
    raise LocalAiError("Ollama didn't start. Try opening it from the Start menu, then check again.")


def _pull_lines(model):
    req = urllib.request.Request(f"{ai.OLLAMA_URL}/api/pull", data=json.dumps({"model": model, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line = line.strip()
            if line:
                yield json.loads(line)


def pull_model(job, model):
    """Download a model through Ollama, reporting progress across its layers."""
    layers = {}
    try:
        for msg in _pull_lines(model):
            if job.cancelled():
                raise LocalAiError("Stopped. What was downloaded is kept, so starting again picks up where it left off.")
            if msg.get("error"):
                raise LocalAiError(f"Ollama couldn't download {model}: {msg['error']}")
            if msg.get("digest") and msg.get("total"):
                layers[msg["digest"]] = (msg.get("completed") or 0, msg["total"])
            done = sum(d for d, _t in layers.values())
            total = sum(t for _d, t in layers.values())
            status = msg.get("status") or ""
            if total and status.startswith("pulling"):
                job.progress(done, total, f"Downloading {model}: {done / GB:.2f} of {total / GB:.2f} GB")
            elif status:
                job.progress(done, total, status[:1].upper() + status[1:])
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LocalAiError(f"The download from Ollama stopped ({getattr(e, 'reason', e)}). Start again to pick up where it left off.") from None


def test_page():
    """A typed test page as PNG bytes."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    font = None
    for name in ("georgia.ttf", "times.ttf", "arial.ttf", "DejaVuSerif.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, 44)
            break
        except OSError:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=44)
        except TypeError:
            font = ImageFont.load_default()
    img = Image.new("RGB", (1100, 420), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(TEST_LINES):
        draw.text((70, 80 + i * 90), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _words(text):
    return {w.strip(".,;:!?\"'").lower() for w in text.split()} - {""}


def run_test(model):
    """Read the test page with the model. Returns (ok, seconds, text)."""
    started = time.monotonic()
    text = ai.complete("ollama", model, None, TEST_SYSTEM, "Read the text in this image.",
                       images=[("image/png", test_page())], max_tokens=400)
    seconds = round(time.monotonic() - started, 1)
    want = _words(" ".join(TEST_LINES))
    ok = len(want & _words(text)) >= 0.7 * len(want)
    return ok, seconds, text.strip()


def use(model, features):
    """Turn on the given AI features with this local model."""
    cfg = app_config.load()
    for f in features:
        if f in app_config.FEATURES:
            cfg["ai"][f] = {"enabled": True, "provider": "ollama", "model": model}
    app_config.save(cfg)


def setup(job, model, features):
    if model not in {m["name"] for m in MODELS}:
        raise LocalAiError("Pick one of the suggested models.")
    if not ollama_version():
        if not ollama_exe():
            install_ollama(job)
        start_ollama(job)
    if model not in ollama_models():
        pull_model(job, model)
    if job.cancelled():
        raise LocalAiError("Stopped.")
    job.progress(0, 0, "Reading a test page (the first one is slowest while the model loads)")
    try:
        ok, seconds, text = run_test(model)
    except ai.ProviderError as e:
        raise LocalAiError(f"The model is downloaded but couldn't read the test page: {e}") from None
    if ok:
        use(model, features)
    return {"model": model, "ok": ok, "seconds": seconds, "text": text, "features": list(features) if ok else []}


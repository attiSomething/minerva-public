"""The free audio and video tool, FFmpeg, which turns narrations into MP3s
and (later) videos.

FFmpeg isn't shipped inside Minerva. When it's first needed, Minerva
downloads a Windows build once (about 31 MB) from the Python Package Index,
where the imageio-ffmpeg project publishes it, checks it against the
fingerprint below, and keeps just ffmpeg.exe in Minerva's settings folder.
Nothing is installed system-wide. An ffmpeg already on the PATH is used as
it is.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile

from . import config as app_config

WHEEL = {
    "url": "https://files.pythonhosted.org/packages/2c/c6/fa760e12a2483469e2bf5058c5faff664acf66cadb4df2ad6205b016a73d/"
           "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl",
    "sha256": "02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a",
    "size": 31246824,
    "member": "imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe",
}
MB = 1024 * 1024


class MediaError(Exception):
    user_facing = True


def _tools_dir():
    return os.path.join(app_config.config_dir(), "tools")


def _no_window():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW


def ffmpeg():
    """Path to ffmpeg, or None."""
    mine = os.path.join(_tools_dir(), "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(mine):
        return mine
    return shutil.which("ffmpeg")


def can_install():
    return os.name == "nt"


def status():
    return {"ffmpeg": bool(ffmpeg()), "can_install": can_install(), "download_mb": round(WHEEL["size"] / MB)}


def install(job):
    """Download FFmpeg once, as a background job."""
    if ffmpeg():
        return status()
    if not can_install():
        raise MediaError("Install FFmpeg with your system's package manager, then try again.")
    folder = tempfile.mkdtemp(prefix="minerva-ffmpeg-")
    wheel = os.path.join(folder, "ffmpeg.whl")
    try:
        digest = hashlib.sha256()
        req = urllib.request.Request(WHEEL["url"], headers={"User-Agent": "Minerva"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(wheel, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or WHEEL["size"])
                done = 0
                while True:
                    if job.cancelled():
                        raise MediaError("Stopped.")
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    job.progress(done, total, f"Downloading the audio and video tool: {done // MB} of {total // MB} MB")
        except (urllib.error.URLError, OSError) as e:
            raise MediaError(f"Couldn't download the audio and video tool ({getattr(e, 'reason', e)}). "
                             "Check your internet connection.") from None
        if digest.hexdigest() != WHEEL["sha256"]:
            raise MediaError("The download didn't match what was expected, so it wasn't used. Try again later.")
        os.makedirs(_tools_dir(), exist_ok=True)
        dest = os.path.join(_tools_dir(), "ffmpeg.exe")
        with zipfile.ZipFile(wheel) as z, z.open(WHEEL["member"]) as src, open(dest + ".part", "wb") as out:
            shutil.copyfileobj(src, out)
        os.replace(dest + ".part", dest)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return status()


def run(args, timeout=1800):
    """Run ffmpeg with args (no "ffmpeg" at the front)."""
    exe = ffmpeg()
    if not exe:
        raise MediaError("The audio and video tool isn't set up yet.")
    try:
        proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", *args],
                              capture_output=True, timeout=timeout, **_no_window())
    except (OSError, subprocess.SubprocessError) as e:
        raise MediaError(f"The audio and video tool didn't run ({e}).") from None
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise MediaError("The audio and video tool stopped: " + (" ".join(tail) or f"exit code {proc.returncode}"))


def run_with_progress(args, seconds, job, label, timeout=7200):
    """Run ffmpeg, reporting how far through `seconds` of media it is."""
    exe = ffmpeg()
    if not exe:
        raise MediaError("The audio and video tool isn't set up yet.")
    try:
        proc = subprocess.Popen([exe, "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_no_window())
    except OSError as e:
        raise MediaError(f"The audio and video tool didn't run ({e}).") from None
    total = max(1, int(seconds))
    try:
        for raw in proc.stdout:
            line = raw.decode("ascii", errors="replace").strip()
            if job.cancelled():
                proc.kill()
                raise MediaError("Stopped.")
            if line.startswith("out_time_us=") and line[12:].isdigit():
                done = min(total, int(line[12:]) // 1000000)
                job.progress(done, total, f"{label}: {done // 60}:{done % 60:02d} of {total // 60}:{total % 60:02d}")
        err = proc.stderr.read()
        proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        tail = err.decode("utf-8", errors="replace").strip().splitlines()[-3:]
        raise MediaError("The audio and video tool stopped: " + (" ".join(tail) or f"exit code {proc.returncode}"))

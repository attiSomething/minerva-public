"""Narration: an entry or a project read into an audio file.

Two kinds of voice:

- This computer's voices (free, offline). Windows' own speech engine
  (Windows.Media.SpeechSynthesis, the voices read aloud uses), reached
  through Windows PowerShell like the free text recognition. Each line is
  spoken on its own, so its place in the audio is known exactly.
- ElevenLabs, with the writer's own key, kept in the Windows credential
  store like the AI keys. The text goes to ElevenLabs; a few stanzas go in
  each request, which comes back with the timing of every character.

Line and stanza pauses follow read aloud. The audio is put together here as
plain WAV, then made into an MP3 by the audio and video tool (FFmpeg) when
it's set up. A project can be one file with a chapter per piece, or one
file per piece. Where each line falls is kept in .minerva/narrations, so a
video can show the words in time with the voice.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave

from . import config as app_config, core, mediatools, secrets_store, sharing

ENGINES = {"system": "This computer's voices", "elevenlabs": "ElevenLabs"}
PACES = {  # (Windows speaking rate, ElevenLabs speed)
    "slower": (0.8, 0.85),
    "normal": (1.0, 1.0),
    "faster": (1.25, 1.15),
}
PACE_LABELS = {"slower": "Slower", "normal": "Normal", "faster": "Faster"}
LINE_GAP = 0.3
STANZA_GAP = 0.9
TITLE_GAP = 1.4
PIECE_GAP = 2.5

EL_URL = "https://api.elevenlabs.io"
EL_MODEL = "eleven_multilingual_v2"   # one credit per character
EL_RATE = 24000                       # pcm_24000: raw 16-bit mono, on every plan
EL_CHUNK = 2500
EL_KEY = "elevenlabs"
CHARS_PER_MINUTE = 850                # about how fast a voice reads


class NarrationError(Exception):
    user_facing = True


def prefs():
    p = dict(app_config.load().get("narration") or {})
    return {"engine": p.get("engine") if p.get("engine") in ENGINES else "system",
            "voice": p.get("voice") or "", "el_voice": p.get("el_voice") or "",
            "pace": p.get("pace") if p.get("pace") in PACES else "normal",
            "split": p.get("split") if p.get("split") in ("one", "each") else "one",
            "format": p.get("format") if p.get("format") in ("mp3", "wav") else "mp3",
            "titles": p.get("titles", True) is not False}


def save_prefs(values):
    cfg = app_config.load()
    cfg["narration"] = {k: v for k, v in values.items()
                        if k in ("engine", "voice", "el_voice", "pace", "split", "format", "titles")}
    app_config.save(cfg)


# --------------------------------------------------------------------------
# What gets read
# --------------------------------------------------------------------------

def gather(conn, kind, item_id, which="final"):
    """(name, author, pieces) for an entry or a project."""
    if kind == "entry":
        row = core.get_entry_row(conn, item_id)
        if row is None:
            raise NarrationError("That entry no longer exists.")
        return row["title"], "", [sharing.entry_piece(row, which)]
    if kind == "project":
        project = core.get_project(conn, item_id)
        if project is None:
            raise NarrationError("That project no longer exists.")
        rows = [core.get_entry_row(conn, e["id"]) for e in project["entries"]]
        pieces = [sharing.entry_piece(r) for r in rows if r is not None]
        if not pieces:
            raise NarrationError("This project has no entries to narrate yet.")
        return project["name"], sharing.project_settings(conn, item_id)["author"], pieces
    raise NarrationError("Choose an entry or a project.")


def _split_long(line, limit):
    """A long line (a prose paragraph) as sentences grouped under limit."""
    if len(line) <= limit:
        return [line]
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", line):
        if cur and len(cur) + 1 + len(sentence) > limit:
            out.append(cur)
            cur = sentence
        else:
            cur = f"{cur} {sentence}".strip()
    if cur:
        out.append(cur)
    return [piece for chunk in out for piece in (
        [chunk[i:i + limit] for i in range(0, len(chunk), limit)] if len(chunk) > limit else [chunk])]


def script(pieces, titles=True):
    """Each piece as {"title", "stanzas": [[line, ...], ...]}, the title
    (when read) as a stanza of its own at the front."""
    out = []
    for p in pieces:
        stanzas = []
        for block in sharing._blocks(p["body"] or ""):
            lines = [x for ln in block for x in _split_long(" ".join(ln.split()), EL_CHUNK) if x]
            if lines:
                stanzas.append(lines)
        out.append({"title": p["title"], "stanzas": ([[p["title"]]] if titles else []) + stanzas,
                    "has_title": bool(titles)})
    return out


def characters(parts):
    return sum(len(line) for part in parts for stanza in part["stanzas"] for line in stanza)


# --------------------------------------------------------------------------
# This computer's voices (Windows)
# --------------------------------------------------------------------------

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
  $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $null = $task.Wait(-1)
  $task.Result
}
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($args[1] -eq 'voices') {
  $list = @($all | ForEach-Object { [ordered]@{ name = $_.DisplayName; language = $_.Language; gender = "$($_.Gender)" } })
  [Console]::Out.WriteLine((ConvertTo-Json @{ voices = $list; default = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::DefaultVoice.DisplayName } -Depth 4 -Compress))
  exit 0
}
$job = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $args[0] 'job.json') | ConvertFrom-Json
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$pick = $all | Where-Object { $_.DisplayName -eq $job.voice } | Select-Object -First 1
if ($pick) { $synth.Voice = $pick }
try { $synth.Options.SpeakingRate = [double]$job.rate } catch { }
$i = 0
foreach ($line in $job.lines) {
  $i++
  $stream = Await ($synth.SynthesizeTextToStreamAsync($line)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
  $out = [System.IO.File]::Create((Join-Path $args[0] ('{0:D5}.wav' -f $i)))
  try { [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream).CopyTo($out) }
  finally { $out.Dispose(); $stream.Dispose() }
  [Console]::Out.WriteLine("line $i")
}
[Console]::Out.WriteLine('done')
"""

_voices = None


def _powershell():
    from . import winocr
    return winocr._powershell()


def _write_script(folder):
    path = os.path.join(folder, "narrate.ps1")
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(_SCRIPT)
    return path


def system_voices():
    """{"available", "voices": [{name, language, gender}], "default"}."""
    global _voices
    if _voices is None:
        exe = _powershell()
        if not exe:
            return {"available": False, "voices": [], "default": ""}
        folder = tempfile.mkdtemp(prefix="minerva-voices-")
        try:
            proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-File", _write_script(folder), folder, "voices"],
                                  capture_output=True, timeout=60, creationflags=0x08000000)
            d = json.loads(proc.stdout.decode("utf-8", errors="replace").strip().lstrip("﻿") or "{}")
        except (OSError, subprocess.SubprocessError, ValueError):
            d = {}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        voices = d.get("voices") or []
        if isinstance(voices, dict):
            voices = [voices]
        _voices = {"available": bool(voices), "voices": voices, "default": d.get("default") or ""}
    return _voices


def _system_synth(lines, voice, rate, folder, job):
    """Speak each line into folder/00001.wav, 00002.wav, ..."""
    exe = _powershell()
    if not exe:
        raise NarrationError("This computer's voices are only available on Windows.")
    with open(os.path.join(folder, "job.json"), "w", encoding="utf-8") as fh:
        json.dump({"voice": voice, "rate": rate, "lines": lines}, fh)
    proc = subprocess.Popen([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", _write_script(folder), folder],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=0x08000000)
    try:
        for raw in proc.stdout:
            text = raw.decode("utf-8", errors="replace").strip()
            if job.cancelled():
                proc.kill()
                raise NarrationError("Stopped.")
            if text.startswith("line "):
                job.progress(int(text[5:]), len(lines), f"Reading line {text[5:]} of {len(lines)}")
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        err = proc.stderr.read().decode("utf-8", errors="replace").strip().splitlines()
        raise NarrationError("Windows' voice stopped: " + (err[-1] if err else f"exit code {proc.returncode}"))
    return [os.path.join(folder, f"{i:05d}.wav") for i in range(1, len(lines) + 1)]


# --------------------------------------------------------------------------
# ElevenLabs
# --------------------------------------------------------------------------

def _el(path, key, body=None, timeout=60):
    req = urllib.request.Request(EL_URL + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "User-Agent": "Minerva"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except ValueError:
            detail = None
        message = (detail.get("message") if isinstance(detail, dict) else detail) or e.reason
        status = detail.get("status") if isinstance(detail, dict) else ""
        if status == "quota_exceeded":
            raise NarrationError(f"Your ElevenLabs account is out of credits for this. {message}") from None
        if e.code == 401:
            raise NarrationError(f"ElevenLabs didn't accept the key. {message}") from None
        if e.code == 429:
            raise _Busy(message) from None
        raise NarrationError(f"ElevenLabs said: {message}") from None
    except (urllib.error.URLError, OSError) as e:
        raise NarrationError(f"Couldn't reach ElevenLabs ({getattr(e, 'reason', e)}). Check your internet connection.") from None


class _Busy(NarrationError):
    pass


def el_key():
    return secrets_store.get_key(EL_KEY)


def el_voices(key=None):
    key = key or el_key()
    if not key:
        raise NarrationError("Add your ElevenLabs key first.")
    d = _el("/v1/voices", key)
    voices = [{"id": v["voice_id"], "name": v.get("name") or v["voice_id"], "category": v.get("category") or "",
               "labels": v.get("labels") or {}} for v in d.get("voices") or []]
    return sorted(voices, key=lambda v: v["name"].casefold())


def el_credits(key=None):
    """Credits left this month, or None if ElevenLabs won't say."""
    key = key or el_key()
    try:
        s = _el("/v1/user/subscription", key)
        return {"left": max(0, int(s["character_limit"]) - int(s["character_count"])), "tier": s.get("tier") or "",
                "resets": s.get("next_character_count_reset_unix")}
    except (NarrationError, KeyError, TypeError, ValueError):
        return None


def save_key(key):
    key = (key or "").strip()
    if not key:
        raise NarrationError("Paste your ElevenLabs key.")
    el_voices(key)  # checks it works before keeping it
    secrets_store.set_key(EL_KEY, key)


def _el_speak(key, voice, text, speed, previous="", following=""):
    """(16-bit mono PCM at EL_RATE, alignment) for text."""
    body = {"text": text, "model_id": EL_MODEL, "voice_settings": {"speed": speed}}
    if previous:
        body["previous_text"] = previous[-500:]
    if following:
        body["next_text"] = following[:500]
    for attempt in range(4):
        try:
            d = _el(f"/v1/text-to-speech/{urllib.request.quote(voice)}/with-timestamps?output_format=pcm_{EL_RATE}",
                    key, body, timeout=180)
            return base64.b64decode(d["audio_base64"]), d.get("alignment") or {}
        except _Busy:
            if attempt == 3:
                raise NarrationError("ElevenLabs is busy. Try again in a few minutes.") from None
            time.sleep(4 * (attempt + 1))


def _chunks(stanzas):
    """Stanzas grouped into requests under EL_CHUNK characters."""
    group, size = [], 0
    for s in stanzas:
        n = sum(len(x) + 1 for x in s) + 1
        if group and size + n > EL_CHUNK:
            yield group
            group, size = [], 0
        group.append(s)
        size += n
    if group:
        yield group


def _line_times(text, offsets, alignment, seconds):
    """(start, end) of each line in the request, from character timings."""
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    exact = len(starts) == len(text) and len(ends) == len(text)
    out = []
    for a, b in offsets:
        if exact:
            out.append((starts[a], ends[b - 1]))
        else:  # timings didn't line up with the text: share the time out by length
            out.append((seconds * a / max(1, len(text)), seconds * b / max(1, len(text))))
    return out


# --------------------------------------------------------------------------
# Putting the audio together
# --------------------------------------------------------------------------

class Track:
    """16-bit mono PCM, built up piece by piece."""

    def __init__(self, rate=None):
        self.rate = rate
        self.data = bytearray()

    def seconds(self):
        return len(self.data) / 2 / self.rate if self.rate else 0.0

    def silence(self, secs):
        if self.rate:
            self.data += b"\x00\x00" * int(self.rate * secs)

    def add_pcm(self, pcm, rate):
        if self.rate is None:
            self.rate = rate
        if rate != self.rate:
            raise NarrationError("The voice changed partway through. Try again.")
        self.data += pcm[: len(pcm) - len(pcm) % 2]

    def add_wav(self, path):
        with wave.open(path, "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.readframes(w.getnframes())
        if width != 2:
            raise NarrationError("Windows' voice made audio Minerva can't read.")
        if channels == 2:  # keep the left channel
            frames = b"".join(frames[i:i + 2] for i in range(0, len(frames), 4))
        self.add_pcm(frames, rate)

    def write(self, path):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate or 22050)
            w.writeframes(bytes(self.data))


def _narrate_system(parts, opts, job):
    """[(Track, [line timings])] per piece."""
    flat = [line for part in parts for stanza in part["stanzas"] for line in stanza]
    folder = tempfile.mkdtemp(prefix="minerva-narrate-")
    try:
        wavs = iter(_system_synth(flat, opts["voice"], PACES[opts["pace"]][0], folder, job))
        out = []
        for part in parts:
            track, times = Track(), []
            for si, stanza in enumerate(part["stanzas"]):
                for li, line in enumerate(stanza):
                    start = track.seconds()
                    track.add_wav(next(wavs))
                    times.append({"text": line, "start": round(start, 3), "end": round(track.seconds(), 3),
                                  "stanza": si, "title": part["has_title"] and si == 0})
                    if li < len(stanza) - 1:
                        track.silence(LINE_GAP)
                if si < len(part["stanzas"]) - 1:
                    track.silence(TITLE_GAP if part["has_title"] and si == 0 else STANZA_GAP)
            out.append((track, times))
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _narrate_elevenlabs(parts, opts, job):
    key = el_key()
    if not key:
        raise NarrationError("Add your ElevenLabs key first.")
    if not opts.get("el_voice"):
        raise NarrationError("Choose an ElevenLabs voice.")
    speed = PACES[opts["pace"]][1]
    requests = [(pi, list(c)) for pi, part in enumerate(parts) for c in _chunks(part["stanzas"])]
    texts = ["\n\n".join("\n".join(s) for s in c) for _pi, c in requests]
    out = [(Track(EL_RATE), []) for _ in parts]
    stanza_no = [0] * len(parts)
    for n, ((pi, chunk), text) in enumerate(zip(requests, texts)):
        if job.cancelled():
            raise NarrationError("Stopped.")
        job.progress(n, len(requests), f"Reading part {n + 1} of {len(requests)} with ElevenLabs")
        pcm, alignment = _el_speak(key, opts["el_voice"], text, speed,
                                   texts[n - 1] if n and requests[n - 1][0] == pi else "",
                                   texts[n + 1] if n + 1 < len(texts) and requests[n + 1][0] == pi else "")
        track, times = out[pi]
        if track.data:
            track.silence(STANZA_GAP)
        base = track.seconds()
        track.add_pcm(pcm, EL_RATE)
        offsets, stanza_of, pos = [], [], 0
        for s in chunk:
            for line in s:
                offsets.append((pos, pos + len(line)))
                stanza_of.append(stanza_no[pi])
                pos += len(line) + 1
            pos += 1
            stanza_no[pi] += 1
        lines = [line for s in chunk for line in s]
        for line, (a, b), si in zip(lines, _line_times(text, offsets, alignment, len(pcm) / 2 / EL_RATE), stanza_of):
            times.append({"text": line, "start": round(base + a, 3), "end": round(base + b, 3), "stanza": si,
                          "title": parts[pi]["has_title"] and si == 0})
    job.progress(len(requests), len(requests), "Putting the audio together")
    return out


def _timings_dir():
    d = os.path.join(core.META_DIR, "narrations")
    os.makedirs(d, exist_ok=True)
    return d


def timings(name):
    """The line timings kept for an exported narration, or None."""
    path = os.path.join(_timings_dir(), os.path.basename(name) + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save(chapters, stem, fmt, meta):
    """Write chapters [(title, Track, times)] as one file; its result."""
    track = Track(chapters[0][1].rate)
    lines, marks = [], []
    for i, (title, t, times) in enumerate(chapters):
        if i:
            track.silence(PIECE_GAP)
        start = track.seconds()
        track.data += t.data
        lines += [x | {"start": round(x["start"] + start, 3), "end": round(x["end"] + start, 3), "chapter": i}
                  for x in times]
        marks.append({"title": title, "start": round(start, 3), "end": round(track.seconds(), 3)})
    path = sharing._unique_path(stem, fmt)
    tmp_wav = path + ".minerva-tmp.wav"
    try:
        track.write(tmp_wav if fmt == "mp3" else path)
        if fmt == "mp3":
            ffmeta = path + ".minerva-tmp.txt"
            esc = lambda s: re.sub(r"([=;#\\\n])", r"\\\1", s)  # noqa: E731
            with open(ffmeta, "w", encoding="utf-8") as fh:
                fh.write(";FFMETADATA1\n")
                fh.write(f"title={esc(meta['title'])}\n")
                if meta.get("author"):
                    fh.write(f"artist={esc(meta['author'])}\n")
                if len(marks) > 1:
                    for m in marks:
                        fh.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(m['start'] * 1000)}\n"
                                 f"END={int(m['end'] * 1000)}\ntitle={esc(m['title'])}\n")
            try:
                mediatools.run(["-i", tmp_wav, "-i", ffmeta, "-map_metadata", "1", "-map_chapters", "1",
                                "-codec:a", "libmp3lame", "-q:a", "4", "-id3v2_version", "3", path])
            finally:
                os.remove(ffmeta)
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)
    name = os.path.basename(path)
    with open(os.path.join(_timings_dir(), name + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"audio": name, "title": meta["title"], "author": meta.get("author") or "",
                   "kind": meta.get("kind"), "id": meta.get("id"),
                   "seconds": round(track.seconds(), 3), "chapters": marks, "lines": lines}, fh, ensure_ascii=False)
    return {"name": name, "folder": os.path.relpath(os.path.dirname(path), core.ARCHIVE_ROOT),
            "seconds": round(track.seconds())}


def estimate(conn, kind, item_id, which="final", engine="system", titles=True):
    name, _author, pieces = gather(conn, kind, item_id, which)
    chars = characters(script(pieces, titles))
    r = {"title": name, "pieces": len(pieces), "characters": chars,
         "minutes": max(1, round(chars / CHARS_PER_MINUTE))}
    if engine == "elevenlabs":
        r["credits"] = chars
        r["has_key"] = bool(el_key())
        if r["has_key"]:
            r["account"] = el_credits()
    return r


def narrate(job, conn, kind, item_id, opts):
    """The background job: read it, put it together, save it to Exports."""
    opts = prefs() | {k: v for k, v in (opts or {}).items() if v is not None}
    if opts["engine"] not in ENGINES or opts["pace"] not in PACES:
        raise NarrationError("Choose a voice and a pace.")
    if opts["format"] == "mp3" and not mediatools.ffmpeg():
        raise NarrationError("Saving an MP3 needs the audio and video tool. Set it up, or save a WAV.")
    name, author, pieces = gather(conn, kind, item_id, opts.get("which") or "final")
    parts = script(pieces, opts["titles"])
    job.progress(0, 0, "Starting the voice")
    made = (_narrate_elevenlabs if opts["engine"] == "elevenlabs" else _narrate_system)(parts, opts, job)
    if job.cancelled():
        raise NarrationError("Stopped.")
    job.progress(0, 0, "Saving")
    chapters = [(p["title"], t, times) for p, (t, times) in zip(parts, made)]
    if kind == "project" and opts["split"] == "one":
        files = [_save(chapters, f"{name} - audiobook", opts["format"],
                       {"title": name, "author": author, "kind": kind, "id": item_id})]
    else:
        files = [_save([c], f"{c[0]} - narration", opts["format"],
                       {"title": c[0], "author": author, "kind": kind, "id": item_id}) for c in chapters]
    return {"files": files, "characters": characters(parts), "engine": opts["engine"]}

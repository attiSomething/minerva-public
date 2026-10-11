"""Free, offline text recognition for typed pages, using the OCR engine
built into Windows 10 and 11 (Windows.Media.Ocr).

Python reaches it through Windows PowerShell, which can call Windows
Runtime APIs without any extra packages. The engine reads print well and
handwriting badly, so each result is checked: only a page that reads like
typed text is used, and everything else is left for the AI model (or for
later, when no AI is turned on).
"""

import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import threading

MIN_WORDS = 8

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
  $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $null = $task.Wait(-1)
  $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { '{"error": "no-language"}'; exit 0 }
$pages = New-Object System.Collections.Generic.List[object]
foreach ($path in (Get-ChildItem -LiteralPath $args[0] -Filter '*.png' | Sort-Object Name)) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path.FullName)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  } finally { $stream.Dispose() }
  $lines = New-Object System.Collections.Generic.List[object]
  foreach ($line in $result.Lines) {
    $words = New-Object System.Collections.Generic.List[object]
    foreach ($w in $line.Words) {
      $r = $w.BoundingRect
      $words.Add([ordered]@{ t = $w.Text; x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height })
    }
    $lines.Add([ordered]@{ words = $words })
  }
  $pages.Add([ordered]@{ lines = $lines })
}
ConvertTo-Json -InputObject ([ordered]@{ language = $engine.RecognizerLanguage.LanguageTag; pages = $pages }) -Depth 8 -Compress
"""

_COMMON = set("""the of and a to in is was it i that he she for on with as his her you they at be this have from or
had by not but are were we my me all one so no there their when which an what them out if up into him its our
your then who will would like can could been has do did over only now down just more some these than about""".split())

_lock = threading.Lock()
_available = None  # cached probe result: None (not checked), or a dict


def _powershell():
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    exe = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return exe if os.path.isfile(exe) else shutil.which("powershell")


def _run(folder, timeout):
    """Run the OCR script over every PNG in folder; the parsed JSON reply."""
    exe = _powershell()
    if not exe:
        return {"error": "not-windows"}
    script = os.path.join(folder, "ocr.ps1")
    with open(script, "w", encoding="utf-8-sig") as fh:
        fh.write(_SCRIPT)
    try:
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", script, folder],
                              capture_output=True, timeout=timeout, creationflags=0x08000000)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": str(e)}
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(out.lstrip("\ufeff"))
    except ValueError:
        return {"error": (proc.stderr.decode("utf-8", errors="replace").strip() or out)[:300]}


def available():
    """Whether Windows text recognition works here, as {"ok", "language"}.
    Checked once per run by reading a tiny blank image."""
    global _available
    with _lock:
        if _available is None:
            if not _powershell():
                _available = {"ok": False, "language": ""}
            else:
                from PIL import Image

                folder = tempfile.mkdtemp(prefix="minerva-ocr-")
                try:
                    Image.new("RGB", (60, 40), "white").save(os.path.join(folder, "1.png"))
                    r = _run(folder, 60)
                finally:
                    shutil.rmtree(folder, ignore_errors=True)
                _available = {"ok": "pages" in r, "language": r.get("language") or ""}
        return dict(_available)


def read_pages(images, timeout=300):
    """Recognize each image (bytes in any format Pillow reads). Returns one
    dict per image: text, words, language and typed (whether it reads like
    a typed or printed page), or None for every image when recognition
    isn't available."""
    from PIL import Image
    import io

    folder = tempfile.mkdtemp(prefix="minerva-ocr-")
    try:
        for i, data in enumerate(images):
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.save(os.path.join(folder, f"{i:05d}.png"))
        r = _run(folder, timeout)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if "pages" not in r:
        return [None] * len(images)
    pages = r["pages"] if isinstance(r["pages"], list) else [r["pages"]]
    return [_page(p, r.get("language") or "") for p in pages]


def read_page(image, timeout=120):
    return read_pages([image], timeout)[0]


def _as_list(v):
    # PowerShell writes a one-item list as the item itself
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _page(p, language):
    lines = []
    for line in _as_list(p.get("lines")):
        words = [w for w in _as_list(line.get("words")) if isinstance(w, dict) and w.get("t")]
        if words:
            lines.append(words)
    text = "\n".join(" ".join(w["t"] for w in line) for line in lines)
    return {"text": text, "words": sum(len(line) for line in lines), "language": language,
            "typed": looks_typed(lines, language)}


_WORDLIKE = re.compile(r"^[\"'“‘(\[]*[^\W\d_]+(?:['’-][^\W\d_]+)*[.,;:!?\"'”’)\]]*$|^[\d.,:/%$-]+$")


def looks_typed(lines, language=""):
    """Whether recognized lines (lists of {"t", "x", "y", "w", "h"}) read
    like a typed or printed page. Handwriting comes back as fragments of
    odd sizes and non-words; print comes back as words in even lines."""
    words = [w for line in lines for w in line]
    if len(words) < MIN_WORDS:
        return False
    tokens = [w["t"] for w in words]
    wordlike = sum(1 for t in tokens if _WORDLIKE.match(t)) / len(tokens)
    if wordlike < 0.85:
        return False
    heights = [max(w.get("h", 0) for w in line) for line in lines if len(line) >= 2]
    if len(heights) >= 3:
        mean = statistics.mean(heights)
        if mean <= 0 or statistics.pstdev(heights) / mean > 0.35:
            return False
    if language.lower().startswith("en"):
        common = sum(1 for t in tokens if t.strip(".,;:!?\"'“”‘’()[]").lower() in _COMMON) / len(tokens)
        if common < 0.12:
            return False
    return True

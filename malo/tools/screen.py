"""See the screen as text.

OCR over a capture, with coordinates, so a control can be found by its label and
clicked the way a person would. Local only, no cloud calls.

Two engines. `winocr` uses the OS recogniser, which is GPU-backed and needs no
install. `rapidocr` is the portable fallback and can be pointed at DirectML on
AMD with ocr_dml. `auto` prefers the OS engine.
"""
import json
import os
import subprocess
import time

from ..core import config
from ..core.config import paths
from ..platform import current
from . import input as itools

_RAPID = None
_RAPID_TRIED = False
_PS1 = None

_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) {
  $asTask.MakeGenericMethod($t).Invoke($null, @($op)).GetAwaiter().GetResult()
}
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]

$src = $args[0]
$dst = $args[1]
Set-Content -Path $dst -Value '' -Encoding UTF8

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($src)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync(0)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) {
  Add-Content -Path $dst -Value '{"error":"no OCR language pack"}' -Encoding UTF8
  exit 0
}
$res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

foreach ($line in $res.Lines) {
  $text = ($line.Words | ForEach-Object { $_.Text }) -join ' '
  $xs = @(); $ys = @()
  foreach ($w in $line.Words) {
    $r = $w.BoundingRect
    $xs += $r.X; $xs += ($r.X + $r.Width)
    $ys += $r.Y; $ys += ($r.Y + $r.Height)
  }
  $x = ($xs | Measure-Object -Minimum).Minimum
  $y = ($ys | Measure-Object -Minimum).Minimum
  $x2 = ($xs | Measure-Object -Maximum).Maximum
  $y2 = ($ys | Measure-Object -Maximum).Maximum
  $obj = @{ text = $text; conf = 0.95; x = [int]$x; y = [int]$y
            w = [int]($x2 - $x); h = [int]($y2 - $y) }
  Add-Content -Path $dst -Value ($obj | ConvertTo-Json -Compress) -Encoding UTF8
}
"""


def _ps1():
    global _PS1
    if _PS1 is None:
        _PS1 = os.path.join(paths().root, "_winocr.ps1")
        os.makedirs(os.path.dirname(_PS1), exist_ok=True)
        with open(_PS1, "w", encoding="utf-8-sig") as fh:
            fh.write(_PS)
    return _PS1


def _rapid():
    global _RAPID, _RAPID_TRIED
    if _RAPID_TRIED:
        return _RAPID
    _RAPID_TRIED = True
    try:
        from rapidocr import RapidOCR
    except Exception:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:
            _RAPID = None
            return None
    try:
        if config.CFG.get("ocr_dml"):
            _RAPID = RapidOCR(params={"EngineConfig.onnxruntime.use_dml": True})
        else:
            _RAPID = RapidOCR()
    except Exception:
        try:
            _RAPID = RapidOCR()
        except Exception:
            _RAPID = None
    return _RAPID


def _engine_name():
    want = (config.CFG.get("ocr_engine") or "auto").strip().lower()
    if want in ("winocr", "rapidocr"):
        return want
    if os.name == "nt":
        return "winocr"
    return "rapidocr"


def _grab(monitor=0):
    p = current()
    shots = p.screens()
    idx = int(monitor or 0)
    if not 0 <= idx < len(shots):
        raise RuntimeError("monitor %d out of range 0-%d" % (idx, len(shots) - 1))
    s = shots[idx]
    img = p.grab((s["left"], s["top"], s["left"] + s["width"], s["top"] + s["height"]))
    if img is None:
        raise RuntimeError("capture unsupported here")
    return img, s["left"], s["top"]


def _ocr(img, engine=None):
    """Return [(text, conf, x, y, w, h)] in image coordinates."""
    engine = engine or _engine_name()
    tmp = os.path.join(paths().root, "_ocr.png")
    res_file = os.path.join(paths().root, "_ocr.jsonl")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    img.save(tmp)
    try:
        if engine == "winocr":
            try:
                os.remove(res_file)
            except Exception:
                pass
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", _ps1(), tmp, res_file],
                capture_output=True, encoding="utf-8", errors="replace", timeout=60)
            try:
                with open(res_file, encoding="utf-8-sig", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except Exception:
                lines = []
            if not lines:
                tail = (out.stderr or "").strip().splitlines()[-4:]
                raise RuntimeError("OCR produced nothing%s"
                                   % (": " + " | ".join(tail) if tail else ""))
            rows = []
            for line in lines:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if "error" in d:
                    raise RuntimeError(d["error"])
                rows.append((d["text"], float(d.get("conf") or 0.9),
                             d["x"], d["y"], d["w"], d["h"]))
            return rows
        eng = _rapid()
        if eng is None:
            raise RuntimeError("no OCR engine - pip install rapidocr")
        res = eng(tmp)
        pairs = getattr(res, "txts", None)
        if pairs is not None:
            boxes = getattr(res, "boxes", []) or []
            scores = getattr(res, "scores", []) or []
            rows = []
            for i, text in enumerate(pairs):
                box = boxes[i] if i < len(boxes) else None
                conf = float(scores[i]) if i < len(scores) else 0.9
                if box is None:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                rows.append((str(text), conf, min(xs), min(ys),
                             max(xs) - min(xs), max(ys) - min(ys)))
            return rows
        rows = []
        for item in (res or []):
            box, text, conf = item[0], str(item[1]), float(item[2])
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            rows.append((text, conf, min(xs), min(ys),
                         max(xs) - min(xs), max(ys) - min(ys)))
        return rows
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
        try:
            os.remove(res_file)
        except Exception:
            pass


def look(monitor=0, limit=80, min_conf=0.45):
    """Capture and OCR the screen. Rows carry text and centre coordinates."""
    try:
        img, ox, oy = _grab(monitor)
        raw = _ocr(img)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    rows = []
    for text, conf, x, y, w, h in raw:
        if conf < min_conf or not text.strip():
            continue
        rows.append({"text": text.strip(), "x": int(x + ox), "y": int(y + oy),
                     "w": int(w), "h": int(h),
                     "cx": int(x + ox + w / 2), "cy": int(y + oy + h / 2),
                     "conf": round(conf, 2)})
    rows.sort(key=lambda r: (r["y"], r["x"]))
    rows = rows[:int(limit or 80)]
    return {"ok": True, "engine": _engine_name(), "count": len(rows),
            "monitor": int(monitor or 0), "rows": rows,
            "text": "\n".join("%s  @%d,%d %dx%d" % (r["text"], r["cx"], r["cy"],
                                                    r["w"], r["h"]) for r in rows)}


def find(text, monitor=0, min_conf=0.45, exact=False, limit=300):
    """Find one on-screen label. Prefers an exact, small match."""
    want = str(text or "").strip().lower()
    if not want:
        return {"error": "text is required"}
    got = look(monitor=monitor, min_conf=min_conf, limit=limit)
    if "error" in got:
        return got
    best, best_score = None, -1.0
    for r in got["rows"]:
        t = r["text"].lower()
        if exact:
            if t != want:
                continue
            score = 10.0
        elif t == want:
            score = 10.0
        elif want in t:
            score = 5.0
        elif t in want:
            score = 3.0
        else:
            continue
        score += r["conf"] * 2
        score -= min(3.0, (r["w"] * r["h"]) / 40000.0)
        if score > best_score:
            best, best_score = r, score
    if not best:
        return {"error": "no match for %r" % text, "count": got["count"]}
    return best


def click_text(text, monitor=0, exact=False, button="left", double=False):
    """Click the centre of an on-screen label."""
    hit = find(text, monitor=monitor, exact=exact)
    if "error" in hit:
        return hit
    moved = itools.mouse_move(hit["cx"], hit["cy"])
    time.sleep(0.15)
    out = itools.click(button=button, double=double)
    return {"clicked": hit["text"], "at": [hit["cx"], hit["cy"]],
            "moved": moved.get("moved"), "ok": out.get("clicked")}


def type_at(x, y, text):
    """Click a point and type into whatever is focused."""
    itools.mouse_move(int(x), int(y))
    time.sleep(0.15)
    itools.click()
    time.sleep(0.25)
    return itools.type_text(text)


def wait_for(text, timeout=20, interval=1.0):
    """Block until a label appears. Returns the match."""
    end = time.time() + float(timeout or 20)
    while time.time() < end:
        hit = find(text)
        if "error" not in hit:
            return hit
        time.sleep(interval)
    return {"error": "timed out waiting for %r" % text}


def read(x, y, w, h):
    """OCR one rectangle only. Far cheaper than a full-screen pass."""
    try:
        img, _, _ = _grab(0)
        crop = img.crop((int(x), int(y), int(x + w), int(y + h)))
        raw = _ocr(crop)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    lines = [t.strip() for t, c, *_ in raw if c >= 0.45 and t.strip()]
    return {"ok": True, "lines": lines, "text": "\n".join(lines)}


def ocr_info():
    """Which engine is selected and what is installed."""
    want = (config.CFG.get("ocr_engine") or "auto").strip().lower()
    return {"engine": _engine_name(), "configured": want,
            "dml": bool(config.CFG.get("ocr_dml")),
            "rapidocr": _rapid() is not None,
            "powershell": bool(os.name == "nt")}
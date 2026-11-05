"""Drive the Perchance AI Furry Generator with the real keyboard and mouse.

Chrome runs with the DevTools protocol open so the finished image can be lifted
out of the DOM, but every click and keystroke is a real one and the page is read
with OCR. The composer is in a closed shadow root, so nothing here uses
selectors.
"""
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
import uuid

from ..core import config
from ..core.config import paths
from ..core.log import log
from ..platform import current
from . import input as itools, screen

try:
    from websockets.sync.client import connect as _ws_connect
except Exception:
    _ws_connect = None

URL = "https://perchance.org/ai-furry-generator"
PORT = 9222
TITLE_HINTS = ("perchance", "furry generator", "ai furry")

CHROME_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
)

_COUNT = r"""
(() => {
  let n = 0;
  const walk = r => {
    if (!r) return;
    try { n += r.querySelectorAll('img[src^="data:image"]').length; } catch (e) {}
    let all;
    try { all = r.querySelectorAll('*'); } catch (e) { return; }
    for (const e of all) {
      if (e.shadowRoot) walk(e.shadowRoot);
      if (e.tagName === 'IFRAME') { try { walk(e.contentDocument); } catch (err) {} }
    }
  };
  walk(document);
  return n;
})()
"""

_NEW_IMG = r"""
(async () => {
  const picks = [];
  const walk = r => {
    if (!r) return;
    try {
      for (const i of r.querySelectorAll('img')) {
        const s = i.currentSrc || i.src || '';
        if (s.startsWith('data:image') || s.startsWith('blob:')) picks.push(i);
      }
    } catch (e) {}
    let all;
    try { all = r.querySelectorAll('*'); } catch (e) { return; }
    for (const e of all) {
      if (e.shadowRoot) walk(e.shadowRoot);
      if (e.tagName === 'IFRAME') { try { walk(e.contentDocument); } catch (err) {} }
    }
  };
  walk(document);
  if (!picks.length) return null;
  const s = picks[picks.length - 1].currentSrc || picks[picks.length - 1].src;
  if (s.startsWith('data:')) return s;
  const b = await fetch(s).then(r => r.blob());
  return await new Promise(res => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.readAsDataURL(b);
  });
})()
"""


def _chrome():
    exe = (config.CFG.get("chrome_path") or "").strip()
    if exe and os.path.isfile(os.path.expandvars(exe)):
        return os.path.expandvars(exe)
    for p in CHROME_PATHS:
        p = os.path.expandvars(p)
        if os.path.isfile(p):
            return p
    for name in ("chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def _profile():
    d = os.path.join(paths().root, "chrome")
    os.makedirs(d, exist_ok=True)
    return d


def _http(path, method="GET"):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), method=method)
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def _probe():
    try:
        _http("/json/version")
        return True
    except Exception:
        return False


def _page_ws():
    tabs = _http("/json")
    for t in tabs:
        if t.get("type") == "page" and "perchance" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    for t in tabs:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    return _http("/json/new?%s" % URL, "PUT")["webSocketDebuggerUrl"]


class _Cdp:
    def __init__(self, url):
        self.ws = _ws_connect(url, max_size=None, open_timeout=15)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv(timeout=45))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message") or "cdp error")
                return msg.get("result") or {}

    def js(self, expr):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True,
                      awaitPromise=True)
        return (r.get("result") or {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _ensure_chrome(timeout=40):
    if _probe():
        return
    exe = _chrome()
    if not exe:
        raise RuntimeError("Chrome not found - set chrome_path in settings")
    args = [exe, "--remote-debugging-port=%d" % PORT,
            "--user-data-dir=" + _profile(), "--no-first-run",
            "--no-default-browser-check", "--start-maximized",
            "--force-renderer-accessibility",
            "--disable-blink-features=AutomationControlled", URL]
    if config.CFG.get("perchance_headless"):
        args.insert(1, "--headless=new")
    log("perchance: launching %s" % exe)
    subprocess.Popen(args, close_fds=True)
    end = time.time() + timeout
    while time.time() < end:
        if _probe():
            return
        time.sleep(0.5)
    raise RuntimeError("Chrome never opened the debug port")


def _focus():
    """Bring the generator window forward. Returns its hwnd."""
    try:
        wins = current().windows(80)
    except Exception as exc:
        raise RuntimeError("cannot list windows: %s" % exc)
    for w in wins:
        t = (w.get("title") or "").lower()
        if any(h in t for h in TITLE_HINTS):
            current().focus_window(w["hwnd"])
            time.sleep(0.6)
            return w["hwnd"]
    for w in wins:
        if "chrome" in (w.get("proc") or "").lower():
            current().focus_window(w["hwnd"])
            time.sleep(0.6)
            return w["hwnd"]
    raise RuntimeError("no Chrome window found")


def _settle(rounds=3):
    for _ in range(rounds):
        hit = None
        for label in ("I understand", "I am 18 or older", "I know the rules", "OK"):
            hit = screen.find(label, exact=True)
            if "error" not in hit:
                break
            hit = None
        if not hit:
            return
        itools.mouse_move(hit["cx"], hit["cy"])
        itools.click()
        time.sleep(0.4)


def _find_go(tries=3):
    """Find the Generate button, tolerating a clipped first letter."""
    for _ in range(tries):
        for needle in ("Generate", "enerate", "nerate", "Generat"):
            hit = screen.find(needle)
            if "error" not in hit:
                return hit
        time.sleep(1.0)
    return {"error": "cannot see the Generate button"}


def _candidates(go, label, typed):
    """Points to try for the prompt box, most likely first."""
    pts = []
    if typed:
        pts.append((typed["cx"], typed["cy"]))
    if label:
        pts.append((label["cx"] + 80, label["cy"] + 34))
        pts.append((label["cx"] + 80, label["cy"] + 20))
    if go:
        for dy in (90, 120, 150, 190, 230, 270, 310):
            pts.append((go["cx"] - 120, max(8, go["cy"] - dy)))
    return pts


def _aim_and_type(prompt, go):
    """Click into the composer and type. Returns (x, y, landed)."""
    mark = prompt[:18].lower()
    got = screen.look(limit=300)
    typed = None
    for r in got.get("rows") or []:
        if mark[:8] and mark[:8] in r["text"].lower():
            typed = r
            break
    label = screen.find("Prompt")
    label = None if "error" in label else label
    x = y = 0
    for x, y in _candidates(go, label, typed):
        itools.mouse_move(x, y)
        itools.click()
        time.sleep(0.2)
        itools.key("ctrl a")
        itools.type_text(prompt)
        time.sleep(0.5)
        if mark in (screen.look(limit=300).get("text") or "").lower():
            return x, y, True
    return x, y, False


def _write(data_url, folder, name):
    head, _, blob = data_url.partition(",")
    ext = ".png"
    if "jpeg" in head or "jpg" in head:
        ext = ".jpg"
    elif "webp" in head:
        ext = ".webp"
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, name + ext)
    with open(out, "wb") as fh:
        fh.write(base64.b64decode(blob))
    return out


def perchance_image(prompt="", mode="", style="", ratio="", timeout=0):
    """Generate an avatar on Perchance. Optionally install it on a mode."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"error": "prompt is required"}
    if len(prompt) > 1500:
        prompt = prompt[:1500]
    wait = float(timeout or config.CFG.get("perchance_timeout") or 180)
    c = None
    try:
        _ensure_chrome()
        hwnd = _focus()
        c = _Cdp(_page_ws())
        c.call("Page.enable")
        c.call("Runtime.enable")
        _settle()

        go = _find_go()
        if "error" in go:
            got = screen.look(limit=300)
            return {"error": go["error"], "hwnd": hwnd,
                    "on_screen": got.get("text")}

        x, y, landed = _aim_and_type(prompt, go)
        log("perchance: typed %d chars at %d,%d landed=%s"
            % (len(prompt), x, y, landed))

        go = _find_go()
        if "error" in go:
            return {"error": "lost the Generate button", "landed": landed}
        before = c.js(_COUNT) or 0
        itools.mouse_move(go["cx"], go["cy"])
        itools.click()
        log("perchance: clicked Generate at %d,%d" % (go["cx"], go["cy"]))

        end = time.time() + wait
        url = None
        while time.time() < end:
            time.sleep(1.5)
            if (c.js(_COUNT) or 0) > before:
                url = c.js(_NEW_IMG)
                if url:
                    break
        if not url:
            return {"error": "no image appeared within %ds" % int(wait),
                    "landed": landed}

        tag = uuid.uuid4().hex[:8]
        saved = _write(url, paths().output, "perchance_" + tag)
        out = {"ok": True, "path": saved, "prompt": prompt, "landed": landed,
               "bytes": os.path.getsize(saved)}
        mode = (mode or "").strip().lower()
        if mode:
            from ..core import personas
            if mode not in personas.PERSONAS:
                out["warning"] = "unknown mode %r, saved without installing" % mode
            else:
                dst = os.path.join(personas.dir_for(mode), "base.png")
                shutil.copyfile(saved, dst)
                out["installed"] = dst
                out["mode"] = mode
        return out
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        if c:
            c.close()


def perchance_debug():
    """What is on screen right now, as OCR sees it."""
    try:
        got = screen.look(limit=120)
        return {"url": (_http("/json") and "ok") if _probe() else "no debug port",
                "count": got.get("count"),
                "generate": screen.find("Generate"),
                "prompt_label": screen.find("Prompt"),
                "on_screen": got.get("text")}
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def perchance_status():
    """Is the debug port up, and is a perchance tab open?"""
    if not _probe():
        return {"running": False, "chrome": _chrome() or "(not found)"}
    tabs = [t.get("url") for t in _http("/json") if t.get("type") == "page"]
    return {"running": True, "chrome": _chrome(),
            "perchance_tab": any("perchance" in (u or "") for u in tabs),
            "tabs": len(tabs)}
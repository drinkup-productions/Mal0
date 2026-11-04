"""Drive the Perchance AI Furry Generator in a real Chrome window.

No Selenium and no driver download: Chrome is launched with the DevTools
protocol open and driven over it. Clicks are real mouse events and typing is
Input.insertText, so the page sees a person at the keyboard. A persistent
profile keeps the Cloudflare cookie and the dismissed overlays.
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

try:
    from websockets.sync.client import connect as _ws_connect
except Exception:
    _ws_connect = None

URL = "https://perchance.org/ai-furry-generator"
PORT = 9222

CHROME_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
)

DISMISS = ("i understand", "i am 18 or older", "i know the rules", "got it",
           "don't show this again", "dont show this again", "ok", "close", "accept")

# One pass over the page: find the prompt box and the Generate button, and
# collect anything covering them. Rects only, no clicking from here.
_LOCATE = r"""
(() => {
  const vis = e => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden'
           && s.display !== 'none' && r.top < innerHeight && r.bottom > 0;
  };
  const box = e => { const r = e.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  const label = e => {
    let t = (e.getAttribute('aria-label') || '') + ' ' + (e.placeholder || '');
    const l = e.closest('label');
    if (l) t += ' ' + l.innerText;
    let p = e.parentElement, n = 0;
    while (p && n++ < 4) { t += ' ' + (p.innerText || '').slice(0, 120); p = p.parentElement; }
    return t.toLowerCase();
  };

  let prompt = null;
  const areas = [...document.querySelectorAll('textarea, [contenteditable="true"]')]
    .filter(vis);
  if (areas.length) {
    const scored = areas.map(e => {
      const l = label(e);
      let s = 0;
      if (/prompt|describe|description/.test(l)) s += 10;
      if (e.id === 'description') s += 20;
      if (e.tagName === 'TEXTAREA') s += 3;
      const r = e.getBoundingClientRect();
      s += Math.min(5, r.width * r.height / 40000);
      return [s, e];
    }).sort((a, b) => b[0] - a[0]);
    prompt = box(scored[0][1]);
  }

  let go = null;
  const hits = [...document.querySelectorAll('button, [role="button"], div, a, span')]
    .filter(e => vis(e) && (e.innerText || '').trim().toLowerCase() === 'generate')
    .map(e => [e.getBoundingClientRect().width, e])
    .sort((a, b) => b[0] - a[0]);
  if (hits.length) go = box(hits[0][1]);

  const gates = [...document.querySelectorAll('button, [role="button"], a, div')]
    .filter(e => {
      if (!vis(e)) return false;
      const t = (e.innerText || '').trim().toLowerCase();
      if (t.length > 40) return false;
      return %s.some(w => t === w || t.startsWith(w));
    })
    .map(e => box(e)).slice(0, 6);

  return {prompt: prompt, go: go, gates: gates};
})()
"""

_COUNT = r"""
(() => [...document.querySelectorAll('img')]
  .filter(i => (i.currentSrc || i.src || '').startsWith('data:image')).length)()
"""

_NEW_IMG = r"""
(async () => {
  const ok = [...document.querySelectorAll('img')].filter(i => {
    const s = i.currentSrc || i.src || '';
    return s.startsWith('data:image') || s.startsWith('blob:');
  });
  if (!ok.length) return null;
  const i = ok[ok.length - 1];
  const s = i.currentSrc || i.src;
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

    def click(self, rect):
        x = rect["x"] + rect["w"] / 2.0
        y = rect["y"] + rect["h"] / 2.0
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                      button="left", clickCount=1)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _connect(timeout=40):
    if _ws_connect is None:
        raise RuntimeError("websockets is not installed")
    if not _probe():
        exe = _chrome()
        if not exe:
            raise RuntimeError("Chrome not found - set chrome_path in settings")
        args = [exe, "--remote-debugging-port=%d" % PORT,
                "--user-data-dir=" + _profile(), "--no-first-run",
                "--no-default-browser-check", "--start-maximized",
                "--disable-blink-features=AutomationControlled", URL]
        if config.CFG.get("perchance_headless"):
            args.insert(1, "--headless=new")
        log("perchance: launching %s" % exe)
        subprocess.Popen(args, close_fds=True)
        end = time.time() + timeout
        while time.time() < end:
            if _probe():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Chrome never opened the debug port")
    return _Cdp(_page_ws())


def _settle(c, rounds=3):
    """Close the age gate, privacy notice and rules dialogs."""
    for _ in range(rounds):
        found = c.js(_LOCATE % json.dumps(list(DISMISS))) or {}
        gates = found.get("gates") or []
        if not gates:
            return
        for g in gates[:3]:
            try:
                c.click(g)
            except Exception:
                pass
        time.sleep(0.4)


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
    """Generate an avatar on Perchance and save it. Optionally install it on a mode."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"error": "prompt is required"}
    if len(prompt) > 1500:
        prompt = prompt[:1500]
    wait = float(timeout or config.CFG.get("perchance_timeout") or 180)
    c = None
    try:
        c = _connect()
        c.call("Page.enable")
        c.call("Runtime.enable")
        try:
            c.call("Page.bringToFront")
        except Exception:
            pass

        if "perchance" not in (c.js("location.href") or ""):
            c.call("Page.navigate", url=URL)
            time.sleep(4)

        _settle(c)
        found = c.js(_LOCATE % json.dumps(list(DISMISS))) or {}
        target = found.get("prompt")
        if not target:
            return {"error": "could not find the prompt box on the page"}

        c.click(target)
        time.sleep(0.2)
        c.call("Input.insertText", text=prompt)
        time.sleep(0.3)

        found = c.js(_LOCATE % json.dumps(list(DISMISS))) or {}
        go = found.get("go")
        if not go:
            return {"error": "could not find the Generate button"}
        before = c.js(_COUNT) or 0
        c.click(go)
        log("perchance: submitted %d chars" % len(prompt))

        end = time.time() + wait
        url = None
        while time.time() < end:
            time.sleep(1.5)
            if (c.js(_COUNT) or 0) > before:
                url = c.js(_NEW_IMG)
                if url:
                    break
        if not url:
            return {"error": "no image appeared within %ds" % int(wait)}

        tag = uuid.uuid4().hex[:8]
        saved = _write(url, paths().output, "perchance_" + tag)
        out = {"ok": True, "path": saved, "prompt": prompt,
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


def perchance_status():
    """Is the debug port up, and is a perchance tab open?"""
    if not _probe():
        return {"running": False, "chrome": _chrome() or "(not found)"}
    tabs = [t.get("url") for t in _http("/json") if t.get("type") == "page"]
    return {"running": True, "chrome": _chrome(),
            "perchance_tab": any("perchance" in (u or "") for u in tabs),
            "tabs": len(tabs)}
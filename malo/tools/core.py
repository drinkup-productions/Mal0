"""The five core tools. Shell access goes through the platform adapter."""
import json
import os
import shutil
import time

from ..core import config, memory, personas, profiles


UNDO_MAX = 50


def _undo_dir():
    d = os.path.join(config.paths().root, "undo")
    os.makedirs(d, exist_ok=True)
    return d


def _undo_index():
    return os.path.join(_undo_dir(), "index.jsonl")


def _undo_rows():
    rows = []
    try:
        with open(_undo_index(), encoding="utf-8") as fh:
            for ln in fh:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return rows


def _snapshot(p):
    if not p or not os.path.isfile(p):
        return None
    d = _undo_dir()
    dest = os.path.join(d, "%d-%s" % (int(time.time() * 1000), os.path.basename(p)))
    shutil.copy2(p, dest)
    with open(_undo_index(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"path": p, "copy": dest, "at": time.time()}) + "\n")
    rows = _undo_rows()
    if len(rows) > UNDO_MAX:
        for r in rows[:-UNDO_MAX]:
            try:
                os.remove(r["copy"])
            except Exception:
                pass
        with open(_undo_index(), "w", encoding="utf-8") as fh:
            for r in rows[-UNDO_MAX:]:
                fh.write(json.dumps(r) + "\n")
    return dest


def undo_list(limit=20):
    rows = _undo_rows()[-int(limit or 20):][::-1]
    now = time.time()
    if not rows:
        return {"undo": "(nothing recorded)"}
    return {"undo": "\n".join("%d| %s (%dm ago)" % (i, r["path"], (now - r["at"]) // 60)
                              for i, r in enumerate(rows))}


def undo(index=0):
    rows = _undo_rows()[::-1]
    if not rows:
        return {"error": "nothing to undo"}
    try:
        r = rows[int(index or 0)]
    except IndexError:
        return {"error": "no entry at %s (have %d)" % (index, len(rows))}
    if not os.path.isfile(r["copy"]):
        return {"error": "snapshot gone: %s" % r["copy"]}
    os.makedirs(os.path.dirname(r["path"]), exist_ok=True)
    shutil.copy2(r["copy"], r["path"])
    return {"restored": r["path"], "from": r["copy"]}


def _roots():
    out = [config.get("workspace") or os.path.expanduser("~")]
    out += [r for r in (config.get("allow_roots") or []) if r]
    out += profiles.roots()
    out.append(config.paths().root)
    if config.get("repo"):
        out.append(config.get("repo"))
    return [os.path.normcase(os.path.realpath(
        os.path.expandvars(os.path.expanduser(r)))) for r in out]


def _inside(p):
    rp = os.path.normcase(os.path.realpath(p))
    for r in _roots():
        if rp == r or rp.startswith(r + os.sep):
            return True
    return False


def _resolve(p, jail=True):
    if not p:
        return None
    p = os.path.expandvars(os.path.expanduser(str(p)))
    if not os.path.isabs(p):
        p = os.path.join(config.get("workspace") or os.path.expanduser("~"), p)
    p = os.path.abspath(p)
    if jail and not _inside(p):
        raise ValueError("outside the workspace: %s" % p)
    return p


def clip(s, n=4500):
    s = s if isinstance(s, str) else str(s)
    return s if len(s) <= n else s[:n] + "\n... [%d more]" % (len(s) - n)


def _open_text(p):
    with open(p, "rb") as fh:
        head = fh.read(4)
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        enc = "utf-16"
    elif head.startswith(b"\xef\xbb\xbf"):
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    return open(p, encoding=enc, errors="replace")

READ_BUDGET = 14000
BASH_BUDGET = 12000


def read(path, offset=1, limit=400):
    p = _resolve(path)
    if not p or not os.path.exists(p):
        parent = os.path.dirname(p or "")
        near = []
        if parent and os.path.isdir(parent):
            near = sorted(os.listdir(parent))[:40]
        return {"error": "no such path: %s" % p,
                "parent": parent or "(none)",
                "parent_entries": "\n".join(near) or "(empty)",
                "note": "it does not exist yet - write() creates parent folders"}
    if os.path.isdir(p):
        rows = [n + ("/" if os.path.isdir(os.path.join(p, n)) else "")
                for n in sorted(os.listdir(p))[:400]]
        return {"path": p, "kind": "dir", "entries": "\n".join(rows) or "(empty)"}
    with _open_text(p) as fh:
        lines = fh.read().splitlines()
    total = len(lines)
    off = max(1, int(offset or 1))
    lim = max(1, min(2000, int(limit or 400)))
    out, used, last = [], 0, off - 1
    for i, line in enumerate(lines[off - 1:off - 1 + lim]):
        row = "%5d| %s\n" % (off + i, line)
        if used + len(row) > READ_BUDGET:
            break
        out.append(row)
        used += len(row)
        last = off + i
    body = "".join(out).rstrip("\n")
    tail = ""
    if last < total:
        tail = "\n... [%d more lines - continue with offset=%d]" % (total - last, last + 1)
    return {"path": p, "lines": total, "from": off, "to": last,
            "content": body + tail}


def tail(path, n=40):
    p = _resolve(path)
    if not p or not os.path.isfile(p):
        return {"error": "no such file: %s" % p}
    with _open_text(p) as fh:
        lines = fh.read().splitlines()
    total = len(lines)
    n = max(1, min(2000, int(n or 40)))
    start = max(0, total - n)
    body = "\n".join("%5d| %s" % (start + i + 1, l) for i, l in enumerate(lines[start:]))
    return {"path": p, "lines": total, "from": start + 1, "content": clip(body)}


def write(path, content):
    p = _resolve(path)
    if not p:
        return {"error": "no path"}
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
        _snapshot(p)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(content or "")
    return {"path": p, "bytes": len(content or "")}


def edit(path, old, new):
    p = _resolve(path)
    if not p or not os.path.isfile(p):
        return {"error": "no such file: %s" % p}
    if old == "" or old == new:
        return {"error": "old is empty or identical to new"}
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        src = fh.read()
    hits = src.count(old)
    _snapshot(p)
    if hits == 1:
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(src.replace(old, new, 1))
        return {"path": p, "match": "exact"}
    if hits > 1:
        return {"error": "'old' matches %d times - add context" % hits}
    nl = "\r\n" if "\r\n" in src else "\n"
    lines, old_l = src.split(nl), [l.rstrip() for l in old.split(nl)]
    while old_l and old_l[-1] == "":
        old_l.pop()
    norm = [l.rstrip() for l in lines]
    spots = [i for i in range(len(norm) - len(old_l) + 1)
             if norm[i:i + len(old_l)] == old_l]
    if not spots:
        return {"error": "old text not found"}
    if len(spots) > 1:
        return {"error": "ambiguous - matches %d places" % len(spots)}
    i = spots[0]
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(nl.join(lines[:i] + new.split(nl) + lines[i + len(old_l):]))
    return {"path": p, "match": "fuzzy", "line": i + 1}


def bash(command, cwd=None, timeout=180):
    from .. import platform as plat
    wd = _resolve(cwd) or config.get("workspace")
    try:
        code, out, err = plat.current().run_shell(command, cwd=wd, timeout=int(timeout))
    except Exception as exc:
        return {"error": str(exc), "cwd": wd}
    res = {"exit_code": code, "cwd": wd}
    if out.strip():
        res["stdout"] = clip(out.strip())
    if err.strip():
        res["stderr"] = clip(err.strip())
    return res


def remember(text, kind="user", importance=0.5):
    text = (text or "").strip()
    if not text:
        return {"error": "nothing to remember"}
    mid = memory.add(text, kind, importance, source="tool")
    return {"saved": text, "id": mid}


def forget(mid=None, text=None):
    n = memory.forget(mid, text)
    return {"removed": n} if n else {"error": "nothing matched"}


def journal(text, keep=12):
    from ..core import presence
    t = (text or "").strip()
    if not t:
        return {"error": "nothing to note"}
    presence.journal_add(t, int(keep or 12))
    return {"noted": t}
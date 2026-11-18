"""Versioned backups. Every mutation is preceded by one.

Nothing here raises into the caller. A failed backup is logged and the
mutation proceeds, because a missing backup beats a refused write.
"""
import hashlib
import json
import os
import shutil
import time
import zipfile
import zlib

from . import config
from .log import log

PER_PATH = 20
TOTAL_BYTES = 250 * 1024 * 1024
ARCHIVE_MAX_FILE = 8 * 1024 * 1024
ARCHIVE_MAX_TOTAL = 60 * 1024 * 1024
ARCHIVE_KEEP = 10
INDEX_KEEP = 4000

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "build",
             "dist", ".buildozer", "backups", "undo", ".pytest_cache",
             ".mypy_cache", ".ruff_cache", ".idea"}
SKIP_EXT = {".pyc", ".pyo", ".zip", ".7z", ".iso", ".exe", ".dll", ".so", ".pyd",
            ".whl", ".msi", ".apk", ".mp4", ".mov", ".m4a", ".wav"}


def _store():
    d = os.path.join(config.paths().root, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _index():
    return os.path.join(_store(), "index.jsonl")


def _rows():
    rows = []
    try:
        with open(_index(), encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return rows


def _write_rows(rows):
    p = _index()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    os.replace(tmp, p)


def _key(path):
    real = os.path.normcase(os.path.realpath(path))
    return hashlib.sha1(real.encode("utf-8", "replace")).hexdigest()[:20]


def _sha(p):
    h = hashlib.sha1()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(name):
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:60]


def _total_bytes(rows):
    return sum(int(r.get("size") or 0) for r in rows)


def _prune(rows):
    """Drop oldest copies past the per-path and total caps."""
    keep, dropped = [], []
    per = {}
    for r in reversed(rows):
        p = r.get("path")
        per[p] = per.get(p, 0) + 1
        if per[p] > PER_PATH:
            dropped.append(r)
        else:
            keep.append(r)
    keep.reverse()
    while _total_bytes(keep) > TOTAL_BYTES and keep:
        dropped.append(keep.pop(0))
    while len(keep) > INDEX_KEEP:
        dropped.append(keep.pop(0))
    for r in dropped:
        try:
            os.remove(r["copy"])
        except Exception:
            pass
    return keep


def snapshot(path, reason="edit"):
    """Copy path aside before it changes. Returns the row, or None."""
    try:
        if not path or not os.path.isfile(path):
            return None
        rows = _rows()
        mine = [r for r in rows if r.get("path") == path]
        if mine and mine[-1].get("sha") == _sha(path):
            return mine[-1]
        d = os.path.join(_store(), _key(path))
        os.makedirs(d, exist_ok=True)
        dest = os.path.join(d, "%d-%s" % (int(time.time() * 1000),
                                          _safe(os.path.basename(path))))
        shutil.copy2(path, dest)
        row = {"id": os.path.basename(dest), "path": path, "copy": dest,
               "at": time.time(), "reason": reason,
               "size": os.path.getsize(dest), "sha": _sha(dest)}
        rows.append(row)
        _write_rows(_prune(rows))
        return row
    except Exception as exc:
        log("backup failed for %s: %s" % (path, exc))
        return None


def restore(row_id, target=None):
    for r in reversed(_rows()):
        if r.get("id") == row_id:
            dest = target or r["path"]
            if not os.path.isfile(r["copy"]):
                return {"error": "copy gone: %s" % r["copy"]}
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            shutil.copy2(r["copy"], dest)
            return {"restored": dest, "from": r["copy"],
                    "reason": r.get("reason"), "age_secs": int(time.time() - r["at"])}
    return {"error": "no backup %s" % row_id}


def listing(pattern="", limit=30):
    rows = _rows()
    if pattern:
        rows = [r for r in rows if pattern.lower() in r.get("path", "").lower()]
    rows = rows[-int(limit or 30):][::-1]
    if not rows:
        return {"backups": "(none)"}
    now = time.time()
    return {"backups": "\n".join(
        "%s| %s (%s, %dm ago, %dB)" % (r["id"], r["path"], r.get("reason", "?"),
                                       (now - r["at"]) // 60, r.get("size") or 0)
        for r in rows)}


def stats():
    rows = _rows()
    return {"count": len(rows), "bytes": _total_bytes(rows),
            "cap_bytes": TOTAL_BYTES, "per_path_cap": PER_PATH,
            "dir": _store()}


# ---- workspace archives, for shell mutations -------------------------

def _archives():
    d = os.path.join(_store(), "trees")
    os.makedirs(d, exist_ok=True)
    return d


def pre_bash(root, reason="bash"):
    """Archive the workspace before a shell command runs."""
    try:
        if not root or not os.path.isdir(root):
            return None
        name = "%d-%s.zip" % (int(time.time() * 1000), _safe(reason))
        dest = os.path.join(_archives(), name)
        added = total = 0
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for base, dirs, files in os.walk(root):
                dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
                for f in files:
                    if os.path.splitext(f)[1].lower() in SKIP_EXT:
                        continue
                    p = os.path.join(base, f)
                    try:
                        size = os.path.getsize(p)
                    except OSError:
                        continue
                    if size > ARCHIVE_MAX_FILE or total + size > ARCHIVE_MAX_TOTAL:
                        continue
                    try:
                        z.write(p, os.path.relpath(p, root))
                    except Exception:
                        continue
                    added += 1
                    total += size
        keep = sorted(os.listdir(_archives()))[-ARCHIVE_KEEP:]
        for old in os.listdir(_archives()):
            if old not in keep:
                try:
                    os.remove(os.path.join(_archives(), old))
                except Exception:
                    pass
        return {"archive": name, "files": added, "bytes": total}
    except Exception as exc:
        log("pre_bash failed: %s" % exc)
        return None


def changed_in(archive, root):
    """Which members of archive differ from disk now."""
    p = os.path.join(_archives(), archive)
    if not os.path.isfile(p):
        return {"error": "no archive %s" % archive}
    changed, added = [], []
    try:
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                target = os.path.join(root, info.filename)
                if not os.path.isfile(target):
                    added.append(info.filename)
                    continue
                with open(target, "rb") as fh:
                    if zlib.crc32(fh.read()) & 0xFFFFFFFF != info.CRC:
                        changed.append(info.filename)
    except Exception as exc:
        return {"error": str(exc)}
    return {"changed": changed, "added": added,
            "note": "restore one with bash_restore(archive, path)"}


def restore_member(archive, path, root=None):
    p = os.path.join(_archives(), archive)
    if not os.path.isfile(p):
        return {"error": "no archive %s" % archive}
    root = root or config.get("workspace")
    rel = str(path).replace("\\", "/").lstrip("/")
    try:
        with zipfile.ZipFile(p) as z:
            data = z.read(rel)
    except KeyError:
        return {"error": "%s not in %s" % (rel, archive)}
    except Exception as exc:
        return {"error": str(exc)}
    dest = os.path.join(root, rel)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    snapshot(dest, "pre-restore")
    with open(dest, "wb") as fh:
        fh.write(data)
    return {"restored": dest, "from": archive, "bytes": len(data)}


def archives(limit=10):
    d = _archives()
    names = sorted(os.listdir(d))[-int(limit or 10):][::-1]
    if not names:
        return {"archives": "(none)"}
    now = time.time()
    return {"archives": "\n".join(
        "%s (%dm ago, %dB)" % (n, (now - os.path.getmtime(os.path.join(d, n))) // 60,
                               os.path.getsize(os.path.join(d, n)))
        for n in names)}
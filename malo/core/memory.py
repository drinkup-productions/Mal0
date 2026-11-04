"""Long-term memory: SQLite + FTS5, hybrid ranking, decay, consolidation."""
import json
import math
import os
import re
import sqlite3
import threading
import time

from . import config, log as _log

KINDS = ("user", "machine", "procedure")
TAG = {"user": "u", "machine": "m", "procedure": "p"}
_LOCK = threading.RLock()
_CONN = None
_MAINT = {"thread": None}

SCHEMA_VERSION = 1

MIGRATIONS = {
    # 2: "ALTER TABLE mem ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS mem (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'user',
    text TEXT NOT NULL,
    norm TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    hits INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    seen REAL NOT NULL,
    source TEXT DEFAULT '',
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts
    USING fts5(text, norm, content='mem', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON mem BEGIN
    INSERT INTO mem_fts(rowid, text, norm) VALUES (new.id, new.text, new.norm);
END;
CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON mem BEGIN
    INSERT INTO mem_fts(mem_fts, rowid, text, norm) VALUES ('delete', old.id, old.text, old.norm);
END;
CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON mem BEGIN
    INSERT INTO mem_fts(mem_fts, rowid, text, norm) VALUES ('delete', old.id, old.text, old.norm);
    INSERT INTO mem_fts(rowid, text, norm) VALUES (new.id, new.text, new.norm);
END;
"""

_W = {"bm25": 0.55, "recency": 0.20, "importance": 0.15, "reinforce": 0.10}
_HALF_LIFE = 21.0  # days

def _migrate_schema(c):
    have = c.execute("PRAGMA user_version").fetchone()[0]
    if have == 0:
        c.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        c.commit()
        return
    for version in sorted(MIGRATIONS):
        if version <= have:
            continue
        c.executescript(MIGRATIONS[version])
        c.execute("PRAGMA user_version = %d" % version)
        c.commit()
        _log.log("memory migrated to v%d" % version)


def conn():
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(os.path.join(config.paths().root, "memory.sqlite"),
                                check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.executescript(SCHEMA)
        _migrate_schema(_CONN)
        _CONN.commit()
        _migrate_notes(_CONN)
        if _MAINT["thread"] is None:
            t = threading.Thread(target=_maintenance, daemon=True, name="memory-maint")
            t.start()
            _MAINT["thread"] = t
    return _CONN

def _maintenance(interval=6 * 3600):
    time.sleep(180)
    while True:
        try:
            n = consolidate()
            if n:
                _log.log("memory consolidated %d duplicate groups" % n)
        except Exception as exc:
            _log.log("memory maintenance: %s" % exc)
        time.sleep(interval)


def close():
    global _CONN
    if _CONN is not None:
        _CONN.close()
        _CONN = None


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]+", " ", (text or "").lower()).split())


def _terms(query):
    return re.findall(r"\w{2,}", (query or "").lower())[:24]


def _age(secs):
    if secs < 3600:
        return "%dm" % max(1, int(secs // 60))
    if secs < 86400:
        return "%dh" % int(secs // 3600)
    return "%dd" % int(secs // 86400)


def _migrate_notes(c):
    """Import the old notes.md once, if the store is empty."""
    if c.execute("SELECT COUNT(*) FROM mem").fetchone()[0]:
        return
    from . import personas
    p = os.path.join(personas.dir_for(personas.active(config.CFG), False), "notes.md")
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except Exception:
        return
    n = 0
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("- "):
            add(ln[2:], "user", 0.6, source="migrated")
            n += 1
    if n:
        _log.log("migrated %d notes into memory" % n)


def add(text, kind="user", importance=0.5, source=""):
    text = " ".join((text or "").split())[:600]
    if not text:
        return None
    kind = kind if kind in KINDS else "user"
    n = _norm(text)
    now = time.time()
    with _LOCK:
        c = conn()
        row = c.execute("SELECT id, importance FROM mem WHERE norm=? AND archived=0",
                        (n,)).fetchone()
        if row:
            c.execute("UPDATE mem SET hits=hits+1, seen=?, importance=MIN(1.0, MAX(importance, ?) + 0.05) "
                      "WHERE id=?", (now, float(importance), row["id"]))
            c.commit()
            return row["id"]
        cur = c.execute("INSERT INTO mem(kind, text, norm, importance, created, seen, source) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (kind, text, n, float(importance), now, now, source))
        c.commit()
        return cur.lastrowid


def recall(query, limit=8, min_score=0.0, budget=None):
    """Hybrid recall: FTS relevance + recency + importance + reinforcement.

    Pinned rows are always candidates and always sort above unpinned ones.
    `budget` caps the total characters returned, but never returns nothing.
    """
    limit = max(1, int(limit))
    now = time.time()
    terms = _terms(query)
    rows = {}

    with _LOCK:
        c = conn()

        if terms:
            match = " OR ".join('"%s"*' % t for t in terms)
            try:
                for r in c.execute(
                    "SELECT m.*, bm25(mem_fts) AS _rank "
                    "FROM mem_fts JOIN mem AS m ON m.id = mem_fts.rowid "
                    "WHERE mem_fts MATCH ? AND m.archived = 0 "
                    "ORDER BY _rank LIMIT ?", (match, limit * 6)).fetchall():
                    d = dict(r)
                    rows[d["id"]] = d
            except sqlite3.OperationalError as exc:
                _log.log("memory recall fts: %s" % exc)

        for r in c.execute(
            "SELECT m.*, 0.0 AS _rank FROM mem AS m "
            "WHERE m.archived = 0 AND m.pinned = 1 "
            "ORDER BY m.importance DESC, m.seen DESC LIMIT ?", (limit,)).fetchall():
            d = dict(r)
            rows.setdefault(d["id"], d)

        if len(rows) < limit:
            for r in c.execute(
                "SELECT m.*, 0.0 AS _rank FROM mem AS m "
                "WHERE m.archived = 0 "
                "ORDER BY m.seen DESC LIMIT ?", (limit * 4,)).fetchall():
                d = dict(r)
                rows.setdefault(d["id"], d)

        scored = []
        for d in rows.values():
            age_days = max(0.0, now - float(d["created"] or now)) / 86400.0
            recency = 0.5 ** (age_days / _HALF_LIFE) if _HALF_LIFE > 0 else 1.0
            relevance = 1.0 / (1.0 + abs(float(d["_rank"]))) if terms else 0.0
            importance = min(1.0, max(0.0, float(d["importance"] or 0.0)))
            reinforce = min(1.0, math.log1p(float(d["hits"] or 0)) / 3.0)
            score = (_W["bm25"] * relevance + _W["recency"] * recency
                     + _W["importance"] * importance + _W["reinforce"] * reinforce)
            if d["pinned"]:
                score += 1.0
            if score >= min_score:
                scored.append((score, d))

        scored.sort(key=lambda p: p[0], reverse=True)

        out = []
        used = 0
        for score, d in scored:
            if len(out) >= limit:
                break
            n = len(d["text"])
            if budget is not None and out and used + n > budget:
                break
            used += n
            d.pop("_rank", None)
            d["score"] = round(score, 4)
            out.append(d)

        if out:
            c.executemany("UPDATE mem SET hits = hits + 1, seen = ? WHERE id = ?",
                          [(now, d["id"]) for d in out])
            c.commit()
        return out


def format_rows(rows):
    if not rows:
        return ""
    now = time.time()
    return "\n".join("[%s:%d]%s %s (%s)" % (TAG.get(r["kind"], "u"), r["id"],
                                            "*" if r["pinned"] else "",
                                            r["text"], _age(now - r["seen"]))
                     for r in rows)


def forget(mid=None, text=None):
    with _LOCK:
        c = conn()
        if mid:
            n = c.execute("DELETE FROM mem WHERE id=?", (int(mid),)).rowcount
        elif text:
            n = c.execute("DELETE FROM mem WHERE norm LIKE ?",
                          ("%" + _norm(text)[:80] + "%",)).rowcount
        else:
            return 0
        c.commit()
        return n


def set_pinned(mid, on=True):
    with _LOCK:
        c = conn()
        c.execute("UPDATE mem SET pinned=? WHERE id=?", (1 if on else 0, int(mid)))
        c.commit()


def archive(mid):
    with _LOCK:
        c = conn()
        c.execute("UPDATE mem SET archived=1 WHERE id=?", (int(mid),))
        c.commit()


def listing(q="", limit=200):
    with _LOCK:
        c = conn()
        if q:
            match = " OR ".join('"%s"' % t for t in _terms(q))
            if match:
                return [dict(r) for r in c.execute(
                    "SELECT m.* FROM mem_fts JOIN mem m ON m.id=mem_fts.rowid "
                    "WHERE mem_fts MATCH ? ORDER BY bm25(mem_fts) LIMIT ?",
                    (match, limit)).fetchall()]
        return [dict(r) for r in c.execute(
            "SELECT * FROM mem WHERE archived=0 "
            "ORDER BY pinned DESC, importance DESC, seen DESC LIMIT ?", (limit,)).fetchall()]


def stats():
    with _LOCK:
        c = conn()
        return {"total": c.execute("SELECT COUNT(*) FROM mem WHERE archived=0").fetchone()[0],
                "pinned": c.execute("SELECT COUNT(*) FROM mem WHERE pinned=1").fetchone()[0],
                "archived": c.execute("SELECT COUNT(*) FROM mem WHERE archived=1").fetchone()[0]}


def consolidate():
    """Merge duplicates, promote repeats, decay and archive the dregs."""
    now = time.time()
    with _LOCK:
        c = conn()
        merged = 0
        for d in c.execute("SELECT norm, GROUP_CONCAT(id) AS ids, COUNT(*) AS n FROM mem "
                           "WHERE archived=0 GROUP BY norm HAVING n > 1").fetchall():
            ids = [int(x) for x in d["ids"].split(",")]
            keep = c.execute("SELECT id FROM mem WHERE id IN (%s) "
                             "ORDER BY importance DESC, hits DESC LIMIT 1"
                             % ",".join("?" * len(ids)), ids).fetchone()["id"]
            rest = [i for i in ids if i != keep]
            if not rest:
                continue
            marks = ",".join("?" * len(rest))
            c.execute("UPDATE mem SET hits = hits + (SELECT SUM(hits) FROM mem WHERE id IN (%s)) "
                      "WHERE id=?" % marks, rest + [keep])
            c.execute("DELETE FROM mem WHERE id IN (%s)" % marks, rest)
            merged += 1
        c.execute("UPDATE mem SET importance = importance * 0.97 "
                  "WHERE archived=0 AND pinned=0 AND seen < ?", (now - 14 * 86400,))
        c.execute("UPDATE mem SET importance = MIN(1.0, importance + 0.1) WHERE hits >= 3")
        c.execute("UPDATE mem SET archived=1 WHERE archived=0 AND pinned=0 AND importance < 0.15")
        c.commit()
    return merged


EXTRACT_PROMPT = (
    "You maintain a long-term memory store. Read the exchange and return ONLY a JSON array of "
    "0-3 objects, each {\"kind\":\"user|machine|procedure\",\"text\":\"...\",\"importance\":0.0-1.0}. "
    "user = durable fact about the person. machine = fact about this computer or project. "
    "procedure = a lesson about how to do something here. Skip anything obvious or transient. "
    "Return [] if nothing is worth keeping."
)


def extract(cfg, user_text, reply_text, prov, model):
    if not cfg.get("memory", True) or not cfg.get("memory_extract", True):
        return 0
    if not user_text or len(reply_text or "") < 20:
        return 0
    from . import provider as _prov
    _prov.set_model(model)
    try:
        raw = prov.complete([
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": "USER: %s\n\nREPLY: %s"
                                        % (user_text[:1200], reply_text[:1200])},
        ], max_tokens=400)
    except Exception as exc:
        _log.log("memory extract: %s" % exc)
        return 0
    i, j = raw.find("["), raw.rfind("]")
    if i < 0 or j < i:
        return 0
    try:
        items = json.loads(raw[i:j + 1])
    except Exception:
        return 0
    n = 0
    for it in items[:3]:
        if isinstance(it, dict) and it.get("text"):
            if add(it["text"], it.get("kind", "user"),
                   float(it.get("importance") or 0.5), source="auto"):
                n += 1
    return n
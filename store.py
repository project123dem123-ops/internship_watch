"""SQLite, one file in the data directory: what was found, every check the
worker ran, and every notification it sent.

A connection per call: the API and the worker run on different threads and
sqlite3 connections are not safe to share. WAL lets the page read while the
worker writes.
"""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config
import sources

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    level       TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- post | update | news | job
    title       TEXT NOT NULL,
    url         TEXT,
    found_on    TEXT,                   -- the page it was listed on
    detail      TEXT,
    deadline    TEXT,                   -- the last date, as the site wrote it
    closes      TEXT,                   -- that date as YYYY-MM-DD; past it the item is closed
    posted      TEXT,
    published   TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    baseline    INTEGER DEFAULT 0       -- already there when the watch first read the source
);
CREATE INDEX IF NOT EXISTS items_by_time ON items(first_seen DESC);

CREATE TABLE IF NOT EXISTS sources (
    source_id   TEXT PRIMARY KEY,
    last_check  TEXT,
    last_ok     TEXT,
    status      TEXT,
    found       INTEGER DEFAULT 0,
    pages       TEXT,                   -- JSON: each address fetched and its HTTP status
    page_lines  TEXT                    -- a watched page's text, one line per entry
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started       TEXT NOT NULL,
    finished      TEXT,
    trigger       TEXT,                 -- schedule | manual
    sources_ok    INTEGER DEFAULT 0,
    sources_failed INTEGER DEFAULT 0,
    found         INTEGER DEFAULT 0,
    new_items     INTEGER DEFAULT 0,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created     TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    item_ids    TEXT,                   -- JSON list
    is_test     INTEGER DEFAULT 0,
    read        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id INTEGER,
    channel         TEXT NOT NULL,
    ok              INTEGER NOT NULL,
    detail          TEXT,
    created         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_lock = threading.Lock()
_ready_for = None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def item_id(*parts):
    return hashlib.sha1("|".join(p or "" for p in parts).encode("utf-8")).hexdigest()[:20]


def closes_of(deadline):
    """A last date as the site wrote it ("28-Nov-2026", "29 Nov 2026") -> "2026-11-28", or None."""
    found = sources.parse_date(deadline) if deadline else None
    return found.isoformat() if found else None


def _migrate(conn):
    """A database made before items had `closes`: add it, filled from `deadline`."""
    if "closes" not in {r[1] for r in conn.execute("PRAGMA table_info(items)")}:
        conn.execute("ALTER TABLE items ADD COLUMN closes TEXT")
        for iid, deadline in conn.execute("SELECT id, deadline FROM items WHERE deadline <> ''").fetchall():
            conn.execute("UPDATE items SET closes = ? WHERE id = ?", (closes_of(deadline), iid))


@contextmanager
def db():
    """A connection that is committed and closed."""
    global _ready_for
    path = config.DB_PATH
    with _lock:
        if _ready_for != path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            boot = sqlite3.connect(path, timeout=30)
            try:
                boot.execute("PRAGMA journal_mode=WAL")
                boot.executescript(SCHEMA)
                _migrate(boot)
                boot.commit()
            finally:
                boot.close()
            _ready_for = path
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recording one source's check
# ---------------------------------------------------------------------------

def record(source, result, enrich=None):
    """Store one source's check. Returns the items that are new.

    The first successful check of a source records what is already there as
    the baseline, without calling it new -- otherwise switching the watch on
    would announce forty old posts. `enrich(item)` reads a new post's own page
    for its dates before it is stored."""
    t = now()
    with db() as conn:
        state = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source["id"],)).fetchone()
        pages = json.dumps(result.get("pages") or [])
        if result.get("error"):
            conn.execute("INSERT INTO sources (source_id, last_check, status, pages) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(source_id) DO UPDATE SET last_check = excluded.last_check, "
                         "status = excluded.status, pages = excluded.pages",
                         (source["id"], t, "error: " + result["error"], pages))
            return []
        first_check = state is None or state["last_ok"] is None
        items = list(result.get("items") or [])
        lines = result.get("lines")

        if source["kind"] == "page" and lines is not None:
            previous = json.loads(state["page_lines"]) if state and state["page_lines"] else None
            added = sources.page_changes(previous, lines) if previous is not None else []
            if added:
                items.append({"kind": "update", "title": f"{source['name']}: the page changed",
                              "url": source["home"], "found_on": source["home"],
                              "detail": " / ".join(added[:4])[:700], "deadline": "",
                              "_key": "\n".join(sorted(added))})

    # Outside the transaction: reading a post's page takes seconds.
    fresh_candidates = []
    with db() as conn:
        for item in items:
            key = item.get("_key") or item.get("url") or item["title"]
            iid = item_id(source["id"] if item["kind"] == "update" else "", key)
            if conn.execute("SELECT 1 FROM items WHERE id = ?", (iid,)).fetchone():
                # Seen again: a corrected link (a news story first stored with a
                # redirect) or a new last date (an extension) replaces the old one.
                deadline = item.get("deadline") or ""
                conn.execute("UPDATE items SET last_seen = ?, url = COALESCE(?, url), "
                             "deadline = CASE WHEN ? <> '' THEN ? ELSE deadline END, "
                             "closes = COALESCE(?, closes) WHERE id = ?",
                             (t, item.get("url"), deadline, deadline, closes_of(deadline), iid))
            else:
                fresh_candidates.append((iid, item))
    if enrich and not first_check:
        for _, item in fresh_candidates[:20]:
            enrich(item)

    fresh = []
    with db() as conn:
        for iid, item in fresh_candidates:
            level = item.get("level") or source["level"]
            conn.execute(
                "INSERT OR IGNORE INTO items (id, source_id, level, kind, title, url, found_on, detail, deadline, "
                "closes, posted, published, first_seen, last_seen, baseline) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iid, source["id"], level, item["kind"], item["title"], item.get("url"), item.get("found_on"),
                 item.get("detail"), item.get("deadline"), closes_of(item.get("deadline")), item.get("posted"),
                 item.get("published"), t, t, 1 if first_check else 0))
            if not first_check:
                fresh.append(dict(item, id=iid, level=level, source=source["name"], source_id=source["id"]))
        conn.execute(
            "INSERT INTO sources (source_id, last_check, last_ok, status, found, pages, page_lines) "
            "VALUES (?, ?, ?, 'ok', ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
            "last_check = excluded.last_check, last_ok = excluded.last_ok, status = 'ok', found = excluded.found, "
            "pages = excluded.pages, page_lines = COALESCE(excluded.page_lines, sources.page_lines)",
            (source["id"], t, t, len(result.get("items") or []), pages,
             json.dumps(lines) if lines is not None else None))
    return fresh


# ---------------------------------------------------------------------------
# Runs, notifications, settings
# ---------------------------------------------------------------------------

def start_run(trigger):
    with db() as conn:
        return conn.execute("INSERT INTO runs (started, trigger) VALUES (?, ?)", (now(), trigger)).lastrowid


def finish_run(run_id, sources_ok, sources_failed, found, new_items, error=None):
    with db() as conn:
        conn.execute("UPDATE runs SET finished = ?, sources_ok = ?, sources_failed = ?, found = ?, new_items = ?, "
                     "error = ? WHERE id = ?", (now(), sources_ok, sources_failed, found, new_items, error, run_id))


def runs(limit=20):
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]


def add_notification(title, body, item_ids, is_test=False):
    with db() as conn:
        return conn.execute("INSERT INTO notifications (created, title, body, item_ids, is_test) VALUES (?, ?, ?, ?, ?)",
                            (now(), title, body, json.dumps(item_ids), 1 if is_test else 0)).lastrowid


def add_delivery(notification_id, channel, ok, detail):
    with db() as conn:
        conn.execute("INSERT INTO deliveries (notification_id, channel, ok, detail, created) VALUES (?, ?, ?, ?, ?)",
                     (notification_id, channel, 1 if ok else 0, (detail or "")[:500], now()))


def notifications(limit=50):
    with db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))]
        for row in rows:
            row["item_ids"] = json.loads(row["item_ids"] or "[]")
            row["read"] = bool(row["read"])
            row["is_test"] = bool(row["is_test"])
            row["deliveries"] = [dict(d) for d in conn.execute(
                "SELECT channel, ok, detail, created FROM deliveries WHERE notification_id = ? ORDER BY id", (row["id"],))]
        unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()[0]
    return rows, unread


def mark_read(ids=None):
    with db() as conn:
        if ids:
            conn.executemany("UPDATE notifications SET read = 1 WHERE id = ?", [(i,) for i in ids])
        else:
            conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")


def get_setting(key, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    with db() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, json.dumps(value)))


# Still open: no last date known, or one not passed yet. A news story counts
# only with a last date: a report with no date to apply by is not an opening.
OPEN = "(closes IS NULL OR closes >= :today) AND (kind <> 'news' OR closes IS NOT NULL)"


def items(limit=2000):
    """The items still open to apply for."""
    with db() as conn:
        return [dict(r, baseline=bool(r["baseline"])) for r in conn.execute(
            # Newest first; among items found in the same check, official
            # postings before programme-page changes, news reports, then jobs.
            f"SELECT * FROM items WHERE {OPEN} ORDER BY first_seen DESC, "
            "CASE kind WHEN 'post' THEN 0 WHEN 'update' THEN 1 WHEN 'news' THEN 2 ELSE 3 END, "
            "COALESCE(closes, '9999') ASC, rowid DESC LIMIT :limit",
            {"today": sources.today().isoformat(), "limit": limit})]


def closed_count():
    """Items kept but no longer shown: their last date has passed (or a news story gave none)."""
    with db() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM items WHERE NOT ({OPEN})",
                            {"today": sources.today().isoformat()}).fetchone()[0]


def source_states():
    with db() as conn:
        out = {}
        for r in conn.execute("SELECT source_id, last_check, last_ok, status, found, pages FROM sources"):
            row = dict(r)
            row["pages"] = json.loads(row["pages"] or "[]")
            out[row["source_id"]] = row
        return out

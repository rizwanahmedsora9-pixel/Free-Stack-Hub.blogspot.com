"""SQLite storage. One writer lock, WAL mode, every Google response kept verbatim."""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, DEFAULT_SETTINGS, INSTANCE_DIR

_lock = threading.RLock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS properties (
    site_url         TEXT PRIMARY KEY,
    permission_level TEXT,
    fetched_at       TEXT
);

CREATE TABLE IF NOT EXISTS urls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT UNIQUE NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'post',   -- post | page | home | other
    title         TEXT,
    labels        TEXT,                            -- JSON list
    published_at  TEXT,
    updated_at    TEXT,
    author        TEXT,
    thumbnail     TEXT,
    summary       TEXT,
    word_count    INTEGER,
    in_sitemap    INTEGER NOT NULL DEFAULT 0,
    in_feed       INTEGER NOT NULL DEFAULT 0,
    sitemap_lastmod TEXT,
    source        TEXT,                            -- sitemap | feed | manual | demo
    discovered_at TEXT NOT NULL,
    last_seen_at  TEXT,
    -- denormalised "latest" columns so the table view is one query
    verdict       TEXT,                            -- PASS | NEUTRAL | FAIL | ERROR
    coverage      TEXT,
    last_crawl    TEXT,
    crawled_as    TEXT,
    fetch_state   TEXT,
    robots_state  TEXT,
    indexing_state TEXT,
    google_canonical TEXT,
    user_canonical TEXT,
    inspected_at  TEXT,
    inspect_error TEXT,
    pushed_at     TEXT,
    push_status   TEXT,                            -- ok | error
    push_error    TEXT,
    push_type     TEXT,
    push_count    INTEGER NOT NULL DEFAULT 0,
    notify_time   TEXT,                            -- from Google's metadata endpoint
    priority      INTEGER NOT NULL DEFAULT 0,
    ignored       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_urls_verdict ON urls(verdict);
CREATE INDEX IF NOT EXISTS idx_urls_kind ON urls(kind);

CREATE TABLE IF NOT EXISTS inspections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id       INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
    checked_at   TEXT NOT NULL,
    http_status  INTEGER,
    verdict      TEXT,
    coverage     TEXT,
    last_crawl   TEXT,
    crawled_as   TEXT,
    fetch_state  TEXT,
    robots_state TEXT,
    indexing_state TEXT,
    google_canonical TEXT,
    user_canonical TEXT,
    referring_urls TEXT,   -- JSON list
    sitemaps     TEXT,     -- JSON list
    rich_results TEXT,     -- JSON
    result_link  TEXT,
    raw          TEXT,     -- full JSON response
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_insp_url ON inspections(url_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS requests_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    kind         TEXT NOT NULL,     -- publish | inspect | metadata | sites | discover
    url          TEXT,
    request_type TEXT,              -- URL_UPDATED | URL_DELETED | ...
    http_status  INTEGER,
    ok           INTEGER NOT NULL DEFAULT 0,
    summary      TEXT,
    error        TEXT,
    duration_ms  INTEGER,
    job_id       INTEGER,
    raw          TEXT
);
CREATE INDEX IF NOT EXISTS idx_req_at ON requests_log(at DESC);
CREATE INDEX IF NOT EXISTS idx_req_url ON requests_log(url);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,      -- inspect_all | inspect_selected | push_unindexed | push_selected | discover | recheck
    status      TEXT NOT NULL,      -- queued | running | done | failed | cancelled
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    total       INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    ok_count    INTEGER NOT NULL DEFAULT 0,
    err_count   INTEGER NOT NULL DEFAULT 0,
    skipped     INTEGER NOT NULL DEFAULT 0,
    message     TEXT,
    params      TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    level   TEXT NOT NULL DEFAULT 'info',   -- info | success | warn | error
    message TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(INSTANCE_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def init_db():
    with _lock:
        conn = _connect()
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        conn.commit()


def reset_db():
    """Drop every table (used when disconnecting / switching modes)."""
    with _lock:
        conn = _connect()
        conn.executescript(
            "DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS jobs; DROP TABLE IF EXISTS requests_log;"
            "DROP TABLE IF EXISTS inspections; DROP TABLE IF EXISTS urls; DROP TABLE IF EXISTS properties;"
            "DROP TABLE IF EXISTS settings;"
        )
        conn.commit()
    init_db()


@contextmanager
def tx():
    """Serialised write transaction."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql, params=()):
    conn = _connect()
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    conn = _connect()
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(sql, params=()):
    conn = _connect()
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


# ---------------- settings ----------------

def get_setting(key, default=""):
    v = scalar("SELECT value FROM settings WHERE key=?", (key,))
    return v if v is not None else DEFAULT_SETTINGS.get(key, default)


def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    for r in query("SELECT key, value FROM settings"):
        out[r["key"]] = r["value"]
    return out


def set_setting(key, value):
    with tx() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, "" if value is None else str(value)),
        )


def set_settings(mapping: dict):
    with tx() as conn:
        for k, v in mapping.items():
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, "" if v is None else str(v)),
            )


# ---------------- events ----------------

def log_event(message, level="info"):
    with tx() as conn:
        conn.execute("INSERT INTO events(at, level, message) VALUES (?,?,?)", (now_iso(), level, message))
        conn.execute("DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 500)")


# ---------------- requests log ----------------

def log_request(kind, url=None, request_type=None, http_status=None, ok=False, summary=None,
                error=None, duration_ms=None, job_id=None, raw=None):
    with tx() as conn:
        conn.execute(
            "INSERT INTO requests_log(at, kind, url, request_type, http_status, ok, summary, error, duration_ms, job_id, raw) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (now_iso(), kind, url, request_type, http_status, 1 if ok else 0, summary, error, duration_ms, job_id,
             json.dumps(raw)[:20000] if raw is not None else None),
        )


def count_requests_since(kind, since_iso) -> int:
    return scalar("SELECT COUNT(*) FROM requests_log WHERE kind=? AND at>=?", (kind, since_iso)) or 0


# ---------------- urls ----------------

def upsert_url(url, **fields):
    """Insert or update a URL row. Only the provided fields are touched."""
    fields = {k: v for k, v in fields.items() if v is not None}
    if "labels" in fields and not isinstance(fields["labels"], str):
        fields["labels"] = json.dumps(fields["labels"])
    with tx() as conn:
        row = conn.execute("SELECT id FROM urls WHERE url=?", (url,)).fetchone()
        ts = now_iso()
        if row:
            fields["last_seen_at"] = ts
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE urls SET {sets} WHERE id=?", (*fields.values(), row["id"]))
            return row["id"], False
        fields.setdefault("kind", "post")
        fields.setdefault("source", "manual")
        fields["discovered_at"] = ts
        fields["last_seen_at"] = ts
        cols = ", ".join(["url", *fields.keys()])
        marks = ", ".join(["?"] * (len(fields) + 1))
        cur = conn.execute(f"INSERT INTO urls({cols}) VALUES ({marks})", (url, *fields.values()))
        return cur.lastrowid, True


def get_url(url_id=None, url=None):
    if url_id is not None:
        return query_one("SELECT * FROM urls WHERE id=?", (url_id,))
    return query_one("SELECT * FROM urls WHERE url=?", (url,))


def delete_url(url_id):
    with tx() as conn:
        conn.execute("DELETE FROM urls WHERE id=?", (url_id,))


# ---------------- jobs ----------------

def create_job(kind, total=0, params=None):
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO jobs(kind, status, created_at, total, params) VALUES (?,?,?,?,?)",
            (kind, "queued", now_iso(), total, json.dumps(params or {})),
        )
        return cur.lastrowid


def update_job(job_id, **fields):
    if not fields:
        return
    with tx() as conn:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id):
    return query_one("SELECT * FROM jobs WHERE id=?", (job_id,))


def active_job():
    return query_one("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY id LIMIT 1")

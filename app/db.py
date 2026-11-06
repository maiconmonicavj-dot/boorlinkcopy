"""Camada de banco de dados (SQLite) e migrações."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    totp_secret    TEXT,               -- criptografado
    totp_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip         TEXT,
    ua         TEXT
);

CREATE TABLE IF NOT EXISTS pending_2fa (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT,
    ip         TEXT,
    ok         INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    severity   TEXT NOT NULL DEFAULT 'info',
    detail     TEXT,
    ip         TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stores (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    domain            TEXT NOT NULL,
    affiliate_param   TEXT NOT NULL DEFAULT 'tag',
    affiliate_value   TEXT NOT NULL DEFAULT '',
    api_kind          TEXT NOT NULL DEFAULT 'manual',   -- manual | generic | amazon | mercado_livre | shopee
    api_base          TEXT,
    api_key_enc       TEXT,
    api_secret_enc    TEXT,
    refresh_token_enc TEXT,
    token_expires_at  TEXT,
    collector_url     TEXT,
    min_rating        REAL NOT NULL DEFAULT 4.0,
    min_sales         INTEGER NOT NULL DEFAULT 50,
    active            INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id       INTEGER NOT NULL,
    external_id    TEXT,
    title          TEXT NOT NULL,
    description    TEXT,
    image_url      TEXT,
    original_url   TEXT NOT NULL,
    affiliate_url  TEXT NOT NULL,
    price          REAL,
    original_price REAL,
    discount_pct   REAL,
    coupon_code    TEXT,
    coupon_desc    TEXT,
    coupon_url     TEXT,
    seller_name    TEXT,
    seller_rating  REAL,
    seller_sales   INTEGER,
    score          REAL NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'approved',   -- approved | blocked | pending
    block_reason   TEXT,
    source         TEXT NOT NULL DEFAULT 'api',
    fingerprint    TEXT UNIQUE,
    category       TEXT,
    posted_at      TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (store_id) REFERENCES stores(id)
);

CREATE TABLE IF NOT EXISTS coupons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id    INTEGER NOT NULL,
    code        TEXT,
    title       TEXT NOT NULL,
    description TEXT,
    url         TEXT,
    expires_at  TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    status     TEXT NOT NULL,
    detail     TEXT,
    collected  INTEGER NOT NULL DEFAULT 0,
    blocked    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_offers_created ON offers(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);
CREATE INDEX IF NOT EXISTS idx_events_created ON security_events(created_at DESC);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


MIGRATIONS = {
    "offers": [("posted_at", "TEXT"), ("category", "TEXT")],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in MIGRATIONS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with db() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid or 0


# --- settings (chave/valor) ---------------------------------------------------
def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

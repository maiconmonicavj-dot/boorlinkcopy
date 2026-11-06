"""Camada de banco de dados (SQLite) e migrações."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DATABASE_URL, DB_PATH, DB_TOKEN, DB_URL

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


def _turso_enabled() -> bool:
    return bool(DB_URL and DB_TOKEN and DB_URL.startswith("libsql://"))


def _turso_http(url: str) -> str:
    host = url.replace("libsql://", "").replace("https://", "").strip("/")
    return f"https://{host}/v2/pipeline"


class LibSQLConn:
    """Adaptador mínimo que fala o protocolo HTTP do Turso/libSQL.

    Usa a mesma interface do sqlite3 usada neste projeto (execute, executemany,
    executescript, commit, rollback, close).
    """

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self._last_id = 0

    def _value(self, v: Any) -> dict:
        if v is None:
            return {"type": "null"}
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        if isinstance(v, bytes):
            import base64

            return {"type": "blob", "base64": base64.b64encode(v).decode()}
        return {"type": "text", "value": str(v)}

    def _rows(self, result: dict) -> list[dict]:
        cols = [c["name"] for c in result.get("cols", [])]
        out = []
        for row in result.get("rows", []):
            out.append({cols[i]: self._py(cell) for i, cell in enumerate(row)})
        return out

    @staticmethod
    def _py(cell: dict):
        t = cell.get("type")
        if t == "null":
            return None
        if t == "integer":
            return int(cell["value"])
        if t == "float":
            return float(cell["value"])
        return cell.get("value")

    def _call(self, stmts: list[dict]) -> list[dict]:
        import requests

        payload = {"requests": stmts + [{"type": "close"}]}
        r = requests.post(self.url, json=payload, timeout=45, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        r.raise_for_status()
        data = r.json()
        results = []
        for res in data.get("results", []):
            if res.get("type") == "error":
                raise RuntimeError(res.get("error", {}).get("message", "erro libSQL"))
            results.append(res.get("response", {}).get("result", {}))
        return results

    # interface sqlite3 -----------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()):
        stmt = {"type": "execute", "stmt": {"sql": sql,
                "args": [self._value(p) for p in params]}}
        if sql.strip().lower().startswith("insert"):
            stmt["stmt"]["want_last_insert_rowid"] = True
        res = self._call([stmt])[0]
        rows = self._rows(res)
        if "last_insert_rowid" in res:
            self._last_id = int(res["last_insert_rowid"] or 0)
        return _Result(rows, getattr(self, "_last_id", 0))

    def executescript(self, script: str):
        stmts = [s.strip() for s in script.split(";") if s.strip()]
        for chunk in stmts:
            self.execute(chunk)
        self.commit()

    def executemany(self, sql: str, seq):
        for params in seq:
            self.execute(sql, params)
        self.commit()

    def begin(self):
        self.execute("BEGIN")

    def commit(self):
        try:
            self.execute("COMMIT")
        except Exception:  # noqa: BLE001
            pass

    def rollback(self):
        try:
            self.execute("ROLLBACK")
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        pass


class _Result:
    def __init__(self, rows: list[dict], last_id: int = 0):
        self._rows = rows
        self.rowcount = len(rows)
        self.lastrowid = last_id

    def fetchall(self):
        return [_Rec(r) for r in self._rows]

    def fetchone(self):
        return _Rec(self._rows[0]) if self._rows else None

    def __iter__(self):
        return iter(self.fetchall())


class _Rec(dict):
    """Registro com acesso por índice e por nome (como sqlite3.Row)."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return dict.__getitem__(self, key)


def connect():
    if _turso_enabled():
        return LibSQLConn(_turso_http(DB_URL), DB_TOKEN)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        if hasattr(conn, "begin"):
            conn.begin()
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


def query(sql: str, params: Iterable[Any] = ()) -> list:
    with db() as conn:
        cur = conn.execute(sql, tuple(params))
        return list(cur.fetchall())


def query_one(sql: str, params: Iterable[Any] = ()):
    with db() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with db() as conn:
        cur = conn.execute(sql, tuple(params))
        return getattr(cur, "lastrowid", 0) or 0


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

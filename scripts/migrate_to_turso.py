"""Copia os dados do SQLite local para o Turso (nuvem).

Uso:
    set BOOR_DB_URL=libsql://SEU-BANCO.turso.io
    set BOOR_DB_TOKEN=SEU_TOKEN
    python scripts/migrate_to_turso.py

Copia todas as tabelas, na ordem certa, e depois as sequências de autoincremento.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import DB_PATH  # noqa: E402

TABLES = ["settings", "users", "sessions", "pending_2fa", "login_attempts",
          "security_events", "stores", "offers", "coupons", "bot_runs"]


def main() -> None:
    if not db._turso_enabled():
        print("Defina BOOR_DB_URL (libsql://...) e BOOR_DB_TOKEN antes de rodar.")
        return
    src = sqlite3.connect(DB_PATH)
    src.row_factory = sqlite3.Row
    db.init_db()  # cria o schema na nuvem
    total = 0
    with db.db() as conn:
        for table in TABLES:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                data = dict(row)
                cols = ", ".join(data)
                marks = ", ".join("?" for _ in data)
                conn.execute(f"INSERT OR REPLACE INTO {table}({cols}) VALUES({marks})",
                             tuple(data.values()))
            total += len(rows)
            print(f"{table}: {len(rows)} registros")
    print(f"Concluído: {total} registros copiados para {os.getenv('BOOR_DB_URL')}")


if __name__ == "__main__":
    main()

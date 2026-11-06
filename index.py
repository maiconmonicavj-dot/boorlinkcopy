"""Entrada serverless para a Vercel (@vercel/python)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import bootstrap  # noqa: E402
from app.main import app  # noqa: E402,F401

# Em produção (Vercel) os dados vêm da nuvem: Turso (libSQL) ou Postgres.
# Sem essas variáveis o SQLite local fica em /tmp (efêmero na Vercel).
try:
    bootstrap(verbose=False)
except Exception as exc:  # noqa: BLE001
    print("[boorlinkcopy] bootstrap:", exc)

"""Configuração central da plataforma boorlinkcopy."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Na Vercel o disco é somente leitura, exceto /tmp
_default_data = "/tmp/boorlinkcopy" if os.getenv("VERCEL") else BASE_DIR / "data"
DATA_DIR = Path(os.getenv("BOOR_DATA_DIR", _default_data))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("BOOR_DB", DATA_DIR / "boorlinkcopy.db"))

# --- Segurança ---------------------------------------------------------------
# Chave usada para criptografar segredos (refresh tokens, TOTP seeds) no banco.
# Em produção defina BOOR_SECRET_KEY (32+ bytes aleatórios) no ambiente/nuvem.
SECRET_KEY = os.getenv("BOOR_SECRET_KEY", "")

SESSION_COOKIE = "boor_session"
SESSION_TTL_MIN = int(os.getenv("BOOR_SESSION_TTL_MIN", "720"))       # 12h
CHALLENGE_TTL_MIN = int(os.getenv("BOOR_CHALLENGE_TTL_MIN", "5"))     # 2FA pendente

# Tentativas de login (por email+IP) antes de bloquear
LOGIN_MAX_ATTEMPTS = int(os.getenv("BOOR_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_MIN = int(os.getenv("BOOR_LOGIN_WINDOW_MIN", "15"))
LOGIN_LOCK_MIN = int(os.getenv("BOOR_LOGIN_LOCK_MIN", "15"))

# 2FA: tentativas de código errado antes de tratar como invasão
TOTP_MAX_ATTEMPTS = int(os.getenv("BOOR_TOTP_MAX_ATTEMPTS", "5"))

# Kill switch: total de eventos de intrusão em uma janela antes de desligar tudo
INTRUSION_WINDOW_MIN = int(os.getenv("BOOR_INTRUSION_WINDOW_MIN", "60"))
INTRUSION_THRESHOLD = int(os.getenv("BOOR_INTRUSION_THRESHOLD", "12"))

# Senha offline (usada só para reativar o sistema após o desligamento de segurança)
OFFLINE_RECOVERY_HASH = "BOOR_OFFLINE_RECOVERY_HASH"
OFFLINE_MAX_ATTEMPTS = 3

# --- Robô --------------------------------------------------------------------
BOT_INTERVAL_MIN = int(os.getenv("BOOR_BOT_INTERVAL_MIN", "20"))  # minutos entre ciclos
HUMAN_MIN_DELAY = float(os.getenv("BOOR_HUMAN_MIN_DELAY", "0.8"))
HUMAN_MAX_DELAY = float(os.getenv("BOOR_HUMAN_MAX_DELAY", "3.5"))
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
]

APP_NAME = "boorlinkcopy"

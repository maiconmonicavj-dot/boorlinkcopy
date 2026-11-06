"""Criptografia de segredos, hashing de senha e tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .config import SECRET_KEY


# --- chave mestra -------------------------------------------------------------
def _master_key() -> bytes:
    if SECRET_KEY:
        return hashlib.sha256(SECRET_KEY.encode()).digest()
    stored = db.get_setting("master_key")
    if not stored:
        stored = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        db.set_setting("master_key", stored)
    return base64.urlsafe_b64decode(stored.encode())


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(_master_key()))


def encrypt(plain: str | None) -> str | None:
    if not plain:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


# --- senhas -------------------------------------------------------------------
PBKDF2_ROUNDS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


# --- tokens de sessão ---------------------------------------------------------
def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now_iso(offset_seconds: int = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_seconds))


def random_password(length: int = 24) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def env_key_name() -> str:
    return os.getenv("BOOR_ENV", "local")

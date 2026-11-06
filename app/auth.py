"""Autenticação, 2FA (TOTP), sessões, rate-limit e kill switch de intrusão."""
from __future__ import annotations

import pyotp

from . import db, security
from .config import (
    INTRUSION_THRESHOLD, INTRUSION_WINDOW_MIN, LOGIN_LOCK_MIN, LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_MIN, OFFLINE_MAX_ATTEMPTS, OFFLINE_RECOVERY_HASH, SESSION_TTL_MIN,
    TOTP_MAX_ATTEMPTS,
)

LOCK_KEY = "system_locked"


class AuthError(Exception):
    pass


# --- eventos ------------------------------------------------------------------
def log_event(kind: str, detail: str = "", severity: str = "info", ip: str | None = None) -> None:
    db.execute(
        "INSERT INTO security_events(kind, severity, detail, ip, created_at) VALUES(?,?,?,?,?)",
        (kind, severity, detail, ip, security.now_iso()),
    )


def recent_events(limit: int = 50) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM security_events ORDER BY id DESC LIMIT ?", (limit,))]


# --- kill switch --------------------------------------------------------------
def is_locked() -> bool:
    return db.get_setting(LOCK_KEY, "0") == "1"


def lock_system(reason: str, ip: str | None = None) -> None:
    db.set_setting(LOCK_KEY, "1")
    db.set_setting("locked_at", security.now_iso())
    db.set_setting("locked_reason", reason)
    db.execute("DELETE FROM sessions")
    db.execute("DELETE FROM pending_2fa")
    log_event("system_locked", reason, "critical", ip)


def _unlock_token() -> str | None:
    """Token de emergência (variável de ambiente BOOR_UNLOCK_TOKEN), lido direto
    no servidor: último recurso caso a senha offline seja esquecida."""
    import os

    return os.getenv("BOOR_UNLOCK_TOKEN") or None


def unlock_with_offline_password(password: str, ip: str | None = None) -> bool:
    stored = db.get_setting(OFFLINE_RECOVERY_HASH) or OFFLINE_RECOVERY_HASH
    attempts = int(db.get_setting("offline_attempts", "0"))
    emergency = _unlock_token()
    if emergency and security.constant_eq(password or "", emergency):
        log_event("system_unlocked", "reativado com BOOR_UNLOCK_TOKEN", "warning", ip)
    elif attempts >= OFFLINE_MAX_ATTEMPTS:
        log_event("offline_attempts_exhausted",
                  "Limite de tentativas da senha offline atingido; use BOOR_UNLOCK_TOKEN.",
                  "critical", ip)
        raise AuthError(
            "Limite de tentativas da senha offline atingido. Reative no servidor com a "
            "variável BOOR_UNLOCK_TOKEN.")
    elif not security.verify_password(password or "", stored):
        db.set_setting("offline_attempts", str(attempts + 1))
        log_event("offline_unlock_failed", f"tentativa {attempts + 1}", "warning", ip)
        return False
    db.set_setting(LOCK_KEY, "0")
    db.set_setting("offline_attempts", "0")
    db.set_setting("locked_reason", "")
    log_event("system_unlocked", "reativado com senha offline", "warning", ip)
    return True


def register_intrusion(kind: str, detail: str = "", ip: str | None = None) -> None:
    """Conta evento de intrusão e desliga o sistema se passar do limite."""
    log_event(kind, detail, "warning", ip)
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM security_events WHERE severity IN ('warning','critical')"
        " AND kind NOT IN ('login_ok') AND created_at >= ?",
        (security.now_iso(-INTRUSION_WINDOW_MIN * 60),),
    )
    if row and row["n"] >= INTRUSION_THRESHOLD and not is_locked():
        lock_system(
            f"{row['n']} eventos de segurança em {INTRUSION_WINDOW_MIN} min "
            f"(último: {kind} - {detail})", ip)


# --- usuários -----------------------------------------------------------------
def create_user(email: str, password: str) -> int:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 6:
        raise AuthError("E-mail inválido.")
    if len(password or "") < 10:
        raise AuthError("A senha precisa ter no mínimo 10 caracteres.")
    if db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("Este e-mail já está cadastrado.")
    uid = db.execute(
        "INSERT INTO users(email, password_hash, totp_confirmed, created_at) VALUES(?,?,0,?)",
        (email, security.hash_password(password), security.now_iso()),
    )
    log_event("user_created", email)
    return uid


def get_user(email: str):
    return db.query_one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))


# --- rate limit de login ------------------------------------------------------
def _login_locked(email: str, ip: str | None) -> bool:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE ok = 0 AND email = ? AND ip IS ?"
        " AND created_at >= ?", (email, ip, security.now_iso(-LOGIN_WINDOW_MIN * 60)))
    if not row or row["n"] < LOGIN_MAX_ATTEMPTS:
        return False
    db.set_setting(f"lock_until:{email}", security.now_iso(LOGIN_LOCK_MIN * 60))
    return True


def _lock_remaining(email: str) -> bool:
    until = db.get_setting(f"lock_until:{email}")
    return bool(until and until > security.now_iso())


# --- login --------------------------------------------------------------------
def start_login(email: str, password: str, ip: str | None = None) -> dict:
    """Etapa 1: e-mail + senha. Devolve challenge token se precisar de 2FA."""
    if is_locked():
        raise AuthError("Sistema desligado por segurança. Reative com a senha offline.")
    email = (email or "").strip().lower()
    if _lock_remaining(email) or _login_locked(email, ip):
        register_intrusion("login_blocked", f"muitas tentativas para {email}", ip)
        raise AuthError("Muitas tentativas. Acesso bloqueado por alguns minutos.")

    user = get_user(email)
    ok = bool(user) and security.verify_password(password or "", user["password_hash"])
    db.execute("INSERT INTO login_attempts(email, ip, ok, created_at) VALUES(?,?,?,?)",
               (email, ip, 1 if ok else 0, security.now_iso()))
    if not ok:
        register_intrusion("login_failed", f"senha inválida para {email}", ip)
        raise AuthError("E-mail ou senha incorretos.")

    if not user["totp_confirmed"]:
        # ainda não configurou o autenticador -> pede configuração
        return {"status": "setup_2fa", "email": email}

    challenge = security.new_token()
    db.execute(
        "INSERT INTO pending_2fa(token_hash, user_id, created_at, expires_at, attempts)"
        " VALUES(?,?,?,?,0)",
        (security.token_hash(challenge), user["id"], security.now_iso(),
         security.now_iso(300)),  # 5 minutos
    )
    return {"status": "need_2fa", "challenge": challenge, "email": email}


def begin_2fa_setup(email: str, password: str) -> dict:
    """Gera segredo TOTP + URI do QR code (exige senha novamente)."""
    user = get_user(email)
    if not user or not security.verify_password(password or "", user["password_hash"]):
        raise AuthError("E-mail ou senha incorretos.")
    secret = pyotp.random_base32()
    db.execute("UPDATE users SET totp_secret = ?, totp_confirmed = 0 WHERE id = ?",
               (security.encrypt(secret), user["id"]))
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user["email"], issuer_name="boorlinkcopy")
    return {"secret": secret, "otpauth_uri": uri, "email": user["email"]}


def confirm_2fa_setup(email: str, code: str, ip: str | None = None) -> str:
    """Confirma o primeiro código e devolve o token de sessão."""
    user = get_user(email)
    if not user:
        raise AuthError("Usuário não encontrado.")
    secret = security.decrypt(user["totp_secret"])
    if not secret or not pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1):
        register_intrusion("2fa_setup_failed", f"código inválido na ativação de {email}", ip)
        raise AuthError("Código inválido. Tente novamente.")
    db.execute("UPDATE users SET totp_confirmed = 1 WHERE id = ?", (user["id"],))
    log_event("2fa_enabled", email)
    return _new_session(user["id"], ip, None)


def verify_2fa(challenge: str, code: str, ip: str | None = None,
               ua: str | None = None) -> str:
    row = db.query_one("SELECT * FROM pending_2fa WHERE token_hash = ?",
                       (security.token_hash(challenge or ""),))
    if not row or row["expires_at"] < security.now_iso():
        raise AuthError("Sessão de verificação expirada. Faça login novamente.")
    if row["attempts"] >= TOTP_MAX_ATTEMPTS:
        db.execute("DELETE FROM pending_2fa WHERE token_hash = ?", (row["token_hash"],))
        register_intrusion("2fa_bruteforce", "tentativas de código esgotadas", ip)
        raise AuthError("Muitos códigos errados. Faça login novamente.")
    user = db.query_one("SELECT * FROM users WHERE id = ?", (row["user_id"],))
    secret = security.decrypt(user["totp_secret"]) if user else None
    if not secret or not pyotp.TOTP(secret).verify((code or "").strip(), valid_window=1):
        db.execute("UPDATE pending_2fa SET attempts = attempts + 1 WHERE token_hash = ?",
                   (row["token_hash"],))
        register_intrusion("2fa_failed", "código 2FA inválido", ip)
        raise AuthError("Código inválido.")
    db.execute("DELETE FROM pending_2fa WHERE token_hash = ?", (row["token_hash"],))
    return _new_session(user["id"], ip, ua)


def _new_session(user_id: int, ip: str | None, ua: str | None) -> str:
    token = security.new_token()
    db.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, ip, ua)"
        " VALUES(?,?,?,?,?,?)",
        (security.token_hash(token), user_id, security.now_iso(),
         security.now_iso(SESSION_TTL_MIN * 60), ip, ua),
    )
    db.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
               (security.now_iso(), user_id))
    log_event("login_ok", f"user {user_id}", "info", ip)
    return token


def session_user(token: str | None):
    if not token:
        return None
    row = db.query_one(
        "SELECT s.*, u.email FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token_hash = ?", (security.token_hash(token),))
    if not row:
        return None
    if row["expires_at"] < security.now_iso():
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (row["token_hash"],))
        return None
    return dict(row)


def logout(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?",
                   (security.token_hash(token),))


def change_password(user_id: int, current: str, new: str) -> None:
    user = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or not security.verify_password(current or "", user["password_hash"]):
        raise AuthError("Senha atual incorreta.")
    if len(new or "") < 10:
        raise AuthError("A nova senha precisa ter no mínimo 10 caracteres.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (security.hash_password(new), user_id))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    log_event("password_changed", f"user {user_id}", "warning")

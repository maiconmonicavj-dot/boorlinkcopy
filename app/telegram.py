"""Publicação das ofertas no grupo do Telegram (bot token + chat id)."""
from __future__ import annotations

import random
import time
from pathlib import Path

import requests

from . import curation, db, security
from .config import DATA_DIR

API = "https://api.telegram.org/bot{token}/{method}"


def _token() -> str | None:
    return security.decrypt(db.get_setting("telegram_token_enc"))


def _chat_id() -> str | None:
    return db.get_setting("telegram_chat_id")


def configured() -> bool:
    return bool(_token() and _chat_id())


def set_config(token: str | None = None, chat_id: str | None = None) -> None:
    if token:
        db.set_setting("telegram_token_enc", security.encrypt(token.strip()) or "")
    if chat_id is not None:
        db.set_setting("telegram_chat_id", chat_id.strip())


def test() -> dict:
    token, chat = _token(), _chat_id()
    if not token or not chat:
        return {"ok": False, "error": "Configure o token do bot e o ID do grupo."}
    try:
        r = requests.post(API.format(token=token, method="sendMessage"), data={
            "chat_id": chat,
            "text": "✅ boorlinkcopy conectado. As ofertas aprovadas vão cair aqui.",
            "disable_web_page_preview": "false",
        }, timeout=20)
        data = r.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", "erro do Telegram")}
        return {"ok": True, "chat": data["result"]["chat"].get("title") or chat}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _local_image(offer: dict) -> Path | None:
    url = offer.get("image_url") or ""
    if url.startswith("/media/"):
        p = Path(DATA_DIR) / "img" / url.split("/")[-1]
        if p.exists() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return p
    return None


def send_offer(offer: dict) -> dict:
    """Publica uma oferta; devolve {'ok': bool, 'error': str?}."""
    token, chat = _token(), _chat_id()
    if not token or not chat:
        return {"ok": False, "error": "Telegram não configurado"}
    text = curation.post_text(offer)
    img = _local_image(offer)
    try:
        if img:
            with img.open("rb") as fh:
                r = requests.post(
                    API.format(token=token, method="sendPhoto"),
                    data={"chat_id": chat, "caption": text[:1024], "parse_mode": "HTML"},
                    files={"photo": fh}, timeout=40)
        else:
            r = requests.post(API.format(token=token, method="sendMessage"), data={
                "chat_id": chat, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "false"}, timeout=30)
        data = r.json()
        if not data.get("ok"):
            # fallback: texto puro sem HTML (títulos com caracteres estranhos)
            r2 = requests.post(API.format(token=token, method="sendMessage"), data={
                "chat_id": chat, "text": _plain(offer)}, timeout=30)
            if not r2.json().get("ok"):
                return {"ok": False, "error": data.get("description", "erro do Telegram")}
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _plain(offer: dict) -> str:
    import re

    return re.sub(r"<[^>]+>", "", curation.post_text(offer))


def pending_offers(limit: int = 40) -> list[dict]:
    rows = db.query(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id"
        " WHERE o.status = 'approved' AND (o.posted_at IS NULL OR o.posted_at = '')"
        " ORDER BY o.score DESC, o.id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def publish_pending(max_posts: int | None = None,
                    pause: tuple[float, float] = (4.0, 12.0)) -> dict:
    """Publica as melhores ofertas ainda não postadas, com pausa 'humana'."""
    if max_posts is None:
        max_posts = int(curation.criteria()["max_posts"])
    posted, skipped, errors = 0, 0, []
    for offer in pending_offers(60):
        if posted >= max_posts:
            break
        ok, reasons = curation.worth(offer)
        if not ok:
            skipped += 1
            continue
        res = send_offer(offer)
        if res["ok"]:
            db.execute("UPDATE offers SET posted_at = ? WHERE id = ?",
                       (security.now_iso(), offer["id"]))
            db.execute(
                "INSERT INTO bot_runs(started_at, ended_at, status, detail, collected)"
                " VALUES(?,?, 'posted', ?, 1)",
                (security.now_iso(), security.now_iso(),
                 f"postada: {offer['title'][:80]} — {', '.join(reasons)}"))
            posted += 1
            time.sleep(random.uniform(*pause))
        else:
            errors.append(res.get("error") or "erro")
            if "chat not found" in (res.get("error") or "") or "unauthorized" in (res.get("error") or "").lower():
                break
    return {"posted": posted, "skipped": skipped, "errors": errors[:3]}

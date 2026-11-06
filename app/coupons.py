"""Cupons: captura, associação com ofertas e link com tag de afiliado."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import db
from .affiliate import convert

CODE_RE = re.compile(r"\b([A-Z0-9][A-Z0-9._-]{3,19})\b")
COUPON_HINT = re.compile(
    r"(cupom|cupons|c[óo]digo|desconto|promo[cç][ãa]o|off\b|% off|frete gr[áa]tis|"
    r"primeira compra|resgate|voucher)", re.IGNORECASE)


def parse_coupons(text: str) -> list[dict]:
    """Extrai cupons de um texto livre (API, página ou mensagem)."""
    if not text:
        return []
    found = []
    seen = set()
    for line in re.split(r"[\n;|]+", text):
        if not COUPON_HINT.search(line):
            continue
        for m in CODE_RE.finditer(line):
            code = m.group(1).strip(".-_")
            if len(code) < 4 or code.lower() in {"cupom", "cupons", "desconto", "frete"}:
                continue
            if code in seen:
                continue
            seen.add(code)
            found.append({"code": code, "title": line.strip()[:180], "description": line.strip()[:300]})
    return found


def save_coupon(store_id: int, code: str | None, title: str,
                description: str | None = None, url: str | None = None,
                expires_at: str | None = None) -> int:
    return db.execute(
        "INSERT INTO coupons(store_id, code, title, description, url, expires_at, active, created_at)"
        " VALUES(?,?,?,?,?,?,1,?)",
        (store_id, code, title, description, url, expires_at, _now()),
    )


def coupon_for_offer(store_id: int, coupon_code: str | None) -> dict | None:
    if not coupon_code:
        return None
    row = db.query_one(
        "SELECT * FROM coupons WHERE store_id = ? AND code = ? AND active = 1"
        " ORDER BY id DESC LIMIT 1", (store_id, coupon_code))
    return dict(row) if row else None


def attach_coupon(offer: dict) -> dict:
    """Garante que o cupom da oferta exista e devolve o link com tag."""
    if not offer.get("coupon_code"):
        return offer
    cp = coupon_for_offer(offer["store_id"], offer["coupon_code"])
    if not cp:
        cid = save_coupon(
            offer["store_id"], offer["coupon_code"],
            offer.get("coupon_desc") or f"Cupom {offer['coupon_code']}",
            offer.get("title"), offer.get("affiliate_url"),
        )
        cp = {"id": cid, "code": offer["coupon_code"],
              "title": offer.get("coupon_desc") or f"Cupom {offer['coupon_code']}"}
    offer["coupon"] = cp
    # botão "Ir para a oferta" sempre com a tag do afiliado
    if not offer.get("affiliate_url") and offer.get("original_url"):
        conv = convert(offer["original_url"])
        offer["affiliate_url"] = conv.get("affiliate_url") or offer["original_url"]
    return offer


def list_active(store_id: int | None = None, limit: int = 60) -> list[dict]:
    today = _now()[:10]
    sql = ("SELECT c.*, s.name AS store_name, s.slug AS store_slug FROM coupons c"
           " JOIN stores s ON s.id = c.store_id"
           " WHERE c.active = 1 AND (c.expires_at IS NULL OR c.expires_at >= ?)")
    params: list = [today]
    if store_id:
        sql += " AND c.store_id = ?"
        params.append(store_id)
    sql += " ORDER BY c.id DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in db.query(sql, params)]
    for r in rows:
        if r.get("url"):
            conv = convert(r["url"])
            r["affiliate_url"] = conv.get("affiliate_url") or r["url"]
        else:
            r["affiliate_url"] = None
    return rows


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

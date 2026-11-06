"""Robô coletor: APIs das lojas, refresh token automático e comportamento humano.

Fontes suportadas:
  * api_kind = 'generic'      -> GET JSON em api_base (lista de ofertas) com Bearer
  * api_kind = 'mercado_livre'-> API pública do Mercado Livre (trends/search)
  * api_kind = 'manual'       -> o robô lê collector_url (JSON já no formato de oferta)

Renovação automática: quando o token expira (ou a API devolve 401), o robô usa o
refresh_token guardado (criptografado) para obter um novo access token e salva.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from . import antifraud, coupons, curation, db, images, security
from .affiliate import convert
from .config import HUMAN_MAX_DELAY, HUMAN_MIN_DELAY, USER_AGENTS


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_pause(a: float = HUMAN_MIN_DELAY, b: float = HUMAN_MAX_DELAY) -> None:
    """Pausa com variação aleatória, como um humano lendo a página."""
    time.sleep(random.uniform(a, b))


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    })
    return s


# --- tokens -------------------------------------------------------------------
def _token_valid(store: dict) -> bool:
    exp = store.get("token_expires_at")
    if not exp:
        return False
    return exp > security.now_iso(60)  # renova 1 min antes


def refresh_access_token(store: dict, s: requests.Session | None = None) -> str | None:
    """Troca o refresh token por um novo access token e grava no banco."""
    rt = security.decrypt(store.get("refresh_token_enc"))
    if not rt or not store.get("api_base"):
        return None
    s = s or _session()
    url = store["api_base"].rstrip("/") + "/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": security.decrypt(store.get("api_key_enc")) or "",
        "client_secret": security.decrypt(store.get("api_secret_enc")) or "",
        "refresh_token": rt,
    }
    try:
        human_pause(0.3, 1.2)
        r = s.post(url, data=payload, timeout=25)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:180]}")
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        db.execute(
            "INSERT INTO security_events(kind, severity, detail, created_at)"
            " VALUES('token_refresh_failed','warning',?,?)",
            (f"{store['slug']}: {exc}", _now()))
        return None

    token = data.get("access_token")
    expires_in = int(data.get("expires_in") or 21_600)
    new_rt = data.get("refresh_token") or rt
    db.execute(
        "UPDATE stores SET refresh_token_enc = ?, token_expires_at = ? WHERE id = ?",
        (security.encrypt(new_rt), security.now_iso(expires_in), store["id"]))
    db.execute(
        "INSERT INTO security_events(kind, severity, detail, created_at)"
        " VALUES('token_refreshed','info',?,?)", (store["slug"], _now()))
    return token


def _bearer(store: dict, s: requests.Session) -> str | None:
    if _token_valid(store):
        return security.decrypt(store.get("api_key_enc")) or None
    return refresh_access_token(store, s)


# --- coleta por tipo de loja --------------------------------------------------
def _fetch_generic(store: dict, s: requests.Session) -> list[dict]:
    token = _bearer(store, s)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = s.get(store["api_base"], headers=headers, timeout=30)
    if r.status_code == 401:
        token = refresh_access_token(store, s)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = s.get(store["api_base"], headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("results") or data.get("items") or data.get("offers") or data
    return items if isinstance(items, list) else []


def _fetch_mercado_livre(store: dict, s: requests.Session) -> list[dict]:
    out: list[dict] = []
    queries = ["ofertas do dia", "promoção", "desconto"]
    for q in queries:
        human_pause()
        r = s.get("https://api.mercadolibre.com/sites/MLB/search",
                  params={"q": q, "limit": 20}, timeout=30)
        if r.status_code >= 400:
            continue
        for item in r.json().get("results", [])[:15]:
            price = item.get("price")
            orig = item.get("original_price")
            disc = round((1 - price / orig) * 100, 1) if price and orig and orig > price else 0
            seller = item.get("seller") or {}
            out.append({
                "external_id": item.get("id"),
                "title": item.get("title"),
                "image_url": (item.get("thumbnail") or "").replace("http://", "https://"),
                "original_url": item.get("permalink"),
                "price": price,
                "original_price": orig,
                "discount_pct": disc,
                "seller_name": seller.get("nickname"),
                "seller_rating": None,
                "seller_sales": None,
                "coupon_code": None,
                "comments": [],
            })
    return out


def _fetch_manual(store: dict, s: requests.Session) -> list[dict]:
    if not store.get("collector_url"):
        return []
    r = s.get(store["collector_url"], timeout=30)
    r.raise_for_status()
    data = r.json()
    items = data.get("offers") or data.get("items") or data
    return items if isinstance(items, list) else []


FETCHERS = {
    "generic": _fetch_generic,
    "mercado_livre": _fetch_mercado_livre,
    "manual": _fetch_manual,
    "amazon": _fetch_generic,
    "shopee": _fetch_generic,
}


# --- persistência -------------------------------------------------------------
def _fingerprint(store_id: int, item: dict) -> str:
    base = str(item.get("external_id") or item.get("original_url") or item.get("title"))
    base = re.sub(r"\s+", " ", base).strip().lower()
    return f"{store_id}:{base}"


def save_offer(store: dict, item: dict) -> tuple[str, str | None]:
    """Valida, converte o link e grava a oferta. Devolve (status, motivo)."""
    url = item.get("original_url") or item.get("url")
    if not url or not item.get("title"):
        return "skipped", "sem link ou título"

    conv = convert(url, store_slug=store["slug"])
    aff = conv.get("affiliate_url") or url

    # cupons vindos junto da oferta
    coupon_code = item.get("coupon_code")
    coupon_desc = item.get("coupon_desc")
    if not coupon_code:
        parsed = coupons.parse_coupons(" ".join(
            str(item.get(k) or "") for k in ("description", "coupon_text", "coupons")))
        if parsed:
            coupon_code = parsed[0]["code"]
            coupon_desc = parsed[0]["title"]
            coupons.save_coupon(store["id"], coupon_code, coupon_desc,
                                item.get("title"), aff)

    verdict = antifraud.evaluate(item, store)

    price = item.get("price")
    orig = item.get("original_price")
    disc = item.get("discount_pct")
    if disc is None and price and orig and orig > price:
        disc = round((1 - price / orig) * 100, 1)

    # foto real do produto (og:image / API da loja); nunca fica em branco
    image_url = images.resolve(
        {"image_url": item.get("image_url"), "original_url": url,
         "title": item.get("title")}, store["name"])

    category = item.get("category") or curation.category_of(item)
    fp = _fingerprint(store["id"], item)
    try:
        db.execute(
            """INSERT INTO offers(store_id, external_id, title, description, image_url,
                original_url, affiliate_url, price, original_price, discount_pct,
                coupon_code, coupon_desc, seller_name, seller_rating, seller_sales,
                score, status, block_reason, source, fingerprint, created_at, category)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (store["id"], item.get("external_id"), item["title"][:300],
             (item.get("description") or "")[:1000], image_url, url, aff,
             price, orig, disc, coupon_code, coupon_desc,
             item.get("seller_name"), item.get("seller_rating"), item.get("seller_sales"),
             verdict["score"], verdict["status"],
             "; ".join(verdict["reasons"])[:500] if verdict["reasons"] else None,
             "api", fp, _now(), category))
    except Exception:  # fingerprint duplicado
        return "skipped", "oferta repetida"
    return verdict["status"], ("; ".join(verdict["reasons"]) or None)


def run_cycle(store_slug: str | None = None, publish: bool = True) -> dict:
    """Um ciclo de coleta do robô."""
    started = _now()
    run_id = db.execute(
        "INSERT INTO bot_runs(started_at, status) VALUES(?, 'running')", (started,))
    total_ok = total_blocked = 0
    details: list[str] = []

    sql = "SELECT * FROM stores WHERE active = 1"
    params: list = []
    if store_slug:
        sql += " AND slug = ?"
        params.append(store_slug)
    stores = [dict(r) for r in db.query(sql, params)]

    s = _session()
    for store in stores:
        fetcher = FETCHERS.get(store["api_kind"], _fetch_generic)
        try:
            human_pause()  # comportamento humano entre lojas
            items = fetcher(store, s)
        except Exception as exc:  # noqa: BLE001
            details.append(f"{store['slug']}: erro {exc}")
            continue
        for item in items:
            status, reason = save_offer(store, item)
            if status == "approved":
                total_ok += 1
            elif status == "blocked":
                total_blocked += 1
                details.append(f"bloqueado: {item.get('title', '')[:60]} ({reason})")
            human_pause(0.2, 0.9)

    pub = {"posted": 0, "skipped": 0, "errors": []}
    if publish:
        from . import telegram

        if telegram.configured():
            pub = telegram.publish_pending()

    db.execute(
        "UPDATE bot_runs SET ended_at = ?, status = 'done', detail = ?, collected = ?,"
        " blocked = ? WHERE id = ?",
        (_now(), (" | ".join(details) + (f" | postadas: {pub['posted']}" if pub["posted"] else ""))[:2000],
         total_ok, total_blocked, run_id))
    return {"run_id": run_id, "collected": total_ok, "blocked": total_blocked,
            "posted": pub["posted"], "post_errors": pub["errors"], "details": details}


def last_runs(limit: int = 10) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM bot_runs ORDER BY id DESC LIMIT ?", (limit,))]

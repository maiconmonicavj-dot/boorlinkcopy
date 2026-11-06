"""Imagens das ofertas: extrai a foto real do produto a partir do link.

Ordem de tentativa:
  1. foto enviada junto com a oferta (API da loja)
  2. og:image / JSON-LD / twitter:image da página do produto
  3. APIs públicas de produto por loja (ex.: Mercado Livre /items/{id})
  4. placeholder local com o nome do produto (nunca imagem em branco)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from .config import DATA_DIR

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
IMG_HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
BAD_HINTS = ("sprite", "logo", "placeholder", "pixel", "transparent", "1x1", "spacer", "blank")

IMG_DIR = Path(os.getenv("BOOR_IMG_DIR", Path(DATA_DIR) / "img"))
IMG_DIR.mkdir(parents=True, exist_ok=True)


def _get(url: str, **kw) -> requests.Response | None:
    """GET tolerante: tenta novamente sem cabeçalhos de imagem se a conexão cair."""
    for headers in (IMG_HEADERS, {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}):
        try:
            return requests.get(url, headers=headers, timeout=20,
                                allow_redirects=True, **kw)
        except Exception:  # noqa: BLE001
            continue
    return None


def is_usable_image(url: str | None) -> bool:
    """Confere se a URL devolve uma imagem real (não vazia, não pixel de rastreio)."""
    if not url or not url.lower().startswith("http"):
        return False
    if any(h in url.lower() for h in BAD_HINTS):
        return False
    r = _get(url, stream=True)
    if r is None or r.status_code >= 400:
        return False
    ctype = (r.headers.get("content-type") or "").lower()
    size = int(r.headers.get("content-length") or 0)
    r.close()
    if not ctype.startswith("image/"):
        return False
    if ctype == "image/gif" and size < 5000:  # gif pequeno = pixel de rastreio
        return False
    if 0 < size < 2000:
        return False
    return True


# --- extração da página do produto -------------------------------------------
OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url|:url)?|twitter:image)["\']'
    r'[^>]+content=["\']([^"\']+)["\']', re.I)
OG_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image)["\']', re.I)
JSONLD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.I | re.S)
DATA_SRC_RE = re.compile(r'<img[^>]+(?:data-src|data-zoom-image|data-image|data-old-hires)=["\']([^"\']+)["\']', re.I)
SRCSET_RE = re.compile(r'(?:srcset|data-srcset)=["\']([^"\']+)["\']', re.I)
PRELOAD_RE = re.compile(r'<link[^>]+rel=["\']preload["\'][^>]+as=["\']image["\'][^>]+href=["\']([^"\']+)["\']', re.I)
HI_RES_RE = re.compile(r'"(hiRes|large|mainUrl)"\s*:\s*"(https://[^"]+)"')


def _from_jsonld(html: str) -> str | None:
    for block in JSONLD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, dict):
                img = cur.get("image")
                if isinstance(img, str) and img.startswith("http"):
                    return img
                if isinstance(img, list) and img and isinstance(img[0], str):
                    return img[0]
                if isinstance(img, dict) and img.get("url"):
                    return img["url"]
                stack.extend(cur.values())
    return None


def _fetch_html(url: str) -> str | None:
    """Baixa o HTML da página do produto, tentando também versões 'www.'/sem www."""
    tries = [url]
    parts = urlsplit(url)
    if parts.netloc.startswith("www."):
        tries.append(url.replace("://www.", "://", 1))
    elif parts.netloc and "." in parts.netloc:
        tries.append(url.replace("://", "://www.", 1))
    best: str | None = None
    for target in tries:
        r = _get(target)
        if r is None or r.status_code >= 400:
            continue
        html = r.text
        if len(html) < 8000:  # página de bloqueio/consentimento
            continue
        if len(html) > len(best or ""):
            best = html
    return best


def image_from_page(url: str) -> str | None:
    html = _fetch_html(url)
    if not html:
        return None
    html = html[:900_000]
    for rx in (OG_RE, OG_RE_ALT):
        m = rx.search(html)
        if m:
            cand = urljoin(url, m.group(1).replace("&amp;", "&"))
            if cand.startswith("http"):
                return cand
    cand = _from_jsonld(html)
    if cand:
        return urljoin(url, cand)
    m = DATA_SRC_RE.search(html)
    if m and m.group(1).startswith("http"):
        return urljoin(url, m.group(1))
    m = PRELOAD_RE.search(html)
    if m:
        return urljoin(url, m.group(1))
    m = HI_RES_RE.search(html)
    if m:
        return m.group(2)
    for srcset in SRCSET_RE.findall(html):
        parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
        http_parts = [p for p in parts if p.startswith("http")]
        if http_parts:
            return urljoin(url, http_parts[-1])  # maior resolução costuma vir por último
    return None


def image_from_store_api(url: str) -> str | None:
    """APIs públicas de produto (Mercado Livre)."""
    m = re.search(r"(MLB)-?(\d{6,})", url, re.I)
    if m:
        item_id = f"MLB{m.group(2)}"
        r = _get(f"https://api.mercadolibre.com/items/{item_id}")
        if r is not None and r.status_code == 200:
            try:
                d = r.json()
                pics = d.get("pictures") or []
                if pics and pics[0].get("secure_url"):
                    return pics[0]["secure_url"]
                if d.get("thumbnail"):
                    return d["thumbnail"]
            except Exception:  # noqa: BLE001
                pass
    return None


# --- placeholder local --------------------------------------------------------
def placeholder(title: str, store: str = "") -> str:
    """SVG local com o nome do produto: nunca fica em branco."""
    key = hashlib.sha1(f"{title}|{store}".encode()).hexdigest()[:12]
    path = IMG_DIR / f"ph_{key}.svg"
    if not path.exists():
        words = (title or "Oferta").strip().split()
        lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) + 1 > 22:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        lines = lines[:3]
        palette = ["#1e3a8a", "#312e81", "#164e63", "#3b0764", "#134e4a"]
        bg = palette[int(key[:4], 16) % len(palette)]
        tspans = "".join(
            f'<tspan x="200" dy="{0 if i == 0 else 26}">{_esc(line)}</tspan>'
            for i, line in enumerate(lines))
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" '
            'viewBox="0 0 400 300">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{bg}"/><stop offset="1" stop-color="#0b1020"/>'
            '</linearGradient></defs>'
            '<rect width="400" height="300" fill="url(#g)"/>'
            '<circle cx="330" cy="60" r="90" fill="#ffffff10"/>'
            '<text x="200" y="130" text-anchor="middle" fill="#e8eefc" '
            f'font-family="Segoe UI,Arial" font-size="19" font-weight="600">{tspans}</text>'
            '<text x="200" y="248" text-anchor="middle" fill="#93a1c4" '
            f'font-family="Segoe UI,Arial" font-size="13">{_esc(store or "boorlinkcopy")}</text>'
            '<text x="200" y="272" text-anchor="middle" fill="#5b8cff" '
            'font-family="Segoe UI,Arial" font-size="12">'
            'sem foto do produto - abra o link da oferta</text>'
            '</svg>')
        path.write_text(svg, encoding="utf-8")
    return f"/media/{path.name}"


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- resolução completa -------------------------------------------------------
def resolve(offer: dict, store_name: str = "", save_locally: bool = True) -> str:
    """Devolve a melhor imagem disponível para a oferta.

    save_locally=True baixa a imagem para /media (evita hotlink bloqueado e
    garante que ela apareça mesmo quando a loja exige referer).
    """
    candidates: list[str] = []
    given = offer.get("image_url") or ""
    if given.startswith("/media/"):  # já resolvida antes
        return given
    if given:
        candidates.append(given)
    for fn in (image_from_store_api, image_from_page):
        try:
            found = fn(offer.get("original_url") or "")
        except Exception:  # noqa: BLE001
            found = None
        if found:
            candidates.append(found)

    for cand in candidates:
        if not cand or not cand.startswith("http"):
            continue
        if not save_locally:
            if is_usable_image(cand):
                return cand
            continue
        local = _download(cand)
        if local:
            return local
    return placeholder(offer.get("title") or "Oferta", store_name)


def _download(url: str) -> str | None:
    r = _get(url)
    if r is None or r.status_code >= 400:
        return None
    ctype = (r.headers.get("content-type") or "").lower()
    if not ctype.startswith("image/"):
        return None
    body = r.content
    if len(body) < 2000 or (ctype == "image/gif" and len(body) < 5000):
        return None
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
           "image/gif": "gif", "image/avif": "avif"}.get(ctype.split(";")[0], "jpg")
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + "." + ext
    path = IMG_DIR / name
    if not path.exists():
        path.write_bytes(body)
    return f"/media/{name}"


def backfill(limit: int = 200) -> dict:
    """Corrige ofertas com foto em branco/ausente (rodar uma vez, ou pelo painel)."""
    from . import db

    rows = db.query(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id"
        " WHERE o.image_url IS NULL OR o.image_url = '' OR o.image_url LIKE 'http%'"
        " ORDER BY o.id DESC LIMIT ?", (limit,))
    fixed = placeholders = 0
    for row in rows:
        offer = dict(row)
        current = offer.get("image_url")
        if current and current.startswith("/media/"):
            continue
        new = resolve(offer, offer.get("store_name") or "")
        db.execute("UPDATE offers SET image_url = ? WHERE id = ?", (new, offer["id"]))
        if new.startswith("/media/ph_"):
            placeholders += 1
        else:
            fixed += 1
    return {"checked": len(rows), "fixed": fixed, "placeholders": placeholders}

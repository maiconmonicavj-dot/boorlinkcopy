"""Conversão de links em links de afiliado (por loja cadastrada)."""
from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from . import db

# Lojas conhecidas: slug -> (nome, domínios, parâmetro da tag)
KNOWN_STORES: dict[str, tuple[str, tuple[str, ...], str]] = {
    "amazon": ("Amazon", ("amazon.com.br", "amazon.com", "amzn.to", "a.co"), "tag"),
    "mercadolivre": ("Mercado Livre", ("mercadolivre.com.br", "mercadolibre.com", "produto.mercadolivre.com.br"), "matt_tool"),
    "shopee": ("Shopee", ("shopee.com.br", "shp.ee"), "af_siteid"),
    "aliexpress": ("AliExpress", ("aliexpress.com", "s.click.aliexpress.com"), "aff_short_key"),
    "magalu": ("Magazine Luiza", ("magazineluiza.com.br", "magalu.com"), "partner_id"),
    "americanas": ("Americanas", ("americanas.com.br",), "utm_source"),
    "casasbahia": ("Casas Bahia", ("casasbahia.com.br",), "utm_source"),
    "ponto": ("Ponto Frio", ("pontofrio.com.br",), "utm_source"),
    "extra": ("Extra", ("extra.com.br",), "utm_source"),
    "netshoes": ("Netshoes", ("netshoes.com.br",), "utm_source"),
    "centauro": ("Centauro", ("centauro.com.br",), "utm_source"),
    "kabum": ("KaBuM!", ("kabum.com.br",), "utm_source"),
    "terabyteshop": ("Terabyte", ("terabyteshop.com.br",), "utm_source"),
    "pichau": ("Pichau", ("pichau.com.br",), "utm_source"),
    "carrefour": ("Carrefour", ("carrefour.com.br",), "utm_source"),
    "dafiti": ("Dafiti", ("dafiti.com.br",), "utm_source"),
    "nike": ("Nike", ("nike.com.br",), "utm_source"),
    "adidas": ("Adidas", ("adidas.com.br",), "utm_source"),
    "samsonite": ("Samsonite", ("samsonite.com.br",), "utm_source"),
    "tokstok": ("Tok&Stok", ("tokstok.com.br",), "utm_source"),
}

# Parâmetros de rastreio que costumam vir colados no link copiado
TRACKING_PARAMS = {
    "gclid", "fbclid", "msclkid", "ttclid", "twclid", "yclid",
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "ref_", "tag", "_encoding", "th", "psc", "pd_rd_r", "pd_rd_w",
    "pd_rd_wg", "pf_rd_p", "pf_rd_r", "spm", "scm", "pvid", "sr_share",
}


def normalize_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def detect_store(url: str) -> str | None:
    """Retorna o slug da loja conhecida a partir do link (ou None)."""
    try:
        host = normalize_domain(urlsplit(url).netloc)
    except ValueError:
        return None
    if not host:
        return None
    for slug, (_, domains, _) in KNOWN_STORES.items():
        for d in domains:
            if host == d or host.endswith("." + d):
                return slug
    # lojas cadastradas pelo usuário
    for row in db.query("SELECT slug, domain FROM stores"):
        d = normalize_domain(row["domain"])
        if d and (host == d or host.endswith("." + d)):
            return row["slug"]
    return None


def _store_config(slug: str | None) -> dict | None:
    if not slug:
        return None
    row = db.query_one("SELECT * FROM stores WHERE slug = ? AND active = 1", (slug,))
    if row:
        return dict(row)
    if slug in KNOWN_STORES:
        name, domains, param = KNOWN_STORES[slug]
        return {
            "slug": slug,
            "name": name,
            "domain": domains[0],
            "affiliate_param": param,
            "affiliate_value": "",
            "active": 1,
        }
    return None


def clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme or "https"
    netloc = parts.netloc.lower()
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")]
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def convert(url: str, tag: str | None = None, store_slug: str | None = None) -> dict:
    """Converte um link de loja em link de afiliado.

    Retorna dict com: ok, store, store_name, affiliate_url, original_url, error.
    """
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "Link vazio."}
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    slug = store_slug or detect_store(url)
    cfg = _store_config(slug)
    if not cfg:
        return {
            "ok": False,
            "error": "Loja não identificada. Cadastre a loja (domínio + parâmetro da tag) para converter este link.",
            "store": None,
        }

    aff_value = tag or cfg.get("affiliate_value") or ""
    if not aff_value:
        return {
            "ok": False,
            "store": cfg["slug"],
            "store_name": cfg["name"],
            "error": f"Tag de afiliado da loja {cfg['name']} não configurada.",
        }

    base = clean_url(url)
    parts = urlsplit(base)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k != cfg["affiliate_param"]]
    q.append((cfg["affiliate_param"], aff_value))
    affiliate_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))

    return {
        "ok": True,
        "store": cfg["slug"],
        "store_name": cfg["name"],
        "original_url": base,
        "affiliate_url": affiliate_url,
        "param": cfg["affiliate_param"],
        "tag": aff_value,
    }


def convert_many(urls: list[str], tag: str | None = None) -> list[dict]:
    seen: set[str] = set()
    out = []
    for raw in urls:
        raw = (raw or "").strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)
        out.append({"input": raw, **convert(raw, tag)})
    return out

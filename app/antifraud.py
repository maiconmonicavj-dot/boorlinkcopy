"""Filtro antifraude: palavras suspeitas nos comentários + reputação do vendedor."""
from __future__ import annotations

import re
import unicodedata

DEFAULT_RISK_PATTERNS = [
    r"\bfraude\b", r"\bfraud(es|ulento|ulenta)\b", r"\bgolpe\b", r"\bestelionat",
    r"\broub(o|aram|ei|ado|ada)\b", r"\bfurt(o|aram|ado)\b",
    r"n[ãa]o\s+entreg(am|ou|a|aram)", r"nunca\s+entreg", r"n[ãa]o\s+recebi",
    r"n[ãa]o\s+chegou", r"n[ãa]o\s+veio", r"produto\s+falso", r"\bfalsificad",
    r"\breplica\b", r"n[ãa]o\s+[ée]\s+original", r"\bengan(o|aram|a[çc][ãa]o)\b",
    r"cobran[çc]a\s+indevida", r"n[ãa]o\s+reembols", r"devolu[çc][ãa]o\s+negada",
    r"\bcareca\b.*\b(loja|vendedor)", r"vendedor\s+ruim", r"loja\s+ruim",
    r"\bp[ée]ssim[ao]\b", r"n[ãa]o\s+comprem", r"n[ãa]o\s+confi[áa]vel",
    r"\bscam\b", r"\bfake\b", r"n[ãa]o\s+recomendo", r"propaganda\s+enganosa",
]

# Termos de reforço (peso maior)
HARD_RISK = ["fraude", "golpe", "roubo", "roubaram", "estelionato", "falsificado", "scam"]


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _patterns() -> list[str]:
    from . import db

    custom = db.get_setting("risk_terms", "")
    extra = [t.strip() for t in custom.split(",") if t.strip()]
    pats = list(DEFAULT_RISK_PATTERNS)
    for term in extra:
        pats.append(r"\b" + re.escape(_strip_accents(term.lower())) + r"\b")
    return pats


def scan_comments(comments: list[str] | str | None) -> dict:
    """Procura termos de fraude/risco nos comentários da oferta."""
    if not comments:
        return {"hits": [], "hard": [], "risk": 0.0}
    if isinstance(comments, str):
        comments = [comments]
    text = _strip_accents(" \n ".join(c for c in comments if c)).lower()
    hits: list[str] = []
    for pat in _patterns():
        m = re.search(pat, text)
        if m:
            hits.append(m.group(0).strip())
    hard = [h for h in hits if any(k in h for k in HARD_RISK)]
    # normaliza risco: 0 a 1
    risk = min(1.0, len(hits) * 0.22 + len(hard) * 0.25)
    return {"hits": sorted(set(hits)), "hard": sorted(set(hard)), "risk": risk}


def seller_risk(rating: float | None, sales: int | None,
                min_rating: float, min_sales: int) -> dict:
    reasons = []
    risk = 0.0
    if rating is not None:
        if rating < min_rating:
            reasons.append(f"reputação {rating:.1f} abaixo do mínimo {min_rating:.1f}")
            risk += min(0.6, (min_rating - rating) * 0.35 + 0.25)
        elif rating < min_rating + 0.3:
            risk += 0.15
    if sales is not None and sales < min_sales:
        reasons.append(f"apenas {sales} vendas (mínimo {min_sales})")
        risk += 0.25
    return {"reasons": reasons, "risk": min(1.0, risk)}


def evaluate(offer: dict, store: dict | None = None) -> dict:
    """Decide se a oferta entra no site.

    Retorna: status ('approved'|'blocked'), risk (0-1), reasons (list), score.
    """
    min_rating = float((store or {}).get("min_rating", 4.0))
    min_sales = int((store or {}).get("min_sales", 50))

    comments = offer.get("comments") or []
    c = scan_comments(comments)
    s = seller_risk(offer.get("seller_rating"), offer.get("seller_sales"),
                    min_rating, min_sales)

    reasons = list(s["reasons"])
    if c["hits"]:
        reasons.append("termos de risco nos comentários: " + ", ".join(c["hits"][:6]))
    if c["hard"]:
        reasons.append("alerta grave: " + ", ".join(c["hard"][:4]))

    risk = min(1.0, c["risk"] * 0.7 + s["risk"] * 0.6)
    blocked = risk >= 0.5 or bool(c["hard"])

    discount = float(offer.get("discount_pct") or 0)
    rating = float(offer.get("seller_rating") or 4.5)
    sales = int(offer.get("seller_sales") or 0)
    # nota de 0-100: desconto (até 50) + reputação (até 30) + volume (até 20)
    score = (min(50.0, discount * 1.1)
             + max(0.0, min(30.0, (rating - 3.0) / 2.0 * 30))
             + min(20.0, sales / 500 * 20)
             - risk * 60)
    score = max(0.0, min(100.0, score))
    return {
        "status": "blocked" if blocked else "approved",
        "risk": round(risk, 2),
        "reasons": reasons,
        "score": round(score, 1),
    }

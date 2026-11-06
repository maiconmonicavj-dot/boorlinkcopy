"""Curadoria das ofertas: quais realmente compensam e o texto de postagem."""
from __future__ import annotations

import re

# Palavras de produto que costumam vender bem em grupo de ofertas
HOT_KEYWORDS = {
    "fone": 6, "airfryer": 6, "air fryer": 6, "smart tv": 7, "tv ": 5,
    "notebook": 7, "celular": 6, "smartphone": 6, "iphone": 7, "galaxy": 5, "xiaomi": 6,
    "console": 6, "playstation": 6, "xbox": 6, "monitor": 5, "cadeira": 5,
    "aspirador": 5, "robo": 3, "liquidificador": 4, "cafeteira": 5, "panela": 5,
    "tênis": 4, "tenis": 4, "perfume": 5, "creme": 3, "shampoo": 3, "fralda": 5,
    "mouse": 3, "teclado": 3, "ssd": 5, "hd externo": 4, "câmera": 4, "camera": 4,
    "bicicleta": 5, "colchão": 5, "colchao": 5, "geladeira": 6, "fogão": 5,
    "ventilador": 4, "ar condicionado": 6, "ar-condicionado": 6, "split": 4,
    "fritadeira": 6, "microondas": 4, "lava e seca": 5, "perfume": 5,
}

# Categorias: produtos caros aceitam desconto menor (5-10% já é dinheiro de verdade)
CATEGORIES = {
    "computadores-gamer": {
        "label": "Computadores Gamer",
        "keywords": ["gamer", "pc gamer", "notebook gamer", "placa de video", "rtx", "ryzen",
                     "intel core", "water cooler", "gabinete", "fonte ", "memoria ram"],
        "min_discount": 7, "min_price": 1500, "emoji": "🎮",
    },
    "geladeiras": {
        "label": "Geladeiras",
        "keywords": ["geladeira", "refrigerador", "freezer", "frigobar", "duplex", "frost free"],
        "min_discount": 8, "min_price": 1800, "emoji": "🧊",
    },
    "ar-condicionado": {
        "label": "Ar-condicionado",
        "keywords": ["ar condicionado", "ar-condicionado", "split", "inverter 9000",
                     "inverter 12000", "inverter 18000", "climatizador"],
        "min_discount": 8, "min_price": 1200, "emoji": "❄️",
    },
    "panelas": {
        "label": "Panelas e cozinha",
        "keywords": ["panela", "jogo de panelas", "frigideira", "caçarola", "cacarola",
                     "pressão", "pressao", "wok", "conjunto de panelas"],
        "min_discount": 12, "min_price": 0, "emoji": "🍳",
    },
    "air-fryer": {
        "label": "Air Fryer",
        "keywords": ["airfryer", "air fryer", "fritadeira", "fritadeira eletrica",
                     "fritadeira sem oleo"],
        "min_discount": 15, "min_price": 0, "emoji": "🍟",
    },
    "ventiladores": {
        "label": "Ventiladores e climatização",
        "keywords": ["ventilador", "ventilador de coluna", "ventilador de mesa", "circulador",
                     "climatizador", "exaustor", "umidificador"],
        "min_discount": 12, "min_price": 0, "emoji": "🌀",
    },
    "tv-e-som": {
        "label": "TV, som e home theater",
        "keywords": ["smart tv", "tv ", "televisao", "televisão", "soundbar", "home theater",
                     "caixa de som", "projetor"],
        "min_discount": 10, "min_price": 1000, "emoji": "📺",
    },
    "celulares": {
        "label": "Celulares e tablets",
        "keywords": ["celular", "smartphone", "iphone", "galaxy", "xiaomi", "motorola",
                     "tablet", "ipad"],
        "min_discount": 8, "min_price": 800, "emoji": "📱",
    },
    "informatica": {
        "label": "Informática",
        "keywords": ["notebook", "monitor", "ssd", "hd externo", "teclado", "mouse",
                     "impressora", "roteador", "webcam"],
        "min_discount": 10, "min_price": 0, "emoji": "💻",
    },
    "casa-e-moveis": {
        "label": "Casa e móveis",
        "keywords": ["sofa", "sofá", "colchao", "colchão", "guarda roupa", "mesa", "cadeira",
                     "rack", "estante", "cama"],
        "min_discount": 12, "min_price": 0, "emoji": "🛋️",
    },
    "eletrodomesticos": {
        "label": "Eletrodomésticos",
        "keywords": ["maquina de lavar", "máquina de lavar", "lava e seca", "lava-loucas",
                     "microondas", "micro-ondas", "fogao", "fogão", "cooktop", "coifa",
                     "aspirador", "robo aspirador"],
        "min_discount": 10, "min_price": 900, "emoji": "🔌",
    },
    "beleza-e-saude": {
        "label": "Beleza e saúde",
        "keywords": ["perfume", "creme", "shampoo", "secador", "prancha", "escova",
                     "kit beleza", "protetor solar"],
        "min_discount": 15, "min_price": 0, "emoji": "💅",
    },
    "moda-e-esporte": {
        "label": "Moda e esporte",
        "keywords": ["tenis", "tênis", "camiseta", "bermuda", "mochila", "bicicleta",
                     "academia", "halter", "suplemento", "whey"],
        "min_discount": 15, "min_price": 0, "emoji": "👟",
    },
    "games": {
        "label": "Games e consoles",
        "keywords": ["console", "playstation", "xbox", "nintendo", "switch", "jogo",
                     "controle ", "headset"],
        "min_discount": 8, "min_price": 500, "emoji": "🕹️",
    },
    "ferramentas": {
        "label": "Ferramentas",
        "keywords": ["furadeira", "parafusadeira", "serra", "chave de fenda", "kit ferramentas",
                     "compressor", "esmerilhadeira"],
        "min_discount": 12, "min_price": 0, "emoji": "🛠️",
    },
    "audio-e-fones": {
        "label": "Fones e áudio",
        "keywords": ["fone", "headset", "earbud", "caixa de som", "soundbar", "audio",
                     "áudio", "bluetooth anc"],
        "min_discount": 15, "min_price": 0, "emoji": "🎧",
    },
    "bebe-e-infantil": {
        "label": "Bebê e infantil",
        "keywords": ["fralda", "carrinho de bebe", "bebe", "bebê", "berço", "berco",
                     "mamadeira", "brinquedo"],
        "min_discount": 12, "min_price": 0, "emoji": "🍼",
    },
    "pet": {
        "label": "Pet",
        "keywords": ["racao", "ração", "petisco", "cama pet", "areia", "coleira",
                     "arranhador", "comedouro"],
        "min_discount": 12, "min_price": 0, "emoji": "🐾",
    },
    "outros": {
        "label": "Outros achados",
        "keywords": [],
        "min_discount": 15, "min_price": 0, "emoji": "✨",
    },
}

# Faixas que viram "menus chamativos" no site
HOT_DEALS_MAX_PRICE = 800       # achados do dia: barato + desconto
LIGHTNING_MAX_AGE_H = 12        # ofertas relâmpago: até 12h de captura
LIGHTNING_MIN_DISCOUNT = 30     # e desconto forte
TOP_DEAL_MIN_SAVING = 300       # "top de hoje": economia em reais

# Produtos que costumam gerar problema/reclamação: só entram com desconto forte
CAUTION_KEYWORDS = ["usado", "recondicionado", "refurbished", "importado", "kit 1 unidade"]

# Padrões — podem ser trocados pelo painel (aba Robô → Critérios)
DEFAULTS = {
    "min_discount": 15.0,   # % mínimo para valer post
    "min_score": 40.0,      # nota mínima de curadoria (0-100)
    "min_rating": 4.3,      # reputação mínima do vendedor
    "min_sales": 100,       # vendas mínimas do vendedor (quando conhecidas)
    "max_posts": 6,         # postagens por ciclo
    "post_interval": 20,    # minutos entre ciclos do robô
}


def criteria() -> dict:
    """Critérios atuais: padrões + ajustes salvos no banco."""
    from . import db

    out = dict(DEFAULTS)
    for key in out:
        raw = db.get_setting(key)
        if raw not in (None, ""):
            try:
                out[key] = float(raw) if "." in str(raw) else int(raw)
            except ValueError:
                pass
    return out


def save_criteria(**values) -> dict:
    from . import db

    for key, val in values.items():
        if key in DEFAULTS and val is not None:
            db.set_setting(key, str(val))
    return criteria()


def hot_keywords() -> dict[str, float]:
    """Palavras-chave de procura: padrão + as que o usuário cadastrou (peso 6)."""
    from . import db

    out = dict(HOT_KEYWORDS)
    custom = db.get_setting("hot_keywords", "") or ""
    for kw in [k.strip().lower() for k in custom.split(",") if k.strip()]:
        out[kw] = 6.0
    blocked = db.get_setting("hot_blocked", "") or ""
    for kw in [k.strip().lower() for k in blocked.split(",") if k.strip()]:
        out.pop(kw, None)
    return out


def caution_keywords() -> list[str]:
    from . import db

    custom = db.get_setting("caution_keywords", "") or ""
    extra = [k.strip().lower() for k in custom.split(",") if k.strip()]
    return CAUTION_KEYWORDS + extra


def _text(offer: dict) -> str:
    return f"{offer.get('title','')} {offer.get('description','')}".lower()


def category_of(offer: dict) -> str:
    """Categoria do produto pelo título/descrição (fallback: 'outros')."""
    t = _text(offer)
    best, best_hits = "outros", 0
    for slug, cfg in CATEGORIES.items():
        hits = sum(1 for kw in cfg["keywords"] if kw in t)
        if hits > best_hits:
            best, best_hits = slug, hits
    return best


def category_info(slug: str | None) -> dict:
    return CATEGORIES.get(slug or "outros", CATEGORIES["outros"])


def min_discount_for(offer: dict) -> float:
    """Desconto mínimo da categoria: produto caro aceita desconto menor."""
    base = float(criteria()["min_discount"])
    cat = category_info(offer.get("category") or category_of(offer))
    price = float(offer.get("price") or 0)
    need = float(cat.get("min_discount") or 0)
    min_price = float(cat.get("min_price") or 0)
    if price and price >= min_price:
        return min(base, need) if need else base
    return base


def appeal(offer: dict) -> float:
    """Quanto o produto 'puxa' público (0-20)."""
    t = _text(offer)
    pts = 0.0
    for kw, w in hot_keywords().items():
        if re.search(r"(?<![a-z])" + re.escape(kw.strip()) + r"(?![a-z])", t):
            pts += w
            break
    for kw in caution_keywords():
        if kw in t:
            pts -= 6
    # produtos caros: a economia em reais também conta (5% de 4.000 = R$ 200)
    saving = saving_brl(offer)
    if saving >= 1000:
        pts += 8
    elif saving >= 500:
        pts += 6
    elif saving >= 250:
        pts += 4
    elif saving >= 120:
        pts += 2
    return max(-10.0, min(24.0, pts))


def saving_brl(offer: dict) -> float:
    price = float(offer.get("price") or 0)
    orig = float(offer.get("original_price") or 0)
    return max(0.0, orig - price) if orig and price else 0.0


def worth(offer: dict) -> tuple[bool, list[str]]:
    """Diz se a oferta compensa postar, com os motivos."""
    cfg = criteria()
    min_discount = min_discount_for(offer)
    min_score = float(cfg["min_score"])
    min_rating = float(cfg["min_rating"])
    min_sales = int(cfg["min_sales"])
    reasons: list[str] = []
    disc = float(offer.get("discount_pct") or 0)
    score = float(offer.get("score") or 0)
    rating = offer.get("seller_rating")
    sales = offer.get("seller_sales")

    if offer.get("status") == "blocked":
        return False, ["oferta bloqueada pelo antifraude"]
    if disc < min_discount:
        return False, [f"desconto de {disc:.0f}% abaixo do mínimo de {min_discount:.0f}%"]
    if rating is not None and rating < min_rating:
        return False, [f"reputação {rating:.1f} abaixo de {min_rating:.1f}"]
    if sales is not None and sales < min_sales:
        return False, [f"apenas {sales} vendas"]
    # a nota da oferta já inclui desconto/reputação; a procura do produto soma até +20
    adj = score + appeal(offer)
    if adj < min_score:
        return False, [f"nota de curadoria {adj:.0f} abaixo de {min_score:.0f}"]

    if disc >= 40:
        reasons.append(f"desconto forte ({disc:.0f}%)")
    if offer.get("coupon_code"):
        reasons.append(f"cupom {offer['coupon_code']}")
    if rating and rating >= 4.7:
        reasons.append(f"vendedor bem avaliado ({rating:.1f})")
    if sales and sales >= 1000:
        reasons.append(f"{sales} vendas")
    if saving_brl(offer) >= 200:
        reasons.append(f"economia de R$ {saving_brl(offer):,.0f}".replace(",", "."))
    if appeal(offer) >= 5:
        reasons.append("produto com boa procura")
    return True, reasons or ["boa relação preço x reputação"]


def _brl(v) -> str:
    if v is None:
        return ""
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def deal_tags(offer: dict) -> list[str]:
    """Faixas chamativas em que a oferta se encaixa."""
    tags: list[str] = []
    disc = float(offer.get("discount_pct") or 0)
    price = float(offer.get("price") or 0)
    orig = float(offer.get("original_price") or 0)
    saving = max(0.0, orig - price) if orig and price else 0.0
    if price and price <= HOT_DEALS_MAX_PRICE and disc >= 20:
        tags.append("achados-do-dia")
    if disc >= LIGHTNING_MIN_DISCOUNT:
        tags.append("ofertas-relampago")
    if saving >= TOP_DEAL_MIN_SAVING or disc >= 45:
        tags.append("top-do-dia")
    if offer.get("coupon_code"):
        tags.append("com-cupom")
    if offer.get("seller_rating") and float(offer["seller_rating"]) >= 4.7 and disc >= 15:
        tags.append("melhor-avaliados")
    return tags


DEAL_LABELS = {
    "achados-do-dia": ("💡", "Achados do dia"),
    "ofertas-relampago": ("⚡", "Oferta relâmpago"),
    "top-do-dia": ("🏆", "Top do dia"),
    "com-cupom": ("🎟️", "Com cupom"),
    "melhor-avaliados": ("⭐", "Melhor avaliados"),
}


def post_text(offer: dict) -> str:
    """Mensagem pronta para o grupo (HTML do Telegram)."""
    def esc(t: str) -> str:
        return re.sub(r"[<>&]", lambda m: {"<": "&lt;", ">": "&gt;", "&": "&amp;"}[m.group(0)],
                      str(t or ""))

    cat = category_info(offer.get("category") or category_of(offer))
    tags = deal_tags(offer)
    head = f"{cat.get('emoji','✨')} <b>{esc(offer.get('title'))}</b>"
    lines = [head]
    meta = [cat["label"]]
    if tags and tags[0] in DEAL_LABELS:
        emoji, label = DEAL_LABELS[tags[0]]
        meta.append(f"{emoji} {label}")
    lines.append(" · ".join(meta))
    price = _brl(offer.get("price"))
    orig = _brl(offer.get("original_price"))
    disc = offer.get("discount_pct")
    if price:
        linha = f"💸 <b>{price}</b>"
        if orig:
            linha += f" <s>{orig}</s>"
        if disc:
            linha += f"  (-{float(disc):.0f}%)"
        lines.append(linha)
    if offer.get("coupon_code"):
        lines.append(f"🎟️ Cupom: <code>{esc(offer['coupon_code'])}</code>")
    if offer.get("seller_name"):
        rep = f" ({offer['seller_rating']:.1f}★)" if offer.get("seller_rating") else ""
        lines.append(f"🏪 {esc(offer['seller_name'])}{rep}")
    if offer.get("store_name"):
        lines.append(f"🛒 {esc(offer['store_name'])}")
    lines.append(f'👉 <a href="{esc(offer.get("affiliate_url") or offer.get("original_url"))}">'
                 "Pegar a oferta</a>")
    return "\n".join(lines)


def caption(offer: dict) -> str:
    return post_text(offer)

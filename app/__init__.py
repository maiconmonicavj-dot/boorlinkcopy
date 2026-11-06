"""Plataforma boorlinkcopy: copiador/conversor de links de afiliado."""
from __future__ import annotations

import os
import sys

from . import db, security
from .affiliate import KNOWN_STORES
from .config import OFFLINE_RECOVERY_HASH


def seed_stores() -> None:
    for slug, (name, domains, param) in KNOWN_STORES.items():
        if db.query_one("SELECT id FROM stores WHERE slug = ?", (slug,)):
            continue
        db.execute(
            """INSERT INTO stores(slug, name, domain, affiliate_param, affiliate_value,
                api_kind, min_rating, min_sales, active, created_at)
               VALUES(?,?,?,?,?,'manual',4.0,50,1,?)""",
            (slug, name, domains[0], param, "", security.now_iso()),
        )


def seed_demo_store() -> None:
    """Loja de demonstração com ofertas de exemplo (modo demonstração)."""
    if db.query_one("SELECT id FROM stores WHERE slug = 'demo'"):
        return
    sid = db.execute(
        """INSERT INTO stores(slug, name, domain, affiliate_param, affiliate_value, api_kind,
            api_base, collector_url, min_rating, min_sales, active, created_at)
           VALUES('demo','Loja Demo','demo.boorlinkcopy.com','tag','demo-20','manual',
                  NULL,NULL,4.2,100,1,?)""", (security.now_iso(),))
    samples = [
        {"title": "Fone Bluetooth ANC 40h de bateria", "price": 199.9, "original_price": 349.9,
         "image_url": "https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800&q=80",
         "url": "https://demo.boorlinkcopy.com/p/fone-anc",
         "seller_rating": 4.8, "seller_sales": 3200, "coupon_code": "FONE20",
         "comments": ["excelente custo beneficio"]},
        {"title": "Air Fryer 5L antiaderente 1500W", "price": 299.0, "original_price": 499.0,
         "image_url": "https://images.unsplash.com/photo-1626082927389-6cd097cdc6ec?w=800&q=80",
         "url": "https://demo.boorlinkcopy.com/p/airfryer-5l",
         "seller_rating": 4.6, "seller_sales": 1500, "coupon_code": "COZINHA10",
         "comments": ["chegou rapido"]},
        {"title": "PC Gamer Ryzen 5, RTX 4060, 16GB, SSD 1TB", "price": 4299.0,
         "original_price": 4899.0, "image_url": "",
         "url": "https://demo.boorlinkcopy.com/p/pc-gamer-rtx4060",
         "seller_rating": 4.7, "seller_sales": 830, "coupon_code": None,
         "comments": ["maquina otima"]},
        {"title": "Geladeira Frost Free Duplex 400L Inox", "price": 3199.0,
         "original_price": 3599.0, "image_url": "",
         "url": "https://demo.boorlinkcopy.com/p/geladeira-duplex-400",
         "seller_rating": 4.5, "seller_sales": 410, "coupon_code": "GELO100",
         "comments": []},
        {"title": "Ar-condicionado Split Inverter 12000 BTUs", "price": 1899.0,
         "original_price": 2199.0, "image_url": "",
         "url": "https://demo.boorlinkcopy.com/p/ar-split-12000",
         "seller_rating": 4.4, "seller_sales": 260, "coupon_code": None, "comments": []},
        {"title": "Jogo de Panelas Antiaderente 5 pecas", "price": 179.9,
         "original_price": 259.9, "image_url": "",
         "url": "https://demo.boorlinkcopy.com/p/panelas-5pecas",
         "seller_rating": 4.6, "seller_sales": 2100, "coupon_code": "PANELA15",
         "comments": []},
        {"title": "Ventilador de Coluna 40cm 6 pas", "price": 139.9,
         "original_price": 199.9, "image_url": "",
         "url": "https://demo.boorlinkcopy.com/p/ventilador-40cm",
         "seller_rating": 4.3, "seller_sales": 900, "coupon_code": None, "comments": []},
        {"title": "Smart TV 50\" 4K", "price": 1799.0, "original_price": 2599.0,
         "image_url": "", "url": "https://demo.boorlinkcopy.com/p/tv-50",
         "seller_rating": 3.1, "seller_sales": 12, "coupon_code": None,
         "comments": ["nao entregaram", "isso e um golpe, fraude"]},
    ]
    from . import robot
    store = dict(db.query_one("SELECT * FROM stores WHERE id = ?", (sid,)))
    for item in samples:
        robot.save_offer(store, item)


def ensure_offline_password(print_it: bool = False) -> str | None:
    """Define a senha offline de reativação (só na primeira execução)."""
    if db.get_setting(OFFLINE_RECOVERY_HASH):
        return None
    pwd = os.getenv("BOOR_OFFLINE_PASSWORD") or security.random_password(20)
    db.set_setting(OFFLINE_RECOVERY_HASH, security.hash_password(pwd))
    path = db.get_setting("offline_password_file")
    if not path:
        from .config import DATA_DIR

        path = str(DATA_DIR / "senha_offline.txt")
        db.set_setting("offline_password_file", path)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "SENHA OFFLINE DE REATIVACAO - boorlinkcopy\n"
                "Guarde fora do servidor. Use so para religar o sistema apos\n"
                "um desligamento de seguranca (tentativa de invasao).\n\n"
                f"{pwd}\n")
    except OSError:
        pass
    if print_it:
        print(f"[boorlinkcopy] Senha offline de reativacao: {pwd}")
        print(f"[boorlinkcopy] Salva em: {path}")
    return pwd


def bootstrap(verbose: bool = True) -> None:
    db.init_db()
    seed_stores()
    if os.getenv("BOOR_DEMO") == "1":
        seed_demo_store()
    ensure_offline_password(print_it=verbose)


def main() -> None:
    import uvicorn

    bootstrap(verbose=True)
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


__all__ = ["bootstrap", "main", "seed_stores", "ensure_offline_password"]

"""API da plataforma boorlinkcopy (FastAPI)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import affiliate, antifraud, auth, coupons, curation, db, images, robot, security, telegram
from .config import APP_NAME, DATA_DIR, SESSION_COOKIE

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="boorlinkcopy", version="1.0.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
_media_dir = DATA_DIR / "img"
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=_media_dir), name="media")


# --- helpers ------------------------------------------------------------------
def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def current_user(request: Request) -> dict:
    user = auth.session_user(request.cookies.get(SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    return user


def set_session(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=bool(os.getenv("BOOR_COOKIE_SECURE", "")), max_age=60 * 720,
        path="/",
    )


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Bloqueia tudo quando o sistema está desligado por segurança."""
    path = request.url.path
    if auth.is_locked() and not (path.startswith("/static") or path.startswith("/media")
                                 or path.startswith("/api/recover")
                                 or path.startswith("/api/status")):
        return JSONResponse(
            {"detail": "Sistema desligado por segurança. Reative com a senha offline.",
             "locked": True}, status_code=423)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# --- modelos ------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str


class VerifyIn(BaseModel):
    challenge: str
    code: str


class Setup2FAIn(BaseModel):
    email: str
    password: str


class Confirm2FAIn(BaseModel):
    email: str
    code: str


class RecoverIn(BaseModel):
    password: str


class ConvertIn(BaseModel):
    links: list[str] | str
    tag: str | None = None


class StoreIn(BaseModel):
    slug: str
    name: str
    domain: str
    affiliate_param: str = "tag"
    affiliate_value: str = ""
    api_kind: str = "manual"
    api_base: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    refresh_token: str | None = None
    collector_url: str | None = None
    min_rating: float = 4.0
    min_sales: int = 50


class CouponIn(BaseModel):
    store_id: int
    code: str | None = None
    title: str
    description: str | None = None
    url: str | None = None
    expires_at: str | None = None


# --- páginas ------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/status")
def status():
    return {
        "app": APP_NAME,
        "locked": auth.is_locked(),
        "locked_reason": db.get_setting("locked_reason", ""),
        "has_user": db.query_one("SELECT id FROM users LIMIT 1") is not None,
    }


# --- autenticação -------------------------------------------------------------
@app.post("/api/auth/register")
def register(body: LoginIn, request: Request):
    try:
        auth.create_user(body.email, body.password)
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "next": "setup_2fa"}


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    try:
        return auth.start_login(body.email, body.password, client_ip(request))
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


@app.post("/api/auth/setup-2fa")
def setup_2fa(body: Setup2FAIn):
    try:
        data = auth.begin_2fa_setup(body.email, body.password)
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    data["qr_svg"] = _qr_svg(data["otpauth_uri"])
    return data


def _qr_svg(text: str) -> str:
    """QR code em SVG (data URI) para escanear no autenticador."""
    import base64
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/svg+xml;base64,{b64}"


@app.post("/api/auth/confirm-2fa")
def confirm_2fa(body: Confirm2FAIn, request: Request):
    try:
        token = auth.confirm_2fa_setup(body.email, body.code, client_ip(request))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from exc
    resp = JSONResponse({"ok": True})
    set_session(resp, token)
    return resp


@app.post("/api/auth/verify")
def verify(body: VerifyIn, request: Request):
    try:
        token = auth.verify_2fa(body.challenge, body.code, client_ip(request),
                                request.headers.get("user-agent"))
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    resp = JSONResponse({"ok": True})
    set_session(resp, token)
    return resp


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.logout(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"], "id": user["user_id"]}


# --- recuperação (senha offline) ----------------------------------------------
@app.post("/api/recover")
def recover(body: RecoverIn, request: Request):
    try:
        ok = auth.unlock_with_offline_password(body.password, client_ip(request))
    except auth.AuthError as exc:
        raise HTTPException(403, str(exc)) from exc
    if not ok:
        raise HTTPException(401, "Senha offline incorreta.")
    return {"ok": True}


# --- conversão de links -------------------------------------------------------
@app.post("/api/convert")
def convert_links(body: ConvertIn, user: dict = Depends(current_user)):
    links = body.links
    if isinstance(links, str):
        links = [l for l in links.replace(",", "\n").splitlines() if l.strip()]
    return {"results": affiliate.convert_many(links, body.tag)}


# --- ofertas ------------------------------------------------------------------
@app.get("/api/offers")
def list_offers(status: str = "approved", store: str | None = None,
                q: str | None = None, category: str | None = None,
                deal: str | None = None, limit: int = 60,
                user: dict = Depends(current_user)):
    sql = ("SELECT o.*, s.name AS store_name, s.slug AS store_slug FROM offers o"
           " JOIN stores s ON s.id = o.store_id WHERE o.status = ?")
    params: list = [status]
    if category:
        sql += " AND o.category = ?"
        params.append(category)
    if store:
        sql += " AND s.slug = ?"
        params.append(store)
    if q:
        sql += " AND (o.title LIKE ? OR o.coupon_code LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY o.score DESC, o.id DESC LIMIT ?"
    params.append(min(limit, 200))
    rows = [dict(r) for r in db.query(sql, params)]
    for r in rows:
        if not r.get("category"):
            r["category"] = curation.category_of(r)
        r["deals"] = curation.deal_tags(r)
        r["category_label"] = curation.category_info(r["category"])["label"]
        coupons.attach_coupon(r)
    if deal:
        rows = [r for r in rows if deal in r["deals"]]
    return {"offers": rows}


@app.get("/api/categories")
def categories(user: dict = Depends(current_user)):
    """Menu de categorias com contagem de ofertas aprovadas."""
    counts: dict[str, int] = {}
    for row in db.query("SELECT title, description, category FROM offers WHERE status = 'approved'"):
        cat = row["category"] or curation.category_of(dict(row))
        counts[cat] = counts.get(cat, 0) + 1
    out = [{"slug": slug, "label": cfg["label"], "emoji": cfg["emoji"],
            "min_discount": cfg["min_discount"], "count": counts.get(slug, 0)}
           for slug, cfg in curation.CATEGORIES.items()]
    out.sort(key=lambda c: (-c["count"], c["label"]))
    return {"categories": out}


@app.get("/api/deals")
def deals(user: dict = Depends(current_user)):
    """Menus chamativos: achados do dia, relâmpago, top do dia, com cupom, melhor avaliados."""
    rows = [dict(r) for r in db.query(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id"
        " WHERE o.status = 'approved' ORDER BY o.score DESC LIMIT 400")]
    out = {key: [] for key in curation.DEAL_LABELS}
    for r in rows:
        if not r.get("category"):
            r["category"] = curation.category_of(r)
        tags = curation.deal_tags(r)
        for t in tags:
            if t in out:
                out[t].append({"id": r["id"], "title": r["title"], "price": r["price"],
                               "original_price": r["original_price"],
                               "discount_pct": r["discount_pct"], "image_url": r["image_url"],
                               "store_name": r["store_name"]})
    return {"deals": out, "labels": {k: list(v) for k, v in curation.DEAL_LABELS.items()}}


@app.get("/api/offers/{offer_id}/go")
def go_to_offer(offer_id: int):
    """Redireciona direto para a oferta já com a tag de afiliado."""
    row = db.query_one("SELECT * FROM offers WHERE id = ?", (offer_id,))
    if not row:
        raise HTTPException(404, "Oferta não encontrada.")
    target = row["affiliate_url"] or row["original_url"]
    if not target or target == row["original_url"]:
        conv = affiliate.convert(row["original_url"])
        target = conv.get("affiliate_url") or target
    from fastapi.responses import RedirectResponse
    return RedirectResponse(target, status_code=302)


@app.post("/api/offers/{offer_id}/status")
def change_offer_status(offer_id: int, status: str, user: dict = Depends(current_user)):
    if status not in ("approved", "blocked", "pending"):
        raise HTTPException(400, "Status inválido.")
    db.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer_id))
    return {"ok": True}


@app.post("/api/images/backfill")
def images_backfill(user: dict = Depends(current_user)):
    """Busca a foto real do produto nos links das ofertas sem imagem."""
    return images.backfill()


@app.post("/api/offers/{offer_id}/refresh-image")
def refresh_image(offer_id: int, user: dict = Depends(current_user)):
    row = db.query_one(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id"
        " WHERE o.id = ?", (offer_id,))
    if not row:
        raise HTTPException(404, "Oferta não encontrada.")
    url = images.resolve(dict(row), row["store_name"])
    db.execute("UPDATE offers SET image_url = ? WHERE id = ?", (url, offer_id))
    return {"ok": True, "image_url": url}


# --- cupons -------------------------------------------------------------------
@app.get("/api/coupons")
def list_coupons(store_id: int | None = None, user: dict = Depends(current_user)):
    return {"coupons": coupons.list_active(store_id)}


@app.post("/api/coupons")
def create_coupon(body: CouponIn, user: dict = Depends(current_user)):
    cid = coupons.save_coupon(body.store_id, body.code, body.title, body.description,
                              body.url, body.expires_at)
    return {"ok": True, "id": cid}


# --- lojas --------------------------------------------------------------------
def _store_out(row: dict) -> dict:
    out = dict(row)
    for k in ("api_key_enc", "api_secret_enc", "refresh_token_enc"):
        out[k.replace("_enc", "_set")] = bool(out.pop(k, None))
    return out


@app.get("/api/stores")
def list_stores(user: dict = Depends(current_user)):
    return {"stores": [_store_out(dict(r)) for r in db.query("SELECT * FROM stores ORDER BY name")]}


@app.post("/api/stores")
def upsert_store(body: StoreIn, user: dict = Depends(current_user)):
    existing = db.query_one("SELECT * FROM stores WHERE slug = ?", (body.slug,))
    data = body.model_dump()
    enc = lambda v: security.encrypt(v) if v else None  # noqa: E731
    if existing:
        db.execute(
            """UPDATE stores SET name=?, domain=?, affiliate_param=?, affiliate_value=?,
               api_kind=?, api_base=?, collector_url=?, min_rating=?, min_sales=?,
               api_key_enc=COALESCE(?, api_key_enc),
               api_secret_enc=COALESCE(?, api_secret_enc),
               refresh_token_enc=COALESCE(?, refresh_token_enc)
               WHERE id=?""",
            (data["name"], data["domain"], data["affiliate_param"], data["affiliate_value"],
             data["api_kind"], data["api_base"], data["collector_url"], data["min_rating"],
             data["min_sales"], enc(data["api_key"]), enc(data["api_secret"]),
             enc(data["refresh_token"]), existing["id"]))
        if data["refresh_token"]:
            db.execute("UPDATE stores SET token_expires_at = NULL WHERE id = ?",
                       (existing["id"],))
        return {"ok": True, "id": existing["id"], "updated": True}

    sid = db.execute(
        """INSERT INTO stores(slug, name, domain, affiliate_param, affiliate_value, api_kind,
            api_base, api_key_enc, api_secret_enc, refresh_token_enc, token_expires_at,
            collector_url, min_rating, min_sales, active, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
        (body.slug, body.name, body.domain, body.affiliate_param, body.affiliate_value,
         body.api_kind, body.api_base, enc(body.api_key), enc(body.api_secret),
         enc(body.refresh_token), None, body.collector_url, body.min_rating,
         body.min_sales, security.now_iso()))
    return {"ok": True, "id": sid, "updated": False}


@app.post("/api/stores/{slug}/refresh-token")
def refresh_token(slug: str, user: dict = Depends(current_user)):
    row = db.query_one("SELECT * FROM stores WHERE slug = ?", (slug,))
    if not row:
        raise HTTPException(404, "Loja não encontrada.")
    token = robot.refresh_access_token(dict(row))
    if not token:
        raise HTTPException(400, "Não foi possível renovar o token (verifique credenciais).")
    return {"ok": True, "expires_at": db.query_one(
        "SELECT token_expires_at FROM stores WHERE id = ?", (row["id"],))["token_expires_at"]}


# --- robô ---------------------------------------------------------------------
@app.post("/api/robot/run")
def robot_run(store: str | None = None, user: dict = Depends(current_user)):
    return robot.run_cycle(store)


@app.get("/api/robot/runs")
def robot_runs(user: dict = Depends(current_user)):
    return {"runs": robot.last_runs()}


# --- telegram (postagem no grupo) --------------------------------------------
class TelegramIn(BaseModel):
    token: str | None = None
    chat_id: str | None = None


@app.get("/api/telegram")
def telegram_status(user: dict = Depends(current_user)):
    return {
        "configured": telegram.configured(),
        "chat_id": db.get_setting("telegram_chat_id") or "",
        "pending": len(telegram.pending_offers()),
        "criteria": curation.criteria(),
    }


@app.post("/api/telegram")
def telegram_setup(body: TelegramIn, user: dict = Depends(current_user)):
    telegram.set_config(body.token, body.chat_id)
    return {"ok": True, "configured": telegram.configured()}


@app.post("/api/telegram/test")
def telegram_test(user: dict = Depends(current_user)):
    return telegram.test()


@app.post("/api/telegram/publish")
def telegram_publish(limit: int = 6, user: dict = Depends(current_user)):
    return telegram.publish_pending(max_posts=limit)


@app.get("/api/telegram/preview")
def telegram_preview(offer_id: int, user: dict = Depends(current_user)):
    row = db.query_one(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id"
        " WHERE o.id = ?", (offer_id,))
    if not row:
        raise HTTPException(404, "Oferta não encontrada.")
    offer = dict(row)
    ok, reasons = curation.worth(offer)
    return {"text": curation.post_text(offer), "worth": ok, "reasons": reasons}


# --- critérios de curadoria ---------------------------------------------------
class CriteriaIn(BaseModel):
    min_discount: float | None = None
    min_score: float | None = None
    min_rating: float | None = None
    min_sales: int | None = None
    max_posts: int | None = None
    post_interval: int | None = None
    hot_keywords: str | None = None
    hot_blocked: str | None = None
    caution_keywords: str | None = None
    risk_terms: str | None = None


@app.get("/api/criteria")
def get_criteria(user: dict = Depends(current_user)):
    return {
        "criteria": curation.criteria(),
        "hot_default": sorted(curation.HOT_KEYWORDS),
        "caution_default": curation.CAUTION_KEYWORDS,
        "hot_custom": db.get_setting("hot_keywords", "") or "",
        "hot_blocked": db.get_setting("hot_blocked", "") or "",
        "caution_custom": db.get_setting("caution_keywords", "") or "",
        "risk_terms": db.get_setting("risk_terms", "") or "",
    }


@app.post("/api/criteria")
def set_criteria(body: CriteriaIn, user: dict = Depends(current_user)):
    data = body.model_dump()
    texts = {k: data.pop(k) for k in
             ("hot_keywords", "hot_blocked", "caution_keywords", "risk_terms")}
    crit = curation.save_criteria(**data)
    for key, val in texts.items():
        if val is not None:
            db.set_setting(key, val.strip())
    # recalcula a nota das ofertas guardadas com a nova régua
    rows = db.query("SELECT o.*, s.min_rating AS s_rating, s.min_sales AS s_sales"
                    " FROM offers o JOIN stores s ON s.id = o.store_id")
    for row in rows:
        o = dict(row)
        v = antifraud.evaluate(o, {"min_rating": o.get("s_rating") or 4.0,
                                   "min_sales": o.get("s_sales") or 50})
        db.execute("UPDATE offers SET score = ?, status = ?, block_reason = ? WHERE id = ?",
                   (v["score"], v["status"], "; ".join(v["reasons"]) or None, o["id"]))
    return {"ok": True, "criteria": crit}


@app.post("/api/criteria/preview")
def preview_criteria(body: CriteriaIn, user: dict = Depends(current_user)):
    """Testa critérios sem salvar: quantas ofertas aprovadas passariam."""
    import copy

    saved = curation.criteria()
    saved.update({k: v for k, v in body.model_dump().items() if v is not None})
    rows = [dict(r) for r in db.query(
        "SELECT o.*, s.name AS store_name FROM offers o JOIN stores s ON s.id = o.store_id")]
    original = curation.criteria
    try:
        curation.criteria = lambda: copy.deepcopy(saved)  # type: ignore[assignment]
        passed = [o for o in rows if curation.worth(o)[0]]
        blocked = [o for o in rows if not curation.worth(o)[0]]
    finally:
        curation.criteria = original  # type: ignore[assignment]
    return {
        "pass": len(passed), "fail": len(blocked), "total": len(rows),
        "examples_pass": [o["title"][:60] for o in passed[:5]],
        "examples_fail": [[o["title"][:60], curation.worth(o)[1]] for o in blocked[:5]],
    }


# --- antifraude / segurança ---------------------------------------------------
class RiskIn(BaseModel):
    comments: list[str] | str | None = None
    seller_rating: float | None = None
    seller_sales: int | None = None


@app.post("/api/antifraud/check")
def check_risk(body: RiskIn, user: dict = Depends(current_user)):
    return antifraud.evaluate(body.model_dump(), {"min_rating": 4.0, "min_sales": 50})


@app.get("/api/security/events")
def events(user: dict = Depends(current_user)):
    return {"events": auth.recent_events(80), "locked": auth.is_locked()}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    q1 = lambda sql, p=(): (db.query_one(sql, p) or {"n": 0})["n"]  # noqa: E731
    return {
        "offers": q1("SELECT COUNT(*) n FROM offers WHERE status='approved'"),
        "blocked": q1("SELECT COUNT(*) n FROM offers WHERE status='blocked'"),
        "coupons": q1("SELECT COUNT(*) n FROM coupons WHERE active=1"),
        "stores": q1("SELECT COUNT(*) n FROM stores WHERE active=1"),
        "alerts": q1("SELECT COUNT(*) n FROM security_events WHERE severity != 'info'"),
        "last_run": (robot.last_runs(1) or [None])[0],
    }

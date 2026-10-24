from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    AlertEvent,
    FetchJob,
    MatchIssue,
    Offer,
    PriceAlert,
    PriceObservation,
    Product,
    Provider,
    ProviderError,
    WatchlistItem,
)
from app.pricing.offers import aware
from app.providers.registry import UNSUPPORTED_SOURCES
from app.matching.attributes import extract_attributes
from app.services.catalog import RANGES, CatalogService, _iso, normalize_query

router = APIRouter(prefix="/api")

CATEGORIES = [
    ("smartphones", "Smartphones"), ("laptops", "Laptops"), ("tablets", "Tablets"), ("smartwatches", "Smartwatches"),
    ("headphones", "Headphones & Earbuds"), ("speakers", "Speakers"), ("televisions", "Televisions"),
    ("monitors", "Monitors"), ("components", "Computer Components"), ("keyboards_mice", "Keyboards & Mice"),
    ("cameras", "Cameras"), ("gaming_consoles", "Gaming Consoles"), ("printers", "Printers"),
    ("networking", "Networking"), ("storage", "Storage Devices"), ("accessories", "Chargers & Accessories"),
    ("other", "Other Electronics"),
]


def catalog(request: Request) -> CatalogService:
    return request.app.state.catalog


def client_id(x_client_id: str = Header(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")) -> str:
    return x_client_id


def http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def demo_on(request: Request) -> bool:
    """Viewer switched on Demo mode (simulated history for products with little real data). Never affects stored data."""
    return request.headers.get("x-buywise-demo") == "1"


def get_product_or_404(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise http_error(404, "product_not_found", f"No product with id {product_id}.")
    return p


# ------------------------------------------------------------------ health
@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict:
    cat: CatalogService = request.app.state.catalog
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:  # noqa: BLE001
        database = f"error: {type(exc).__name__}"
    configured = [p.id for p in cat.registry.configured()]
    recent = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = {r.id: r for r in db.scalars(select(Provider))} if database == "ok" else {}
    verified_recently = [pid for pid in configured if rows.get(pid) and rows[pid].last_success_at and aware(rows[pid].last_success_at) >= recent]
    if not configured:
        live = "not_configured"
    elif verified_recently:
        live = "operational"
    elif any(rows.get(pid) and rows[pid].last_failure_at for pid in configured):
        live = "degraded"
    else:
        live = "unverified"  # credentials present but no successful fetch observed yet
    return {
        "app": "ok",
        "database": database,
        "live_price_fetching": live,
        "configured_providers": configured,
        "providers_with_success_last_24h": verified_recently,
        "scheduler_running": request.app.state.scheduler.running,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/providers/status")
def providers_status(request: Request, db: Session = Depends(get_db)) -> dict:
    cat: CatalogService = request.app.state.catalog
    rows = {r.id: r for r in db.scalars(select(Provider))}
    now = datetime.now(timezone.utc)
    out = []
    for p in cat.registry.providers:
        r = rows.get(p.id)
        cooling = bool(r and r.cooldown_until and aware(r.cooldown_until) > now)
        if not p.is_configured():
            state = "not_configured"
        elif cooling:
            state = "cooling_down"
        elif r and r.last_success_at and (not r.last_failure_at or aware(r.last_success_at) >= aware(r.last_failure_at)):
            state = "working"
        elif r and r.last_failure_at:
            state = "failing"
        else:
            state = "configured_untested"
        out.append({
            "id": p.id, "name": p.display_name, "source_type": p.source_type, "state": state,
            "configured": p.is_configured(), "required_env": list(p.credential_env), "docs_url": p.docs_url,
            "last_success_at": _iso(r.last_success_at) if r else None,
            "last_failure_at": _iso(r.last_failure_at) if r else None,
            "last_error": r.last_error if r else None,
            "cooldown_until": _iso(r.cooldown_until) if cooling else None,
        })
    return {"providers": out, "unsupported_sources": UNSUPPORTED_SOURCES}


@router.get("/categories")
def categories(db: Session = Depends(get_db)) -> dict:
    counts = dict(db.execute(select(Product.category, func.count(Product.id)).group_by(Product.category)).all())
    return {"categories": [{"id": k, "name": v, "tracked_products": counts.get(k, 0)} for k, v in CATEGORIES]}


# ------------------------------------------------------------------ search
SortKey = Literal["relevance", "price_asc", "price_desc", "offers"]


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=120),
    category: str | None = Query(None, max_length=40),
    brand: list[str] = Query(default_factory=list),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    storage_gb: int | None = Query(None, ge=1),
    ram_gb: int | None = Query(None, ge=1),
    condition: Literal["new", "refurbished", "any"] = "new",
    include_accessories: bool = False,
    all_stores: bool = False,
    sort: SortKey = "relevance",
    page: int = Query(1, ge=1, le=50),
    page_size: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    if len(normalize_query(q)) < 2:
        raise http_error(422, "invalid_query", "Please enter at least two letters or digits.")
    res = await catalog(request).search(db, q)
    items = res["products"]
    facets = {
        "brands": sorted({p["brand"] for p in items if p["brand"]}),
        "categories": sorted({p["category"] for p in items}),
        "storage_gb": sorted({p["storage_gb"] for p in items if p["storage_gb"]}),
        "ram_gb": sorted({p["ram_gb"] for p in items if p["ram_gb"]}),
    }
    if category:
        items = [p for p in items if p["category"] == category]
    if brand:
        wanted = {b.lower() for b in brand}
        items = [p for p in items if (p["brand"] or "").lower() in wanted]
    if condition != "any":
        items = [p for p in items if p["condition"] == condition]
    # Device searches show devices only; cases/skins/chargers etc. are hidden unless asked for.
    hidden_accessories = 0
    if not include_accessories and extract_attributes(normalize_query(q)).kind == "device":
        before = len(items)
        items = [p for p in items if p["category"] != "accessories"]
        hidden_accessories = before - len(items)
    # By default only products sold by at least one trusted store are listed.
    hidden_untrusted = 0
    if not all_stores and catalog(request).settings.trusted_only:
        before = len(items)
        items = [p for p in items if p["trusted_offer_count"] > 0]
        hidden_untrusted = before - len(items)
    if storage_gb:
        items = [p for p in items if p["storage_gb"] == storage_gb]
    if ram_gb:
        items = [p for p in items if p["ram_gb"] == ram_gb]
    if min_price is not None:
        items = [p for p in items if p["best_price"] is not None and p["best_price"] >= min_price]
    if max_price is not None:
        items = [p for p in items if p["best_price"] is not None and p["best_price"] <= max_price]
    big = float("inf")
    if sort == "price_asc":
        items.sort(key=lambda p: p["best_price"] if p["best_price"] is not None else big)
    elif sort == "price_desc":
        items.sort(key=lambda p: -(p["best_price"] or -1))
    elif sort == "offers":
        items.sort(key=lambda p: -p["verified_offer_count"])
    else:
        items.sort(key=lambda p: -p["relevance"])
    total = len(items)
    start = (page - 1) * page_size
    return {**{k: v for k, v in res.items() if k != "products"}, "facets": facets, "total": total, "page": page,
            "hidden_accessories": hidden_accessories, "hidden_untrusted": hidden_untrusted,
            "page_size": page_size, "results": items[start:start + page_size]}


@router.get("/suggestions")
def suggestions(q: str = Query(..., min_length=1, max_length=60), db: Session = Depends(get_db)) -> dict:
    like = f"%{normalize_query(q)}%"
    rows = db.scalars(select(Product.title).where(func.lower(Product.title).like(like)).order_by(Product.view_count.desc()).limit(8)).all()
    return {"suggestions": [r.split(":")[0][:90] for r in rows]}


@router.get("/home")
def home(request: Request, db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    recent = db.scalars(select(Product).where(Product.last_refreshed_at.is_not(None)).order_by(Product.last_refreshed_at.desc()).limit(8)).all()
    popular = db.scalars(select(Product).where(Product.view_count > 0).order_by(Product.view_count.desc()).limit(8)).all()
    deals = []
    for p in db.scalars(select(Product).join(Offer).where(Offer.mrp.is_not(None)).distinct().limit(60)):
        s = cat.product_summary(p)
        best = next((o for o in p.offers if s["best_price"] is not None and o.price == s["best_price"] and o.mrp), None)
        if best and best.mrp and s["best_freshness"] in ("live", "cached") and best.mrp > best.price:
            deals.append({**s, "mrp": best.mrp, "discount_pct": round((best.mrp - best.price) / best.mrp * 100, 1)})
    deals.sort(key=lambda d: -d["discount_pct"])
    return {
        "recently_tracked": [cat.product_summary(p) for p in recent],
        "popular": [cat.product_summary(p) for p in popular],
        "verified_deals": deals[:8],
        "deals_note": "Discounts are computed only from the retailer-reported MRP and a current verified price.",
    }


# ------------------------------------------------------------------ products
@router.get("/products/{product_id}")
async def product_detail(request: Request, product_id: int, include_refurbished: bool = False, db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    p = get_product_or_404(db, product_id)
    p.view_count = (p.view_count or 0) + 1
    p.last_viewed_at = datetime.now(timezone.utc)
    db.commit()
    scheduled = False
    if cat.needs_refresh(p):
        scheduled = cat.schedule_refresh(p.id, "view")
    data = cat.product_detail(db, p, include_refurbished, demo=demo_on(request))
    data["refresh_in_progress"] = data["refresh_in_progress"] or scheduled
    data["affiliate_disclosure"] = cat.settings.affiliate_disclosure
    return data


@router.get("/products/{product_id}/offers")
def product_offers(
    request: Request,
    product_id: int,
    sort: Literal["top_stores", "price_asc", "price_desc", "recent", "retailer", "availability"] = "top_stores",
    include_refurbished: bool = False,
    all_stores: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    cat = catalog(request)
    p = get_product_or_404(db, product_id)
    offers = cat.product_detail(db, p, include_refurbished)["offers"]
    hidden_untrusted = 0
    if not all_stores and cat.settings.trusted_only:
        hidden_untrusted = sum(1 for o in offers if not o["trusted_store"])
        offers = [o for o in offers if o["trusted_store"]]
    if not include_refurbished:
        offers = [o for o in offers if o["condition"] == "new" or p.condition != "new"]
    big = float("inf")
    keyf = {
        # Flipkart, Reliance Digital, Amazon, Vijay Sales, Croma first (cheapest of them on top), then other stores by price
        "top_stores": lambda o: (0 if o["preferred_rank"] is not None else 1,
                                 o["price"] if o["price"] is not None else big),
        "price_asc": lambda o: (o["price"] if o["price"] is not None else big),
        "price_desc": lambda o: -(o["price"] or 0),
        "recent": lambda o: -(datetime.fromisoformat(o["last_verified_at"]).timestamp() if o["last_verified_at"] else 0),
        "retailer": lambda o: (o["retailer"] or "").lower(),
        "availability": lambda o: {"in_stock": 0, "preorder": 1, "unknown": 2, "out_of_stock": 3}.get(o["availability"], 2),
    }[sort]
    offers.sort(key=keyf)
    return {"product_id": product_id, "sort": sort, "offers": offers, "hidden_untrusted": hidden_untrusted}


@router.get("/products/{product_id}/final-price")
def product_final_price(request: Request, product_id: int, banks: list[str] = Query(default_factory=list),
                        coupons: bool = False, db: Session = Depends(get_db)) -> dict:
    """True Final Price for each trusted store. `banks` = cards the shopper holds (e.g. banks=HDFC&banks=ICICI)."""
    cat = catalog(request)
    p = get_product_or_404(db, product_id)
    offers = cat.product_detail(db, p)["offers"]
    from app.pricing.final_price import compute
    return compute(offers, {b.strip() for b in banks if b.strip()}, coupons)


@router.get("/products/{product_id}/history")
def product_history(request: Request, product_id: int, range: Literal["7d", "30d", "90d", "180d", "365d"] = "30d",  # noqa: A002
                    db: Session = Depends(get_db)) -> dict:
    if range not in RANGES:
        raise http_error(422, "invalid_range", "Unsupported range.")
    p = get_product_or_404(db, product_id)
    return catalog(request).history(db, p, range, demo=demo_on(request))


@router.post("/products/{product_id}/refresh")
async def product_refresh(request: Request, product_id: int, db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    get_product_or_404(db, product_id)
    if not cat.registry.configured():
        raise http_error(503, "no_providers_configured", "No price providers are configured on the server, so prices cannot be refreshed.")
    return await cat.refresh_product(product_id, "manual")


# ------------------------------------------------------------------ watchlist
class WatchIn(BaseModel):
    product_id: int = Field(..., ge=1)


@router.post("/watchlist", status_code=201)
def add_watch(body: WatchIn, request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    p = get_product_or_404(db, body.product_id)
    existing = db.scalar(select(WatchlistItem).where(WatchlistItem.client_id == cid, WatchlistItem.product_id == p.id))
    if existing is None:
        existing = WatchlistItem(client_id=cid, product_id=p.id, price_when_added=cat.product_summary(p)["best_price"])
        db.add(existing)
        db.commit()
    return {"id": existing.id, "product_id": p.id}


@router.delete("/watchlist/{product_id}", status_code=204)
def remove_watch(product_id: int, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> None:
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.client_id == cid, WatchlistItem.product_id == product_id))
    if item:
        db.delete(item)
        db.commit()


@router.get("/watchlist")
def list_watch(request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    out = []
    for w in db.scalars(select(WatchlistItem).where(WatchlistItem.client_id == cid).order_by(WatchlistItem.created_at.desc())):
        s = cat.product_summary(w.product)
        hist_min = db.scalar(select(func.min(PriceObservation.price)).where(
            PriceObservation.product_id == w.product_id, PriceObservation.verification_status == "verified"))
        alert = db.scalar(select(PriceAlert).where(PriceAlert.client_id == cid, PriceAlert.product_id == w.product_id))
        change = (s["best_price"] - w.price_when_added) if (s["best_price"] is not None and w.price_when_added) else None
        out.append({**s, "added_at": _iso(w.created_at), "price_when_added": w.price_when_added, "price_change": change,
                    "historical_min": hist_min,
                    "alert": {"id": alert.id, "target_price": alert.target_price, "active": alert.active} if alert else None})
    return {"items": out}


# ------------------------------------------------------------------ alerts
class AlertIn(BaseModel):
    product_id: int = Field(..., ge=1)
    target_price: float = Field(..., gt=0, lt=10_000_000)
    channel: Literal["in_app", "email"] = "in_app"
    email: EmailStr | None = None

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.lower() if v else v


@router.post("/alerts", status_code=201)
def create_alert(body: AlertIn, request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    get_product_or_404(db, body.product_id)
    if body.channel == "email" and not body.email:
        raise http_error(422, "email_required", "An e-mail address is required for e-mail alerts.")
    alert = db.scalar(select(PriceAlert).where(PriceAlert.client_id == cid, PriceAlert.product_id == body.product_id))
    if alert is None:
        alert = PriceAlert(client_id=cid, product_id=body.product_id, target_price=body.target_price)
        db.add(alert)
    alert.target_price = body.target_price
    alert.channel = body.channel
    alert.email = body.email
    alert.active = True
    alert.armed = True
    db.commit()
    s = cat.settings
    email_ready = bool(s.smtp_host and s.smtp_from)
    from app.services.alerts import evaluate_alerts
    evaluate_alerts(db, cat, body.product_id)
    return {"id": alert.id, "delivery_note": None if body.channel == "in_app" or email_ready else
            "E-mail delivery is not configured on this server; the alert will be recorded in-app only."}


@router.get("/alerts")
def list_alerts(cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    out = []
    for a in db.scalars(select(PriceAlert).where(PriceAlert.client_id == cid).order_by(PriceAlert.created_at.desc())):
        events = sorted(a.events, key=lambda e: e.created_at, reverse=True)[:10]
        out.append({
            "id": a.id, "product_id": a.product_id, "product_title": a.product.title, "image_url": a.product.image_url,
            "target_price": a.target_price, "channel": a.channel, "email": a.email, "active": a.active,
            "armed": a.armed, "created_at": _iso(a.created_at),
            "events": [{"triggered_price": e.triggered_price, "retailer": e.retailer_name, "offer_url": e.offer_url,
                        "delivery_status": e.delivery_status, "delivery_error": e.delivery_error,
                        "created_at": _iso(e.created_at)} for e in events],
        })
    return {"alerts": out}


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: int, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> None:
    a = db.get(PriceAlert, alert_id)
    if a is None or a.client_id != cid:
        raise http_error(404, "alert_not_found", "Alert not found.")
    db.delete(a)
    db.commit()


# ------------------------------------------------------------------ admin
def require_admin(request: Request, authorization: str | None = Header(None)) -> None:
    token = request.app.state.settings.admin_token
    if not token:
        raise http_error(503, "admin_disabled", "Diagnostics are disabled. Set ADMIN_TOKEN in backend/.env to enable them.")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, token):
        raise http_error(401, "unauthorized", "Invalid admin token.")


@router.get("/admin/diagnostics", dependencies=[Depends(require_admin)])
def diagnostics(request: Request, db: Session = Depends(get_db)) -> dict:
    cat = catalog(request)
    sched = request.app.state.scheduler
    now = datetime.now(timezone.utc)
    offers = db.scalars(select(Offer)).all()
    fresh_counts: dict[str, int] = {}
    for o in offers:
        f = cat.offer_view(o).freshness
        fresh_counts[f] = fresh_counts.get(f, 0) + 1
    return {
        "providers": providers_status(request, db)["providers"],
        "recent_errors": [{"provider": e.provider_id, "kind": e.kind, "message": e.message, "http_status": e.http_status,
                           "context": e.context, "at": _iso(e.created_at)}
                          for e in db.scalars(select(ProviderError).order_by(ProviderError.created_at.desc()).limit(30))],
        "recent_jobs": [{"kind": j.kind, "trigger": j.trigger, "target": j.target, "status": j.status, "detail": j.detail,
                         "started_at": _iso(j.started_at), "finished_at": _iso(j.finished_at)}
                        for j in db.scalars(select(FetchJob).order_by(FetchJob.started_at.desc()).limit(30))],
        "match_issues": [{"provider": m.provider_id, "listing_title": m.listing_title, "candidate_product_id": m.candidate_product_id,
                          "confidence": m.confidence, "reason": m.reason, "at": _iso(m.created_at)}
                         for m in db.scalars(select(MatchIssue).order_by(MatchIssue.created_at.desc()).limit(30))],
        "scheduler": {"enabled": cat.settings.scheduler_enabled, "running": sched.running, "ticks": sched.ticks,
                      "last_tick_at": _iso(sched.last_tick_at), "last_tick_refreshed": sched.last_tick_refreshed,
                      "last_error": sched.last_error, "background_refreshes": len(cat.background)},
        "freshness": fresh_counts,
        "email": {"configured": bool(cat.settings.smtp_host and cat.settings.smtp_from), "host": cat.settings.smtp_host,
                  "port": cat.settings.smtp_port, "from": cat.settings.smtp_from},
        "counts": {"products": db.scalar(select(func.count(Product.id))), "offers": len(offers),
                   "observations": db.scalar(select(func.count(PriceObservation.id))),
                   "alert_events": db.scalar(select(func.count(AlertEvent.id)))},
        "time": now.isoformat(),
    }


class TestEmailIn(BaseModel):
    email: EmailStr


@router.post("/admin/test-email", dependencies=[Depends(require_admin)])
def test_email(body: TestEmailIn, request: Request) -> dict:
    """Admin only: send one test e-mail to check the SMTP settings in backend/.env."""
    from app.services.mailer import send_email
    status, error = send_email(catalog(request).settings, str(body.email), "BuyWise test e-mail",
                               "This is a test e-mail from your BuyWise server. Price alerts and Regret Shield "
                               "notifications will arrive like this.\n")
    return {"status": status, "error": error}


@router.post("/admin/scheduler/tick", dependencies=[Depends(require_admin)])
async def run_tick(request: Request) -> dict:
    ids = await request.app.state.scheduler.tick()
    return {"refreshed_product_ids": ids}

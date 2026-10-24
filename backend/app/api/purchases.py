"""Regret Shield API. Every purchase route is scoped to the caller's X-Client-Id; other clients get 404."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import client_id, demo_on, get_product_or_404, http_error
from app.database.session import get_db
from app.models import PurchaseCheck, PurchaseNotification, TrackedPurchase
from app.pricing.offers import aware
from app.regret.service import IST, RegretService, today_ist
from app.services.catalog import _iso
from app.services.mailer import email_configured

router = APIRouter(prefix="/api")
REF_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_/#. ")


def regret(request: Request) -> RegretService:
    return request.app.state.regret


def _to_dt(d: date | None) -> datetime | None:
    return datetime.combine(d, time(12, 0), tzinfo=IST).astimezone(timezone.utc) if d else None


def _clean_ref(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if len(v) > 100 or not set(v) <= REF_CHARS:
        raise ValueError("Order reference may only contain letters, digits, spaces and - _ / # .")
    return v


class PurchaseBase(BaseModel):
    retailer: str = Field(..., min_length=1, max_length=120)
    purchase_price: float = Field(..., gt=0, lt=100_000_000)
    purchase_date: date
    order_ref: str | None = None
    return_deadline: date | None = None
    protection_deadline: date | None = None
    expected_costs: float | None = Field(None, ge=0, lt=100_000_000)
    notify: bool = True
    email: EmailStr | None = None   # optional: also e-mail this purchase's alerts

    _ref = field_validator("order_ref")(classmethod(lambda cls, v: _clean_ref(v)))

    @model_validator(mode="after")
    def _dates(self):  # noqa: ANN202
        if self.purchase_date > today_ist() + timedelta(days=1):
            raise ValueError("Purchase date can't be in the future.")
        for name in ("return_deadline", "protection_deadline"):
            d = getattr(self, name)
            if d is not None and d < self.purchase_date:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} can't be before the purchase date.")
        return self


class PurchaseIn(PurchaseBase):
    product_id: int = Field(..., ge=1)


class PurchasePatch(BaseModel):
    retailer: str | None = Field(None, min_length=1, max_length=120)
    purchase_price: float | None = Field(None, gt=0, lt=100_000_000)
    purchase_date: date | None = None
    order_ref: str | None = None
    return_deadline: date | None = None
    protection_deadline: date | None = None
    expected_costs: float | None = Field(None, ge=0, lt=100_000_000)
    notify: bool | None = None
    email: EmailStr | None = None

    _ref = field_validator("order_ref")(classmethod(lambda cls, v: _clean_ref(v)))


def _own(db: Session, pid: int, cid: str) -> TrackedPurchase:
    p = db.get(TrackedPurchase, pid)
    if p is None or p.client_id != cid:  # same 404 for "missing" and "someone else's" – no existence leak
        raise http_error(404, "purchase_not_found", "Purchase not found.")
    return p


def _out(svc: RegretService, db: Session, p: TrackedPurchase) -> dict:
    ev = svc.evaluate(db, p)
    return {
        "id": p.id, "product_id": p.product_id, "product_title": p.product.title, "image_url": p.product.image_url,
        "storage_gb": p.product.storage_gb, "ram_gb": p.product.ram_gb, "colour": p.product.colour, "condition": p.product.condition,
        "retailer": p.retailer, "purchase_price": p.purchase_price,
        "purchase_date": aware(p.purchase_date).astimezone(IST).date().isoformat(),
        "order_ref": p.order_ref,
        "return_deadline": aware(p.return_deadline).astimezone(IST).date().isoformat() if p.return_deadline else None,
        "protection_deadline": aware(p.protection_deadline).astimezone(IST).date().isoformat() if p.protection_deadline else None,
        "expected_costs": p.expected_costs, "notify": p.notify, "email": p.email, "status": ev["status"],
        "last_checked_at": _iso(p.last_checked_at), "created_at": _iso(p.created_at),
        "unread_notifications": sum(1 for n in p.notifications if n.read_at is None),
        **{k: ev[k] for k in ("comparable", "comparable_verified_at", "deadlines", "difference", "difference_pct",
                              "meaningful_drop", "net_benefit", "actions", "notes")},
    }


@router.get("/products/{product_id}/regret-shield")
def pre_purchase(request: Request, product_id: int, db: Session = Depends(get_db)) -> dict:
    return regret(request).pre_check(db, get_product_or_404(db, product_id), demo=demo_on(request))


@router.post("/purchases", status_code=201)
def create_purchase(body: PurchaseIn, request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    svc = regret(request)
    get_product_or_404(db, body.product_id)  # re-uses the existing product record – no duplicate products
    p = TrackedPurchase(client_id=cid, product_id=body.product_id, retailer=body.retailer.strip(),
                        purchase_price=round(body.purchase_price, 2), purchase_date=_to_dt(body.purchase_date),
                        order_ref=body.order_ref, return_deadline=_to_dt(body.return_deadline),
                        protection_deadline=_to_dt(body.protection_deadline), expected_costs=body.expected_costs,
                        notify=body.notify, email=str(body.email).lower() if body.email else None)
    db.add(p)
    db.flush()
    svc.record(db, p, svc.evaluate(db, p))  # first check right away, from the latest verified offers
    db.commit()
    db.refresh(p)
    return _out(svc, db, p)


@router.get("/purchases")
def list_purchases(request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    svc = regret(request)
    rows = db.scalars(select(TrackedPurchase).where(TrackedPurchase.client_id == cid)
                      .order_by(TrackedPurchase.created_at.desc())).all()
    items = [_out(svc, db, p) for p in rows]
    upcoming = sorted(({**d, "purchase_id": it["id"], "product_title": it["product_title"]}
                       for it in items for d in it["deadlines"] if d["state"] != "passed"), key=lambda d: d["days_left"])
    return {"items": items, "deadlines": upcoming,
            "price_drops": [it["id"] for it in items if it["status"] == "price_drop"],
            "thresholds": {"min_drop_pct": svc.settings.regret_min_drop_pct, "min_drop_amount": svc.settings.regret_min_drop_amount},
            "email_ready": email_configured(svc.settings),
            "monitoring": {"scheduler_enabled": svc.settings.scheduler_enabled,
                           "note": "Purchases are re-checked automatically while the BuyWise backend is running "
                                   f"(every {svc.settings.refresh_popular_minutes} min for tracked products)."}}


@router.get("/purchases/notifications")
def notifications(cid: str = Depends(client_id), db: Session = Depends(get_db),
                  unread_only: bool = False) -> dict:
    q = (select(PurchaseNotification).join(TrackedPurchase).where(TrackedPurchase.client_id == cid)
         .order_by(PurchaseNotification.created_at.desc()).limit(100))
    if unread_only:
        q = q.where(PurchaseNotification.read_at.is_(None))
    rows = db.scalars(q).all()
    return {"items": [{"id": n.id, "purchase_id": n.purchase_id, "kind": n.kind, "message": n.message,
                       "created_at": _iso(n.created_at), "read": n.read_at is not None, "email_status": n.email_status} for n in rows],
            "unread": sum(1 for n in rows if n.read_at is None)}


@router.post("/purchases/notifications/read")
def mark_read(cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(PurchaseNotification).join(TrackedPurchase).where(
        TrackedPurchase.client_id == cid, PurchaseNotification.read_at.is_(None))).all()
    for n in rows:
        n.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"marked": len(rows)}


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: int, request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    return _out(regret(request), db, _own(db, purchase_id, cid))


@router.patch("/purchases/{purchase_id}")
def update_purchase(purchase_id: int, body: PurchasePatch, request: Request, cid: str = Depends(client_id),
                    db: Session = Depends(get_db)) -> dict:
    svc = regret(request)
    p = _own(db, purchase_id, cid)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k in ("purchase_date", "return_deadline", "protection_deadline"):
            v = _to_dt(v)
        if k == "email" and v is not None:
            v = str(v).lower()
        if k == "purchase_date" and v is None:
            continue
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    pdate = aware(p.purchase_date).astimezone(IST).date()
    if pdate > today_ist() + timedelta(days=1):
        raise http_error(422, "invalid_date", "Purchase date can't be in the future.")
    for name in ("return_deadline", "protection_deadline"):
        d = getattr(p, name)
        if d is not None and aware(d).astimezone(IST).date() < pdate:
            raise http_error(422, "invalid_date", f"{name.replace('_', ' ').capitalize()} can't be before the purchase date.")
    p.updated_at = datetime.now(timezone.utc)
    svc.record(db, p, svc.evaluate(db, p))
    db.commit()
    db.refresh(p)
    return _out(svc, db, p)


@router.delete("/purchases/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: int, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> None:
    db.delete(_own(db, purchase_id, cid))
    db.commit()


@router.get("/purchases/{purchase_id}/history")
def purchase_history(purchase_id: int, cid: str = Depends(client_id), db: Session = Depends(get_db),
                     limit: int = Query(200, ge=1, le=1000)) -> dict:
    p = _own(db, purchase_id, cid)
    rows = db.scalars(select(PurchaseCheck).where(PurchaseCheck.purchase_id == p.id)
                      .order_by(PurchaseCheck.checked_at.desc()).limit(limit)).all()
    return {"purchase_id": p.id, "purchase_price": p.purchase_price,
            "checks": [{"checked_at": _iso(c.checked_at), "status": c.status, "comparable_price": c.comparable_price,
                        "retailer": c.retailer, "difference": c.difference, "offer_verified_at": _iso(c.offer_verified_at)}
                       for c in rows]}


@router.post("/purchases/{purchase_id}/check")
async def check_now(purchase_id: int, request: Request, cid: str = Depends(client_id), db: Session = Depends(get_db)) -> dict:
    """Re-fetch the product's prices through the existing refresh pipeline, then re-check the purchase."""
    svc = regret(request)
    p = _own(db, purchase_id, cid)
    refresh = None
    if svc.catalog.registry.configured():
        refresh = await svc.catalog.refresh_product(p.product_id, "manual")
        db.expire_all()
        p = _own(db, purchase_id, cid)
    svc.record(db, p, svc.evaluate(db, p))
    db.commit()
    return {**_out(svc, db, p), "refresh": refresh}

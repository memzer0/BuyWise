"""Regret Shield: purchase tracking, ownership, price-drop maths, deadlines, notifications, scheduler monitoring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import session as dbs
from app.main import create_app
from app.models import Offer, PurchaseCheck, PurchaseNotification, TrackedPurchase
from app.providers.registry import ProviderRegistry
from app.regret.service import inr, today_ist
from app.workers.scheduler import RefreshScheduler
from tests.fakes import FakeProvider, row

CATALOG = {
    "iphone 16": [
        row("a1", "Apple iPhone 16 (Black, 128 GB)", 69999, "Shop A", availability="in_stock"),
        row("a2", "Apple iPhone 16 (Black, 256 GB)", 79999, "Shop A", availability="in_stock"),
    ],
}
CATALOG_B = {"iphone 16": [row("b1", "Apple iPhone 16 128GB Black", 68999, "Shop B", availability="in_stock")]}
ME = {"X-Client-Id": "client-owner-0001"}
OTHER = {"X-Client-Id": "client-intruder-02"}


@pytest.fixture()
def ctx(settings, db_url):  # noqa: ANN001
    reg = ProviderRegistry(settings, [FakeProvider(settings, CATALOG, provider_id="prov_a"),
                                      FakeProvider(settings, CATALOG_B, provider_id="prov_b")])
    app = create_app(settings, reg)
    with TestClient(app) as c:
        res = c.get("/api/search", params={"q": "iphone 16"}).json()["results"]
        ids = {p["storage_gb"]: p["id"] for p in res}
        yield c, ids


def buy(c, pid, price, headers=ME, **extra):  # noqa: ANN001, ANN003
    body = {"product_id": pid, "retailer": "Shop A", "purchase_price": price,
            "purchase_date": today_ist().isoformat(), **extra}
    return c.post("/api/purchases", json=body, headers=headers)


# ---------------------------------------------------------------- CRUD + ownership
def test_create_list_get_patch_delete(ctx):  # noqa: ANN001
    c, ids = ctx
    r = buy(c, ids[128], 75000, order_ref="OD-123/45")
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["product_id"] == ids[128] and p["purchase_price"] == 75000 and p["order_ref"] == "OD-123/45"
    assert p["status"] == "price_drop" and p["last_checked_at"]
    lst = c.get("/api/purchases", headers=ME).json()
    assert [i["id"] for i in lst["items"]] == [p["id"]] and lst["price_drops"] == [p["id"]]
    assert c.get(f"/api/purchases/{p['id']}", headers=ME).json()["retailer"] == "Shop A"
    u = c.patch(f"/api/purchases/{p['id']}", json={"purchase_price": 60000, "notify": False}, headers=ME).json()
    assert u["purchase_price"] == 60000 and u["status"] == "no_drop" and u["notify"] is False
    assert c.delete(f"/api/purchases/{p['id']}", headers=ME).status_code == 204
    assert c.get(f"/api/purchases/{p['id']}", headers=ME).status_code == 404
    with dbs.SessionLocal() as db:  # checks + notifications are removed with the purchase
        assert db.scalars(select(PurchaseCheck)).all() == [] and db.scalars(select(PurchaseNotification)).all() == []


def test_other_clients_cannot_see_or_change_purchases(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    assert c.get("/api/purchases", headers=OTHER).json()["items"] == []
    assert c.get("/api/purchases/notifications", headers=OTHER).json()["items"] == []
    for method, path, kw in (("get", f"/api/purchases/{pid}", {}), ("patch", f"/api/purchases/{pid}", {"json": {"notify": False}}),
                             ("delete", f"/api/purchases/{pid}", {}), ("get", f"/api/purchases/{pid}/history", {}),
                             ("post", f"/api/purchases/{pid}/check", {})):
        r = getattr(c, method)(path, headers=OTHER, **kw)
        assert r.status_code == 404 and r.json()["error"]["code"] == "purchase_not_found", (method, path)
    c.post("/api/purchases/notifications/read", headers=OTHER)
    assert c.get("/api/purchases/notifications", headers=ME).json()["unread"] >= 1  # untouched by the other client
    assert c.get(f"/api/purchases/{pid}", headers=ME).status_code == 200
    assert c.get("/api/purchases").status_code == 422  # client id is required


@pytest.mark.parametrize("extra,why", [
    ({"purchase_price": 0}, "zero price"),
    ({"purchase_price": -5}, "negative price"),
    ({"purchase_date": (today_ist() + timedelta(days=5)).isoformat()}, "future date"),
    ({"return_deadline": (today_ist() - timedelta(days=5)).isoformat()}, "deadline before purchase"),
    ({"order_ref": "<script>"}, "bad characters"),
    ({"retailer": ""}, "empty retailer"),
    ({"expected_costs": -1}, "negative costs"),
])
def test_input_validation(ctx, extra, why):  # noqa: ANN001
    c, ids = ctx
    body = {"product_id": ids[128], "retailer": "Shop A", "purchase_price": 70000,
            "purchase_date": today_ist().isoformat(), **extra}
    assert c.post("/api/purchases", json=body, headers=ME).status_code == 422, why


def test_unknown_product_and_patch_validation(ctx):  # noqa: ANN001
    c, ids = ctx
    assert buy(c, 99999, 70000).status_code == 404
    pid = buy(c, ids[128], 70000).json()["id"]
    bad = (today_ist() - timedelta(days=30)).isoformat()
    assert c.patch(f"/api/purchases/{pid}", json={"return_deadline": bad}, headers=ME).status_code == 422


# ---------------------------------------------------------------- price-drop maths
def test_price_drop_maths_and_exact_variant(ctx):  # noqa: ANN001
    c, ids = ctx
    p = buy(c, ids[128], 75000).json()
    comp = p["comparable"]
    # cheapest comparable offer for the SAME 128 GB variant (68,999 at Shop B), never the 256 GB product
    assert comp["status"] == "comparable" and comp["price"] == 68999 and comp["retailer"] == "Shop B"
    assert p["difference"] == 6001 and p["difference_pct"] == pytest.approx(6001 / 75000 * 100, abs=0.01)
    assert p["meaningful_drop"] is True and p["actions"]
    assert p["net_benefit"] is None  # no expected costs entered → no net benefit
    p256 = buy(c, ids[256], 79999).json()
    assert p256["comparable"]["price"] == 79999 and p256["status"] == "no_drop" and p256["difference"] == 0


def test_small_drop_and_no_drop(ctx):  # noqa: ANN001
    c, ids = ctx
    small = buy(c, ids[128], 69100).json()  # ₹101 cheaper now – under the ₹200 / 2 % threshold
    assert small["status"] == "small_drop" and small["difference"] == 101 and small["meaningful_drop"] is False
    assert small["actions"] == []
    higher = buy(c, ids[128], 60000).json()
    assert higher["status"] == "no_drop" and higher["difference"] == -8999
    assert c.get("/api/purchases/notifications", headers=ME).json()["items"] == []


def test_net_benefit_only_with_expected_costs(ctx):  # noqa: ANN001
    c, ids = ctx
    p = buy(c, ids[128], 75000, expected_costs=1500).json()
    nb = p["net_benefit"]
    assert nb["amount"] == 4501 and nb["inputs"] == {"difference": 6001, "expected_costs": 1500}
    assert "Estimated" in nb["label"]


def test_zero_purchase_price_handled_safely(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 70000).json()["id"]
    svc = c.app.state.regret
    with dbs.SessionLocal() as db:
        p = db.get(TrackedPurchase, pid)
        p.purchase_price = 0  # e.g. legacy/corrupt row – must not divide by zero
        ev = svc.evaluate(db, p)
    assert ev["status"] == "invalid_purchase_price" and ev["difference_pct"] is None


def _age_offers(product_id: int, **changes) -> None:  # noqa: ANN003
    with dbs.SessionLocal() as db:
        for o in db.scalars(select(Offer).where(Offer.product_id == product_id)).all():
            for k, v in changes.items():
                setattr(o, k, v)
        db.commit()


def test_stale_and_unavailable_comparable(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    _age_offers(ids[128], last_verified_at=datetime.now(timezone.utc) - timedelta(days=3))
    p = c.get(f"/api/purchases/{pid}", headers=ME).json()
    assert p["status"] == "stale_data" and p["difference"] is None and "stale" in p["notes"][0]
    _age_offers(ids[128], last_verified_at=datetime.now(timezone.utc), availability="out_of_stock")
    p = c.get(f"/api/purchases/{pid}", headers=ME).json()
    assert p["status"] == "comparable_unavailable" and p["difference"] is None and p["comparable"]["status"] == "comparable_unavailable"


# ---------------------------------------------------------------- monitoring, notifications, deadlines
def test_monitoring_dedupes_checks_and_notifications(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    svc = c.app.state.regret
    now = datetime.now(timezone.utc)
    with dbs.SessionLocal() as db:
        svc.monitor_all(db, now)                     # same hour bucket as the first check → no new row
        svc.monitor_all(db, now + timedelta(hours=2))
        svc.monitor_all(db, now + timedelta(hours=3))
        checks = db.scalars(select(PurchaseCheck).where(PurchaseCheck.purchase_id == pid)).all()
        assert len(checks) == 3
        drops = db.scalars(select(PurchaseNotification).where(PurchaseNotification.kind == "price_drop")).all()
        assert len(drops) == 1 and inr(6001) in drops[0].message
    hist = c.get(f"/api/purchases/{pid}/history", headers=ME).json()["checks"]
    assert len(hist) == 3 and all(h["comparable_price"] == 68999 for h in hist)
    n = c.get("/api/purchases/notifications", headers=ME).json()
    assert n["unread"] == 1
    assert c.post("/api/purchases/notifications/read", headers=ME).json() == {"marked": 1}
    assert c.get("/api/purchases/notifications", params={"unread_only": True}, headers=ME).json()["items"] == []


def test_no_notifications_when_disabled(ctx):  # noqa: ANN001
    c, ids = ctx
    buy(c, ids[128], 75000, notify=False)
    assert c.get("/api/purchases/notifications", headers=ME).json()["items"] == []


def test_deadline_states_and_alerts(ctx):  # noqa: ANN001
    c, ids = ctx
    t = today_ist()
    p = buy(c, ids[128], 60000, purchase_date=(t - timedelta(days=5)).isoformat(),
            return_deadline=(t + timedelta(days=2)).isoformat(),
            protection_deadline=(t + timedelta(days=20)).isoformat()).json()
    dl = {d["kind"]: d for d in p["deadlines"]}
    assert dl["return"]["state"] == "soon" and dl["return"]["days_left"] == 2
    assert dl["protection"]["state"] == "upcoming"
    lst = c.get("/api/purchases", headers=ME).json()
    assert [d["kind"] for d in lst["deadlines"]] == ["return", "protection"]
    svc = c.app.state.regret
    with dbs.SessionLocal() as db:
        svc.monitor_all(db, datetime.now(timezone.utc) + timedelta(hours=2))
    items = c.get("/api/purchases/notifications", headers=ME).json()["items"]
    assert [i["kind"] for i in items] == ["deadline"] and "in 2 day(s)" in items[0]["message"]
    with dbs.SessionLocal() as db:  # day after the deadline → "passed", no new alert
        pr = db.get(TrackedPurchase, p["id"])
        states = {d["kind"]: d["state"] for d in svc.deadlines(pr, datetime.now(timezone.utc) + timedelta(days=3))}
    assert states == {"return": "passed", "protection": "upcoming"}


def test_unavailable_monitoring_notice_after_three_checks(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000, notify=True).json()["id"]
    _age_offers(ids[128], availability="out_of_stock")
    svc = c.app.state.regret
    now = datetime.now(timezone.utc)
    with dbs.SessionLocal() as db:
        for h in (2, 3, 4, 5):
            svc.monitor_all(db, now + timedelta(hours=h))
        kinds = [n.kind for n in db.scalars(select(PurchaseNotification).where(PurchaseNotification.purchase_id == pid))]
    assert kinds.count("monitoring") == 1


def test_scheduler_monitors_purchases(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    sched = RefreshScheduler(c.app.state.catalog, c.app.state.regret)
    assert ids[128] in sched.due_products(datetime.now(timezone.utc) + timedelta(days=1))
    assert sched.check_purchases() == 1
    with dbs.SessionLocal() as db:
        assert db.get(TrackedPurchase, pid).last_checked_at is not None


def test_check_now_refreshes(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    r = c.post(f"/api/purchases/{pid}/check", headers=ME)
    assert r.status_code == 200 and r.json()["refresh"] is not None and r.json()["status"] == "price_drop"


# ---------------------------------------------------------------- pre-purchase check
def test_pre_purchase_check(ctx):  # noqa: ANN001
    c, ids = ctx
    r = c.get(f"/api/products/{ids[128]}/regret-shield").json()
    assert r["result"] in {"BUY_NOW", "WAIT", "COMPARE_FIRST", "INSUFFICIENT_DATA"}
    # no price history yet → BuyWise must not claim a confident BUY NOW
    assert r["result"] != "BUY_NOW"
    assert "Return policy" in r["missing"] and r["best_offer"]["price"] == 68999
    labels = {e["label"] for e in r["evidence"]}
    assert {"Current price", "Exact variant", "Seller", "Warranty"} <= labels
    assert c.get("/api/products/99999/regret-shield").status_code == 404


def test_edit_updates_current_hour_history(ctx):  # noqa: ANN001
    c, ids = ctx
    pid = buy(c, ids[128], 75000).json()["id"]
    c.patch(f"/api/purchases/{pid}", json={"purchase_price": 69000}, headers=ME)
    checks = c.get(f"/api/purchases/{pid}/history", headers=ME).json()["checks"]
    assert len(checks) == 1 and checks[0]["difference"] == 1 and checks[0]["status"] == "small_drop"

"""Demo mode: simulated history is opt-in, flagged, deterministic, never stored, never used for purchases."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import session as dbs
from app.main import create_app
from app.models import PriceObservation
from app.providers.registry import ProviderRegistry
from app.services.demo_history import demo_daily
from tests.fakes import FakeProvider, row

CATALOG = {"iphone 16": [row("a1", "Apple iPhone 16 (Black, 128 GB)", 69999, "Shop A", availability="in_stock")]}
DEMO = {"X-BuyWise-Demo": "1", "X-Client-Id": "demo-client-0001"}


def _client(settings):  # noqa: ANN001, ANN202
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, CATALOG, provider_id="prov_a")]))
    return TestClient(app)


def test_demo_is_opt_in_flagged_and_not_stored(settings, db_url):  # noqa: ANN001
    with _client(settings) as c:
        pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
        real = c.get(f"/api/products/{pid}/history", params={"range": "365d"}).json()
        assert real["demo_points"] == 0 and all(not pt.get("demo") for pt in real["lowest_series"])
        assert c.get(f"/api/products/{pid}").json()["demo_history"] is False
        with dbs.SessionLocal() as db:
            stored = db.scalar(select(func.count()).select_from(PriceObservation))

        h = c.get(f"/api/products/{pid}/history", params={"range": "365d"}, headers=DEMO).json()
        assert h["demo_points"] > 60 and h["demo_note"]
        demo_pts = [pt for pt in h["lowest_series"] if pt.get("demo")]
        assert demo_pts and all(pt["retailer"] == "Demo (simulated)" for pt in demo_pts)
        assert not h["lowest_series"][-1].get("demo") and h["lowest_series"][-1]["price"] == 69999  # real data last
        d = c.get(f"/api/products/{pid}", headers=DEMO).json()
        assert d["demo_history"] is True and d["deal"]["score"] is not None
        assert d["decision"]["verdict"] != "NOT_ENOUGH_DATA" and d["decision"]["evidence_level"] == "low"
        assert not any("SIMULATED" in lim for lim in d["decision"]["limitations"])  # no visible demo wording
        assert d["summary"]["lowest_verified_price"] == 69999  # the current price is always real
        pre = c.get(f"/api/products/{pid}/regret-shield", headers=DEMO).json()
        assert pre["result"] != "INSUFFICIENT_DATA" and pre["demo_history"] is True
        with dbs.SessionLocal() as db:  # nothing simulated was written
            assert db.scalar(select(func.count()).select_from(PriceObservation)) == stored


def test_demo_curve_is_deterministic_and_bounded():
    a = demo_daily(7, 50000, date(2026, 10, 15))
    assert a == demo_daily(7, 50000, date(2026, 10, 15)) and len(a) == 120
    assert all(0.85 * 50000 <= v <= 1.17 * 50000 for v in a.values())
    assert a != demo_daily(8, 50000, date(2026, 10, 15))

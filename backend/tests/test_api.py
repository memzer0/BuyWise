from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from tests.fakes import FakeProvider, row

CATALOG = {
    "iphone 16": [
        row("a1", "Apple iPhone 16 (Black, 128 GB)", 69999, "Shop A", mrp=79900, availability="in_stock"),
        row("a2", "Apple iPhone 16 (Black, 256 GB)", 79999, "Shop A", availability="in_stock"),
    ],
}
CATALOG_B = {
    "iphone 16": [row("b1", "Apple iPhone 16 128GB Black", 68999, "Shop B", availability="in_stock")],
}
HEADERS = {"X-Client-Id": "test-client-123"}


@pytest.fixture()
def app_and_providers(settings, db_url):  # noqa: ANN001
    a = FakeProvider(settings, CATALOG, provider_id="prov_a")
    b = FakeProvider(settings, CATALOG_B, provider_id="prov_b")
    down = FakeProvider(settings, error=ProviderError("server_error", "down", 503), provider_id="prov_down")
    app = create_app(settings, ProviderRegistry(settings, [a, b, down]))
    with TestClient(app) as c:
        yield c, a, b


def test_health_reports_providers_separately(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    h = c.get("/api/health").json()
    assert h["app"] == "ok" and h["database"] == "ok" and h["live_price_fetching"] == "unverified"


def test_search_groups_offers_and_reports_partial(app_and_providers):  # noqa: ANN001
    c, a, b = app_and_providers
    r = c.get("/api/search", params={"q": "iphone 16"})
    assert r.status_code == 200 and r.headers["x-request-id"]
    data = r.json()
    assert data["source"] == "live" and data["partial"] is True
    statuses = {p["provider"]: p["status"] for p in data["providers"]}
    assert statuses == {"prov_a": "ok", "prov_b": "ok", "prov_down": "error"}
    assert data["total"] == 2
    p128 = next(p for p in data["results"] if p["storage_gb"] == 128)
    assert p128["verified_offer_count"] == 2 and p128["best_price"] == 68999 and p128["best_retailer"] == "Shop B"
    # second identical search is served from cache – no extra provider calls
    calls = a.calls
    assert c.get("/api/search", params={"q": "iphone 16"}).json()["source"] == "cache" and a.calls == calls


def test_search_filters_and_sort(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    d = c.get("/api/search", params={"q": "iphone 16", "storage_gb": 256}).json()
    assert d["total"] == 1 and d["results"][0]["storage_gb"] == 256
    d = c.get("/api/search", params={"q": "iphone 16", "sort": "price_desc"}).json()
    assert d["results"][0]["best_price"] == 79999


def test_product_detail_offers_and_exact_urls(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    pid = next(p["id"] for p in c.get("/api/search", params={"q": "iphone 16"}).json()["results"] if p["storage_gb"] == 128)
    d = c.get(f"/api/products/{pid}").json()
    urls = {o["retailer"]: o["product_url"] for o in d["offers"]}
    assert urls == {"Shop A": "https://shopa.example/p/a1", "Shop B": "https://shopb.example/p/b1"}
    best = [o for o in d["offers"] if o["is_best_price"]]
    assert len(best) == 1 and best[0]["retailer"] == "Shop B"
    assert d["summary"]["price_difference"] == 1000
    assert d["score"]["components"] and d["prediction"]["available"] is False
    o = c.get(f"/api/products/{pid}/offers", params={"sort": "price_desc"}).json()["offers"]
    assert o[0]["price"] == 69999


def test_history_only_real_observations(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
    h = c.get(f"/api/products/{pid}/history", params={"range": "30d"}).json()
    assert h["observation_count"] >= 1 and all(pt["price"] > 0 for pt in h["points"])
    assert h["tracking_started_at"] is not None
    assert c.get(f"/api/products/{pid}/history", params={"range": "2d"}).status_code == 422


def test_manual_refresh(app_and_providers):  # noqa: ANN001
    c, a, _ = app_and_providers
    pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
    before = a.calls
    r = c.post(f"/api/products/{pid}/refresh").json()
    assert r["status"] == "success" and a.calls == before + 1


def test_watchlist_and_alerts(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    pid = next(p["id"] for p in c.get("/api/search", params={"q": "iphone 16"}).json()["results"] if p["storage_gb"] == 128)
    assert c.post("/api/watchlist", json={"product_id": pid}, headers=HEADERS).status_code == 201
    assert c.post("/api/watchlist", json={"product_id": pid}, headers=HEADERS).status_code == 201  # idempotent
    items = c.get("/api/watchlist", headers=HEADERS).json()["items"]
    assert len(items) == 1 and items[0]["historical_min"] == 68999
    r = c.post("/api/alerts", json={"product_id": pid, "target_price": 70000}, headers=HEADERS)
    assert r.status_code == 201
    alerts = c.get("/api/alerts", headers=HEADERS).json()["alerts"]
    assert len(alerts[0]["events"]) == 1 and alerts[0]["events"][0]["delivery_status"] == "recorded"
    # refreshing again at the same price must not create a duplicate event
    c.post(f"/api/products/{pid}/refresh")
    assert len(c.get("/api/alerts", headers=HEADERS).json()["alerts"][0]["events"]) == 1
    assert c.get("/api/watchlist").status_code == 422  # client id required


def test_error_responses(app_and_providers):  # noqa: ANN001
    c, *_ = app_and_providers
    e = c.get("/api/products/9999").json()["error"]
    assert e["code"] == "product_not_found" and e["request_id"]
    assert c.get("/api/search", params={"q": "!!"}).json()["error"]["code"] == "invalid_query"
    assert c.get("/api/admin/diagnostics").status_code == 401
    assert c.get("/api/admin/diagnostics", headers={"Authorization": "Bearer test-admin-token"}).status_code == 200


def test_no_providers_configured(settings, db_url):  # noqa: ANN001
    app = create_app(settings)  # real registry, no credentials in env
    with TestClient(app) as c:
        d = c.get("/api/search", params={"q": "iphone 16"}).json()
        assert d["no_providers_configured"] is True and d["results"] == []
        assert c.get("/api/health").json()["live_price_fetching"] == "not_configured"


def test_scheduler_refreshes_due_products(app_and_providers):  # noqa: ANN001
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.database.session import SessionLocal
    from app.models import Product

    c, a, _ = app_and_providers
    pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
    c.post("/api/watchlist", json={"product_id": pid}, headers=HEADERS)
    sched = c.app.state.scheduler
    with SessionLocal() as s:
        p = s.get(Product, pid)
        p.last_refreshed_at = datetime.now(timezone.utc) - timedelta(hours=5)
        s.commit()
    before = a.calls
    refreshed = asyncio.run(sched.tick())
    assert pid in refreshed and a.calls > before
    # immediately afterwards nothing is due (interval respected)
    assert pid not in sched.due_products()


def test_scheduler_pretracks_popular_searches(app_and_providers):  # noqa: ANN001
    import asyncio

    c, a, _ = app_and_providers
    sched = c.app.state.scheduler
    sched.settings = sched.settings.model_copy(update={"pretrack_enabled": True, "pretrack_queries": "iphone 16, pixel 9",
                                                       "pretrack_per_tick": 1})
    assert sched.due_pretrack_queries() == ["iphone 16", "pixel 9"][:1]
    before = a.calls
    assert asyncio.run(sched.pretrack()) == ["iphone 16"]
    assert a.calls > before
    # just searched → only the other query is still due; once both ran, nothing is due until the interval passes
    assert sched.due_pretrack_queries() == ["pixel 9"]
    asyncio.run(sched.pretrack())
    assert sched.due_pretrack_queries() == []


def test_search_ranks_exact_variant_first(settings, db_url):  # noqa: ANN001
    cat = {"iphone 16 128gb": [
        row("x1", "APPLE iPhone 12 128GB Green", 40000, "Shop A"),
        row("x2", "Apple iPhone 16 Plus", 79900, "Shop A"),
        row("x3", "Apple iPhone 16 (Black, 128 GB)", 69900, "Shop A"),
        row("x4", "Apple iPhone 16 (Black, 256 GB)", 79900, "Shop A"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        res = c.get("/api/search", params={"q": "iphone 16 128gb"}).json()["results"]
        assert res[0]["title"] == "Apple iPhone 16 (Black, 128 GB)" and res[0]["query_mismatches"] == []
        by = {r["title"]: r["query_mismatches"] for r in res}
        assert "model" in by["APPLE iPhone 12 128GB Green"]
        assert "variant" in by["Apple iPhone 16 Plus"] and "storage" in by["Apple iPhone 16 (Black, 256 GB)"]


def test_store_links_replace_google_pages(settings, db_url):  # noqa: ANN001
    from app.providers.validation import build_listing

    class FakeShopping(FakeProvider):
        async def fetch_store_offers(self, page_token, group_key, fallback_title):  # noqa: ANN001, ANN201
            self.store_calls = getattr(self, "store_calls", 0) + 1
            return [build_listing(provider_id=self.id, source_type="licensed_api", listing_key=f"{group_key}|store|{n.lower()}",
                                  title="Apple iPhone 16 Plus 128 GB", retailer=n, price=p, currency="INR",
                                  product_url=u, provider_ref=page_token)
                    for n, p, u in [("Reliance Digital", 79900, "https://www.reliancedigital.in/p/494422"),
                                    ("Croma", 78990, "https://www.croma.com/p/309688")]]

    cat = {"iphone 16 plus": [row("g1|Reliance Digital", "Apple iPhone 16 Plus", 79900, "Reliance Digital",
                                  url="https://www.google.co.in/search?ibp=oshop&prds=1", provider_ref="tok")]}
    prov = FakeShopping(settings, cat, provider_id="serpapi_google_shopping")
    app = create_app(settings, ProviderRegistry(settings, [prov]))
    with TestClient(app) as c:
        pid = c.get("/api/search", params={"q": "iphone 16 plus"}).json()["results"][0]["id"]
        first = c.get(f"/api/products/{pid}").json()
        assert first["refresh_in_progress"] is True  # store list is fetched on first open
        import time
        for _ in range(50):
            d = c.get(f"/api/products/{pid}").json()
            if not d["refresh_in_progress"]:
                break
            time.sleep(0.1)
        offers = {o["retailer"]: (o["link_type"], o["product_url"]) for o in d["offers"]}
        assert offers == {"Reliance Digital": ("exact_listing", "https://www.reliancedigital.in/p/494422"),
                          "Croma": ("exact_listing", "https://www.croma.com/p/309688")}
        best = next(o for o in d["offers"] if o["is_best_price"])
        assert best["retailer"] == "Croma"
        assert prov.store_calls == 1


def test_variants_listed(settings, db_url):  # noqa: ANN001
    cat = {"iphone 16": [
        row("v1", "Apple iPhone 16 (Black, 128 GB)", 69900, "Shop A"),
        row("v2", "Apple iPhone 16 (Black, 256 GB)", 79900, "Shop A"),
        row("v3", "Apple iPhone 16 (White, 128 GB)", 69900, "Shop A"),
        row("v4", "Apple iPhone 16 Pro (Black, 128 GB)", 119900, "Shop A"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        res = c.get("/api/search", params={"q": "iphone 16"}).json()["results"]
        pid = next(r["id"] for r in res if r["title"] == "Apple iPhone 16 (Black, 128 GB)")
        v = c.get(f"/api/products/{pid}").json()["variants"]
        assert sorted((x["storage_gb"], x["colour"]) for x in v) == [(128, "white"), (256, "black")]  # not the Pro


def test_detail_has_deal_similar_and_relative_prices(settings, db_url):  # noqa: ANN001
    cat = {"galaxy": [
        row("s1", "Samsung Galaxy S24 (Onyx Black, 8GB RAM, 256GB)", 64999, "Shop A"),
        row("s2", "Samsung Galaxy S24 (Onyx Black, 8GB RAM, 256GB)", 66999, "Shop B"),
        row("s3", "Samsung Galaxy S24 FE (Mint, 8GB RAM, 128GB)", 39999, "Shop A"),
        row("s4", "Silicone Case for Samsung Galaxy S24", 499, "Shop A"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        res = c.get("/api/search", params={"q": "galaxy"}).json()["results"]
        pid = next(r["id"] for r in res if r["title"].startswith("Samsung Galaxy S24 (Onyx"))
        d = c.get(f"/api/products/{pid}").json()
        assert d["deal"]["score"] is None and d["deal"]["insight"]["title"] == "Tracking just started"
        assert {o["retailer"]: o["vs_best_pct"] for o in d["offers"]} == {"Shop A": 0.0, "Shop B": 3.1}
        sim = d["similar"]
        assert [s["title"] for s in sim] == ["Samsung Galaxy S24 FE (Mint, 8GB RAM, 128GB)"]  # not the case
        assert sim[0]["buy_url"] == "https://shopa.example/p/s3"

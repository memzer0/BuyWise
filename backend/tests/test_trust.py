from fastapi.testclient import TestClient

from app.main import create_app
from app.pricing.trust import DEFAULT_TRUSTED_DOMAINS, DEFAULT_TRUSTED_STORES, TrustPolicy
from app.providers.registry import ProviderRegistry
from tests.fakes import FakeProvider, row


def test_default_trusted_stores():
    t = TrustPolicy(DEFAULT_TRUSTED_STORES, DEFAULT_TRUSTED_DOMAINS)
    for name in ("Amazon.in", "Flipkart", "Croma", "Reliance Digital", "Vijay Sales", "Tata CLiQ", "Apple"):
        assert t.is_trusted(name), name
    assert not t.is_trusted("KerfCase") and not t.is_trusted("Baba Tools") and not t.is_trusted("Meesho")
    # exact links on a trusted domain count even if the store name differs
    assert t.is_trusted("Croma Retail", "https://www.croma.com/apple-iphone-16/p/1", "exact_listing")
    # a Google Shopping page never proves the domain
    assert not t.is_trusted("Random", "https://www.google.com/x", "aggregator_page")
    assert not t.is_trusted("Fake", "https://croma.com.evil.example/p/1", "exact_listing")


def test_search_hides_accessories_and_untrusted_by_default(settings, db_url):  # noqa: ANN001
    settings.trusted_stores = DEFAULT_TRUSTED_STORES
    cat = {"iphone 16": [
        row("a", "Apple iPhone 16 (Black, 128 GB)", 69900, "Croma"),
        row("b", "Apple iPhone 16 (Black, 128 GB)", 70900, "Some Random Shop"),
        row("c", "Apple iPhone 16 Pro (Natural Titanium, 256 GB)", 129900, "Unknown Store"),
        row("d", "Silicone Case for iPhone 16", 499, "Croma"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        d = c.get("/api/search", params={"q": "iphone 16"}).json()
        titles = [r["title"] for r in d["results"]]
        assert titles == ["Apple iPhone 16 (Black, 128 GB)"]
        assert d["hidden_accessories"] == 1 and d["hidden_untrusted"] == 1
        d2 = c.get("/api/search", params={"q": "iphone 16", "include_accessories": True, "all_stores": True}).json()
        assert len(d2["results"]) == 3
        # an accessory search shows accessories
        assert c.get("/api/search", params={"q": "case for iphone 16"}).json()["hidden_accessories"] == 0

        pid = d["results"][0]["id"]
        detail = c.get(f"/api/products/{pid}").json()
        best = next(o for o in detail["offers"] if o["is_best_price"])
        assert best["retailer"] == "Croma"  # the untrusted cheaper/dearer shop is never "best"
        untrusted = next(o for o in detail["offers"] if o["retailer"] == "Some Random Shop")
        assert untrusted["trusted_store"] is False and untrusted["ineligible_reason"] == "untrusted_store"
        offers = c.get(f"/api/products/{pid}/offers").json()
        assert [o["retailer"] for o in offers["offers"]] == ["Croma"] and offers["hidden_untrusted"] == 1
        assert len(c.get(f"/api/products/{pid}/offers", params={"all_stores": True}).json()["offers"]) == 2


def test_preferred_store_ranking():
    t = TrustPolicy(DEFAULT_TRUSTED_STORES, DEFAULT_TRUSTED_DOMAINS)
    assert t.preferred_rank("Flipkart") == 0 and t.preferred_rank("Reliance Digital") == 1
    assert t.preferred_rank("Amazon.in") == 2 and t.preferred_rank("Amazon India") == 2
    assert t.preferred_rank("Vijay Sales") == 3 and t.preferred_rank("Croma") == 4
    assert t.preferred_rank("Tata CLiQ") is None and t.preferred_rank("Amazonia Gadgets") is None
    assert t.preferred_rank("Croma Retail", "https://www.croma.com/p/1", "exact_listing") == 4


def test_top_stores_listed_first(settings, db_url):  # noqa: ANN001
    settings.trusted_stores = DEFAULT_TRUSTED_STORES
    cat = {"galaxy s24": [
        row("t", "Samsung Galaxy S24 (Onyx Black, 8GB RAM, 256GB)", 61999, "Tata CLiQ"),
        row("c", "Samsung Galaxy S24 (Onyx Black, 8GB RAM, 256GB)", 64999, "Croma"),
        row("f", "Samsung Galaxy S24 (Onyx Black, 8GB RAM, 256GB)", 63999, "Flipkart"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        r = c.get("/api/search", params={"q": "galaxy s24"}).json()["results"][0]
        assert r["preferred_stores"] == ["Croma", "Flipkart"] and r["best_retailer"] == "Tata CLiQ"
        offers = c.get(f"/api/products/{r['id']}/offers").json()["offers"]
        # top stores first (cheapest of them first), then other trusted stores – honest lowest price is still Tata CLiQ
        assert [o["retailer"] for o in offers] == ["Flipkart", "Croma", "Tata CLiQ"]
        assert next(o for o in offers if o["is_best_price"])["retailer"] == "Tata CLiQ"


def test_one_row_per_store_and_history_only_trusted(settings, db_url):  # noqa: ANN001
    settings.trusted_stores = DEFAULT_TRUSTED_STORES
    cat = {"iphone 17 pro": [
        row("a1", "Apple iPhone 17 Pro (256GB) Deep Blue", 142989, "amazon.in"),
        row("a2", "Apple iPhone 17 Pro (256GB) Deep Blue", 143500, "amazon.in"),
        row("j1", "Apple iPhone 17 Pro (256GB) Deep Blue", 134900, "James & Co"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        pid = c.get("/api/search", params={"q": "iphone 17 pro"}).json()["results"][0]["id"]
        d = c.get(f"/api/products/{pid}").json()
        assert sorted(o["retailer"] for o in d["offers"]) == ["James & Co", "amazon.in"]  # one amazon row
        h = c.get(f"/api/products/{pid}/history", params={"range": "30d"}).json()
        assert h["lowest"] == 142989 and {pt["retailer"] for pt in h["points"]} == {"amazon.in"}

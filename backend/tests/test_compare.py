"""Product comparison: columns, factual summary, and the endpoint (stored data only – no provider calls)."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.registry import ProviderRegistry
from app.services.compare import summarize
from tests.fakes import FakeProvider, row


def _col(id_, title, price, **kw):  # noqa: ANN001, ANN003, ANN202
    base = {"id": id_, "title": title, "brand": "X", "category": "smartphones", "image_url": None, "storage_gb": None,
            "ram_gb": None, "colour": None, "condition": "new", "screen_inches": None, "specs": {}, "price": price,
            "highest_price": price, "best_store": "Shop A", "best_url": None, "best_link_type": None, "availability": None,
            "store_count": 1, "last_known": None, "last_verified_at": None, "deal_score": None, "deal_label": None,
            "buywise_score": None, "decision": {"verdict": "NOT_ENOUGH_DATA", "label": "Tracking price", "headline": ""},
            "rating": None, "ratings_count": None, "praised": [], "complaints": [], "reviews_analysed": 0,
            "history": {"lowest": None, "average": None, "highest": None}}
    return {**base, **kw}


def test_summary_states_only_supported_facts():
    a = _col(1, "Phone A", 59999, deal_score=80, deal_label="Great deal", rating=4.5, ratings_count=900, store_count=4,
             storage_gb=256, praised=["Camera"], reviews_analysed=6)
    b = _col(2, "Phone B", 64999, deal_score=55, deal_label="Fair", rating=4.2, ratings_count=12, store_count=2,
             storage_gb=128, complaints=["Heating"], reviews_analysed=5)
    s = summarize([a, b])
    h = {x["key"]: x for x in s["highlights"]}
    assert h["cheapest"]["product_id"] == 1 and "₹5,000 less than Phone B" in h["cheapest"]["text"]
    assert h["deal"]["product_id"] == 1 and h["rating"]["product_id"] == 1 and h["stores"]["product_id"] == 1
    assert s["overall"] == "Phone A leads on lowest price, best deal right now, highest rated and most stores."
    assert "Storage: 256 GB (Phone A) vs 128 GB (Phone B)." in s["differences"]
    assert any("Phone B: complaints mention heating (from 5 written reviews)" in d for d in s["differences"])
    assert any("fewer than 20" in n and "Phone B" in n for n in s["notes"])


def test_ties_and_missing_prices_are_not_called_wins():
    a = _col(1, "Phone A", None, rating=4.4, ratings_count=100)
    b = _col(2, "Phone B", 49999, rating=4.4, ratings_count=50)
    s = summarize([a, b])
    keys = [x["key"] for x in s["highlights"]]
    assert keys == ["cheapest"] and s["highlights"][0]["text"].startswith("Only Phone B has a current verified price")
    assert s["overall"] is None
    assert any("No current verified price for Phone A" in n for n in s["notes"])


def test_mixed_categories_and_conditions_are_flagged():
    s = summarize([_col(1, "Phone", 1000), _col(2, "Laptop", 2000, category="laptops", condition="refurbished")])
    assert any("different categories" in n for n in s["notes"])
    assert any(d.startswith("Condition differs") for d in s["differences"])


def test_endpoint_reads_stored_data_without_provider_calls(settings, db_url):  # noqa: ANN001
    prov = FakeProvider(settings, {"phone": [row("a1", "Google Pixel 9 (Obsidian, 128 GB)", 69999, "Shop A"),
                                             row("b1", "Samsung Galaxy S25 (Navy, 256 GB)", 74999, "Shop B")]})
    app = create_app(settings, ProviderRegistry(settings, [prov]))
    with TestClient(app) as c:
        ids = [r["id"] for r in c.get("/api/search", params={"q": "phone"}).json()["results"]]
        calls = prov.calls
        d = c.get("/api/compare", params={"ids": ",".join(map(str, ids + [ids[0], 99999]))}).json()
        assert prov.calls == calls                      # no provider calls for comparing
        assert [p["id"] for p in d["products"]] == ids and d["missing"] == [99999]
        assert {p["price"] for p in d["products"]} == {69999, 74999}
        assert d["summary"]["highlights"][0]["key"] == "cheapest"
        assert c.get("/api/compare", params={"ids": "a,b"}).status_code == 422

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.providers.registry import ProviderRegistry
from app.providers.serpapi_shopping import SerpApiGoogleShoppingProvider
from app.reviews.analyze import analyze, sentiment
from app.scoring.decision import timing
from tests.fakes import FakeProvider, row

DATA = {
    "rating": 4.4, "reviews_count": 3551,
    "ratings": [{"stars": 5, "amount": 3166}, {"stars": 1, "amount": 89}],
    "user_reviews": [
        {"title": "Great phone", "text": "The camera is excellent and the display is bright. Battery lasts a full day easily, very happy with performance.",
         "user_name": "a", "rating": 5, "source": "Flipkart"},
        {"title": "Heating", "text": "Phone heats a lot while gaming and the battery drains fast. Camera is good though.",
         "user_name": "b", "rating": 3, "source": "Amazon"},
        {"title": "Good", "text": "Good", "user_name": "c", "rating": 5},
        {"title": "BEST PHONE EVER!!!", "text": "MUST BUY!!! 5 STAR!!!", "user_name": "d", "rating": 5},
        {"title": "Disappointed", "text": "Terrible battery, worst purchase, the screen is dull and it lags all the time.", "user_name": "e", "rating": 5},
        {"title": "Got it free", "text": "Received this product to review. The design looks premium and sound is clear.", "user_name": "f", "rating": 5, "incentivized": True},
    ],
    "insights": [{"title": "What people say", "items": [{"pros": ["Great camera"], "cons": ["Heats up"]}]}],
}


def test_sentiment_with_negation():
    assert sentiment("The camera is good") == 1 and sentiment("The camera is not good") == -1


def test_review_summary_and_signals():
    r = analyze(DATA)
    assert r["available"] and r["rating"] == 4.4 and r["distribution"][0] == {"stars": 5, "count": 3166}
    by = {x["user_name"]: x for x in r["reviews"]}
    assert by["a"]["signals"] == []
    assert by["f"]["group"] == "flagged" and "Marked as incentivized by the source" in by["f"]["signals"]
    # rating/text mismatch, short or excited reviews are never questioned
    assert by["e"]["signals"] == [] and by["d"]["signals"] == [] and by["c"]["signals"] == []
    aspects = {a["aspect"]: a for a in r["aspects"]}
    assert aspects["Camera"]["positive"] >= 2 and aspects["Heating"]["negative"] >= 1
    assert "camera" in r["summary"].lower() and {"type": "pro", "text": "Great camera"} in r["insights"]
    assert r["counts"] == {"flagged": 1, "other": 5}


def test_reviews_unavailable_states():
    assert analyze(None)["available"] is False
    assert "no reviews" in analyze({"empty": True})["reason"]


def test_timing_needs_history():
    t = timing(current=100, lowest=100, highest=100, average=100, days_observed=1, pump=False, trend_per_day=None)
    assert t["available"] is False and "2 days" in t["reason"]


def test_timing_horizons():
    t = timing(current=110, lowest=100, highest=120, average=110, days_observed=10, pump=False, trend_per_day=-1)
    h = {x["key"]: x for x in t["horizons"]}
    assert h["3d"]["score"] == 60 and h["1w"]["score"] == 50 and h["1m"]["score"] == 40
    assert h["1m"]["recommendation"] == "Better to wait" and h["3d"]["tone"] == "fair"
    low = timing(current=100, lowest=100, highest=120, average=110, days_observed=10, pump=False, trend_per_day=None)
    assert all(x["recommendation"] == "Go ahead & buy now" for x in low["horizons"])
    pumped = timing(current=100, lowest=100, highest=120, average=110, days_observed=10, pump=True, trend_per_day=None)
    assert all(x["score"] <= 40 for x in pumped["horizons"])


def test_serpapi_store_call_captures_reviews(settings):  # noqa: ANN001
    settings.serpapi_api_key = "k"
    data = {"product_results": {"title": "Phone", "rating": 4.4, "reviews": 3551, "ratings": DATA["ratings"],
                                "user_reviews": DATA["user_reviews"], "top_insights": DATA["insights"], "stores": []}}
    p = SerpApiGoogleShoppingProvider(settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))))
    asyncio.run(p.fetch_store_offers("tok", "g", "Phone"))
    assert p.last_extra["reviews"]["reviews_count"] == 3551 and len(p.last_extra["reviews"]["user_reviews"]) == 6


def test_product_api_reviews_and_timing(settings, db_url):  # noqa: ANN001
    class Shop(FakeProvider):
        async def fetch_store_offers(self, page_token, group_key, fallback_title):  # noqa: ANN001, ANN201
            self.last_extra = {"reviews": DATA}
            return []

    prov = Shop(settings, {"pixel": [row("g|A", "Google Pixel 9 (Obsidian, 256 GB)", 79999, "Shop A",
                                         url="https://www.google.co.in/search?ibp=oshop&prds=1", provider_ref="tok")]},
                provider_id="serpapi_google_shopping")
    app = create_app(settings, ProviderRegistry(settings, [prov]))
    with TestClient(app) as c:
        pid = c.get("/api/search", params={"q": "pixel"}).json()["results"][0]["id"]
        first = c.get(f"/api/products/{pid}").json()
        assert first["reviews"]["available"] is False and first["timing"]["available"] is False
        import time
        for _ in range(50):
            d = c.get(f"/api/products/{pid}").json()
            if not d["refresh_in_progress"]:
                break
            time.sleep(0.1)
        assert d["reviews"]["available"] and d["reviews"]["reviews_count"] == 3551

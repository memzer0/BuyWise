"""AI answers for "Ask the reviews": excerpt verification, evidence guards, caching and the endpoint."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import create_app
from app.models import Product
from app.reviews import answer as svc

DATA = {"fetched_at": "2026-10-15T10:00:00+00:00", "reviews_count": 500, "user_reviews": [
    {"title": None, "text": "Battery easily lasts a full day. Great phone.", "rating": 5, "source": "amazon.in"},
    {"title": "Hot", "text": "It heats up a lot during games.", "rating": 2, "source": "flipkart.com"},
]}
EXC = [{"review_id": 0, "text": "Battery easily lasts a full day."}]


def _gemini(reply: str, calls: list | None = None) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": reply}]}}]})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _clear_cache():  # noqa: ANN202
    svc._CACHE.clear()
    yield
    svc._CACHE.clear()


def _s(settings):  # noqa: ANN001, ANN202
    return settings.model_copy(update={"gemini_api_key": "g"})


def test_verified_excerpts_and_grounded_answer(settings):  # noqa: ANN001
    calls: list = []
    res = asyncio.run(svc.answer(_s(settings), 1, DATA, "How is the battery?", EXC, ["Battery"], None,
                                 _gemini("One reviewer says the battery lasts a full day [1].", calls)))
    assert res["status"] == "ok" and res["citations"] == [1] and res["cached"] is False
    prompt = calls[0].read().decode()
    assert "[1] (5" in prompt and "Battery easily lasts a full day." in prompt and "Battery: mentioned in 1 of 2 reviews" in prompt
    # second identical question is served from the cache – no second AI call
    again = asyncio.run(svc.answer(_s(settings), 1, DATA, "how is the battery?", EXC, ["Battery"], None, _gemini("x", calls)))
    assert again["cached"] is True and again["answer"] == res["answer"] and len(calls) == 1


def test_rejects_excerpts_not_in_stored_reviews(settings):  # noqa: ANN001
    for bad in ([{"review_id": 0, "text": "Battery is terrible."}], [{"review_id": 9, "text": "Great phone."}]):
        with pytest.raises(svc.ReviewAnswerError) as e:
            asyncio.run(svc.answer(_s(settings), 1, DATA, "battery?", bad, [], None, _gemini("x [1]")))
        assert e.value.status == 422


@pytest.mark.parametrize("reply,why", [
    ("Battery lasts a full day.", "citations"),                       # no citation
    ("Battery lasts a full day [3].", "citations"),                   # cites an excerpt that wasn't given
    ("90% of owners love the battery [1].", "numbers"),               # invented statistic
    ("A reviewer wrote “the battery never dies at all” [1].", "quotes"),  # invented quotation
])
def test_guard_rejects_unsupported_replies(settings, reply, why):  # noqa: ANN001
    res = asyncio.run(svc.answer(_s(settings), 1, DATA, "battery?", EXC, ["Battery"], None, _gemini(reply)))
    assert res["status"] == "rejected" and res["reason"] == why and res["answer"] is None


def test_falls_back_to_lite_model_when_gemini_is_overloaded(settings):  # noqa: ANN001
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        if len(urls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Battery lasts a full day [1]."}]}}]})
    res = asyncio.run(svc.answer(_s(settings), 1, DATA, "battery?", EXC, ["Battery"], None,
                                 httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert res["status"] == "ok" and res["model"] == svc.GEMINI_FALLBACK_MODEL
    assert settings.gemini_model in urls[0] and svc.GEMINI_FALLBACK_MODEL in urls[1]


def test_falls_back_when_primary_model_times_out(settings):  # noqa: ANN001
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        if len(urls) == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Battery lasts a full day [1]."}]}}]})
    res = asyncio.run(svc.answer(_s(settings), 1, DATA, "battery?", EXC, ["Battery"], None,
                                 httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert res["status"] == "ok" and res["model"] == svc.GEMINI_FALLBACK_MODEL and len(urls) == 2


def test_insufficient_and_not_configured(settings):  # noqa: ANN001
    res = asyncio.run(svc.answer(_s(settings), 1, DATA, "warranty?", EXC, [], None, _gemini("INSUFFICIENT")))
    assert res["status"] == "insufficient"
    with pytest.raises(svc.ReviewAnswerError) as e:
        asyncio.run(svc.answer(settings, 1, DATA, "battery?", EXC, [], None))
    assert e.value.status == 503


def test_endpoint(settings, db_url):  # noqa: ANN001
    app = create_app(settings)
    with TestClient(app) as c:
        with SessionLocal() as db:
            p = Product(title="Phone X", review_data=DATA)
            db.add(p)
            db.commit()
            pid = p.id
        assert c.post(f"/api/products/{pid}/reviews/ask", json={"question": "battery?", "excerpts": EXC}).status_code == 503
        assert c.post("/api/products/99999/reviews/ask", json={"question": "battery?"}).status_code == 404
        assert c.post(f"/api/products/{pid}/reviews/ask", json={"question": "x" * 300}).status_code == 422

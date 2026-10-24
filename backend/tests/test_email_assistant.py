"""E-mail notifications (SMTP mocked) and the AI assistant (HTTP mocked) – nothing leaves the test machine."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assistant import service as assistant
from app.main import create_app
from app.providers.registry import ProviderRegistry
from app.regret.service import today_ist
from app.services import mailer
from tests.fakes import FakeProvider, row

CATALOG = {"iphone 16": [row("a1", "Apple iPhone 16 (Black, 128 GB)", 69999, "Shop A", availability="in_stock")]}
ME = {"X-Client-Id": "email-client-0001"}


class FakeSMTP:
    sent: list = []

    def __init__(self, *a, **k): pass  # noqa: ANN002, ANN003
    def __enter__(self): return self  # noqa: ANN204
    def __exit__(self, *a): return False  # noqa: ANN002
    def starttls(self, **k): pass  # noqa: ANN003
    def login(self, u, p): pass  # noqa: ANN001
    def send_message(self, msg): FakeSMTP.sent.append(msg)  # noqa: ANN001


@pytest.fixture()
def smtp(monkeypatch):  # noqa: ANN001, ANN201
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def client(settings, **over):  # noqa: ANN001, ANN003, ANN201
    s = settings.model_copy(update=over)
    return TestClient(create_app(s, ProviderRegistry(s, [FakeProvider(s, CATALOG, provider_id="prov_a")])))


def test_mailer_reports_not_configured(settings):  # noqa: ANN001
    assert mailer.send_email(settings, "a@b.com", "x", "y")[0] == "not_configured"


def test_regret_shield_emails_each_event_once(settings, db_url, smtp):  # noqa: ANN001
    with client(settings, smtp_host="smtp.gmail.com", smtp_from="buywise@example.com", smtp_username="u", smtp_password="p") as c:
        pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
        r = c.post("/api/purchases", headers=ME, json={"product_id": pid, "retailer": "Shop A", "purchase_price": 75000,
                                                       "purchase_date": today_ist().isoformat(), "email": "Me@Example.com"})
        assert r.status_code == 201 and r.json()["email"] == "me@example.com"
        assert len(smtp.sent) == 1 and "price drop" in smtp.sent[0]["Subject"] and smtp.sent[0]["To"] == "me@example.com"
        c.patch(f"/api/purchases/{r.json()['id']}", headers=ME, json={"notify": True})  # re-check: same event → no 2nd mail
        assert len(smtp.sent) == 1
        n = c.get("/api/purchases/notifications", headers=ME).json()["items"][0]
        assert n["email_status"] == "sent"
        assert c.get("/api/purchases", headers=ME).json()["email_ready"] is True


def test_invalid_email_rejected(settings, db_url):  # noqa: ANN001
    with client(settings) as c:
        pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
        r = c.post("/api/purchases", headers=ME, json={"product_id": pid, "retailer": "Shop A", "purchase_price": 70000,
                                                       "purchase_date": today_ist().isoformat(), "email": "not-an-email"})
        assert r.status_code == 422


def test_test_email_is_admin_only(settings, db_url, smtp):  # noqa: ANN001
    with client(settings, smtp_host="smtp.gmail.com", smtp_from="buywise@example.com") as c:
        assert c.post("/api/admin/test-email", json={"email": "me@example.com"}).status_code == 401
        r = c.post("/api/admin/test-email", json={"email": "me@example.com"}, headers={"Authorization": "Bearer test-admin-token"})
        assert r.json() == {"status": "sent", "error": None} and len(smtp.sent) == 1


# ---------------------------------------------------------------- assistant
def _mock(handler):  # noqa: ANN001, ANN202
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_assistant_gemini_grounded(settings):  # noqa: ANN001
    s = settings.model_copy(update={"gemini_api_key": "g-key"})
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["key"] = req.headers["x-goog-api-key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Buy at Shop A for ₹69,999."}]}}]})

    res = asyncio.run(assistant.ask(s, [{"role": "user", "content": "Where is it cheapest?"}], "Current: Shop A ₹69,999", _mock(handler)))
    assert res == {"reply": "Buy at Shop A for ₹69,999.", "provider": "gemini", "model": "gemini-flash-latest"}
    assert seen["key"] == "g-key" and "Shop A ₹69,999" in seen["body"]["system_instruction"]["parts"][0]["text"]
    assert "Never invent a" in seen["body"]["system_instruction"]["parts"][0]["text"]


def test_assistant_anthropic_and_errors(settings):  # noqa: ANN001
    s = settings.model_copy(update={"anthropic_api_key": "a-key"})
    ok = _mock(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": "Hello"}]}))
    res = asyncio.run(assistant.ask(s, [{"role": "assistant", "content": "hi"}, {"role": "user", "content": "hey"}], "", ok))
    assert res["provider"] == "anthropic" and res["reply"] == "Hello"
    with pytest.raises(assistant.AssistantError) as e:
        asyncio.run(assistant.ask(s, [{"role": "user", "content": "x"}], "", _mock(lambda r: httpx.Response(401))))
    assert e.value.code == "assistant_auth"
    with pytest.raises(assistant.AssistantError) as e:
        asyncio.run(assistant.ask(s, [{"role": "user", "content": "x"}], "", _mock(lambda r: httpx.Response(429))))
    assert e.value.code == "assistant_rate_limited"


def test_assistant_api_not_configured_and_context(settings, db_url, monkeypatch):  # noqa: ANN001
    with client(settings) as c:
        assert c.get("/api/assistant/status").json()["configured"] is False
        r = c.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 503 and r.json()["error"]["code"] == "assistant_not_configured"
    captured = {}

    async def fake_ask(s, messages, context, client=None):  # noqa: ANN001, ANN202
        captured["context"] = context
        return {"reply": "ok", "provider": "gemini", "model": "m"}

    monkeypatch.setattr(assistant, "ask", fake_ask)
    with client(settings, gemini_api_key="k") as c:
        pid = c.get("/api/search", params={"q": "iphone 16"}).json()["results"][0]["id"]
        r = c.post("/api/assistant/chat", json={"messages": [{"role": "user", "content": "worth it?"}], "product_id": pid}).json()
        assert r["grounded_on_product"] is True and "Shop A: ₹69,999" in captured["context"]

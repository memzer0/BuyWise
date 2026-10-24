"""BuyWise AI shopping assistant (the chat bubble).

The model only sees facts BuyWise already has – the product the shopper is looking at, its current verified store
prices, deal score, decision and price-history summary – and is told not to invent prices, offers or dates.
API keys live in backend/.env and are only used here, server-side. Gemini is used when GEMINI_API_KEY is set,
otherwise Claude when ANTHROPIC_API_KEY is set; with neither, the assistant reports that it isn't set up.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MAX_TURNS = 12
MAX_CHARS = 2000

SYSTEM = """You are the BuyWise shopping assistant for electronics buyers in India. Be friendly, short and practical
(at most about 120 words unless asked for more). Use ₹ and Indian number formatting.

Rules:
- For prices, stores, deal scores, price history and verdicts use ONLY the BuyWise data given below. Never invent a
  price, discount, coupon, bank offer, stock level, sale date or warranty. If something isn't in the data, say BuyWise
  doesn't have it and suggest checking the store page.
- Never claim a store will refund a difference, match a price or accept a return.
- General product knowledge (what a spec means, which features matter, how to choose) is fine – say it's general advice.
- You cannot place orders, log in to stores or see the user's accounts.
- If asked about something unrelated to shopping/electronics, answer briefly and steer back to BuyWise.

BuyWise data for this conversation:
{context}"""


@dataclass
class AssistantError(Exception):
    code: str
    message: str
    status: int = 502


def provider(s: Settings) -> str | None:
    if s.gemini_api_key:
        return "gemini"
    if s.anthropic_api_key:
        return "anthropic"
    return None


def product_context(d: dict, history: dict | None) -> str:
    """A compact, factual summary of what BuyWise knows about one product."""
    p = d["product"]
    lines = [f"Product: {p['title']} (BuyWise id {p['id']})"]
    specs = [f"{k}: {v}" for k, v in (("Brand", p.get("brand")), ("Storage GB", p.get("storage_gb")), ("RAM GB", p.get("ram_gb")),
                                      ("Colour", p.get("colour")), ("Condition", p.get("condition"))) if v]
    if specs:
        lines.append("Specs: " + ", ".join(specs))
    offers = sorted((o for o in d["offers"] if o["eligible_for_best_price"] and o["price"] is not None), key=lambda o: o["price"])
    if offers:
        lines.append("Current verified prices from trusted stores (cheapest first):")
        lines += [f"- {o['retailer']}: ₹{o['price']:,.0f}" + (" (lowest)" if o["is_best_price"] else "")
                  + (f", shipping ₹{o['shipping_cost']:,.0f}" if o.get("shipping_cost") else "") for o in offers[:8]]
    else:
        lk = d["summary"].get("last_known")
        lines.append("No current verified price." + (f" Last seen ₹{lk['price']:,.0f} at {lk['retailer']} on {lk['date']}." if lk else ""))
    deal = d["deal"]
    lines.append(f"Deal score: {deal['score'] if deal['score'] is not None else 'not available'} ({deal['label']})")
    dec = d["decision"]
    lines.append(f"BuyWise decision: {dec['label']} – {dec['headline']} Reasons: {' '.join(dec['reasons'][:3])}")
    if history:
        lines.append(f"Price history (lowest price across stores): lowest ₹{history['lowest'] or 0:,.0f}, highest ₹{history['highest'] or 0:,.0f}, "
                     f"average ₹{history['average'] or 0:,.0f}, {history['observation_count']} real price observations.")
    fp = d.get("final_price") or {}
    if fp.get("banks_mentioned"):
        lines.append("Banks mentioned in store offer notes: " + ", ".join(fp["banks_mentioned"]))
    return "\n".join(lines)


def _clean(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages[-MAX_TURNS:]:
        role = "assistant" if m.get("role") == "assistant" else "user"
        text = str(m.get("content", ""))[:MAX_CHARS].strip()
        if text:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


async def ask(s: Settings, messages: list[dict], context: str, client: httpx.AsyncClient | None = None) -> dict:
    which = provider(s)
    if which is None:
        raise AssistantError("assistant_not_configured",
                             "The AI assistant isn't set up yet: add GEMINI_API_KEY (or ANTHROPIC_API_KEY) to backend/.env "
                             "and restart BuyWise.", 503)
    msgs = _clean(messages)
    if not msgs:
        raise AssistantError("empty_message", "Type a question first.", 422)
    system = SYSTEM.format(context=context or "No specific product is open. You can still help with general shopping questions "
                                              "and explain how BuyWise works (search, compare stores, deal score, price alerts, Regret Shield).")
    own = client is None
    client = client or httpx.AsyncClient(timeout=s.assistant_timeout_seconds)
    try:
        if which == "gemini":
            r = await client.post(GEMINI_URL.format(model=s.gemini_model), headers={"x-goog-api-key": s.gemini_api_key or ""}, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in msgs],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700},
            })
            data = _json_or_error(r, "Gemini")
            parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            model = s.gemini_model
        else:
            r = await client.post(ANTHROPIC_URL, headers={"x-api-key": s.anthropic_api_key or "", "anthropic-version": "2023-06-01"},
                                  json={"model": s.anthropic_model, "max_tokens": 700, "system": system, "messages": msgs})
            data = _json_or_error(r, "Claude")
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
            model = s.anthropic_model
    except httpx.TimeoutException as exc:
        raise AssistantError("assistant_timeout", "The AI service took too long to answer. Please try again.", 504) from exc
    except httpx.HTTPError as exc:
        raise AssistantError("assistant_unreachable", "Couldn't reach the AI service. Check your internet connection.", 502) from exc
    finally:
        if own:
            await client.aclose()
    if not text:
        raise AssistantError("assistant_empty", "The AI service returned no answer (it may have been blocked). Try rephrasing.", 502)
    return {"reply": text, "provider": which, "model": model}


def _json_or_error(r: httpx.Response, name: str) -> dict:
    if r.status_code in (401, 403):
        raise AssistantError("assistant_auth", f"{name} rejected the API key – check it in backend/.env.", 502)
    if r.status_code == 404:
        log.warning("%s model not found: %s", name, r.text[:300])
        raise AssistantError("assistant_model", f"{name} doesn't recognise the model name – check the *_MODEL setting in backend/.env.", 502)
    if r.status_code == 429:
        raise AssistantError("assistant_rate_limited", f"{name} usage limit reached for now. Please wait a minute and try again.", 429)
    if r.status_code >= 400:
        log.warning("%s API error %s", name, r.status_code)
        raise AssistantError("assistant_error", f"{name} returned an error (HTTP {r.status_code}).", 502)
    try:
        return r.json()
    except ValueError as exc:
        raise AssistantError("assistant_error", f"{name} sent an unreadable answer.", 502) from exc

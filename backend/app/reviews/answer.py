"""AI-written answers for "Ask the reviews", grounded in excerpts the server has verified.

Flow: the review section retrieves matching review sentences (deterministic, see frontend askReviews.ts) and sends
the question + those excerpts. Here every excerpt is checked to be a verbatim part of a review stored for that
product, the aspect statistics are recomputed from the stored reviews, and only then is the model asked to answer
from that evidence alone. The reply is rejected (and the UI keeps its extractive answer) if it cites an excerpt that
wasn't given, quotes text that isn't in the excerpts, or contains a number that isn't in the evidence.
Answers are cached per product, review snapshot, question and excerpt set to avoid repeat AI calls.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict

import httpx

from app.assistant.service import ANTHROPIC_URL, GEMINI_URL, AssistantError, _json_or_error, provider
from app.core.config import Settings
from app.reviews.analyze import analyze

log = logging.getLogger(__name__)

SYSTEM = """You summarise what customer reviews say, for a shopper in India. Use ONLY the numbered review excerpts and
the review statistics below – no outside knowledge about the product.
Rules:
- Answer the shopper's question in at most 3 short sentences (under 70 words).
- Back every claim with the excerpt number(s) in square brackets, e.g. [1] or [2][3].
- Do not quote text that isn't in the excerpts, and do not use any number that isn't in the statistics or excerpts.
- If statistics say "low confidence" or the sample is small, say these are a few individual experiences.
- If the excerpts don't answer the question, reply with exactly: INSUFFICIENT
- Don't recommend buying or not buying; just report what reviewers say."""

GEMINI_FALLBACK_MODEL = "gemini-flash-lite-latest"
PRIMARY_TIMEOUT_SECONDS = 12.0
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
CACHE_MAX = 256
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
QUOTE_RE = re.compile(r"[“\"]([^”\"]{10,})[”\"]")
CITE_RE = re.compile(r"\[(\d+)\]")


class ReviewAnswerError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("‘", "'")).strip().lower()


def verify_excerpts(review_data: dict | None, excerpts: list[dict]) -> list[dict]:
    """Keep the excerpts' order; raise if any isn't a verbatim part of the stored review it claims to come from."""
    reviews = [r for r in ((review_data or {}).get("user_reviews") or []) if isinstance(r, dict) and (r.get("text") or r.get("title"))]
    out = []
    for e in excerpts:
        i = e["review_id"]
        if not 0 <= i < len(reviews):
            raise ReviewAnswerError(422, "unknown_review", "An excerpt refers to a review this product doesn't have.")
        r = reviews[i]
        full = _norm(". ".join(x for x in (r.get("title"), r.get("text")) if x))
        if _norm(e["text"]) not in full:
            raise ReviewAnswerError(422, "excerpt_mismatch", "An excerpt doesn't match the stored review text.")
        out.append({"review_id": i, "text": e["text"].strip(), "rating": r.get("rating"), "source": r.get("source")})
    return out


def stat_lines(analysis: dict, aspects: list[str]) -> list[str]:
    n = analysis.get("coverage", {}).get("sample_size", 0)
    by = {a["aspect"]: a for a in analysis.get("aspects") or []}
    lines = [f"Written reviews analysed: {n}" + (f" (of {analysis['coverage']['total_ratings']} ratings)"
                                                if analysis.get("coverage", {}).get("total_ratings") else "")]
    for name in aspects[:5]:
        a = by.get(name)
        if not a:
            lines.append(f"{name}: mentioned in 0 of {n} reviews")
        else:
            lines.append(f"{name}: mentioned in {a['mentions']} of {n} reviews – {a['positive']} positive, {a['negative']} "
                         f"negative, {a['mixed']} mixed; {a['confidence']} confidence")
    return lines


def guard(reply: str, excerpts: list[dict], evidence_text: str) -> str | None:
    """Why the reply can't be shown, or None when it only uses the evidence."""
    cites = {int(c) for c in CITE_RE.findall(reply)}
    if not cites or any(c < 1 or c > len(excerpts) for c in cites):
        return "citations"
    body = CITE_RE.sub("", reply)
    allowed = set(NUM_RE.findall(evidence_text))
    if any(num not in allowed for num in NUM_RE.findall(body)):
        return "numbers"
    joined = _norm(" ".join(e["text"] for e in excerpts))
    if any(_norm(q) not in joined for q in QUOTE_RE.findall(body)):
        return "quotes"
    return None


async def answer(s: Settings, product_id: int, review_data: dict | None, question: str, excerpts_in: list[dict],
                 aspects: list[str], use_case: str | None, client: httpx.AsyncClient | None = None) -> dict:
    which = provider(s)
    if which is None:
        raise ReviewAnswerError(503, "assistant_not_configured", "AI answers aren't set up on this server.")
    excerpts = verify_excerpts(review_data, excerpts_in)
    if not excerpts:
        return {"status": "insufficient", "answer": None, "citations": [], "cached": False}
    analysis = analyze(review_data)
    key = (product_id, (review_data or {}).get("fetched_at"), _norm(question), tuple(e["review_id"] for e in excerpts),
           tuple(aspects), use_case)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return {**_CACHE[key], "cached": True}

    stats = stat_lines(analysis, aspects)
    numbered = [f"[{i}] ({e['rating']}★, {e['source'] or 'unknown source'}) {e['text']}" if e["rating"] is not None
                else f"[{i}] ({e['source'] or 'unknown source'}) {e['text']}" for i, e in enumerate(excerpts, 1)]
    uc = next((u["label"] for u in analysis.get("use_cases") or [] if u["key"] == use_case), None)
    evidence = "Review statistics:\n" + "\n".join(stats) + "\n\nReview excerpts:\n" + "\n".join(numbered)
    user = (f"Shopper's use case: {uc}\n" if uc else "") + f"Question: {question}\n\n{evidence}"

    own = client is None
    client = client or httpx.AsyncClient(timeout=s.assistant_timeout_seconds)
    try:
        if which == "gemini":
            # When the configured model is overloaded (HTTP 503 / 500), fall back once to the lighter model.
            # A hung request (timeout) counts as overloaded too, so the primary model gets a shorter time limit.
            models = [s.gemini_model] + ([GEMINI_FALLBACK_MODEL] if s.gemini_model != GEMINI_FALLBACK_MODEL else [])
            for i, model in enumerate(models):
                last = i == len(models) - 1
                if i:
                    await asyncio.sleep(0.5)
                try:
                    r = await client.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": s.gemini_api_key or ""}, json={
                        "system_instruction": {"parts": [{"text": SYSTEM}]},
                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800},
                    }, timeout=s.assistant_timeout_seconds if last else min(PRIMARY_TIMEOUT_SECONDS, s.assistant_timeout_seconds))
                except httpx.TimeoutException:
                    if last:
                        raise
                    log.info("review answer: %s timed out, trying %s", model, models[i + 1])
                    continue
                if r.status_code not in (500, 503):
                    break
            data = _json_or_error(r, "Gemini")
            parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        else:
            r = await client.post(ANTHROPIC_URL, headers={"x-api-key": s.anthropic_api_key or "", "anthropic-version": "2023-06-01"},
                                  json={"model": s.anthropic_model, "max_tokens": 400, "system": SYSTEM,
                                        "messages": [{"role": "user", "content": user}]})
            data = _json_or_error(r, "Claude")
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
            model = s.anthropic_model
    except AssistantError as e:
        raise ReviewAnswerError(e.status, e.code, e.message) from None
    except httpx.TimeoutException as exc:
        raise ReviewAnswerError(504, "assistant_timeout", "The AI service took too long to answer.") from exc
    except httpx.HTTPError as exc:
        raise ReviewAnswerError(502, "assistant_unreachable", "Couldn't reach the AI service.") from exc
    finally:
        if own:
            await client.aclose()

    if not text or text.strip().upper().startswith("INSUFFICIENT"):
        result = {"status": "insufficient", "answer": None, "citations": [], "provider": which, "model": model}
    else:
        why = guard(text, excerpts, evidence + "\n" + question)
        if why:
            log.info("review answer rejected (%s) for product %s", why, product_id)
            result = {"status": "rejected", "answer": None, "citations": [], "provider": which, "model": model, "reason": why}
        else:
            result = {"status": "ok", "answer": text, "citations": sorted({int(c) for c in CITE_RE.findall(text)}),
                      "provider": which, "model": model}
    _CACHE[key] = result
    if len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)
    return {**result, "cached": False}

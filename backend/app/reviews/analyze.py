"""Review intelligence over the reviews Google Shopping returns for a product (real review text only).

* Aspects: each sentence that mentions an aspect (battery, camera, heating …) is scored with a small positive /
  negative word list (with simple negation). Counts are per REVIEW: a review is positive, negative or mixed about an
  aspect depending on its sentences. Every insight carries the number of reviews behind it, the share of the sample
  and a confidence level, and points at verbatim excerpts – BuyWise never writes opinions of its own.
* Coverage: the sample Google Shopping shows is usually a handful of reviews out of thousands of ratings, so the
  result says how much of the total it covers and avoids product-wide conclusions from small samples.
* Reliability: only evidence-based collection signals – near-identical wording, "incentivized" as marked by the
  source, and many reviews posted on the same exact day (only when the source gives exact dates). Ratings, sentiment
  and review length are never used to question a review, and verified-purchase status / reviewer history are not
  available from the source, so they are not claimed.
* Use cases: which aspects matter for coding, gaming, photography, office work or everyday use, and why. Used by the
  UI to put relevant insights first – negative feedback is never hidden.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

ASPECTS: dict[str, tuple[str, ...]] = {
    "Battery": ("battery", "backup", "battery life", "drain", "drains", "mah", "lasts a day", "full day"),
    "Performance": ("performance", "speed", "fast", "lag", "laggy", "lags", "smooth", "processor", "chip", "hang", "hangs",
                    "multitasking", "snappy", "slow"),
    "Heating": ("heat", "heating", "heats", "hot", "warm", "temperature", "overheat", "overheating"),
    "Display": ("display", "screen", "brightness", "amoled", "oled", "refresh rate", "panel", "resolution"),
    "Camera": ("camera", "photo", "photos", "picture", "pictures", "video", "videos", "selfie", "lens", "zoom", "portrait"),
    "Sound": ("sound", "audio", "speaker", "speakers", "bass", "volume", "noise cancellation", "anc", "mic", "microphone"),
    "Build & design": ("build", "design", "look", "looks", "premium", "weight", "finish", "quality", "keyboard",
                       "hinge", "material"),
    "Durability": ("durable", "durability", "lasted", "broke", "stopped working", "dead after", "long lasting", "sturdy",
                   "scratch", "scratches", "crack", "cracked", "wear"),
    "Charging": ("charging", "charger", "charge", "fast charging", "wireless charging"),
    "Software": ("software", "update", "updates", "ui", "bloatware", "ads", "os", "bug", "bugs", "ios", "android"),
    "Connectivity": ("network", "wifi", "wi-fi", "bluetooth", "signal", "5g", "connection", "hotspot"),
    "Customer service": ("customer service", "customer care", "support", "service center", "service centre", "warranty",
                         "replacement", "refund"),
    "Delivery & packaging": ("delivery", "delivered", "packaging", "package", "box", "seller", "courier", "shipping"),
    "Value for money": ("value", "price", "worth", "expensive", "cheap", "money", "costly", "overpriced", "budget"),
}
POS = {"good", "great", "excellent", "amazing", "awesome", "best", "nice", "love", "loved", "smooth", "fast", "superb",
       "perfect", "worth", "solid", "bright", "clear", "crisp", "long", "premium", "happy", "satisfied", "impressive",
       "fantastic", "recommend", "recommended", "reliable", "decent", "lasts", "brilliant", "sturdy", "durable", "snappy",
       "helpful", "quick", "cool"}
NEG = {"bad", "poor", "worst", "terrible", "awful", "slow", "lag", "laggy", "lags", "heats", "heating", "hot", "drain",
       "drains", "issue", "issues", "problem", "problems", "broken", "broke", "defective", "disappointed", "disappointing",
       "waste", "hang", "hangs", "weak", "dull", "overpriced", "expensive", "noisy", "damaged", "fake", "return",
       "returned", "bug", "bugs", "crash", "crashes", "faulty", "useless", "average", "mediocre", "overheating",
       "overheats", "cracked", "scratches", "unhelpful", "rude", "delayed", "struggle", "struggles", "struggled",
       "struggling", "annoying", "regret", "glitch", "glitches", "glitchy", "freezes", "dies"}
NEGATORS = {"not", "no", "never", "isn't", "wasn't", "don't", "doesn't", "didn't", "hardly", "without"}
# phrases whose positive-looking words ("fast", "quickly") actually describe a problem
NEG_PHRASE_RE = re.compile(r"\b(drains? (fast|quickly)|dies (fast|quickly)|heats up (fast|quickly)|stopped working)\b", re.I)
WORD_RE = re.compile(r"[a-z0-9'+-]+")

# Which aspects matter for each use case, and why (shown next to the matching insights).
USE_CASES: dict[str, tuple[str, dict[str, str]]] = {
    "everyday": ("Everyday use", {
        "Battery": "You'll want it to last a full day without charging.",
        "Durability": "It should keep working after months of daily handling.",
        "Camera": "Most everyday photos are taken on the go.",
        "Software": "Updates, bugs and ads affect every day of use.",
        "Value for money": "Whether owners feel it was worth the price.",
    }),
    "gaming": ("Gaming", {
        "Performance": "Lag or stutter shows up first in games.",
        "Heating": "Long gaming sessions push temperatures up.",
        "Battery": "Games drain the battery much faster than normal use.",
        "Display": "Refresh rate and brightness shape how games look.",
        "Sound": "Speakers and audio matter for immersion.",
    }),
    "photography": ("Photography", {
        "Camera": "The core of the experience for photos and video.",
        "Display": "You judge and edit shots on the screen.",
        "Performance": "Slow processing means missed moments.",
        "Battery": "Shooting all day drains the battery.",
        "Heating": "Video recording can make devices hot.",
    }),
    "coding": ("Coding", {
        "Performance": "Builds, IDEs and multitasking need a fast processor.",
        "Display": "You'll read code on it for hours.",
        "Battery": "Working unplugged depends on battery life.",
        "Heating": "Sustained load from builds heats devices up.",
        "Build & design": "Keyboard and build quality matter for long sessions.",
    }),
    "office": ("Office work", {
        "Battery": "A workday away from a charger.",
        "Display": "Spreadsheets and documents all day.",
        "Performance": "Many apps and browser tabs at once.",
        "Connectivity": "Reliable Wi-Fi and Bluetooth for calls.",
        "Sound": "Microphone and speakers for meetings.",
    }),
}

MIN_STANCE_MENTIONS = 2   # fewer reviews than this → "limited evidence", no praise/complaint label
EXCERPT_MAX = 240


def _words(t: str) -> list[str]:
    return WORD_RE.findall(t.lower().replace("’", "'").replace("‘", "'"))  # curly apostrophes: don’t → don't


def sentiment(text: str) -> int:
    """+1 / -1 / 0 for a sentence using the word lists with one-word negation."""
    ws = _words(text)
    score = -2 * len(NEG_PHRASE_RE.findall(text))
    for i, w in enumerate(ws):
        neg = i > 0 and ws[i - 1] in NEGATORS or i > 1 and ws[i - 2] in NEGATORS
        if w in POS:
            score += -1 if neg else 1
        elif w in NEG:
            score += 1 if neg else -1
    return (score > 0) - (score < 0)


def _aspects_in(sentence: str) -> list[str]:
    low = " " + sentence.lower() + " "
    return [a for a, keys in ASPECTS.items() if any(re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low) for k in keys)]


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


CLAUSE_RE = re.compile(r"\s*(?:[,;]|\b(?:but|however|though|although|whereas|while)\b)\s*", re.I)


def _clause_aspects(sentence: str) -> list[tuple[str, int]]:
    """(aspect, sentiment) per clause, so "battery is good but it heats" scores battery + and heating −."""
    out: dict[str, list[int]] = {}
    for clause in CLAUSE_RE.split(sentence):
        if clause.strip():
            sv = sentiment(clause)
            for a in _aspects_in(clause):
                out.setdefault(a, []).append(sv)
    return [(a, v) for a, vs in out.items() for v in vs]


def _excerpt(s: str) -> str:
    return s if len(s) <= EXCERPT_MAX else s[:EXCERPT_MAX - 1].rstrip() + "…"


def _exact_date(value: object) -> date | None:
    """Only absolute dates count for timing analysis ("3 months ago" is too coarse)."""
    if not isinstance(value, str) or "ago" in value.lower():
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _confidence(mentions: int, sample: int) -> str:
    if mentions < 3 or sample < 5:
        return "low"
    return "medium" if mentions < 8 else "high"


def _coverage(sample: int, total: object, duplicates: int = 0) -> dict:
    total_n = total if isinstance(total, int) and total > 0 else None
    pct = round(sample / total_n * 100, 2) if total_n else None
    if sample < 5:
        level, note = "low", f"Only {sample} written review{'s' if sample != 1 else ''} available – treat these as individual experiences, not a verdict."
    elif sample < 15 or (pct is not None and pct < 1):
        level, note = "medium", f"{sample} written reviews – enough to spot recurring themes, not to measure how common they are."
    else:
        level, note = "high", f"{sample} written reviews – recurring themes are reasonably well supported."
    if total_n:
        note += f" They are {pct:g}% of the {total_n:,} ratings this product has."
    if duplicates:
        note += f" {duplicates} near-duplicate review{'s are' if duplicates != 1 else ' is'} listed but not counted twice."
    return {"sample_size": sample, "total_ratings": total_n, "coverage_pct": pct, "level": level, "note": note,
            "duplicates_excluded": duplicates}


def analyze(data: dict | None) -> dict:
    """`data`: stored review payload {rating, reviews_count, ratings, user_reviews, insights}. Returns UI-ready result."""
    if not data:
        return {"available": False, "reason": "No reviews have been fetched for this product yet."}
    if data.get("empty"):
        return {"available": False, "reason": "Google Shopping returned no reviews for this product."}
    reviews = [r for r in (data.get("user_reviews") or []) if isinstance(r, dict) and (r.get("text") or r.get("title"))]
    n = len(reviews)
    token_sets = [set(_words(f"{r.get('title') or ''} {r.get('text') or ''}")) for r in reviews]
    dupes_of = [[i for i in range(n) if i != idx and len(token_sets[idx]) >= 6 and _jaccard(token_sets[idx], token_sets[i]) >= 0.8]
                for idx in range(n)]
    # a near-duplicate of an earlier review is listed but not counted again in the aspect statistics
    counted = [not any(i < idx for i in dupes_of[idx]) for idx in range(n)]
    n_unique = sum(counted)
    out_reviews: list[dict] = []
    stats: dict[str, dict] = {}
    for idx, r in enumerate(reviews):
        text = ". ".join(x for x in (r.get("title"), r.get("text")) if x).strip()
        per_aspect: dict[str, list[int]] = {}
        for s in _sentences(text):
            for a, sv in _clause_aspects(s):
                per_aspect.setdefault(a, []).append(sv)
                if not counted[idx]:
                    continue
                st = stats.setdefault(a, {"aspect": a, "mentions": 0, "positive": 0, "negative": 0, "mixed": 0, "neutral": 0,
                                          "examples": []})
                if len(s) >= 12 and sum(1 for e in st["examples"] if e["sentiment"] == sv) < 3 and \
                        not any(e["review_id"] == idx for e in st["examples"]):
                    st["examples"].append({"review_id": idx, "text": _excerpt(s), "sentiment": sv})
        aspect_sentiment: dict[str, str] = {}
        for a, svs in per_aspect.items():
            pos, neg = any(v > 0 for v in svs), any(v < 0 for v in svs)
            label = "mixed" if pos and neg else "positive" if pos else "negative" if neg else "neutral"
            aspect_sentiment[a] = label
            if counted[idx]:
                stats[a]["mentions"] += 1
                stats[a][label] += 1

        signals = []
        if r.get("incentivized") is True:
            signals.append("Marked as incentivized by the source")
        dupes = dupes_of[idx]
        if dupes:
            signals.append("Nearly identical wording to another review")
        rating = r.get("rating") if isinstance(r.get("rating"), (int, float)) else None
        out_reviews.append({
            "id": idx, "title": r.get("title"), "text": r.get("text"), "user_name": r.get("user_name"),
            "source": r.get("source"), "rating": rating, "date": r.get("date"), "incentivized": r.get("incentivized"),
            "sentiment": sentiment(text), "aspects": sorted(per_aspect), "aspect_sentiment": aspect_sentiment,
            "signals": signals, "duplicate_of": dupes, "counted": counted[idx], "group": "flagged" if signals else "other",
        })

    aspects = []
    for st in sorted(stats.values(), key=lambda a: -a["mentions"]):
        m = st["mentions"]
        pos, neg = st["positive"], st["negative"]
        opinions = pos + neg + st["mixed"]   # reviews that actually express a view on this aspect
        if m >= MIN_STANCE_MENTIONS and opinions == 0:
            stance = "neutral"   # mentioned without a clear opinion
        elif opinions < MIN_STANCE_MENTIONS:
            stance = "limited"
        elif pos >= 0.6 * opinions and pos > neg:
            stance = "praised"
        elif neg >= 0.5 * opinions and neg > pos:
            stance = "complaint"
        else:
            stance = "mixed"
        aspects.append({**st, "share": round(m / n_unique, 3) if n_unique else 0, "stance": stance,
                        "confidence": _confidence(m, n_unique)})

    praised = [a["aspect"] for a in aspects if a["stance"] == "praised"][:4]
    complaints = [a["aspect"] for a in aspects if a["stance"] == "complaint"][:4]
    mixed = [a["aspect"] for a in aspects if a["stance"] == "mixed"][:3]
    parts = []
    if praised:
        parts.append(f"reviewers mostly praise {_join(praised)}")
    if complaints:
        parts.append(f"recurring complaints mention {_join(complaints)}")
    if mixed:
        parts.append(f"opinions are mixed on {_join(mixed)}")
    summary = (f"In the {n_unique} reviews available, " + "; ".join(parts) + ".") if parts else None

    insights = []
    for block in data.get("insights") or []:
        for it in (block.get("items") or []) if isinstance(block, dict) else []:
            if not isinstance(it, dict):
                continue
            for k in ("pros", "cons"):
                for v in it.get(k) or []:
                    if isinstance(v, str):
                        insights.append({"type": k[:-1], "text": v})
            if it.get("key_point"):
                insights.append({"type": "point", "text": str(it["key_point"])})
    dist = [{"stars": int(x.get("stars")), "count": int(x.get("amount") or 0)} for x in (data.get("ratings") or [])
            if isinstance(x, dict) and x.get("stars") is not None]

    return {
        "available": bool(out_reviews or dist),
        "origin": {"source": "Google Shopping", "live": True, "fetched_at": data.get("fetched_at"),
                   "stores": sorted({r["source"] for r in out_reviews if r["source"]})},
        "rating": data.get("rating"),
        "reviews_count": data.get("reviews_count"),
        "distribution": sorted(dist, key=lambda d: -d["stars"]),
        "coverage": _coverage(n_unique, data.get("reviews_count"), n - n_unique),
        "summary": summary,
        "aspects": aspects,
        "aspect_keywords": {a: list(k) for a, k in ASPECTS.items()},
        "use_cases": [{"key": k, "label": label, "aspects": [{"aspect": a, "why": why} for a, why in m.items()]}
                      for k, (label, m) in USE_CASES.items()],
        "insights": insights[:10],
        "reviews": out_reviews,
        "reliability": _reliability(reviews, out_reviews),
        "counts": {"flagged": sum(1 for r in out_reviews if r["signals"]), "other": sum(1 for r in out_reviews if not r["signals"])},
        "sample_note": f"Based on the {n} written review(s) Google Shopping shows for this product"
                       + (f" (out of {data['reviews_count']:,} ratings)" if isinstance(data.get("reviews_count"), int) else "") + ".",
        "method_note": "Aspects and sentiment are found with keyword rules on the review text; every insight links to "
                       "the reviews behind it.",
        "fetched_at": data.get("fetched_at"),
    }


def _reliability(raw: list[dict], out: list[dict]) -> dict:
    signals = []
    dup_ids = sorted({r["id"] for r in out if r["duplicate_of"]})
    if dup_ids:
        signals.append({"kind": "duplicate_text", "label": "Near-identical wording",
                        "detail": f"{len(dup_ids)} reviews share at least 80% of their words with another review. Copied "
                                  "text can mean reposted or templated reviews – or the same person posting twice.",
                        "review_ids": dup_ids})
    inc_ids = [r["id"] for r in out if r["incentivized"] is True]
    if inc_ids:
        signals.append({"kind": "incentivized", "label": "Incentivized reviews",
                        "detail": f"{len(inc_ids)} review(s) are marked by the source as written in exchange for a free "
                                  "product or other incentive.", "review_ids": inc_ids})
    days = [_exact_date(r.get("date")) for r in raw]
    exact = [d for d in days if d is not None]
    limitations = []
    if len(exact) >= 4:
        day, cnt = Counter(exact).most_common(1)[0]
        if cnt >= 4 and cnt / len(exact) >= 0.6:
            signals.append({"kind": "timing_cluster", "label": "Many reviews on one day",
                            "detail": f"{cnt} of {len(exact)} dated reviews were posted on {day.isoformat()}. A burst like "
                                      "this can follow a promotion – or a review campaign.",
                            "review_ids": [i for i, d in enumerate(days) if d == day]})
    elif any(r.get("date") for r in raw):
        limitations.append("Review dates are approximate (for example “3 months ago”), so posting patterns over time "
                           "can't be checked.")
    limitations += [
        "Verified-purchase status and reviewer history aren't provided by the source, so they aren't checked.",
        "Star ratings, sentiment and review length are never used to question a review.",
    ]
    if len(out) < 5:
        limitations.append("With fewer than 5 written reviews there is too little text to detect patterns reliably.")
    return {"signals": signals, "limitations": limitations,
            "checked": ["Near-identical wording", "Incentive disclosures from the source", "Posting-date bursts (exact dates only)"]}


def _join(items: list[str]) -> str:
    items = [i.lower() for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

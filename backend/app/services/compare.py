"""Side-by-side product comparison built only from data BuyWise already has stored (no provider calls).

For 2–4 products it returns one compact column per product and a factual summary: who is cheapest (and by how
much), best deal score, best rated, most stores, spec differences and what reviewers praise or complain about.
Every statement in the summary is computed from those numbers – nothing is guessed. Products with no current
verified price are compared on what is known and flagged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Product

MAX_COMPARE = 4


def _inr(v: float | None) -> str:
    if v is None:
        return "—"
    n = int(round(v))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    last3, rest = s[-3:], s[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return "₹" + ",".join(groups + [last3])


def _storage(gb: int | None) -> str | None:
    if not gb:
        return None
    return f"{gb // 1024} TB" if gb >= 1024 and gb % 1024 == 0 else f"{gb} GB"


def column(d: dict) -> dict:
    """One comparison column from a product_detail() result."""
    p = d["product"]
    best = next((o for o in d["offers"] if o.get("is_best_price")), None)
    rv = d.get("reviews") or {}
    aspects = rv.get("aspects") or []
    rating = rv.get("rating") if rv.get("available") else None
    ratings_count = rv.get("reviews_count") if rv.get("available") else None
    if rating is None and best and best.get("rating") is not None:
        rating, ratings_count = best["rating"], best.get("rating_count")
    hist = d.get("timing", {}).get("stats", {})
    return {
        "id": p["id"], "title": p["title"], "brand": p["brand"], "category": p["category"], "image_url": p["image_url"],
        "storage_gb": p["storage_gb"], "ram_gb": p["ram_gb"], "colour": p["colour"], "condition": p["condition"],
        "screen_inches": p["screen_inches"], "specs": p.get("specs") or {},
        "price": d["summary"]["lowest_verified_price"],
        "highest_price": d["summary"]["highest_verified_price"],
        "best_store": best["retailer"] if best else None,
        "best_url": best["product_url"] if best else None,
        "best_link_type": best["link_type"] if best else None,
        "availability": best["availability"] if best else None,
        "store_count": d["summary"]["verified_offer_count"],
        "last_known": d["summary"].get("last_known"),
        "last_verified_at": p.get("last_verified_at"),
        "deal_score": d["deal"].get("score"), "deal_label": d["deal"].get("label"),
        "buywise_score": d["score"].get("score"),
        "decision": {"verdict": d["decision"]["verdict"], "label": d["decision"]["label"], "headline": d["decision"]["headline"]},
        "rating": rating, "ratings_count": ratings_count,
        "praised": [a["aspect"] for a in aspects if a.get("stance") == "praised"][:4],
        "complaints": [a["aspect"] for a in aspects if a.get("stance") == "complaint"][:4],
        "reviews_analysed": (rv.get("coverage") or {}).get("sample_size", 0),
        "history": {"lowest": hist.get("lowest"), "average": hist.get("average"), "highest": hist.get("highest")},
    }


def _short(c: dict) -> str:
    t = c["title"]
    return t if len(t) <= 48 else t[:47].rstrip() + "…"


def summarize(cols: list[dict]) -> dict:
    """Factual highlights, differences and caveats for 2+ columns."""
    highlights: list[dict] = []
    differences: list[str] = []
    notes: list[str] = []
    priced = sorted((c for c in cols if c["price"] is not None), key=lambda c: c["price"])

    if len(priced) >= 2:
        a, b = priced[0], priced[1]
        gap = b["price"] - a["price"]
        text = (f"{_short(a)} is the cheapest at {_inr(a['price'])} ({a['best_store']})"
                + (f", {_inr(gap)} less than {_short(b)}." if gap > 0 else f" – the same price as {_short(b)}."))
        highlights.append({"key": "cheapest", "product_id": a["id"], "label": "Lowest price", "text": text})
    elif len(priced) == 1:
        highlights.append({"key": "cheapest", "product_id": priced[0]["id"], "label": "Lowest price",
                           "text": f"Only {_short(priced[0])} has a current verified price ({_inr(priced[0]['price'])})."})
    unpriced = [c for c in cols if c["price"] is None]
    if unpriced:
        notes.append("No current verified price for " + ", ".join(_short(c) for c in unpriced)
                     + " – price comparisons leave them out.")

    scored = [c for c in cols if c["deal_score"] is not None]
    if len(scored) >= 2:
        top = max(scored, key=lambda c: c["deal_score"])
        if sum(1 for c in scored if c["deal_score"] == top["deal_score"]) == 1:
            highlights.append({"key": "deal", "product_id": top["id"], "label": "Best deal right now",
                               "text": f"{_short(top)} has the best deal score ({top['deal_score']}/100, {top['deal_label']})."})

    rated = [c for c in cols if c["rating"] is not None]
    if len(rated) >= 2:
        top = max(rated, key=lambda c: (c["rating"], c["ratings_count"] or 0))
        if sum(1 for c in rated if c["rating"] == top["rating"]) == 1:
            cnt = f" from {top['ratings_count']:,} ratings" if top["ratings_count"] else ""
            highlights.append({"key": "rating", "product_id": top["id"], "label": "Highest rated",
                               "text": f"{_short(top)} is rated highest: {top['rating']:.1f}★{cnt}."})
            few = [c for c in rated if (c["ratings_count"] or 0) < 20]
            if few:
                notes.append("Ratings based on fewer than 20 reviews are less reliable: " + ", ".join(_short(c) for c in few) + ".")

    stocked = [c for c in cols if c["store_count"]]
    if len(stocked) >= 2:
        top = max(stocked, key=lambda c: c["store_count"])
        if sum(1 for c in stocked if c["store_count"] == top["store_count"]) == 1 and top["store_count"] > 1:
            highlights.append({"key": "stores", "product_id": top["id"], "label": "Most stores",
                               "text": f"{_short(top)} is sold by the most trusted stores ({top['store_count']})."})

    for key, label, fmt in (("storage_gb", "storage", _storage), ("ram_gb", "RAM", lambda v: f"{v} GB" if v else None),
                            ("screen_inches", "screen", lambda v: f'{v}"' if v else None)):
        vals = [(c, fmt(c[key])) for c in cols if c[key]]
        if len(vals) >= 2 and len({v for _, v in vals}) > 1:
            differences.append(f"{label.capitalize()}: " + " vs ".join(f"{v} ({_short(c)})" for c, v in vals) + ".")
    conds = {c["condition"] for c in cols}
    if len(conds) > 1:
        differences.append("Condition differs: " + ", ".join(f"{_short(c)} is {c['condition']}" for c in cols) + ".")
    if len({c["category"] for c in cols}) > 1:
        notes.append("These products are from different categories, so some rows don't compare like for like.")

    for c in cols:
        bits = []
        if c["praised"]:
            bits.append("reviewers praise " + ", ".join(a.lower() for a in c["praised"]))
        if c["complaints"]:
            bits.append("complaints mention " + ", ".join(a.lower() for a in c["complaints"]))
        if bits:
            differences.append(f"{_short(c)}: " + "; ".join(bits) + f" (from {c['reviews_analysed']} written reviews).")

    # Overall line: only when one product leads at least two of the measured categories.
    wins: dict[int, list[str]] = {}
    for h in highlights:
        if h["key"] != "cheapest" or len(priced) >= 2:   # "only one has a price" isn't a win
            wins.setdefault(h["product_id"], []).append(h["label"].lower())
    overall = None
    leader = max(wins.items(), key=lambda kv: len(kv[1]), default=None)
    if leader and len(leader[1]) >= 2:
        c = next(x for x in cols if x["id"] == leader[0])
        overall = f"{_short(c)} leads on {', '.join(leader[1][:-1])} and {leader[1][-1]}."
    if not highlights:
        notes.append("Not enough price, rating or deal data yet to say which is better – open each product to refresh it.")
    return {"overall": overall, "highlights": highlights, "differences": differences, "notes": notes}


def compare(catalog, db: Session, ids: list[int], demo: bool = False) -> dict:  # noqa: ANN001
    seen: list[int] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    cols, missing = [], []
    for pid in seen[:MAX_COMPARE]:
        p = db.get(Product, pid)
        if p is None:
            missing.append(pid)
            continue
        cols.append(column(catalog.product_detail(db, p, demo=demo)))
    return {"products": cols, "missing": missing, "summary": summarize(cols) if len(cols) >= 2 else None,
            "max": MAX_COMPARE}

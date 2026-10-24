"""Review intelligence: per-review aspect stances, coverage/confidence, evidence-only reliability signals, use cases."""
from app.reviews.analyze import analyze


def _rev(text, **kw):  # noqa: ANN001, ANN003, ANN202
    return {"title": None, "text": text, "user_name": kw.pop("user", None), "source": kw.pop("source", "Flipkart"),
            "rating": kw.pop("rating", 4), "date": kw.pop("date", None), "incentivized": kw.pop("incentivized", None)}


def test_aspects_are_counted_per_review_with_stance_and_confidence():
    data = {"reviews_count": 1000, "user_reviews": [
        _rev("Battery life is excellent. Camera is good."),
        _rev("Great battery, lasts a full day."),
        _rev("Battery is good but it heats a lot while gaming."),
        _rev("The battery drains fast. Camera is bad in low light."),
        _rev("Phone heats up and the display is dull."),
    ]}
    r = analyze(data)
    a = {x["aspect"]: x for x in r["aspects"]}
    bat = a["Battery"]
    assert bat["mentions"] == 4 and bat["positive"] == 3 and bat["negative"] == 1 and bat["stance"] == "praised"
    assert bat["share"] == 0.8 and bat["confidence"] == "medium"
    assert a["Heating"]["stance"] == "complaint"
    assert a["Camera"]["stance"] == "mixed"           # one positive, one negative
    assert a["Display"]["stance"] == "limited"         # a single review is not a trend
    # every example is a verbatim sentence from the review it points to
    for x in r["aspects"]:
        for e in x["examples"]:
            assert e["text"].rstrip("…") in (r["reviews"][e["review_id"]]["text"] or "")
    assert r["reviews"][2]["aspect_sentiment"]["Battery"] == "positive"
    assert r["summary"].startswith("In the 5 reviews available")


def test_negation_with_curly_apostrophe():
    r = analyze({"user_reviews": [_rev("I don’t feel heating and battery is long lasting.")]})
    s = r["reviews"][0]["aspect_sentiment"]
    assert s["Heating"] == "positive" and s["Battery"] == "positive" and "Build & design" not in s


def test_coverage_reflects_small_samples():
    small = analyze({"reviews_count": 12876, "user_reviews": [_rev("Good camera."), _rev("Nice display, very bright.")]})
    assert small["coverage"]["level"] == "low" and small["coverage"]["coverage_pct"] == 0.02
    assert "individual experiences" in small["coverage"]["note"]
    big = analyze({"user_reviews": [_rev(f"Review number {i} says the battery is good.") for i in range(20)]})
    assert big["coverage"]["level"] == "high" and big["coverage"]["total_ratings"] is None


def test_near_duplicates_are_flagged_and_not_double_counted():
    text = "I am heavily disappointed, the battery drains fast and the camera is bad."
    r = analyze({"user_reviews": [_rev(text), _rev(text), _rev("The camera is great and battery is good.")]})
    sig = {s["kind"]: s for s in r["reliability"]["signals"]}
    assert sig["duplicate_text"]["review_ids"] == [0, 1]
    assert r["reviews"][1]["counted"] is False and r["coverage"]["duplicates_excluded"] == 1
    assert {x["aspect"]: x for x in r["aspects"]}["Battery"]["mentions"] == 2  # not 3


def test_reliability_uses_evidence_only():
    r = analyze({"user_reviews": [
        _rev("BEST PHONE EVER!!! MUST BUY!!!", rating=5),
        _rev("ok", rating=1),
        _rev("Terrible battery and laggy.", rating=5),
        _rev("Got it free to review, the design looks premium.", incentivized=True),
    ]})
    assert [s["kind"] for s in r["reliability"]["signals"]] == ["incentivized"]
    assert [x["signals"] for x in r["reviews"][:3]] == [[], [], []]
    lim = " ".join(r["reliability"]["limitations"])
    assert "Verified-purchase" in lim and "never used to question" in lim and "fewer than 5" in lim


def test_timing_cluster_only_with_exact_dates():
    same = [_rev(f"Review {i}: the display is bright and good.", date="2026-03-01") for i in range(4)]
    r = analyze({"user_reviews": same + [_rev("Battery is fine.", date="2026-01-10")]})
    sig = {s["kind"]: s for s in r["reliability"]["signals"]}
    assert sig["timing_cluster"]["review_ids"] == [0, 1, 2, 3]
    rel = analyze({"user_reviews": [_rev(f"Review {i} display good.", date="3 months ago") for i in range(5)]})
    assert not rel["reliability"]["signals"] and "approximate" in rel["reliability"]["limitations"][0]


def test_use_cases_and_origin():
    r = analyze({"fetched_at": "2026-10-15T10:00:00+00:00", "user_reviews": [_rev("Good camera.", source="amazon.in")]})
    keys = [u["key"] for u in r["use_cases"]]
    assert keys == ["everyday", "gaming", "photography", "coding", "office"]
    gaming = next(u for u in r["use_cases"] if u["key"] == "gaming")
    assert gaming["aspects"][0]["aspect"] == "Performance" and gaming["aspects"][0]["why"]
    assert r["origin"] == {"source": "Google Shopping", "live": True, "fetched_at": "2026-10-15T10:00:00+00:00", "stores": ["amazon.in"]}
    assert "battery" in r["aspect_keywords"]["Battery"]

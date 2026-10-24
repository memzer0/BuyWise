from datetime import date, timedelta

from app.scoring.deal import evaluate

T = date(2026, 10, 9)


def series(prices: list[float]) -> dict[date, float]:
    start = T - timedelta(days=len(prices) - 1)
    return {start + timedelta(days=i): p for i, p in enumerate(prices)}


def test_no_history_gives_no_score():
    r = evaluate(100000, series([100000]), [], T)
    assert r.score is None and r.label == "Tracking price"
    assert all(c.status == "na" for c in r.checks if c.key != "cheaper_than_stores")
    assert r.insight["title"] == "Tracking just started"


def test_steady_drop_is_a_good_deal():
    r = evaluate(90000, series([100000] * 20 + [95000] * 5 + [90000] * 5), [95000, 99000], T)
    by = {c.key: c.status for c in r.checks}
    assert by["below_last_price"] == "pass" and by["at_all_time_low"] == "pass" and by["below_average"] == "pass"
    assert by["no_price_pump"] == "pass" and by["cheaper_than_stores"] == "pass"
    assert r.score >= 80 and r.label == "Steal deal"
    assert r.price_changes[0] == {"date": T.replace(day=5).isoformat(), "from": 95000, "to": 90000, "change": -5000}


def test_price_pump_detected():
    # steady at 100k, raised to 120k, then "dropped" back to 100k
    r = evaluate(100000, series([100000] * 20 + [120000] * 5 + [100000] * 3), [], T)
    pump = next(c for c in r.checks if c.key == "no_price_pump")
    assert pump.status == "fail" and r.insight["title"] == "Price hike before this price"
    assert r.label in ("Fair price", "Not a real deal", "Good catch")


def test_above_all_time_low_fails():
    r = evaluate(110000, series([100000] * 10 + [110000] * 10), [], T)
    by = {c.key: c for c in r.checks}
    assert by["at_all_time_low"].status == "fail" and "₹1,00,000" in by["at_all_time_low"].detail
    assert by["below_last_price"].status == "fail"

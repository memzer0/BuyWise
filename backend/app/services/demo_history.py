"""Demo price history – SIMULATED data for presentations, never stored and never presented as real.

Used only when the viewer has switched on Demo mode (X-BuyWise-Demo: 1) and a product has fewer than
MIN_REAL_DAYS days of real price checks. The series is deterministic per product (same product → same demo curve),
is anchored on the product's current verified price so it joins the real data, and every point carries
"demo": True so the UI can draw and label it differently.

It is NEVER written to the database and NEVER used for price alerts, Regret Shield post-purchase checks, the
"lowest verified price" or any stored record.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

MIN_REAL_DAYS = 7      # products with at least this many days of real checks never get demo data
DEMO_DAYS = 120        # length of the simulated window before the first real check
# Typical Indian sale windows (month, start day, length in days) – where the demo curve dips.
SALE_WINDOWS = [(1, 20, 6), (3, 10, 4), (5, 2, 5), (7, 12, 3), (8, 10, 6), (9, 26, 10), (10, 18, 6), (11, 28, 4), (12, 20, 6)]
NOTE = ("Demo mode: the part of the graph before BuyWise started tracking is simulated for demonstration. "
        "It is not real price history. You can turn demo history off at the bottom of the page.")


def _price_end(v: float) -> float:
    """Round like Indian retail prices (…99 / …999)."""
    if v >= 10_000:
        return float(int(round(v / 100.0)) * 100 - 1)
    if v >= 1_000:
        return float(int(round(v / 10.0)) * 10 - 1)
    return float(int(round(v)))


def _in_sale(d: date) -> bool:
    for m, start, length in SALE_WINDOWS:
        s = date(d.year, m, start)
        if s <= d < s + timedelta(days=length):
            return True
    return False


SCENARIOS = ("falling", "falling", "stable", "dipped")


def demo_daily(product_id: int, anchor_price: float, end: date, days: int = DEMO_DAYS) -> dict[date, float]:
    """Simulated daily lowest prices for the `days` days ending the day before `end`, joining `anchor_price`.

    Each product gets one of a few shapes so the demo isn't the same everywhere:
      falling – started higher and came down to today's price (today is the lowest)
      stable  – hovered just above today's price, short sale dips only down to today's price
      dipped  – was cheaper during a sale and is now back up (today is above the lowest)"""
    rng = random.Random(product_id * 7919 + 17)
    scenario = SCENARIOS[rng.randrange(len(SCENARIOS))]
    start_level = {"falling": rng.uniform(1.08, 1.15), "stable": rng.uniform(1.01, 1.04), "dipped": rng.uniform(1.02, 1.06)}[scenario]
    floor = anchor_price * (0.86 if scenario == "dipped" else 1.0)
    level = anchor_price * start_level
    out: dict[date, float] = {}
    start = end - timedelta(days=days)
    for i in range(days):
        d = start + timedelta(days=i)
        progress = i / max(days - 1, 1)
        target = anchor_price * (start_level + (1.0 - start_level) * progress if scenario == "falling" else start_level)
        if rng.random() < 0.12:                       # occasional price change
            level *= 1 + rng.uniform(-0.03, 0.03)
        level += (target - level) * 0.15
        price = level
        if _in_sale(d):
            price *= 1 - (rng.uniform(0.05, 0.11) if scenario == "dipped" else rng.uniform(0.01, 0.04))
        out[d] = _price_end(min(max(price, floor), anchor_price * 1.16))
    return out


def demo_points(product_id: int, anchor_price: float, first_real: date | None, today: date) -> list[dict]:
    end = first_real or today
    daily = demo_daily(product_id, anchor_price, end)
    return [{"observed_at": datetime.combine(d, time(12, 0), tzinfo=timezone.utc).isoformat(), "price": p,
             "retailer": "Demo (simulated)", "stores": 0, "demo": True} for d, p in sorted(daily.items())]

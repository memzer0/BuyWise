"""Rule-based deal check (BuyHatke-style "deal scanner") computed only from real observed prices.

Each rule earns points when it passes, none when it fails, half when the price is the same as the reference
("same", within SAME_TOL), and is excluded ("na") when there is not enough history to judge it.
The score is points earned / points available among judged rules × 100.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

RULES = [
    # key, label, max points
    ("below_last_price", "Below the last price", 27),
    ("no_price_pump", "No price hike before this price", 19),
    ("at_all_time_low", "At the lowest price seen", 20),
    ("six_month_low", "At the 6-month low", 12),
    ("below_average", "Below the average price", 12),
    ("cheaper_than_stores", "Cheaper than other stores", 10),
]
MIN_JUDGED_POINTS = 30   # below this, no overall score is given
SAME_TOL = 0.005         # prices within 0.5 % count as "the same" (₹1,05,000 vs ₹1,04,999)
PUMP_RISE = 0.08         # a rise of ≥8% within the last 30 days, followed by a fall, counts as a pump


@dataclass
class Check:
    key: str
    label: str
    max_points: int
    status: str              # pass / same / fail / na
    points: int = 0
    detail: str = ""


@dataclass
class DealResult:
    score: int | None
    label: str
    completeness: float
    insight: dict | None
    checks: list[Check] = field(default_factory=list)
    price_changes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _inr(v: float) -> str:
    """₹ with Indian digit grouping: ₹1,23,45,678."""
    n = str(int(round(v)))
    if len(n) > 3:
        rest, last3 = n[:-3], n[-3:]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        n = ",".join(groups + [last3])
    return f"₹{n}"


def label_for(score: int | None) -> str:
    if score is None:
        return "Tracking price"
    if score >= 80:
        return "Steal deal"
    if score >= 60:
        return "Good catch"
    if score >= 40:
        return "Fair price"
    return "Not a real deal"


def evaluate(current: float | None, daily_min: dict[date, float], other_store_prices: list[float],
             today: date | None = None) -> DealResult:
    """`daily_min`: lowest observed trusted-store price per day (real observations only)."""
    today = today or date.today()
    days = sorted(daily_min)
    checks: list[Check] = []
    changes: list[dict] = []
    prev = None
    for d in days:
        if prev is not None and abs(daily_min[d] - prev[1]) > 0.5:
            changes.append({"date": d.isoformat(), "from": prev[1], "to": daily_min[d], "change": round(daily_min[d] - prev[1], 2)})
        prev = (d, daily_min[d])
    changes.reverse()

    if current is None:
        return DealResult(None, "No verified price", 0.0, None,
                          [Check(k, lbl, m, "na", 0, "No current verified price.") for k, lbl, m in RULES], changes)

    span = (days[-1] - days[0]).days if days else 0
    lowest = min(daily_min.values()) if daily_min else None
    enough = len(days) >= 2 and span >= 2   # at least two separate days of checks, two or more days apart

    def same(a: float, b: float) -> bool:
        return abs(a - b) <= max(0.5, b * SAME_TOL)

    def half(c: Check) -> None:
        c.status, c.points = "same", c.max_points // 2
    for key, lbl, mx in RULES:
        c = Check(key, lbl, mx, "na")
        if key == "below_last_price":
            # last different price before the current one
            last = next((ch["from"] for ch in changes if abs(ch["to"] - current) <= 0.5), None)
            if last is None and changes:
                last = changes[0]["to"]
            if last is None and len(days) >= 2:
                prev_day = days[-2] if days[-1] == today else days[-1]
                last = daily_min[prev_day]
            if last is None:
                c.detail = "Needs a price check on an earlier day."
            elif same(current, last):
                half(c)
                c.detail = f"Same as the last price ({_inr(last)})."
            elif current < last:
                c.status, c.points, c.detail = "pass", mx, f"Below the last price ({_inr(last)})."
            else:
                c.status, c.detail = "fail", f"Above the last price ({_inr(last)})."
        elif key == "no_price_pump":
            if not enough:
                c.detail = "Needs price checks on at least two days."
            else:
                window = [daily_min[d] for d in days if d >= today - timedelta(days=30)]
                peak = max(window) if window else current
                peak_day = max((d for d in days if d >= today - timedelta(days=30) and daily_min[d] == peak), default=None)
                before = [daily_min[d] for d in days if peak_day and d < peak_day]
                base = min(before[-7:]) if before else None
                pumped = base is not None and peak >= base * (1 + PUMP_RISE) and current < peak and current >= base * 0.98
                if pumped:
                    c.status, c.detail = "fail", f"Price went up to {_inr(peak)} before coming back to {_inr(current)} (was {_inr(base)})."
                else:
                    c.status, c.points, c.detail = "pass", mx, (
                        "No sudden price hike in the last 30 days." if span >= 30 else
                        f"No sudden price hike in the {span} days BuyWise has tracked.")
        elif key == "at_all_time_low":
            if not enough:
                c.detail = "Needs price checks on at least two days."
            elif current <= lowest or same(current, lowest):
                c.status, c.points, c.detail = "pass", mx, f"Matches the lowest price seen ({_inr(lowest)})."
            else:
                c.status, c.detail = "fail", f"Above the lowest price seen ({_inr(lowest)})."
        elif key == "six_month_low":
            if span < 14:
                c.detail = "Needs at least 2 weeks of price history."
            else:
                six = [daily_min[d] for d in days if d >= today - timedelta(days=183)]
                low6 = min(six) if six else lowest
                if current <= low6 or same(current, low6):
                    c.status, c.points, c.detail = "pass", mx, f"At the 6-month low ({_inr(low6)})."
                else:
                    c.status, c.detail = "fail", f"Above the 6-month low ({_inr(low6)})."
        elif key == "below_average":
            if not enough:
                c.detail = "Needs price checks on at least two days."
            else:
                avg = sum(daily_min.values()) / len(daily_min)
                if same(current, avg):
                    half(c)
                    c.detail = f"Same as the average price ({_inr(avg)})."
                elif current < avg:
                    c.status, c.points, c.detail = "pass", mx, f"Below the average price ({_inr(avg)})."
                else:
                    c.status, c.detail = "fail", f"Not below the average price ({_inr(avg)})."
        elif key == "cheaper_than_stores":
            if not other_store_prices:
                c.detail = "Only one store has a verified price."
            else:
                others = sorted(other_store_prices)
                med = others[len(others) // 2]
                if current < med * 0.99:
                    c.status, c.points, c.detail = "pass", mx, f"{(med - current) / med * 100:.1f}% below the other stores' typical price ({_inr(med)})."
                elif current <= med * 1.01:
                    half(c)
                    c.detail = f"About the same as other stores ({_inr(med)})."
                else:
                    c.status, c.detail = "fail", f"Above the other stores' typical price ({_inr(med)})."
        checks.append(c)

    judged = sum(c.max_points for c in checks if c.status != "na")
    earned = sum(c.points for c in checks)
    score = round(earned / judged * 100) if judged >= MIN_JUDGED_POINTS else None

    pump = next((c for c in checks if c.key == "no_price_pump" and c.status == "fail"), None)
    atl = next((c for c in checks if c.key == "at_all_time_low" and c.status == "pass"), None)
    last = next((c for c in checks if c.key == "below_last_price" and c.status != "na"), None)
    if pump:
        insight = {"kind": "warning", "title": "Price hike before this price", "body": pump.detail}
    elif atl:
        insight = {"kind": "good", "title": "Lowest price we've seen", "body": atl.detail}
    elif last and last.status == "pass":
        insight = {"kind": "good", "title": "Better than the last price", "body": last.detail}
    elif last and last.status == "fail":
        insight = {"kind": "warning", "title": "Price went up", "body": last.detail}
    elif days:
        insight = {"kind": "info", "title": "Tracking just started",
                   "body": f"First price check on {days[0].strftime('%d %b %Y')}. The deal check gets sharper as BuyWise keeps checking."}
    else:
        insight = None
    return DealResult(score, label_for(score), round(judged / 100, 2), insight, checks, changes[:20])

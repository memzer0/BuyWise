"""BuyWise Decision Engine: BUY_NOW / WAIT / CONSIDER_ALTERNATIVES / NOT_ENOUGH_DATA.

Transparent rules over evidence BuyWise already holds (deal-scanner checks on real observed prices, the current
verified offers, and newer models it has tracked). No future price is promised; "evidence level" describes how much
of the evidence exists, it is not a probability.

Rule order (first match wins):
 1. No verified current offer                                  -> NOT_ENOUGH_DATA
 2. A newer generation of the same model is tracked and costs
    at most 15% more than this one                             -> CONSIDER_ALTERNATIVES
 3. Price hike detected before the current price              -> WAIT
 4. Current price at the lowest price seen (≥3 days of data)   -> BUY_NOW
 5. ≥5% above the lowest price seen, with ≥7 days of data      -> WAIT
 6. Below the last price and below the average                -> BUY_NOW
 7. Above the average price by ≥3% (≥7 days of data)           -> WAIT
 8. Fewer than 30 points of deal checks can be judged          -> NOT_ENOUGH_DATA
 9. Otherwise                                                   -> BUY_NOW (fair price, no warning signs)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

LABELS = {
    "BUY_NOW": "Buy now",
    "WAIT": "Wait",
    "CONSIDER_ALTERNATIVES": "Consider alternatives",
    "NOT_ENOUGH_DATA": "Tracking price",
}


@dataclass
class Decision:
    verdict: str
    label: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence_level: str = "low"          # low / medium / high – share of evidence available, not a probability
    alternatives: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _inr(v: float) -> str:
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


def decide(*, best_price: float | None, best_retailer: str | None, best_availability: str | None,
           best_link_exact: bool, store_count: int, deal: dict, lowest: float | None, average: float | None,
           span_days: int, newer_models: list[dict], last_known: dict | None = None) -> Decision:
    checks = {c["key"]: c for c in deal.get("checks", [])}
    completeness = deal.get("completeness", 0.0)
    level = "high" if completeness >= 0.7 else "medium" if completeness >= 0.4 else "low"
    # a short history caps how sure the advice can be, however many checks could be judged
    if span_days < 3:
        level = "low"
    elif span_days < 14 and level == "high":
        level = "medium"
    limitations = ["Future prices can't be known for certain – this is guidance based on prices seen so far."]
    if span_days < 7:
        limitations.append("Price tracking started recently – this advice sharpens over the next few days.")
    if best_availability in (None, "unknown"):
        limitations.append("The store did not report stock status.")
    if best_price is not None and not best_link_exact:
        limitations.append("The cheapest offer's link opens Google Shopping, not the store's own page.")
    if store_count < 2:
        limitations.append("Only one store has a verified price, so there is little to compare against.")

    def make(verdict: str, headline: str, reasons: list[str], alts: list[dict] | None = None) -> Decision:
        return Decision(verdict, LABELS[verdict], headline, reasons, limitations, level, alts or [])

    if best_price is None:
        reasons = ["BuyWise needs at least one verified, in-date offer to give advice."]
        if last_known:
            reasons.append(f"Last price BuyWise saw: {_inr(last_known['price'])} at {last_known['retailer']} on "
                           f"{last_known['date']} ({last_known['age']}). It hasn't been re-confirmed, so it isn't used here.")
            reasons.append("Press “Check prices now” to get today's price.")
        return make("NOT_ENOUGH_DATA", "No verified current price from a trusted store.", reasons)

    cheaper_newer = [m for m in newer_models if m.get("best_price") is not None and m["best_price"] <= best_price * 1.15]
    if cheaper_newer:
        m = min(cheaper_newer, key=lambda x: x["best_price"])
        diff = m["best_price"] - best_price
        rel = "less" if diff < 0 else "more"
        return make("CONSIDER_ALTERNATIVES", f"A newer model is available for {_inr(abs(diff))} {rel}.",
                    [f"{m['title']} is tracked at {_inr(m['best_price'])} ({m.get('retailer') or 'store'}).",
                     "Newer generations usually get longer software support; older models often get cheaper once a successor launches."],
                    cheaper_newer)

    pump = checks.get("no_price_pump")
    if pump and pump["status"] == "fail":
        return make("WAIT", "The price was raised before this 'deal'.", [pump["detail"]])

    atl = checks.get("at_all_time_low")
    if atl and atl["status"] == "pass" and span_days >= 3:
        return make("BUY_NOW", f"{_inr(best_price)} at {best_retailer} is the lowest price BuyWise has seen.", [atl["detail"]])

    if lowest and span_days >= 3 and best_price >= lowest * 1.05:
        pct = (best_price - lowest) / lowest * 100
        return make("WAIT", f"Currently {pct:.0f}% above the lowest price seen ({_inr(lowest)}).",
                    [f"Prices for this product have been lower within the last {span_days} days."])

    last = checks.get("below_last_price")
    avg = checks.get("below_average")
    if last and avg and last["status"] == "pass" and avg["status"] == "pass":
        return make("BUY_NOW", "Price has just dropped and is below its average.", [last["detail"], avg["detail"]])

    if average and span_days >= 3 and best_price >= average * 1.03:
        return make("WAIT", f"Above the average price ({_inr(average)}).", ["Prices have usually been lower than this."])

    judged = sum(c["max_points"] for c in checks.values() if c["status"] != "na")
    if judged >= 30 and span_days < 3:
        return make("NOT_ENOUGH_DATA", "No warning signs so far – BuyWise is still tracking this price.",
                    [f"The lowest verified price is {_inr(best_price)} at {best_retailer}.",
                     f"BuyWise has {span_days} day(s) of prices – the advice firms up after a few more days of checks."])
    if judged < 30:
        return make("NOT_ENOUGH_DATA", "BuyWise is tracking this price.",
                    [f"If you need it now, the lowest verified price is {_inr(best_price)} at {best_retailer}.",
                     "Add it to your watchlist – BuyWise will keep checking and this advice will firm up."])

    score = deal.get("score")
    if score is not None and score < 40:
        return make("WAIT", "This isn't a good price compared with what BuyWise has seen.",
                    [c["detail"] for c in checks.values() if c["status"] == "fail"][:3])
    return make("BUY_NOW", "A fair price with no warning signs.",
                [c["detail"] for c in checks.values() if c["status"] in ("pass", "same")][:3])


# ---------------------------------------------------------------------------------------------------------------
# "Should you buy now?" – timing guide for a given need-by horizon.
#
# timing score (0 = bad time, 100 = good time), computed only from observed prices:
#   position = (highest − current) / (highest − lowest) × 100      (100 = at the lowest price seen)
#   price never changed                                            → 70 ("stable price")
#   need within 2–3 days : score = max(position, 60)  – waiting isn't really an option
#   need within a week   : score = position
#   need within a month  : score = position − 10 if the fitted trend is falling, else position
#   price hike detected before the current price  → capped at 40 (3 days) / 35 (week) / 30 (month)
# Recommendation: ≥70 good time to buy, 45–69 fair (buy if you need it), <45 better to wait.
# Needs observations on ≥2 days; otherwise no score.
# ---------------------------------------------------------------------------------------------------------------
HORIZONS = [("3d", "2–3 days"), ("1w", "1 week"), ("1m", "1 month")]


def timing(*, current: float | None, lowest: float | None, highest: float | None, average: float | None,
           days_observed: int, pump: bool, trend_per_day: float | None) -> dict:
    stats = {"highest": highest, "average": average, "lowest": lowest, "current": current}
    if current is None:
        return {"available": False, "reason": "No verified current price.", "stats": stats, "horizons": []}
    if days_observed < 2 or lowest is None or highest is None:
        return {"available": False, "stats": stats, "horizons": [],
                "reason": f"Needs price checks on at least 2 days (have {days_observed}). Add it to your watchlist to keep tracking."}
    out = []
    stable = highest - lowest < 1
    position = 70.0 if stable else max(0.0, min(100.0, (highest - current) / (highest - lowest) * 100))
    above_low = (current - lowest) / lowest * 100 if lowest else 0.0
    for key, label in HORIZONS:
        if key == "3d":
            score = max(position, 60.0)
            if pump:
                score = min(score, 40.0)
        elif key == "1w":
            score = min(position, 35.0) if pump else position
        else:
            score = position - (10 if trend_per_day is not None and trend_per_day < 0 else 0)
            if pump:
                score = min(score, 30.0)
        score = round(max(0.0, min(100.0, score)))
        if score >= 70:
            rec, tone = "Go ahead & buy now", "good"
        elif score >= 45:
            rec, tone = "Fair time – buy if you need it", "fair"
        else:
            rec, tone = "Better to wait", "wait"
        why = []
        if stable:
            why.append(f"The price has stayed at {_inr(current)} since tracking began – no sign of a drop.")
        elif current <= lowest + 0.5:
            why.append("This is the lowest price BuyWise has seen.")
        else:
            why.append(f"{above_low:.1f}% above the lowest price seen ({_inr(lowest)}).")
        if pump:
            why.append("The price was raised shortly before this price, so the 'discount' may not be real.")
        if key == "3d" and score >= 60 and not pump and above_low > 0.5:
            why.append("You need it soon, so waiting for a drop is risky.")
        if key == "1m" and trend_per_day is not None and trend_per_day < 0:
            why.append("Observed prices are trending down (an estimate, not a guarantee).")
        out.append({"key": key, "label": label, "score": score, "recommendation": rec, "tone": tone, "why": why})
    return {"available": True, "stats": stats, "horizons": out, "reason": None,
            "method": "Score = where today's price sits between the highest and lowest prices BuyWise has observed, "
                      "adjusted for how soon you need it and for price hikes before the current price."}

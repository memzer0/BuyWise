"""Transparent BuyWise Score (0–100).

Components (each 0–100) and default weights (configurable via SCORE_WEIGHT_* env vars):
  price_vs_history  0.35  where the current best price sits between the lowest and highest observed price
  market_position   0.25  how much cheaper the best offer is than the median of other verified offers
  trend             0.15  direction of the fitted price trend (falling trend ⇒ lower score: waiting may pay)
  rating            0.15  provider-supplied average rating (only when a provider returns genuine ratings)
  availability      0.10  best offer is verified in stock with an exact product link

Missing components are NOT scored as perfect; they are dropped and the remaining weights are
renormalised. `confidence` = share of total weight that had real data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from app.core.config import Settings
from app.scoring.prediction import Prediction


@dataclass
class Component:
    key: str
    label: str
    weight: float
    score: float | None
    explanation: str


@dataclass
class ScoreResult:
    score: int | None
    confidence: float
    components: list[Component] = field(default_factory=list)
    verdict: str | None = None
    reasons: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def compute_score(
    settings: Settings,
    *,
    best_price: float | None,
    best_in_stock: bool,
    best_exact_link: bool,
    other_verified_prices: list[float],
    history_prices: list[float],
    history_days: int,
    prediction: Prediction,
    ratings: list[tuple[float, int | None]],
) -> ScoreResult:
    w = {
        "price_vs_history": settings.score_weight_price_vs_history,
        "market_position": settings.score_weight_market_position,
        "trend": settings.score_weight_trend,
        "rating": settings.score_weight_rating,
        "availability": settings.score_weight_availability,
    }
    if best_price is None:
        return ScoreResult(None, 0.0, [], None, [],
                           ["No verified, current, matched offer is available, so no score is given."])
    comps: list[Component] = []
    limits: list[str] = []
    reasons: list[str] = []

    # price vs history
    if len(history_prices) >= 5 and history_days >= 7:
        lo, hi = min(history_prices), max(history_prices)
        s = 100.0 if hi == lo else max(0.0, min(100.0, (hi - best_price) / (hi - lo) * 100))
        comps.append(Component("price_vs_history", "Price vs. observed history", w["price_vs_history"], round(s, 1),
                               f"Current best ₹{best_price:,.0f}; observed range ₹{lo:,.0f}–₹{hi:,.0f} over {history_days} days."))
        if best_price <= lo * 1.01:
            reasons.append("Current price is at (or within 1% of) the lowest price BuyWise has observed.")
        elif s < 40:
            reasons.append("Current price is in the upper part of the observed range.")
    else:
        comps.append(Component("price_vs_history", "Price vs. observed history", w["price_vs_history"], None,
                               f"Needs ≥5 observations over ≥7 days (have {len(history_prices)} over {history_days} days)."))
        limits.append("Price tracking began recently; history-based scoring is not yet possible.")

    # market position
    if other_verified_prices:
        med = median(other_verified_prices)
        saving = (med - best_price) / med if med else 0.0
        s = max(0.0, min(100.0, 50 + saving * 250))  # 20% below median ⇒ 100
        comps.append(Component("market_position", "Price vs. other sellers", w["market_position"], round(s, 1),
                               f"Best offer is {saving * 100:.1f}% below the median of {len(other_verified_prices)} other verified offer(s)."))
        if saving >= 0.05:
            reasons.append(f"Best offer is {saving * 100:.0f}% cheaper than the typical verified seller price.")
    else:
        comps.append(Component("market_position", "Price vs. other sellers", w["market_position"], None,
                               "Only one verified seller offer is available, so there is nothing to compare against."))
        limits.append("Only one verified seller offer was found.")

    # trend
    if prediction.available and prediction.slope_per_day is not None:
        rel = prediction.slope_per_day * 7 / best_price
        s = max(0.0, min(100.0, 50 + rel * 1000))  # rising 5%/week ⇒ 100 (buy now); falling ⇒ low (wait)
        comps.append(Component("trend", "Price trend", w["trend"], round(s, 1),
                               f"Fitted trend {prediction.slope_per_day:+,.0f} ₹/day (estimate, hold-out MAE ₹{prediction.holdout_mae})."))
        if rel < -0.02:
            reasons.append("Observed prices are trending down; waiting may get a lower price (estimate, not a guarantee).")
        elif rel > 0.02:
            reasons.append("Observed prices are trending up.")
    else:
        comps.append(Component("trend", "Price trend", w["trend"], None, prediction.reason or "Building up."))

    # rating
    rated = [(r, n or 0) for r, n in ratings if r is not None]
    if rated:
        total_n = sum(n for _, n in rated)
        avg = sum(r * max(n, 1) for r, n in rated) / sum(max(n, 1) for _, n in rated)
        s = max(0.0, min(100.0, (avg - 1) / 4 * 100))
        comps.append(Component("rating", "Customer rating", w["rating"], round(s, 1),
                               f"Average {avg:.1f}/5 from provider data ({total_n:,} ratings)."))
    else:
        comps.append(Component("rating", "Customer rating", w["rating"], None, "No provider supplied genuine rating data."))

    # availability
    s = (60 if best_in_stock else 30) + (40 if best_exact_link else 0)
    comps.append(Component("availability", "Availability & link quality", w["availability"], float(s),
                           ("In stock" if best_in_stock else "Stock status not confirmed") + "; " +
                           ("exact product link." if best_exact_link else "link is not an exact retailer listing.")))

    have = [c for c in comps if c.score is not None]
    total_w = sum(c.weight for c in comps)
    have_w = sum(c.weight for c in have)
    score = round(sum(c.score * c.weight for c in have) / have_w) if have_w else None
    confidence = round(have_w / total_w, 2) if total_w else 0.0
    verdict = None
    if score is not None and confidence >= 0.5:
        verdict = "good_time_to_buy" if score >= 70 else "consider_waiting" if score < 45 else "fair_price"
    elif score is not None:
        verdict = "insufficient_data"
    return ScoreResult(score, confidence, comps, verdict, reasons, limits)

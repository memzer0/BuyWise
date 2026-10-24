"""Baseline price prediction: ordinary least-squares on the daily lowest observed price.

Only runs when there are at least MIN_DAYS distinct observation days. Accuracy is evaluated with a
time-ordered hold-out (fit on the first 80 % of days, test on the last 20 %), and reported as MAE.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

MIN_DAYS = 14
HORIZON_DAYS = 7


@dataclass
class Prediction:
    available: bool
    reason: str | None = None
    predicted_price: float | None = None
    horizon_days: int = HORIZON_DAYS
    slope_per_day: float | None = None
    holdout_mae: float | None = None
    holdout_mape: float | None = None
    days_used: int = 0
    method: str = "ordinary least squares on daily minimum observed price"


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx


def predict(daily_min: dict[date, float]) -> Prediction:
    days = sorted(daily_min)
    if len(days) < MIN_DAYS:
        return Prediction(False, f"Price trend estimate appears after {MIN_DAYS} days of tracking ({len(days)} so far).",
                          days_used=len(days))
    origin = days[0]
    xs = [(d - origin).days for d in days]
    ys = [daily_min[d] for d in days]
    split = max(int(len(xs) * 0.8), MIN_DAYS - 3)
    slope_t, icpt_t = _ols(xs[:split], ys[:split])
    errs = [abs((slope_t * x + icpt_t) - y) for x, y in zip(xs[split:], ys[split:])]
    mae = sum(errs) / len(errs) if errs else None
    mape = (sum(e / y for e, y in zip(errs, ys[split:])) / len(errs) * 100) if errs else None
    slope, icpt = _ols(xs, ys)
    target_x = (days[-1] + timedelta(days=HORIZON_DAYS) - origin).days
    pred = max(0.0, slope * target_x + icpt)
    return Prediction(True, None, round(pred, 2), HORIZON_DAYS, round(slope, 2),
                      round(mae, 2) if mae is not None else None, round(mape, 2) if mape is not None else None, len(days))

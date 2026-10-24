"""Freshness labelling and lowest-verified-price selection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import Settings


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness_status(last_verified_at: datetime | None, settings: Settings, *, fetched_this_request: bool = False,
                     has_price: bool = True, now: datetime | None = None) -> str:
    """live | cached | stale | unavailable

    live        – fetched from the provider during the current request
    cached      – verified earlier, within the stale threshold
    stale       – older than the stale threshold (shown, never ranked as cheapest)
    unavailable – no verified price
    """
    if not has_price or last_verified_at is None:
        return "unavailable"
    if fetched_this_request:
        return "live"
    now = now or datetime.now(timezone.utc)
    age = (now - aware(last_verified_at)).total_seconds()
    return "cached" if age <= settings.stale_after_seconds else "stale"


@dataclass
class OfferView:
    id: int
    price: float | None
    currency: str
    availability: str
    freshness: str
    match_status: str
    verification_status: str
    condition: str
    link_type: str
    shipping_cost: float | None
    trusted: bool = True

    @property
    def total_cost(self) -> float | None:
        if self.price is None or self.shipping_cost is None:
            return None
        return round(self.price + self.shipping_cost, 2)


def eligible_for_best_price(o: OfferView) -> tuple[bool, str | None]:
    """Only verified, matched, non-stale, in-stock (or unknown-stock) INR offers can be called cheapest."""
    if o.price is None:
        return False, "no_price"
    if o.currency != "INR":
        return False, "currency"
    if o.verification_status != "verified":
        return False, "unverified_data"
    if o.match_status != "verified":
        return False, "unverified_match"
    if o.freshness not in ("live", "cached"):
        return False, f"freshness_{o.freshness}"
    if o.availability == "out_of_stock":
        return False, "out_of_stock"
    if not o.trusted:
        return False, "untrusted_store"
    return True, None


def select_lowest(offers: list[OfferView], include_refurbished: bool = False) -> OfferView | None:
    pool = [o for o in offers if eligible_for_best_price(o)[0] and (include_refurbished or o.condition == "new")]
    if not pool:
        return None
    return min(pool, key=lambda o: (o.price, 0 if o.link_type == "exact_listing" else 1))

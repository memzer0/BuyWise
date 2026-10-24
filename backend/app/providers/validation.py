"""Shared validation applied to every raw listing before it becomes a `Listing`."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.urls import classify_link, validate_offer_url
from app.matching.attributes import NON_PRODUCT_RE
from app.providers.base import Listing, parse_price


class RejectedListing(ValueError):
    pass


def build_listing(
    *,
    provider_id: str,
    source_type: str,
    listing_key: str | None,
    title: str | None,
    retailer: str | None,
    price,  # noqa: ANN001
    currency: str | None,
    product_url: str | None,
    allow_http: bool = False,
    expected_currency: str = "INR",
    excluded_sellers: frozenset[str] = frozenset(),
    **extra,  # noqa: ANN003
) -> Listing:
    if not listing_key:
        raise RejectedListing("missing_listing_key")
    if not title or not title.strip():
        raise RejectedListing("missing_title")
    if NON_PRODUCT_RE.search(title):
        raise RejectedListing("non_product_listing")
    if retailer and retailer.strip().lower() in excluded_sellers:
        raise RejectedListing("excluded_seller")
    value = parse_price(price)
    if value is None:
        raise RejectedListing("missing_or_malformed_price")
    cur = (currency or "").upper().strip()
    if cur in ("₹", "RS", "RS.", "INR"):
        cur = "INR"
    if cur != expected_currency:
        raise RejectedListing(f"unexpected_currency:{cur or 'none'}")
    ok, reason = validate_offer_url(product_url, allow_http=allow_http)
    if not ok:
        raise RejectedListing(f"invalid_url:{reason}")
    assert product_url is not None
    for k in ("mrp", "shipping_cost"):
        if k in extra:
            extra[k] = parse_price(extra[k]) if extra[k] not in (0, "0", 0.0) else (0.0 if k == "shipping_cost" else None)
    return Listing(
        provider_id=provider_id,
        listing_key=str(listing_key)[:300],
        title=title.strip()[:500],
        retailer=(retailer or "Unknown seller").strip()[:120],
        price=value,
        currency=cur,
        product_url=product_url.strip(),
        link_type=classify_link(product_url.strip()),
        fetched_at=datetime.now(timezone.utc),
        source_type=source_type,
        **extra,
    )

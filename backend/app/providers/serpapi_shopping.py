"""SerpApi – Google Shopping (India). Licensed third-party API.

Search:  https://serpapi.com/google-shopping-api     (engine=google_shopping)
Stores:  https://serpapi.com/google-immersive-product-api (engine=google_immersive_product, page_token=...)

Each `shopping_results` item is one seller offer as shown on Google Shopping India. Its documented
`product_link` points to a Google Shopping page, NOT the retailer listing, so such offers are labelled
`aggregator_page`. When a product is opened, BuyWise calls the immersive-product endpoint with the
item's `immersive_product_page_token`; that returns the product's store list, where each store's `link`
is the retailer's own product page – those become exact Buy Now links (costs one extra SerpApi search).
"""
from __future__ import annotations

import logging
import re

from app.providers.base import BaseProvider, Listing, ProviderError
from app.pricing.final_price import notes_from_store
from app.providers.validation import RejectedListing, build_listing

log = logging.getLogger(__name__)


def _currency_of(price_text) -> str | None:  # noqa: ANN001
    """'₹69,900.00' -> 'INR'; '$799' -> '$'; None when no price text."""
    if not isinstance(price_text, str) or not price_text.strip():
        return None
    if "₹" in price_text or price_text.strip().upper().startswith(("RS", "INR")):
        return "INR"
    sym = re.sub(r"[\d.,\s]", "", price_text)
    return sym or None


class SerpApiGoogleShoppingProvider(BaseProvider):
    id = "serpapi_google_shopping"
    display_name = "Google Shopping India (via SerpApi)"
    source_type = "licensed_api"
    credential_env = ("SERPAPI_API_KEY",)
    docs_url = "https://serpapi.com/google-shopping-api"
    endpoint = "https://serpapi.com/search.json"

    def is_configured(self) -> bool:
        return bool(self.settings.serpapi_api_key)

    def _check_error(self, data: dict) -> bool:
        """Raise for SerpApi errors. Returns True when the error just means 'no results'."""
        if not data.get("error"):
            return False
        msg = str(data["error"])
        low = msg.lower()
        if "hasn't returned any results" in low or "no results" in low:
            return True
        if "run out of searches" in low or "plan" in low and "limit" in low:
            raise ProviderError("quota_exceeded", msg[:300])
        if "invalid api key" in low:
            raise ProviderError("access_denied", msg[:300], 401)
        raise ProviderError("provider_error", msg[:300])

    async def search_products(self, query: str, limit: int = 20) -> list[Listing]:
        params = {
            "engine": "google_shopping",
            "q": query,
            "gl": "in",
            "hl": "en",
            "google_domain": "google.co.in",
            "location": self.settings.serpapi_location,
            "api_key": self.settings.serpapi_api_key,
        }
        data = await self.request_json("GET", self.endpoint, params=params)
        if self._check_error(data):
            return []
        self.last_rejections = 0
        out: list[Listing] = []
        for item in (data.get("shopping_results") or [])[: limit * 2]:
            try:
                out.append(self.normalize(item))
            except RejectedListing as exc:
                self.last_rejections += 1
                log.debug("serpapi rejected listing %s: %s", item.get("title"), exc)
        return out[:limit]

    def normalize(self, item: dict) -> Listing:
        url = item.get("link") or item.get("product_link")
        price = item.get("extracted_price") if item.get("extracted_price") is not None else item.get("price")
        key_base = item.get("product_id") or item.get("link") or item.get("product_link")
        source = item.get("source")
        delivery = (item.get("delivery") or "").lower()
        title = item.get("title") or ""
        if item.get("second_hand_condition") and "refurb" not in title.lower():
            title = f"{title} (Refurbished)"
        return build_listing(
            provider_id=self.id,
            source_type=self.source_type,
            listing_key=f"{key_base}|{source}" if key_base else None,
            title=title,
            retailer=source,
            price=price,
            currency=_currency_of(item.get("price")),
            product_url=url,
            allow_http=self.settings.allow_http_offer_urls,
            excluded_sellers=self.settings.excluded_seller_set,
            image_url=item.get("thumbnail"),
            shipping_cost=0.0 if "free" in delivery else None,
            rating=float(item["rating"]) if isinstance(item.get("rating"), (int, float)) else None,
            rating_count=int(item["reviews"]) if isinstance(item.get("reviews"), int) else None,
            seller_name=source,
            provider_ref=item.get("immersive_product_page_token"),
        )

    async def fetch_store_offers(self, page_token: str, group_key: str, fallback_title: str) -> list[Listing]:
        """Store list for one Google Shopping product – each store's own product link and price."""
        params = {
            "engine": "google_immersive_product",
            "page_token": page_token,
            "more_stores": "true",
            "gl": "in",
            "hl": "en",
            "api_key": self.settings.serpapi_api_key,
        }
        data = await self.request_json("GET", self.endpoint, params=params)
        if self._check_error(data):
            return []
        pr = data.get("product_results") or {}
        base_title = pr.get("title") or fallback_title
        # Reviews / rating breakdown come in the same response – kept as raw data (no extra search).
        if pr.get("user_reviews") or pr.get("ratings") or pr.get("top_insights"):
            from datetime import datetime, timezone
            self.last_extra = {"reviews": {
                "rating": pr.get("rating"), "reviews_count": pr.get("reviews"), "ratings": pr.get("ratings") or [],
                "user_reviews": [{k: r.get(k) for k in ("title", "text", "user_name", "source", "rating", "date", "incentivized")}
                                 for r in (pr.get("user_reviews") or []) if isinstance(r, dict)][:30],
                "insights": pr.get("top_insights") or [],
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }}
        brand = pr.get("brand") if isinstance(pr.get("brand"), str) else None
        self.last_rejections = 0
        out: list[Listing] = []
        for s in pr.get("stores") or []:
            name = s.get("name")
            try:
                shipping = s.get("shipping_extracted")
                if shipping is None and "free" in str(s.get("shipping") or "").lower():
                    shipping = 0.0
                out.append(build_listing(
                    provider_id=self.id,
                    source_type=self.source_type,
                    listing_key=f"{group_key}|store|{(name or '').strip().lower()}" if name else None,
                    title=s.get("title") or base_title,
                    retailer=name,
                    price=s.get("extracted_price") if s.get("extracted_price") is not None else s.get("price"),
                    currency=_currency_of(s.get("price")),
                    product_url=s.get("link"),
                    allow_http=self.settings.allow_http_offer_urls,
                    excluded_sellers=self.settings.excluded_seller_set,
                    mrp=s.get("extracted_original_price"),
                    shipping_cost=shipping,
                    rating=float(s["rating"]) if isinstance(s.get("rating"), (int, float)) else None,
                    rating_count=int(s["reviews"]) if isinstance(s.get("reviews"), int) else None,
                    seller_name=name,
                    brand=brand,
                    provider_ref=page_token,
                    offer_notes=notes_from_store(s) or None,
                ))
            except RejectedListing as exc:
                self.last_rejections += 1
                log.debug("serpapi store rejected %s: %s", name, exc)
        return out

"""Flipkart Affiliate API – keyword search (official affiliate API).

Docs: https://affiliate.flipkart.com/api-docs/af_prod_ref.html
Auth headers: Fk-Affiliate-Id, Fk-Affiliate-Token (from the Flipkart Affiliate dashboard).
Endpoint: GET {FLIPKART_API_BASE}/search.json?query=...&resultCount=N

Each product has productBaseInfoV1 (productId, title, productUrl, flipkartSpecialPrice,
flipkartSellingPrice, maximumRetailPrice, inStock, productBrand, imageUrls, attributes, categoryPath)
and productShippingInfoV1 (shippingCharges, sellerName). The response list key is parsed
defensively (`products` or `productInfoList`) because the docs show both shapes for different endpoints.
`productUrl` is the exact Flipkart listing (with affiliate tracking) and is used unchanged.
"""
from __future__ import annotations

import logging

from app.providers.base import BaseProvider, Listing
from app.providers.validation import RejectedListing, build_listing

log = logging.getLogger(__name__)


class FlipkartAffiliateProvider(BaseProvider):
    id = "flipkart_affiliate"
    display_name = "Flipkart (Affiliate API)"
    source_type = "official_api"
    retailers = ("Flipkart",)
    credential_env = ("FLIPKART_AFFILIATE_ID", "FLIPKART_AFFILIATE_TOKEN")
    docs_url = "https://affiliate.flipkart.com/api-docs/"

    def is_configured(self) -> bool:
        return bool(self.settings.flipkart_affiliate_id and self.settings.flipkart_affiliate_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Fk-Affiliate-Id": self.settings.flipkart_affiliate_id or "",
            "Fk-Affiliate-Token": self.settings.flipkart_affiliate_token or "",
            "Accept": "application/json",
        }

    async def search_products(self, query: str, limit: int = 20) -> list[Listing]:
        data = await self.request_json(
            "GET",
            f"{self.settings.flipkart_api_base}/search.json",
            params={"query": query, "resultCount": min(10, limit)},
            headers=self._headers(),
        )
        products = data.get("products") or data.get("productInfoList") or []
        self.last_rejections = 0
        out = []
        for p in products:
            try:
                out.append(self.normalize(p))
            except RejectedListing as exc:
                self.last_rejections += 1
                log.debug("flipkart rejected listing: %s", exc)
        return out

    def normalize(self, p: dict) -> Listing:
        base = p.get("productBaseInfoV1") or (p.get("productBaseInfo") or {}).get("productAttributes") or {}
        ship = p.get("productShippingInfoV1") or {}
        special = base.get("flipkartSpecialPrice") or {}
        selling = base.get("flipkartSellingPrice") or {}
        price_obj = special if special.get("amount") else selling
        mrp = (base.get("maximumRetailPrice") or {}).get("amount")
        images = base.get("imageUrls") or {}
        image = images.get("400x400") or images.get("800x800") or next(iter(images.values()), None) if images else None
        attrs = base.get("attributes") or {}
        in_stock = base.get("inStock")
        shipping = (ship.get("shippingCharges") or {}).get("amount")
        return build_listing(
            provider_id=self.id,
            source_type=self.source_type,
            listing_key=base.get("productId"),
            title=base.get("title"),
            retailer="Flipkart",
            price=price_obj.get("amount"),
            currency=price_obj.get("currency"),
            product_url=base.get("productUrl"),
            seller_name=ship.get("sellerName"),
            mrp=mrp,
            shipping_cost=shipping,
            availability="in_stock" if in_stock is True else "out_of_stock" if in_stock is False else "unknown",
            image_url=image,
            brand=base.get("productBrand"),
            colour=attrs.get("color") or None,
            category_hint=base.get("categoryPath"),
            identifiers={"flipkart_pid": base["productId"]} if base.get("productId") else {},
        )

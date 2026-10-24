"""Amazon India via the Amazon Creators API (official affiliate API that replaced PA-API 5).

Docs: https://affiliate-program.amazon.com/creatorsapi/docs/en-us/
- Token: OAuth2 client_credentials, scope "creatorsapi::default". India (IN) uses the EU
  credential region (v3.2) whose token endpoint is https://api.amazon.co.uk/auth/o2/token.
- searchItems: POST https://creatorsapi.amazon/catalog/v1/searchItems with header x-marketplace.
- getItems:    POST https://creatorsapi.amazon/catalog/v1/getItems with itemIds (max 10).
- Response: searchResult.items[] / itemsResult.items[] with asin, detailPageURL,
  itemInfo.title.displayValue, images.primary.*.url, offersV2.listings[].price.money.{amount,currency}.

`detailPageURL` is Amazon's exact product page (with your partner tag) and is used unchanged.
"""
from __future__ import annotations

import logging
import time

from app.providers.base import BaseProvider, Listing, ProviderError
from app.providers.validation import RejectedListing, build_listing

log = logging.getLogger(__name__)

RESOURCES = [
    "itemInfo.title",
    "itemInfo.byLineInfo",
    "itemInfo.externalIds",
    "itemInfo.manufactureInfo",
    "itemInfo.productInfo",
    "images.primary.large",
    "offersV2.listings.price",
    "offersV2.listings.availability",
    "offersV2.listings.condition",
    "offersV2.listings.merchantInfo",
    "offersV2.listings.isBuyBoxWinner",
]

AVAILABILITY_MAP = {"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock", "AVAILABLE_DATE": "out_of_stock",
                    "PREORDER": "preorder", "LEADTIME": "in_stock", "IN_STOCK_SCARCE": "in_stock"}


class AmazonCreatorsProvider(BaseProvider):
    id = "amazon_creators_api"
    display_name = "Amazon India (Creators API)"
    source_type = "official_api"
    retailers = ("Amazon India",)
    credential_env = ("AMAZON_CREATORS_CREDENTIAL_ID", "AMAZON_CREATORS_CREDENTIAL_SECRET", "AMAZON_PARTNER_TAG")
    docs_url = "https://affiliate-program.amazon.com/creatorsapi/docs/en-us/"

    _token: str | None = None
    _token_expiry: float = 0.0

    def is_configured(self) -> bool:
        s = self.settings
        return bool(s.amazon_creators_credential_id and s.amazon_creators_credential_secret and s.amazon_partner_tag)

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        s = self.settings
        data = await self.request_json(
            "POST",
            s.amazon_creators_token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": s.amazon_creators_credential_id,
                "client_secret": s.amazon_creators_credential_secret,
                "scope": "creatorsapi::default",
            },
        )
        token = data.get("access_token")
        if not token:
            raise ProviderError("auth_failed", "token endpoint returned no access_token")
        self._token = token
        self._token_expiry = time.time() + float(data.get("expires_in", 3600))
        return token

    async def _post(self, operation: str, body: dict) -> dict:
        token = await self._access_token()
        s = self.settings
        payload = {"partnerTag": s.amazon_partner_tag, "marketplace": s.amazon_marketplace, "resources": RESOURCES, **body}
        return await self.request_json(
            "POST",
            f"{s.amazon_creators_api_base}/{operation}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "x-marketplace": s.amazon_marketplace},
        )

    async def search_products(self, query: str, limit: int = 20) -> list[Listing]:
        data = await self._post("searchItems", {"keywords": query, "searchIndex": "Electronics", "itemCount": min(10, limit)})
        items = (data.get("searchResult") or {}).get("items") or []
        return self._normalize_items(items)

    async def refresh_listings(self, listing_keys: list[str], query: str) -> list[Listing]:
        out: list[Listing] = []
        for i in range(0, len(listing_keys), 10):
            data = await self._post("getItems", {"itemIds": listing_keys[i:i + 10]})
            out.extend(self._normalize_items((data.get("itemsResult") or {}).get("items") or []))
        return out

    def _normalize_items(self, items: list[dict]) -> list[Listing]:
        self.last_rejections = 0
        out = []
        for item in items:
            try:
                out.append(self.normalize(item))
            except RejectedListing as exc:
                self.last_rejections += 1
                log.debug("amazon rejected %s: %s", item.get("asin"), exc)
        return out

    def normalize(self, item: dict) -> Listing:
        info = item.get("itemInfo") or {}
        title = ((info.get("title") or {}).get("displayValue"))
        byline = info.get("byLineInfo") or {}
        brand = ((byline.get("brand") or {}).get("displayValue"))
        listings = ((item.get("offersV2") or {}).get("listings")) or []
        chosen = next((lst for lst in listings if lst.get("isBuyBoxWinner")), listings[0] if listings else None)
        if chosen is None:
            raise RejectedListing("no_offer_listing")
        money = ((chosen.get("price") or {}).get("money")) or {}
        condition = ((chosen.get("condition") or {}).get("value") or "New")
        if condition.lower() != "new" and title and "refurb" not in title.lower():
            title = f"{title} (Renewed)"
        avail = AVAILABILITY_MAP.get(((chosen.get("availability") or {}).get("type") or "").upper(), "unknown")
        images = (item.get("images") or {}).get("primary") or {}
        image = next((images[k].get("url") for k in ("large", "medium", "small") if isinstance(images.get(k), dict)), None)
        ids: dict[str, str] = {}
        ext = info.get("externalIds") or {}
        for src, kind in (("eaNs", "gtin"), ("upCs", "gtin")):
            vals = (ext.get(src) or {}).get("displayValues") or []
            if vals and "gtin" not in ids:
                ids[kind] = str(vals[0])
        model = ((info.get("manufactureInfo") or {}).get("model") or {}).get("displayValue")
        if model:
            ids["model_number"] = str(model)
        colour = ((info.get("productInfo") or {}).get("color") or {}).get("displayValue")
        merchant = ((chosen.get("merchantInfo") or {}).get("name"))
        return build_listing(
            provider_id=self.id,
            source_type=self.source_type,
            listing_key=item.get("asin"),
            title=title,
            retailer="Amazon India",
            price=money.get("amount"),
            currency=money.get("currency"),
            product_url=item.get("detailPageURL"),
            seller_name=merchant,
            availability=avail,
            image_url=image,
            brand=brand,
            colour=colour,
            identifiers=ids,
        )

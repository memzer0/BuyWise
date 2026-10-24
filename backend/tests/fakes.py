"""Test-only provider. Lives under tests/ so it can never be loaded by the production app."""
from __future__ import annotations

from app.providers.base import BaseProvider, Listing, ProviderError
from app.providers.validation import build_listing


class FakeProvider(BaseProvider):
    id = "fake_provider"
    display_name = "Fake test provider"
    source_type = "official_api"

    def __init__(self, settings, catalog: dict[str, list[dict]] | None = None, error: ProviderError | None = None,
                 provider_id: str | None = None):  # noqa: ANN001
        super().__init__(settings)
        self.catalog = catalog or {}
        self.error = error
        self.calls = 0
        if provider_id:
            self.id = provider_id

    def is_configured(self) -> bool:
        return True

    async def search_products(self, query: str, limit: int = 20) -> list[Listing]:
        self.calls += 1
        if self.error:
            raise self.error
        out = []
        for key, rows in self.catalog.items():
            if key in query or query in key:
                for r in rows:
                    out.append(build_listing(provider_id=self.id, source_type=self.source_type, **r))
        return out


def row(key: str, title: str, price: float, retailer: str = "Shop A", url: str | None = None, **extra) -> dict:  # noqa: ANN003
    return {"listing_key": key, "title": title, "retailer": retailer, "price": price, "currency": "INR",
            "product_url": url or f"https://{retailer.lower().replace(' ', '')}.example/p/{key}", **extra}

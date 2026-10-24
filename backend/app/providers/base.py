"""Common provider interface and the normalized listing structure every adapter returns."""
from __future__ import annotations

import abc
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.core.config import Settings


@dataclass
class Listing:
    """One seller offer exactly as reported by a provider (already validated)."""

    provider_id: str
    listing_key: str              # stable id inside the provider (ASIN, Flipkart pid, Google product id + seller)
    title: str
    retailer: str
    price: float
    currency: str
    product_url: str
    link_type: str                # exact_listing / aggregator_page / search_page
    fetched_at: datetime
    source_type: str              # official_api / licensed_api
    seller_name: str | None = None
    mrp: float | None = None
    shipping_cost: float | None = None
    availability: str = "unknown"
    image_url: str | None = None
    brand: str | None = None
    colour: str | None = None
    category_hint: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    warranty: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    specs: dict[str, str] = field(default_factory=dict)
    provider_ref: str | None = None
    offer_notes: list[str] | None = None  # bank offers / coupons as written by the store   # provider token for follow-up lookups (e.g. Google Shopping store list)


@dataclass
class ProviderResult:
    provider_id: str
    status: str                   # ok / empty / not_configured / error / rate_limited / cooling_down
    listings: list[Listing] = field(default_factory=list)
    rejected: int = 0             # listings dropped by validation (missing price, bad URL, wrong currency…)
    extra: dict | None = None     # product-level data such as reviews
    error: str | None = None
    http_status: int | None = None
    retry_after: float | None = None
    duration_ms: int = 0


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, http_status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.retry_after = retry_after


class BaseProvider(abc.ABC):
    id: str = "base"
    display_name: str = "Base"
    source_type: str = "official_api"
    retailers: tuple[str, ...] = ()
    credential_env: tuple[str, ...] = ()
    docs_url: str = ""
    last_rejections: int = 0
    last_extra: dict | None = None   # extra product-level data from the last call (e.g. reviews)

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._lock = asyncio.Semaphore(max(1, settings.provider_max_concurrency))
        self._last_call = 0.0
        self._spacing_lock = asyncio.Lock()

    # ---- capability flags -------------------------------------------------
    @abc.abstractmethod
    def is_configured(self) -> bool: ...

    @abc.abstractmethod
    async def search_products(self, query: str, limit: int = 20) -> list[Listing]: ...

    async def refresh_listings(self, listing_keys: list[str], query: str) -> list[Listing]:
        """Re-fetch current data for known listings. Default: re-run the search and keep matching keys."""
        wanted = set(listing_keys)
        return [lst for lst in await self.search_products(query, limit=40) if lst.listing_key in wanted]

    # ---- shared HTTP plumbing ---------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.provider_timeout_seconds),
                headers={"User-Agent": "BuyWise/1.0 (price comparison; contact via project README)"},
                follow_redirects=False,
            )
        return self._client

    async def _respect_spacing(self) -> None:
        async with self._spacing_lock:
            wait = self.settings.provider_min_interval_seconds - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def request_json(self, method: str, url: str, **kwargs) -> dict:  # noqa: ANN003
        async with self._lock:
            await self._respect_spacing()
            try:
                resp = await self.client.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                raise ProviderError("timeout", f"timed out after {self.settings.provider_timeout_seconds}s") from exc
            except httpx.HTTPError as exc:
                raise ProviderError("network", f"{type(exc).__name__}: {exc}") from exc
        return self._decode(resp)

    def _decode(self, resp: httpx.Response) -> dict:
        if resp.status_code == 429:
            raise ProviderError("rate_limited", "provider returned HTTP 429", 429, _retry_after(resp))
        if resp.status_code in (401, 403):
            raise ProviderError("access_denied", f"provider returned HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
        if resp.status_code >= 500:
            raise ProviderError("server_error", f"provider returned HTTP {resp.status_code}", resp.status_code, _retry_after(resp))
        if resp.status_code >= 400:
            raise ProviderError("bad_request", f"provider returned HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
        if len(resp.content) > self.settings.max_response_bytes:
            raise ProviderError("response_too_large", f"response exceeded {self.settings.max_response_bytes} bytes")
        ctype = resp.headers.get("content-type", "")
        if "json" not in ctype:
            raise ProviderError("not_json", f"expected JSON, got '{ctype or 'no content-type'}'", resp.status_code)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError("malformed_json", "response body is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("malformed_json", "top-level JSON is not an object")
        return data

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _retry_after(resp: httpx.Response) -> float | None:
    val = resp.headers.get("retry-after")
    if not val:
        return None
    try:
        return max(0.0, float(val))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(val)
            return max(0.0, dt.timestamp() - time.time())
        except Exception:  # noqa: BLE001
            return None


def parse_price(value) -> float | None:  # noqa: ANN001
    """Accept numbers or strings like '₹1,29,900.00'. Returns None for missing / non-positive values."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
        if not cleaned or cleaned.count(".") > 1:
            return None
        try:
            v = float(cleaned)
        except ValueError:
            return None
    return v if v > 0 else None

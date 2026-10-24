"""Holds provider instances, runs them concurrently with failure isolation, cooldown and backoff."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Provider, ProviderError as ProviderErrorRow
from app.providers.amazon_creators import AmazonCreatorsProvider
from app.providers.base import BaseProvider, ProviderError, ProviderResult
from app.providers.flipkart_affiliate import FlipkartAffiliateProvider
from app.providers.serpapi_shopping import SerpApiGoogleShoppingProvider

log = logging.getLogger(__name__)

# Order = priority: official retailer APIs first, then licensed aggregators.
PROVIDER_CLASSES: list[type[BaseProvider]] = [AmazonCreatorsProvider, FlipkartAffiliateProvider, SerpApiGoogleShoppingProvider]

# Retailers with no public / authorised data API that BuyWise could verify. Listed for transparency only.
UNSUPPORTED_SOURCES = [
    {"name": "Croma", "reason": "No public product/price API found; scraping not used."},
    {"name": "Reliance Digital", "reason": "No public product/price API found; scraping not used."},
    {"name": "Vijay Sales", "reason": "No public product/price API found; scraping not used."},
    {"name": "Smartprix / 91mobiles", "reason": "No public API documented; offers from these retailers may still appear via Google Shopping."},
]


class ProviderRegistry:
    def __init__(self, settings: Settings, providers: list[BaseProvider] | None = None):
        self.settings = settings
        self.providers: list[BaseProvider] = providers if providers is not None else [cls(settings) for cls in PROVIDER_CLASSES]

    def get(self, provider_id: str) -> BaseProvider | None:
        return next((p for p in self.providers if p.id == provider_id), None)

    def configured(self) -> list[BaseProvider]:
        return [p for p in self.providers if p.is_configured()]

    def ensure_rows(self, db: Session) -> None:
        for p in self.providers:
            if db.get(Provider, p.id) is None:
                db.add(Provider(id=p.id, display_name=p.display_name))
        db.commit()

    async def run(self, db: Session, op: str, provider: BaseProvider, *args, context: str = "") -> ProviderResult:  # noqa: ANN002
        """Run one provider operation with cooldown/backoff bookkeeping. Never raises."""
        row = db.get(Provider, provider.id)
        if not provider.is_configured():
            return ProviderResult(provider.id, "not_configured", error=f"missing credentials: {', '.join(provider.credential_env)}")
        now = datetime.now(timezone.utc)
        if row and row.cooldown_until and _aware(row.cooldown_until) > now:
            secs = int((_aware(row.cooldown_until) - now).total_seconds())
            return ProviderResult(provider.id, "cooling_down", error=f"backing off after errors; retry in {secs}s")
        started = time.monotonic()
        provider.last_rejections = 0
        provider.last_extra = None
        try:
            listings = await getattr(provider, op)(*args)
        except ProviderError as exc:
            self._record_failure(db, row, provider, exc, context)
            status = "rate_limited" if exc.kind in ("rate_limited", "quota_exceeded") else "error"
            return ProviderResult(provider.id, status, error=f"{exc.kind}: {exc}", http_status=exc.http_status,
                                  retry_after=exc.retry_after, duration_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 – isolate any adapter bug from the rest of the search
            log.exception("provider %s crashed", provider.id)
            self._record_failure(db, row, provider, ProviderError("adapter_exception", f"{type(exc).__name__}: {exc}"), context)
            return ProviderResult(provider.id, "error", error=f"adapter_exception: {type(exc).__name__}",
                                  duration_ms=int((time.monotonic() - started) * 1000))
        if row:
            row.last_success_at = now
            row.consecutive_failures = 0
            row.cooldown_until = None
            row.total_requests = (row.total_requests or 0) + 1
            db.commit()
        return ProviderResult(provider.id, "ok" if listings else "empty", listings=listings,
                              rejected=getattr(provider, "last_rejections", 0), extra=getattr(provider, "last_extra", None),
                              duration_ms=int((time.monotonic() - started) * 1000))

    def _record_failure(self, db: Session, row: Provider | None, provider: BaseProvider, exc: ProviderError, context: str) -> None:
        now = datetime.now(timezone.utc)
        db.add(ProviderErrorRow(provider_id=provider.id, kind=exc.kind, message=str(exc)[:1000],
                                http_status=exc.http_status, context=context[:300]))
        if row:
            row.last_failure_at = now
            row.last_error = f"{exc.kind}: {str(exc)[:400]}"
            row.consecutive_failures = (row.consecutive_failures or 0) + 1
            row.total_requests = (row.total_requests or 0) + 1
            if exc.kind in ("rate_limited", "quota_exceeded", "server_error", "timeout", "network", "access_denied"):
                backoff = min(self.settings.backoff_max_seconds,
                              self.settings.backoff_base_seconds * (2 ** (row.consecutive_failures - 1)))
                if exc.retry_after:
                    backoff = max(backoff, exc.retry_after)
                row.cooldown_until = now + timedelta(seconds=backoff)
        db.commit()

    async def run_all(self, db: Session, op: str, *args, context: str = "") -> list[ProviderResult]:  # noqa: ANN002
        # DB bookkeeping is synchronous; provider I/O runs concurrently.
        results = await asyncio.gather(*(self.run(db, op, p, *args, context=context) for p in self.providers))
        return list(results)

    async def aclose(self) -> None:
        for p in self.providers:
            await p.aclose()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

"""In-process automatic refresh scheduler (no Redis required).

Every SCHEDULER_TICK_SECONDS it picks tracked products whose prices are due:
  * popular (watchlisted, has an alert, or viewed ≥ POPULAR_VIEW_THRESHOLD times) → every REFRESH_POPULAR_MINUTES
  * other products that have been viewed at least once                         → every REFRESH_NORMAL_MINUTES
At most SCHEDULER_BATCH_SIZE products per tick, oldest first. It also re-runs up to PRETRACK_PER_TICK of the
PRETRACK_QUERIES searches that are due (every PRETRACK_INTERVAL_HOURS), so popular products collect real price
history before anyone opens them. Provider spacing, concurrency limits,
Retry-After and exponential backoff are enforced by the provider layer.

For multi-process deployments run only ONE instance with SCHEDULER_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.database.session import SessionLocal
from app.models import PriceAlert, Product, SearchRecord, TrackedPurchase, WatchlistItem
from app.services.catalog import normalize_query

log = logging.getLogger(__name__)


class RefreshScheduler:
    def __init__(self, catalog, regret=None) -> None:  # noqa: ANN001
        self.catalog = catalog
        self.regret = regret
        self.last_purchase_checks = 0
        self.settings = catalog.settings
        self._task: asyncio.Task | None = None
        self.last_tick_at: datetime | None = None
        self.last_tick_refreshed: list[int] = []
        self.last_pretrack: list[str] = []
        self.last_error: str | None = None
        self.ticks = 0

    def start(self) -> None:
        if self.settings.scheduler_enabled and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="buywise-refresh-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def due_products(self, now: datetime | None = None) -> list[int]:
        now = now or datetime.now(timezone.utc)
        s = self.settings
        with SessionLocal() as db:
            watched = set(db.scalars(select(WatchlistItem.product_id)).all()) | set(
                db.scalars(select(PriceAlert.product_id).where(PriceAlert.active.is_(True))).all()) | set(
                db.scalars(select(TrackedPurchase.product_id)).all())
            candidates = db.scalars(
                select(Product).where(or_(Product.view_count > 0, Product.id.in_(watched or {-1})))
                .order_by(Product.last_refreshed_at.is_not(None), Product.last_refreshed_at)
            ).all()
            due = []
            for p in candidates:
                popular = p.id in watched or p.view_count >= s.popular_view_threshold
                interval = timedelta(minutes=s.refresh_popular_minutes if popular else s.refresh_normal_minutes)
                last = p.last_refreshed_at
                if last is not None and last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last is None or now - last >= interval:
                    due.append((0 if popular else 1, p.id))
            due.sort()
            return [pid for _, pid in due[: s.scheduler_batch_size]]

    def due_pretrack_queries(self, now: datetime | None = None) -> list[str]:
        """Pre-track searches not run within PRETRACK_INTERVAL_HOURS (by anyone), never-run ones first."""
        s = self.settings
        if not s.pretrack_enabled:
            return []
        now = now or datetime.now(timezone.utc)
        due = []
        with SessionLocal() as db:
            for q in s.pretrack_query_list:
                last = db.scalar(select(func.max(SearchRecord.created_at)).where(SearchRecord.normalized_query == normalize_query(q)))
                if last is not None and last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last is None or now - last >= timedelta(hours=s.pretrack_interval_hours):
                    due.append((last or datetime.min.replace(tzinfo=timezone.utc), q))
        due.sort()
        return [q for _, q in due[: s.pretrack_per_tick]]

    async def pretrack(self) -> list[str]:
        queries = self.due_pretrack_queries()
        for q in queries:
            with SessionLocal() as db:
                await self.catalog.search(db, q)
        self.last_pretrack = queries
        return queries

    async def tick(self) -> list[int]:
        self.ticks += 1
        self.last_tick_at = datetime.now(timezone.utc)
        ids: list[int] = []
        if self.catalog.registry.configured():
            ids = self.due_products()
            for pid in ids:
                await self.catalog.refresh_product(pid, "scheduler")
            await self.pretrack()
        self.last_tick_refreshed = ids
        self.check_purchases()
        return ids

    def check_purchases(self) -> int:
        """Re-evaluate tracked purchases against the latest stored offers (bucketed, so at most one check/hour)."""
        if self.regret is None:
            return 0
        with SessionLocal() as db:
            self.last_purchase_checks = self.regret.monitor_all(db)
        return self.last_purchase_checks

    async def _loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            try:
                await self.tick()
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                log.exception("scheduler tick failed")
            await asyncio.sleep(self.settings.scheduler_tick_seconds)

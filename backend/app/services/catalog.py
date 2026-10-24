"""Search, product views, refresh, price history and alerts – the core application service."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.session import SessionLocal
from app.matching.attributes import TOKEN_RE, extract_attributes, normalize_text
from app.models import FetchJob, Offer, PriceObservation, Product, SearchRecord
from app.pricing.offers import OfferView, aware, eligible_for_best_price, freshness_status, select_lowest
from app.providers.base import BaseProvider
from app.providers.registry import ProviderRegistry
from app.scoring.buywise import compute_score
from app.pricing.final_price import compute as final_price_compute
from app.reviews.analyze import analyze as analyze_reviews
from app.scoring.decision import _inr as inr, decide, timing as decision_timing
from app.scoring.deal import evaluate as evaluate_deal
from app.scoring.prediction import predict
from app.services.alerts import evaluate_alerts
from app.services import demo_history
from app.services.ingest import backfill_variant, ingest_all
from app.pricing.trust import TrustPolicy, normalize_store
from app.services.singleflight import SingleFlight

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

RANGES = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365}
QUERY_MAX = 120


def normalize_query(q: str) -> str:
    q = normalize_text(q)
    q = re.sub(r"[^\w\s.+\-/\"']", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q[:QUERY_MAX]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class CatalogService:
    def __init__(self, settings: Settings, registry: ProviderRegistry):
        self.settings = settings
        self.registry = registry
        self.flights = SingleFlight()
        self.trust = TrustPolicy(settings.trusted_stores, settings.trusted_domains, settings.preferred_stores)
        self.background: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ offers
    def offer_view(self, o: Offer, live_ids: set[int] | None = None) -> OfferView:
        return OfferView(
            id=o.id, price=o.price, currency=o.currency, availability=o.availability,
            freshness=freshness_status(o.last_verified_at, self.settings, fetched_this_request=bool(live_ids and o.id in live_ids),
                                       has_price=o.price is not None),
            match_status=o.match_status, verification_status=o.verification_status, condition=o.condition,
            link_type=o.link_type, shipping_cost=o.shipping_cost,
            trusted=self.is_trusted(o) or not self.settings.trusted_only,
        )

    def preferred_rank(self, o: Offer) -> int | None:
        return self.trust.preferred_rank(o.retailer.name if o.retailer else None, o.product_url, o.link_type)

    def is_trusted(self, o: Offer) -> bool:
        return self.trust.is_trusted(o.retailer.name if o.retailer else None, o.product_url, o.link_type)

    def offer_dict(self, o: Offer, live_ids: set[int] | None = None, best_id: int | None = None) -> dict:
        v = self.offer_view(o, live_ids)
        ok, why = eligible_for_best_price(v)
        provider = self.registry.get(o.provider_id)
        return {
            "offer_id": o.id,
            "canonical_product_id": o.product_id,
            "provider": o.provider_id,
            "provider_name": provider.display_name if provider else o.provider_id,
            "retailer": o.retailer.name if o.retailer else None,
            "seller_name": o.seller_name,
            "listing_title": o.listing_title,
            "price": o.price,
            "mrp": o.mrp,
            "currency": o.currency,
            "shipping_cost": o.shipping_cost,
            "total_cost": v.total_cost,
            "availability": o.availability,
            "condition": o.condition,
            "product_url": o.product_url,
            "link_type": o.link_type,
            "image_url": o.image_url,
            "rating": o.rating,
            "rating_count": o.rating_count,
            "warranty": o.warranty,
            "fetched_at": _iso(o.fetched_at),
            "last_verified_at": _iso(o.last_verified_at),
            "source_type": o.source_type,
            "freshness_status": v.freshness,
            "verification_status": o.verification_status,
            "match_status": o.match_status,
            "match_confidence": o.match_confidence,
            "match_evidence": o.match_evidence,
            "eligible_for_best_price": ok,
            "ineligible_reason": why,
            "is_best_price": best_id == o.id,
            "offer_notes": o.offer_notes or [],
            "trusted_store": self.is_trusted(o),
            "preferred_rank": self.preferred_rank(o),
            "error_reason": o.error_reason,
        }

    # ------------------------------------------------------------- summaries
    def product_summary(self, p: Product, live_ids: set[int] | None = None) -> dict:
        views = [self.offer_view(o, live_ids) for o in self.visible_offers(p)]
        best = select_lowest(views, include_refurbished=p.condition != "new")
        best_offer = next((o for o in p.offers if best and o.id == best.id), None)
        last = max((aware(o.last_verified_at) for o in p.offers if o.last_verified_at), default=None)
        return {
            "id": p.id,
            "title": p.title,
            "brand": p.brand,
            "category": p.category,
            "image_url": p.image_url,
            "storage_gb": p.storage_gb,
            "ram_gb": p.ram_gb,
            "colour": p.colour,
            "condition": p.condition,
            "screen_inches": p.screen_inches,
            "offer_count": len(p.offers),
            "verified_offer_count": sum(1 for v in views if eligible_for_best_price(v)[0]),
            "trusted_offer_count": sum(1 for o in p.offers if self.is_trusted(o)),
            "preferred_stores": sorted({o.retailer.name for o in p.offers if o.retailer and self.preferred_rank(o) is not None}),
            **self._price_change(best_offer),
            "retailers": sorted({o.retailer.name for o in p.offers if o.retailer}),
            "best_price": best.price if best else None,
            "best_retailer": best_offer.retailer.name if best_offer and best_offer.retailer else None,
            "best_freshness": best.freshness if best else None,
            "best_link_type": best.link_type if best else None,
            "last_verified_at": _iso(last),
        }

    @staticmethod
    def _price_change(best: Offer | None) -> dict:
        """Change of the best offer's price versus its previous different observed price (BuyHatke-style drop tag)."""
        if best is None or best.price is None:
            return {"previous_price": None, "price_change": None}
        prev = next((ob.price for ob in sorted(best.observations, key=lambda x: x.observed_at, reverse=True)
                     if abs(ob.price - best.price) > 0.5), None)
        return {"previous_price": prev, "price_change": round(best.price - prev, 2) if prev is not None else None}

    # ------------------------------------------------------------------ search
    async def search(self, db: Session, query: str) -> dict:
        norm = normalize_query(query)
        cutoff = now_utc() - timedelta(seconds=self.settings.search_cache_seconds)
        cached = db.scalar(select(SearchRecord).where(SearchRecord.normalized_query == norm, SearchRecord.created_at >= cutoff)
                           .order_by(SearchRecord.created_at.desc()).limit(1))
        live_ids: set[int] = set()
        if cached is not None:
            product_ids, report, source = list(cached.product_ids), list(cached.provider_report), "cache"
            fetched_at = _iso(cached.created_at)
        else:
            (product_ids, report, live_ids), _shared = await self.flights.do(f"search:{norm}", lambda: self._search_live(db, norm))
            source, fetched_at = "live", _iso(now_utc())
        products = []
        if product_ids:
            rows = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
            products = [self.product_summary(rows[i], live_ids) for i in product_ids if i in rows]
        qtokens = set(TOKEN_RE.findall(norm))
        q = extract_attributes(norm)
        for idx, p in enumerate(products):
            ttoks = set(TOKEN_RE.findall(normalize_text(p["title"])))
            pa = extract_attributes(p["title"])
            score = (len(qtokens & ttoks) / len(qtokens) if qtokens else 0) + min(p["verified_offer_count"], 3) * 0.05
            mismatches = []
            if q.model_tokens and pa.model_tokens and not (q.model_tokens <= pa.model_tokens):
                score -= 0.5
                mismatches.append("model")
            if pa.tier - q.tier:
                score -= 0.3
                mismatches.append("variant")
            if q.storage_gb and p["storage_gb"] and q.storage_gb != p["storage_gb"]:
                score -= 0.3
                mismatches.append("storage")
            if p["preferred_stores"]:
                score += 0.15  # sold by Flipkart / Reliance Digital / Amazon / Vijay Sales / Croma
            if q.kind == "device" and p["category"] == "accessories":
                score -= 0.4
                mismatches.append("accessory")
            p["relevance"] = round(score - idx * 0.001, 4)
            p["query_mismatches"] = mismatches
        configured = [r for r in report if r["status"] != "not_configured"]
        ok = [r for r in configured if r["status"] in ("ok", "empty")]
        return {
            "query": query,
            "normalized_query": norm,
            "source": source,
            "fetched_at": fetched_at,
            "providers": report,
            "partial": bool(configured) and len(ok) < len(configured),
            "no_providers_configured": not configured,
            "all_providers_failed": bool(configured) and not ok,
            "products": products,
        }

    async def _search_live(self, db: Session, norm: str) -> tuple[list[int], list[dict], set[int]]:
        job = FetchJob(kind="search", trigger="user", target=norm, status="running")
        db.add(job)
        db.commit()
        results = await self.registry.run_all(db, "search_products", norm, 20, context=f"search:{norm}")
        product_ids: list[int] = []
        live_ids: set[int] = set()
        report = []
        for res in results:
            outcomes = ingest_all(db, res.listings, self.settings) if res.listings else []
            for oc in outcomes:
                live_ids.add(oc.offer_id)
                if oc.product_id not in product_ids:
                    product_ids.append(oc.product_id)
            provider = self.registry.get(res.provider_id)
            report.append({
                "provider": res.provider_id,
                "name": provider.display_name if provider else res.provider_id,
                "status": res.status,
                "listings": len(res.listings),
                "rejected": res.rejected,
                "error": res.error,
                "duration_ms": res.duration_ms,
            })
        any_ok = any(r["status"] in ("ok", "empty") for r in report)
        job.status = "success" if any_ok and all(r["status"] in ("ok", "empty", "not_configured") for r in report) else ("partial" if any_ok else "failed")
        job.detail = {"providers": report, "products": len(product_ids)}
        job.finished_at = now_utc()
        if any_ok:  # only cache results that came from at least one working provider
            db.add(SearchRecord(normalized_query=norm, product_ids=product_ids, provider_report=report))
            # Products whose offers were just fetched don't need an immediate re-fetch when opened.
            for p in db.scalars(select(Product).where(Product.id.in_(product_ids))):
                p.last_refreshed_at = now_utc()
        db.commit()
        for pid in product_ids:
            evaluate_alerts(db, self, pid)
        return product_ids, report, live_ids

    # ---------------------------------------------------------------- refresh
    def product_query(self, p: Product) -> str:
        name = re.split(r"\s*[:|;]\s*|\s+-\s+", p.title, maxsplit=1)[0]
        q = normalize_query(name)
        if p.storage_gb and str(p.storage_gb) not in q:
            q += f" {p.storage_gb}gb"
        return q[:100]

    def wants_store_links(self, p: Product) -> bool:
        return (self.settings.serpapi_store_links and (p.store_links_checked_at is None or p.review_data is None) and
                any(o.provider_ref and o.link_type == "aggregator_page" for o in p.offers))

    def needs_refresh(self, p: Product) -> bool:
        if self.wants_store_links(p) and self.registry.get("serpapi_google_shopping") and \
                self.registry.get("serpapi_google_shopping").is_configured():
            return True
        last = aware(p.last_refreshed_at) or max((aware(o.last_verified_at) for o in p.offers if o.last_verified_at), default=None)
        return last is None or (now_utc() - last).total_seconds() > self.settings.fresh_window_seconds

    async def refresh_product(self, product_id: int, trigger: str) -> dict:
        result, shared = await self.flights.do(f"refresh:{product_id}", lambda: self._refresh(product_id, trigger))
        return {**result, "joined_inflight_request": shared}

    def schedule_refresh(self, product_id: int, trigger: str) -> bool:
        if self.flights.in_progress(f"refresh:{product_id}"):
            return True
        if not self.registry.configured():
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # called outside the event loop – cannot start a background refresh
            log.warning("schedule_refresh called without a running event loop")
            return False
        task = asyncio.create_task(self.refresh_product(product_id, trigger))
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return True

    def refresh_in_progress(self, product_id: int) -> bool:
        return self.flights.in_progress(f"refresh:{product_id}")

    def _store_ref_offer(self, p: Product, provider_id: str) -> Offer | None:
        """Offer whose provider token can fetch the product's store list (cheapest verified one first)."""
        if provider_id != "serpapi_google_shopping" or not self.settings.serpapi_store_links:
            return None
        cands = [o for o in p.offers if o.provider_id == provider_id and o.provider_ref]
        cands.sort(key=lambda o: (o.match_status != "verified", o.price or 0))
        return cands[0] if cands else None

    async def _refresh(self, product_id: int, trigger: str) -> dict:
        db = SessionLocal()
        try:
            p = db.get(Product, product_id)
            if p is None:
                return {"status": "not_found", "providers": []}
            query = self.product_query(p)
            job = FetchJob(kind="refresh", trigger=trigger, target=f"product:{product_id}", status="running")
            db.add(job)
            db.commit()
            report = []
            seen_offer_ids: set[int] = set()
            for provider in self.registry.providers:
                keys = [o.listing_key for o in p.offers if o.provider_id == provider.id]
                overrides = type(provider).refresh_listings is not BaseProvider.refresh_listings
                preferred = None
                ref_offer = self._store_ref_offer(p, provider.id)
                if ref_offer is not None:
                    # One store-list call refreshes all stores of this product and yields exact retailer links.
                    res = await self.registry.run(db, "fetch_store_offers", provider, ref_offer.provider_ref,
                                                  ref_offer.listing_key.split("|")[0], p.title, context=f"stores:{product_id}")
                    preferred = product_id
                    if res.status in ("ok", "empty"):
                        p.store_links_checked_at = now_utc()
                    if res.extra and res.extra.get("reviews"):
                        p.review_data = res.extra["reviews"]
                    elif res.status in ("ok", "empty") and p.review_data is None:
                        # remember that Google returned no reviews, so we don't re-fetch on every visit
                        p.review_data = {"empty": True, "fetched_at": now_utc().isoformat()}
                elif keys and overrides:
                    res = await self.registry.run(db, "refresh_listings", provider, keys, query, context=f"refresh:{product_id}")
                else:
                    res = await self.registry.run(db, "search_products", provider, query, 20, context=f"refresh:{product_id}")
                if preferred is not None and res.listings:
                    backfill_variant(p, res.listings)
                outcomes = ingest_all(db, res.listings, self.settings, preferred_product_id=preferred) if res.listings else []
                seen_offer_ids.update(oc.offer_id for oc in outcomes)
                if res.status in ("ok", "empty"):
                    for o in db.scalars(select(Offer).where(Offer.product_id == product_id, Offer.provider_id == provider.id)):
                        if o.id not in seen_offer_ids:
                            o.last_seen_missing_at = now_utc()
                report.append({"provider": res.provider_id, "status": res.status, "listings": len(res.listings),
                               "error": res.error, "duration_ms": res.duration_ms})
            p = db.get(Product, product_id)
            any_ok = any(r["status"] in ("ok", "empty") for r in report)
            if any_ok:
                p.last_refreshed_at = now_utc()
            job.status = "success" if any_ok else "failed"
            job.detail = {"providers": report, "offers_updated": len(seen_offer_ids)}
            job.finished_at = now_utc()
            db.commit()
            evaluate_alerts(db, self, product_id)
            return {"status": job.status, "providers": report, "offers_updated": len(seen_offer_ids), "refreshed_at": _iso(now_utc())}
        except Exception as exc:  # noqa: BLE001
            log.exception("refresh failed for product %s", product_id)
            db.rollback()
            return {"status": "failed", "error": f"{type(exc).__name__}", "providers": []}
        finally:
            db.close()

    # ---------------------------------------------------------------- detail
    def visible_offers(self, p: Product) -> list[Offer]:
        """One offer per store: prefer an up-to-date price, then a verified match, then an exact store link,
        then the lower price (so a fresh store-page price replaces an old search result from the same store)."""
        cutoff = now_utc() - timedelta(seconds=self.settings.stale_after_seconds)

        def rank(o: Offer) -> tuple:
            seen = o.last_verified_at
            stale = seen is None or (seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)) < cutoff
            return (stale, o.match_status != "verified", o.link_type != "exact_listing",
                    o.price if o.price is not None else 1e12)

        best: dict[str, Offer] = {}
        for o in p.offers:
            key = normalize_store(o.retailer.name if o.retailer else "")
            cur = best.get(key)
            if cur is None or rank(o) < rank(cur):
                best[key] = o
        return [o for o in p.offers if best.get(normalize_store(o.retailer.name if o.retailer else "")) is o]

    @staticmethod
    def last_known_price(offers: list[dict]) -> dict | None:
        """Most recently confirmed price from a trusted store with a verified variant match – for reference when
        there is no current price. Never used for scores, "lowest price" or decisions."""
        cands = [o for o in offers if o["price"] is not None and o["trusted_store"] and o["match_status"] == "verified"
                 and o["last_verified_at"] and o["condition"] == "new"]
        if not cands:
            return None
        o = max(cands, key=lambda x: (x["last_verified_at"], -x["price"]))
        seen = datetime.fromisoformat(o["last_verified_at"])
        days = (now_utc() - (seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc))).days
        return {"price": o["price"], "retailer": o["retailer"], "observed_at": o["last_verified_at"],
                "date": seen.astimezone(IST).strftime("%d %b %Y"),
                "days_ago": days, "age": "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"}

    def product_detail(self, db: Session, p: Product, include_refurbished: bool = False, demo: bool = False) -> dict:
        shown = self.visible_offers(p)
        views = {o.id: self.offer_view(o) for o in shown}
        best = select_lowest(list(views.values()), include_refurbished=include_refurbished or p.condition != "new")
        offers = [self.offer_dict(o, best_id=best.id if best else None) for o in shown]
        eligible = [o for o in offers if o["eligible_for_best_price"]]
        prices = [o["price"] for o in eligible]
        history = self.history(db, p, "365d", demo=demo)
        daily = {datetime.fromisoformat(d["date"]).date(): d["min_price"] for d in history["daily_min"]}
        prediction = predict(daily)
        best_offer = next((o for o in offers if o["is_best_price"]), None)
        deal = evaluate_deal(best.price if best else None, daily,
                             [o["price"] for o in eligible if not o["is_best_price"]], now_utc().date())
        for o in offers:  # BuyHatke-style "x% cheaper / costlier" versus the headline (lowest verified) price
            o["vs_best_pct"] = (round((o["price"] - best.price) / best.price * 100, 1)
                                if best and o["price"] is not None and best.price else None)
        deal_d = deal.to_dict()
        last_known = None if best else self.last_known_price(offers)
        if last_known:
            deal_d["insight"] = {
                "kind": "info",
                "title": f"Last seen {inr(last_known['price'])} at {last_known['retailer']}, {last_known['age']}",
                "body": (f"BuyWise last confirmed this price on {last_known['date']} and hasn't been able to confirm it since, "
                         "so it isn't scored or shown as the current price. Press “Check prices now” to get today's price."),
            }
        decision = decide(
            best_price=best.price if best else None,
            best_retailer=best_offer["retailer"] if best_offer else None,
            best_availability=best_offer["availability"] if best_offer else None,
            best_link_exact=bool(best_offer and best_offer["link_type"] == "exact_listing"),
            store_count=len(eligible), deal=deal_d, lowest=history["lowest"], average=history["average"],
            span_days=history["span_days"], newer_models=self.newer_models(db, p), last_known=last_known,
        )
        is_demo = history.get("demo_points", 0) > 0
        if is_demo:
            # Demo mode (secret switch): flagged in the API via demo_history, but no visible wording.
            decision.evidence_level = "low"
        score = compute_score(
            self.settings,
            best_price=best.price if best else None,
            best_in_stock=bool(best_offer and best_offer["availability"] == "in_stock"),
            best_exact_link=bool(best_offer and best_offer["link_type"] == "exact_listing"),
            other_verified_prices=[o["price"] for o in eligible if not o["is_best_price"]],
            history_prices=[pt["price"] for pt in history["points"]],
            history_days=history["span_days"],
            prediction=prediction,
            ratings=[(o["rating"], o["rating_count"]) for o in eligible],
        )
        return {
            "variants": self.variants(db, p),
            "product": {
                **self.product_summary(p),
                "family": p.family,
                "specs": p.specs or {},
                "identifiers": [{"kind": i.kind, "value": i.value} for i in p.identifiers],
                "view_count": p.view_count,
                "last_refreshed_at": _iso(p.last_refreshed_at),
                "created_at": _iso(p.created_at),
            },
            "offers": offers,
            "summary": {
                "lowest_verified_price": min(prices) if prices else None,
                "highest_verified_price": max(prices) if prices else None,
                "price_difference": (max(prices) - min(prices)) if len(prices) >= 2 else None,
                "verified_offer_count": len(eligible),
                "last_known": last_known,
                "total_offer_count": len(offers),
                "shipping_note": "Totals include shipping only where the provider reported the shipping cost; "
                                 "'—' means shipping was not reported. Taxes are included in Indian retail prices.",
            },
            "score": {
                "score": score.score, "confidence": score.confidence, "verdict": score.verdict,
                "reasons": score.reasons, "limitations": score.limitations,
                "components": [c.__dict__ for c in score.components],
            },
            "prediction": prediction.__dict__,
            "deal": deal_d,
            "decision": decision.to_dict(),
            "timing": decision_timing(current=best.price if best else None, lowest=history["lowest"],
                                      highest=history["highest"], average=history["average"],
                                      days_observed=len(history["daily_min"]),
                                      pump=any(c["key"] == "no_price_pump" and c["status"] == "fail" for c in deal_d["checks"]),
                                      trend_per_day=prediction.slope_per_day if prediction.available else None),
            "reviews": analyze_reviews(p.review_data),
            "final_price": final_price_compute(offers, set(), False),
            "similar": self.similar(db, p),
            "refresh_in_progress": self.refresh_in_progress(p.id),
            "demo_history": is_demo,
            "demo_note": history.get("demo_note"),
        }

    def newer_models(self, db: Session, p: Product) -> list[dict]:
        """Tracked products of a newer generation of the same line: same brand, category, condition, Pro/Max tier,
        same family words, and a higher generation number (iPhone 16 -> 17, Galaxy S24 -> S25)."""
        a = extract_attributes(p.title, p.brand, p.colour)
        gen = _generation(a.model_tokens)
        if not p.brand or gen is None:
            return []
        fam = a.core_tokens - a.model_tokens - a.tier
        out = []
        for c in db.scalars(select(Product).where(Product.id != p.id, Product.brand == p.brand, Product.category == p.category,
                                                  Product.condition == p.condition).limit(400)):
            ca = extract_attributes(c.title, c.brand, c.colour)
            cg = _generation(ca.model_tokens)
            if cg is None or cg[0] != gen[0] or cg[1] <= gen[1] or ca.tier != a.tier or ca.kind != a.kind:
                continue
            if not (fam & (ca.core_tokens - ca.model_tokens - ca.tier)):
                continue
            s = self.product_summary(c)
            if s["best_price"] is None:
                continue
            out.append({"id": c.id, "title": c.title, "best_price": s["best_price"], "retailer": s["best_retailer"],
                        "image_url": c.image_url, "storage_gb": c.storage_gb})
        out.sort(key=lambda x: x["best_price"])
        return out[:5]

    def variants(self, db: Session, p: Product) -> list[dict]:
        """Other tracked products of the same model (same brand, model number, Pro/Max tier, condition) –
        e.g. other storage sizes or colours. Only products BuyWise has actually fetched are listed."""
        if not p.model_tokens or not p.brand:
            return []
        rows = db.scalars(select(Product).where(
            Product.id != p.id, Product.brand == p.brand, Product.model_tokens == p.model_tokens,
            Product.tier_tokens.is_(p.tier_tokens) if p.tier_tokens is None else Product.tier_tokens == p.tier_tokens,
            Product.condition == p.condition, Product.category == p.category,
        ).limit(24)).all()
        out = []
        for v in rows:
            if v.storage_gb is None and v.colour is None:
                continue
            s = self.product_summary(v)
            if s["trusted_offer_count"] == 0:
                continue
            out.append({"id": v.id, "storage_gb": v.storage_gb, "colour": v.colour, "best_price": s["best_price"],
                        "image_url": v.image_url,
                        "title": v.title})
        return out

    def similar(self, db: Session, p: Product, limit: int = 10) -> list[dict]:
        """Similar-looking products BuyWise has already found (same category, not accessories, sold by a trusted
        store), ranked by title similarity. Each carries its cheapest trusted offer for a direct Buy-now link."""
        base = set(TOKEN_RE.findall(normalize_text(p.title)))
        if not base:
            return []
        cands = db.scalars(select(Product).where(Product.id != p.id, Product.category == p.category,
                                                 Product.condition == p.condition).limit(400)).all()
        scored = []
        for c in cands:
            toks = set(TOKEN_RE.findall(normalize_text(c.title)))
            sim = len(base & toks) / len(base | toks) if toks else 0.0
            if c.brand and c.brand == p.brand:
                sim += 0.15
            if sim >= 0.2:
                scored.append((sim, c))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, c in scored:
            s = self.product_summary(c)
            if s["best_price"] is None:
                continue
            views = [self.offer_view(o) for o in self.visible_offers(c)]
            b = select_lowest(views, include_refurbished=c.condition != "new")
            offer = next((o for o in c.offers if b and o.id == b.id), None)
            out.append({"id": c.id, "title": c.title, "image_url": c.image_url, "best_price": s["best_price"],
                        "retailer": s["best_retailer"], "buy_url": offer.product_url if offer else None,
                        "link_type": offer.link_type if offer else None})
            if len(out) >= limit:
                break
        return out

    # ---------------------------------------------------------------- history
    def lowest_series(self, rows: list[PriceObservation]) -> list[dict]:
        """Lowest price across stores at each price check. Observations are grouped into checks by
        OBSERVATION_BUCKET_SECONDS; a store's last price counts until it is older than STALE_AFTER_SECONDS."""
        bucket_s = self.settings.observation_bucket_seconds
        stale = self.settings.stale_after_seconds
        groups: dict[int, list[PriceObservation]] = defaultdict(list)
        for r in rows:
            groups[int(aware(r.observed_at).timestamp() // bucket_s)].append(r)
        last: dict[int, tuple[float, float, str]] = {}  # offer_id -> (timestamp, price, retailer)
        out = []
        for b in sorted(groups):
            for r in groups[b]:
                last[r.offer_id] = (aware(r.observed_at).timestamp(), r.price, r.retailer_name)
            t = max(aware(r.observed_at).timestamp() for r in groups[b])
            live = [(price, ret) for ts, price, ret in last.values() if t - ts <= stale]
            if live:
                price, ret = min(live)
                out.append({"observed_at": datetime.fromtimestamp(t, timezone.utc).isoformat(), "price": price,
                            "retailer": ret, "stores": len(live)})
        return out

    def history(self, db: Session, p: Product, range_key: str, demo: bool = False) -> dict:
        days = RANGES[range_key]
        since = now_utc() - timedelta(days=days)
        first = db.scalar(select(func.min(PriceObservation.observed_at)).where(PriceObservation.product_id == p.id))
        # Only offers the shopper actually sees count: one per store, verified match, trusted store (by default).
        allowed = {o.id for o in self.visible_offers(p)
                   if o.match_status == "verified" and (self.is_trusted(o) or not self.settings.trusted_only)}
        rows = db.scalars(
            select(PriceObservation)
            .where(PriceObservation.product_id == p.id, PriceObservation.observed_at >= since,
                   PriceObservation.verification_status == "verified", PriceObservation.offer_id.in_(allowed or {-1}))
            .order_by(PriceObservation.observed_at)
        ).all()
        points = [{"observed_at": _iso(r.observed_at), "price": r.price, "retailer": r.retailer_name,
                   "offer_id": r.offer_id, "availability": r.availability, "source": r.provider_id} for r in rows]
        by_retailer: dict[str, list[dict]] = defaultdict(list)
        daily: dict[str, float] = {}
        for r in rows:
            by_retailer[r.retailer_name].append({"observed_at": _iso(r.observed_at), "price": r.price})
            d = aware(r.observed_at).date().isoformat()
            daily[d] = min(daily.get(d, r.price), r.price)
        span = 0
        if rows:
            span = (aware(rows[-1].observed_at) - aware(rows[0].observed_at)).days
        lowest_series = self.lowest_series(rows)
        latest_low = lowest_series[-1] if lowest_series else None
        demo_count = 0
        if demo and len(daily) < demo_history.MIN_REAL_DAYS:
            # Demo mode only: simulated points BEFORE the first real check, clearly flagged. Never stored.
            anchor = lowest_series[0]["price"] if lowest_series else self.product_summary(p)["best_price"]
            if anchor:
                first_day = aware(first).date() if first else None
                sim = [pt for pt in demo_history.demo_points(p.id, anchor, first_day, now_utc().date())
                       if datetime.fromisoformat(pt["observed_at"]) >= since]
                demo_count = len(sim)
                for pt in sim:
                    daily.setdefault(pt["observed_at"][:10], pt["price"])
                lowest_series = sim + lowest_series
                if lowest_series:
                    span = (datetime.fromisoformat(lowest_series[-1]["observed_at"])
                            - datetime.fromisoformat(lowest_series[0]["observed_at"])).days
                if latest_low is None and sim:
                    latest_low = sim[-1]
        low_prices = [pt["price"] for pt in lowest_series]
        return {
            "demo_points": demo_count,
            "demo_note": demo_history.NOTE if demo_count else None,
            "range": range_key,
            "points": points,
            "series": [{"retailer": k, "points": v} for k, v in by_retailer.items()],
            "daily_min": [{"date": k, "min_price": v} for k, v in sorted(daily.items())],
            "observation_count": len(rows),
            "span_days": span,
            # one point per price check: the lowest price across stores at that moment
            "lowest_series": lowest_series,
            "lowest": min(low_prices, default=None),
            "average": round(sum(daily.values()) / len(daily), 2) if daily else None,
            "highest": max(low_prices, default=None),
            "latest": latest_low,
            "tracking_started_at": _iso(first),
            "sufficient": len(lowest_series) >= 2,
            "note": None if len(lowest_series) >= 2 else (
                "Price tracking has started – the graph fills in as BuyWise checks prices." if rows
                else "No price checks in this range yet."),
        }


def _generation(model_tokens) -> tuple[str, int] | None:  # noqa: ANN001
    """('', 16) for iPhone 16, ('s', 24) for Galaxy S24; None when there isn't exactly one generation token."""
    import re as _re
    gens = [m for t in model_tokens if (m := _re.fullmatch(r"([a-z]{0,2})(\d{1,3})", t))]
    if len(gens) != 1:
        return None
    return gens[0].group(1), int(gens[0].group(2))


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return aware(dt).isoformat()

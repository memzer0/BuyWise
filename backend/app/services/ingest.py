"""Persist validated provider listings: match to canonical products, upsert offers, record observations."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.urls import host_of
from app.matching.attributes import COMPONENT_BRANDS, Attributes, classify_category, detect_brand, extract_attributes
from app.matching.matcher import compare
from app.models import MatchIssue, Offer, PriceObservation, Product, ProductIdentifier, Retailer
from app.providers.base import Listing

log = logging.getLogger(__name__)
SOFT_CONFLICTS = {"model_tokens", "screen_inches"}


@dataclass
class IngestOutcome:
    product_id: int
    offer_id: int
    match_status: str
    created_product: bool


def product_attributes(p: Product) -> Attributes:
    # Products saved before the brand fix may carry a component maker (e.g. "intel") as their brand.
    brand = p.brand if p.brand not in COMPONENT_BRANDS else (detect_brand(p.title) or p.brand)
    a = extract_attributes(p.title, brand, p.colour)
    # stored, possibly provider-supplied values win over title parsing
    a.storage_gb = p.storage_gb if p.storage_gb is not None else a.storage_gb
    a.ram_gb = p.ram_gb if p.ram_gb is not None else a.ram_gb
    a.condition = p.condition or a.condition
    return a


def product_identifiers(p: Product) -> dict[str, str]:
    return {i.kind: i.value for i in p.identifiers if i.kind in ("gtin", "model_number")}


def _get_retailer(db: Session, name: str, url: str) -> Retailer:
    r = db.scalar(select(Retailer).where(Retailer.name == name))
    if r is None:
        r = Retailer(name=name, domain=host_of(url) or None)
        db.add(r)
        db.flush()
    return r


def _find_product(db: Session, attrs: Attributes, ids: dict[str, str], settings: Settings) -> tuple[Product | None, float, dict, str]:
    # 1. deterministic identifiers
    for kind in ("gtin", "model_number"):
        if ids.get(kind):
            ident = db.scalar(select(ProductIdentifier).where(ProductIdentifier.kind == kind, ProductIdentifier.value == ids[kind]))
            if ident:
                res = compare(attrs, product_attributes(ident.product), ids, product_identifiers(ident.product))
                if not res.is_conflict:
                    return ident.product, res.confidence, res.evidence, "verified"
    # 2. attribute + name similarity among same-brand candidates
    q = select(Product).where(Product.condition == attrs.condition)
    if attrs.brand:
        q = q.where(Product.brand == attrs.brand)
    if attrs.storage_gb is not None:
        q = q.where((Product.storage_gb == attrs.storage_gb) | (Product.storage_gb.is_(None)))
    best: tuple[Product | None, float, dict] = (None, 0.0, {})
    for cand in db.scalars(q.limit(200)):
        res = compare(attrs, product_attributes(cand), ids, product_identifiers(cand))
        if not res.is_conflict and res.confidence > best[1]:
            best = (cand, res.confidence, res.evidence)
    cand, conf, ev = best
    if cand is not None and conf >= settings.match_verified_threshold:
        return cand, conf, ev, "verified"
    if cand is not None and conf >= settings.match_unverified_threshold:
        return cand, conf, ev, "unverified"
    return None, conf, ev, "new"


def _preferred(db: Session, product_id: int | None, attrs: Attributes, ids: dict[str, str]) -> tuple[Product | None, float, dict]:
    """A listing from the same provider catalogue entry (e.g. Google Shopping store list) is attached to that
    product unless its attributes contradict it."""
    if product_id is None:
        return None, 0.0, {}
    p = db.get(Product, product_id)
    if p is None:
        return None, 0.0, {}
    res = compare(attrs, product_attributes(p), ids, product_identifiers(p))
    # The provider already grouped this listing with the product, so differing marketing/spec numbers in the
    # title ("Windows 11", bundle codes) are not a reason to split it off. Real variant differences – storage,
    # RAM, colour, condition, tier, accessory, region, brand, identifiers – still block the attachment.
    if set(res.conflicts) - SOFT_CONFLICTS:
        return None, 0.0, {}
    evidence = {**res.evidence, "basis": "same provider catalogue entry"}
    return p, 0.9 if res.conflicts else max(res.confidence, 0.9), evidence


def adopt_offer(db: Session, offer: Offer, product_id: int, attrs: Attributes, ids: dict[str, str]) -> bool:
    """Move an offer that an earlier, stricter match filed under another product back to the product whose
    provider catalogue entry it came from. Its price observations move with it. Returns True if moved."""
    if offer.product_id == product_id:
        return False
    target, conf, evidence = _preferred(db, product_id, attrs, ids)
    if target is None:
        return False
    old = offer.product_id
    offer.product_id = target.id
    offer.match_confidence, offer.match_status = conf, "verified"
    offer.match_evidence = {**evidence, "moved_from_product": old}
    db.execute(PriceObservation.__table__.update().where(PriceObservation.offer_id == offer.id).values(product_id=target.id))
    db.expire(offer, ["product"])
    log.info("offer %s moved from product %s to %s (same provider catalogue entry)", offer.id, old, target.id)
    return True


def _price_outlier(db: Session, product: Product, price: float) -> str | None:
    """Flag a price far from the other verified offers for the same product (e.g. a skin listed as a phone)."""
    prices = sorted(o.price for o in product.offers if o.price and o.match_status == "verified")
    if not prices:
        return None
    mid = prices[len(prices) // 2]
    if price < 0.5 * mid:
        return f"price {price:.0f} is less than half the median verified price {mid:.0f}"
    if price > 2 * mid:
        return f"price {price:.0f} is more than double the median verified price {mid:.0f}"
    return None


def ingest_listing(db: Session, lst: Listing, settings: Settings, now: datetime | None = None,
                   preferred_product_id: int | None = None) -> IngestOutcome:
    now = now or datetime.now(timezone.utc)
    attrs = extract_attributes(lst.title, lst.brand, lst.colour)
    offer = db.scalar(select(Offer).where(Offer.provider_id == lst.provider_id, Offer.listing_key == lst.listing_key))
    created = False
    if offer is None:
        product, conf, evidence = _preferred(db, preferred_product_id, attrs, lst.identifiers)
        status = "verified" if product is not None else ""
        if product is None:
            product, conf, evidence, status = _find_product(db, attrs, lst.identifiers, settings)
        if product is not None and status == "verified":
            why = _price_outlier(db, product, lst.price)
            if why:
                status = "unverified"
                evidence = {**evidence, "price_outlier": why}
                db.add(MatchIssue(provider_id=lst.provider_id, listing_title=lst.title[:500], candidate_product_id=product.id,
                                  confidence=conf, reason=f"price outlier: {why}"[:300]))
        if product is None:
            product = Product(
                title=lst.title,
                brand=attrs.brand,
                family=attrs.family,
                category=classify_category(lst.title, lst.category_hint),
                storage_gb=attrs.storage_gb,
                ram_gb=attrs.ram_gb,
                colour=attrs.colour,
                condition=attrs.condition,
                screen_inches=attrs.screen_inches,
                model_tokens=" ".join(sorted(attrs.model_tokens))[:200] or None,
                tier_tokens=" ".join(sorted(attrs.tier))[:120] or None,
                image_url=lst.image_url,
                specs=lst.specs or None,
            )
            db.add(product)
            db.flush()
            conf, evidence, status, created = 1.0, {"basis": "first_listing_for_product"}, "verified", True
        elif status == "unverified":
            db.add(MatchIssue(provider_id=lst.provider_id, listing_title=lst.title[:500], candidate_product_id=product.id,
                              confidence=conf, reason="confidence below verified threshold; shown but excluded from best price"))
        for kind, value in lst.identifiers.items():
            if kind in ("gtin", "model_number", "asin", "flipkart_pid") and status == "verified":
                exists = db.scalar(select(ProductIdentifier).where(ProductIdentifier.kind == kind, ProductIdentifier.value == value))
                if exists is None:
                    db.add(ProductIdentifier(product_id=product.id, kind=kind, value=value[:120]))
        retailer = _get_retailer(db, lst.retailer, lst.product_url)
        offer = Offer(
            product_id=product.id, provider_id=lst.provider_id, retailer_id=retailer.id, listing_key=lst.listing_key,
            listing_title=lst.title, source_type=lst.source_type, match_confidence=conf, match_status=status,
            match_evidence=evidence, currency=lst.currency,
        )
        db.add(offer)
    else:
        if preferred_product_id is not None and offer.product_id != preferred_product_id:
            adopt_offer(db, offer, preferred_product_id, attrs, lst.identifiers)
        product = db.get(Product, offer.product_id)
    # update the offer with the freshly fetched values
    offer.listing_title = lst.title
    offer.seller_name = lst.seller_name
    offer.price = lst.price
    offer.mrp = lst.mrp
    offer.currency = lst.currency
    offer.shipping_cost = lst.shipping_cost
    offer.availability = lst.availability
    offer.condition = attrs.condition
    offer.product_url = lst.product_url
    offer.link_type = lst.link_type
    if lst.provider_ref:
        offer.provider_ref = lst.provider_ref
    if lst.offer_notes is not None:
        offer.offer_notes = lst.offer_notes
    offer.image_url = lst.image_url
    offer.rating = lst.rating
    offer.rating_count = lst.rating_count
    offer.warranty = lst.warranty
    offer.verification_status = "verified"
    offer.error_reason = None
    offer.fetched_at = lst.fetched_at
    offer.last_verified_at = lst.fetched_at
    offer.last_seen_missing_at = None
    if product.image_url is None and lst.image_url:
        product.image_url = lst.image_url
    db.flush()
    record_observation(db, offer, lst.retailer, settings)
    return IngestOutcome(product.id, offer.id, offer.match_status, created)


def record_observation(db: Session, offer: Offer, retailer_name: str, settings: Settings) -> bool:
    """Store one price snapshot per offer per bucket. Returns True if a new row was written."""
    if offer.price is None or offer.last_verified_at is None:
        return False
    ts = offer.last_verified_at if offer.last_verified_at.tzinfo else offer.last_verified_at.replace(tzinfo=timezone.utc)
    bucket = int(ts.timestamp() // settings.observation_bucket_seconds)
    exists = db.scalar(select(PriceObservation.id).where(PriceObservation.offer_id == offer.id, PriceObservation.bucket == bucket))
    if exists:
        return False
    try:
        with db.begin_nested():
            db.add(PriceObservation(
                product_id=offer.product_id, offer_id=offer.id, retailer_name=retailer_name, provider_id=offer.provider_id,
                price=offer.price, currency=offer.currency, availability=offer.availability,
                verification_status="verified" if offer.match_status == "verified" else "unverified_match",
                observed_at=ts, bucket=bucket,
            ))
        return True
    except IntegrityError:
        return False


def ingest_all(db: Session, listings: list[Listing], settings: Settings,
               preferred_product_id: int | None = None) -> list[IngestOutcome]:
    outcomes = []
    for lst in listings:
        try:
            outcomes.append(ingest_listing(db, lst, settings, preferred_product_id=preferred_product_id))
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception("failed to ingest listing %s/%s", lst.provider_id, lst.listing_key)
            db.rollback()
    return outcomes


def backfill_variant(product: Product, listings: list[Listing]) -> dict[str, int]:
    """Fill in storage/RAM that the product's own (short) title didn't state, from the provider's store list for
    that same product – only when at least two store listings state it and at least 60 % of those agree.
    Returns what was filled in. Nothing is guessed: values come from the stores' own titles."""
    filled: dict = {}
    if product.brand in COMPONENT_BRANDS:
        fixed = detect_brand(product.title)
        if fixed and fixed != product.brand:
            product.brand = filled["brand"] = fixed
    attrs = [extract_attributes(lst.title, lst.brand, lst.colour) for lst in listings]
    for field in ("storage_gb", "ram_gb"):
        if getattr(product, field) is not None:
            continue
        vals = [getattr(a, field) for a in attrs if getattr(a, field) is not None]
        if len(vals) < 2:
            continue
        top = max(set(vals), key=vals.count)
        if vals.count(top) >= 2 and vals.count(top) / len(vals) >= 0.6:
            setattr(product, field, top)
            filled[field] = top
    if filled:
        log.info("product %s: filled %s from its store list", product.id, filled)
    return filled


def repair_store_offers(db: Session, provider_id: str = "serpapi_google_shopping") -> dict[str, int]:
    """Offline, idempotent repair for every product (no provider calls): store-list offers that an older, stricter
    matcher filed under separate products are moved back to the product whose Google Shopping entry they came from,
    together with their price history. Also fixes component-maker brands and fills in storage/RAM agreed by the
    store titles. Ambiguous cases (one catalogue entry claimed by several products) are left untouched."""
    from types import SimpleNamespace

    owners: dict[str, set[int]] = defaultdict(set)
    for o in db.scalars(select(Offer).where(Offer.provider_id == provider_id, Offer.provider_ref.is_not(None))):
        if "|store|" not in o.listing_key:
            owners[o.listing_key.split("|")[0]].add(o.product_id)
    moved = fixed = 0
    for token, pids in owners.items():
        if len(pids) != 1:
            continue
        product = db.get(Product, next(iter(pids)))
        store_offers = db.scalars(select(Offer).where(Offer.provider_id == provider_id,
                                                      Offer.listing_key.like(f"{token}|store|%"))).all()
        if not store_offers:
            continue
        pseudo = [SimpleNamespace(title=o.listing_title, brand=None, colour=None) for o in store_offers]
        if backfill_variant(product, pseudo):  # type: ignore[arg-type]
            fixed += 1
        for o in store_offers:
            if o.product_id != product.id:
                attrs = extract_attributes(o.listing_title)
                if adopt_offer(db, o, product.id, attrs, {}):
                    moved += 1
    db.commit()
    if moved or fixed:
        log.info("store-offer repair: moved %s offers, updated %s products", moved, fixed)
    return {"moved": moved, "products_updated": fixed}

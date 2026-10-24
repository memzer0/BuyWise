"""Database models."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # e.g. "serpapi_google_shopping"
    display_name: Mapped[str] = mapped_column(String(120))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    quota_info: Mapped[dict | None] = mapped_column(JSON)


class Retailer(Base):
    __tablename__ = "retailers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    domain: Mapped[str | None] = mapped_column(String(255))


class Product(Base):
    """Canonical product (one specific variant)."""

    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(120), index=True)
    family: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), default="other", index=True)
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    colour: Mapped[str | None] = mapped_column(String(60))
    condition: Mapped[str] = mapped_column(String(20), default="new")
    screen_inches: Mapped[float | None] = mapped_column(Float)
    model_tokens: Mapped[str | None] = mapped_column(String(200))
    tier_tokens: Mapped[str | None] = mapped_column(String(120))
    image_url: Mapped[str | None] = mapped_column(String(2048))
    specs: Mapped[dict | None] = mapped_column(JSON)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    store_links_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_data: Mapped[dict | None] = mapped_column(JSON)  # reviews / rating breakdown from Google Shopping (raw)

    identifiers: Mapped[list[ProductIdentifier]] = relationship(back_populates="product", cascade="all, delete-orphan")
    offers: Mapped[list[Offer]] = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductIdentifier(Base):
    __tablename__ = "product_identifiers"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_identifier_kind_value"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # gtin, model_number, asin, flipkart_pid
    value: Mapped[str] = mapped_column(String(120))
    product: Mapped[Product] = relationship(back_populates="identifiers")


class Offer(Base):
    """One seller listing (from one provider) attached to a canonical product."""

    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("provider_id", "listing_key", name="uq_offer_provider_listing"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), index=True)
    retailer_id: Mapped[int | None] = mapped_column(ForeignKey("retailers.id"))
    listing_key: Mapped[str] = mapped_column(String(300))
    listing_title: Mapped[str] = mapped_column(String(500))
    seller_name: Mapped[str | None] = mapped_column(String(200))
    price: Mapped[float | None] = mapped_column(Float)
    mrp: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    shipping_cost: Mapped[float | None] = mapped_column(Float)
    availability: Mapped[str] = mapped_column(String(20), default="unknown")  # in_stock/out_of_stock/unknown
    condition: Mapped[str] = mapped_column(String(20), default="new")
    product_url: Mapped[str | None] = mapped_column(String(2048))
    link_type: Mapped[str] = mapped_column(String(20), default="exact_listing")
    image_url: Mapped[str | None] = mapped_column(String(2048))
    rating: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int | None] = mapped_column(Integer)
    warranty: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(30))  # official_api / licensed_api
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_status: Mapped[str] = mapped_column(String(20), default="verified")  # verified / unverified
    match_evidence: Mapped[dict | None] = mapped_column(JSON)
    verification_status: Mapped[str] = mapped_column(String(20), default="verified")  # verified / invalid
    error_reason: Mapped[str | None] = mapped_column(String(200))
    provider_ref: Mapped[str | None] = mapped_column(String(2000))
    offer_notes: Mapped[list | None] = mapped_column(JSON)  # store-reported bank offers / coupons (raw text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_missing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    product: Mapped[Product] = relationship(back_populates="offers")
    retailer: Mapped[Retailer | None] = relationship()
    observations: Mapped[list[PriceObservation]] = relationship(back_populates="offer", cascade="all, delete-orphan")


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint("offer_id", "bucket", name="uq_observation_offer_bucket"),
        Index("ix_observation_product_time", "product_id", "observed_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    retailer_name: Mapped[str] = mapped_column(String(120))
    provider_id: Mapped[str] = mapped_column(String(40))
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    availability: Mapped[str] = mapped_column(String(20))
    verification_status: Mapped[str] = mapped_column(String(20))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bucket: Mapped[int] = mapped_column(Integer)
    offer: Mapped[Offer] = relationship(back_populates="observations")


class SearchRecord(Base):
    __tablename__ = "search_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_query: Mapped[str] = mapped_column(String(200), index=True)
    product_ids: Mapped[list] = mapped_column(JSON, default=list)
    provider_report: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("client_id", "product_id", name="uq_watch_client_product"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    price_when_added: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    product: Mapped[Product] = relationship()


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (UniqueConstraint("client_id", "product_id", name="uq_alert_client_product"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    target_price: Mapped[float] = mapped_column(Float)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")  # in_app / email
    email: Mapped[str | None] = mapped_column(String(254))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    armed: Mapped[bool] = mapped_column(Boolean, default=True)  # false after firing until price rises above target
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    product: Mapped[Product] = relationship()
    events: Mapped[list[AlertEvent]] = relationship(back_populates="alert", cascade="all, delete-orphan")


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("price_alerts.id", ondelete="CASCADE"), index=True)
    triggered_price: Mapped[float] = mapped_column(Float)
    retailer_name: Mapped[str] = mapped_column(String(120))
    offer_url: Mapped[str | None] = mapped_column(String(2048))
    delivery_channel: Mapped[str] = mapped_column(String(20))
    delivery_status: Mapped[str] = mapped_column(String(20))  # recorded / sent / failed / not_configured
    delivery_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    alert: Mapped[PriceAlert] = relationship(back_populates="events")


class FetchJob(Base):
    __tablename__ = "fetch_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # search / refresh
    trigger: Mapped[str] = mapped_column(String(20))  # user / scheduler / manual
    target: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20))  # running / success / partial / failed
    detail: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderError(Base):
    __tablename__ = "provider_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    context: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MatchIssue(Base):
    """Listings that could not be confidently matched – visible in diagnostics."""

    __tablename__ = "match_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(40))
    listing_title: Mapped[str] = mapped_column(String(500))
    candidate_product_id: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- Regret Shield
class TrackedPurchase(Base):
    """A purchase the shopper registered for post-purchase price monitoring. Private to `client_id`."""

    __tablename__ = "tracked_purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    retailer: Mapped[str] = mapped_column(String(120))
    purchase_price: Mapped[float] = mapped_column(Float)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    order_ref: Mapped[str | None] = mapped_column(String(100))
    return_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    protection_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_costs: Mapped[float | None] = mapped_column(Float)  # user-entered return shipping / restocking etc.
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    # optional: where to e-mail this purchase's alerts (only stored if the shopper enters it)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    product: Mapped[Product] = relationship()
    checks: Mapped[list[PurchaseCheck]] = relationship(back_populates="purchase", cascade="all, delete-orphan")
    notifications: Mapped[list[PurchaseNotification]] = relationship(back_populates="purchase", cascade="all, delete-orphan")


class PurchaseCheck(Base):
    """One monitoring check of a tracked purchase against the comparable verified offers at that time."""

    __tablename__ = "purchase_checks"
    __table_args__ = (UniqueConstraint("purchase_id", "bucket", name="uq_purchase_check_bucket"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("tracked_purchases.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bucket: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    comparable_price: Mapped[float | None] = mapped_column(Float)
    retailer: Mapped[str | None] = mapped_column(String(120))
    offer_id: Mapped[int | None] = mapped_column(Integer)
    offer_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    difference: Mapped[float | None] = mapped_column(Float)
    purchase: Mapped[TrackedPurchase] = relationship(back_populates="checks")


class PurchaseNotification(Base):
    __tablename__ = "purchase_notifications"
    __table_args__ = (UniqueConstraint("purchase_id", "event_key", name="uq_purchase_notification_event"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("tracked_purchases.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # price_drop / deadline / monitoring
    event_key: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # sent / failed / not_configured
    purchase: Mapped[TrackedPurchase] = relationship(back_populates="notifications")

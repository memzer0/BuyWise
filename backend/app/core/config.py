"""Application settings, loaded from environment variables / backend/.env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.pricing.trust import DEFAULT_PREFERRED_STORES, DEFAULT_TRUSTED_DOMAINS, DEFAULT_TRUSTED_STORES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "BuyWise"
    environment: str = "development"
    database_url: str = "sqlite:///./buywise.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"
    auto_migrate: bool = True  # run `alembic upgrade head` on startup

    # --- Provider credentials (all optional; app starts without them) ---
    serpapi_api_key: str | None = None
    serpapi_location: str = "India"
    # When a product is opened, fetch Google Shopping's store list for it (1 extra SerpApi search)
    # to get each store's own product link instead of a Google Shopping page.
    serpapi_store_links: bool = True

    amazon_creators_credential_id: str | None = None
    amazon_creators_credential_secret: str | None = None
    amazon_partner_tag: str | None = None
    # India is served by the EU credential region (v3.2) per Amazon's Creators API docs.
    amazon_creators_token_url: str = "https://api.amazon.co.uk/auth/o2/token"
    amazon_creators_api_base: str = "https://creatorsapi.amazon/catalog/v1"
    amazon_marketplace: str = "www.amazon.in"

    flipkart_affiliate_id: str | None = None
    flipkart_affiliate_token: str | None = None
    flipkart_api_base: str = "https://affiliate-api.flipkart.net/affiliate/1.0"

    # --- Fetching behaviour ---
    provider_timeout_seconds: float = 15.0
    max_response_bytes: int = 5_000_000
    provider_max_concurrency: int = 2
    provider_min_interval_seconds: float = 1.5   # minimum spacing between calls to one provider
    backoff_base_seconds: float = 30.0
    backoff_max_seconds: float = 3600.0

    # --- Freshness policy (seconds) ---
    fresh_window_seconds: int = 30 * 60          # opened products older than this are re-fetched
    stale_after_seconds: int = 24 * 3600         # offers older than this are labelled stale
    search_cache_seconds: int = 30 * 60
    observation_bucket_seconds: int = 10 * 60    # at most one observation per offer per bucket

    # --- Automatic refresh scheduler ---
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60
    refresh_popular_minutes: int = 60
    refresh_normal_minutes: int = 360
    popular_view_threshold: int = 5
    scheduler_batch_size: int = 5

    # --- Pre-tracking: re-run these searches on a timer so popular products build real price history before
    # anyone opens them. Each search is 1 SerpApi call and records prices for ~20 products.
    # Monthly cost ≈ number of queries × (30 × 24 / PRETRACK_INTERVAL_HOURS) searches.
    pretrack_enabled: bool = True
    pretrack_interval_hours: int = 24
    pretrack_per_tick: int = 1
    pretrack_queries: str = (
        "iPhone 17, iPhone 16, Samsung Galaxy S25, Samsung Galaxy A56, OnePlus 13, OnePlus Nord 5, Google Pixel 10, "
        "Nothing Phone 3, iQOO Neo 10, Redmi Note 15, Realme GT 7, Vivo V60, MacBook Air M4, Lenovo IdeaPad Slim 5, "
        "ASUS Vivobook 15, HP Pavilion 15, AirPods Pro 3, boAt Airdopes, Sony WH-1000XM6, OnePlus Buds 4, "
        "Samsung Galaxy Watch 8, Apple Watch Series 11, iPad Air, Samsung 55 inch 4K TV"
    )

    @property
    def pretrack_query_list(self) -> list[str]:
        return [q.strip() for q in self.pretrack_queries.split(",") if q.strip()]

    # --- Matching ---
    match_verified_threshold: float = 0.80
    match_unverified_threshold: float = 0.60

    # --- Score weights (renormalised over available components) ---
    score_weight_price_vs_history: float = 0.35
    score_weight_market_position: float = 0.25
    score_weight_trend: float = 0.15
    score_weight_rating: float = 0.15
    score_weight_availability: float = 0.10

    # --- Public API rate limiting ---
    rate_limit_per_minute: int = 120

    # --- Regret Shield (post-purchase monitoring) ---
    regret_min_drop_pct: float = 2.0      # a drop must be at least this % of the purchase price …
    regret_min_drop_amount: float = 200.0 # … and at least this many rupees to count as meaningful
    regret_deadline_warn_days: int = 3    # notify when a user-entered deadline is this close
    regret_check_bucket_minutes: int = 60 # at most one stored check per purchase per bucket

    # --- AI shopping assistant (chat bubble). Keys stay on the server; the first configured provider is used. ---
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    assistant_timeout_seconds: float = 30.0

    # --- Admin ---
    admin_token: str | None = None

    # --- Alerts: optional SMTP e-mail delivery ---
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True

    allow_http_offer_urls: bool = False
    # Sellers whose listings reuse device names for accessories (skins/cases). Comma separated, case-insensitive.
    excluded_sellers: str = "KerfCase,dbrand"
    # Only offers from these stores are shown by default and used for the lowest price (see app/pricing/trust.py).
    trusted_only: bool = True
    trusted_stores: str = DEFAULT_TRUSTED_STORES
    trusted_domains: str = DEFAULT_TRUSTED_DOMAINS
    # Shown first in seller lists and boosted in search, in this order.
    preferred_stores: str = DEFAULT_PREFERRED_STORES

    @property
    def excluded_seller_set(self) -> frozenset[str]:
        return frozenset(s.strip().lower() for s in self.excluded_sellers.split(",") if s.strip())

    affiliate_disclosure: str = Field(
        default="Some links may be affiliate links. BuyWise may earn a commission at no extra cost to you."
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

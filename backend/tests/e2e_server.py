"""Backend for the Playwright end-to-end suite ONLY.

Starts the real BuyWise app (real DB, matching, pricing, API) but with the test-only FakeProvider,
so browser tests are deterministic and do not depend on external API keys. This module lives in
tests/ and is never imported by the production app.

    python -m tests.e2e_server      (from backend/, port 8001, database e2e.db)
"""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite:///./e2e.db"
os.environ["SCHEDULER_ENABLED"] = "false"

import uvicorn  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers.registry import ProviderRegistry  # noqa: E402
from tests.fakes import FakeProvider, row  # noqa: E402

if os.path.exists("e2e.db"):
    os.remove("e2e.db")

settings = Settings(_env_file=None, database_url="sqlite:///./e2e.db", scheduler_enabled=False, provider_min_interval_seconds=0,
                    cors_origins="http://127.0.0.1:5174,http://localhost:5174",
                    trusted_stores="Test Retailer A, Test Retailer B")
catalog_a = {"pixel 9": [row("ga1", "Google Pixel 9 (Obsidian, 12GB RAM, 256GB)", 79999, "Test Retailer A", availability="in_stock")]}
catalog_b = {"pixel 9": [row("gb1", "Google Pixel 9 5G 12GB RAM 256GB Obsidian", 78499, "Test Retailer B", availability="in_stock")]}
app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, catalog_a, provider_id="e2e_a"),
                                                        FakeProvider(settings, catalog_b, provider_id="e2e_b")]))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)

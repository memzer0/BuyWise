from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bootstrap.db")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AUTO_MIGRATE"] = "false"
for k in ("SERPAPI_API_KEY", "FLIPKART_AFFILIATE_ID", "FLIPKART_AFFILIATE_TOKEN", "AMAZON_CREATORS_CREDENTIAL_ID"):
    os.environ.pop(k, None)

import pytest  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.database import session as dbs  # noqa: E402
from app.database.session import Base  # noqa: E402


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None, scheduler_enabled=False, pretrack_enabled=False, auto_migrate=False, provider_min_interval_seconds=0,
                    rate_limit_per_minute=0, admin_token="test-admin-token",
                    # test fixture stores count as trusted; the trust filter itself is tested in test_trust.py
                    trusted_stores="Shop A, Shop B, Reliance Digital, Croma, Amazon India, Flipkart")


@pytest.fixture()
def db_url(tmp_path) -> str:  # noqa: ANN001
    url = f"sqlite:///{tmp_path / 'test.db'}"
    dbs.configure_engine(url)
    Base.metadata.create_all(dbs.engine)
    yield url
    dbs.engine.dispose()


@pytest.fixture()
def db(db_url):  # noqa: ANN001
    s = dbs.SessionLocal()
    yield s
    s.close()

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Offer, PriceObservation
from app.pricing.offers import OfferView, freshness_status, select_lowest
from app.providers.validation import RejectedListing, build_listing
from app.scoring.buywise import compute_score
from app.scoring.prediction import predict
from app.services.ingest import ingest_listing, record_observation
from tests.fakes import row

import pytest


def ov(i, price, **kw):  # noqa: ANN001, ANN003, ANN201
    base = dict(id=i, price=price, currency="INR", availability="in_stock", freshness="cached", match_status="verified",
                verification_status="verified", condition="new", link_type="exact_listing", shipping_cost=None)
    base.update(kw)
    return OfferView(**base)


def test_lowest_verified_price_selection():
    assert select_lowest([ov(1, 100), ov(2, 90), ov(3, 95)]).id == 2


def test_stale_and_unverified_excluded():
    offers = [ov(1, 100), ov(2, 50, freshness="stale"), ov(3, 60, match_status="unverified"), ov(4, 70, verification_status="invalid")]
    assert select_lowest(offers).id == 1


def test_out_of_stock_excluded_and_refurb_optional():
    offers = [ov(1, 100), ov(2, 80, availability="out_of_stock"), ov(3, 70, condition="refurbished")]
    assert select_lowest(offers).id == 1
    assert select_lowest(offers, include_refurbished=True).id == 3


def test_freshness_labels(settings):  # noqa: ANN001
    now = datetime.now(timezone.utc)
    assert freshness_status(now, settings, fetched_this_request=True) == "live"
    assert freshness_status(now - timedelta(hours=1), settings) == "cached"
    assert freshness_status(now - timedelta(days=3), settings) == "stale"
    assert freshness_status(None, settings) == "unavailable"


def test_currency_validation():
    with pytest.raises(RejectedListing):
        build_listing(provider_id="p", source_type="official_api", listing_key="k", title="t", retailer="r", price=10,
                      currency="USD", product_url="https://shop.example/p/1")
    with pytest.raises(RejectedListing):
        build_listing(provider_id="p", source_type="official_api", listing_key="k", title="t", retailer="r", price=None,
                      currency="INR", product_url="https://shop.example/p/1")


def _listing(settings, key, title, price, retailer="Shop A"):  # noqa: ANN001, ANN201
    return build_listing(provider_id="fake_provider", source_type="official_api", **row(key, title, price, retailer))


def test_snapshot_creation_and_duplicate_prevention(settings, db):  # noqa: ANN001
    from app.models import Provider
    db.add(Provider(id="fake_provider", display_name="f"))
    db.commit()
    oc = ingest_listing(db, _listing(settings, "a1", "Apple iPhone 16 (Black, 128 GB)", 69999), settings)
    db.commit()
    assert db.scalar(select(func.count(PriceObservation.id))) == 1
    # same offer, same bucket -> no duplicate
    ingest_listing(db, _listing(settings, "a1", "Apple iPhone 16 (Black, 128 GB)", 69999), settings)
    db.commit()
    offer = db.get(Offer, oc.offer_id)
    assert record_observation(db, offer, "Shop A", settings) is False
    assert db.scalar(select(func.count(PriceObservation.id))) == 1
    # a later bucket creates a new snapshot
    offer.last_verified_at = datetime.now(timezone.utc) + timedelta(seconds=settings.observation_bucket_seconds + 5)
    assert record_observation(db, offer, "Shop A", settings) is True


def test_cross_retailer_grouping_and_variant_separation(settings, db):  # noqa: ANN001
    from app.models import Provider
    db.add(Provider(id="fake_provider", display_name="f"))
    db.commit()
    a = ingest_listing(db, _listing(settings, "a1", "Apple iPhone 16 (Black, 128 GB)", 69999, "Shop A"), settings)
    b = ingest_listing(db, _listing(settings, "b1", "Apple iPhone 16 128GB Black", 70500, "Shop B"), settings)
    c = ingest_listing(db, _listing(settings, "c1", "Apple iPhone 16 (Black, 256 GB)", 79999, "Shop A"), settings)
    d = ingest_listing(db, _listing(settings, "d1", "Apple iPhone 16 Pro (Black Titanium, 128 GB)", 109999, "Shop A"), settings)
    assert a.product_id == b.product_id and b.match_status == "verified"
    assert len({a.product_id, c.product_id, d.product_id}) == 3


def test_prediction_requires_history():
    assert predict({}).available is False
    base = datetime(2026, 1, 1).date()
    series = {base + timedelta(days=i): 1000 - i * 5 for i in range(20)}
    p = predict(series)
    assert p.available and p.slope_per_day < 0 and p.holdout_mae is not None


def test_score_missing_data_not_perfect(settings):  # noqa: ANN001
    s = compute_score(settings, best_price=1000, best_in_stock=True, best_exact_link=True, other_verified_prices=[],
                      history_prices=[1000], history_days=0, prediction=predict({}), ratings=[])
    assert s.confidence < 0.5 and s.verdict == "insufficient_data"
    none = compute_score(settings, best_price=None, best_in_stock=False, best_exact_link=False, other_verified_prices=[],
                         history_prices=[], history_days=0, prediction=predict({}), ratings=[])
    assert none.score is None


def test_price_outlier_marked_unverified(settings, db):  # noqa: ANN001
    from app.models import Provider
    db.add(Provider(id="fake_provider", display_name="f"))
    db.commit()
    a = ingest_listing(db, _listing(settings, "r1", "Apple iPhone 16 Plus", 79900, "Reliance Digital"), settings)
    db.commit()
    b = ingest_listing(db, _listing(settings, "k1", "Apple iPhone 16 Plus", 24147, "Some Shop"), settings)
    db.commit()
    assert b.product_id == a.product_id and b.match_status == "unverified"
    assert "price_outlier" in db.get(Offer, b.offer_id).match_evidence

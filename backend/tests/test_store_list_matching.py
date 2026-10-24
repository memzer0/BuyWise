"""Store lists (one provider catalogue entry) must land on the product they belong to, and stale data is labelled."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.matching.attributes import extract_attributes
from app.matching.matcher import compare
from app.models import Offer, PriceObservation, Product, Provider
from app.providers.registry import ProviderRegistry
from app.providers.validation import build_listing
from app.services.catalog import CatalogService
from app.services.ingest import backfill_variant, ingest_all

TOKEN = "1224008798"
LAPTOP = "ASUS TUF F16 Intel Core 5 210H Gaming Laptop"
STORE_TITLES = {
    "Flipkart": "Asus TUF F16 Gaming Laptop (Intel Core 5/ 16GB RAM/ 512GB SSD/ 16 Inch (40.64 cm) FHD+ Display/ 6GB-NVIDIA GeForce RTX 3050 Graphics/ Windows 11/ MS-",
    "Vijay Sales": "ASUS TUF Gaming F16 Intel Core 5 16 GB DDR4 & 512 GB SSD Mecha Gray NVIDIA GeForce RTX 3050A 144Hz Refresh Rate Windows 11",
    "Croma": "Asus FX607VB-RL087WS Intel Core 5 Processor 210H 16GB RAM 512GB SSD",
}


def lst(retailer: str, title: str, price: float, key: str | None = None, ref: str | None = None):  # noqa: ANN201
    li = build_listing(provider_id="serpapi_google_shopping", source_type="licensed_aggregator_api",
                       listing_key=key or f"{TOKEN}|store|{retailer.lower()}", title=title, retailer=retailer, price=price,
                       currency="INR", product_url=f"https://{retailer.lower().replace(' ', '')}.example/p/1")
    li.provider_ref = ref
    return li


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def provider_row(request):  # noqa: ANN001, ANN201
    if "db" in request.fixturenames:
        db = request.getfixturevalue("db")
        db.add(Provider(id="serpapi_google_shopping", display_name="Google Shopping", consecutive_failures=0, total_requests=0))
        db.commit()


def test_brand_is_the_device_maker_not_the_gpu_or_cpu():
    assert extract_attributes(STORE_TITLES["Flipkart"]).brand == "asus"
    assert extract_attributes(LAPTOP).brand == "asus"
    assert extract_attributes("NVIDIA GeForce RTX 4060 8GB Graphics Card").brand == "nvidia"
    assert extract_attributes("Apple iPhone 16 (Black, 128 GB)").brand == "apple"


def test_spec_numbers_are_not_model_tokens():
    toks = extract_attributes(STORE_TITLES["Flipkart"]).model_tokens
    assert not toks & {"11", "40", "3050", "64"}
    assert "f16" in toks


def test_redmi_and_xiaomi_are_the_same_brand_but_variants_still_differ():
    a = extract_attributes("Xiaomi Redmi 13 5G 128 GB (Orchid Pink, 8GB RAM)")
    b = extract_attributes("Redmi 13 5G (Orchid Pink, 8GB RAM, 128 GB)")
    assert not compare(a, b).is_conflict
    c = extract_attributes("Redmi 13 5G (Orchid Pink, 6GB RAM, 128 GB)")
    assert "ram_gb" in compare(a, c).conflicts


def test_store_list_attaches_to_its_product_and_repairs_misfiled_offers(db, settings):  # noqa: ANN001
    # 1. the product as first seen in search results: short title, brand stored wrongly by the old detector
    ingest_all(db, [lst("Flipkart", LAPTOP, 104999, key=f"{TOKEN}|Flipkart", ref="tok")], settings)
    p = db.scalars(select(Product)).one()
    p.brand = "intel"
    db.commit()
    # 2. old behaviour: store listings got filed as separate products – simulate that, with a price history
    for r, t in STORE_TITLES.items():
        ingest_all(db, [lst(r, t, 110990 if r == "Vijay Sales" else 105000)], settings)
    misfiled = db.scalars(select(Offer).where(Offer.listing_key.like(f"{TOKEN}|store|%"))).all()
    for o in misfiled:
        if o.product_id == p.id:  # force the old (wrong) state for the test
            other = Product(title=o.listing_title, category="laptops", condition="new", brand="asus")
            db.add(other)
            db.flush()
            o.product_id = other.id
            db.execute(PriceObservation.__table__.update().where(PriceObservation.offer_id == o.id).values(product_id=other.id))
    db.commit()
    assert all(o.product_id != p.id for o in misfiled)

    # 3. refresh through the store list (same catalogue entry) → offers come home with their history
    listings = [lst(r, t, 105000) for r, t in STORE_TITLES.items()]
    listings.append(lst("Reliance Digital", "ASUS TUF F16 Intel Core 5 8GB RAM 512GB SSD", 79990))  # different RAM variant
    filled = backfill_variant(p, listings)
    assert filled == {"brand": "asus", "storage_gb": 512, "ram_gb": 16}
    ingest_all(db, listings, settings, preferred_product_id=p.id)
    db.expire_all()
    mine = {o.retailer.name for o in db.scalars(select(Offer).where(Offer.product_id == p.id))}
    assert mine == {"Flipkart", "Vijay Sales", "Croma"}  # the 8 GB listing is a different variant → not attached
    obs = db.scalars(select(PriceObservation).where(PriceObservation.product_id == p.id)).all()
    assert len(obs) >= 4  # history moved along with the offers
    moved = db.scalars(select(Offer).where(Offer.listing_key == f"{TOKEN}|store|croma")).one()
    assert moved.match_status == "verified" and "moved_from_product" in moved.match_evidence


def test_backfill_needs_agreement(db, settings):  # noqa: ANN001
    p = Product(title="Redmi Note 17 5G", category="smartphones", condition="new", brand="xiaomi")
    one = [lst("A", "Redmi Note 17 5G 8GB 128GB", 1)]
    assert backfill_variant(p, one) == {}  # a single listing isn't enough
    split = [lst("A", "Redmi Note 17 5G 8GB RAM 128GB", 1), lst("B", "Redmi Note 17 5G 8GB RAM 256GB", 1)]
    assert backfill_variant(p, split) == {"ram_gb": 8}  # storage 128/256 disagree → left unknown
    assert p.storage_gb is None


def test_fresh_price_replaces_stale_one_from_same_store_and_last_known_shown(db, settings):  # noqa: ANN001
    cat = CatalogService(settings, ProviderRegistry(settings, []))
    ingest_all(db, [lst("Flipkart", "Apple iPhone 16 (Black, 128 GB)", 69999, key="k|Flipkart"),
                    lst("Flipkart", "Apple iPhone 16 Black 128GB", 68999, key="k|store|flipkart")], settings)
    p = db.scalars(select(Product)).one()
    old, new = sorted(p.offers, key=lambda o: o.id)
    old.last_verified_at = datetime.now(timezone.utc) - timedelta(days=6)
    db.commit()
    assert cat.visible_offers(p) == [new]
    d = cat.product_detail(db, p)
    assert d["summary"]["lowest_verified_price"] == 68999 and d["summary"]["last_known"] is None

    new.last_verified_at = datetime.now(timezone.utc) - timedelta(days=6)
    db.commit()
    d = cat.product_detail(db, p)
    assert d["summary"]["lowest_verified_price"] is None  # stale prices are never "current"
    lk = d["summary"]["last_known"]
    assert lk["price"] == 68999 and lk["retailer"] == "Flipkart" and lk["days_ago"] == 6
    assert d["deal"]["score"] is None and "Last seen ₹68,999 at Flipkart, 6 days ago" in d["deal"]["insight"]["title"]
    assert d["decision"]["verdict"] == "NOT_ENOUGH_DATA"
    assert any("Last price BuyWise saw: ₹68,999" in r for r in d["decision"]["reasons"])


# ---------------------------------------------------------------- deal rules with early history
from datetime import date  # noqa: E402

from app.scoring.deal import evaluate as evaluate_deal  # noqa: E402
from app.scoring.decision import decide  # noqa: E402


def test_unchanged_price_gets_a_score_after_two_days():
    today = date(2026, 10, 15)
    d = evaluate_deal(105000, {date(2026, 10, 9): 104999, today: 104999}, [110990], today)
    st = {c.key: (c.status, c.points) for c in d.checks}
    assert st["below_last_price"] == ("same", 13)        # same as last price → half points
    assert st["at_all_time_low"] == ("pass", 20)         # ₹1 above the lowest counts as the lowest (0.5 % tolerance)
    assert st["no_price_pump"][0] == "pass" and st["six_month_low"][0] == "na"
    assert d.score is not None and d.label == "Good catch"


def test_one_day_of_checks_is_still_not_scored():
    today = date(2026, 10, 15)
    d = evaluate_deal(105000, {today: 105000}, [110990], today)
    assert d.score is None


def test_decision_waits_when_price_is_above_what_was_seen():
    today = date(2026, 10, 15)
    deal = evaluate_deal(15499, {date(2026, 10, 9): 11994, today: 15499}, [], today).to_dict()
    dec = decide(best_price=15499, best_retailer="Mi.com", best_availability="in_stock", best_link_exact=True,
                 store_count=1, deal=deal, lowest=11994, average=13746, span_days=6, newer_models=[])
    assert dec.verdict == "WAIT"


def test_history_line_is_lowest_price_per_check(db, settings):  # noqa: ANN001
    cat = CatalogService(settings, ProviderRegistry(settings, []))
    ingest_all(db, [lst("Flipkart", "Apple iPhone 16 (Black, 128 GB)", 69999, key="k|Flipkart"),
                    lst("Croma", "Apple iPhone 16 Black 128GB", 72999, key="k|Croma")], settings)
    p = db.scalars(select(Product)).one()
    h = cat.history(db, p, "30d")
    assert [pt["price"] for pt in h["lowest_series"]] == [69999]  # one check → one point, the lowest store
    assert h["latest"]["retailer"] == "Flipkart" and h["highest"] == 69999


def test_offline_repair_moves_misfiled_store_offers(db, settings):  # noqa: ANN001
    from app.services.ingest import repair_store_offers
    ingest_all(db, [lst("Flipkart", LAPTOP, 104999, key=f"{TOKEN}|Flipkart", ref="tok")], settings)
    p = db.scalars(select(Product)).one()
    other = Product(title="dup", category="laptops", condition="new", brand="asus")
    db.add(other)
    db.flush()
    ingest_all(db, [lst("Vijay Sales", STORE_TITLES["Vijay Sales"], 110990), lst("Croma", STORE_TITLES["Croma"], 105000)], settings)
    for o in db.scalars(select(Offer).where(Offer.listing_key.like(f"{TOKEN}|store|%"))):
        o.product_id = other.id
    db.commit()
    assert repair_store_offers(db) == {"moved": 2, "products_updated": 1}
    assert repair_store_offers(db) == {"moved": 0, "products_updated": 0}  # idempotent
    assert {o.retailer.name for o in db.get(Product, p.id).offers} == {"Flipkart", "Vijay Sales", "Croma"}

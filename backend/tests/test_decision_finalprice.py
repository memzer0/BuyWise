from fastapi.testclient import TestClient

from app.main import create_app
from app.pricing.final_price import compute, notes_from_store, parse_note
from app.providers.registry import ProviderRegistry
from app.scoring.decision import decide
from tests.fakes import FakeProvider, row


# ---------------------------------------------------------------- offer parsing
def test_parse_bank_percent_with_cap_and_min():
    t = parse_note("10% Instant Discount up to ₹1,500 on HDFC Bank Credit Card. Min purchase ₹5,000")
    assert t.kind == "bank" and t.banks == ["HDFC"] and t.percent == 10 and t.cap == 1500 and t.min_purchase == 5000
    assert t.flat_off is None
    assert t.saving(69999)[0] == 1500 and t.saving(4000)[0] == 0


def test_parse_flat_bank_coupon_exchange():
    assert parse_note("Flat ₹4,000 off with ICICI Bank cards").flat_off == 4000
    c = parse_note("Use code SAVE500 to get ₹500 off")
    assert c.kind == "coupon" and c.code == "SAVE500" and c.flat_off == 500
    assert parse_note("Up to ₹25,000 off on exchange").kind == "exchange"


def test_notes_from_store_keeps_only_offers():
    store = {"details_and_offers": ["In stock online", "₹3,000 off with SBI credit cards", {"text": "No cost EMI available"}],
             "coupon": "Code BIG10 for 10% off up to ₹1,000"}
    notes = notes_from_store(store)
    assert "In stock online" not in notes and len(notes) == 3


# ---------------------------------------------------------------- final price
def _offer(i, retailer, price, notes, ship=None):  # noqa: ANN001, ANN202
    return {"offer_id": i, "retailer": retailer, "price": price, "shipping_cost": ship, "eligible_for_best_price": True,
            "offer_notes": notes}


def test_final_price_only_applies_selected_banks():
    offers = [_offer(1, "Croma", 70000, ["₹3,000 off with SBI credit cards"], 0.0),
              _offer(2, "Flipkart", 69500, ["10% off up to ₹1,500 on HDFC cards", "Up to ₹20,000 off on exchange"])]
    none = compute(offers, set(), False)
    assert [s["retailer"] for s in none["stores"]] == ["Flipkart", "Croma"]
    assert all(s["applied"] == [] for s in none["stores"]) and none["banks_mentioned"] == ["HDFC", "SBI"]
    flip = next(s for s in none["stores"] if s["retailer"] == "Flipkart")
    assert flip["guaranteed_total"] is None and "Delivery charge not reported" in flip["unknowns"][0]
    sbi = compute(offers, {"SBI"}, False)
    croma = next(s for s in sbi["stores"] if s["retailer"] == "Croma")
    assert croma["guaranteed_total"] == 70000 and croma["possible_total"] == 67000
    assert sbi["stores"][0]["retailer"] == "Croma"  # now cheaper for an SBI card holder
    ex = next(n for n in next(s for s in sbi["stores"] if s["retailer"] == "Flipkart")["not_applied"] if n["kind"] == "exchange")
    assert ex["saving"] == 0


def test_final_price_ignores_ineligible_offers():
    o = _offer(1, "X", 100, [])
    o["eligible_for_best_price"] = False
    assert compute([o], set(), False)["stores"] == []


# ---------------------------------------------------------------- decision engine
def _deal(**status):  # noqa: ANN003, ANN202
    keys = ["below_last_price", "no_price_pump", "at_all_time_low", "six_month_low", "below_average", "cheaper_than_stores"]
    pts = {"below_last_price": 27, "no_price_pump": 19, "at_all_time_low": 20, "six_month_low": 12, "below_average": 12, "cheaper_than_stores": 10}
    checks = [{"key": k, "max_points": pts[k], "status": status.get(k, "na"), "detail": f"{k} detail"} for k in keys]
    judged = sum(c["max_points"] for c in checks if c["status"] != "na")
    return {"checks": checks, "completeness": judged / 100}


BASE = dict(best_price=70000, best_retailer="Croma", best_availability="in_stock", best_link_exact=True, store_count=3,
            lowest=70000, average=72000, span_days=10, newer_models=[])


def test_decision_no_price():
    d = decide(**{**BASE, "best_price": None}, deal=_deal())
    assert d.verdict == "NOT_ENOUGH_DATA"


def test_decision_pump_waits_and_low_buys():
    assert decide(**BASE, deal=_deal(no_price_pump="fail", at_all_time_low="pass")).verdict == "WAIT"
    d = decide(**BASE, deal=_deal(no_price_pump="pass", at_all_time_low="pass"))
    assert d.verdict == "BUY_NOW" and "lowest price" in d.headline


def test_decision_above_low_waits():
    d = decide(**{**BASE, "best_price": 75000}, deal=_deal(no_price_pump="pass", at_all_time_low="fail"))
    assert d.verdict == "WAIT" and "7% above" in d.headline


def test_decision_newer_model_alternative():
    newer = [{"id": 2, "title": "Apple iPhone 17 (Black, 128 GB)", "best_price": 74900, "retailer": "Croma"}]
    d = decide(**{**BASE, "newer_models": newer}, deal=_deal())
    assert d.verdict == "CONSIDER_ALTERNATIVES" and d.alternatives[0]["id"] == 2


def test_decision_insufficient_history():
    d = decide(**{**BASE, "span_days": 0}, deal=_deal(cheaper_than_stores="fail"))
    assert d.verdict == "NOT_ENOUGH_DATA" and d.evidence_level == "low"
    assert any("Future prices" in x for x in d.limitations)


# ---------------------------------------------------------------- API integration
def test_product_api_has_decision_and_final_price(settings, db_url):  # noqa: ANN001
    cat = {"iphone": [
        row("a", "Apple iPhone 16 (Black, 128 GB)", 69900, "Shop A", offer_notes=["₹4,000 off with HDFC Bank cards"]),
        row("b", "Apple iPhone 16 (Black, 128 GB)", 70900, "Shop B", shipping_cost=0.0),
        row("c", "Apple iPhone 17 (Black, 128 GB)", 74900, "Shop A"),
        row("d", "Apple iPhone 17 Pro (Black, 128 GB)", 119900, "Shop A"),
    ]}
    app = create_app(settings, ProviderRegistry(settings, [FakeProvider(settings, cat, provider_id="p")]))
    with TestClient(app) as c:
        res = c.get("/api/search", params={"q": "iphone"}).json()["results"]
        pid16 = next(r["id"] for r in res if r["title"].startswith("Apple iPhone 16"))
        d = c.get(f"/api/products/{pid16}").json()
        assert d["decision"]["verdict"] == "CONSIDER_ALTERNATIVES"
        assert [a["title"] for a in d["decision"]["alternatives"]] == ["Apple iPhone 17 (Black, 128 GB)"]  # not the Pro
        assert "passport" not in d
        assert d["final_price"]["banks_mentioned"] == ["HDFC"]
        fp = c.get(f"/api/products/{pid16}/final-price", params={"banks": ["HDFC"]}).json()
        shop_a = next(s for s in fp["stores"] if s["retailer"] == "Shop A")
        assert shop_a["possible_total"] == 65900 and shop_a["applied"][0]["banks"] == ["HDFC"]
        pid17 = next(r["id"] for r in res if r["title"] == "Apple iPhone 17 (Black, 128 GB)")
        assert c.get(f"/api/products/{pid17}").json()["decision"]["verdict"] != "CONSIDER_ALTERNATIVES"

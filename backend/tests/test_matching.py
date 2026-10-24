from app.matching.attributes import classify_category, extract_attributes
from app.matching.matcher import compare

VERIFIED = 0.80


def match(a: str, b: str, ba=None, bb=None):  # noqa: ANN001, ANN201
    return compare(extract_attributes(a, ba), extract_attributes(b, bb))


def test_attribute_extraction_phone():
    a = extract_attributes("Apple iPhone 16 (Black, 128 GB)")
    assert a.brand == "apple" and a.storage_gb == 128 and a.colour == "black" and a.condition == "new"
    assert "16" in a.model_tokens and "128" not in a.model_tokens


def test_attribute_extraction_ram_storage():
    a = extract_attributes("Samsung Galaxy S24 Ultra 5G (Titanium Gray, 12GB RAM, 256GB Storage)")
    assert a.ram_gb == 12 and a.storage_gb == 256 and "ultra" in a.tier and a.colour == "titanium"
    b = extract_attributes("OnePlus 13 (Black Eclipse, 16GB/512GB)")
    assert b.ram_gb == 16 and b.storage_gb == 512


def test_identical_model_across_retailers_matches():
    r = match("Apple iPhone 16 (Black, 128 GB)", "iPhone 16 128 GB: 5G Mobile Phone with Camera Control, A18 Chip; Black", None, "Apple")
    assert not r.is_conflict and r.confidence >= VERIFIED, r


def test_storage_variants_separate():
    r = match("Apple iPhone 16 (Black, 128 GB)", "Apple iPhone 16 (Black, 256 GB)")
    assert r.is_conflict and "storage_gb" in r.conflicts


def test_ram_variants_separate():
    r = match("Dell Inspiron 15 Laptop 8GB RAM 512GB SSD", "Dell Inspiron 15 Laptop 16GB RAM 512GB SSD")
    assert r.is_conflict and "ram_gb" in r.conflicts


def test_standard_vs_pro_separate():
    r = match("Apple iPhone 16 (Black, 128 GB)", "Apple iPhone 16 Pro (Black Titanium, 128 GB)")
    assert r.is_conflict and "tier" in r.conflicts


def test_new_vs_refurbished_separate():
    r = match("Apple iPhone 15 (Blue, 128 GB)", "(Refurbished) Apple iPhone 15 (Blue, 128 GB)")
    assert r.is_conflict and "condition" in r.conflicts


def test_generations_separate():
    r = match("Apple iPhone 15 (Black, 128 GB)", "Apple iPhone 16 (Black, 128 GB)")
    assert r.is_conflict and "model_tokens" in r.conflicts


def test_low_confidence_not_verified():
    # same brand/storage but almost nothing else in common
    r = match("Samsung 128GB EVO Plus microSD card", "Samsung Galaxy Tab 128GB")
    assert r.confidence < VERIFIED


def test_identifier_match_and_mismatch():
    a, b = extract_attributes("Phone X 128GB"), extract_attributes("Different words 128GB")
    assert compare(a, b, {"gtin": "0194253"}, {"gtin": "0194253"}).confidence == 1.0
    assert compare(a, b, {"gtin": "0194253"}, {"gtin": "999"}).is_conflict


def test_category_classifier():
    assert classify_category("Apple iPhone 16 (Black, 128 GB)") == "smartphones"
    assert classify_category("HP Victus Gaming Laptop") == "laptops"
    assert classify_category("Sony WH-1000XM5 Wireless Headphones") == "headphones"


# --- regressions from the first live Google Shopping India run (iphone 16 128gb) ---
def test_short_title_does_not_absorb_unrelated_long_title():
    r = match("iPhone 16", "USA AT&T iPhone 16 Series Only Recently Upgraded Bundle Offer Pack")
    assert r.confidence < VERIFIED


def test_accessory_never_matches_device():
    r = match("Apple iPhone 16 Plus", "Silicone Case for iPhone 16 Plus")
    assert r.is_conflict and "kind" in r.conflicts
    assert extract_attributes("Skin for Apple iPhone 16 Pro Max").kind == "accessory"
    assert classify_category("Tempered Glass Screen Protector for iPhone 16") == "accessories"


def test_device_with_charging_case_is_not_accessory():
    assert extract_attributes("Apple AirPods Pro 2 with MagSafe Charging Case (USB-C)").kind == "device"
    assert extract_attributes("Apple iPhone 16 Plus").kind == "device"


# --- regressions from the iPhone 17 Pro product page ---
def test_restored_carrier_and_rental_listings():
    a = extract_attributes("Restored Apple iPhone 17 Pro - Verizon - 256GB Silver")
    assert a.condition == "refurbished" and a.region == "us_carrier"
    r = match("Apple iPhone 17 Pro (256GB) Silver", "Apple iPhone 17 Pro - Verizon - 256GB Silver")
    assert r.is_conflict and "region" in r.conflicts
    from app.matching.attributes import NON_PRODUCT_RE
    assert NON_PRODUCT_RE.search("Apple Rent iPhone 17 Pro") and not NON_PRODUCT_RE.search("Apple iPhone 17 Pro")


def test_storage_known_on_one_side_is_not_verified():
    r = match("Apple iPhone 17 Pro", "Apple iPhone 17 Pro (256GB) - Deep Blue with AppleCare Services")
    assert not r.is_conflict and r.confidence < VERIFIED

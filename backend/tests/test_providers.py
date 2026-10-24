import asyncio

import httpx
import pytest

from app.core.urls import classify_link, validate_offer_url
from app.models import Provider
from app.providers.amazon_creators import AmazonCreatorsProvider
from app.providers.base import ProviderError
from app.providers.flipkart_affiliate import FlipkartAffiliateProvider
from app.providers.registry import ProviderRegistry
from app.providers.serpapi_shopping import SerpApiGoogleShoppingProvider
from tests.fakes import FakeProvider, row


def client_for(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


# ---------------------------------------------------------------- URL rules
@pytest.mark.parametrize("url,ok", [
    ("https://www.flipkart.com/apple-iphone-16/p/itm123?pid=MOB1", True),
    ("javascript:alert(1)", False),
    ("http://shop.example/p/1", False),
    ("https://user:pw@shop.example/p/1", False),
    ("", False),
    ("ftp://shop.example/x", False),
])
def test_validate_offer_url(url, ok):  # noqa: ANN001
    assert validate_offer_url(url)[0] is ok


def test_classify_link():
    assert classify_link("https://www.amazon.in/dp/B0DGJ65N7V?tag=x-21") == "exact_listing"
    assert classify_link("https://www.amazon.in/s?k=iphone+16") == "search_page"
    assert classify_link("https://www.flipkart.com/search?q=iphone") == "search_page"
    assert classify_link("https://www.google.com/search?ibp=oshop&q=iphone") == "aggregator_page"
    assert classify_link("https://www.croma.com/") == "homepage"
    assert classify_link("https://www.flipkart.com/apple-iphone-16-black-128-gb/p/itmb07?pid=MOB&q=iphone") == "exact_listing"


# ---------------------------------------------------------------- Flipkart
FLIPKART_SAMPLE = {"products": [
    {"productBaseInfoV1": {"productId": "MOBH4DQFG8NKFRDY", "title": "Apple iPhone 16 (Black, 128 GB)",
                           "productUrl": "https://dl.flipkart.com/dl/apple-iphone-16-black-128-gb/p/itmb07?pid=MOBH4DQFG8NKFRDY&affid=x",
                           "flipkartSpecialPrice": {"amount": 69999.0, "currency": "INR"},
                           "flipkartSellingPrice": {"amount": 72999.0, "currency": "INR"},
                           "maximumRetailPrice": {"amount": 79900.0, "currency": "INR"}, "inStock": True,
                           "productBrand": "Apple", "imageUrls": {"400x400": "https://rukminim2.flixcart.com/x.jpg"},
                           "attributes": {"color": "Black"}, "categoryPath": "Mobiles>Apple"},
     "productShippingInfoV1": {"shippingCharges": {"amount": 0.0, "currency": "INR"}, "sellerName": "RetailNet"}},
    {"productBaseInfoV1": {"productId": "NOPRICE", "title": "Broken listing", "productUrl": "https://dl.flipkart.com/dl/x/p/itm1",
                           "flipkartSpecialPrice": {}, "flipkartSellingPrice": {}}},
    {"productBaseInfoV1": {"productId": "BADURL", "title": "Bad URL listing", "productUrl": "javascript:alert(1)",
                           "flipkartSellingPrice": {"amount": 100, "currency": "INR"}}},
]}


def test_flipkart_parsing_and_rejection(settings):  # noqa: ANN001
    settings.flipkart_affiliate_id, settings.flipkart_affiliate_token = "id", "tok"
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["headers"] = req.headers
        seen["url"] = str(req.url)
        return httpx.Response(200, json=FLIPKART_SAMPLE)

    p = FlipkartAffiliateProvider(settings, client_for(handler))
    out = run(p.search_products("iphone 16", 10))
    assert len(out) == 1 and p.last_rejections == 2
    lst = out[0]
    assert lst.price == 69999.0 and lst.mrp == 79900.0 and lst.currency == "INR"
    assert lst.product_url == FLIPKART_SAMPLE["products"][0]["productBaseInfoV1"]["productUrl"]  # unchanged
    assert lst.link_type == "exact_listing" and lst.availability == "in_stock" and lst.shipping_cost == 0.0
    assert seen["headers"]["Fk-Affiliate-Id"] == "id" and "search.json" in seen["url"]


# ---------------------------------------------------------------- Amazon
AMAZON_SAMPLE = {"searchResult": {"items": [
    {"asin": "B0DGJ65N7V", "detailPageURL": "https://www.amazon.in/dp/B0DGJ65N7V?tag=test-21&linkCode=osi",
     "itemInfo": {"title": {"displayValue": "iPhone 16 128 GB: 5G Mobile Phone with Camera Control; Black"},
                  "byLineInfo": {"brand": {"displayValue": "Apple"}}},
     "images": {"primary": {"large": {"url": "https://m.media-amazon.com/images/I/x.jpg"}}},
     "offersV2": {"listings": [{"availability": {"type": "IN_STOCK"}, "condition": {"value": "New"}, "isBuyBoxWinner": True,
                                "merchantInfo": {"name": "Appario Retail"},
                                "price": {"money": {"amount": 70990.0, "currency": "INR", "displayAmount": "₹70,990.00"}}}]}},
    {"asin": "B0USD", "detailPageURL": "https://www.amazon.in/dp/B0USD",
     "itemInfo": {"title": {"displayValue": "Wrong currency item"}},
     "offersV2": {"listings": [{"price": {"money": {"amount": 10, "currency": "USD"}}}]}},
]}}


def test_amazon_parsing_token_and_currency_rejection(settings):  # noqa: ANN001
    settings.amazon_creators_credential_id = "cid"
    settings.amazon_creators_credential_secret = "sec"
    settings.amazon_partner_tag = "test-21"
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path.endswith("/auth/o2/token"):
            return httpx.Response(200, json={"access_token": "abc", "token_type": "bearer", "expires_in": 3600})
        assert req.headers["Authorization"] == "Bearer abc" and req.headers["x-marketplace"] == "www.amazon.in"
        return httpx.Response(200, json=AMAZON_SAMPLE)

    p = AmazonCreatorsProvider(settings, client_for(handler))
    out = run(p.search_products("iphone 16", 10))
    assert len(out) == 1 and p.last_rejections == 1
    assert out[0].product_url == "https://www.amazon.in/dp/B0DGJ65N7V?tag=test-21&linkCode=osi"
    assert out[0].retailer == "Amazon India" and out[0].seller_name == "Appario Retail" and out[0].brand == "Apple"
    assert calls[0].endswith("/auth/o2/token") and calls[1].endswith("/searchItems")


# ---------------------------------------------------------------- SerpApi
def test_serpapi_google_link_labelled_aggregator(settings):  # noqa: ANN001
    settings.serpapi_api_key = "k"
    data = {"shopping_results": [
        {"title": "Apple iPhone 16 128GB Black", "product_id": "123", "source": "Croma", "price": "₹69,900.00",
         "extracted_price": 69900, "product_link": "https://www.google.com/search?ibp=oshop&prds=pid:123", "rating": 4.6, "reviews": 1200},
        {"title": "Apple iPhone 16 128GB Black", "product_id": "123", "source": "Vijay Sales", "price": "₹70,490.00",
         "extracted_price": 70490, "link": "https://www.vijaysales.com/p/123/apple-iphone-16-128gb-black"},
        {"title": "no price", "product_id": "9", "source": "X", "product_link": "https://www.google.com/x"},
    ]}
    p = SerpApiGoogleShoppingProvider(settings, client_for(lambda r: httpx.Response(200, json=data)))
    out = run(p.search_products("iphone 16", 10))
    assert len(out) == 2 and p.last_rejections == 1
    assert out[0].link_type == "aggregator_page" and out[1].link_type == "exact_listing"
    assert out[0].listing_key != out[1].listing_key


def test_serpapi_quota_error(settings):  # noqa: ANN001
    settings.serpapi_api_key = "k"
    p = SerpApiGoogleShoppingProvider(settings, client_for(lambda r: httpx.Response(200, json={"error": "Your account has run out of searches."})))
    with pytest.raises(ProviderError) as e:
        run(p.search_products("x y", 10))
    assert e.value.kind == "quota_exceeded"


# ---------------------------------------------------------------- HTTP errors
def test_rate_limit_retry_after_and_backoff(settings, db):  # noqa: ANN001
    settings.flipkart_affiliate_id, settings.flipkart_affiliate_token = "id", "tok"
    p = FlipkartAffiliateProvider(settings, client_for(lambda r: httpx.Response(429, headers={"Retry-After": "120"})))
    reg = ProviderRegistry(settings, [p])
    reg.ensure_rows(db)
    res = run(reg.run(db, "search_products", p, "iphone", 10))
    assert res.status == "rate_limited" and res.retry_after == 120
    row_ = db.get(Provider, p.id)
    assert row_.consecutive_failures == 1 and row_.cooldown_until is not None
    # next call is skipped while cooling down – no request hammering
    res2 = run(reg.run(db, "search_products", p, "iphone", 10))
    assert res2.status == "cooling_down"


def test_html_instead_of_json(settings):  # noqa: ANN001
    settings.flipkart_affiliate_id, settings.flipkart_affiliate_token = "id", "tok"
    p = FlipkartAffiliateProvider(settings, client_for(lambda r: httpx.Response(200, text="<html>captcha</html>",
                                                                              headers={"content-type": "text/html"})))
    with pytest.raises(ProviderError) as e:
        run(p.search_products("iphone", 10))
    assert e.value.kind == "not_json"


def test_timeout(settings):  # noqa: ANN001
    settings.flipkart_affiliate_id, settings.flipkart_affiliate_token = "id", "tok"

    def handler(req):  # noqa: ANN001, ANN202
        raise httpx.ReadTimeout("slow", request=req)

    p = FlipkartAffiliateProvider(settings, client_for(handler))
    with pytest.raises(ProviderError) as e:
        run(p.search_products("iphone", 10))
    assert e.value.kind == "timeout"


def test_provider_failure_isolation(settings, db):  # noqa: ANN001
    good = FakeProvider(settings, {"iphone": [row("a1", "Apple iPhone 16 (Black, 128 GB)", 69999)]}, provider_id="good")
    bad = FakeProvider(settings, error=ProviderError("server_error", "boom", 503), provider_id="bad")
    reg = ProviderRegistry(settings, [bad, good])
    reg.ensure_rows(db)
    results = run(reg.run_all(db, "search_products", "iphone", 10))
    by = {r.provider_id: r for r in results}
    assert by["bad"].status == "error" and by["good"].status == "ok" and len(by["good"].listings) == 1


def test_non_product_and_excluded_sellers_rejected(settings):  # noqa: ANN001
    settings.serpapi_api_key = "k"
    data = {"shopping_results": [
        {"title": "USA AT&T iPhone 16 Series Only (Recently Upgraded) [Duplicate-82452162]", "product_id": "1",
         "source": "Baba Tools", "price": "₹3,999.00", "extracted_price": 3999, "product_link": "https://www.google.com/x1"},
        {"title": "iPhone 16 Plus", "product_id": "2", "source": "KerfCase", "price": "₹24,147.38",
         "extracted_price": 24147.38, "product_link": "https://www.google.com/x2"},
        {"title": "Apple iPhone 16 Plus", "product_id": "3", "source": "Reliance Digital", "price": "₹79,900.00",
         "extracted_price": 79900, "product_link": "https://www.google.com/x3", "immersive_product_page_token": "tok3"},
    ]}
    p = SerpApiGoogleShoppingProvider(settings, client_for(lambda r: httpx.Response(200, json=data)))
    out = run(p.search_products("iphone 16", 10))
    assert [o.retailer for o in out] == ["Reliance Digital"] and p.last_rejections == 2
    assert out[0].provider_ref == "tok3"


def test_serpapi_store_list_gives_exact_links(settings):  # noqa: ANN001
    settings.serpapi_api_key = "k"
    seen = {}
    data = {"product_results": {"title": "Apple iPhone 16 Plus", "brand": "Apple", "stores": [
        {"name": "Reliance Digital", "link": "https://www.reliancedigital.in/product/apple-iphone-16-plus-128-gb-black/p/494422",
         "price": "₹79,900.00", "extracted_price": 79900, "shipping": "Free delivery"},
        {"name": "Croma", "link": "https://www.croma.com/apple-iphone-16-plus-128gb-black-/p/309688",
         "price": "₹78,990.00", "extracted_price": 78990, "extracted_original_price": 89900},
        {"name": "US Shop", "link": "https://shop.example.com/p/1", "price": "$899.00", "extracted_price": 899},
    ]}}

    def handler(req):  # noqa: ANN001, ANN202
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=data)

    p = SerpApiGoogleShoppingProvider(settings, client_for(handler))
    out = run(p.fetch_store_offers("tok3", "3", "Apple iPhone 16 Plus"))
    assert seen["engine"] == "google_immersive_product" and seen["page_token"] == "tok3"
    assert [o.retailer for o in out] == ["Reliance Digital", "Croma"] and p.last_rejections == 1  # $ price rejected
    assert all(o.link_type == "exact_listing" for o in out)
    assert out[0].shipping_cost == 0.0 and out[1].mrp == 89900
    assert out[1].listing_key == "3|store|croma"

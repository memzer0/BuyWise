"""Validation for outbound offer URLs shown to users as Buy Now links."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

GOOGLE_HOST_SUFFIXES = ("google.com", "google.co.in", "googleusercontent.com", "googleadservices.com")

# Path / query patterns that indicate a search or listing page rather than one product.
SEARCH_PATH_MARKERS = ("/s", "/search", "/sch/", "/searchresults", "/catalogsearch")
SEARCH_QUERY_KEYS = ("k", "q", "query", "field-keywords", "searchterm", "text")


def validate_offer_url(url: str | None, allow_http: bool = False) -> tuple[bool, str | None]:
    """Return (ok, reason). Rejects non-http(s) schemes, credentials in URL, missing host."""
    if not url or not isinstance(url, str):
        return False, "missing_url"
    url = url.strip()
    if len(url) > 2048:
        return False, "url_too_long"
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http"):
        return False, "unsafe_scheme"
    if scheme == "http" and not allow_http:
        return False, "insecure_http"
    if not parsed.hostname:
        return False, "missing_host"
    if parsed.username or parsed.password:
        return False, "credentials_in_url"
    return True, None


def classify_link(url: str) -> str:
    """Classify a validated URL.

    exact_listing    – a single retailer product page
    aggregator_page  – a Google Shopping / comparison page, not the retailer listing
    search_page      – a retailer search / results page (never presented as exact)
    homepage         – bare domain
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if any(host == s or host.endswith("." + s) for s in GOOGLE_HOST_SUFFIXES):
        return "aggregator_page"
    if path in ("", "/"):
        return "homepage"
    lowered = path.lower().rstrip("/") or "/"
    if lowered == "/":
        return "homepage"
    qs = parse_qs(parsed.query)
    is_search_path = lowered in SEARCH_PATH_MARKERS or lowered.endswith("/search")
    if is_search_path or (any(k in qs for k in SEARCH_QUERY_KEYS) and "/dp/" not in lowered and "/p/" not in lowered):
        return "search_page"
    return "exact_listing"


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()

"""Trusted-store list: established Indian electronics retailers and official brand stores.

"Trusted" means the store is on this curated list (configurable with TRUSTED_STORES / TRUSTED_DOMAINS).
It does not verify individual third-party sellers on a marketplace. An offer is trusted when its retailer
name or its exact link's domain is on the list.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

DEFAULT_TRUSTED_STORES = (
    "Amazon, Amazon.in, Amazon India, Flipkart, Croma, Reliance Digital, Vijay Sales, Tata CLiQ, JioMart, "
    "Apple, Apple Store, Samsung, Samsung India, Samsung Shop, OnePlus, Xiaomi, Mi, Mi Store, Google Store, "
    "Sangeetha Mobiles, Poorvika, Lenovo, HP, HP Store, Dell, ASUS, Acer, Sony, Sony Center, ShopatSC, "
    "boAt, boAt Lifestyle, Noise, Bajaj Electronics, Cashify"
)
DEFAULT_TRUSTED_DOMAINS = (
    "amazon.in, flipkart.com, croma.com, reliancedigital.in, vijaysales.com, tatacliq.com, jiomart.com, "
    "apple.com, samsung.com, oneplus.in, mi.com, store.google.com, sangeethamobiles.com, poorvika.com, "
    "lenovo.com, hp.com, dell.com, asus.com, acer.com, sony.co.in, shopatsc.com, boat-lifestyle.com, "
    "gonoise.com, bajajelectronics.com, cashify.in"
)


DEFAULT_PREFERRED_STORES = "Flipkart, Reliance Digital, Amazon, Vijay Sales, Croma"
PREFERRED_DOMAINS = {
    "flipkart": "flipkart.com", "reliancedigital": "reliancedigital.in", "amazon": "amazon.in",
    "vijaysales": "vijaysales.com", "croma": "croma.com",
}


def normalize_store(name: str | None) -> str:
    n = (name or "").lower().strip()
    n = re.sub(r"\.(com|in|co\.in)$", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def parse_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


class TrustPolicy:
    def __init__(self, stores: str, domains: str, preferred: str = DEFAULT_PREFERRED_STORES):
        self.names = {normalize_store(s) for s in parse_list(stores)}
        self.domains = [d.lower().lstrip(".") for d in parse_list(domains)]
        # preferred stores are always trusted and are listed first, in this order
        self.preferred = [normalize_store(s) for s in parse_list(preferred)]
        self.names.update(self.preferred)

    def preferred_rank(self, retailer: str | None, url: str | None = None, link_type: str | None = None) -> int | None:
        """0-based position in the preferred-store list, or None. 'Amazon India' / 'Amazon.in' count as Amazon."""
        name = normalize_store(retailer)
        host = (urlparse(url).hostname or "").lower() if url and link_type == "exact_listing" else ""
        for i, pref in enumerate(self.preferred):
            if name == pref or (name.startswith(pref) and name[len(pref):] in ("india", "in", "store", "shop")):
                return i
            dom = PREFERRED_DOMAINS.get(pref)
            if dom and host and (host == dom or host.endswith("." + dom)):
                return i
        return None

    def is_trusted(self, retailer: str | None, url: str | None = None, link_type: str | None = None) -> bool:
        if normalize_store(retailer) in self.names:
            return True
        if url and link_type == "exact_listing":
            host = (urlparse(url).hostname or "").lower()
            return any(host == d or host.endswith("." + d) for d in self.domains)
        return False

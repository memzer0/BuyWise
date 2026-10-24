"""True Final Price: what a shopper would actually pay at each store.

Guaranteed part   = verified base price + shipping (only when the store reported it).
Conditional part  = bank-card offers / coupons parsed from the store's own offer text. They are applied ONLY when
                    the shopper says they hold that bank's card (or opts in to coupons), are capped as the text states,
                    and respect a stated minimum purchase. Exchange and EMI offers are listed but never subtracted,
                    because their value depends on things BuyWise cannot check.
Assumption (stated to the user): at most one bank offer and one coupon are combined per store.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

BANKS = [
    ("HDFC", r"hdfc"), ("ICICI", r"icici"), ("SBI", r"\bsbi\b|state bank"), ("Axis", r"\baxis\b"),
    ("Kotak", r"kotak"), ("IDFC First", r"idfc"), ("Yes Bank", r"yes bank"), ("AU Bank", r"\bau (small finance )?bank"),
    ("IndusInd", r"indusind"), ("OneCard", r"one ?card"), ("RBL", r"\brbl\b"), ("HSBC", r"hsbc"),
    ("Standard Chartered", r"standard chartered"), ("Federal Bank", r"federal bank"), ("Bank of Baroda", r"bank of baroda|\bbob\b"),
    ("American Express", r"amex|american express"), ("Citi", r"\bciti"),
]
_AMT = r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)"
FLAT_RE = re.compile(_AMT + r"\s*(?:instant\s*)?(?:off|discount|cashback|savings?)", re.I)
FLAT_RE2 = re.compile(r"(?:flat|instant discount of|discount of|save|get)\s*" + _AMT, re.I)
PCT_RE = re.compile(r"(\d{1,2}(?:\.\d+)?)\s*%\s*(?:instant\s*)?(?:off|discount|cashback|savings?)", re.I)
CAP_RE = re.compile(r"(?:up ?to|max(?:imum)?(?: discount)?(?: of)?)\s*" + _AMT, re.I)
MIN_RE = re.compile(r"(?:min(?:imum)?\.?\s*(?:purchase|order|transaction|cart)(?:\s*value)?(?:\s*of)?|on (?:orders|purchases) (?:above|over|of))\s*" + _AMT, re.I)
CODE_RE = re.compile(r"(?:code|coupon)\s*[:\-]?\s*['\"]?([A-Z0-9]{4,20})\b")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class OfferTerm:
    text: str
    kind: str                      # bank / coupon / exchange / emi / cashback / other
    banks: list[str] = field(default_factory=list)
    flat_off: float | None = None
    percent: float | None = None
    cap: float | None = None
    min_purchase: float | None = None
    code: str | None = None

    def saving(self, price: float) -> tuple[float, str | None]:
        """Saving on `price`, or 0 and the reason it can't be applied."""
        if self.kind in ("exchange", "emi"):
            return 0.0, "depends on your old device / loan terms"
        if self.min_purchase and price < self.min_purchase:
            return 0.0, f"needs a minimum purchase of ₹{self.min_purchase:,.0f}"
        if self.flat_off:
            amt = self.flat_off
        elif self.percent:
            amt = price * self.percent / 100
        else:
            return 0.0, "the amount is not stated clearly"
        if self.cap:
            amt = min(amt, self.cap)
        return round(min(amt, price), 2), None


def parse_note(text: str) -> OfferTerm:
    t = " ".join(str(text).split())
    low = t.lower()
    banks = [name for name, rx in BANKS if re.search(rx, low)]
    flat = FLAT_RE.search(t) or FLAT_RE2.search(t)
    pct = PCT_RE.search(t)
    cap = CAP_RE.search(t)
    mn = MIN_RE.search(t)
    code = CODE_RE.search(t)
    if "exchange" in low:
        kind = "exchange"
    elif banks or re.search(r"\b(credit|debit) card", low):
        kind = "bank"
    elif code or "coupon" in low:
        kind = "coupon"
    elif "emi" in low and not (flat or pct):
        kind = "emi"
    elif "cashback" in low:
        kind = "cashback"
    else:
        kind = "other"
    flat_v = _num(flat.group(1)) if flat else None
    cap_v = _num(cap.group(1)) if cap else None
    if flat_v is not None and cap_v is not None and abs(flat_v - cap_v) < 0.01 and pct:
        flat_v = None  # "10% off up to ₹1,500" – the ₹ figure is the cap, not a flat discount
    return OfferTerm(t[:300], kind, banks, flat_v, _num(pct.group(1)) if pct else None, cap_v,
                     _num(mn.group(1)) if mn else None, code.group(1) if code else None)


def notes_from_store(store: dict) -> list[str]:
    """Collect offer text from a Google Shopping store entry (`details_and_offers`, `coupon`, `discount`)."""
    out: list[str] = []
    for item in store.get("details_and_offers") or []:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            txt = " ".join(str(v) for k, v in item.items() if isinstance(v, (str, int, float)) and k not in ("link", "thumbnail"))
            if txt.strip():
                out.append(txt)
    for key in ("coupon", "discount"):
        v = store.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v)
        elif isinstance(v, dict):
            txt = " ".join(str(x) for x in v.values() if isinstance(x, (str, int, float)))
            if txt.strip():
                out.append(txt)
    # keep only lines that look like offers, not generic details such as "In stock online"
    keep = [o for o in out if re.search(r"off|discount|cashback|coupon|code|bank|card|emi|exchange|save", o, re.I)]
    return list(dict.fromkeys(" ".join(k.split())[:300] for k in keep))[:12]


@dataclass
class StoreFinalPrice:
    offer_id: int
    retailer: str
    base_price: float
    shipping: float | None
    guaranteed_total: float | None          # None when shipping is not reported
    applied: list[dict] = field(default_factory=list)
    not_applied: list[dict] = field(default_factory=list)
    possible_total: float | None = None
    unknowns: list[str] = field(default_factory=list)


def compute(offers: list[dict], banks: set[str], use_coupons: bool) -> dict:
    """`offers`: offer dicts from the catalog (eligible ones are used). `banks`: cards the shopper says they hold."""
    rows: list[StoreFinalPrice] = []
    mentioned: set[str] = set()
    any_terms = False
    for o in offers:
        if o.get("price") is None or not o.get("eligible_for_best_price"):
            continue
        base = float(o["price"])
        ship = o.get("shipping_cost")
        row = StoreFinalPrice(o["offer_id"], o.get("retailer") or "Store", base, ship,
                              round(base + ship, 2) if ship is not None else None)
        if ship is None:
            row.unknowns.append("Delivery charge not reported by the store")
        terms = [parse_note(n) for n in (o.get("offer_notes") or [])]
        any_terms = any_terms or bool(terms)
        best_bank: tuple[float, OfferTerm] | None = None
        best_coupon: tuple[float, OfferTerm] | None = None
        for term in terms:
            mentioned.update(term.banks)
            saving, why = term.saving(base)
            entry = {**asdict(term), "saving": saving}
            if term.kind == "bank":
                if not term.banks:
                    row.not_applied.append({**entry, "reason": "card type/bank not named – check eligibility on the store page"})
                elif not (banks & set(term.banks)):
                    row.not_applied.append({**entry, "reason": f"you haven't selected {', '.join(term.banks)}"})
                elif why:
                    row.not_applied.append({**entry, "reason": why})
                elif not best_bank or saving > best_bank[0]:
                    if best_bank:
                        row.not_applied.append({**asdict(best_bank[1]), "saving": best_bank[0], "reason": "a bigger bank offer was used"})
                    best_bank = (saving, term)
                else:
                    row.not_applied.append({**entry, "reason": "a bigger bank offer was used"})
            elif term.kind == "coupon":
                if not use_coupons:
                    row.not_applied.append({**entry, "reason": "coupons not included"})
                elif why:
                    row.not_applied.append({**entry, "reason": why})
                elif not best_coupon or saving > best_coupon[0]:
                    best_coupon = (saving, term)
            else:
                row.not_applied.append({**entry, "reason": why or "not a fixed discount – check terms on the store page"})
        for pick in (best_bank, best_coupon):
            if pick:
                row.applied.append({**asdict(pick[1]), "saving": pick[0]})
        start = row.guaranteed_total if row.guaranteed_total is not None else base
        row.possible_total = round(start - sum(a["saving"] for a in row.applied), 2)
        rows.append(row)
    rows.sort(key=lambda r: (r.possible_total if r.possible_total is not None else 1e12))
    return {
        "stores": [asdict(r) for r in rows],
        "banks_mentioned": sorted(mentioned),
        "selected_banks": sorted(banks),
        "coupons_included": use_coupons,
        "offers_data_available": any_terms,
        "assumptions": [
            "Base prices are the verified store prices BuyWise fetched; taxes are included in Indian retail prices.",
            "Bank offers are applied only for cards you select, using the cap and minimum purchase stated in the offer text.",
            "At most one bank offer and one coupon are combined per store.",
            "Exchange, EMI and unclear offers are listed but never subtracted.",
            "Always confirm the final amount at checkout – offers can change or have extra conditions.",
        ],
    }

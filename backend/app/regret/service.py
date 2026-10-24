"""BuyWise Regret Shield.

Pre-purchase:  maps the existing Decision Engine to BUY NOW / WAIT / COMPARE FIRST / INSUFFICIENT DATA and lists the
               evidence (and what is missing) behind it.
Post-purchase: compares a registered purchase with the cheapest *comparable* verified offer for the SAME product
               record (BuyWise products are variant-level: same storage, RAM, colour, generation, condition).
               Comparable = trusted store, verified match, not stale, not out of stock, same condition.

    Price difference      = purchase price − comparable current price       (positive = it is cheaper now)
    Percentage difference = price difference / purchase price × 100

A drop is "meaningful" when it is ≥ REGRET_MIN_DROP_PCT % of the purchase price AND ≥ REGRET_MIN_DROP_AMOUNT rupees.
An observed drop is NOT money the shopper can recover; BuyWise never assumes a refund, price protection or an
accepted return. The estimated net benefit is shown only when the shopper entered their expected costs, and only as
"if a return with a full refund is accepted".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Offer, Product, PurchaseCheck, PurchaseNotification, TrackedPurchase
from app.pricing.offers import aware, eligible_for_best_price, select_lowest
from app.services.mailer import send_email

IST = ZoneInfo("Asia/Kolkata")
SUBJECTS = {"price_drop": "price drop on something you bought", "deadline": "a deadline is coming up",
            "monitoring": "prices couldn't be checked"}
RESULT_LABELS = {
    "BUY_NOW": "Buy now",
    "WAIT": "Wait",
    "COMPARE_FIRST": "Compare first",
    "INSUFFICIENT_DATA": "Tracking price",
}


def today_ist(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(IST).date()


def inr(v: float) -> str:
    n = str(int(round(abs(v))))
    if len(n) > 3:
        rest, last3 = n[:-3], n[-3:]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        n = ",".join(groups + [last3])
    return ("-" if v < 0 else "") + f"₹{n}"


class RegretService:
    def __init__(self, catalog) -> None:  # noqa: ANN001
        self.catalog = catalog
        self.settings = catalog.settings

    # ------------------------------------------------------------------ comparable offer
    def comparable(self, product: Product) -> dict:
        offers = self.catalog.visible_offers(product)
        views = [self.catalog.offer_view(o) for o in offers]
        best = select_lowest(views, include_refurbished=product.condition != "new")
        if best is not None:
            o = next(x for x in offers if x.id == best.id)
            return {"status": "comparable", "offer_id": o.id, "price": o.price,
                    "retailer": o.retailer.name if o.retailer else None, "product_url": o.product_url,
                    "link_type": o.link_type, "last_verified_at": aware(o.last_verified_at),
                    "freshness": best.freshness, "match_confidence": o.match_confidence, "reason": None}
        priced = [(o, v) for o, v in zip(offers, views) if o.price is not None]
        stale = [o for o, v in priced if eligible_for_best_price(v)[1] == "freshness_stale"]
        if stale:
            latest = max(aware(o.last_verified_at) for o in stale)
            return {"status": "stale_data", "reason": f"The latest verified prices are stale (last checked {latest:%d %b %Y %H:%M} UTC).",
                    "last_verified_at": latest}
        return {"status": "comparable_unavailable", "last_verified_at": None,
                "reason": "No verified, in-stock offer for this exact product and variant from a trusted store right now."}

    # ------------------------------------------------------------------ evaluation
    def deadlines(self, p: TrackedPurchase, now: datetime | None = None) -> list[dict]:
        t = today_ist(now)
        out = []
        for kind, label, d in (("return", "Return / exchange window", p.return_deadline),
                               ("protection", "Price-protection window", p.protection_deadline)):
            if d is None:
                continue
            dd = aware(d).astimezone(IST).date() if isinstance(d, datetime) else d
            left = (dd - t).days
            state = "passed" if left < 0 else "today" if left == 0 else "soon" if left <= self.settings.regret_deadline_warn_days else "upcoming"
            out.append({"kind": kind, "label": label, "date": dd.isoformat(), "days_left": left, "state": state})
        return out

    def evaluate(self, db: Session, p: TrackedPurchase, now: datetime | None = None) -> dict:
        s = self.settings
        comp = self.comparable(p.product)
        dls = self.deadlines(p, now)
        res: dict = {"comparable": {k: v for k, v in comp.items() if k != "last_verified_at"},
                     "comparable_verified_at": comp["last_verified_at"].isoformat() if comp.get("last_verified_at") else None,
                     "deadlines": dls, "difference": None, "difference_pct": None, "meaningful_drop": False,
                     "net_benefit": None, "actions": [], "notes": []}
        if comp["status"] != "comparable":
            res["status"] = comp["status"]
            res["notes"].append(comp["reason"])
            return res
        price = float(comp["price"])
        if not p.purchase_price or p.purchase_price <= 0:
            res["status"] = "invalid_purchase_price"
            res["notes"].append("The purchase price must be greater than zero to compare.")
            return res
        diff = round(p.purchase_price - price, 2)
        pct = round(diff / p.purchase_price * 100, 2)
        res["difference"], res["difference_pct"] = diff, pct
        meaningful = diff >= s.regret_min_drop_amount and pct >= s.regret_min_drop_pct
        res["meaningful_drop"] = meaningful
        if meaningful:
            res["status"] = "price_drop"
        elif diff > 0:
            res["status"] = "small_drop"
            res["notes"].append(f"Cheaper by {inr(diff)}, below the {s.regret_min_drop_pct:g}% / {inr(s.regret_min_drop_amount)} threshold for alerts.")
        else:
            res["status"] = "no_drop"
        if comp["retailer"] and comp["retailer"].lower() != (p.retailer or "").lower():
            res["notes"].append(f"The comparable offer is from {comp['retailer']}, not {p.retailer}; a different store's price doesn't oblige {p.retailer} to refund you.")
        if comp["link_type"] != "exact_listing":
            res["notes"].append("This offer's link opens Google Shopping – confirm the exact listing before acting.")
        res["notes"].append("Warranty terms for the comparable offer are not reported by the data source – check they match yours.")
        if meaningful:
            open_dls = [d for d in dls if d["state"] != "passed"]
            acts = [f"Check whether {p.retailer} offers a price adjustment for drops after purchase (don't assume it does)."]
            if any(d["kind"] == "protection" for d in open_dls):
                acts.append("Your price-protection window is still open – contact the seller with your order details.")
            if any(d["kind"] == "return" for d in open_dls):
                acts.append("Your return/exchange window is still open – check the return conditions, restocking fees and return shipping first.")
            if dls and not open_dls:
                acts.append("Your entered deadlines have passed, so a return or adjustment is unlikely – keep this for future purchases.")
            acts.append(f"Compare the benefit ({inr(diff)}) against return shipping, restocking charges and the effort of re-buying.")
            acts.append(f"Open the comparable offer at {comp['retailer']} and review its terms before acting.")
            res["actions"] = acts
            if p.expected_costs is not None:
                res["net_benefit"] = {"amount": round(diff - p.expected_costs, 2),
                                      "label": "Estimated – only if a return with a full refund is accepted and you re-buy at the comparable price",
                                      "inputs": {"difference": diff, "expected_costs": p.expected_costs}}
            else:
                res["notes"].append("Net benefit not shown: enter your expected return/restocking costs to estimate it.")
        return res

    # ------------------------------------------------------------------ persistence of checks + notifications
    def record(self, db: Session, p: TrackedPurchase, ev: dict, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        bucket = int(now.timestamp() // (self.settings.regret_check_bucket_minutes * 60))
        comp = ev["comparable"]
        fields = dict(checked_at=now, status=ev["status"], comparable_price=comp.get("price"), retailer=comp.get("retailer"),
                      offer_id=comp.get("offer_id"), difference=ev["difference"],
                      offer_verified_at=datetime.fromisoformat(ev["comparable_verified_at"]) if ev["comparable_verified_at"] else None)
        existing = db.scalar(select(PurchaseCheck).where(PurchaseCheck.purchase_id == p.id, PurchaseCheck.bucket == bucket))
        if existing is not None:  # one row per purchase per bucket, holding the latest result in that bucket
            for k, v in fields.items():
                setattr(existing, k, v)
        else:
            try:
                with db.begin_nested():
                    db.add(PurchaseCheck(purchase_id=p.id, bucket=bucket, **fields))
            except IntegrityError:
                pass
        p.status = ev["status"]
        p.last_checked_at = now
        if p.notify:
            self._notify(db, p, ev)

    def _add_notification(self, db: Session, p: TrackedPurchase, kind: str, key: str, message: str) -> bool:
        if db.scalar(select(PurchaseNotification.id).where(PurchaseNotification.purchase_id == p.id,
                                                            PurchaseNotification.event_key == key)):
            return False
        try:
            with db.begin_nested():
                n = PurchaseNotification(purchase_id=p.id, kind=kind, event_key=key[:120], message=message[:500])
                db.add(n)
        except IntegrityError:
            return False
        if p.email:  # each event is e-mailed once – the unique event key above prevents repeats
            n.email_status, _ = send_email(self.settings, p.email, f"BuyWise Regret Shield: {SUBJECTS.get(kind, 'update')}",
                                           f"{message}\n\nOpen BuyWise → Regret Shield to see the details.\n"
                                           "BuyWise never assumes a store will refund a difference or accept a return – "
                                           "check the store's policy first.\n")
        return True

    def _notify(self, db: Session, p: TrackedPurchase, ev: dict) -> None:
        comp = ev["comparable"]
        title = p.product.title[:80]
        if ev["status"] == "price_drop":
            self._add_notification(db, p, "price_drop", f"drop:{comp['offer_id']}:{int(comp['price'])}",
                                   f"{title}: now {inr(comp['price'])} at {comp['retailer']} – {inr(ev['difference'])} "
                                   f"({ev['difference_pct']:.1f}%) below what you paid.")
        for d in ev["deadlines"]:
            if d["state"] in ("soon", "today"):
                when = "today" if d["days_left"] == 0 else f"in {d['days_left']} day(s)"
                self._add_notification(db, p, "deadline", f"deadline:{d['kind']}:{d['date']}",
                                       f"{title}: your {d['label'].lower()} ends {when} ({d['date']}).")
        if ev["status"] in ("comparable_unavailable", "stale_data"):
            recent = db.scalars(select(PurchaseCheck).where(PurchaseCheck.purchase_id == p.id)
                                .order_by(PurchaseCheck.checked_at.desc()).limit(3)).all()
            if len(recent) == 3 and all(c.status in ("comparable_unavailable", "stale_data") for c in recent):
                last_ok = db.scalar(select(PurchaseCheck.checked_at).where(
                    PurchaseCheck.purchase_id == p.id, PurchaseCheck.status.not_in(("comparable_unavailable", "stale_data")))
                    .order_by(PurchaseCheck.checked_at.desc()).limit(1))
                self._add_notification(db, p, "monitoring", f"monitoring:{(last_ok or p.created_at):%Y%m%d%H}",
                                       f"{title}: BuyWise couldn't verify a comparable price in the last 3 checks. "
                                       "Monitoring continues automatically.")

    def monitor_all(self, db: Session, now: datetime | None = None, product_ids: set[int] | None = None) -> int:
        q = select(TrackedPurchase)
        if product_ids is not None:
            q = q.where(TrackedPurchase.product_id.in_(product_ids or {-1}))
        n = 0
        for p in db.scalars(q).all():
            self.record(db, p, self.evaluate(db, p, now), now)
            n += 1
        db.commit()
        return n

    # ------------------------------------------------------------------ pre-purchase
    def pre_check(self, db: Session, product: Product, demo: bool = False) -> dict:
        d = self.catalog.product_detail(db, product, demo=demo)
        dec = d["decision"]
        best = next((o for o in d["offers"] if o["is_best_price"]), None)
        result = {"BUY_NOW": "BUY_NOW", "WAIT": "WAIT", "CONSIDER_ALTERNATIVES": "COMPARE_FIRST",
                  "NOT_ENOUGH_DATA": "INSUFFICIENT_DATA"}[dec["verdict"]]
        reasons = [dec["headline"], *dec["reasons"]]
        compare_triggers = []
        if best and best["link_type"] != "exact_listing":
            compare_triggers.append("The cheapest offer's link opens Google Shopping, not the store's own listing – confirm the exact variant first.")
        if best and best["match_confidence"] is not None and best["match_confidence"] < 0.9:
            compare_triggers.append(f"Variant match confidence is {best['match_confidence'] * 100:.0f}% – check storage, RAM and colour on the listing.")
        if result == "BUY_NOW" and compare_triggers:
            result = "COMPARE_FIRST"
        reasons += compare_triggers
        evidence = [
            {"label": "Current price", "value": f"{inr(best['price'])} at {best['retailer']}" if best else None, "ok": best is not None},
            {"label": "Price vs. history", "value": d["deal"]["insight"]["title"] if d["deal"].get("insight") else None,
             "ok": d["deal"]["score"] is not None},
            {"label": "Exact variant", "value": f"{best['match_confidence'] * 100:.0f}% match" if best else None,
             "ok": bool(best and best["match_confidence"] >= 0.9)},
            {"label": "Delivery charge", "value": (("Free" if best["shipping_cost"] == 0 else inr(best["shipping_cost"]))
                                                    if best and best["shipping_cost"] is not None else None),
             "ok": bool(best and best["shipping_cost"] is not None)},
            {"label": "Seller", "value": ("Trusted store" if best["trusted_store"] else "Not on trusted list") if best else None,
             "ok": bool(best and best["trusted_store"])},
            {"label": "Warranty", "value": best["warranty"] if best and best.get("warranty") else None, "ok": bool(best and best.get("warranty"))},
            {"label": "Return policy", "value": None, "ok": False},
            {"label": "BuyWise Score", "value": f"{d['score']['score']}/100" if d["score"]["score"] is not None else None,
             "ok": d["score"]["score"] is not None},
        ]
        missing = [e["label"] for e in evidence if e["value"] is None]
        return {"result": result, "label": RESULT_LABELS[result], "reasons": reasons,
                "evidence": evidence, "missing": missing,
                "limitations": dec["limitations"] + (["Return policy isn't available from BuyWise's data sources – check it on the store page."]),
                "evidence_level": dec["evidence_level"],
                "demo_history": d.get("demo_history", False),
                "observed_at": best["last_verified_at"] if best else None,
                "best_offer": {"retailer": best["retailer"], "price": best["price"], "product_url": best["product_url"],
                               "link_type": best["link_type"]} if best else None}

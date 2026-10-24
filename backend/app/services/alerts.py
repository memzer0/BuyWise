"""Price alerts: fire once when the lowest verified price drops to/below target; re-arm when it rises above."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertEvent, PriceAlert, Product
from app.pricing.offers import select_lowest
from app.services.mailer import send_email

if TYPE_CHECKING:
    from app.services.catalog import CatalogService

log = logging.getLogger(__name__)


def evaluate_alerts(db: Session, catalog: CatalogService, product_id: int) -> int:
    alerts = db.scalars(select(PriceAlert).where(PriceAlert.product_id == product_id, PriceAlert.active.is_(True))).all()
    if not alerts:
        return 0
    product = db.get(Product, product_id)
    db.refresh(product)
    views = [catalog.offer_view(o) for o in product.offers]
    best = select_lowest(views, include_refurbished=product.condition != "new")
    fired = 0
    for alert in alerts:
        if best is None:
            continue
        if best.price <= alert.target_price:
            if not alert.armed:
                continue  # already notified for this dip – duplicate prevention
            offer = next(o for o in product.offers if o.id == best.id)
            status, error = deliver(catalog, alert, product, best.price, offer.retailer.name if offer.retailer else "", offer.product_url)
            db.add(AlertEvent(alert_id=alert.id, triggered_price=best.price,
                              retailer_name=offer.retailer.name if offer.retailer else "unknown",
                              offer_url=offer.product_url, delivery_channel=alert.channel,
                              delivery_status=status, delivery_error=error))
            alert.armed = False
            fired += 1
        elif not alert.armed:
            alert.armed = True  # price went back above target: allow a future notification
    db.commit()
    return fired


def deliver(catalog: CatalogService, alert: PriceAlert, product: Product, price: float, retailer: str,
            url: str | None) -> tuple[str, str | None]:
    if alert.channel == "in_app":
        return "recorded", None
    s = catalog.settings
    if alert.channel == "email":
        if not alert.email:
            return "failed", "No e-mail address on this alert."
        return send_email(s, alert.email,
                          f"BuyWise price alert: {product.title[:80]} is now ₹{price:,.0f}",
                          f"{product.title}\n\nLowest verified price: ₹{price:,.0f} at {retailer} (your target: ₹{alert.target_price:,.0f}).\n"
                          f"Listing: {url}\n\nPrices change frequently; check the retailer page before buying.\n{s.affiliate_disclosure}\n")
    return "failed", f"unknown channel {alert.channel}"

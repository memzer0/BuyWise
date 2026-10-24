import { ChevronRight, ExternalLink, Info, ShieldCheck, Star } from "lucide-react";
import type { Offer } from "../types/api";
import { capitalize, formatINR, safeHref, timeAgo } from "../utils/format";
import { StoreLogo } from "./StoreLogo";
import { Badge } from "./ui";

const INELIGIBLE: Record<string, string> = {
  unverified_match: "Possible match only – not used for lowest price",
  freshness_stale: "Price is stale – not used for lowest price",
  freshness_unavailable: "No verified price",
  out_of_stock: "Out of stock",
  no_price: "No price",
  untrusted_store: "Store not on the trusted list – not used for lowest price",
};

export function BuyButton({ offer }: { offer: Offer }) {
  const href = safeHref(offer.product_url);
  if (!href) return <span className="text-xs text-ink-soft">No valid link</span>;
  const exact = offer.link_type === "exact_listing";
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow sponsored" data-testid="buy-link"
      aria-label={`${exact ? "Buy" : "View"} at ${offer.retailer ?? "seller"} for ${formatINR(offer.price)}`}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-semibold ${
        exact ? "btn-gloss bg-accent-strong text-white hover:brightness-110" : "border border-line text-ink hover:bg-surface-2"}`}>
      {exact ? "Buy now" : "View offer"} {exact ? <ChevronRight className="h-4 w-4" aria-hidden /> : <ExternalLink className="h-3.5 w-3.5" aria-hidden />}
    </a>
  );
}

function Delivery({ o }: { o: Offer }) {
  if (o.shipping_cost === 0) return <span>Free delivery</span>;
  if (o.shipping_cost) return <span>Delivery {formatINR(o.shipping_cost)} · total {formatINR(o.total_cost)}</span>;
  return <span>Delivery charges not reported</span>;
}

function Relative({ o }: { o: Offer }) {
  if (o.is_best_price) return <span className="text-xs font-semibold text-success">Lowest price</span>;
  if (o.vs_best_pct == null || o.vs_best_pct === 0) return null;
  return o.vs_best_pct > 0
    ? <span className="text-xs font-medium text-danger">{o.vs_best_pct}% costlier</span>
    : <span className="text-xs font-medium text-success">{Math.abs(o.vs_best_pct)}% cheaper</span>;
}

/** "Compare available prices" list: one row per store. */
export function OfferTable({ offers }: { offers: Offer[] }) {
  return (
    <ul className="divide-y divide-line">
      {offers.map((o) => (
        <li key={o.offer_id} data-testid="offer-row" className={`flex gap-3 px-4 py-4 sm:px-5 ${o.is_best_price ? "bg-accent-soft/60" : ""}`}>
          <StoreLogo name={o.retailer} url={o.link_type === "exact_listing" ? o.product_url : null} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-base font-semibold">{o.retailer ?? "Unknown store"}</span>
                  {o.is_best_price && <Badge tone="sun">Lowest verified</Badge>}
                  {o.preferred_rank !== null && <Badge tone="brand"><Star className="h-3 w-3" aria-hidden /> Top store</Badge>}
                  {o.trusted_store
                    ? <Badge tone="teal"><ShieldCheck className="h-3 w-3" aria-hidden /> Trusted store</Badge>
                    : <Badge tone="amber">Not on trusted list</Badge>}
                  {o.condition !== "new" && <Badge tone="amber">{capitalize(o.condition)}</Badge>}
                </div>
                <p className="text-sm text-ink-soft"><Delivery o={o} /></p>
                {o.availability === "out_of_stock" && <p className="text-sm font-medium text-danger">Currently out of stock</p>}
              </div>
              <div className="text-right">
                <p className="tabular text-xl font-bold">{formatINR(o.price)}</p>
                <Relative o={o} />
                {o.mrp && o.price && o.mrp > o.price ? (
                  <p className="text-xs text-ink-soft"><span className="line-through">{formatINR(o.mrp)}</span> MRP</p>
                ) : null}
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <p className="min-w-0 truncate text-xs text-ink-soft" title={o.listing_title}>
                {o.listing_title} · checked {timeAgo(o.last_verified_at)}
                {o.link_type === "exact_listing" ? "" : " · link opens Google Shopping"}
              </p>
              <BuyButton offer={o} />
            </div>
            {o.link_type !== "exact_listing" && <Badge tone="amber">Google Shopping page</Badge>}
            {!o.eligible_for_best_price && o.ineligible_reason && INELIGIBLE[o.ineligible_reason] && (
              <p className="mt-1 flex items-center gap-1 text-xs text-ink-soft"><Info className="h-3 w-3" aria-hidden />{INELIGIBLE[o.ineligible_reason]}</p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

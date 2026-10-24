import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CompareButton } from "../components/compare/CompareButton";
import { Check, Copy, ExternalLink, Eye, Loader2, MessageCircle, RefreshCw, Sparkles, Star, Store } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { DealPanel } from "../components/DealPanel";
import { DecisionCard } from "../components/DecisionCard";
import { FinalPriceCalculator } from "../components/FinalPriceCalculator";
import { RegretShieldCard } from "../components/RegretShield";
import { ReviewsSection } from "../components/ReviewsSection";
import { OfferTable } from "../components/OfferTable";
import { PriceHistoryChart } from "../components/PriceHistoryChart";
import { ProductImage } from "../components/ProductCard";
import { StoreLogo } from "../components/StoreLogo";
import { StorePriceChart } from "../components/StorePriceChart";
import { Card, EmptyState, ErrorState, ProviderStrip, Skeleton } from "../components/ui";
import type { Offer, ProductDetail } from "../types/api";
import { CATEGORY_LABELS, capitalize, formatDateTime, formatINR, safeHref } from "../utils/format";

const OFFER_SORTS = [
  { v: "top_stores", label: "Top stores first" },
  { v: "price_asc", label: "Lowest price" },
  { v: "price_desc", label: "Highest price" },
  { v: "recent", label: "Most recently verified" },
  { v: "retailer", label: "Retailer" },
  { v: "availability", label: "Availability" },
];

const storageLabel = (gb: number) => (gb >= 1024 ? `${gb / 1024} TB` : `${gb} GB`);

export function ProductPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const [sort, setSort] = useState("top_stores");
  const [includeRefurb, setIncludeRefurb] = useState(false);
  const [allStores, setAllStores] = useState(false);

  const detail = useQuery({
    queryKey: ["product", id, includeRefurb],
    queryFn: ({ signal }) => api.product(id, includeRefurb, signal),
    enabled: Number.isInteger(id) && id > 0,
    // While the backend is refreshing prices in the background, poll until it finishes.
    refetchInterval: (q) => (q.state.data?.refresh_in_progress ? 3000 : false),
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });
  const offers = useQuery({
    queryKey: ["offers", id, sort, includeRefurb, allStores, detail.data?.product.last_verified_at],
    queryFn: ({ signal }) => api.offers(id, sort, includeRefurb, allStores, signal),
    enabled: detail.isSuccess,
  });
  const refresh = useMutation({
    mutationFn: () => api.refresh(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product", id] });
      qc.invalidateQueries({ queryKey: ["offers", id] });
      qc.invalidateQueries({ queryKey: ["history", id] });
      qc.invalidateQueries({ queryKey: ["regret", id] });
    },
  });
  const watch = useMutation({ mutationFn: () => api.addWatch(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }) });

  if (!Number.isInteger(id) || id <= 0) return <EmptyState title="Invalid product link" />;
  if (detail.isPending) return <ProductSkeleton />;
  if (detail.isError) {
    const e = detail.error as ApiError;
    return e.status === 404 ? <EmptyState title="Product not found">It may have been removed. Try searching again.</EmptyState>
      : <ErrorState message={e.message} onRetry={() => detail.refetch()} />;
  }
  const d = detail.data;
  const p = d.product;
  const best = d.offers.find((o) => o.is_best_price) ?? null;
  const offerList: Offer[] = offers.data?.offers ?? d.offers.filter((o) => allStores || o.trusted_store);
  const hiddenUntrusted = offers.data?.hidden_untrusted ?? 0;
  const specs: [string, string][] = [
    ["Brand", capitalize(p.brand)], ["Category", CATEGORY_LABELS[p.category] ?? p.category],
    ["Storage", p.storage_gb ? storageLabel(p.storage_gb) : ""], ["RAM", p.ram_gb ? `${p.ram_gb} GB` : ""],
    ["Colour", capitalize(p.colour)], ["Screen", p.screen_inches ? `${p.screen_inches}"` : ""],
    ["Condition", capitalize(p.condition)], ...Object.entries(p.specs ?? {}),
    ...p.identifiers.filter((i) => ["gtin", "model_number"].includes(i.kind)).map((i) => [i.kind.toUpperCase().replace("_", " "), i.value] as [string, string]),
  ].filter(([, v]) => v) as [string, string][];

  return (
    <div className="space-y-6">
      {/* ---------- top: gallery | details | deal panel ---------- */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)_minmax(320px,0.95fr)]">
        <div className="min-w-0 space-y-4">
          <Gallery d={d} />
          <KeySpecs specs={specs} />
        </div>

        <div className="min-w-0">
          {best?.retailer && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-sm font-semibold">
              <Store className="h-4 w-4 text-brand" aria-hidden /> {best.retailer}
            </span>
          )}
          <h1 className="mt-3 text-xl font-medium leading-snug sm:text-2xl" data-testid="product-title">{p.title}</h1>
          {best?.rating != null && (
            <p className="mt-2 flex items-center gap-1 text-sm">
              <span className="font-semibold text-brand">{best.rating.toFixed(1)}</span>
              <Stars value={best.rating} />
              {best.rating_count ? <span className="text-ink-soft">{best.rating_count.toLocaleString("en-IN")} ratings</span> : null}
              <span className="text-xs text-ink-soft">· via Google Shopping</span>
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="tabular text-4xl font-bold">{formatINR(d.summary.lowest_verified_price)}</span>
            {best?.mrp && best.price && best.mrp > best.price ? (
              <>
                <span className="tabular text-lg text-ink-soft line-through">{formatINR(best.mrp)}</span>
                <span className="w-full text-sm font-semibold text-success">
                  {Math.round(((best.mrp - best.price) / best.mrp) * 100)}% off MRP (store-reported)
                </span>
              </>
            ) : null}
          </div>
          {d.summary.lowest_verified_price === null && (
            d.summary.last_known ? (
              <p className="mt-1 text-sm text-ink-soft" data-testid="last-known">
                No current price. <span className="text-warning">Last seen {formatINR(d.summary.last_known.price)} at {d.summary.last_known.retailer} on {d.summary.last_known.date} ({d.summary.last_known.age})</span> – not re-confirmed since. Press “Check prices now” to get today's price.
              </p>
            ) : <p className="mt-1 text-sm text-ink-soft">No current verified price from a trusted store.</p>
          )}
          {best && <StockLine availability={best.availability} />}
          <ShareRow title={p.title} price={d.summary.lowest_verified_price} />
          <div className="mt-2"><CompareButton size="md" item={{ id: p.id, title: p.title, image_url: p.image_url, category: p.category }} /></div>
          <p className="mt-1 text-xs text-ink-soft">
            Checked {formatDateTime(p.last_verified_at)}
            {d.refresh_in_progress && <span className="ml-2 inline-flex items-center gap-1 text-brand"><Loader2 className="h-3 w-3 animate-spin" aria-hidden /> checking stores…</span>}
          </p>

          {best && safeHref(best.product_url) && (
            <a href={safeHref(best.product_url)!} target="_blank" rel="noopener noreferrer nofollow sponsored" data-testid="main-buy"
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl btn-gloss bg-accent-strong py-3.5 text-lg font-bold text-white shadow-lg shadow-accent/20 hover:brightness-110">
              {best.link_type === "exact_listing" ? `Buy on ${best.retailer}` : `See ${best.retailer} offer`}
              <ExternalLink className="h-5 w-5" aria-hidden />
            </a>
          )}
          {best && best.link_type !== "exact_listing" && (
            <p className="mt-1.5 text-xs text-ink-soft">This store's link opens its Google Shopping page – the store did not provide a direct product link.</p>
          )}

          <Variants d={d} />

          <div className="mt-5 flex flex-wrap gap-2">
            <button onClick={() => watch.mutate()} disabled={watch.isPending || watch.isSuccess}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium hover:bg-surface-2 disabled:opacity-60">
              <Eye className="h-4 w-4" aria-hidden /> {watch.isSuccess ? "On your watchlist" : "Add to watchlist"}
            </button>
            <button onClick={() => refresh.mutate()} disabled={refresh.isPending}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium hover:bg-surface-2 disabled:opacity-60">
              <RefreshCw className={`h-4 w-4 ${refresh.isPending ? "animate-spin" : ""}`} aria-hidden /> Check prices now
            </button>
          </div>
          {watch.isError && <p className="mt-2 text-sm text-danger">{(watch.error as Error).message}</p>}
          {refresh.isError && <p className="mt-2 text-sm text-danger">{(refresh.error as Error).message}</p>}
          {refresh.data && <div className="mt-3"><ProviderStrip runs={refresh.data.providers} /></div>}

          <AtAGlance d={d} />
        </div>

        <DealPanel d={d} productId={id} best={best} />
      </div>

      {/* ---------- decision ---------- */}
      <DecisionCard d={d} />

      {/* ---------- regret shield ---------- */}
      <RegretShieldCard productId={id} version={p.last_verified_at} bestRetailer={best?.retailer ?? null} bestPrice={best?.price ?? null} />

      {/* ---------- price history ---------- */}
      <PriceHistoryChart productId={id} version={p.last_verified_at} />

      {/* ---------- sellers ---------- */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-5">
          <div>
            <h2 className="text-xl font-bold">Compare {offerList.length} available {offerList.length === 1 ? "price" : "prices"}</h2>
            <p className="text-sm text-ink-soft">
              {d.summary.verified_offer_count} verified {d.summary.verified_offer_count === 1 ? "offer" : "offers"}
              {d.summary.price_difference !== null && <> · {formatINR(d.summary.price_difference)} between cheapest and dearest</>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={includeRefurb} onChange={(e) => setIncludeRefurb(e.target.checked)} /> Include refurbished
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={allStores} onChange={(e) => setAllStores(e.target.checked)} /> Show all stores
            </label>
            <select aria-label="Sort offers" value={sort} onChange={(e) => setSort(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5">
              {OFFER_SORTS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
            </select>
          </div>
        </div>
        {offerList.length >= 2 && <div className="border-b border-line p-5"><StorePriceChart offers={offerList} /></div>}
        {offerList.length === 0 ? (
          <p className="p-6 text-sm text-ink-soft">
            {hiddenUntrusted > 0
              ? `No trusted store offers this product right now. ${hiddenUntrusted} offer(s) from other stores are hidden – tick “Show all stores” to see them.`
              : "No offers recorded for this product."}
          </p>
        ) : <OfferTable offers={offerList} />}
        <div className="space-y-1 border-t border-line p-4 text-xs text-ink-soft">
          {offerList.length > 0 && hiddenUntrusted > 0 && <p>{hiddenUntrusted} offer(s) from stores not on the trusted list are hidden.</p>}
          <p>{d.summary.shipping_note}</p>
          <p>“Lowest verified” is given only to a trusted store whose offer is verified, matched to this exact variant, not out of stock and not stale. Trusted stores are established Indian retailers and official brand stores; individual marketplace sellers are not vetted.</p>
          <p>{d.affiliate_disclosure}</p>
        </div>
      </Card>

      <FinalPriceCalculator productId={id} initial={d.final_price} />

      <ReviewsSection r={d.reviews} />

      {d.similar.length > 0 && <SimilarProducts items={d.similar} />}

      {specs.length > 0 && (
        <Card className="p-5">
          <h2 className="mb-3 text-xl font-bold">Specifications</h2>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {specs.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4 border-b border-line/60 pb-1.5"><dt className="text-ink-soft">{k}</dt><dd className="text-right font-medium">{v}</dd></div>
            ))}
          </dl>
          <p className="mt-2 text-xs text-ink-soft">Derived from store listing titles and provider data.</p>
        </Card>
      )}
    </div>
  );
}

/** Compact key facts under the photo (the full list stays in "Specifications" further down). */
function KeySpecs({ specs }: { specs: [string, string][] }) {
  const top = specs.filter(([k]) => k !== "Category").slice(0, 6);
  if (top.length === 0) return null;
  return (
    <Card className="p-4" data-testid="key-specs">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-soft">Key specs</p>
      <dl className="grid grid-cols-2 gap-2">
        {top.map(([k, v]) => (
          <div key={k} className="rounded-xl bg-white/50 px-3 py-2 ring-1 ring-white/70">
            <dt className="text-[11px] text-ink-soft">{k}</dt>
            <dd className="truncate text-sm font-semibold" title={v}>{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** Real numbers only: deal score, trusted stores compared, lowest price seen, and the cheapest few stores with
 *  their own links. Fills the space beside the (taller) deal panel. */
function AtAGlance({ d }: { d: ProductDetail }) {
  const stores = d.offers.filter((o) => o.eligible_for_best_price && o.price !== null)
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0)).slice(0, 4);
  const lowestSeen = d.timing?.stats?.lowest ?? null;
  const tiles: [string, string, string][] = [
    ["Deal score", d.deal.score !== null ? `${d.deal.score}/100` : "—", d.deal.score !== null ? d.deal.label : "Needs 2 days of checks"],
    ["Stores compared", String(d.summary.verified_offer_count), d.summary.verified_offer_count === 1 ? "trusted store" : "trusted stores"],
    ["Lowest seen", lowestSeen !== null ? formatINR(lowestSeen) : "—", "by BuyWise"],
  ];
  return (
    <div className="mt-6 space-y-3" data-testid="at-a-glance">
      <div className="grid grid-cols-3 gap-2">
        {tiles.map(([label, value, sub], i) => (
          <div key={label} className={`liquid relative rounded-2xl px-3 py-3 text-center ${i === 0 ? "ring-1 ring-sun/60" : ""}`}>
            <p className="text-[11px] font-medium text-ink-soft">{label}</p>
            <p className="tabular text-lg font-bold leading-tight">{value}</p>
            <p className="truncate text-[11px] text-ink-soft">{sub}</p>
          </div>
        ))}
      </div>
      {stores.length > 0 && (
        <Card className="p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-soft">Stores at a glance</p>
          <ul className="space-y-1.5">
            {stores.map((o) => {
              const href = safeHref(o.product_url);
              return (
                <li key={o.offer_id} className={`flex items-center gap-3 rounded-xl px-2.5 py-2 ${o.is_best_price ? "bg-sun-soft ring-1 ring-sun/60" : "bg-white/40"}`}>
                  <StoreLogo name={o.retailer} url={o.product_url} size={28} />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{o.retailer}</span>
                  <span className="tabular text-sm font-bold">{formatINR(o.price)}</span>
                  <span className={`w-14 text-right text-xs ${o.is_best_price ? "font-semibold text-success" : "text-ink-soft"}`}>
                    {o.is_best_price ? "Lowest" : o.vs_best_pct == null ? "" : Math.abs(o.vs_best_pct) < 0.05 ? "Same" : `+${o.vs_best_pct.toFixed(1)}%`}
                  </span>
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer nofollow sponsored" aria-label={`Open ${o.retailer}`}
                      className="grid h-7 w-7 place-items-center rounded-lg text-brand hover:bg-accent-soft"><ExternalLink className="h-4 w-4" /></a>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Gallery({ d }: { d: ProductDetail }) {
  const images = [...new Set([d.product.image_url, ...d.offers.map((o) => o.image_url)].filter((x): x is string => !!x))].slice(0, 6);
  const [sel, setSel] = useState(0);
  const main = images[sel] ?? null;
  return (
    <div>
      <Card className="flex aspect-square items-center justify-center p-6">
        <ProductImage src={main} alt={d.product.title} className="h-full w-full" />
      </Card>
      {images.length > 1 && (
        <div className="mt-3 flex gap-2 overflow-x-auto">
          {images.map((src, i) => (
            <button key={src} onClick={() => setSel(i)} aria-label={`Image ${i + 1}`}
              className={`img-well h-16 w-16 shrink-0 border-2 p-1 ${i === sel ? "border-accent" : "border-line"}`}>
              <img src={src} alt="" referrerPolicy="no-referrer" className="h-full w-full object-contain" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Stars({ value }: { value: number }) {
  return (
    <span className="flex" aria-label={`${value.toFixed(1)} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={`h-4 w-4 ${value >= i - 0.25 ? "fill-brand text-brand" : value >= i - 0.75 ? "fill-brand/40 text-brand" : "text-ink-soft"}`} aria-hidden />
      ))}
    </span>
  );
}

function StockLine({ availability }: { availability: Offer["availability"] }) {
  const map = {
    in_stock: ["text-success", "In stock"],
    out_of_stock: ["text-danger", "Currently out of stock"],
    preorder: ["text-warning", "Pre-order"],
    unknown: ["text-ink-soft", "Stock status not reported by the store"],
  } as const;
  const [cls, text] = map[availability];
  return <p className={`mt-2 text-sm font-medium ${cls}`}>{text}</p>;
}

/** Size / colour chips. Other options link to other variants BuyWise has actually tracked. */
function Variants({ d }: { d: ProductDetail }) {
  const p = d.product;
  const v = d.variants;
  if (!v.length || (!p.storage_gb && !p.colour)) return null;
  const sizes = new Map<number, number>();
  for (const x of v) if (x.storage_gb && x.storage_gb !== p.storage_gb && (!sizes.has(x.storage_gb) || x.colour === p.colour)) sizes.set(x.storage_gb, x.id);
  const colours = new Map<string, number>();
  for (const x of v) if (x.colour && x.colour !== p.colour && (!colours.has(x.colour) || x.storage_gb === p.storage_gb)) colours.set(x.colour, x.id);
  const chip = "flex min-w-[100px] flex-col items-center gap-1.5 rounded-xl border-2 px-4 py-2.5 text-sm font-semibold";
  const img = (src: string | null) => src
    ? <img src={src} alt="" referrerPolicy="no-referrer" className="img-well h-10 w-10 rounded-full object-contain p-0.5" />
    : <span className="h-10 w-10 rounded-full bg-surface-2" aria-hidden />;
  const imgOf = (vid: number) => v.find((x) => x.id === vid)?.image_url ?? null;
  return (
    <div className="mt-6 space-y-4" data-testid="variants">
      {p.storage_gb && sizes.size > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Size</p>
          <div className="flex flex-wrap gap-2">
            <span className={`${chip} border-brand bg-brand-soft`}>{img(p.image_url)}{storageLabel(p.storage_gb)}</span>
            {[...sizes.entries()].sort((a, b) => a[0] - b[0]).map(([gb, vid]) => (
              <Link key={gb} to={`/product/${vid}`} className={`${chip} border-line bg-surface hover:border-brand`}>{img(imgOf(vid))}{storageLabel(gb)}</Link>
            ))}
          </div>
        </div>
      )}
      {p.colour && colours.size > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Colour</p>
          <div className="flex flex-wrap gap-2">
            <span className={`${chip} border-brand bg-brand-soft`}>{img(p.image_url)}{capitalize(p.colour)}</span>
            {[...colours.entries()].map(([c, vid]) => (
              <Link key={c} to={`/product/${vid}`} className={`${chip} border-line bg-surface hover:border-brand`}>{img(imgOf(vid))}{capitalize(c)}</Link>
            ))}
          </div>
        </div>
      )}
      <p className="text-xs text-ink-soft">Options shown are other variants BuyWise has already found prices for.</p>
    </div>
  );
}

function ShareRow({ title, price }: { title: string; price: number | null }) {
  const [copied, setCopied] = useState(false);
  const url = typeof window !== "undefined" ? window.location.href : "";
  const text = `${title}${price ? ` – ${formatINR(price)}` : ""} on BuyWise: ${url}`;
  return (
    <div className="mt-3 inline-flex items-center gap-3 rounded-full border border-line bg-surface px-4 py-1.5 text-sm">
      <span className="text-ink-soft">Share on</span>
      <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noopener noreferrer" aria-label="Share on WhatsApp"
        className="grid h-7 w-7 place-items-center rounded-full bg-[#25d366] text-white">
        <MessageCircle className="h-4 w-4" aria-hidden />
      </a>
      <span className="h-5 w-px bg-line" aria-hidden />
      <button type="button" aria-label="Copy link" onClick={async () => {
        try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked */ }
      }} className="inline-flex items-center gap-1 text-ink hover:text-brand">
        {copied ? <Check className="h-4 w-4 text-success" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
        {copied ? "Copied" : ""}
      </button>
    </div>
  );
}

function SimilarProducts({ items }: { items: ProductDetail["similar"] }) {
  return (
    <section data-testid="similar">
      <h2 className="flex items-center gap-2 text-xl font-bold">Similar products <Sparkles className="h-5 w-5 text-brand" aria-hidden /></h2>
      <p className="mb-3 text-sm text-ink-soft">
        {items.length} similar product{items.length === 1 ? "" : "s"} BuyWise has found, starting at <strong className="text-success">{formatINR(Math.min(...items.map((i) => i.best_price)))}</strong>
      </p>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {items.map((it) => {
          const href = safeHref(it.buy_url);
          return (
            <Card key={it.id} className="lift flex flex-col p-3">
              <Link to={`/product/${it.id}`} className="relative block">
                <ProductImage src={it.image_url} alt={it.title} className="h-36 w-full" />
                <span className="absolute bottom-0 left-0"><StoreLogo name={it.retailer} size={28} /></span>
              </Link>
              <Link to={`/product/${it.id}`} className="mt-2 line-clamp-2 text-sm font-medium hover:text-brand">{it.title}</Link>
              <p className="mt-1 tabular text-lg font-bold">{formatINR(it.best_price)}</p>
              {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer nofollow sponsored"
                  className="mt-auto rounded-lg bg-brand-soft py-2 text-center text-sm font-semibold text-brand hover:bg-brand/20">
                  {it.link_type === "exact_listing" ? "Buy now" : "View offer"}
                </a>
              ) : null}
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function ProductSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-3" aria-busy="true">
      <Skeleton className="aspect-square w-full" />
      <div className="space-y-3"><Skeleton className="h-6 w-24" /><Skeleton className="h-8 w-full" /><Skeleton className="h-10 w-40" /><Skeleton className="h-12 w-full" /></div>
      <Skeleton className="h-80 w-full" />
    </div>
  );
}

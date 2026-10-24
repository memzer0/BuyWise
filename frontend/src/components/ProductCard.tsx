import { ImageOff, Store, TrendingDown, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import type { ProductSummary } from "../types/api";
import { capitalize, formatINR } from "../utils/format";
import { CompareButton } from "./compare/CompareButton";
import { Badge, Card, FreshnessBadge } from "./ui";

const MISMATCH: Record<string, string> = { model: "model", variant: "variant", storage: "storage", accessory: "item (accessory)" };

export function ProductImage({ src, alt, className = "" }: { src: string | null; alt: string; className?: string }) {
  if (!src) {
    return (
      <div className={`flex items-center justify-center rounded-xl bg-surface-2 text-ink-soft ${className}`} aria-label="No image supplied by provider">
        <ImageOff className="h-8 w-8" aria-hidden />
      </div>
    );
  }
  return <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" className={`img-well object-contain p-2 ${className}`} />;
}

export function ProductCard({ p }: { p: ProductSummary }) {
  const chips = [p.storage_gb && `${p.storage_gb >= 1024 ? p.storage_gb / 1024 + " TB" : p.storage_gb + " GB"}`,
    p.ram_gb && `${p.ram_gb} GB RAM`, p.colour && capitalize(p.colour)].filter(Boolean) as string[];
  return (
    <Card className="lift group relative flex h-full flex-col overflow-hidden">
      <div className="absolute right-2 top-2 z-10"><CompareButton item={{ id: p.id, title: p.title, image_url: p.image_url, category: p.category }} /></div>
      <Link to={`/product/${p.id}`} className="flex h-full flex-col" data-testid="product-card">
        <div className="p-3">
          <ProductImage src={p.image_url} alt={p.title} className="mx-auto h-40 w-full" />
        </div>
        <div className="flex flex-1 flex-col gap-2 border-t border-line p-4">
          <div className="flex flex-wrap items-center gap-1.5">
            {p.brand && <span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">{p.brand}</span>}
            {p.condition !== "new" && <Badge tone="amber">{capitalize(p.condition)}</Badge>}
            {p.query_mismatches && p.query_mismatches.length > 0 && (
              <Badge tone="slate" title="This product differs from what you searched for">
                Different {p.query_mismatches.map((m) => MISMATCH[m] ?? m).join(", ")}
              </Badge>
            )}
          </div>
          <h3 className="line-clamp-2 text-sm font-medium leading-snug group-hover:text-brand">{p.title}</h3>
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {chips.map((c) => <span key={c} className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-soft">{c}</span>)}
            </div>
          )}
          {p.preferred_stores.length > 0 && (
            <p className="text-[11px] text-ink-soft">At {p.preferred_stores.join(", ")}</p>
          )}
          <div className="mt-auto pt-2">
            {p.best_price !== null ? (
              <>
                <p className="text-xs text-ink-soft">Lowest verified price</p>
                <div className="flex items-baseline gap-2">
                  <p className="tabular text-xl font-bold">{formatINR(p.best_price)}</p>
                  {p.price_change !== null && p.price_change !== 0 && (
                    <span data-testid="price-change"
                      title={`Previously ${formatINR(p.previous_price)} at this store`}
                      className={`inline-flex items-center gap-0.5 text-xs font-semibold ${p.price_change < 0 ? "text-success" : "text-danger"}`}>
                      {p.price_change < 0 ? <TrendingDown className="h-3 w-3" aria-hidden /> : <TrendingUp className="h-3 w-3" aria-hidden />}
                      {formatINR(Math.abs(p.price_change))}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 flex items-center gap-1 text-xs text-ink-soft">
                  <Store className="h-3 w-3" aria-hidden /> {p.best_retailer}
                  {p.verified_offer_count > 1 ? ` · ${p.verified_offer_count} sellers compared` : " · 1 seller"}
                </p>
              </>
            ) : (
              <p className="text-sm text-ink-soft">No current verified price</p>
            )}
            <div className="mt-2"><FreshnessBadge status={p.best_freshness ?? "unavailable"} at={p.last_verified_at} /></div>
          </div>
        </div>
      </Link>
    </Card>
  );
}

export function ProductGridSkeleton({ n = 8 }: { n?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" aria-busy="true" aria-label="Loading results">
      {Array.from({ length: n }).map((_, i) => (
        <Card key={i} className="p-4">
          <div className="mx-auto h-40 w-full animate-pulse rounded bg-surface-2" />
          <div className="mt-4 h-3 w-1/3 animate-pulse rounded bg-surface-2" />
          <div className="mt-2 h-4 w-full animate-pulse rounded bg-surface-2" />
          <div className="mt-6 h-6 w-1/2 animate-pulse rounded bg-surface-2" />
        </Card>
      ))}
    </div>
  );
}

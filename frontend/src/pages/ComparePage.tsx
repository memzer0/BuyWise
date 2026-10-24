import { useQuery } from "@tanstack/react-query";
import { ChevronRight, GitCompareArrows, Info, Sparkles, Star, Trophy, X } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { compareList } from "../components/compare/compareStore";
import { ProductImage } from "../components/ProductCard";
import { Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import type { CompareColumn } from "../types/api";
import { capitalize, formatINR, safeHref } from "../utils/format";

type Better = "low" | "high" | null;
interface Row { key: string; label: string; group: string; value: (c: CompareColumn) => ReactNode; raw: (c: CompareColumn) => unknown; better?: Better }

const storage = (gb: number | null) => (gb ? (gb >= 1024 && gb % 1024 === 0 ? `${gb / 1024} TB` : `${gb} GB`) : null);
const AVAIL: Record<string, string> = { in_stock: "In stock", out_of_stock: "Out of stock", preorder: "Pre-order", unknown: "Not reported" };
const dash = <span className="text-ink-soft">—</span>;

function rows(cols: CompareColumn[]): Row[] {
  const specKeys = [...new Set(cols.flatMap((c) => Object.keys(c.specs ?? {})))];
  return [
    { key: "price", group: "Price", label: "Lowest verified price", better: "low", raw: (c) => c.price,
      value: (c) => c.price != null ? <strong className="tabular text-lg">{formatINR(c.price)}</strong>
        : c.last_known ? <span className="text-xs text-warning">Last seen {formatINR(c.last_known.price)} ({c.last_known.age})</span> : dash },
    { key: "store", group: "Price", label: "Cheapest store", raw: (c) => c.best_store, value: (c) => c.best_store ?? dash },
    { key: "stores", group: "Price", label: "Trusted stores compared", better: "high", raw: (c) => c.store_count || null, value: (c) => c.store_count || dash },
    { key: "stock", group: "Price", label: "Availability", raw: (c) => c.availability, value: (c) => (c.availability ? AVAIL[c.availability] : dash) },
    { key: "hist_low", group: "Price", label: "Lowest price seen", better: "low", raw: (c) => c.history.lowest, value: (c) => (c.history.lowest != null ? formatINR(c.history.lowest) : dash) },
    { key: "hist_avg", group: "Price", label: "Average price", raw: (c) => c.history.average, value: (c) => (c.history.average != null ? formatINR(c.history.average) : dash) },
    { key: "deal", group: "BuyWise verdict", label: "Deal score", better: "high", raw: (c) => c.deal_score,
      value: (c) => (c.deal_score != null ? <span><strong>{c.deal_score}</strong>/100 <span className="text-xs text-ink-soft">{c.deal_label}</span></span> : <span className="text-xs text-ink-soft">{c.deal_label ?? "—"}</span>) },
    { key: "score", group: "BuyWise verdict", label: "BuyWise Score", better: "high", raw: (c) => c.buywise_score, value: (c) => (c.buywise_score != null ? `${c.buywise_score}/100` : dash) },
    { key: "decision", group: "BuyWise verdict", label: "Decision", raw: (c) => c.decision.label,
      value: (c) => <span title={c.decision.headline}>{c.decision.label}</span> },
    { key: "rating", group: "Reviews", label: "Rating", better: "high", raw: (c) => c.rating,
      value: (c) => (c.rating != null ? <span className="inline-flex items-center gap-1"><strong>{c.rating.toFixed(1)}</strong><Star className="h-3.5 w-3.5 fill-warning text-warning" aria-hidden />
        {c.ratings_count ? <span className="text-xs text-ink-soft">({c.ratings_count.toLocaleString("en-IN")})</span> : null}</span> : dash) },
    { key: "praised", group: "Reviews", label: "Reviewers praise", raw: (c) => c.praised.join(","),
      value: (c) => (c.praised.length ? <span className="text-success">{c.praised.join(", ")}</span> : dash) },
    { key: "complaints", group: "Reviews", label: "Common complaints", raw: (c) => c.complaints.join(","),
      value: (c) => (c.complaints.length ? <span className="text-danger">{c.complaints.join(", ")}</span> : dash) },
    { key: "brand", group: "Specs", label: "Brand", raw: (c) => c.brand, value: (c) => capitalize(c.brand) || dash },
    { key: "storage", group: "Specs", label: "Storage", raw: (c) => c.storage_gb, value: (c) => storage(c.storage_gb) ?? dash },
    { key: "ram", group: "Specs", label: "RAM", raw: (c) => c.ram_gb, value: (c) => (c.ram_gb ? `${c.ram_gb} GB` : dash) },
    { key: "screen", group: "Specs", label: "Screen", raw: (c) => c.screen_inches, value: (c) => (c.screen_inches ? `${c.screen_inches}"` : dash) },
    { key: "colour", group: "Specs", label: "Colour", raw: (c) => c.colour, value: (c) => capitalize(c.colour) || dash },
    { key: "condition", group: "Specs", label: "Condition", raw: (c) => c.condition, value: (c) => capitalize(c.condition) },
    ...specKeys.map((k): Row => ({ key: `spec:${k}`, group: "Specs", label: k, raw: (c) => c.specs?.[k], value: (c) => c.specs?.[k] ?? dash })),
  ];
}

function bestIds(row: Row, cols: CompareColumn[]): Set<number> {
  if (!row.better) return new Set();
  const vals = cols.map((c) => ({ id: c.id, v: row.raw(c) })).filter((x): x is { id: number; v: number } => typeof x.v === "number");
  if (vals.length < 2) return new Set();
  const target = row.better === "low" ? Math.min(...vals.map((x) => x.v)) : Math.max(...vals.map((x) => x.v));
  const winners = vals.filter((x) => x.v === target);
  return winners.length === vals.length ? new Set() : new Set(winners.map((x) => x.id));
}

export function ComparePage() {
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const [diffOnly, setDiffOnly] = useState(false);
  const ids = (sp.get("ids") ?? "").split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0);
  const q = useQuery({ queryKey: ["compare", ids.join(",")], queryFn: ({ signal }) => api.compare(ids, signal), enabled: ids.length >= 2 });

  const removeCol = (id: number) => {
    compareList.remove(id);
    const left = ids.filter((x) => x !== id);
    navigate(left.length ? `/compare?ids=${left.join(",")}` : "/compare", { replace: true });
  };

  if (ids.length < 2) {
    return (
      <EmptyState title="Pick at least 2 products to compare">
        Search for products and press <strong>Compare</strong> on each product card (or on a product page). The products you pick
        appear in the bar at the bottom left – press <strong>Compare</strong> there to see them side by side.
      </EmptyState>
    );
  }
  if (q.isPending) return <Skeleton className="h-96 w-full" />;
  if (q.isError) return <ErrorState title="Couldn't load the comparison" message={(q.error as Error).message} onRetry={() => q.refetch()} />;

  const cols = q.data.products;
  if (cols.length < 2) {
    return <EmptyState title="Not enough products to compare">Some of the chosen products no longer exist. Pick at least 2 products again.</EmptyState>;
  }
  const all = rows(cols);
  const shown = diffOnly ? all.filter((r) => new Set(cols.map((c) => JSON.stringify(r.raw(c) ?? null))).size > 1) : all;
  const groups = [...new Set(shown.map((r) => r.group))];
  const s = q.data.summary;
  const titleOf = (id: number) => cols.find((c) => c.id === id)?.title ?? "";

  return (
    <div className="space-y-6" data-testid="compare-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold"><GitCompareArrows className="h-6 w-6 text-brand" aria-hidden /> Compare {cols.length} products</h1>
          <p className="text-sm text-ink-soft">From prices and reviews BuyWise has already checked – comparing doesn't use any searches.</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)} /> Show only differences
        </label>
      </div>

      {s && (
        <Card className="p-5" data-testid="compare-summary">
          <h2 className="flex items-center gap-2 text-lg font-bold"><Sparkles className="h-5 w-5 text-brand" aria-hidden /> Summary</h2>
          {s.overall && <p className="mt-2 flex items-start gap-2 font-semibold"><Trophy className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />{s.overall}</p>}
          {s.highlights.length > 0 && (
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {s.highlights.map((h) => (
                <li key={h.key} className="rounded-xl border border-line bg-surface-2/40 p-3 text-sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-brand">{h.label}</p>
                  <p className="mt-0.5">{h.text}</p>
                  <Link to={`/product/${h.product_id}`} className="mt-1 inline-flex items-center text-xs text-brand hover:underline" title={titleOf(h.product_id)}>
                    View product <ChevronRight className="h-3 w-3" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {s.differences.length > 0 && (
            <div className="mt-4">
              <p className="text-sm font-semibold">Key differences</p>
              <ul className="mt-1 space-y-1 text-sm">{s.differences.map((d) => <li key={d}>• {d}</li>)}</ul>
            </div>
          )}
          {s.notes.length > 0 && (
            <ul className="mt-3 space-y-0.5 text-xs text-ink-soft">
              {s.notes.map((n) => <li key={n} className="flex items-start gap-1.5"><Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{n}</li>)}
            </ul>
          )}
        </Card>
      )}

      <Card className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm" data-testid="compare-table">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 w-40 bg-surface p-3 text-left align-bottom text-xs font-semibold uppercase tracking-wide text-ink-soft">Product</th>
              {cols.map((c) => {
                const href = safeHref(c.best_url);
                return (
                  <th key={c.id} className="min-w-[180px] p-3 text-left align-top font-normal">
                    <div className="relative">
                      <button type="button" onClick={() => removeCol(c.id)} aria-label={`Remove ${c.title}`}
                        className="absolute right-0 top-0 rounded-full p-1 text-ink-soft hover:bg-surface-2 hover:text-ink"><X className="h-4 w-4" /></button>
                      <ProductImage src={c.image_url} alt={c.title} className="h-28 w-full" />
                      <Link to={`/product/${c.id}`} className="mt-2 line-clamp-2 block font-medium hover:text-brand">{c.title}</Link>
                      {href && (
                        <a href={href} target="_blank" rel="noopener noreferrer nofollow sponsored"
                          className="mt-2 inline-flex items-center gap-1 rounded-lg btn-gloss bg-accent-strong px-3 py-1 text-xs font-semibold text-white">
                          {c.best_link_type === "exact_listing" ? `Buy on ${c.best_store}` : `See ${c.best_store} offer`} <ChevronRight className="h-3 w-3" aria-hidden />
                        </a>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <GroupRows key={g} group={g} rows={shown.filter((r) => r.group === g)} cols={cols} />
            ))}
            {shown.length === 0 && (
              <tr><td colSpan={cols.length + 1} className="p-4 text-center text-ink-soft">These products don't differ on any compared detail.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
      <p className="text-xs text-ink-soft">Green marks the best value in a row where products differ. Prices change often – confirm on the store's page before buying.</p>
    </div>
  );
}

function GroupRows({ group, rows: rs, cols }: { group: string; rows: Row[]; cols: CompareColumn[] }) {
  return (
    <>
      <tr><th colSpan={cols.length + 1} className="bg-surface-2/60 px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-ink-soft">{group}</th></tr>
      {rs.map((r) => {
        const best = bestIds(r, cols);
        return (
          <tr key={r.key} className="border-t border-line" data-testid={`row-${r.key}`}>
            <th scope="row" className="sticky left-0 z-10 bg-surface p-3 text-left text-xs font-medium text-ink-soft">{r.label}</th>
            {cols.map((c) => (
              <td key={c.id} className={`p-3 align-top ${best.has(c.id) ? "bg-success/10 font-semibold text-success" : ""}`} data-best={best.has(c.id) || undefined}>
                {r.value(c)}
              </td>
            ))}
          </tr>
        );
      })}
    </>
  );
}

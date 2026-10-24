import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { ProductCard, ProductGridSkeleton } from "../components/ProductCard";
import { EmptyState, ErrorState, ProviderStrip } from "../components/ui";
import type { SearchParams } from "../types/api";
import { CATEGORY_LABELS, capitalize, formatDateTime } from "../utils/format";

const SORTS: { v: NonNullable<SearchParams["sort"]>; label: string }[] = [
  { v: "relevance", label: "Relevance" },
  { v: "price_asc", label: "Price: low to high" },
  { v: "price_desc", label: "Price: high to low" },
  { v: "offers", label: "Most sellers" },
];

function num(v: string | null): number | undefined {
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

export function SearchPage() {
  const [sp, setSp] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const q = sp.get("q")?.trim() ?? "";
  const params: SearchParams = {
    q,
    category: sp.get("category") || undefined,
    brand: sp.getAll("brand"),
    min_price: num(sp.get("min_price")),
    max_price: num(sp.get("max_price")),
    storage_gb: num(sp.get("storage_gb")),
    ram_gb: num(sp.get("ram_gb")),
    condition: (sp.get("condition") as SearchParams["condition"]) || "new",
    include_accessories: sp.get("include_accessories") === "true" || undefined,
    all_stores: sp.get("all_stores") === "true" || undefined,
    sort: (sp.get("sort") as SearchParams["sort"]) || "relevance",
    page: num(sp.get("page")) || 1,
    page_size: 20,
  };

  const query = useQuery({
    queryKey: ["search", params],
    queryFn: ({ signal }) => api.search(params, signal),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: (count, err) => !(err instanceof ApiError && err.status < 500 && err.status !== 0) && count < 1,
  });

  function update(changes: Record<string, string | string[] | undefined>) {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(changes)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v !== undefined && v !== "") next.set(k, v);
    }
    if (!("page" in changes)) next.delete("page");
    setSp(next);
  }

  if (q.length < 2) {
    return <EmptyState title="Search for a product">Type at least two characters, for example “Galaxy S24 256GB” or “Sony WH-1000XM5”.</EmptyState>;
  }

  const d = query.data;
  const activeFilters = ["category", "brand", "min_price", "max_price", "storage_gb", "ram_gb", "include_accessories", "all_stores"].some((k) => sp.get(k)) || params.condition !== "new";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Results for “{q}”</h1>
          {d && (
            <p className="text-sm text-ink-soft" data-testid="result-count">
              {d.total} product{d.total === 1 ? "" : "s"} · {d.source === "cache" ? `cached results from ${formatDateTime(d.fetched_at)}` : "fetched live just now"}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm lg:hidden" onClick={() => setShowFilters((s) => !s)}>
            <SlidersHorizontal className="h-4 w-4" aria-hidden /> Filters
          </button>
          <label className="text-sm text-ink-soft" htmlFor="sort">Sort</label>
          <select id="sort" value={params.sort} onChange={(e) => update({ sort: e.target.value })} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
            {SORTS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
          </select>
        </div>
      </div>

      {d && <ProviderStrip runs={d.providers} />}
      {d && (d.hidden_accessories > 0 || d.hidden_untrusted > 0) && (
        <p className="rounded-lg border border-line bg-surface p-3 text-sm text-ink-soft" role="status" data-testid="hidden-notice">
          Hidden:{" "}
          {d.hidden_accessories > 0 && <>{d.hidden_accessories} accessor{d.hidden_accessories === 1 ? "y" : "ies"} (cases, covers, etc.)</>}
          {d.hidden_accessories > 0 && d.hidden_untrusted > 0 && " · "}
          {d.hidden_untrusted > 0 && <>{d.hidden_untrusted} product{d.hidden_untrusted === 1 ? "" : "s"} sold only by stores not on the trusted list</>}
          . Use the filters to show them.
        </p>
      )}
      {d?.partial && !d.all_providers_failed && (
        <p className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning" role="status">
          Partial results: some data providers failed for this search. Offers from those sources are missing.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        <aside className={`${showFilters ? "block" : "hidden"} lg:block`} aria-label="Filters">
          {d && (
            <div className="space-y-5 rounded-xl border border-line bg-surface p-4 text-sm">
              {activeFilters && (
                <button className="flex items-center gap-1 text-brand" onClick={() => update({ category: undefined, brand: [], min_price: undefined, max_price: undefined, storage_gb: undefined, ram_gb: undefined, condition: undefined, include_accessories: undefined, all_stores: undefined })}>
                  <X className="h-3.5 w-3.5" aria-hidden /> Clear filters
                </button>
              )}
              <FilterGroup title="Category">
                <select aria-label="Category" value={params.category ?? ""} onChange={(e) => update({ category: e.target.value })} className="w-full rounded-lg border border-line px-2 py-1.5">
                  <option value="">All categories</option>
                  {[...new Set([...d.facets.categories, ...(params.category ? [params.category] : [])])].map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c] ?? c}</option>)}
                </select>
              </FilterGroup>
              {d.facets.brands.length > 0 && (
                <FilterGroup title="Brand">
                  {d.facets.brands.map((b) => (
                    <label key={b} className="flex items-center gap-2 py-0.5">
                      <input type="checkbox" checked={params.brand?.includes(b) ?? false}
                        onChange={(e) => update({ brand: e.target.checked ? [...(params.brand ?? []), b] : (params.brand ?? []).filter((x) => x !== b) })} />
                      {capitalize(b)}
                    </label>
                  ))}
                </FilterGroup>
              )}
              <FilterGroup title="Price (₹)">
                <PriceRange min={params.min_price} max={params.max_price} onApply={(min, max) => update({ min_price: min, max_price: max })} />
              </FilterGroup>
              {d.facets.storage_gb.length > 0 && (
                <FilterGroup title="Storage">
                  <select aria-label="Storage" value={params.storage_gb ?? ""} onChange={(e) => update({ storage_gb: e.target.value })} className="w-full rounded-lg border border-line px-2 py-1.5">
                    <option value="">Any</option>
                    {d.facets.storage_gb.map((s) => <option key={s} value={s}>{s >= 1024 ? `${s / 1024} TB` : `${s} GB`}</option>)}
                  </select>
                </FilterGroup>
              )}
              {d.facets.ram_gb.length > 0 && (
                <FilterGroup title="RAM">
                  <select aria-label="RAM" value={params.ram_gb ?? ""} onChange={(e) => update({ ram_gb: e.target.value })} className="w-full rounded-lg border border-line px-2 py-1.5">
                    <option value="">Any</option>
                    {d.facets.ram_gb.map((s) => <option key={s} value={s}>{s} GB</option>)}
                  </select>
                </FilterGroup>
              )}
              <FilterGroup title="Show">
                <label className="flex items-center gap-2 py-0.5">
                  <input type="checkbox" checked={!!params.include_accessories}
                    onChange={(e) => update({ include_accessories: e.target.checked ? "true" : undefined })} />
                  Include accessories
                </label>
                <label className="flex items-center gap-2 py-0.5">
                  <input type="checkbox" checked={!!params.all_stores}
                    onChange={(e) => update({ all_stores: e.target.checked ? "true" : undefined })} />
                  Show all stores (not only trusted)
                </label>
              </FilterGroup>
              <FilterGroup title="Condition">
                {(["new", "refurbished", "any"] as const).map((c) => (
                  <label key={c} className="flex items-center gap-2 py-0.5">
                    <input type="radio" name="condition" checked={params.condition === c} onChange={() => update({ condition: c === "new" ? undefined : c })} />
                    {c === "any" ? "New & refurbished" : capitalize(c)}
                  </label>
                ))}
              </FilterGroup>
            </div>
          )}
        </aside>

        <div>
          {query.isPending ? <ProductGridSkeleton /> : query.isError ? (
            <ErrorState title="Search failed" message={(query.error as Error).message} onRetry={() => query.refetch()} />
          ) : d!.no_providers_configured ? (
            <EmptyState title="No price providers are configured">
              BuyWise only shows real prices from retailer or shopping APIs, and none are set up on this server.
              Add at least one API key to <code>backend/.env</code> – see <Link className="text-brand underline" to="/admin">Diagnostics</Link> for the list.
            </EmptyState>
          ) : d!.all_providers_failed ? (
            <ErrorState title="All data providers failed" message="No provider returned data for this search. No prices are shown rather than guessing. Try again in a few minutes." onRetry={() => query.refetch()} />
          ) : d!.results.length === 0 && d!.hidden_untrusted > 0 ? (
            <EmptyState title="No trusted stores sell this right now">
              Found {d!.hidden_untrusted} product{d!.hidden_untrusted === 1 ? "" : "s"}, but only from stores not on the trusted list (e.g. importers or local shops).{" "}
              <button className="font-semibold text-brand underline" onClick={() => update({ all_stores: "true" })}>Show all stores</button>
            </EmptyState>
          ) : d!.results.length === 0 ? (
            <EmptyState title="No matching products">
              {d!.total === 0 && !activeFilters ? "The configured providers returned no listings for this query. Try a broader name or check the spelling." : "No products match the selected filters."}
            </EmptyState>
          ) : (
            <>
              <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 ${query.isFetching ? "opacity-60" : ""}`}>
                {d!.results.map((p) => <ProductCard key={p.id} p={p} />)}
              </div>
              {d!.total > d!.page_size && (
                <nav className="mt-6 flex items-center justify-center gap-2" aria-label="Pagination">
                  <button disabled={d!.page <= 1} onClick={() => update({ page: String(d!.page - 1) })} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm disabled:opacity-40">Previous</button>
                  <span className="text-sm text-ink-soft">Page {d!.page} of {Math.ceil(d!.total / d!.page_size)}</span>
                  <button disabled={d!.page * d!.page_size >= d!.total} onClick={() => update({ page: String(d!.page + 1) })} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm disabled:opacity-40">Next</button>
                </nav>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return <fieldset><legend className="mb-1.5 font-semibold">{title}</legend>{children}</fieldset>;
}

function PriceRange({ min, max, onApply }: { min?: number; max?: number; onApply: (min?: string, max?: string) => void }) {
  const [lo, setLo] = useState(min?.toString() ?? "");
  const [hi, setHi] = useState(max?.toString() ?? "");
  return (
    <form className="flex items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); onApply(lo || undefined, hi || undefined); }}>
      <input aria-label="Minimum price" inputMode="numeric" value={lo} onChange={(e) => setLo(e.target.value.replace(/\D/g, ""))} placeholder="Min" className="w-full rounded-lg border border-line px-2 py-1.5" />
      <input aria-label="Maximum price" inputMode="numeric" value={hi} onChange={(e) => setHi(e.target.value.replace(/\D/g, ""))} placeholder="Max" className="w-full rounded-lg border border-line px-2 py-1.5" />
      <button type="submit" className="rounded-lg border border-line px-2 py-1.5 font-medium hover:bg-surface-2">Go</button>
    </form>
  );
}

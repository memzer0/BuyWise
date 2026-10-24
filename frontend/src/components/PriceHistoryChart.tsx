import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { HistoryResponse } from "../types/api";
import { formatDateTime, formatINR } from "../utils/format";
import { Card, ErrorState, Skeleton } from "./ui";

const RANGES = [
  { key: "30d", label: "1 Month" },
  { key: "90d", label: "3 Month" },
  { key: "365d", label: "Max" },
] as const;

// Categorical order validated (CVD + normal vision) against the light surface #F7F6F1; lighter slots rely on the
// legend, tooltip and the offer table below for relief.
const STORE_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"];
const MAX_STORES = STORE_COLOURS.length;

function shortINR(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e3).toFixed(v % 1000 === 0 ? 0 : 1)}K`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(v >= 1e4 ? 1 : 2)}K`;
  return `₹${Math.round(v)}`;
}

/** A y-range that hugs the data so real price moves are visible (a ₹0 baseline flattens a ₹1,000 change on a
 *  ₹1,00,000 phone). Padding is 4 % of the price, so an unchanged price still reads as a level line. */
function yDomain(values: number[]): [number, number] {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = Math.max((hi - lo) * 0.15, hi * 0.04);
  const step = hi >= 1e5 ? 1000 : hi >= 1e4 ? 500 : 100;
  return [Math.max(0, Math.floor((lo - pad) / step) * step), Math.ceil((hi + pad) / step) * step];
}

function dateTick(t: number) {
  return new Date(t).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const tooltipStyle = {
  contentStyle: { borderRadius: 10, background: "rgb(255 255 255 / 0.92)", border: "1px solid #d9d6ca", color: "#14172b", boxShadow: "0 10px 30px -16px rgb(20 23 43 / 0.35)" },
  labelStyle: { color: "#545a70" },
};

function storeRows(h: HistoryResponse) {
  // the most-observed stores first; colour follows the store (stable order), never the rank on screen
  const stores = [...h.series].sort((a, b) => b.points.length - a.points.length || a.retailer.localeCompare(b.retailer))
    .slice(0, MAX_STORES).map((s) => s.retailer).sort();
  const rows = new Map<number, Record<string, number>>();
  for (const s of h.series) {
    if (!stores.includes(s.retailer)) continue;
    for (const pt of s.points) {
      const t = new Date(pt.observed_at).getTime();
      const key = Math.round(t / 600_000) * 600_000; // align the same price check across stores (10-min buckets)
      const row = rows.get(key) ?? { t: key };
      row[s.retailer] = pt.price;
      rows.set(key, row);
    }
  }
  return { stores, data: [...rows.values()].sort((a, b) => a.t - b.t), hidden: Math.max(0, h.series.length - stores.length) };
}

/** Price history. "Lowest price" = the lowest store price at each real price check (smooth curve, highest and lowest
 *  points marked); in Demo mode a simulated stretch before tracking began is drawn the same way.
 *  "By store" = each store's own real observed prices. */
export function PriceHistoryChart({ productId, version }: { productId: number; version?: string | null }) {
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("365d");
  const [view, setView] = useState<"lowest" | "stores">("lowest");
  const q = useQuery({
    queryKey: ["history", productId, range, version ?? null],
    queryFn: ({ signal }) => api.history(productId, range, signal),
  });

  // Demo points (secret Demo mode) are drawn exactly like real ones.
  const lowest = useMemo(
    () => (q.data?.lowest_series ?? []).map((pt) => ({ t: new Date(pt.observed_at).getTime(), price: pt.price, retailer: pt.retailer, demo: !!pt.demo })),
    [q.data],
  );
  const extremes = useMemo(() => {
    if (lowest.length < 2) return null;
    const hi = lowest.reduce((a, b) => (b.price > a.price ? b : a));
    const lo = lowest.reduce((a, b) => (b.price < a.price ? b : a));
    return hi.price === lo.price ? null : { hi, lo };
  }, [lowest]);
  // keep the Highest/Lowest labels inside the chart when the point sits near the left or right edge
  const edge = (t: number, def: "top" | "bottom"): "top" | "bottom" | "left" | "right" => {
    if (lowest.length < 2) return def;
    const f = (t - lowest[0].t) / Math.max(1, lowest[lowest.length - 1].t - lowest[0].t);
    return f > 0.85 ? "left" : f < 0.1 ? "right" : def;
  };
  const byStore = useMemo(() => (q.data ? storeRows(q.data) : null), [q.data]);
  const changed = q.data?.lowest !== null && q.data?.lowest !== q.data?.highest;

  return (
    <Card className="p-5 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-bold">Price History</h2>
        <div className="flex flex-wrap gap-2">
          <div role="tablist" aria-label="History view" className="flex rounded-full bg-white/40 p-1 ring-1 ring-white/70">
            {([["lowest", "Lowest price"], ["stores", "By store"]] as const).map(([k, label]) => (
              <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${view === k ? "liquid relative text-brand" : "text-ink hover:text-brand"}`}>
                {label}
              </button>
            ))}
          </div>
          <div role="tablist" aria-label="History range" className="flex rounded-full bg-white/40 p-1 ring-1 ring-white/70">
            {RANGES.map((r) => (
              <button key={r.key} role="tab" aria-selected={range === r.key} onClick={() => setRange(r.key)}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${range === r.key ? "liquid relative text-brand" : "text-ink hover:text-brand"}`}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {q.isPending ? <Skeleton className="h-72 w-full" /> : q.isError ? (
        <ErrorState title="Couldn't load price history" message={(q.error as Error).message} onRetry={() => q.refetch()} />
      ) : lowest.length >= 2 ? (
        <>
          <div className="h-72 w-full" data-testid="history-chart">
            <ResponsiveContainer width="100%" height="100%">
              {view === "lowest" ? (
                <AreaChart data={lowest} margin={{ top: 26, right: 16, bottom: 0, left: 4 }}>
                  <defs>
                    <linearGradient id="bwHistoryFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#1546d9" stopOpacity={0.32} />
                      <stop offset="60%" stopColor="#5b8cff" stopOpacity={0.12} />
                      <stop offset="100%" stopColor="#f9b318" stopOpacity={0.04} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} stroke="#d9d6ca" strokeDasharray="3 6" />
                  <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickLine={false} axisLine={false}
                    tick={{ fontSize: 12, fill: "#545a70" }} minTickGap={48} tickFormatter={dateTick} />
                  <YAxis width={64} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#545a70" }}
                    domain={yDomain(lowest.map((d) => d.price))} tickFormatter={(v) => shortINR(v as number)} />
                  <Tooltip {...tooltipStyle}
                    labelFormatter={(t) => new Date(t as number).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                    formatter={(v, _name, item) => {
                      const pl = item.payload as { retailer: string; demo: boolean };
                      return [`${formatINR(v as number)}${pl.demo ? "" : ` at ${pl.retailer}`}`, "Lowest price"];
                    }}
                    itemStyle={{ color: "#14172b" }} cursor={{ stroke: "#f9b318", strokeWidth: 1.5 }} />
                  <Area type="monotone" dataKey="price" stroke="#1546d9" strokeWidth={2.5} fill="url(#bwHistoryFill)" baseValue="dataMin" connectNulls
                    dot={lowest.length <= 30 ? { r: 3.5, fill: "#1546d9", stroke: "#fff", strokeWidth: 2 } : false}
                    activeDot={{ r: 6, fill: "#1546d9", stroke: "#fff", strokeWidth: 2 }} animationDuration={500} />
                  {extremes && (
                    <ReferenceDot x={extremes.hi.t} y={extremes.hi.price} r={5} fill="#b8293a" stroke="#fff" strokeWidth={2} ifOverflow="extendDomain"
                      label={{ value: `Highest ${formatINR(extremes.hi.price)}`, position: edge(extremes.hi.t, "top"), fill: "#b8293a", fontSize: 11, fontWeight: 600 }} />
                  )}
                  {extremes && (
                    <ReferenceDot x={extremes.lo.t} y={extremes.lo.price} r={5} fill="#137a45" stroke="#fff" strokeWidth={2} ifOverflow="extendDomain"
                      label={{ value: `Lowest ${formatINR(extremes.lo.price)}`, position: edge(extremes.lo.t, "bottom"), fill: "#137a45", fontSize: 11, fontWeight: 600 }} />
                  )}
                </AreaChart>
              ) : (
                <LineChart data={byStore!.data} margin={{ top: 10, right: 8, bottom: 0, left: 4 }}>
                  <CartesianGrid vertical={false} stroke="#d9d6ca" strokeDasharray="3 6" />
                  <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickLine={false} axisLine={false}
                    tick={{ fontSize: 12, fill: "#545a70" }} minTickGap={40} tickFormatter={dateTick} />
                  <YAxis width={64} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#545a70" }}
                    domain={yDomain(byStore!.data.flatMap((r) => byStore!.stores.map((s) => r[s]).filter((v): v is number => v !== undefined)))}
                    tickFormatter={(v) => shortINR(v as number)} />
                  <Tooltip {...tooltipStyle} labelFormatter={(t) => formatDateTime(new Date(t as number).toISOString())}
                    formatter={(v, n) => [formatINR(v as number), n as string]} itemStyle={{ color: "#14172b" }} />
                  <Legend wrapperStyle={{ fontSize: 12, color: "#545a70" }} iconType="plainline" />
                  {byStore!.stores.map((s, i) => (
                    <Line key={s} type="stepAfter" dataKey={s} name={s} stroke={STORE_COLOURS[i]} strokeWidth={2} connectNulls
                      dot={{ r: 4, fill: STORE_COLOURS[i], stroke: "#f8f7f2", strokeWidth: 2 }} activeDot={{ r: 6 }} animationDuration={400} />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-8 gap-y-1 text-sm">
            <span>Lowest: <strong className="tabular text-success">{formatINR(q.data.lowest)}</strong></span>
            <span>Average: <strong className="tabular">{formatINR(q.data.average)}</strong></span>
            <span>Highest: <strong className="tabular text-danger">{formatINR(q.data.highest)}</strong></span>
            {q.data.latest && <span>Latest: <strong className="tabular text-cyan">{formatINR(q.data.latest.price)}</strong> at {q.data.latest.retailer}</span>}
          </div>
          <p className="mt-2 text-xs text-ink-soft">
            {view === "lowest"
              ? (changed ? "Lowest price across trusted stores at each check. Hover the graph to see the price on any day."
                : "The lowest price hasn't changed between checks so far – the line is level because the price really stayed the same. Try “By store” to see each store.")
              : `Each store's own checked prices (real data only)${byStore && byStore.hidden > 0 ? ` – top ${MAX_STORES} stores shown; ${byStore.hidden} more in the table below` : ""}.`}
            {" "}BuyWise records real prices while it is running.
          </p>
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-line bg-canvas p-8 text-center text-sm text-ink-soft" data-testid="history-insufficient">
          {lowest.length === 1
            ? `Tracking since ${formatDateTime(q.data.tracking_started_at)} at ${formatINR(lowest[0].price)}. The graph fills in as BuyWise checks prices.`
            : q.data.note}
        </div>
      )}
    </Card>
  );
}

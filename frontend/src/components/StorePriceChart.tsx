import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Offer } from "../types/api";
import { formatINR } from "../utils/format";

/** Horizontal bar chart of current prices per store (one bar per store, cheapest offer of that store). */
export function StorePriceChart({ offers }: { offers: Offer[] }) {
  const byStore = new Map<string, Offer>();
  for (const o of offers) {
    if (o.price === null || !o.retailer) continue;
    const cur = byStore.get(o.retailer);
    if (!cur || (cur.price ?? Infinity) > o.price) byStore.set(o.retailer, o);
  }
  const data = [...byStore.values()]
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0))
    .map((o) => ({ store: o.retailer!, price: o.price!, best: o.is_best_price, eligible: o.eligible_for_best_price }));
  if (data.length < 2) return null;
  const height = 40 + data.length * 38;
  return (
    <div data-testid="store-price-chart">
      <h2 className="text-lg font-semibold">Price across stores</h2>
      <p className="mb-2 text-xs text-ink-soft">Current price at each store. The yellow bar is the lowest verified price; blue bars are other trusted stores.</p>
      <div style={{ height }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 72, bottom: 4, left: 8 }}>
            <CartesianGrid stroke="#d9d6ca" horizontal={false} strokeDasharray="3 6" />
            <XAxis type="number" hide domain={[0, "dataMax"]} />
            <YAxis type="category" dataKey="store" width={120} tick={{ fontSize: 12, fill: "#14172b" }} />
            <Tooltip formatter={(v) => formatINR(v as number)} cursor={{ fill: "rgb(21 70 217 / 0.06)" }}
              contentStyle={{ borderRadius: 12, background: "rgb(255 255 255 / 0.92)", border: "1px solid #d9d6ca", color: "#14172b", boxShadow: "0 10px 30px -16px rgb(20 23 43 / 0.35)" }} />
            <Bar dataKey="price" radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {data.map((d) => <Cell key={d.store} fill={d.best ? "#f9b318" : d.eligible ? "#1546d9" : "#b3af9f"} />)}
              <LabelList dataKey="price" position="right" formatter={(v) => formatINR(v as number)} style={{ fontSize: 12, fill: "#14172b" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

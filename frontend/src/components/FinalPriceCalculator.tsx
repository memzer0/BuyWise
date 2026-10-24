import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Calculator, Check, Info } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { FinalPrice } from "../types/api";
import { formatINR } from "../utils/format";
import { StoreLogo } from "./StoreLogo";
import { Card } from "./ui";

/** True Final Price: guaranteed totals plus offers applied only for the cards the shopper says they hold. */
export function FinalPriceCalculator({ productId, initial }: { productId: number; initial: FinalPrice }) {
  const [banks, setBanks] = useState<string[]>([]);
  const [coupons, setCoupons] = useState(false);
  const q = useQuery({
    queryKey: ["final-price", productId, banks, coupons],
    queryFn: ({ signal }) => api.finalPrice(productId, banks, coupons, signal),
    initialData: banks.length === 0 && !coupons ? initial : undefined,
    placeholderData: keepPreviousData,
  });
  const fp = q.data ?? initial;
  const toggle = (b: string) => setBanks((cur) => (cur.includes(b) ? cur.filter((x) => x !== b) : [...cur, b]));

  return (
    <Card data-testid="final-price">
      <div className="border-b border-line p-5">
        <h2 className="flex items-center gap-2 text-xl font-bold"><Calculator className="h-5 w-5 text-cyan" aria-hidden /> True final price</h2>
        <p className="text-sm text-ink-soft">What you'd actually pay at each store. Card offers count only for the cards you select.</p>
        {fp.banks_mentioned.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-soft">I have a card from:</span>
            {fp.banks_mentioned.map((b) => (
              <button key={b} type="button" onClick={() => toggle(b)} aria-pressed={banks.includes(b)}
                className={`press inline-flex items-center gap-1 rounded-full border px-3 py-1 ${banks.includes(b) ? "border-accent bg-accent-soft text-brand" : "border-line hover:border-accent/60"}`}>
                {banks.includes(b) && <Check className="h-3.5 w-3.5" aria-hidden />}{b}
              </button>
            ))}
            <label className="ml-2 inline-flex items-center gap-1.5"><input type="checkbox" checked={coupons} onChange={(e) => setCoupons(e.target.checked)} /> Include coupon codes</label>
          </div>
        ) : (
          <p className="mt-3 rounded-lg border border-line bg-surface-2 p-3 text-sm text-ink-soft" data-testid="no-offers-note">
            {fp.offers_data_available
              ? "The stores' offers don't name a specific bank card."
              : "No bank offers or coupons were reported by the stores for this product, so totals below are price + delivery only."}
          </p>
        )}
      </div>
      {fp.stores.length === 0 ? (
        <p className="p-5 text-sm text-ink-soft">No verified offers from trusted stores to calculate.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-ink-soft">
              <tr className="border-b border-line">
                <th className="px-5 py-2 font-medium">Store</th><th className="px-3 py-2 font-medium">Price</th>
                <th className="px-3 py-2 font-medium">Delivery</th><th className="px-3 py-2 font-medium">Guaranteed</th>
                <th className="px-3 py-2 font-medium">Your offers</th><th className="px-5 py-2 text-right font-medium">You could pay</th>
              </tr>
            </thead>
            <tbody>
              {fp.stores.map((s, i) => (
                <tr key={s.offer_id} className={`border-b border-line/70 align-top ${i === 0 ? "bg-cyan/5" : ""}`} data-testid="final-price-row">
                  <td className="px-5 py-3"><span className="flex items-center gap-2 font-semibold"><StoreLogo name={s.retailer} size={26} />{s.retailer}</span></td>
                  <td className="px-3 py-3 tabular">{formatINR(s.base_price)}</td>
                  <td className="px-3 py-3 tabular">{s.shipping === null ? <span className="text-warning">not reported</span> : s.shipping === 0 ? "Free" : formatINR(s.shipping)}</td>
                  <td className="px-3 py-3 tabular">{s.guaranteed_total === null ? <span className="text-ink-soft">{formatINR(s.base_price)} + delivery</span> : formatINR(s.guaranteed_total)}</td>
                  <td className="px-3 py-3">
                    {s.applied.length === 0 ? <span className="text-ink-soft">—</span> : s.applied.map((a) => (
                      <p key={a.text} className="text-success" title={a.text}>−{formatINR(a.saving)} <span className="text-xs text-ink-soft">{a.kind === "coupon" ? `code ${a.code ?? ""}` : a.banks.join(", ")}</span></p>
                    ))}
                    {s.not_applied.length > 0 && (
                      <details className="mt-1 text-xs text-ink-soft"><summary className="cursor-pointer">{s.not_applied.length} other offer(s)</summary>
                        <ul className="mt-1 space-y-1">{s.not_applied.map((n) => <li key={n.text}>• {n.text} <em>({n.reason})</em></li>)}</ul>
                      </details>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <p className="tabular text-lg font-bold">{formatINR(s.possible_total)}</p>
                    {s.guaranteed_total === null && <p className="text-xs text-warning">+ delivery if charged</p>}
                    {i === 0 && <p className="text-xs font-semibold text-cyan">Lowest for you</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="p-5 text-xs text-ink-soft">
        <summary className="flex cursor-pointer items-center gap-1"><Info className="h-3.5 w-3.5" aria-hidden /> How this is calculated</summary>
        <ul className="mt-2 space-y-1">{fp.assumptions.map((a) => <li key={a}>• {a}</li>)}</ul>
      </details>
    </Card>
  );
}

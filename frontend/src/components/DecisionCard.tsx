import { ArrowRight, CircleHelp, Hourglass, ShoppingCart, Shuffle } from "lucide-react";
import { Link } from "react-router-dom";
import type { ProductDetail } from "../types/api";
import { formatINR } from "../utils/format";
import { OrbitMark } from "./OrbitMark";
import { Card } from "./ui";

const VERDICT = {
  BUY_NOW: { cls: "border-success/50 bg-success/10 text-success", Icon: ShoppingCart },
  WAIT: { cls: "border-warning/50 bg-warning/10 text-warning", Icon: Hourglass },
  CONSIDER_ALTERNATIVES: { cls: "border-cyan/50 bg-cyan/10 text-cyan", Icon: Shuffle },
  NOT_ENOUGH_DATA: { cls: "border-line bg-surface-2 text-ink-soft", Icon: CircleHelp },
} as const;
const LEVEL = { high: "High", medium: "Medium", low: "Low" } as const;

/** BuyWise Decision Engine: Buy now / Wait / Consider alternatives / Not enough data, with reasons and limitations. */
export function DecisionCard({ d }: { d: ProductDetail }) {
  const dec = d.decision;
  const v = VERDICT[dec.verdict];
  return (
    <Card className="relative overflow-hidden" data-testid="decision">
      <div aria-hidden className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full bg-accent/15 blur-3xl" />
      <div className="relative flex flex-wrap items-start gap-x-6 gap-y-4 p-5">
        <div className="flex min-w-[220px] flex-col gap-2">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-soft"><OrbitMark size={18} /> BuyWise decision</p>
          <span className={`inline-flex w-fit items-center gap-2 rounded-xl border px-4 py-2 text-xl font-bold ${v.cls}`} data-testid="decision-verdict">
            <v.Icon className="h-5 w-5" aria-hidden /> {dec.label}
          </span>
          <span className="text-xs text-ink-soft">Evidence level: <strong className="text-ink">{LEVEL[dec.evidence_level]}</strong>
            </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{dec.headline}</p>
          <ul className="mt-1 space-y-1 text-sm text-ink-soft">{dec.reasons.map((r) => <li key={r}>• {r}</li>)}</ul>
          {dec.alternatives.length > 0 && (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {dec.alternatives.slice(0, 2).map((a) => (
                <Link key={a.id} to={`/product/${a.id}`} className="lift flex items-center justify-between gap-3 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm">
                  <span className="min-w-0 truncate">{a.title}</span>
                  <span className="flex shrink-0 items-center gap-1 font-semibold text-cyan">{formatINR(a.best_price)} <ArrowRight className="h-4 w-4" aria-hidden /></span>
                </Link>
              ))}
            </div>
          )}
          <details className="mt-3 text-xs text-ink-soft">
            <summary className="cursor-pointer">Limitations ({dec.limitations.length})</summary>
            <ul className="mt-1 space-y-0.5">{dec.limitations.map((l) => <li key={l}>• {l}</li>)}</ul>
          </details>
        </div>
      </div>
    </Card>
  );
}

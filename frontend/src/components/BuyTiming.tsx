import { ArrowDown, ArrowUp, ArrowUpDown, Info } from "lucide-react";
import { useState } from "react";
import type { Timing } from "../types/api";
import { formatINR } from "../utils/format";
import { ScoreGauge } from "./ScoreGauge";

const TONE = { good: "text-success", fair: "text-warning", wait: "text-danger" } as const;

/** "Should you buy now?" – timing advice for when the shopper needs the product, from observed prices only. */
export function BuyTiming({ t }: { t: Timing }) {
  const [key, setKey] = useState<"3d" | "1w" | "1m">("1w");
  const h = t.horizons.find((x) => x.key === key) ?? null;
  return (
    <div data-testid="buy-timing">
      <h3 className="text-lg font-bold">Should you buy now?</h3>
      {t.available ? (
        <>
          <div className="mt-2 flex items-center gap-2">
            <div role="tablist" aria-label="When do you need it?" className="flex rounded-full bg-white/40 p-1 ring-1 ring-white/70">
              {t.horizons.map((x) => (
                <button key={x.key} role="tab" aria-selected={key === x.key} onClick={() => setKey(x.key)}
                  className={`rounded-full px-3 py-1 text-sm font-medium transition ${key === x.key ? "btn-gloss bg-accent-strong text-white" : "text-ink-soft hover:text-ink"}`}>
                  {x.label}
                </button>
              ))}
            </div>
            <span title={t.method} className="text-ink-soft"><Info className="h-4 w-4" aria-label="How this works" /></span>
          </div>
          <p className="mt-1 text-xs text-ink-soft">Choose when you need it</p>
          {h && (
            <div className="mt-3 flex flex-wrap items-center gap-4">
              <div className="text-center">
                <ScoreGauge score={h.score} size={150} />
                <div className="-mt-1 flex justify-center gap-3 text-[11px] text-ink-soft">
                  <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-danger" />Bad time</span>
                  <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-success" />Good time</span>
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm text-ink-soft">Our recommendation</p>
                <p className={`text-xl font-bold ${TONE[h.tone]}`} data-testid="timing-recommendation">{h.recommendation}</p>
                <ul className="mt-1 space-y-0.5 text-sm text-ink-soft">{h.why.map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 rounded-lg bg-surface-2 p-3 text-sm text-ink-soft" data-testid="timing-unavailable">{t.reason}</p>
      )}
      <h3 className="mt-5 text-lg font-bold">Price stats</h3>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <Stat label="Highest price" value={t.stats.highest} icon={<ArrowUp className="h-3.5 w-3.5 text-danger" aria-hidden />} />
        <Stat label="Average price" value={t.stats.average} icon={<ArrowUpDown className="h-3.5 w-3.5 text-warning" aria-hidden />} />
        <div className="col-span-2"><Stat label="Lowest price" value={t.stats.lowest} icon={<ArrowDown className="h-3.5 w-3.5 text-success" aria-hidden />} /></div>
      </div>
      <p className="mt-1 text-[11px] text-ink-soft">From prices BuyWise has observed at trusted stores.</p>
    </div>
  );
}

function Stat({ label, value, icon }: { label: string; value: number | null; icon: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-surface-2 p-3 text-center">
      <p className="flex items-center justify-center gap-1 text-xs text-ink-soft">{label} {icon}</p>
      <p className="mt-1 tabular text-lg font-bold">{value === null ? "—" : formatINR(value)}</p>
    </div>
  );
}

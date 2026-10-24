import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, Bell, ChevronRight, ThumbsDown, ThumbsUp, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { api, rememberEmail, savedEmail } from "../api/client";
import type { Offer, ProductDetail } from "../types/api";
import { formatINR, safeHref } from "../utils/format";
import { BuyTiming } from "./BuyTiming";
import { ScoreGauge } from "./ScoreGauge";
import { Card } from "./ui";

const CHANGES_PREVIEW = 5;

function labelStyle(score: number | null): { cls: string; Icon: typeof ThumbsUp } {
  if (score === null) return { cls: "border-line text-ink-soft bg-surface", Icon: BarChart3 };
  if (score >= 60) return { cls: "border-success text-success bg-success/10", Icon: ThumbsUp };
  if (score >= 40) return { cls: "border-warning text-warning bg-warning/10", Icon: ThumbsUp };
  return { cls: "border-warning text-warning bg-warning/10", Icon: ThumbsDown };
}

export function DealPanel({ d, productId, best }: { d: ProductDetail; productId: number; best: Offer | null }) {
  const [tab, setTab] = useState<"scanner" | "drops">("scanner");
  const [showAll, setShowAll] = useState(false);
  const deal = d.deal;
  const { cls, Icon } = labelStyle(deal.score);
  const insight = deal.insight;
  const InsightIcon = insight?.kind === "warning" ? AlertTriangle : insight?.kind === "good" ? TrendingDown : BarChart3;
  const buyHref = best ? safeHref(best.product_url) : null;

  return (
    <Card className="overflow-hidden">
      <div role="tablist" className="grid grid-cols-2 border-b border-line text-sm font-medium">
        {(["scanner", "drops"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={`py-3 ${tab === t ? "border-b-2 border-brand text-brand" : "text-ink-soft hover:text-ink"}`}>
            {t === "scanner" ? "Deal scanner" : "Price drop"}
          </button>
        ))}
      </div>

      {tab === "scanner" ? (
        <>
          <div className="flex items-center justify-between gap-3 px-5 pt-5">
            <span className={`inline-flex items-center gap-1.5 rounded-full border-2 px-4 py-1.5 text-sm font-semibold ${cls}`} data-testid="deal-label">
              <Icon className="h-4 w-4" aria-hidden /> {deal.label}
            </span>
            <div className="text-center">
              <ScoreGauge score={deal.score} size={128} />
              <p className="-mt-1 text-sm">Deal score <strong className="tabular" data-testid="buywise-score">{deal.score ?? "—"}</strong></p>
            </div>
          </div>
          {insight && (
            <div className={`mx-5 mt-4 flex gap-3 rounded-xl p-4 ${insight.kind === "warning" ? "bg-warning/10" : insight.kind === "good" ? "bg-success/10" : "bg-brand-soft"}`}
              data-testid="deal-insight">
              <InsightIcon className={`mt-0.5 h-5 w-5 shrink-0 ${insight.kind === "warning" ? "text-warning" : insight.kind === "good" ? "text-success" : "text-brand"}`} aria-hidden />
              <div>
                <p className="font-semibold">{insight.title}</p>
                <p className="text-sm text-ink-soft">{insight.body}</p>
              </div>
            </div>
          )}
          <div className="mt-5 border-t border-line bg-surface-2/60 px-5 py-4">
            <div className="mb-2 flex justify-between text-sm font-semibold"><span>Deal score breakup</span><span>Pts</span></div>
            <ul className="space-y-2.5 text-sm" data-testid="deal-checks">
              {deal.checks.map((c) => (
                <li key={c.key} className="flex items-start justify-between gap-3">
                  <span className={c.status === "na" ? "text-ink-soft" : ""}>
                    {c.label}
                    <span className="block text-xs text-ink-soft">{c.detail}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5 tabular" title={c.status === "na" ? "Tracking" : c.status === "pass" ? "Passed" : c.status === "same" ? "Same price – half points" : "Not met"}>
                    <span className={`h-3.5 w-3.5 rounded-full border-[3px] ${c.status === "pass" ? "border-success" : c.status === "same" ? "border-warning" : c.status === "fail" ? "border-danger" : "border-line"}`} aria-hidden />
                    {c.status === "na" ? "–" : c.points}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs italic text-ink-soft">
              Calculated only from prices BuyWise has actually observed ({Math.round(deal.completeness * 100)}% of the checks could be judged so far).
            </p>
          </div>
          <details className="group border-t border-line px-5 py-4" data-testid="buywise-score-details">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm">
              <span className="font-semibold">BuyWise Score
                <span className="ml-1 font-normal text-ink-soft">(weighted value score)</span>
              </span>
              <span className="tabular">
                <strong className="text-brand" data-testid="weighted-score">{d.score.score ?? "—"}</strong><span className="text-ink-soft">/100</span>
                <span className="ml-2 text-xs text-ink-soft">data {Math.round(d.score.confidence * 100)}%</span>
              </span>
            </summary>
            <ul className="mt-3 space-y-2 text-sm">
              {d.score.components.map((c) => (
                <li key={c.key} className="flex items-start justify-between gap-3">
                  <span className={c.score === null ? "text-ink-soft" : ""}>{c.label} <span className="text-xs text-ink-soft">({Math.round(c.weight * 100)}%)</span>
                    <span className="block text-xs text-ink-soft">{c.explanation}</span></span>
                  <span className="tabular">{c.score === null ? "–" : Math.round(c.score)}</span>
                </li>
              ))}
            </ul>
            {[...d.score.reasons, ...d.score.limitations].map((r) => <p key={r} className="mt-2 text-xs text-ink-soft">• {r}</p>)}
            <p className="mt-2 text-xs text-ink-soft">
              {d.prediction.available
                ? `Trend estimate: about ${formatINR(d.prediction.predicted_price)} in ${d.prediction.horizon_days} days (hold-out error ±${formatINR(d.prediction.holdout_mae)}). An estimate, not a guarantee.`
                : d.prediction.reason ?? "Price trend estimate coming soon."}
            </p>
          </details>
        </>
      ) : (
        <div className="p-5" data-testid="price-drops">
          <BuyTiming t={d.timing} />
          <h3 className="mb-1 mt-6 text-lg font-bold">Recent price changes</h3>
          {deal.price_changes.length === 0 ? (
            <p className="text-sm text-ink-soft">No price changes recorded yet. Changes appear here as BuyWise re-checks this product.</p>
          ) : (
            <>
            <ul className="divide-y divide-line text-sm">
              {deal.price_changes.slice(0, showAll ? undefined : CHANGES_PREVIEW).map((c) => (
                <li key={c.date + c.to} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="text-ink-soft">{new Date(c.date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</span>
                  <span className="tabular">{formatINR(c.from)} → <strong>{formatINR(c.to)}</strong></span>
                  <span className={`inline-flex items-center gap-1 font-semibold ${c.change < 0 ? "text-success" : "text-danger"}`}>
                    {c.change < 0 ? <TrendingDown className="h-4 w-4" aria-hidden /> : <TrendingUp className="h-4 w-4" aria-hidden />}
                    {formatINR(Math.abs(c.change))}
                  </span>
                </li>
              ))}
            </ul>
            {deal.price_changes.length > CHANGES_PREVIEW && (
              <button type="button" onClick={() => setShowAll((v) => !v)} data-testid="price-changes-toggle"
                className="mt-1 text-xs font-semibold text-brand hover:underline">
                {showAll ? "Show less" : `Show more (${deal.price_changes.length - CHANGES_PREVIEW})`}
              </button>
            )}
            </>
          )}
        </div>
      )}

      <div className="border-t border-line p-5">
        <AlertForm productId={productId} current={d.summary.lowest_verified_price} />
        {best && buyHref && (
          <>
            <p className="my-3 text-center text-xs font-medium text-ink-soft">OR</p>
            <a href={buyHref} target="_blank" rel="noopener noreferrer nofollow sponsored"
              className="flex w-full items-center justify-center gap-1 rounded-xl btn-gloss bg-accent-strong py-3 text-base font-bold text-white hover:brightness-110">
              {best.link_type === "exact_listing" ? `Buy on ${best.retailer}` : `See ${best.retailer} offer`} <ChevronRight className="h-5 w-5" aria-hidden />
            </a>
          </>
        )}
      </div>
    </Card>
  );
}

function AlertForm({ productId, current }: { productId: number; current: number | null }) {
  const qc = useQueryClient();
  const [target, setTarget] = useState(current ? String(Math.floor(current * 0.95)) : "");
  const [email, setEmail] = useState(savedEmail());
  const m = useMutation({
    mutationFn: () => {
      const mail = email.trim();
      if (mail) rememberEmail(mail);
      return api.createAlert(mail
        ? { product_id: productId, target_price: Number(target), channel: "email", email: mail }
        : { product_id: productId, target_price: Number(target), channel: "in_app" });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  });
  return (
    <form id="alert" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <p className="mb-2 text-center font-semibold">Set a price drop alert to buy later</p>
      <div className="flex items-center gap-2 rounded-xl border border-line bg-surface p-1.5 pl-3 focus-within:border-brand">
        <Bell className="h-4 w-4 text-ink-soft" aria-hidden />
        <span className="text-ink-soft">₹</span>
        <input required inputMode="numeric" aria-label="Target price" value={target}
          onChange={(e) => setTarget(e.target.value.replace(/\D/g, ""))} className="min-w-0 flex-1 py-2 outline-none tabular" />
        <button type="submit" disabled={m.isPending || !target}
          className="rounded-lg btn-gloss bg-accent-strong px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">
          {m.isPending ? "Saving…" : "Set alert"}
        </button>
      </div>
      <input type="email" inputMode="email" autoComplete="email" aria-label="E-mail for this alert (optional)" value={email}
        onChange={(e) => setEmail(e.target.value)} placeholder="E-mail me too (optional)" maxLength={254}
        className="mt-2 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-brand" />
      {m.isSuccess && <p className="mt-2 text-sm text-success">Alert saved{email.trim() ? " – we'll e-mail you when it drops" : ""}. {m.data.delivery_note}</p>}
      {m.isError && <p className="mt-2 text-sm text-danger">{(m.error as Error).message}</p>}
    </form>
  );
}

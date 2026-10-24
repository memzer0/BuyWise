import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleHelp, Hourglass, Loader2, ShieldCheck, ShoppingCart, Shuffle, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, rememberEmail, savedEmail } from "../api/client";
import type { Purchase, PurchaseInput, RegretResult } from "../types/api";
import { formatDateTime, formatINR } from "../utils/format";
import { Card, ErrorState, Skeleton } from "./ui";

export const RESULT_STYLE: Record<RegretResult, { cls: string; Icon: typeof ShoppingCart }> = {
  BUY_NOW: { cls: "border-success/50 bg-success/10 text-success", Icon: ShoppingCart },
  WAIT: { cls: "border-warning/50 bg-warning/10 text-warning", Icon: Hourglass },
  COMPARE_FIRST: { cls: "border-cyan/50 bg-cyan/10 text-cyan", Icon: Shuffle },
  INSUFFICIENT_DATA: { cls: "border-line bg-surface-2 text-ink-soft", Icon: CircleHelp },
};

/** Today's date in the browser's time zone as YYYY-MM-DD (for <input type="date">). */
export function localISODate(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:border-brand focus:outline-none";

type FormValues = Omit<PurchaseInput, "product_id">;

/** Purchase form used for both "Track my purchase" and editing. Only price, store and date are required. */
export function PurchaseForm({ initial, submitLabel, pending, error, onSubmit, onCancel }: {
  initial: Partial<FormValues>;
  submitLabel: string;
  pending: boolean;
  error: string | null;
  onSubmit: (v: FormValues) => void;
  onCancel?: () => void;
}) {
  const [retailer, setRetailer] = useState(initial.retailer ?? "");
  const [price, setPrice] = useState(initial.purchase_price ? String(initial.purchase_price) : "");
  const [date, setDate] = useState(initial.purchase_date ?? localISODate());
  const [orderRef, setOrderRef] = useState(initial.order_ref ?? "");
  const [ret, setRet] = useState(initial.return_deadline ?? "");
  const [prot, setProt] = useState(initial.protection_deadline ?? "");
  const [costs, setCosts] = useState(initial.expected_costs != null ? String(initial.expected_costs) : "");
  const [notify, setNotify] = useState(initial.notify ?? true);
  const [email, setEmail] = useState("email" in initial ? (initial.email ?? "") : savedEmail()); // edit keeps its own value
  const [localErr, setLocalErr] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const p = Number(price);
    if (!retailer.trim()) return setLocalErr("Enter the store you bought from.");
    if (!Number.isFinite(p) || p <= 0) return setLocalErr("Enter the price you paid (more than ₹0).");
    if (date > localISODate(new Date(Date.now() + 86_400_000))) return setLocalErr("The purchase date can't be in the future.");
    for (const [d, name] of [[ret, "Return deadline"], [prot, "Price-protection deadline"]] as const)
      if (d && d < date) return setLocalErr(`${name} can't be before the purchase date.`);
    const c = costs.trim() === "" ? null : Number(costs);
    const mail = email.trim();
    if (mail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail)) return setLocalErr("Enter a valid e-mail address, or leave it empty.");
    if (c !== null && (!Number.isFinite(c) || c < 0)) return setLocalErr("Expected costs must be ₹0 or more.");
    setLocalErr(null);
    onSubmit({ retailer: retailer.trim(), purchase_price: p, purchase_date: date, order_ref: orderRef.trim() || null,
      return_deadline: ret || null, protection_deadline: prot || null, expected_costs: c, notify, email: mail || null });
    if (mail) rememberEmail(mail);
  };

  const err = localErr ?? error;
  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Purchase details" noValidate>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-medium text-ink-soft">Store *
          <input className={input} value={retailer} onChange={(e) => setRetailer(e.target.value)} maxLength={120} required />
        </label>
        <label className="text-xs font-medium text-ink-soft">Price paid (₹) *
          <input className={input} type="number" inputMode="decimal" min={1} step="any" value={price} onChange={(e) => setPrice(e.target.value)} required />
        </label>
        <label className="text-xs font-medium text-ink-soft">Purchase date *
          <input className={input} type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
      </div>
      <details className="rounded-lg border border-line bg-surface-2/50 px-3 py-2" open={Boolean(initial.return_deadline || initial.protection_deadline || initial.order_ref || initial.expected_costs != null)}>
        <summary className="cursor-pointer text-sm font-medium">Optional details – deadlines, order reference, expected costs</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-ink-soft">Return / exchange deadline
            <input className={input} type="date" value={ret} onChange={(e) => setRet(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-ink-soft">Price-protection deadline
            <input className={input} type="date" value={prot} onChange={(e) => setProt(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-ink-soft">Order reference (for your own records)
            <input className={input} value={orderRef} onChange={(e) => setOrderRef(e.target.value)} maxLength={100} placeholder="Optional" />
          </label>
          <label className="text-xs font-medium text-ink-soft">Expected return / restocking costs (₹)
            <input className={input} type="number" min={0} step="any" value={costs} onChange={(e) => setCosts(e.target.value)} placeholder="Optional" />
          </label>
        </div>
        <p className="mt-2 text-xs text-ink-soft">Enter deadlines only from your order page or the store's policy – BuyWise never guesses them.</p>
      </details>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> Notify me about price drops and deadlines
      </label>
      {notify && (
        <label className="block text-xs font-medium text-ink-soft">E-mail me too (optional)
          <input className={input} type="email" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com" maxLength={254} />
        </label>
      )}
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" disabled={pending} className="btn-gloss inline-flex items-center gap-2 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-60">
          {pending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />} {submitLabel}
        </button>
        {onCancel && <button type="button" onClick={onCancel} className="rounded-lg px-3 py-2 text-sm text-ink-soft hover:bg-surface-2">Cancel</button>}
      </div>
      <p className="text-xs text-ink-soft">
        BuyWise never asks for marketplace passwords, OTPs, payment details or receipts. Your purchase is stored on this BuyWise server and
        linked only to this browser.
      </p>
    </form>
  );
}

/** Product page: pre-purchase check + "Track my purchase". */
export function RegretShieldCard({ productId, version, bestRetailer, bestPrice }: { productId: number; version?: string | null; bestRetailer: string | null; bestPrice: number | null }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["regret", productId, version ?? null], queryFn: ({ signal }) => api.regretShield(productId, signal) });
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<Purchase | null>(null);
  const create = useMutation({
    mutationFn: (v: FormValues) => api.createPurchase({ ...v, product_id: productId }),
    onSuccess: (p) => { setSaved(p); setOpen(false); qc.invalidateQueries({ queryKey: ["purchases"] }); },
  });

  return (
    <Card className="relative overflow-hidden" data-testid="regret-shield">
      <div aria-hidden className="pointer-events-none absolute -left-24 -top-24 h-56 w-56 rounded-full bg-cyan/10 blur-3xl" />
      <div className="relative space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-bold"><ShieldCheck className="h-5 w-5 text-cyan" aria-hidden /> Regret Shield</h2>
          <Link to="/purchases" className="text-sm text-brand hover:underline">My purchases →</Link>
        </div>

        {q.isPending ? <Skeleton className="h-24 w-full" /> : q.isError ? <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} /> : (() => {
          const r = q.data;
          const st = RESULT_STYLE[r.result];
          return (
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div className="space-y-2">
                <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-soft">Before you buy
                  </p>
                <span className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-lg font-bold ${st.cls}`} data-testid="regret-result">
                  <st.Icon className="h-5 w-5" aria-hidden /> {r.label}
                </span>
                <ul className="space-y-1 text-sm text-ink-soft">{r.reasons.map((x) => <li key={x}>• {x}</li>)}</ul>
                {r.observed_at && <p className="text-xs text-ink-soft">Based on prices verified {formatDateTime(r.observed_at)}.</p>}
              </div>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-soft">Evidence checked</p>
                <ul className="grid gap-1.5 sm:grid-cols-2" data-testid="regret-evidence">
                  {r.evidence.map((e) => (
                    <li key={e.label} className="flex items-start gap-2 rounded-lg border border-line bg-surface-2/60 px-2.5 py-1.5 text-sm">
                      {e.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="Available" />
                        : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-ink-soft" aria-label="Missing" />}
                      <span className="min-w-0"><span className="font-medium">{e.label}</span>
                        <span className="block truncate text-xs text-ink-soft">{e.value ?? "Not available"}</span></span>
                    </li>
                  ))}
                </ul>
                {r.limitations.length > 0 && (
                  <details className="mt-2 text-xs text-ink-soft">
                    <summary className="cursor-pointer">Limitations ({r.limitations.length})</summary>
                    <ul className="mt-1 space-y-0.5">{r.limitations.map((l) => <li key={l}>• {l}</li>)}</ul>
                  </details>
                )}
              </div>
            </div>
          );
        })()}

        <div className="border-t border-line pt-4">
          {saved ? (
            <p className="text-sm" role="status">
              <CheckCircle2 className="mr-1 inline h-4 w-4 text-success" aria-hidden />
              Tracking your purchase at {formatINR(saved.purchase_price)}. BuyWise will compare it with verified prices for this exact variant.{" "}
              <Link to="/purchases" className="text-brand underline">View in My purchases</Link>
            </p>
          ) : open ? (
            <PurchaseForm
              initial={{ retailer: bestRetailer ?? "", purchase_price: bestPrice ?? undefined }}
              submitLabel="Start tracking"
              pending={create.isPending}
              error={create.error ? (create.error as ApiError).message : null}
              onSubmit={(v) => create.mutate(v)}
              onCancel={() => setOpen(false)}
            />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-ink-soft">Already bought it? Track your purchase and BuyWise will tell you if this exact variant gets cheaper while your return or price-protection window is open.</p>
              <button onClick={() => setOpen(true)} className="rounded-lg border border-brand/60 px-4 py-2 text-sm font-semibold text-brand hover:bg-brand/10">Track my purchase</button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

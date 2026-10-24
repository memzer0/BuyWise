import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, CalendarClock, ExternalLink, History, Loader2, Pencil, RefreshCw, ShieldCheck, Trash2, TrendingDown } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { ProductImage } from "../components/ProductCard";
import { PurchaseForm } from "../components/RegretShield";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import type { Purchase, PurchaseStatus } from "../types/api";
import { formatDateTime, formatINR, safeHref } from "../utils/format";

const STATUS: Record<PurchaseStatus, { tone: "green" | "amber" | "red" | "slate" | "cyan" | "brand"; label: string }> = {
  price_drop: { tone: "green", label: "Price dropped" },
  small_drop: { tone: "cyan", label: "Slightly cheaper" },
  no_drop: { tone: "slate", label: "No drop" },
  comparable_unavailable: { tone: "amber", label: "Comparable offer unavailable" },
  stale_data: { tone: "amber", label: "Prices are stale" },
  invalid_purchase_price: { tone: "red", label: "Check purchase price" },
  pending: { tone: "slate", label: "Not checked yet" },
};
const DEADLINE_TONE = { passed: "slate", today: "red", soon: "amber", upcoming: "cyan" } as const;

function variant(p: Purchase) {
  return [p.storage_gb && `${p.storage_gb} GB`, p.ram_gb && `${p.ram_gb} GB RAM`, p.colour, p.condition !== "new" && p.condition]
    .filter(Boolean).join(" · ");
}

function daysText(n: number) {
  return n < 0 ? `${-n} day(s) ago` : n === 0 ? "today" : `in ${n} day(s)`;
}

function PurchaseHistoryList({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["purchase-history", id], queryFn: ({ signal }) => api.purchaseHistory(id, signal) });
  if (q.isPending) return <Skeleton className="h-16 w-full" />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} />;
  if (q.data.checks.length === 0) return <p className="text-sm text-ink-soft">No checks recorded yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm" data-testid="purchase-history">
        <thead className="text-xs text-ink-soft"><tr><th className="py-1 pr-3">Checked</th><th className="pr-3">Result</th><th className="pr-3">Comparable price</th><th>Difference</th></tr></thead>
        <tbody>
          {q.data.checks.map((c) => (
            <tr key={c.checked_at} className="border-t border-line">
              <td className="py-1.5 pr-3 text-ink-soft">{formatDateTime(c.checked_at)}</td>
              <td className="pr-3">{STATUS[c.status]?.label ?? c.status}</td>
              <td className="tabular pr-3">{c.comparable_price != null ? `${formatINR(c.comparable_price)}${c.retailer ? ` · ${c.retailer}` : ""}` : "—"}</td>
              <td className="tabular">{c.difference != null ? (c.difference > 0 ? `${formatINR(c.difference)} cheaper` : c.difference < 0 ? `${formatINR(-c.difference)} dearer` : "Same") : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PurchaseCard({ p }: { p: Purchase }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const done = () => { qc.invalidateQueries({ queryKey: ["purchases"] }); qc.invalidateQueries({ queryKey: ["purchase-notifications"] }); qc.invalidateQueries({ queryKey: ["purchase-history", p.id] }); };
  const update = useMutation({ mutationFn: (v: Parameters<typeof api.updatePurchase>[1]) => api.updatePurchase(p.id, v), onSuccess: () => { setEditing(false); done(); } });
  const del = useMutation({ mutationFn: () => api.deletePurchase(p.id), onSuccess: done });
  const check = useMutation({ mutationFn: () => api.checkPurchase(p.id), onSuccess: done });
  const st = STATUS[p.status] ?? STATUS.pending;
  const comp = p.comparable;
  const href = safeHref(comp.product_url);
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <Card className="p-4" data-testid={`purchase-${p.id}`}>
      <div className="flex flex-wrap items-start gap-4">
        <div className="h-16 w-16 shrink-0"><ProductImage src={p.image_url} alt={p.product_title} /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/product/${p.product_id}`} className="font-semibold hover:text-brand">{p.product_title}</Link>
            <Badge tone={st.tone}>{st.label}</Badge>
            {!p.notify && <Badge tone="slate">Notifications off</Badge>}
            {p.notify && p.email && <Badge tone="brand">E-mail alerts on</Badge>}
          </div>
          {variant(p) && <p className="text-xs text-ink-soft">{variant(p)}</p>}
          <p className="mt-1 text-sm">
            Paid <strong className="tabular">{formatINR(p.purchase_price)}</strong> at {p.retailer} on {p.purchase_date}
            {p.order_ref && <span className="text-ink-soft"> · Ref {p.order_ref}</span>}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button aria-label="Check now" title="Re-check prices now" onClick={() => check.mutate()} disabled={check.isPending} className="rounded-lg p-2 text-ink-soft hover:bg-surface-2 disabled:opacity-50">
            {check.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button aria-label="Edit purchase" onClick={() => setEditing((e) => !e)} className="rounded-lg p-2 text-ink-soft hover:bg-surface-2"><Pencil className="h-4 w-4" /></button>
          {confirmDelete ? (
            <span className="flex items-center gap-1 text-xs">
              <button onClick={() => del.mutate()} className="rounded-lg bg-danger/15 px-2 py-1 font-semibold text-danger">Delete</button>
              <button onClick={() => setConfirmDelete(false)} className="rounded-lg px-2 py-1 text-ink-soft">Keep</button>
            </span>
          ) : (
            <button aria-label="Delete purchase" onClick={() => setConfirmDelete(true)} className="rounded-lg p-2 text-ink-soft hover:bg-surface-2"><Trash2 className="h-4 w-4" /></button>
          )}
        </div>
      </div>

      {check.isError && <p role="alert" className="mt-2 text-sm text-danger">{(check.error as Error).message}</p>}

      {editing ? (
        <div className="mt-4 border-t border-line pt-4">
          <PurchaseForm
            initial={{ retailer: p.retailer, purchase_price: p.purchase_price, purchase_date: p.purchase_date, order_ref: p.order_ref,
              return_deadline: p.return_deadline, protection_deadline: p.protection_deadline, expected_costs: p.expected_costs, notify: p.notify, email: p.email }}
            submitLabel="Save changes" pending={update.isPending} error={update.error ? (update.error as ApiError).message : null}
            onSubmit={(v) => update.mutate(v)} onCancel={() => setEditing(false)}
          />
        </div>
      ) : (
        <div className="mt-4 grid gap-4 border-t border-line pt-4 md:grid-cols-2">
          <div className="space-y-2">
            {comp.status === "comparable" && comp.price != null ? (
              <>
                <p className="text-sm text-ink-soft">Lowest comparable verified price now</p>
                <p className="flex flex-wrap items-baseline gap-2">
                  <span className="tabular text-2xl font-bold">{formatINR(comp.price)}</span>
                  <span className="text-sm text-ink-soft">at {comp.retailer}</span>
                  {href && <a href={href} target="_blank" rel="noopener noreferrer nofollow sponsored" className="inline-flex items-center gap-1 text-sm text-brand underline">Open <ExternalLink className="h-3 w-3" /></a>}
                </p>
                {p.difference != null && p.difference_pct != null && (
                  <p className={`tabular text-sm font-semibold ${p.difference > 0 ? "text-success" : "text-ink-soft"}`} data-testid="purchase-difference">
                    {p.difference > 0 ? `${formatINR(p.difference)} (${p.difference_pct.toFixed(Math.abs(p.difference_pct) < 1 ? 2 : 1)}%) cheaper than you paid`
                      : p.difference < 0 ? `${formatINR(-p.difference)} more than you paid` : "Same as what you paid"}
                  </p>
                )}
                {p.comparable_verified_at && <p className="text-xs text-ink-soft">Verified {formatDateTime(p.comparable_verified_at)} · last checked {formatDateTime(p.last_checked_at)}</p>}
              </>
            ) : (
              <div>
                <p className="font-semibold">{comp.status === "stale_data" ? "Prices are stale" : "Comparable offer unavailable"}</p>
                {comp.reason && <p className="text-sm text-ink-soft">{comp.reason}</p>}
                <p className="text-xs text-ink-soft">Last checked {formatDateTime(p.last_checked_at)}</p>
              </div>
            )}
            {p.net_benefit && (
              <div className="rounded-lg border border-line bg-surface-2/60 p-3 text-sm">
                <p>Estimated net benefit: <strong className="tabular">{formatINR(p.net_benefit.amount)}</strong></p>
                <p className="text-xs text-ink-soft">{p.net_benefit.label}. {formatINR(p.net_benefit.inputs.difference)} difference − {formatINR(p.net_benefit.inputs.expected_costs)} your expected costs.</p>
              </div>
            )}
          </div>
          <div className="space-y-2 text-sm">
            {p.deadlines.length > 0 ? (
              <ul className="space-y-1">
                {p.deadlines.map((d) => (
                  <li key={d.kind} className="flex flex-wrap items-center gap-2">
                    <CalendarClock className="h-4 w-4 text-ink-soft" aria-hidden /> {d.label}: {d.date}
                    <Badge tone={DEADLINE_TONE[d.state]}>{d.state === "passed" ? "Passed" : `Ends ${daysText(d.days_left)}`}</Badge>
                  </li>
                ))}
              </ul>
            ) : <p className="text-ink-soft">No deadlines entered. Add your return or price-protection deadline to get reminders.</p>}
            {p.actions.length > 0 && (
              <div>
                <p className="font-semibold">What you can do</p>
                <ul className="mt-1 space-y-0.5 text-ink-soft">{p.actions.map((a) => <li key={a}>• {a}</li>)}</ul>
              </div>
            )}
            {p.notes.length > 0 && <ul className="space-y-0.5 text-xs text-ink-soft">{p.notes.map((n) => <li key={n}>• {n}</li>)}</ul>}
          </div>
        </div>
      )}
      <div className="mt-3">
        <button onClick={() => setShowHistory((s) => !s)} className="inline-flex items-center gap-1 text-xs text-brand hover:underline">
          <History className="h-3.5 w-3.5" aria-hidden /> {showHistory ? "Hide" : "Show"} monitoring history
        </button>
        {showHistory && <div className="mt-2"><PurchaseHistoryList id={p.id} /></div>}
      </div>
    </Card>
  );
}

export function PurchasesPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["purchases"], queryFn: ({ signal }) => api.purchases(signal), refetchInterval: 120_000 });
  const n = useQuery({ queryKey: ["purchase-notifications"], queryFn: ({ signal }) => api.purchaseNotifications(signal), refetchInterval: 120_000 });
  const markRead = useMutation({ mutationFn: api.markPurchaseNotificationsRead, onSuccess: () => qc.invalidateQueries({ queryKey: ["purchase-notifications"] }) });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold"><ShieldCheck className="h-6 w-6 text-cyan" aria-hidden /> Regret Shield</h1>
        <p className="text-sm text-ink-soft">Track what you bought. BuyWise compares it with verified prices for the exact same variant and reminds you before your deadlines.</p>
      </div>

      {q.isPending ? <Skeleton className="h-48 w-full" /> : q.isError ? <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} /> : (
        <>
          <div className="grid gap-3 sm:grid-cols-3" data-testid="purchase-stats">
            <Card className="p-4"><p className="text-xs text-ink-soft">My purchases</p><p className="text-2xl font-bold">{q.data.items.length}</p></Card>
            <Card className="p-4"><p className="flex items-center gap-1 text-xs text-ink-soft"><TrendingDown className="h-3.5 w-3.5" /> Price drops</p><p className="text-2xl font-bold text-success">{q.data.price_drops.length}</p></Card>
            <Card className="p-4"><p className="flex items-center gap-1 text-xs text-ink-soft"><CalendarClock className="h-3.5 w-3.5" /> Open deadlines</p><p className="text-2xl font-bold">{q.data.deadlines.length}</p></Card>
          </div>

          {q.data.deadlines.length > 0 && (
            <Card className="p-4">
              <h2 className="font-semibold">Deadline alerts</h2>
              <ul className="mt-2 space-y-1 text-sm">
                {q.data.deadlines.map((d) => (
                  <li key={`${d.purchase_id}-${d.kind}`} className="flex flex-wrap items-center gap-2">
                    <Badge tone={DEADLINE_TONE[d.state]}>{d.days_left === 0 ? "Today" : `${d.days_left} day(s)`}</Badge>
                    <span>{d.label} for <Link to={`/product/${q.data.items.find((i) => i.id === d.purchase_id)?.product_id ?? ""}`} className="text-brand hover:underline">{d.product_title}</Link> ends {d.date}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 font-semibold"><BellRing className="h-4 w-4 text-brand" aria-hidden /> Insights & notifications {n.data && n.data.unread > 0 && <Badge tone="brand">{n.data.unread} new</Badge>}</h2>
              {n.data && n.data.unread > 0 && <button onClick={() => markRead.mutate()} className="text-xs text-brand hover:underline">Mark all as read</button>}
            </div>
            {n.isPending ? <Skeleton className="mt-2 h-10 w-full" /> : n.isError ? <p className="mt-2 text-sm text-danger">{(n.error as Error).message}</p> :
              n.data.items.length === 0 ? <p className="mt-2 text-sm text-ink-soft">No notifications yet.</p> : (
                <ul className="mt-2 space-y-1.5 text-sm" data-testid="purchase-notifications">
                  {n.data.items.slice(0, 20).map((x) => (
                    <li key={x.id} className={x.read ? "text-ink-soft" : ""}>
                      <span className="text-xs text-ink-soft">{formatDateTime(x.created_at)} · </span>{x.message}
                      {x.email_status === "sent" && <span className="ml-1 text-xs text-success">· e-mailed</span>}
                      {(x.email_status === "failed" || x.email_status === "not_configured") && <span className="ml-1 text-xs text-warning">· e-mail not sent</span>}
                    </li>
                  ))}
                </ul>
              )}
            <p className="mt-3 text-xs text-ink-soft">
              {q.data.monitoring.scheduler_enabled ? q.data.monitoring.note : "Automatic monitoring is switched off on this server – use “Check now” on a purchase."}{" "}
              A drop is flagged when it is at least {q.data.thresholds.min_drop_pct}% and {formatINR(q.data.thresholds.min_drop_amount)}.
              {q.data.email_ready ? "Notifications appear here, and by e-mail for purchases with an e-mail address." : "Notifications appear here. E-mail isn't set up on this server yet (see Diagnostics)."} A lower price elsewhere doesn't mean your store will refund the difference or accept a return.
            </p>
          </Card>

          <section className="space-y-3">
            <h2 className="text-lg font-semibold">My purchases</h2>
            {q.data.items.length === 0 ? (
              <EmptyState title="No purchases tracked yet">Open any product and choose “Track my purchase”.</EmptyState>
            ) : q.data.items.map((p) => <PurchaseCard key={p.id} p={p} />)}
          </section>
        </>
      )}
    </div>
  );
}

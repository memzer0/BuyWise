import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Card, EmptyState, ErrorState, Skeleton } from "../components/ui";
import { formatDateTime, formatINR, safeHref } from "../utils/format";

const DELIVERY: Record<string, { tone: "green" | "amber" | "red" | "slate"; label: string }> = {
  recorded: { tone: "green", label: "Shown in app" },
  sent: { tone: "green", label: "E-mail sent" },
  failed: { tone: "red", label: "Delivery failed" },
  not_configured: { tone: "amber", label: "E-mail not configured" },
};

export function AlertsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alerts"], queryFn: ({ signal }) => api.alerts(signal), refetchInterval: 60_000 });
  const del = useMutation({ mutationFn: (id: number) => api.deleteAlert(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }) });
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Price alerts</h1>
        <p className="text-sm text-ink-soft">Alerts fire once per price drop, using only verified, current offers.</p>
      </div>
      {q.isPending ? <Skeleton className="h-40 w-full" /> : q.isError ? <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} /> :
        q.data.alerts.length === 0 ? <EmptyState title="No alerts yet">Open any product and set a target price.</EmptyState> : (
          <div className="space-y-3">
            {q.data.alerts.map((a) => (
              <Card key={a.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link to={`/product/${a.product_id}`} className="font-medium hover:text-brand">{a.product_title}</Link>
                    <p className="text-sm text-ink-soft">Target {formatINR(a.target_price)} · {a.channel === "email" ? `E-mail to ${a.email}` : "In-app"} · {a.armed ? "Waiting for price drop" : "Triggered – re-arms when price rises above target"}</p>
                  </div>
                  <button aria-label="Delete alert" onClick={() => del.mutate(a.id)} className="rounded-lg p-2 text-ink-soft hover:bg-surface-2"><Trash2 className="h-4 w-4" /></button>
                </div>
                {a.events.length > 0 && (
                  <ul className="mt-3 space-y-1 border-t border-line pt-3 text-sm">
                    {a.events.map((e, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2">
                        <span className="tabular font-semibold">{formatINR(e.triggered_price)}</span> at {e.retailer}
                        <span className="text-ink-soft">· {formatDateTime(e.created_at)}</span>
                        <Badge tone={(DELIVERY[e.delivery_status] ?? DELIVERY.failed).tone} title={e.delivery_error ?? undefined}>{(DELIVERY[e.delivery_status] ?? { label: e.delivery_status }).label}</Badge>
                        {safeHref(e.offer_url) && <a className="text-brand underline" href={safeHref(e.offer_url)!} target="_blank" rel="noopener noreferrer nofollow sponsored">Open listing</a>}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            ))}
          </div>
        )}
    </div>
  );
}

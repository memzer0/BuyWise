import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, TrendingDown, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ProductImage } from "../components/ProductCard";
import { Card, EmptyState, ErrorState, FreshnessBadge, Skeleton } from "../components/ui";
import { formatINR } from "../utils/format";

export function WatchlistPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["watchlist"], queryFn: ({ signal }) => api.watchlist(signal) });
  const remove = useMutation({ mutationFn: (id: number) => api.removeWatch(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }) });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Watchlist</h1>
        <p className="text-sm text-ink-soft">Watched products are refreshed automatically on the server's schedule. Stored for this browser only.</p>
      </div>
      {q.isPending ? <Skeleton className="h-40 w-full" /> : q.isError ? <ErrorState message={(q.error as Error).message} onRetry={() => q.refetch()} /> :
        q.data.items.length === 0 ? <EmptyState title="Nothing on your watchlist yet">Open a product and choose “Add to watchlist”.</EmptyState> : (
          <Card className="divide-y divide-line">
            {q.data.items.map((it) => (
              <div key={it.id} className="grid grid-cols-[64px_1fr_auto] items-center gap-4 p-4">
                <ProductImage src={it.image_url} alt={it.title} className="h-16 w-16" />
                <div className="min-w-0">
                  <Link to={`/product/${it.id}`} className="line-clamp-2 font-medium hover:text-brand">{it.title}</Link>
                  <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                    <span className="tabular font-semibold">{formatINR(it.best_price)}</span>
                    {it.price_change !== null && it.price_change !== 0 && (
                      <span className={`inline-flex items-center gap-1 ${it.price_change < 0 ? "text-success" : "text-danger"}`}>
                        {it.price_change < 0 ? <TrendingDown className="h-4 w-4" aria-hidden /> : <TrendingUp className="h-4 w-4" aria-hidden />}
                        {formatINR(Math.abs(it.price_change))} since added
                      </span>
                    )}
                    <span className="text-ink-soft">Lowest observed: {formatINR(it.historical_min)}</span>
                    <span className="text-ink-soft">Alert: {it.alert ? `${formatINR(it.alert.target_price)}` : <Link to={`/product/${it.id}#alert`} className="text-brand underline">set one</Link>}</span>
                    <FreshnessBadge status={it.best_freshness ?? "unavailable"} at={it.last_verified_at} />
                  </div>
                </div>
                <button aria-label={`Remove ${it.title} from watchlist`} onClick={() => remove.mutate(it.id)} className="rounded-lg p-2 text-ink-soft hover:bg-surface-2">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </Card>
        )}
    </div>
  );
}

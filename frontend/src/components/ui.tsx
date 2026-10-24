import { AlertTriangle, CheckCircle2, Clock, PackageSearch, RefreshCw, XCircle } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";
import type { Freshness, LinkType, ProviderRun } from "../types/api";
import { timeAgo } from "../utils/format";

export function Card({ children, className = "", ...rest }: { children: ReactNode; className?: string } & HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={`glass rounded-2xl border ${className}`}>{children}</div>;
}

type Tone = "green" | "amber" | "red" | "slate" | "teal" | "brand" | "cyan" | "sun";
const TONES: Record<Tone, string> = {
  green: "bg-success/10 text-success ring-success/30",
  amber: "bg-warning/10 text-warning ring-warning/30",
  red: "bg-danger/10 text-danger ring-danger/30",
  slate: "bg-surface-2 text-ink-soft ring-line",
  teal: "bg-accent-soft text-brand ring-accent/40",
  brand: "bg-brand-soft text-brand ring-brand/30",
  cyan: "bg-sun-soft text-cyan ring-sun/50",
  sun: "bg-sun text-ink ring-sun",
};

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  );
}

const FRESH: Record<Freshness, { tone: Tone; label: string; help: string }> = {
  live: { tone: "cyan", label: "Recently verified", help: "Fetched from the provider during this request." },
  cached: { tone: "slate", label: "Cached", help: "Verified earlier from the provider; not re-fetched just now." },
  stale: { tone: "amber", label: "Stale", help: "Older than the freshness threshold. Not used for best-price ranking." },
  unavailable: { tone: "red", label: "Unavailable", help: "No verified price is available." },
};

export function FreshnessBadge({ status, at }: { status: Freshness | null; at?: string | null }) {
  if (!status) return null;
  const f = FRESH[status];
  return (
    <Badge tone={f.tone} title={`${f.help}${at ? ` Last checked ${new Date(at).toLocaleString("en-IN")}.` : ""}`}>
      <Clock className="h-3 w-3" aria-hidden />
      {f.label}
      {at ? <span className="font-normal">· {timeAgo(at)}</span> : null}
    </Badge>
  );
}

export function LinkTypeBadge({ type }: { type: LinkType }) {
  if (type === "exact_listing") return <Badge tone="green">Exact listing</Badge>;
  if (type === "aggregator_page") return <Badge tone="amber" title="The provider only supplied a Google Shopping page, not the retailer's own listing.">Google Shopping page</Badge>;
  return <Badge tone="red" title="This is not a single-product page.">Not an exact listing</Badge>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-surface-2 ${className}`} />;
}

export function ErrorState({ title, message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <Card className="flex flex-col items-center gap-3 p-8 text-center" >
      <AlertTriangle className="h-8 w-8 text-danger" aria-hidden />
      <div>
        <p className="font-semibold">{title ?? "Something went wrong"}</p>
        <p className="mt-1 text-sm text-ink-soft">{message}</p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm font-medium hover:bg-surface-2">
          <RefreshCw className="h-4 w-4" aria-hidden /> Retry
        </button>
      )}
    </Card>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Card className="flex flex-col items-center gap-2 p-10 text-center">
      <PackageSearch className="h-9 w-9 text-ink-soft" aria-hidden />
      <p className="font-semibold">{title}</p>
      {children && <div className="max-w-xl text-sm text-ink-soft">{children}</div>}
    </Card>
  );
}

const RUN_TONE: Record<ProviderRun["status"], Tone> = {
  ok: "green", empty: "slate", not_configured: "slate", error: "red", rate_limited: "amber", cooling_down: "amber",
};
const RUN_LABEL: Record<ProviderRun["status"], string> = {
  ok: "returned results", empty: "no results", not_configured: "not configured", error: "failed",
  rate_limited: "rate limited", cooling_down: "backing off",
};

export function ProviderStrip({ runs }: { runs: ProviderRun[] }) {
  return (
    <div className="flex flex-wrap gap-2" aria-label="Data provider status">
      {runs.map((r) => (
        <Badge key={r.provider} tone={RUN_TONE[r.status]} title={r.error ?? undefined}>
          {r.status === "ok" ? <CheckCircle2 className="h-3 w-3" aria-hidden /> : r.status === "error" ? <XCircle className="h-3 w-3" aria-hidden /> : null}
          {r.name ?? r.provider}: {RUN_LABEL[r.status]}
          {r.status === "ok" ? ` (${r.listings})` : ""}
        </Badge>
      ))}
    </div>
  );
}

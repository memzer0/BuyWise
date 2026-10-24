import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "../api/client";
import { Badge, Card, ErrorState, Skeleton } from "../components/ui";
import { formatDateTime } from "../utils/format";

const STATE_TONE = { working: "green", configured_untested: "amber", failing: "red", cooling_down: "amber", not_configured: "slate" } as const;
const TOKEN_KEY = "buywise.adminToken";

export function AdminPage() {
  const providers = useQuery({ queryKey: ["providers"], queryFn: ({ signal }) => api.providers(signal), refetchInterval: 30_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => api.health(signal) });
  const [token, setToken] = useState(() => { try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; } });
  const [draft, setDraft] = useState("");
  const diag = useQuery({
    queryKey: ["diagnostics", token],
    queryFn: ({ signal }) => api.diagnostics(token, signal),
    enabled: !!token,
    retry: false,
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Diagnostics</h1>
      {health.data && (
        <Card className="flex flex-wrap gap-6 p-4 text-sm">
          <div><p className="text-ink-soft">API</p><p className="font-semibold">{health.data.app}</p></div>
          <div><p className="text-ink-soft">Database</p><p className="font-semibold">{health.data.database}</p></div>
          <div><p className="text-ink-soft">Live price fetching</p><p className="font-semibold" data-testid="live-status">{health.data.live_price_fetching.replace("_", " ")}</p></div>
          <div><p className="text-ink-soft">Auto-refresh scheduler</p><p className="font-semibold">{health.data.scheduler_running ? "running" : "stopped"}</p></div>
        </Card>
      )}
      {health.isError && <ErrorState message={(health.error as Error).message} onRetry={() => health.refetch()} />}

      <section>
        <h2 className="mb-2 text-lg font-semibold">Data providers</h2>
        {providers.isPending ? <Skeleton className="h-32 w-full" /> : providers.isError ? <ErrorState message={(providers.error as Error).message} /> : (
          <div className="grid gap-3 md:grid-cols-3">
            {providers.data.providers.map((p) => (
              <Card key={p.id} className="p-4 text-sm">
                <div className="flex items-center justify-between gap-2"><p className="font-semibold">{p.name}</p><Badge tone={STATE_TONE[p.state]}>{p.state.replace("_", " ")}</Badge></div>
                <p className="mt-1 text-xs text-ink-soft">{p.source_type.replace("_", " ")}</p>
                {!p.configured && <p className="mt-2 text-xs">Set in <code>backend/.env</code>: {p.required_env.map((e) => <code key={e} className="mr-1 rounded bg-surface-2 px-1">{e}</code>)}</p>}
                <p className="mt-2 text-xs text-ink-soft">Last success: {formatDateTime(p.last_success_at)}</p>
                {p.last_error && <p className="mt-1 break-words text-xs text-danger">Last error: {p.last_error}</p>}
                <a className="mt-2 inline-block text-xs text-brand underline" href={p.docs_url} target="_blank" rel="noopener noreferrer">Provider documentation</a>
              </Card>
            ))}
          </div>
        )}
        {providers.data && (
          <div className="mt-3 text-xs text-ink-soft">
            <p className="font-medium text-ink">Not integrated directly:</p>
            <ul className="list-inside list-disc">{providers.data.unsupported_sources.map((s) => <li key={s.name}>{s.name} – {s.reason}</li>)}</ul>
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Operational details</h2>
        {!token || (diag.error instanceof ApiError && diag.error.status === 401) ? (
          <form className="flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); setToken(draft); try { sessionStorage.setItem(TOKEN_KEY, draft); } catch { /* ignore */ } }}>
            <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Admin token (ADMIN_TOKEN)" aria-label="Admin token" className="flex-1 rounded-lg border border-line px-3 py-2 text-sm" />
            <button className="rounded-lg btn-gloss bg-accent-strong px-3 py-2 text-sm font-semibold text-white hover:brightness-110">Unlock</button>
          </form>
        ) : null}
        {diag.isError && <p className="mt-2 text-sm text-danger">{(diag.error as Error).message}</p>}
        {diag.data && (
          <div className="space-y-3">
            <EmailTest token={token} configured={Boolean((diag.data.email as { configured?: boolean } | undefined)?.configured)} />
            {(["scheduler", "freshness", "counts"] as const).map((k) => (
              <Card key={k} className="p-4"><p className="mb-1 font-semibold capitalize">{k}</p><pre className="overflow-x-auto text-xs">{JSON.stringify(diag.data[k], null, 2)}</pre></Card>
            ))}
            {(["recent_errors", "recent_jobs", "match_issues"] as const).map((k) => (
              <Card key={k} className="p-4">
                <p className="mb-1 font-semibold">{k.replace("_", " ")}</p>
                <pre className="max-h-72 overflow-auto text-xs">{JSON.stringify(diag.data[k], null, 2)}</pre>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/** Send one test e-mail with the server's SMTP settings (admin only). */
function EmailTest({ token, configured }: { token: string; configured: boolean }) {
  const [to, setTo] = useState("");
  const m = useMutation({ mutationFn: () => api.testEmail(token, to.trim()) });
  return (
    <Card className="p-4 text-sm">
      <p className="mb-1 font-semibold">E-mail notifications</p>
      <p className="mb-3 text-ink-soft">
        {configured ? "E-mail is set up on this server. Send a test to check it reaches your inbox."
          : "E-mail isn't set up yet. Add SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM to backend/.env and restart."}
      </p>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <input type="email" required value={to} onChange={(e) => setTo(e.target.value)} placeholder="you@example.com"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2" aria-label="Send test e-mail to" />
        <button disabled={m.isPending} className="rounded-lg btn-gloss bg-accent-strong px-3 py-2 font-semibold text-white disabled:opacity-60">
          {m.isPending ? "Sending…" : "Send test e-mail"}
        </button>
      </form>
      {m.data && (m.data.status === "sent"
        ? <p className="mt-2 text-success">Sent – check your inbox (and the spam folder).</p>
        : <p className="mt-2 text-danger">Not sent: {m.data.error}</p>)}
      {m.isError && <p className="mt-2 text-danger">{(m.error as Error).message}</p>}
    </Card>
  );
}

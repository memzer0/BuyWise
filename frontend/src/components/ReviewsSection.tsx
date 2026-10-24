import { Info, MessageSquareText, Quote, ShieldCheck, Star, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { AspectSentiment, ReviewAspect, ReviewItem, Reviews } from "../types/api";
import { timeAgo } from "../utils/format";
import { AskTheReviews } from "./reviews/AskTheReviews";
import { Badge, Card } from "./ui";

type SentFilter = "all" | "positive" | "negative" | "mixed";

const STANCE: Record<ReviewAspect["stance"], { tone: "green" | "red" | "amber" | "slate"; label: string }> = {
  praised: { tone: "green", label: "Mostly praised" },
  complaint: { tone: "red", label: "Recurring complaint" },
  mixed: { tone: "amber", label: "Mixed" },
  neutral: { tone: "slate", label: "Mentioned" },
  limited: { tone: "slate", label: "Limited evidence" },
};
const CONF_LABEL = { low: "Low confidence", medium: "Medium confidence", high: "High confidence" } as const;
const TONE_BORDER: Record<AspectSentiment, string> = {
  positive: "border-success/50", negative: "border-danger/50", mixed: "border-warning/50", neutral: "border-line",
};

/** Review intelligence: rating breakdown, aspect analysis with evidence, "ask the reviews", use-case focus,
 *  reliability checks and the reviews themselves – all from the real reviews Google Shopping returns. */
export function ReviewsSection({ r }: { r: Reviews }) {
  const [aspect, setAspect] = useState<string | null>(null);
  const [sent, setSent] = useState<SentFilter>("all");
  const [useCase, setUseCase] = useState<string | null>(null);

  const reviews = r.reviews ?? [];
  const n = r.coverage?.sample_size ?? reviews.length;
  const uc = r.use_cases?.find((u) => u.key === useCase) ?? null;

  // Use-case aspects first (in the order they matter), then everything else – nothing is hidden.
  const aspectRows = useMemo(() => {
    const list = r.aspects ?? [];
    if (!uc) return list.map((a) => ({ a, why: null as string | null, name: a.aspect }));
    const by = new Map(list.map((a) => [a.aspect, a]));
    const first = uc.aspects.map((x) => ({ a: by.get(x.aspect) ?? null, why: x.why as string | null, name: x.aspect }));
    const rest = list.filter((a) => !uc.aspects.some((x) => x.aspect === a.aspect)).map((a) => ({ a, why: null, name: a.aspect }));
    return [...first, ...rest];
  }, [r.aspects, uc]);

  if (!r.available) {
    return (
      <Card className="p-5" data-testid="reviews">
        <h2 className="flex items-center gap-2 text-xl font-bold"><MessageSquareText className="h-5 w-5 text-brand" aria-hidden /> Reviews</h2>
        <p className="mt-2 text-sm text-ink-soft">{r.reason ?? "No reviews yet for this product."}</p>
      </Card>
    );
  }

  const shown = reviews.filter((x) => {
    if (aspect && !x.aspects.includes(aspect)) return false;
    if (sent === "all") return true;
    const s = aspect ? x.aspect_sentiment?.[aspect] : x.sentiment > 0 ? "positive" : x.sentiment < 0 ? "negative" : "neutral";
    return s === sent;
  });
  const selected = aspect ? r.aspects?.find((a) => a.aspect === aspect) ?? null : null;
  const evidence = selected
    ? selected.examples.filter((e) => sent === "all" || (sent === "positive" ? e.sentiment > 0 : sent === "negative" ? e.sentiment < 0
      : reviews[e.review_id]?.aspect_sentiment?.[selected.aspect] === "mixed"))
    : [];
  const total = (r.distribution ?? []).reduce((acc, d) => acc + d.count, 0);

  return (
    <Card data-testid="reviews">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line p-5">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold"><MessageSquareText className="h-5 w-5 text-brand" aria-hidden /> Reviews & what buyers say</h2>
          {r.origin && (
            <p className="mt-1 text-xs text-ink-soft" data-testid="review-origin">
              Live reviews via {r.origin.source}{r.origin.fetched_at ? ` · fetched ${timeAgo(r.origin.fetched_at)}` : ""}
              {r.origin.stores.length > 0 && ` · from ${r.origin.stores.slice(0, 4).join(", ")}${r.origin.stores.length > 4 ? "…" : ""}`}
            </p>
          )}
        </div>
        {r.coverage && n > 0 && (
          <Badge tone={r.coverage.level === "high" ? "green" : r.coverage.level === "medium" ? "amber" : "slate"} title={r.coverage.note}>
            {n} review{n === 1 ? "" : "s"} analysed{r.coverage.coverage_pct != null ? ` · ${r.coverage.coverage_pct}% of ratings` : ""}
          </Badge>
        )}
      </div>

      <div className="grid gap-6 p-5 md:grid-cols-[220px_1fr]">
        <div>
          {r.rating != null && (
            <p className="flex items-baseline gap-2"><span className="text-4xl font-bold tabular">{Number(r.rating).toFixed(1)}</span>
              <Star className="h-5 w-5 fill-warning text-warning" aria-hidden /></p>
          )}
          {r.reviews_count != null && <p className="text-sm text-ink-soft">{r.reviews_count.toLocaleString("en-IN")} ratings</p>}
          {total > 0 && (
            <ul className="mt-3 space-y-1.5" aria-label="Rating breakdown">
              {r.distribution!.map((d) => (
                <li key={d.stars} className="flex items-center gap-2 text-xs">
                  <span className="w-6 tabular text-ink-soft">{d.stars}★</span>
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <span className={`block h-full rounded-full ${d.stars >= 4 ? "bg-success" : d.stars === 3 ? "bg-warning" : "bg-danger"}`}
                      style={{ width: `${(d.count / total) * 100}%` }} />
                  </span>
                  <span className="w-12 text-right tabular text-ink-soft">{d.count.toLocaleString("en-IN")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-soft">Review summary</p>
          <p className="mt-1 text-base" data-testid="review-summary">
            {r.summary ?? (n ? "No aspect comes up in more than one review yet." : "No written reviews to analyse yet.")}
          </p>
          {r.coverage && n > 0 && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-ink-soft" data-testid="review-coverage">
              <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />{r.coverage.note}
            </p>
          )}
          {(r.insights ?? []).filter((i) => i.type !== "point").length > 0 && (
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              {r.insights!.filter((i) => i.type !== "point").map((i) => (
                <p key={i.type + i.text} className={`flex items-start gap-2 text-sm ${i.type === "pro" ? "text-success" : "text-danger"}`}>
                  {i.type === "pro" ? <ThumbsUp className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> : <ThumbsDown className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}
                  <span className="text-ink">{i.text}</span>
                </p>
              ))}
              <p className="text-[11px] text-ink-soft sm:col-span-2">Pros and cons as summarised by Google Shopping.</p>
            </div>
          )}
        </div>
      </div>

      {n > 0 && (
        <div className="space-y-5 border-t border-line p-5">
          {(r.use_cases ?? []).length > 0 && (
            <div>
              <p className="text-sm font-semibold">What will you use it for? <span className="font-normal text-ink-soft">(optional)</span></p>
              <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label="Use case">
                {r.use_cases!.map((u) => (
                  <button key={u.key} type="button" role="radio" aria-checked={useCase === u.key}
                    onClick={() => setUseCase(useCase === u.key ? null : u.key)}
                    className={`press rounded-full border px-3 py-1 text-sm ${useCase === u.key ? "border-accent bg-accent-soft text-brand" : "border-line text-ink-soft hover:text-ink"}`}>
                    {u.label}
                  </button>
                ))}
              </div>
              {uc && (
                <p className="mt-2 text-xs text-ink-soft">
                  Aspects that matter for {uc.label.toLowerCase()} are shown first. Everything else – including complaints – is still listed.
                </p>
              )}
            </div>
          )}

          <div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">What reviewers say about…</p>
              <div className="flex gap-1" role="radiogroup" aria-label="Sentiment filter">
                {(["all", "positive", "negative", "mixed"] as SentFilter[]).map((s) => (
                  <button key={s} type="button" role="radio" aria-checked={sent === s} onClick={() => setSent(s)}
                    className={`rounded-full px-2.5 py-0.5 text-xs capitalize ${sent === s ? "bg-ink text-white" : "text-ink-soft hover:text-ink"}`}>{s}</button>
                ))}
              </div>
            </div>
            {aspectRows.length === 0 ? (
              <p className="mt-2 text-sm text-ink-soft">The reviews don't mention specific aspects such as battery, camera or performance.</p>
            ) : (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="aspect-grid">
                {aspectRows.map(({ a, why, name }) => (
                  <li key={name}>
                    {a ? (
                      <button type="button" onClick={() => setAspect(aspect === name ? null : name)} aria-pressed={aspect === name}
                        className={`w-full rounded-xl border p-3 text-left transition ${aspect === name ? "border-brand bg-brand-soft" : "border-line bg-surface-2/40 hover:border-brand/50"}`}
                        data-testid="aspect-card">
                        <span className="flex items-center justify-between gap-2">
                          <span className="font-semibold">{name}</span>
                          <Badge tone={STANCE[a.stance].tone}>{STANCE[a.stance].label}</Badge>
                        </span>
                        <AspectBar a={a} />
                        <span className="mt-1 block text-xs text-ink-soft">
                          {a.mentions} of {n} reviews ({Math.round(a.share * 100)}%) · {a.positive}+ / {a.negative}−{a.mixed ? ` / ${a.mixed} mixed` : ""} · {CONF_LABEL[a.confidence]}
                        </span>
                        {why && <span className="mt-1 block text-xs text-brand">Why it matters: {why}</span>}
                      </button>
                    ) : (
                      <div className="rounded-xl border border-dashed border-line p-3 text-sm" data-testid="aspect-missing">
                        <span className="font-semibold">{name}</span>
                        <span className="block text-xs text-ink-soft">None of the {n} reviews mention this.</span>
                        {why && <span className="mt-1 block text-xs text-brand">Why it matters: {why}</span>}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {selected && (
              <div className="mt-3 rounded-xl border border-line p-3" data-testid="aspect-evidence">
                <p className="flex items-center justify-between text-sm font-semibold">
                  Evidence for {selected.aspect.toLowerCase()}
                  <button type="button" onClick={() => setAspect(null)} className="rounded p-1 text-ink-soft hover:text-ink" aria-label="Clear aspect filter">
                    <X className="h-4 w-4" />
                  </button>
                </p>
                {evidence.length === 0 ? (
                  <p className="mt-1 text-sm text-ink-soft">No {sent === "all" ? "" : `${sent} `}excerpts about {selected.aspect.toLowerCase()}.</p>
                ) : (
                  <ul className="mt-2 space-y-2">
                    {evidence.map((e) => {
                      const rv = reviews[e.review_id];
                      return (
                        <li key={e.review_id + e.text} className={`border-l-2 pl-3 text-sm ${e.sentiment > 0 ? "border-success/50" : e.sentiment < 0 ? "border-danger/50" : "border-line"}`}>
                          <Quote className="mr-1 inline h-3 w-3 text-ink-soft" aria-hidden />{e.text}
                          {rv && <span className="block text-xs text-ink-soft">{[rv.rating != null ? `${rv.rating}★` : null, rv.user_name, rv.source, rv.date].filter(Boolean).join(" · ")}</span>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </div>

          <AskTheReviews r={r} useCase={useCase} />

          {r.reliability && <Reliability rel={r.reliability} />}
        </div>
      )}

      {reviews.length > 0 && (
        <div className="border-t border-line">
          <p className="px-5 pt-4 text-sm font-semibold">
            Customer reviews ({shown.length}{shown.length !== reviews.length ? ` of ${reviews.length}` : ""})
            {(aspect || sent !== "all") && (
              <button type="button" onClick={() => { setAspect(null); setSent("all"); }} className="ml-2 text-xs font-normal text-brand hover:underline">
                Clear filters
              </button>
            )}
          </p>
          <ul className="grid gap-3 p-5 md:grid-cols-2">
            {shown.map((x) => <ReviewCard key={x.id} x={x} focus={aspect} />)}
            {shown.length === 0 && <li className="text-sm text-ink-soft">No reviews match these filters.</li>}
          </ul>
          {r.method_note && <p className="px-5 pb-5 text-xs text-ink-soft">{r.method_note}</p>}
        </div>
      )}
    </Card>
  );
}

function AspectBar({ a }: { a: ReviewAspect }) {
  const seg: [number, string][] = [[a.positive, "bg-success"], [a.mixed, "bg-warning"], [a.negative, "bg-danger"], [a.neutral, "bg-line"]];
  return (
    <span className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
      {seg.map(([v, cls]) => v > 0 && <span key={cls} className={cls} style={{ width: `${(v / Math.max(1, a.mentions)) * 100}%` }} />)}
    </span>
  );
}

function Reliability({ rel }: { rel: NonNullable<Reviews["reliability"]> }) {
  return (
    <details className="rounded-xl border border-line p-4" data-testid="review-reliability">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4 text-brand" aria-hidden /> Review reliability</span>
        <span className="text-xs text-ink-soft">
          {rel.signals.length ? `${rel.signals.length} pattern${rel.signals.length === 1 ? "" : "s"} found` : "No suspicious patterns found"}
        </span>
      </summary>
      <div className="mt-3 space-y-3 text-sm">
        {rel.signals.map((s) => (
          <div key={s.kind} className="rounded-lg bg-warning/10 p-3">
            <p className="font-semibold">{s.label}</p>
            <p className="text-ink-soft">{s.detail}</p>
          </div>
        ))}
        <p className="text-xs text-ink-soft">Checked: {rel.checked.join(" · ")}.</p>
        <ul className="space-y-0.5 text-xs text-ink-soft">{rel.limitations.map((l) => <li key={l}>• {l}</li>)}</ul>
        <p className="text-xs text-ink-soft">These are patterns worth knowing about, not proof that any review is fake.</p>
      </div>
    </details>
  );
}

function ReviewCard({ x, focus }: { x: ReviewItem; focus: string | null }) {
  const tone = focus ? x.aspect_sentiment?.[focus] ?? "neutral" : "neutral";
  return (
    <li className={`rounded-xl border bg-surface-2/50 p-4 ${focus ? TONE_BORDER[tone] : "border-line"}`} data-testid="review-card">
      <div className="flex flex-wrap items-center gap-2">
        {x.rating != null && <span className="inline-flex items-center gap-0.5 rounded bg-success/15 px-1.5 py-0.5 text-xs font-semibold text-success">{x.rating}<Star className="h-3 w-3 fill-success" aria-hidden /></span>}
        {x.title && <span className="font-semibold">{x.title}</span>}
      </div>
      {x.text && <p className="mt-2 whitespace-pre-line text-sm">{x.text}</p>}
      {x.aspects.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-1">
          {x.aspects.map((a) => {
            const s = x.aspect_sentiment?.[a];
            return <Badge key={a} tone={s === "positive" ? "green" : s === "negative" ? "red" : s === "mixed" ? "amber" : "slate"}>{a}</Badge>;
          })}
        </p>
      )}
      {x.signals.length > 0 && (
        <p className="mt-2 text-xs text-warning">
          Reliability note: {x.signals.join(" · ")}{x.counted === false ? " (not counted twice in the analysis)" : ""}
        </p>
      )}
      <p className="mt-2 text-xs text-ink-soft">{[x.user_name, x.source, x.date].filter(Boolean).join(" · ")}</p>
    </li>
  );
}

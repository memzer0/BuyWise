import { MessageCircleQuestion, Quote, Search, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { API_BASE } from "../../api/client";
import type { Reviews } from "../../types/api";
import { askReviews, type ReviewAnswer } from "./askReviews";

const TONE_CLS = { positive: "border-success/50", negative: "border-danger/50", mixed: "border-warning/50", neutral: "border-line" } as const;

type Ai = { state: "idle" | "loading" | "ok" | "none" | "withheld"; text?: string };

/** Ask a question. The instant answer is assembled from the review statistics and verbatim review sentences; when the
 *  server has an AI key it also writes a short summary of those same quotes, citing them as [1], [2] … */
export function AskTheReviews({ r, useCase }: { r: Reviews; useCase: string | null }) {
  const { id } = useParams();
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState<{ q: string; a: ReviewAnswer } | null>(null);
  const [ai, setAi] = useState<Ai>({ state: "idle" });
  const ctrl = useRef<AbortController | null>(null);
  useEffect(() => () => ctrl.current?.abort(), []);

  const uc = r.use_cases?.find((u) => u.key === useCase);
  const suggestions = [
    "How is the battery life?", "Does it heat up?", "Any durability problems?", "What do people complain about?",
    uc ? `Is it good for ${uc.label.toLowerCase()}?` : "Is it good for gaming?",
  ];

  async function fetchAi(question: string, a: ReviewAnswer) {
    ctrl.current?.abort();
    if (!id || a.status !== "answered" || a.excerpts.length === 0) { setAi({ state: "idle" }); return; }
    const c = new AbortController();
    ctrl.current = c;
    setAi({ state: "loading" });
    try {
      const res = await fetch(`${API_BASE}/api/products/${id}/reviews/ask`, {
        method: "POST", signal: c.signal, headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question, use_case: useCase, aspects: a.aspects,
          excerpts: a.excerpts.map((e) => ({ review_id: e.review.id, text: e.text })) }),
      });
      const body = res.ok ? await res.json() : null;
      if (c.signal.aborted) return;
      if (body?.status === "ok" && body.answer) setAi({ state: "ok", text: body.answer });
      else setAi({ state: body?.status === "rejected" ? "withheld" : "none" });
    } catch {
      if (!c.signal.aborted) setAi({ state: "none" });
    }
  }

  const ask = (text: string) => {
    if (!text.trim()) return;
    setQ(text);
    const a = askReviews(text, r, useCase);
    setAsked({ q: text, a });
    void fetchAi(text, a);
  };

  return (
    <div className="rounded-xl border border-line bg-surface-2/40 p-4" data-testid="ask-reviews">
      <p className="flex items-center gap-2 font-semibold"><MessageCircleQuestion className="h-4 w-4 text-brand" aria-hidden /> Ask the reviews</p>
      <p className="text-xs text-ink-soft">Answers use only what these reviews say – quotes are word for word.</p>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <label htmlFor="ask-reviews-input" className="sr-only">Question about this product's reviews</label>
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-line bg-surface px-3 focus-within:border-brand">
          <Search className="h-4 w-4 shrink-0 text-ink-soft" aria-hidden />
          <input id="ask-reviews-input" value={q} onChange={(e) => setQ(e.target.value)} maxLength={160}
            placeholder="e.g. Does the battery last a full day?" className="w-full bg-transparent py-2 text-sm outline-none" />
        </div>
        <button type="submit" disabled={!q.trim()} className="rounded-xl btn-gloss bg-accent-strong px-4 text-sm font-semibold text-white disabled:opacity-50">Ask</button>
      </form>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {suggestions.map((s) => (
          <button key={s} type="button" onClick={() => ask(s)}
            className="press rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-soft hover:text-ink">{s}</button>
        ))}
      </div>

      {asked && (
        <div className="mt-4 space-y-3" data-testid="review-answer" aria-live="polite">
          <p className="text-sm font-semibold">“{asked.q}”</p>
          {ai.state === "loading" && (
            <p className="flex items-center gap-2 text-xs text-ink-soft" data-testid="ai-loading">
              <Sparkles className="h-3.5 w-3.5 animate-pulse text-brand" aria-hidden /> Writing a short summary of the quotes…
            </p>
          )}
          {ai.state === "ok" && (
            <div className="rounded-lg border border-brand/30 bg-surface p-3 text-sm" data-testid="ai-answer">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-brand"><Sparkles className="h-3.5 w-3.5" aria-hidden /> AI summary of the quotes below</p>
              <p>{ai.text}</p>
            </div>
          )}
          {ai.state === "withheld" && (
            <p className="text-xs text-ink-soft" data-testid="ai-withheld">The AI summary was withheld because it went beyond what the quotes say.</p>
          )}
          <div className={`rounded-lg p-3 text-sm ${asked.a.status === "insufficient" ? "bg-warning/10" : "bg-brand-soft"}`}>
            {asked.a.lines.map((l) => <p key={l}>{l}</p>)}
            {asked.a.status === "insufficient" && <p className="mt-1 text-xs text-ink-soft">Not enough evidence in the available reviews – try the store page for more reviews.</p>}
            {asked.a.caveat && asked.a.status === "answered" && <p className="mt-2 text-xs text-ink-soft">{asked.a.caveat}</p>}
          </div>
          {asked.a.excerpts.length > 0 && (
            <ol className="space-y-2" aria-label="Supporting review excerpts">
              {asked.a.excerpts.map((e, i) => (
                <li key={e.review.id} className={`border-l-2 pl-3 text-sm ${TONE_CLS[e.tone]}`} data-testid="answer-excerpt">
                  <span className="mr-1 text-xs font-semibold text-brand">[{i + 1}]</span>
                  <Quote className="mr-1 inline h-3 w-3 text-ink-soft" aria-hidden />{e.text}
                  <span className="block text-xs text-ink-soft">
                    {[e.review.rating != null ? `${e.review.rating}★` : null, e.review.user_name, e.review.source, e.review.date].filter(Boolean).join(" · ")}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

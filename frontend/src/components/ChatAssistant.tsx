import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, SendHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { LogoMark } from "./OrbitMark";

type Msg = { role: "user" | "assistant"; content: string };
const STORE_KEY = "buywise.chat";

const PRODUCT_PROMPTS = ["Should I buy this now?", "Which store is cheapest?", "Is this a good deal?", "Any bank offers?"];
const GENERAL_PROMPTS = ["How does BuyWise work?", "Best time to buy a phone?", "What is the deal score?", "What is Regret Shield?"];

/** Minimal formatting for replies: paragraphs, "- " bullets and **bold**. No HTML from the model is rendered. */
function Rich({ text }: { text: string }) {
  const inline = (s: string): ReactNode[] => s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
  return (
    <div className="space-y-1.5">
      {text.split(/\n+/).map((line, i) => {
        const bullet = /^\s*[-*•]\s+/.test(line);
        return bullet
          ? <p key={i} className="flex gap-1.5"><span aria-hidden>•</span><span>{inline(line.replace(/^\s*[-*•]\s+/, ""))}</span></p>
          : <p key={i}>{inline(line)}</p>;
      })}
    </div>
  );
}

/** Floating "Ask BuyWise AI" chat in the bottom-right corner. On a product page it answers about that product using
 *  BuyWise's own data (current store prices, deal score, history); the AI key stays on the server. */
export function ChatAssistant() {
  const loc = useLocation();
  const productId = /^\/product\/(\d+)/.exec(loc.pathname)?.[1];
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    try { return JSON.parse(sessionStorage.getItem(STORE_KEY) ?? "[]") as Msg[]; } catch { return []; }
  });
  const listRef = useRef<HTMLDivElement>(null);
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: ({ signal }) => api.assistantStatus(signal), enabled: open, staleTime: 60_000 });

  useEffect(() => { try { sessionStorage.setItem(STORE_KEY, JSON.stringify(msgs.slice(-30))); } catch { /* ignore */ } }, [msgs]);

  const send = useMutation({
    mutationFn: (history: Msg[]) => api.assistantChat(history, productId ? Number(productId) : null),
    onSuccess: (r) => setMsgs((m) => [...m, { role: "assistant", content: r.reply }]),
  });

  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [msgs, open, send.isPending]);

  const ask = (text: string) => {
    const t = text.trim();
    if (!t || send.isPending) return;
    const next = [...msgs, { role: "user" as const, content: t }];
    setMsgs(next);
    setDraft("");
    send.mutate(next);
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); ask(draft); };
  const prompts = productId ? PRODUCT_PROMPTS : GENERAL_PROMPTS;
  const notConfigured = status.data && !status.data.configured;

  return (
    <>
      {!open && (
        <button type="button" onClick={() => setOpen(true)} aria-label="Ask BuyWise AI" data-testid="chat-open"
          className="liquid fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full py-2 pl-2 pr-4 text-sm font-semibold text-ink transition hover:-translate-y-0.5">
          <span className="relative"><LogoMark size={36} /><Sparkles className="absolute -right-1 -top-1 h-4 w-4 text-sun drop-shadow" aria-hidden /></span>
          Ask BuyWise AI
        </button>
      )}
      {open && (
        <section role="dialog" aria-label="BuyWise AI assistant" data-testid="chat-panel"
          className="liquid liquid-strong fixed bottom-4 right-4 z-40 flex h-[min(560px,calc(100vh-6rem))] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-3xl">
          <header className="flex items-center gap-2 border-b border-white/60 px-4 py-3">
            <LogoMark size={30} />
            <div className="min-w-0 flex-1">
              <p className="font-bold leading-tight">BuyWise AI</p>
              <p className="truncate text-[11px] text-ink-soft">{productId ? "Answers about this product using BuyWise prices" : "Ask about products, prices and BuyWise"}</p>
            </div>
            {msgs.length > 0 && <button type="button" onClick={() => setMsgs([])} className="rounded-lg px-2 py-1 text-xs text-ink-soft hover:bg-white/60">Clear</button>}
            <button type="button" onClick={() => setOpen(false)} aria-label="Close assistant" className="rounded-lg p-1.5 hover:bg-white/60"><X className="h-4 w-4" /></button>
          </header>

          <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm" aria-live="polite">
            {msgs.length === 0 && (
              <div className="space-y-3">
                <p className="rounded-2xl bg-white/70 px-3 py-2">Hi! I can help you decide what to buy and when. {productId ? "Ask me about this product." : "What are you shopping for?"}</p>
                <div className="flex flex-wrap gap-1.5">
                  {prompts.map((p) => (
                    <button key={p} type="button" onClick={() => ask(p)} className="rounded-full bg-accent-soft px-3 py-1 text-xs font-medium text-brand hover:bg-accent/15">{p}</button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex"}>
                <div className={`max-w-[85%] rounded-2xl px-3 py-2 ${m.role === "user" ? "btn-gloss bg-accent-strong text-white" : "bg-white/80 text-ink ring-1 ring-white"}`}>
                  {m.role === "assistant" ? <Rich text={m.content} /> : m.content}
                </div>
              </div>
            ))}
            {send.isPending && <p className="flex items-center gap-2 text-ink-soft"><Loader2 className="h-4 w-4 animate-spin" /> Thinking…</p>}
            {send.isError && <p role="alert" className="rounded-xl bg-danger/10 px-3 py-2 text-danger">{(send.error as ApiError).message}</p>}
            {notConfigured && !send.isError && (
              <p className="rounded-xl bg-sun-soft px-3 py-2 text-xs text-ink">The AI assistant isn't set up on this server yet – add a GEMINI_API_KEY to backend/.env and restart BuyWise.</p>
            )}
          </div>

          <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-white/60 p-3">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000} placeholder="Ask anything about this purchase…"
              aria-label="Message" className="min-w-0 flex-1 rounded-xl bg-white/80 px-3 py-2 text-sm outline-none ring-1 ring-white focus:ring-accent/50" />
            <button type="submit" disabled={!draft.trim() || send.isPending} aria-label="Send"
              className="btn-gloss-sun grid h-9 w-9 place-items-center rounded-xl bg-sun text-ink disabled:opacity-50"><SendHorizontal className="h-4 w-4" /></button>
          </form>
          <p className="px-4 pb-2 text-[10px] text-ink-soft">AI can make mistakes. Prices come from BuyWise data – always confirm on the store page.</p>
        </section>
      )}
    </>
  );
}

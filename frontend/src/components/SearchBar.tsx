import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useDebounced } from "../hooks/useDebounced";
import { addRecentSearch, getRecentSearches } from "../hooks/recent";

export function SearchBar({ initial = "", large = false }: { initial?: string; large?: boolean }) {
  const [value, setValue] = useState(initial);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [hint, setHint] = useState<string | null>(null);
  const listId = useId();
  const wrapRef = useRef<HTMLFormElement>(null);
  const debounced = useDebounced(value.trim(), 250);

  useEffect(() => setValue(initial), [initial]);

  // Suggestions come from products the backend has actually tracked; obsolete requests are aborted via signal.
  const sugg = useQuery({
    queryKey: ["suggestions", debounced],
    queryFn: ({ signal }) => api.suggestions(debounced, signal),
    enabled: open && debounced.length >= 2,
    staleTime: 60_000,
  });
  const recent = getRecentSearches().filter((r) => !value || r.toLowerCase().includes(value.toLowerCase())).slice(0, 5);
  const items: { text: string; kind: "recent" | "suggestion" }[] = [
    ...recent.map((t) => ({ text: t, kind: "recent" as const })),
    ...(sugg.data?.suggestions ?? []).filter((s) => !recent.includes(s)).map((t) => ({ text: t, kind: "suggestion" as const })),
  ].slice(0, 8);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function go(q: string) {
    const query = q.trim();
    if (query.length < 2) {
      // tell the shopper why nothing happened instead of silently ignoring the click
      setHint("Type a product name first – e.g. iPhone 16 128GB");
      inputRef.current?.focus();
      return;
    }
    setHint(null);
    addRecentSearch(query);
    setOpen(false);
    const same = location.pathname === "/search" && new URLSearchParams(location.search).get("q") === query;
    if (same) qc.invalidateQueries({ queryKey: ["search"] }); // same search again → fetch it again
    else navigate(`/search?q=${encodeURIComponent(query)}`);
  }

  return (
    <form
      ref={wrapRef}
      role="search"
      className="relative w-full"
      onSubmit={(e) => {
        e.preventDefault();
        go(active >= 0 && items[active] ? items[active].text : value);
      }}
    >
      <label htmlFor={`${listId}-input`} className="sr-only">Search electronics</label>
      <div className={`liquid relative flex items-center gap-2 rounded-2xl focus-within:ring-2 focus-within:ring-accent/40 ${large ? "px-4 py-3" : "px-3 py-2"}`}>
        <Search className={`${large ? "h-5 w-5" : "h-4 w-4"} text-ink-soft`} aria-hidden />
        <input
          id={`${listId}-input`}
          ref={inputRef}
          value={value}
          onChange={(e) => { setValue(e.target.value); setOpen(true); setActive(-1); setHint(null); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, -1)); }
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Search phones, laptops, earbuds… e.g. iPhone 16 128GB"
          className={`w-full bg-transparent outline-none placeholder:text-ink-soft ${large ? "text-lg" : "text-sm"}`}
          role="combobox"
          aria-expanded={open && items.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          maxLength={120}
        />
        <button type="submit" className={`press btn-gloss-sun rounded-xl bg-sun font-semibold text-ink hover:brightness-105 ${large ? "px-5 py-2" : "px-3 py-1.5 text-sm"}`}>
          Compare
        </button>
      </div>
      {hint && <p role="alert" className="absolute left-3 top-full z-20 mt-1 rounded-lg bg-sun px-3 py-1 text-xs font-semibold text-ink shadow">{hint}</p>}
      {open && items.length > 0 && (
        <ul id={listId} role="listbox" className="glass absolute z-20 mt-2 w-full overflow-hidden rounded-2xl border py-1">
          {items.map((it, i) => (
            <li
              key={`${it.kind}-${it.text}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => { e.preventDefault(); go(it.text); }}
              className={`flex cursor-pointer items-center gap-2 px-4 py-2 text-sm ${i === active ? "bg-surface-2" : "hover:bg-surface-2"}`}
            >
              {it.kind === "recent" ? <History className="h-4 w-4 text-ink-soft" aria-hidden /> : <Search className="h-4 w-4 text-ink-soft" aria-hidden />}
              <span className="truncate">{it.text}</span>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

import { Check, GitCompareArrows } from "lucide-react";
import { useState } from "react";
import { compareList, MAX_COMPARE, useCompareList, type CompareItem } from "./compareStore";

/** "Add to compare" toggle used on product cards and the product page. */
export function CompareButton({ item, size = "sm" }: { item: CompareItem; size?: "sm" | "md" }) {
  const list = useCompareList();
  const added = list.some((x) => x.id === item.id);
  const [full, setFull] = useState(false);
  const toggle = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (added) { compareList.remove(item.id); setFull(false); return; }
    setFull(!compareList.add(item));
  };
  return (
    <span className="relative inline-flex">
      <button type="button" onClick={toggle} aria-pressed={added} data-testid="compare-toggle"
        className={`press inline-flex items-center gap-1.5 rounded-full border font-medium transition ${size === "md" ? "px-3 py-1.5 text-sm" : "px-2.5 py-1 text-xs"} ${
          added ? "border-brand bg-brand-soft text-brand" : "border-line bg-surface/90 text-ink-soft hover:border-brand hover:text-brand"}`}>
        {added ? <Check className="h-3.5 w-3.5" aria-hidden /> : <GitCompareArrows className="h-3.5 w-3.5" aria-hidden />}
        {added ? "Added to compare" : "Compare"}
      </button>
      {full && (
        <span role="alert" className="absolute right-0 top-full z-20 mt-1 w-48 rounded-lg bg-ink px-2 py-1 text-[11px] text-white shadow">
          You can compare up to {MAX_COMPARE} products. Remove one first.
        </span>
      )}
    </span>
  );
}

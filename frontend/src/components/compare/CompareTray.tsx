import { GitCompareArrows, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { ProductImage } from "../ProductCard";
import { compareList, MAX_COMPARE, useCompareList } from "./compareStore";

/** Floating bar listing the products picked for comparison (bottom-left, clear of the chat button). */
export function CompareTray() {
  const list = useCompareList();
  const loc = useLocation();
  if (list.length === 0 || loc.pathname === "/compare") return null;
  const ready = list.length >= 2;
  return (
    <div className="liquid fixed bottom-4 left-4 z-40 flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-2xl p-2 pr-3 shadow-lg sm:max-w-xl"
      role="region" aria-label="Products to compare" data-testid="compare-tray">
      <ul className="flex min-w-0 gap-1.5 overflow-x-auto">
        {list.map((x) => (
          <li key={x.id} className="relative shrink-0" title={x.title}>
            <ProductImage src={x.image_url} alt={x.title} className="h-11 w-11 rounded-lg bg-surface" />
            <button type="button" onClick={() => compareList.remove(x.id)} aria-label={`Remove ${x.title} from compare`}
              className="absolute -right-1 -top-1 rounded-full bg-ink p-0.5 text-white"><X className="h-3 w-3" /></button>
          </li>
        ))}
        {Array.from({ length: MAX_COMPARE - list.length }).map((_, i) => (
          <li key={`empty-${i}`} className="hidden h-11 w-11 shrink-0 rounded-lg border border-dashed border-line sm:block" aria-hidden />
        ))}
      </ul>
      <div className="flex shrink-0 flex-col items-start gap-0.5">
        {ready ? (
          <Link to={`/compare?ids=${list.map((x) => x.id).join(",")}`} data-testid="compare-now"
            className="inline-flex items-center gap-1.5 rounded-xl btn-gloss bg-accent-strong px-3 py-1.5 text-sm font-semibold text-white">
            <GitCompareArrows className="h-4 w-4" aria-hidden /> Compare {list.length}
          </Link>
        ) : (
          <span className="px-1 text-xs text-ink-soft">Add 1 more product to compare</span>
        )}
        <button type="button" onClick={() => compareList.clear()} className="px-1 text-[11px] text-ink-soft hover:text-ink">Clear</button>
      </div>
    </div>
  );
}

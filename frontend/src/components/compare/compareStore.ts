import { useSyncExternalStore } from "react";

/** Products picked for comparison. Per browser (localStorage), shared across tabs, at most MAX_COMPARE. */
export interface CompareItem { id: number; title: string; image_url: string | null; category: string }

export const MAX_COMPARE = 4;
const KEY = "buywise.compare";
const EVENT = "buywise-compare";

function read(): CompareItem[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x?.id === "number").slice(0, MAX_COMPARE) : [];
  } catch {
    return [];
  }
}

let cache: CompareItem[] = read();

function write(items: CompareItem[]) {
  cache = items.slice(0, MAX_COMPARE);
  try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* storage unavailable – keeps working for this page */ }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(cb: () => void) {
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) { cache = read(); cb(); } };
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => { window.removeEventListener(EVENT, cb); window.removeEventListener("storage", onStorage); };
}

export function useCompareList(): CompareItem[] {
  return useSyncExternalStore(subscribe, () => cache, () => cache);
}

export const compareList = {
  get: () => cache,
  has: (id: number) => cache.some((x) => x.id === id),
  /** false when the list is already full */
  add(item: CompareItem): boolean {
    if (cache.some((x) => x.id === item.id)) return true;
    if (cache.length >= MAX_COMPARE) return false;
    write([...cache, item]);
    return true;
  },
  remove: (id: number) => write(cache.filter((x) => x.id !== id)),
  clear: () => write([]),
  set: (items: CompareItem[]) => write(items),
};

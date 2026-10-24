const KEY = "buywise.recentSearches";

export function getRecentSearches(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, 10) : [];
  } catch {
    return [];
  }
}

export function addRecentSearch(q: string): void {
  try {
    const list = [q, ...getRecentSearches().filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 10);
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable – recent searches are a convenience only */
  }
}

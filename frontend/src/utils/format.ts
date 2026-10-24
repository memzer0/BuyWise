const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export function formatINR(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : inr.format(v);
}

export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const s = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

/** Only http(s) URLs are ever rendered as links. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export const CATEGORY_LABELS: Record<string, string> = {
  smartphones: "Smartphones", laptops: "Laptops", tablets: "Tablets", smartwatches: "Smartwatches",
  headphones: "Headphones", speakers: "Speakers", televisions: "TVs", monitors: "Monitors",
  components: "Components", keyboards_mice: "Keyboards & Mice", cameras: "Cameras", gaming_consoles: "Consoles",
  printers: "Printers", networking: "Networking", storage: "Storage", accessories: "Accessories", other: "Other",
};

export function capitalize(s: string | null | undefined): string {
  return s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : "";
}

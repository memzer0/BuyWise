import { useState } from "react";

const DOMAINS: Record<string, string> = {
  flipkart: "flipkart.com", amazon: "amazon.in", amazonin: "amazon.in", amazonindia: "amazon.in", croma: "croma.com",
  reliancedigital: "reliancedigital.in", vijaysales: "vijaysales.com", tatacliq: "tatacliq.com", jiomart: "jiomart.com",
  apple: "apple.com", applestore: "apple.com", samsung: "samsung.com", samsungindia: "samsung.com", samsungshop: "samsung.com",
  oneplus: "oneplus.in", xiaomi: "mi.com", mi: "mi.com", mistore: "mi.com", googlestore: "store.google.com",
  sangeethamobiles: "sangeethamobiles.com", poorvika: "poorvika.com", cashify: "cashify.in", bajajelectronics: "bajajelectronics.com",
};
const PALETTE = ["#1546d9", "#14172b", "#3a5fcf", "#545a70", "#0f348f", "#2b3150"];

function norm(name: string): string {
  return name.toLowerCase().replace(/\.(com|in|co\.in)$/, "").replace(/[^a-z0-9]/g, "");
}

/** Store icon: the store's own favicon when its domain is known, otherwise a coloured letter. */
export function StoreLogo({ name, url, size = 36 }: { name: string | null; url?: string | null; size?: number }) {
  const [failed, setFailed] = useState(false);
  const n = norm(name ?? "?");
  let domain = DOMAINS[n];
  if (!domain && url) {
    try {
      const host = new URL(url).hostname.replace(/^www\./, "");
      if (!/google\./.test(host)) domain = host;
    } catch { /* ignore */ }
  }
  const letter = (name ?? "?").trim().charAt(0).toUpperCase() || "?";
  const color = PALETTE[[...n].reduce((a, c) => a + c.charCodeAt(0), 0) % PALETTE.length];
  const box = { width: size, height: size };
  if (domain && !failed) {
    return (
      <span className="grid shrink-0 place-items-center overflow-hidden rounded-full border border-line bg-surface" style={box}>
        <img src={`https://icons.duckduckgo.com/ip3/${domain}.ico`} alt="" referrerPolicy="no-referrer"
          width={size * 0.6} height={size * 0.6} onError={() => setFailed(true)} />
      </span>
    );
  }
  return (
    <span className="grid shrink-0 place-items-center rounded-full font-bold text-white" style={{ ...box, background: color, fontSize: size * 0.42 }} aria-hidden>
      {letter}
    </span>
  );
}

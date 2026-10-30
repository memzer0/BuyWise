import { useQuery } from "@tanstack/react-query";
import {
  Camera, Cable, Cpu, Gamepad2, HardDrive, Headphones, Keyboard, Laptop, Monitor, Package, Printer, Router, Smartphone,
  Speaker, Tablet, Tv, Watch, type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ProductCard } from "../components/ProductCard";
import { SearchBar } from "../components/SearchBar";
import { LogoMark } from "../components/OrbitMark";
import { Card } from "../components/ui";
import { getRecentSearches } from "../hooks/recent";

const ICONS: Record<string, LucideIcon> = {
  smartphones: Smartphone, laptops: Laptop, tablets: Tablet, smartwatches: Watch, headphones: Headphones, speakers: Speaker,
  televisions: Tv, monitors: Monitor, components: Cpu, keyboards_mice: Keyboard, cameras: Camera, gaming_consoles: Gamepad2,
  printers: Printer, networking: Router, storage: HardDrive, accessories: Cable, other: Package,
};
// Clicking a category runs a real backend search with a representative query for that category.
const CATEGORY_QUERY: Record<string, string> = {
  smartphones: "smartphone", laptops: "laptop", tablets: "tablet", smartwatches: "smartwatch", headphones: "wireless earbuds",
  speakers: "bluetooth speaker", televisions: "smart tv", monitors: "monitor", components: "ssd", keyboards_mice: "wireless mouse",
  cameras: "camera", gaming_consoles: "gaming console", printers: "printer", networking: "wifi router", storage: "portable ssd",
  accessories: "fast charger", other: "electronics",
};

const QUICK: [string, string][] = [["smartphones", "Smartphones"], ["laptops", "Laptops"], ["headphones", "Earbuds"], ["televisions", "TVs"], ["smartwatches", "Smartwatches"]];

/** Hero visual: the BuyWise mark in a floating liquid-glass orb, with glass chips naming real features (no numbers –
 *  nothing here pretends to be a live price). Hidden on small screens. */
function HeroVisual() {
  const chip = "liquid absolute flex items-center gap-2 whitespace-nowrap rounded-2xl px-3.5 py-2 text-sm font-semibold text-ink";
  return (
    <div aria-hidden className="pointer-events-none absolute right-10 top-1/2 hidden h-[340px] w-[340px] -translate-y-1/2 lg:block">
      <div className="absolute inset-10 rounded-full bg-gradient-to-br from-accent/60 via-sky/40 to-sun/70 blur-2xl" />
      <div className="liquid float absolute inset-14 grid place-items-center rounded-full">
        <LogoMark size={128} className="drop-shadow-[0_18px_24px_rgb(21_70_217/0.45)]" />
      </div>
      <div className={`${chip} float left-0 top-6 [animation-delay:-2s]`}><span className="h-2.5 w-2.5 rounded-full bg-sun" /> Lowest verified</div>
      <div className={`${chip} float bottom-10 left-[-10px] [animation-delay:-4s]`}><span className="h-2.5 w-2.5 rounded-full bg-accent" /> Real price history</div>
      <div className={`${chip} float bottom-2 right-0 [animation-delay:-1s]`}><span className="h-2.5 w-2.5 rounded-full bg-success" /> Regret Shield</div>
    </div>
  );
}

const TILE_TINTS = ["bg-accent-soft text-brand", "bg-sun-soft text-cyan", "bg-sky/15 text-brand", "bg-apricot/20 text-cyan"];

export function HomePage() {
  const cats = useQuery({ queryKey: ["categories"], queryFn: ({ signal }) => api.categories(signal) });
  const home = useQuery({ queryKey: ["home"], queryFn: ({ signal }) => api.home(signal) });
  const providers = useQuery({ queryKey: ["providers"], queryFn: ({ signal }) => api.providers(signal) });
  const recent = getRecentSearches().slice(0, 6);
  const noneConfigured = !!providers.data?.providers && !providers.data.providers.some((p) => p.configured);

  return (
    <div className="space-y-10">
      <section className="liquid relative overflow-hidden rounded-[2rem] px-6 py-10 sm:px-10 sm:py-14">
        {/* ambient cobalt / sun glow */}
        <div aria-hidden className="pointer-events-none absolute -left-24 -top-32 -z-10 h-80 w-80 rounded-full bg-accent/30 blur-3xl" />
        <div aria-hidden className="pointer-events-none absolute -bottom-40 right-0 -z-10 h-96 w-96 rounded-full bg-sun/35 blur-3xl" />
        <HeroVisual />
        <div className="relative max-w-2xl">
          <p className="liquid relative mb-4 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold text-ink">
            <span className="h-2 w-2 rounded-full bg-sun shadow-[0_0_10px_var(--color-sun)]" aria-hidden />
            Live prices from trusted Indian stores
          </p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-6xl">
            Smarter Tech.<br /><span className="text-gradient">Better Prices.</span>
          </h1>
          <p className="mt-4 max-w-xl text-base text-ink-soft sm:text-lg">
            Compare electronics across retailers, track real price movements, and make smarter buying decisions with BuyWise.
          </p>
        </div>
        <div className="relative mt-7 max-w-3xl"><SearchBar large /></div>
        {recent.length > 0 && (
          <div className="relative mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-soft">Recent:</span>
            {recent.map((r) => <Link key={r} to={`/search?q=${encodeURIComponent(r)}`} className="press rounded-full border border-line bg-surface/60 px-3 py-1 hover:border-accent/60 hover:bg-surface-2">{r}</Link>)}
          </div>
        )}
        <div className="relative mt-4 flex flex-wrap gap-2 text-sm">
          {QUICK.map(([id, label]) => (
            <Link key={id} to={`/search?q=${encodeURIComponent(CATEGORY_QUERY[id])}&category=${id}`}
              className="press liquid relative rounded-full px-3.5 py-1.5 font-medium text-brand hover:text-ink">{label}</Link>
          ))}
        </div>
        {noneConfigured && (
          <p className="relative mt-6 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
            No price providers are configured on this server yet, so searches cannot return prices.
            Add an API key in <code>backend/.env</code> (see <Link to="/admin" className="underline">Diagnostics</Link> for what each provider needs).
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">Browse electronics</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {(cats.data?.categories ?? []).map((c, i) => {
            const Icon = ICONS[c.id] ?? Package;
            return (
              <Link key={c.id} to={`/search?q=${encodeURIComponent(CATEGORY_QUERY[c.id] ?? c.name)}&category=${c.id}`}>
                <Card className="lift flex h-full items-center gap-3 p-3">
                  <span className={`grid h-10 w-10 place-items-center rounded-xl ${TILE_TINTS[i % TILE_TINTS.length]}`}><Icon className="h-5 w-5" aria-hidden /></span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{c.name}</p>
                    <p className="text-[11px] text-ink-soft">{c.tracked_products} tracked</p>
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

      {home.data && home.data.verified_deals.length > 0 && (
        <Section title="Verified deals" note={home.data.deals_note}>
          {home.data.verified_deals.map((p) => (
            <div key={p.id} className="relative">
              <span className="absolute left-3 top-3 z-10 rounded bg-success px-1.5 py-0.5 text-xs font-semibold text-canvas">{p.discount_pct}% below MRP</span>
              <ProductCard p={p} />
            </div>
          ))}
        </Section>
      )}
      {home.data && home.data.popular.length > 0 && (
        <Section title="Popular comparisons" note="Ranked by how often products are opened on this BuyWise server.">
          {home.data.popular.map((p) => <ProductCard key={p.id} p={p} />)}
        </Section>
      )}
      {home.data && home.data.recently_tracked.length > 0 && (
        <Section title="Recently tracked">
          {home.data.recently_tracked.map((p) => <ProductCard key={p.id} p={p} />)}
        </Section>
      )}

      <section className="grid gap-4 md:grid-cols-3">
        {[
          ["Real prices only", "Every price comes from a retailer API or licensed shopping API. If a source fails, BuyWise says so instead of guessing."],
          ["Exact variant matching", "Storage, RAM, model generation, Pro/standard and refurbished listings are kept apart, so you compare like with like."],
          ["Price history at a glance", "See how a product's price has moved over time and spot the right moment to buy."],
        ].map(([t, d]) => (
          <Card key={t} className="p-5"><p className="font-semibold">{t}</p><p className="mt-1 text-sm text-ink-soft">{d}</p></Card>
        ))}
      </section>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {note && <p className="text-xs text-ink-soft">{note}</p>}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
    </section>
  );
}

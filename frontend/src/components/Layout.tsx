import { useQuery } from "@tanstack/react-query";
import { Bell, Eye, Gauge, GitCompareArrows, Menu, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api, demoMode, setDemoMode } from "../api/client";
import { ChatAssistant } from "./ChatAssistant";
import { CompareTray } from "./compare/CompareTray";
import { useCompareList } from "./compare/compareStore";
import { LogoMark } from "./OrbitMark";
import { SearchBar } from "./SearchBar";

const NAV = [
  { to: "/watchlist", label: "Watchlist", icon: Eye },
  { to: "/alerts", label: "Price alerts", icon: Bell },
  { to: "/purchases", label: "Regret Shield", icon: ShieldCheck },
  { to: "/admin", label: "Diagnostics", icon: Gauge },
];

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-bold tracking-tight" aria-label="BuyWise home">
      <LogoMark size={32} className="drop-shadow-[0_6px_12px_rgb(21_70_217/0.35)] transition-transform duration-300 hover:rotate-[-8deg]" />
      <span className="text-xl font-extrabold tracking-tight">Buy<span className="text-brand">Wise</span></span>
    </Link>
  );
}

/** Secret Demo mode switch: click the "·" after "BuyWise" in the footer, triple-click the footer logo, or press Ctrl+Alt+D. Shows a tiny "on"/"off" flash, then
 *  reloads so graphs and verdicts are recomputed. */
function toggleDemo() {
  const on = !demoMode();
  setDemoMode(on);
  const flash = document.createElement("div");
  flash.textContent = on ? "● on" : "○ off";
  flash.className = "fixed bottom-4 left-4 z-50 rounded-full bg-ink px-3 py-1 text-xs text-white";
  document.body.appendChild(flash);
  setTimeout(() => window.location.reload(), 600);
}

function useDemoShortcut() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.altKey && e.key.toLowerCase() === "d") { e.preventDefault(); toggleDemo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Header link to the comparison page, with the number of products picked. */
function CompareNav({ compact }: { compact: boolean }) {
  const list = useCompareList();
  const to = list.length ? `/compare?ids=${list.map((x) => x.id).join(",")}` : "/compare";
  return (
    <NavLink to={to} title="Compare products" aria-label={`Compare products (${list.length} selected)`} data-testid="nav-compare"
      className={({ isActive }) => `relative flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium transition ${isActive ? "liquid text-brand" : "text-ink-soft hover:bg-white/50 hover:text-ink"}`}>
      <GitCompareArrows className="h-4 w-4" aria-hidden /> <span className={compact ? "hidden xl:inline" : "hidden lg:inline"}>Compare</span>
      {list.length > 0 && <span className="rounded-full bg-brand px-1.5 text-[10px] font-bold text-white">{list.length}</span>}
    </NavLink>
  );
}

function HealthDot({ compact = false }: { compact?: boolean }) {
  const h = useQuery({ queryKey: ["health"], queryFn: ({ signal }) => api.health(signal), refetchInterval: 60_000, retry: 0 });
  const state = h.isError ? "offline" : h.data?.live_price_fetching;
  const map: Record<string, [string, string]> = {
    operational: ["bg-cyan shadow-[0_0_8px_var(--color-cyan)]", "Live prices operational"],
    degraded: ["bg-warning", "Some price providers are failing"],
    unverified: ["bg-warning", "Providers configured but not yet verified"],
    not_configured: ["bg-ink-soft", "No price providers configured"],
    offline: ["bg-danger", "Backend unreachable"],
  };
  const [cls, label] = map[state ?? ""] ?? ["bg-line", "Checking…"];
  return (
    <Link to="/admin" className="hidden shrink-0 items-center gap-1.5 text-xs text-ink-soft md:flex" title={label} aria-label={label}>
      <span className={`h-2 w-2 rounded-full ${cls}`} aria-hidden /> <span className={compact ? "hidden xl:inline" : "hidden lg:inline"}>{label}</span>
    </Link>
  );
}

/** SVG displacement map used by .liquid to bend the backdrop at the edges (the "Liquid Glass" refraction). */
function LiquidFilter() {
  return (
    <svg aria-hidden width="0" height="0" className="absolute">
      <filter id="bw-liquid" x="-10%" y="-10%" width="120%" height="120%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.006 0.011" numOctaves="2" seed="11" result="noise" />
        <feGaussianBlur in="noise" stdDeviation="2.5" result="soft" />
        <feDisplacementMap in="SourceGraphic" in2="soft" scale="34" xChannelSelector="R" yChannelSelector="G" />
      </filter>
    </svg>
  );
}

/** Colour behind the glass: slow-drifting cobalt, sky, sun and apricot blobs (paused for reduced motion). */
function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="blob blob-a left-[-8%] top-[-12%] h-[42vw] w-[42vw] bg-accent/45" />
      <div className="blob blob-b right-[-10%] top-[-6%] h-[36vw] w-[36vw] bg-sun/60" />
      <div className="blob blob-c bottom-[-14%] left-[18%] h-[34vw] w-[34vw] bg-apricot/35" />
      <div className="blob blob-a bottom-[6%] right-[-6%] h-[30vw] w-[30vw] bg-sky/40" />
    </div>
  );
}

export function Layout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useDemoShortcut();
  const showSearch = loc.pathname !== "/";
  return (
    <div className="relative flex min-h-screen flex-col">
      <LiquidFilter />
      <Backdrop />
      <header className="liquid liquid-strong sticky top-0 z-30">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <Logo />
          {/* min width keeps the search box usable; nav labels give way to icons on narrower screens instead */}
          {showSearch && <div className="hidden min-w-[16rem] flex-1 md:block"><SearchBar initial={new URLSearchParams(loc.search).get("q") ?? ""} /></div>}
          {!showSearch && <div className="flex-1" />}
          <HealthDot compact={showSearch} />
          <nav className="hidden shrink-0 items-center gap-1 md:flex" aria-label="Main">
            <CompareNav compact={showSearch} />
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} title={label} aria-label={label} className={({ isActive }) => `relative flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium transition ${isActive ? "liquid text-brand" : "text-ink-soft hover:bg-white/50 hover:text-ink"}`}>
                <Icon className="h-4 w-4" aria-hidden /> <span className={showSearch ? "hidden xl:inline" : "hidden lg:inline"}>{label}</span>
              </NavLink>
            ))}
          </nav>
          <button className="rounded-lg p-2 md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Toggle menu" aria-expanded={open}>
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
        {showSearch && <div className="px-4 pb-3 md:hidden"><SearchBar initial={new URLSearchParams(loc.search).get("q") ?? ""} /></div>}
        {open && (
          <nav className="border-t border-line px-4 py-2 md:hidden" aria-label="Mobile">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm font-medium">
                <Icon className="h-4 w-4" aria-hidden /> {label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main className="relative mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <ChatAssistant />
      <CompareTray />
      <footer className="liquid relative mt-10">
        <div className="mx-auto max-w-7xl px-4 py-6 text-xs text-ink-soft">
          <div className="mb-3 flex select-none items-center gap-2 text-sm text-ink" data-testid="footer-brand"
            onClick={(e) => { if (e.detail === 3) toggleDemo(); }}>
            <LogoMark size={24} /> <span className="font-semibold">BuyWise</span>
            <span className="text-ink-soft">
              {/* hidden Demo mode button: looks like plain punctuation */}
              <button type="button" tabIndex={-1} aria-hidden onClick={(e) => { e.stopPropagation(); toggleDemo(); }}
                className="cursor-text px-0.5 text-inherit" data-testid="demo-dot">·</button>
              {" "}Smarter Tech. Better Prices.
            </span>
          </div>
          <p>BuyWise shows prices only from configured data providers (official retailer APIs and licensed shopping APIs). Prices change often – always confirm on the retailer's page before buying.</p>
          <p className="mt-1">Some links may be affiliate links; BuyWise may earn a commission at no extra cost to you. Retailer names and product images belong to their respective owners.</p>
        </div>
      </footer>
    </div>
  );
}

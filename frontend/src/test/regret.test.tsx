import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RegretShieldCard } from "../components/RegretShield";
import { PurchasesPage } from "../pages/PurchasesPage";
import type { Purchase, PurchasesResponse, RegretPreCheck } from "../types/api";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

type Handler = (url: string, init?: RequestInit) => unknown;
function route(h: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = h(String(input), init);
    if (body === undefined) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

const pre: RegretPreCheck = {
  result: "COMPARE_FIRST", label: "Compare first", reasons: ["Variant match confidence is 85% – check storage."],
  evidence: [{ label: "Current price", value: "₹68,999 at Flipkart", ok: true }, { label: "Return policy", value: null, ok: false }],
  missing: ["Return policy"], limitations: ["Return policy isn't available."], evidence_level: "medium",
  observed_at: new Date().toISOString(), best_offer: { retailer: "Flipkart", price: 68999, product_url: "https://www.flipkart.com/x/p/1", link_type: "exact_listing" },
};

const purchase = (o: Partial<Purchase> = {}): Purchase => ({
  id: 1, product_id: 7, product_title: "Apple iPhone 16 (Black, 128 GB)", image_url: null, storage_gb: 128, ram_gb: null, colour: "black",
  condition: "new", retailer: "Amazon India", purchase_price: 75000, purchase_date: "2026-10-01", order_ref: null,
  return_deadline: "2026-10-11", protection_deadline: null, expected_costs: null, notify: true, status: "price_drop",
  last_checked_at: new Date().toISOString(), created_at: new Date().toISOString(), unread_notifications: 1,
  comparable: { status: "comparable", offer_id: 3, price: 68999, retailer: "Flipkart", product_url: "https://www.flipkart.com/x/p/1", link_type: "exact_listing", reason: null },
  comparable_verified_at: new Date().toISOString(),
  deadlines: [{ kind: "return", label: "Return / exchange window", date: "2026-10-11", days_left: 2, state: "soon" }],
  difference: 6001, difference_pct: 8.0, meaningful_drop: true, net_benefit: null,
  actions: ["Check whether Amazon India offers a price adjustment for drops after purchase (don't assume it does)."],
  notes: ["Net benefit not shown: enter your expected return/restocking costs to estimate it."], email: null, ...o,
});

const list = (items: Purchase[]): PurchasesResponse => ({
  items, deadlines: items.flatMap((p) => p.deadlines.map((d) => ({ ...d, purchase_id: p.id, product_title: p.product_title }))),
  price_drops: items.filter((p) => p.status === "price_drop").map((p) => p.id),
  thresholds: { min_drop_pct: 2, min_drop_amount: 200 }, monitoring: { scheduler_enabled: true, note: "Purchases are re-checked automatically." },
});

describe("RegretShieldCard", () => {
  it("shows the pre-purchase result, evidence and missing items", async () => {
    route(() => pre);
    wrap(<RegretShieldCard productId={7} bestRetailer="Flipkart" bestPrice={68999} />);
    expect(await screen.findByTestId("regret-result")).toHaveTextContent("Compare first");
    const ev = screen.getByTestId("regret-evidence");
    expect(within(ev).getByText("₹68,999 at Flipkart")).toBeInTheDocument();
    expect(within(ev).getByText("Not available")).toBeInTheDocument();
  });

  it("validates and submits a tracked purchase without requiring order number or receipt", async () => {
    const fetch = route((url, init) => (url.endsWith("/api/purchases") && init?.method === "POST" ? purchase() : pre));
    wrap(<RegretShieldCard productId={7} bestRetailer="Flipkart" bestPrice={68999} />);
    await userEvent.click(await screen.findByRole("button", { name: "Track my purchase" }));
    const price = screen.getByLabelText(/Price paid/);
    await userEvent.clear(price);
    await userEvent.click(screen.getByRole("button", { name: "Start tracking" }));
    expect(screen.getByRole("alert")).toHaveTextContent("more than ₹0");
    await userEvent.type(price, "75000");
    await userEvent.click(screen.getByRole("button", { name: "Start tracking" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Tracking your purchase at ₹75,000");
    const post = fetch.mock.calls.find(([u, i]) => String(u).endsWith("/api/purchases") && i?.method === "POST")!;
    const body = JSON.parse(String(post[1]!.body));
    expect(body).toMatchObject({ product_id: 7, retailer: "Flipkart", purchase_price: 75000, order_ref: null, notify: true });
    expect(screen.queryByText(/password|OTP/i, { selector: "input" })).toBeNull();
  });
});

describe("PurchasesPage", () => {
  it("shows price drop, deadline and notifications", async () => {
    route((url) => url.includes("notifications") ? { items: [{ id: 1, purchase_id: 1, kind: "price_drop", message: "iPhone now ₹68,999", created_at: new Date().toISOString(), read: false }], unread: 1 } : list([purchase()]));
    wrap(<PurchasesPage />);
    expect(await screen.findByTestId("purchase-difference")).toHaveTextContent("₹6,001 (8.0%) cheaper than you paid");
    expect(screen.getByText("Price dropped")).toBeInTheDocument();
    expect(screen.getByText("Deadline alerts")).toBeInTheDocument();
    expect(await screen.findByText("iPhone now ₹68,999")).toBeInTheDocument();
    expect(screen.getByText("1 new")).toBeInTheDocument();
  });

  it("labels an unavailable comparable offer instead of inventing a price", async () => {
    route((url) => url.includes("notifications") ? { items: [], unread: 0 } : list([purchase({
      status: "comparable_unavailable", difference: null, difference_pct: null, actions: [], deadlines: [],
      comparable: { status: "comparable_unavailable", reason: "No verified, in-stock offer for this exact product right now." } })]));
    wrap(<PurchasesPage />);
    expect(await screen.findByText("No verified, in-stock offer for this exact product right now.")).toBeInTheDocument();
    expect(screen.getAllByText("Comparable offer unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("purchase-difference")).toBeNull();
  });

  it("shows an empty state and supports delete with confirmation", async () => {
    let items = [purchase()];
    const fetch = route((url, init) => {
      if (init?.method === "DELETE") { items = []; return undefined; }
      return url.includes("notifications") ? { items: [], unread: 0 } : list(items);
    });
    wrap(<PurchasesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete purchase" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("No purchases tracked yet")).toBeInTheDocument();
    expect(fetch.mock.calls.some(([u, i]) => String(u).endsWith("/api/purchases/1") && i?.method === "DELETE")).toBe(true);
  });
});

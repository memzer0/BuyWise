import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OfferTable } from "../components/OfferTable";
import { SearchBar } from "../components/SearchBar";
import { SearchPage } from "../pages/SearchPage";
import type { Offer, SearchResponse } from "../types/api";

function wrap(ui: React.ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname + loc.search}</div>;
}

const offer = (o: Partial<Offer>): Offer => ({
  offer_id: 1, provider: "flipkart_affiliate", provider_name: "Flipkart (Affiliate API)", retailer: "Flipkart", seller_name: null,
  listing_title: "Apple iPhone 16 (Black, 128 GB)", price: 69999, mrp: 79900, currency: "INR", shipping_cost: 0, total_cost: 69999,
  availability: "in_stock", condition: "new", product_url: "https://www.flipkart.com/apple-iphone-16/p/itm1?pid=MOB1",
  link_type: "exact_listing", image_url: null, rating: null, rating_count: null, warranty: null, fetched_at: new Date().toISOString(),
  last_verified_at: new Date().toISOString(), source_type: "official_api", freshness_status: "live", verification_status: "verified",
  match_status: "verified", match_confidence: 1, eligible_for_best_price: true, ineligible_reason: null, is_best_price: true,
  trusted_store: true, preferred_rank: 0, ...o,
});

const searchResponse = (overrides: Partial<SearchResponse> = {}): SearchResponse => ({
  query: "iphone 16", source: "live", fetched_at: new Date().toISOString(),
  providers: [{ provider: "flipkart_affiliate", name: "Flipkart", status: "ok", listings: 2, error: null, duration_ms: 100 },
    { provider: "serpapi_google_shopping", name: "Google Shopping", status: "error", listings: 0, error: "timeout", duration_ms: 15000 }],
  partial: true, no_providers_configured: false, all_providers_failed: false,
  facets: { brands: ["apple"], categories: ["smartphones"], storage_gb: [128, 256], ram_gb: [] },
  total: 1, page: 1, page_size: 20, hidden_accessories: 2, hidden_untrusted: 1,
  results: [{ id: 7, title: "Apple iPhone 16 (Black, 128 GB)", brand: "apple", category: "smartphones", image_url: null, storage_gb: 128,
    ram_gb: null, colour: "black", condition: "new", screen_inches: null, offer_count: 2, verified_offer_count: 2, trusted_offer_count: 2, preferred_stores: ["Flipkart"], previous_price: 71999, price_change: -2000,
    retailers: ["Amazon India", "Flipkart"], best_price: 69999, best_retailer: "Flipkart", best_freshness: "live",
    best_link_type: "exact_listing", last_verified_at: new Date().toISOString() }],
  ...overrides,
});

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe("SearchBar", () => {
  it("submits the query to the search route", async () => {
    mockFetch({ suggestions: [] });
    wrap(<Routes><Route path="*" element={<><SearchBar /><LocationProbe /></>} /></Routes>);
    await userEvent.type(screen.getByRole("combobox"), "Galaxy S24 256GB");
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));
    expect(screen.getByTestId("loc").textContent).toBe("/search?q=Galaxy%20S24%20256GB");
  });
});

describe("SearchPage", () => {
  it("calls the backend and renders results with partial-result notice", async () => {
    const f = mockFetch(searchResponse());
    wrap(<Routes><Route path="/search" element={<SearchPage />} /></Routes>, "/search?q=iphone%2016");
    expect(await screen.findByText("Apple iPhone 16 (Black, 128 GB)")).toBeInTheDocument();
    expect(String(f.mock.calls[0][0])).toContain("/api/search?q=iphone+16");
    expect(screen.getByTestId("result-count")).toHaveTextContent("1 product");
    expect(screen.getByTestId("price-change")).toHaveTextContent("₹2,000");
    expect(screen.getByText(/Partial results/)).toBeInTheDocument();
    expect(screen.getByText(/Google Shopping: failed/)).toBeInTheDocument();
    expect(screen.getByTestId("hidden-notice")).toHaveTextContent("2 accessories");
    expect(screen.getByTestId("hidden-notice")).toHaveTextContent("1 product sold only by stores not on the trusted list");
  });

  it("changing sort and filters updates the request", async () => {
    const f = mockFetch(searchResponse());
    wrap(<Routes><Route path="/search" element={<><SearchPage /><LocationProbe /></>} /></Routes>, "/search?q=iphone%2016");
    await screen.findByText("Apple iPhone 16 (Black, 128 GB)");
    await userEvent.selectOptions(screen.getByLabelText("Sort"), "price_asc");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Storage" }), "128");
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("sort=price_asc"));
    expect(screen.getByTestId("loc").textContent).toContain("storage_gb=128");
    await waitFor(() => expect(f.mock.calls.some((c) => String(c[0]).includes("storage_gb=128") && String(c[0]).includes("sort=price_asc"))).toBe(true));
  });

  it("shows an honest empty state when no providers are configured", async () => {
    mockFetch(searchResponse({ no_providers_configured: true, results: [], total: 0, partial: false }));
    wrap(<Routes><Route path="/search" element={<SearchPage />} /></Routes>, "/search?q=iphone");
    expect(await screen.findByText("No price providers are configured")).toBeInTheDocument();
  });

  it("shows an error state with retry on network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    wrap(<Routes><Route path="/search" element={<SearchPage />} /></Routes>, "/search?q=iphone");
    expect(await screen.findByText("Search failed", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/Cannot reach the BuyWise server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows loading skeleton while fetching", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    wrap(<Routes><Route path="/search" element={<SearchPage />} /></Routes>, "/search?q=iphone");
    expect(screen.getByLabelText("Loading results")).toBeInTheDocument();
  });
});

describe("OfferTable", () => {
  it("each Buy button uses its own offer's exact URL", () => {
    const offers = [
      offer({ offer_id: 1, retailer: "Flipkart", price: 69999 }),
      offer({ offer_id: 2, retailer: "Amazon India", price: 70990, is_best_price: false,
        product_url: "https://www.amazon.in/dp/B0DGJ65N7V?tag=x-21" }),
    ];
    wrap(<OfferTable offers={offers} />);
    const rows = screen.getAllByTestId("offer-row");
    expect(within(rows[0]).getByTestId("buy-link")).toHaveAttribute("href", "https://www.flipkart.com/apple-iphone-16/p/itm1?pid=MOB1");
    expect(within(rows[1]).getByTestId("buy-link")).toHaveAttribute("href", "https://www.amazon.in/dp/B0DGJ65N7V?tag=x-21");
    expect(within(rows[0]).getByText("Lowest verified")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Top store")).toBeInTheDocument();
  });

  it("never renders unsafe URLs and labels non-exact links", () => {
    wrap(<OfferTable offers={[
      offer({ offer_id: 3, product_url: "javascript:alert(1)" }),
      offer({ offer_id: 4, link_type: "aggregator_page", product_url: "https://www.google.com/search?ibp=oshop", is_best_price: false }),
    ]} />);
    const rows = screen.getAllByTestId("offer-row");
    expect(within(rows[0]).queryByTestId("buy-link")).toBeNull();
    expect(within(rows[0]).getByText("No valid link")).toBeInTheDocument();
    expect(within(rows[1]).getByTestId("buy-link")).toHaveTextContent("View offer");
    expect(within(rows[1]).getByText("Google Shopping page")).toBeInTheDocument();
  });
});

describe("ProductPage", () => {
  it("renders buy button for the best offer, deal panel, variants and honest history", async () => {
    const { ProductPage } = await import("../pages/ProductPage");
    const best = offer({ offer_id: 1, retailer: "Croma", price: 128490, mrp: 134900, product_url: "https://www.croma.com/p/1" });
    const other = offer({ offer_id: 2, retailer: "Flipkart", price: 129999, is_best_price: false, product_url: "https://www.flipkart.com/x/p/itm2" });
    const detail = {
      variants: [{ id: 8, storage_gb: 512, colour: "deep blue", best_price: 149900, title: "x", image_url: null }],
      product: { ...searchResponse().results[0], id: 7, storage_gb: 256, colour: "deep blue", family: null, specs: {}, identifiers: [],
        last_refreshed_at: null, created_at: new Date().toISOString() },
      offers: [best, other],
      summary: { lowest_verified_price: 128490, highest_verified_price: 129999, price_difference: 1509, verified_offer_count: 2,
        total_offer_count: 2, shipping_note: "note" },
      score: { score: 56, confidence: 0.35, verdict: "insufficient_data", reasons: [], limitations: [],
        components: [{ key: "market_position", label: "Price vs. other sellers", weight: 0.25, score: 60, explanation: "e" },
          { key: "price_vs_history", label: "Price vs. observed history", weight: 0.35, score: null, explanation: "needs data" }] },
      prediction: { available: false, reason: "Not enough price history to predict.", predicted_price: null, horizon_days: 7,
        slope_per_day: null, holdout_mae: null, days_used: 0, method: "" },
      refresh_in_progress: false, affiliate_disclosure: "disclosure",
      deal: { score: null, label: "Tracking price", completeness: 0.1,
        insight: { kind: "info", title: "Tracking just started", body: "First price check today." },
        checks: [{ key: "cheaper_than_stores", label: "Cheaper than other stores", max_points: 10, status: "pass", points: 10, detail: "1.2% below" },
          { key: "at_all_time_low", label: "At the lowest price seen", max_points: 20, status: "na", points: 0, detail: "Needs at least 3 days of price checks." }],
        price_changes: [] },
      decision: { verdict: "CONSIDER_ALTERNATIVES", label: "Consider alternatives", headline: "A newer model is available for ₹4,000 more.",
        reasons: ["Apple iPhone 17 is tracked at ₹1,32,490 (Croma)."], limitations: ["Future prices can't be known for certain."],
        evidence_level: "low", alternatives: [{ id: 11, title: "Apple iPhone 17 (Black, 256 GB)", best_price: 132490, retailer: "Croma", image_url: null }] },
      timing: { available: true, reason: null, method: "m", stats: { highest: 59999, average: 52308.16, lowest: 46609, current: 128490 },
        horizons: [{ key: "3d", label: "2–3 days", score: 80, recommendation: "Go ahead & buy now", tone: "good", why: ["This is the lowest price BuyWise has seen."] },
          { key: "1w", label: "1 week", score: 50, recommendation: "Fair time – buy if you need it", tone: "fair", why: ["w"] },
          { key: "1m", label: "1 month", score: 30, recommendation: "Better to wait", tone: "wait", why: ["m"] }] },
      reviews: { available: true, rating: 4.4, reviews_count: 3551, distribution: [{ stars: 5, count: 3000 }, { stars: 1, count: 89 }],
        summary: "Reviewers mostly praise camera; common complaints mention heating.", aspects: [], insights: [{ type: "pro", text: "Great camera" }],
        reviews: [{ id: 0, title: "Great", text: "Camera is excellent", user_name: "a", source: "Flipkart", rating: 5, date: null, incentivized: null, sentiment: 1, aspects: ["Camera"], aspect_sentiment: { Camera: "positive" }, signals: [], duplicate_of: [], counted: true, group: "other" },
          { id: 1, title: "Free", text: "Got it to review", user_name: "f", source: null, rating: 5, date: null, incentivized: true, sentiment: 0, aspects: [], aspect_sentiment: {}, signals: ["Marked as incentivized by the source"], duplicate_of: [], counted: true, group: "flagged" }],
        counts: { flagged: 1, other: 1 }, sample_note: "Based on 2 reviews", method_note: "Keyword rules." },
      final_price: { stores: [{ offer_id: 1, retailer: "Croma", base_price: 128490, shipping: 0, guaranteed_total: 128490, applied: [],
          not_applied: [{ text: "₹4,000 off with HDFC Bank cards", kind: "bank", banks: ["HDFC"], flat_off: 4000, percent: null, cap: null,
            min_purchase: null, code: null, saving: 4000, reason: "you haven't selected HDFC" }], possible_total: 128490, unknowns: [] }],
        banks_mentioned: ["HDFC"], selected_banks: [], coupons_included: false, offers_data_available: true, assumptions: ["a"] },
      similar: [{ id: 9, title: "Apple iPhone 17 (Lavender, 256 GB)", image_url: null, best_price: 82900, retailer: "Croma",
        buy_url: "https://www.croma.com/p/9", link_type: "exact_listing" }],
    };
    const history = { range: "365d", points: [{ observed_at: new Date().toISOString(), price: 128490, retailer: "Croma", offer_id: 1 }],
      series: [], lowest_series: [{ observed_at: new Date().toISOString(), price: 128490, retailer: "Croma", stores: 1 }], daily_min: [], observation_count: 1, span_days: 0, lowest: 128490, average: 128490, highest: 128490, latest: null,
      tracking_started_at: new Date().toISOString(), sufficient: false, note: null };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const u = String(input);
      const fpHdfc = { ...detail.final_price, selected_banks: ["HDFC"], stores: [{ ...detail.final_price.stores[0], not_applied: [],
        applied: [{ ...detail.final_price.stores[0].not_applied[0], reason: undefined }], possible_total: 124490 }] };
      const regret = { result: "INSUFFICIENT_DATA", label: "Tracking price", reasons: ["Not enough price history yet."],
        evidence: [{ label: "Current price", value: "₹1,28,490 at Croma", ok: true }], missing: [], limitations: [],
        evidence_level: "low", observed_at: null, best_offer: null };
      const body = u.includes("/regret-shield") ? regret : u.includes("/history") ? history : u.includes("/offers") ? { product_id: 7, sort: "top_stores", offers: [best, other], hidden_untrusted: 0 }
        : u.includes("/final-price") ? (u.includes("banks=HDFC") ? fpHdfc : detail.final_price) : detail;
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }));
    wrap(<Routes><Route path="/product/:id" element={<ProductPage />} /></Routes>, "/product/7");
    const buy = await screen.findByTestId("main-buy");
    expect(buy).toHaveAttribute("href", "https://www.croma.com/p/1");
    expect(buy).toHaveTextContent("Buy on Croma");
    expect(screen.getByText(/5% off MRP/)).toBeInTheDocument();
    expect(screen.getByTestId("deal-label")).toHaveTextContent("Tracking price");
    expect(screen.getByTestId("buywise-score")).toHaveTextContent("—");
    expect(await screen.findByTestId("regret-result")).toHaveTextContent("Tracking price");
    expect(screen.getByTestId("deal-insight")).toHaveTextContent("Tracking just started");
    expect(screen.getByTestId("deal-checks")).toHaveTextContent("Needs at least 3 days");
    expect(within(screen.getByTestId("similar")).getByRole("link", { name: "Buy now" })).toHaveAttribute("href", "https://www.croma.com/p/9");
    expect(screen.getByRole("link", { name: "Share on WhatsApp" })).toHaveAttribute("href", expect.stringContaining("https://wa.me/?text="));
    expect(screen.getByTestId("decision-verdict")).toHaveTextContent("Consider alternatives");
    expect(within(screen.getByTestId("decision")).getByRole("link", { name: /iPhone 17/ })).toHaveAttribute("href", "/product/11");
    const fp = screen.getByTestId("final-price");
    expect(within(fp).getByTestId("final-price-row")).toHaveTextContent("₹1,28,490");
    await userEvent.click(within(fp).getByRole("button", { name: "HDFC" }));
    expect(await within(fp).findByText("−₹4,000")).toBeInTheDocument();
    expect(within(fp).getByTestId("final-price-row")).toHaveTextContent("₹1,24,490");
    // reviews
    const rv = screen.getByTestId("reviews");
    expect(within(rv).getByTestId("review-summary")).toHaveTextContent("praise camera");
    expect(within(rv).getAllByTestId("review-card")).toHaveLength(2);
    // only the source-marked incentive is noted; nothing is questioned for rating or length
    expect(within(rv).getByText(/Reliability note: Marked as incentivized/)).toBeInTheDocument();
    // buy timing
    await userEvent.click(screen.getByRole("tab", { name: "Price drop" }));
    expect(screen.getByTestId("timing-recommendation")).toHaveTextContent("Fair time");
    await userEvent.click(screen.getByRole("tab", { name: "2–3 days" }));
    expect(screen.getByTestId("timing-recommendation")).toHaveTextContent("Go ahead & buy now");
    expect(screen.getByTestId("buy-timing")).toHaveTextContent("₹46,609");
    expect(within(screen.getByTestId("variants")).getByRole("link", { name: "512 GB" })).toHaveAttribute("href", "/product/8");
    expect(await screen.findByTestId("history-insufficient")).toHaveTextContent("Tracking since");
  });
});

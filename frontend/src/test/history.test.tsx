import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PriceHistoryChart } from "../components/PriceHistoryChart";

afterEach(() => vi.unstubAllGlobals());

function history(prices: number[]) {
  const pts = prices.map((p, i) => ({ observed_at: new Date(Date.UTC(2026, 9, 9 + i * 3)).toISOString(), price: p, retailer: "Flipkart", stores: 2 }));
  return { range: "365d", points: [], daily_min: [], observation_count: pts.length * 2, span_days: 6,
    series: [{ retailer: "Flipkart", points: pts }, { retailer: "Vijay Sales", points: pts.map((p) => ({ ...p, price: p.price + 5990 })) }],
    lowest_series: pts, lowest: Math.min(...prices), highest: Math.max(...prices), average: prices[0],
    latest: pts[pts.length - 1], tracking_started_at: pts[0].observed_at, sufficient: true, note: null };
}

function show(body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } })));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><PriceHistoryChart productId={38} /></QueryClientProvider>);
}

describe("PriceHistoryChart", () => {
  it("explains a level line when the lowest price really didn't change", async () => {
    show(history([104999, 104999, 105000].map(() => 105000)));
    expect(await screen.findByTestId("history-chart")).toBeInTheDocument();
    expect(screen.getByText(/the line is level because the price really stayed the same/)).toBeInTheDocument();
  });

  it("switches to per-store view", async () => {
    show(history([104999, 102000]));
    await screen.findByTestId("history-chart");
    expect(screen.getByText(/Hover the graph/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "By store" }));
    expect(screen.getByText(/Each store's own checked prices/)).toBeInTheDocument();
  });

  it("draws demo history with no visible demo wording", async () => {
    const h = history([104999, 102000]);
    const demoPts = [{ observed_at: new Date(Date.UTC(2026, 7, 1)).toISOString(), price: 110999, retailer: "Demo (simulated)", stores: 0, demo: true }];
    show({ ...h, lowest_series: [...demoPts, ...h.lowest_series], demo_points: 1, demo_note: "Demo mode" });
    expect(await screen.findByTestId("history-chart")).toBeInTheDocument();
    expect(screen.queryByText(/demo|simulated/i)).not.toBeInTheDocument();
  });
});

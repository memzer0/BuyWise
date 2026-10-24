import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompareButton } from "../components/compare/CompareButton";
import { compareList, MAX_COMPARE } from "../components/compare/compareStore";
import { CompareTray } from "../components/compare/CompareTray";
import { ComparePage } from "../pages/ComparePage";
import type { CompareColumn, CompareResponse } from "../types/api";

afterEach(() => { act(() => compareList.clear()); vi.unstubAllGlobals(); });

const col = (id: number, title: string, extra: Partial<CompareColumn> = {}): CompareColumn => ({
  id, title, brand: "apple", category: "smartphones", image_url: null, storage_gb: 128, ram_gb: 8, colour: "black", condition: "new",
  screen_inches: 6.1, specs: {}, price: 59999, highest_price: 61999, best_store: "Croma", best_url: "https://www.croma.com/p/1",
  best_link_type: "exact_listing", availability: "in_stock", store_count: 2, last_known: null, last_verified_at: null,
  deal_score: 60, deal_label: "Good deal", buywise_score: 55, decision: { verdict: "BUY_NOW", label: "Buy now", headline: "h" },
  rating: 4.4, ratings_count: 500, praised: ["Camera"], complaints: [], reviews_analysed: 6,
  history: { lowest: 58999, average: 60500, highest: 62999 }, ...extra,
});

const DATA: CompareResponse = {
  products: [col(1, "Phone A", { price: 54999, storage_gb: 256, deal_score: 80 }), col(2, "Phone B", { complaints: ["Heating"] })],
  missing: [], max: 4,
  summary: { overall: "Phone A leads on lowest price and best deal right now.",
    highlights: [{ key: "cheapest", product_id: 1, label: "Lowest price", text: "Phone A is the cheapest at ₹54,999 (Croma), ₹5,000 less than Phone B." }],
    differences: ["Storage: 256 GB (Phone A) vs 128 GB (Phone B)."], notes: ["A note."] },
};

function renderAt(path: string, ui: React.ReactNode, route = "*") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={ui} /></Routes></MemoryRouter></QueryClientProvider>);
}

describe("compare selection", () => {
  it("adds and removes products, caps the list and shows the tray", async () => {
    const item = { id: 1, title: "Phone A", image_url: null, category: "smartphones" };
    renderAt("/", <><CompareButton item={item} /><CompareTray /></>);
    await userEvent.click(screen.getByTestId("compare-toggle"));
    expect(screen.getByTestId("compare-toggle")).toHaveTextContent("Added to compare");
    expect(screen.getByTestId("compare-tray")).toHaveTextContent("Add 1 more product to compare");
    act(() => { compareList.add({ ...item, id: 2, title: "Phone B" }); });
    expect(screen.getByTestId("compare-now")).toHaveAttribute("href", "/compare?ids=1,2");
    act(() => { for (let i = 3; i <= MAX_COMPARE; i++) compareList.add({ ...item, id: i }); });
    expect(compareList.add({ ...item, id: 99 })).toBe(false);
    expect(compareList.get()).toHaveLength(MAX_COMPARE);
    await userEvent.click(screen.getByTestId("compare-toggle"));
    expect(compareList.has(1)).toBe(false);
  });
});

describe("ComparePage", () => {
  it("shows the summary and a table with the best values highlighted", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(DATA), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    renderAt("/compare?ids=1,2", <ComparePage />, "/compare");
    expect(await screen.findByTestId("compare-summary")).toHaveTextContent("Phone A leads on lowest price");
    expect(String((fetch.mock.calls[0] as unknown[])[0])).toMatch(/\/api\/compare\?ids=1,2$/);
    const price = screen.getByTestId("row-price");
    expect(within(price).getAllByRole("cell")[0]).toHaveAttribute("data-best", "true");
    expect(within(price).getAllByRole("cell")[1]).not.toHaveAttribute("data-best");
    expect(screen.getByTestId("row-complaints")).toHaveTextContent("Heating");
    expect(screen.getAllByRole("link", { name: /Buy on Croma/ })[0]).toHaveAttribute("href", "https://www.croma.com/p/1");
    // "only differences" hides rows where every product has the same value
    expect(screen.getByTestId("row-ram")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Show only differences"));
    expect(screen.queryByTestId("row-ram")).not.toBeInTheDocument();
    expect(screen.getByTestId("row-storage")).toBeInTheDocument();
  });

  it("explains how to pick products when fewer than 2 are chosen", () => {
    renderAt("/compare?ids=5", <ComparePage />, "/compare");
    expect(screen.getByText("Pick at least 2 products to compare")).toBeInTheDocument();
  });
});

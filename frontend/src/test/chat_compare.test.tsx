import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatAssistant } from "../components/ChatAssistant";
import { SearchBar } from "../components/SearchBar";

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });

function wrap(ui: React.ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes><Route path="*" element={ui} /></Routes></MemoryRouter></QueryClientProvider>);
}

describe("ChatAssistant", () => {
  it("asks about the open product and shows the reply", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const u = String(input);
      const body = u.includes("/assistant/status") ? { configured: true, provider: "gemini", model: "m" }
        : { reply: "Flipkart is cheapest at **₹69,999**.", provider: "gemini", model: "m", grounded_on_product: true };
      void init;
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetch);
    wrap(<ChatAssistant />, "/product/38");
    await userEvent.click(screen.getByTestId("chat-open"));
    await userEvent.click(screen.getByRole("button", { name: "Which store is cheapest?" }));
    expect(await screen.findByText("₹69,999")).toBeInTheDocument();
    const call = fetch.mock.calls.find(([u]) => String(u).includes("/assistant/chat"))!;
    expect(JSON.parse(String(call[1]!.body))).toMatchObject({ product_id: 38, messages: [{ role: "user", content: "Which store is cheapest?" }] });
  });

  it("explains when the assistant isn't set up", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).includes("status")
      ? new Response(JSON.stringify({ configured: false, provider: null, model: null }), { status: 200, headers: { "content-type": "application/json" } })
      : new Response(JSON.stringify({ error: { code: "assistant_not_configured", message: "The AI assistant isn't set up yet." } }), { status: 503, headers: { "content-type": "application/json" } })));
    wrap(<ChatAssistant />);
    await userEvent.click(screen.getByTestId("chat-open"));
    expect(await screen.findByText(/add a GEMINI_API_KEY/)).toBeInTheDocument();
  });
});

describe("Compare button", () => {
  it("tells the shopper to type something when the box is empty", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ suggestions: [] }), { status: 200, headers: { "content-type": "application/json" } })));
    wrap(<SearchBar />);
    await userEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Type a product name first");
  });
});

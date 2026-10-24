import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ReviewsSection } from "../components/ReviewsSection";
import { askReviews } from "../components/reviews/askReviews";
import type { ReviewItem, Reviews } from "../types/api";

const rev = (id: number, text: string, aspect_sentiment: ReviewItem["aspect_sentiment"], extra: Partial<ReviewItem> = {}): ReviewItem => ({
  id, title: null, text, user_name: `user${id}`, source: "amazon.in", rating: 4, date: "2 months ago", incentivized: null,
  sentiment: 0, aspects: Object.keys(aspect_sentiment), aspect_sentiment, signals: [], duplicate_of: [], counted: true, group: "other", ...extra,
});

const R: Reviews = {
  available: true, rating: 4.3, reviews_count: 1200, distribution: [{ stars: 5, count: 900 }, { stars: 1, count: 300 }],
  origin: { source: "Google Shopping", live: true, fetched_at: new Date().toISOString(), stores: ["amazon.in"] },
  coverage: { sample_size: 4, total_ratings: 1200, coverage_pct: 0.33, level: "low", note: "Only 4 written reviews available – treat these as individual experiences, not a verdict.", duplicates_excluded: 0 },
  summary: "In the 4 reviews available, reviewers mostly praise battery; recurring complaints mention heating.",
  aspects: [
    { aspect: "Battery", mentions: 3, positive: 2, negative: 1, mixed: 0, neutral: 0, share: 0.75, stance: "praised", confidence: "low",
      examples: [{ review_id: 0, text: "Battery easily lasts a full day.", sentiment: 1 }, { review_id: 2, text: "The battery drains fast when gaming.", sentiment: -1 }] },
    { aspect: "Heating", mentions: 2, positive: 0, negative: 2, mixed: 0, neutral: 0, share: 0.5, stance: "complaint", confidence: "low",
      examples: [{ review_id: 2, text: "It heats up a lot during games.", sentiment: -1 }] },
  ],
  aspect_keywords: { Battery: ["battery", "drain"], Heating: ["heat", "heats", "hot"], Performance: ["performance", "lag"], Camera: ["camera"] },
  use_cases: [{ key: "gaming", label: "Gaming", aspects: [{ aspect: "Performance", why: "Lag shows up first in games." }, { aspect: "Heating", why: "Long sessions get hot." }] }],
  insights: [],
  reviews: [
    rev(0, "Battery easily lasts a full day. Great phone.", { Battery: "positive" }, { sentiment: 1 }),
    rev(1, "Battery is solid and the screen is nice.", { Battery: "positive" }, { sentiment: 1 }),
    rev(2, "The battery drains fast when gaming. It heats up a lot during games.", { Battery: "negative", Heating: "negative" }, { sentiment: -1, rating: 2 }),
    rev(3, "Gets hot while charging.", { Heating: "negative" }, { sentiment: -1, signals: ["Marked as incentivized by the source"], incentivized: true, group: "flagged" }),
  ],
  reliability: { signals: [{ kind: "incentivized", label: "Incentivized reviews", detail: "1 review(s) are marked by the source as incentivized.", review_ids: [3] }],
    limitations: ["Verified-purchase status and reviewer history aren't provided by the source, so they aren't checked."], checked: ["Near-identical wording"] },
  counts: { flagged: 1, other: 3 }, method_note: "Keyword rules.",
};

describe("askReviews (grounded answers)", () => {
  it("answers an aspect question with counts and verbatim excerpts", () => {
    const a = askReviews("How is the battery life?", R);
    expect(a.status).toBe("answered");
    expect(a.lines[0]).toBe("Battery: 3 of 4 reviews mention it (2 positive, 1 negative) – low confidence, too few reviews to call it a trend.");
    expect(a.excerpts.length).toBeGreaterThan(0);
    for (const e of a.excerpts) expect(`${e.review.text}`).toContain(e.text); // quotes are word for word
  });

  it("says when the reviews don't cover the question", () => {
    const a = askReviews("Is the warranty claim process easy?", R);
    expect(a.status).toBe("insufficient");
    expect(a.lines[0]).toMatch(/None of the 4 available reviews mention this/);
    expect(a.excerpts).toEqual([]);
  });

  it("reports an aspect nobody mentions instead of guessing", () => {
    const a = askReviews("How is the camera?", R);
    expect(a.status).toBe("insufficient");
    expect(a.lines[0]).toBe("Camera: none of the 4 reviews mention it.");
  });

  it("lists recurring complaints with only negative excerpts", () => {
    const a = askReviews("What do people complain about?", R);
    expect(a.lines.join(" ")).toMatch(/Heating: 2 of 4 reviews/);
    expect(a.excerpts.every((e) => e.tone !== "positive")).toBe(true);
  });

  it("maps a suitability question to the use case's aspects", () => {
    const a = askReviews("Is it good for gaming?", R);
    expect(a.lines[0]).toMatch(/For gaming, the aspects that matter most are performance, heating/);
    expect(a.lines).toContain("Performance: none of the 4 reviews mention it.");
  });
});

describe("ReviewsSection", () => {
  it("shows origin, coverage and the aspect grid; selecting an aspect filters reviews and shows evidence", async () => {
    render(<ReviewsSection r={R} />);
    expect(screen.getByTestId("review-origin")).toHaveTextContent("Live reviews via Google Shopping");
    expect(screen.getByTestId("review-coverage")).toHaveTextContent("individual experiences");
    const cards = screen.getAllByTestId("aspect-card");
    expect(cards[0]).toHaveTextContent("Battery");
    expect(cards[0]).toHaveTextContent("3 of 4 reviews (75%)");
    expect(cards[0]).toHaveTextContent("Low confidence");
    await userEvent.click(cards[1]); // Heating
    expect(screen.getByTestId("aspect-evidence")).toHaveTextContent("It heats up a lot during games.");
    expect(screen.getAllByTestId("review-card")).toHaveLength(2);
    await userEvent.click(screen.getByRole("radio", { name: "positive" }));
    expect(screen.queryAllByTestId("review-card")).toHaveLength(0);
    expect(screen.getByText("No reviews match these filters.")).toBeInTheDocument();
  });

  it("puts use-case aspects first with the reason, without hiding the rest", async () => {
    render(<ReviewsSection r={R} />);
    await userEvent.click(screen.getByRole("radio", { name: "Gaming" }));
    const grid = screen.getByTestId("aspect-grid");
    const items = within(grid).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Performance");
    expect(items[0]).toHaveTextContent("None of the 4 reviews mention this.");
    expect(items[1]).toHaveTextContent("Heating");
    expect(items[1]).toHaveTextContent("Why it matters: Long sessions get hot.");
    expect(items[2]).toHaveTextContent("Battery"); // still listed
  });

  it("asks the reviews and shows grounded excerpts", async () => {
    render(<ReviewsSection r={R} />);
    await userEvent.type(screen.getByLabelText("Question about this product's reviews"), "Does it heat up?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const ans = screen.getByTestId("review-answer");
    expect(ans).toHaveTextContent("Heating: 2 of 4 reviews mention it (0 positive, 2 negative)");
    expect(within(ans).getAllByTestId("answer-excerpt")[0]).toHaveTextContent(/heats up a lot during games|Gets hot while charging/);
  });

  it("adds an AI summary of the same quotes when the server provides one", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ status: "ok", answer: "Two reviewers say it heats up while gaming [1][2].", citations: [1, 2] }),
      { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    render(<MemoryRouter initialEntries={["/product/8"]}><Routes><Route path="/product/:id" element={<ReviewsSection r={R} />} /></Routes></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "Does it heat up?" }));
    expect(await screen.findByTestId("ai-answer")).toHaveTextContent("Two reviewers say it heats up while gaming [1][2].");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/products\/8\/reviews\/ask$/);
    const body = JSON.parse(String(init.body));
    expect(body.aspects).toEqual(["Heating"]);
    expect(body.excerpts.map((e: { review_id: number }) => e.review_id).sort()).toEqual([2, 3]);
    expect(screen.getAllByTestId("answer-excerpt")[0]).toHaveTextContent("[1]");
    vi.unstubAllGlobals();
  });

  it("withholds an AI summary the server rejected and keeps the quote-based answer", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "rejected", answer: null }), { status: 200 })));
    render(<MemoryRouter initialEntries={["/product/8"]}><Routes><Route path="/product/:id" element={<ReviewsSection r={R} />} /></Routes></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: "How is the battery life?" }));
    expect(await screen.findByTestId("ai-withheld")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-answer")).not.toBeInTheDocument();
    expect(screen.getByTestId("review-answer")).toHaveTextContent("Battery: 3 of 4 reviews mention it");
    vi.unstubAllGlobals();
  });

  it("explains reliability signals and limitations", () => {
    render(<ReviewsSection r={R} />);
    const rel = screen.getByTestId("review-reliability");
    expect(rel).toHaveTextContent("1 pattern found");
    expect(rel).toHaveTextContent("Verified-purchase status");
    expect(rel).toHaveTextContent("not proof that any review is fake");
  });

  it("handles products without reviews", () => {
    render(<ReviewsSection r={{ available: false, reason: "Google Shopping returned no reviews for this product." }} />);
    expect(screen.getByTestId("reviews")).toHaveTextContent("Google Shopping returned no reviews");
  });
});

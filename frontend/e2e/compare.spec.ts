import { expect, test } from "@playwright/test";

test("search, open product, inspect offers and exact Buy links", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("combobox").fill("pixel 9");
  await page.getByRole("button", { name: /compare/i }).click();

  await expect(page).toHaveURL(/\/search\?q=pixel%209/);
  const card = page.getByTestId("product-card").first();
  await expect(card).toContainText("Pixel 9");
  await expect(card).toContainText("2 sellers compared");
  await card.click();

  await expect(page.getByTestId("product-title")).toContainText("Pixel 9");
  const rows = page.getByTestId("offer-row");
  await expect(rows).toHaveCount(2);
  // Freshness + source shown for every offer
  for (const r of await rows.all()) {
    await expect(r).toContainText(/Recently verified|Cached/);
    await expect(r).toContainText("Source:");
  }
  // Each Buy link is the exact URL of its own offer
  await expect(page.locator('a[data-testid="buy-link"][href="https://testretailerb.example/p/gb1"]')).toBeVisible();
  await expect(page.locator('a[data-testid="buy-link"][href="https://testretailera.example/p/ga1"]')).toBeVisible();
  await expect(rows.first()).toContainText("Lowest verified");
  await expect(rows.first()).toContainText("Test Retailer B");

  // Only one observation per seller exists -> chart must not pretend to have history
  await expect(page.getByTestId("history-chart").or(page.getByTestId("history-insufficient"))).toBeVisible();
});

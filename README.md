# BuyWise — electronics price comparison for India

BuyWise searches electronics across Indian retailers through **official / licensed data APIs**, matches the exact
product variant across sellers, links every price to the exact listing it came from, records real price history,
and scores deals transparently. It never invents products, prices, ratings or history: if no provider is
configured or every provider fails, it says so.

```
backend/   FastAPI + SQLAlchemy + Alembic (Python 3.11+)
  app/providers/   one adapter per data source (Amazon Creators API, Flipkart Affiliate, SerpApi Google Shopping)
  app/matching/    attribute extraction + variant matching (storage, RAM, tier, generation, condition, colour, GTIN)
  app/pricing/     freshness labels + "lowest verified price" rules
  app/scoring/     BuyWise Score + baseline price prediction
  app/services/    search, ingest, refresh, history, alerts
  app/workers/     in-process automatic refresh scheduler (no Redis needed)
  tests/           pytest suite (+ test-only fake provider and e2e server)
frontend/  React 18 + Vite + TypeScript + Tailwind v4 + TanStack Query + Recharts
```

## 1. Data providers – you need at least one key to see prices

| Provider | What it gives | Exact Buy link? | How to get access | `.env` keys |
|---|---|---|---|---|
| **SerpApi – Google Shopping India** (licensed API) | Offers from whichever Indian retailers Google Shopping India lists for the product, plus ratings | Only when SerpApi returns the merchant link; otherwise labelled **"Google Shopping page"** and never called an exact listing | Sign up at serpapi.com → copy your private API key (check serpapi.com/pricing for the current free allowance) | `SERPAPI_API_KEY` |
| **Amazon Creators API** (official) | Amazon.in items, buy-box price, availability, GTIN/model | Yes – `detailPageURL` with your partner tag | Amazon Associates India account approved for the Creators API → create Credential ID/Secret. PA-API 5 is deprecated; this adapter uses its replacement | `AMAZON_CREATORS_CREDENTIAL_ID`, `AMAZON_CREATORS_CREDENTIAL_SECRET`, `AMAZON_PARTNER_TAG` |
| **Flipkart Affiliate API** (official) | Flipkart items, special/selling price, MRP, stock, seller, shipping | Yes – `productUrl` | affiliate.flipkart.com → register → API token page (Tracking ID + Token) | `FLIPKART_AFFILIATE_ID`, `FLIPKART_AFFILIATE_TOKEN` |

Not integrated directly: **Croma, Reliance Digital, Vijay Sales, Smartprix, 91mobiles** – no public product/price API
was found, and BuyWise does not scrape sites or bypass bot protection. Their offers can still appear through Google Shopping.

**Easiest start:** a SerpApi key alone gives multi-retailer comparison. Opening a product calls SerpApi's store list once (1 extra search) to replace Google Shopping pages with each store's own product link (`SERPAPI_STORE_LINKS`). Sellers that list skins/cases under phone names are ignored (`EXCLUDED_SELLERS`). Add Amazon/Flipkart keys for exact retailer links.

> Verification status: the adapters were built from each provider's published documentation and are covered by
> parsing tests, but they have **not yet been run against the live APIs** (the build environment had no internet
> access to those hosts and no credentials). After you add a key, open **Diagnostics** – a provider shows
> `working` only after a real successful fetch. If a provider's response shape differs from its docs, the
> failure is recorded there (and the listing is rejected rather than shown with a wrong price).

## 2. Run on Windows

**Quickest (no Node.js needed):** the backend also serves the pre-built website from `frontend\dist`. After the backend steps below, just open **http://127.0.0.1:8765**. The Node.js steps are only needed if you want to change the frontend code.


Requirements: **Python 3.11+** (python.org, tick "Add to PATH") and **Node.js 20+** (nodejs.org).

**Terminal 1 – backend** (Command Prompt):
```bat
cd buywise\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```
In `notepad`, paste at least one API key, save, close. The database (`backend\buywise.db`, SQLite) is created and
migrated automatically on startup (`AUTO_MIGRATE=true`). To migrate manually: `alembic upgrade head`.

PowerShell users: activate with `.venv\Scripts\Activate.ps1` (if blocked, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once), and use `Copy-Item .env.example .env`.

**Terminal 2 – frontend:**
```bat
cd buywise\frontend
copy .env.example .env
npm install
npm run dev
```
Open **http://127.0.0.1:5173**. API docs: http://127.0.0.1:8765/docs.

Or just double-click `start-windows.bat` in the project root after doing the install steps once.

### Tests and build
```bat
cd backend  &&  .venv\Scripts\activate  &&  python -m pytest -q
cd frontend &&  npm test  &&  npm run build
cd frontend &&  npx playwright install chromium  &&  npm run e2e
```
The e2e suite starts its own backend (`backend/tests/e2e_server.py`, port 8001) with a **test-only** fake provider,
so it needs no API keys. Fixtures live only under `tests/` and are never loaded by the real app.

### Troubleshooting
- **"Cannot reach the BuyWise server"** – backend not running, or `frontend\.env` `VITE_API_BASE_URL` doesn't match. Restart `npm run dev` after editing `.env`.
- **CORS error in browser console** – add your frontend origin to `CORS_ORIGINS` in `backend\.env`.
- **Search says "No price providers are configured"** – no key in `backend\.env`, or backend not restarted after editing it.
- **Provider shows `failing` / `cooling_down`** – see Diagnostics (set `ADMIN_TOKEN` in `.env` to unlock details). 401/403 = wrong or unapproved credentials; 429/quota = wait, BuyWise backs off automatically.
- **`pip install` fails on psycopg** – it's only needed for PostgreSQL; remove the line if you use SQLite.
- **`[WinError 10013]` when starting the backend** – Windows has reserved or blocked that port. Use another port (the default here is 8765) and set the same port in `frontend\.env` `VITE_API_BASE_URL`.
- **Port in use** – change `--port` and update `VITE_API_BASE_URL` / `CORS_ORIGINS` accordingly.

### PostgreSQL / Docker (optional)
`docker compose up` starts PostgreSQL, backend and frontend. For a local Postgres without Docker set
`DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/buywise`.

## 3. How it works

**Search** (`GET /api/search`): query → all configured providers concurrently (per-provider timeout, spacing,
concurrency limit, Retry-After and exponential back-off) → each listing validated (positive INR price, http(s) URL,
title, stable id) → matched to a canonical product → offers + price observations stored → results cached for
`SEARCH_CACHE_SECONDS`. Response reports each provider's status; failures give partial results, never invented ones.

**Matching**: GTIN / model number first; otherwise any disagreement in brand, storage, RAM, colour, screen size,
tier (Pro/Max/Ultra/Plus/FE…), generation tokens (iPhone 15 vs 16) or condition (new vs refurbished) blocks a merge.
Remaining similarity gives a confidence score. ≥0.80 → verified; 0.60–0.80 → shown as *Unverified match* and
excluded from best price (logged in Diagnostics); lower → separate product. Evidence is stored with every offer.

**Freshness**: `live` (fetched during this request), `cached` (verified within `STALE_AFTER_SECONDS`, default 24 h),
`stale` (older; shown but never "cheapest"), `unavailable`. Every price shows its last-checked time.

**Accessories & trusted stores**: device searches hide accessories (cases, covers, skins, screen guards…) unless *Include accessories* is ticked. By default only products and offers from stores on the trusted list (Amazon, Flipkart, Croma, Reliance Digital, Vijay Sales, Tata CLiQ, JioMart, official Apple/Samsung/OnePlus/Xiaomi/Google/Lenovo/HP/Dell/ASUS/Acer/Sony stores, Sangeetha, Poorvika, Bajaj Electronics, Cashify…) are shown; *Show all stores* reveals the rest, but they are never used for the lowest price. The list is in `app/pricing/trust.py` and can be overridden with `TRUSTED_STORES` / `TRUSTED_DOMAINS`. It identifies established stores; it does not vet individual marketplace sellers.

**Top stores**: Flipkart, Reliance Digital, Amazon, Vijay Sales and Croma (`PREFERRED_STORES`) are listed first in every seller table ("Top store" badge) and boost search ranking. The "Lowest verified" tag still goes to whichever trusted store is genuinely cheapest.

**Graphs & insights**: price-across-stores bar chart, price-history chart, lowest/average/highest observed price, "x% below average" and "lowest price we've seen" tags, and price-drop tags on search results – all from real observations only.

**Lowest verified price** requires: a trusted store, verified data, verified match, INR, not stale, not out of stock, new condition
(unless refurbished is included). Shipping is added to totals only when the provider reports it.

**Automatic refresh**: opening a product older than `FRESH_WINDOW_SECONDS` triggers a background refresh (the page
polls until it finishes). The scheduler refreshes watched/alerted/popular products every `REFRESH_POPULAR_MINUTES`
and other viewed products every `REFRESH_NORMAL_MINUTES`, a few per tick, deduplicating concurrent refreshes.
Run only one backend process with `SCHEDULER_ENABLED=true`.

**History**: one observation per offer per `OBSERVATION_BUCKET_SECONDS` (unique constraint prevents duplicates).
Charts plot only real observations (step lines, no interpolation) and say when there's too little data.

**BuyWise Score** (weights in `.env`): price vs. observed history 35%, price vs. other sellers 25%, trend 15%,
rating 15% (only if a provider returns real ratings), availability & link quality 10%. Missing components are dropped
and the rest re-weighted; *data completeness* shows how much was available. **Prediction**: least-squares trend on
the daily minimum price, only after 14 days of observations, validated on the last 20% of days (MAE shown).

**Regret Shield** (`/purchases`, plus a card on every product page):
*Before you buy* maps the Decision Engine to **Buy now / Wait / Compare first / Insufficient data** and lists the
evidence checked (current price, price vs. history, exact variant, delivery, seller, warranty, return policy, score)
and what is missing. *After you buy* you enter the store, price and date (order reference, return deadline,
price-protection deadline and expected return costs are optional; no receipts, passwords, OTPs or payment details).
BuyWise then compares your price with the cheapest comparable offer for the **same product record** (same variant,
trusted store, verified match, not stale, in stock, same condition):
`difference = purchase price − comparable price`, `% = difference ÷ purchase price × 100`.
A drop counts when it is ≥ `REGRET_MIN_DROP_PCT` (2 %) **and** ≥ `REGRET_MIN_DROP_AMOUNT` (₹200). If no comparable
offer is verified the purchase shows *Comparable offer unavailable* (or *Prices are stale*) – never a guessed price.
Net benefit is shown only if you enter expected costs, and only as an estimate. BuyWise never assumes a store offers
price protection or will accept a return. Checks run on the scheduler tick (at most one stored check per purchase per
`REGRET_CHECK_BUCKET_MINUTES`); tracked products are refreshed like watchlisted ones. Notifications (price drop,
deadline within `REGRET_DEADLINE_WARN_DAYS`, prices unverifiable for 3 checks) appear in-app and are de-duplicated.
Monitoring runs only while the backend is running. Purchases belong to the browser's anonymous id; other ids get 404.

**E-mail**: price alerts (optional e-mail field) and Regret Shield purchases (optional e-mail) are e-mailed once per event
over SMTP (`SMTP_*` in `.env`; Gmail needs an App Password). Diagnostics → *Send test e-mail* checks the setup.

**AI assistant** (chat bubble, bottom right): answers with the open product's BuyWise data (current store prices, deal
score, decision, history summary) and is told never to invent prices or offers. Uses `GEMINI_API_KEY`
(default model `gemini-flash-latest`) or `ANTHROPIC_API_KEY`; keys stay on the server. Endpoints: `GET /api/assistant/status`,
`POST /api/assistant/chat`.

**Demo history** (footer switch, on by default): products with fewer than 7 days of real checks get a deterministic
*simulated* history before tracking began, drawn dashed yellow and labelled "DEMO" everywhere it influences a verdict.
It is never stored and never used for alerts, Regret Shield post-purchase checks or the current price.

**Alerts** fire once when the lowest verified price ≤ target and re-arm when it rises above. In-app always;
e-mail only if SMTP is configured (otherwise the event says `not_configured`). Watchlist/alerts are tied to an
anonymous per-browser id (no accounts).

## 4. API
`GET /api/health` · `GET /api/providers/status` · `GET /api/search?q=` (filters: `category, brand, min_price,
max_price, storage_gb, ram_gb, condition, sort, page, page_size`) · `GET /api/suggestions?q=` · `GET /api/home` ·
`GET /api/categories` · `GET /api/products/{id}` · `GET /api/products/{id}/offers?sort=` ·
`GET /api/products/{id}/history?range=7d|30d|90d|180d|365d` · `POST /api/products/{id}/refresh` ·
`GET|POST /api/watchlist`, `DELETE /api/watchlist/{product_id}` · `GET|POST /api/alerts`, `DELETE /api/alerts/{id}` ·
`GET /api/products/{id}/regret-shield` · `GET|POST /api/purchases`, `GET|PATCH|DELETE /api/purchases/{id}`,
`GET /api/purchases/{id}/history`, `POST /api/purchases/{id}/check`, `GET /api/purchases/notifications`,
`POST /api/purchases/notifications/read` ·
`GET /api/admin/diagnostics`, `POST /api/admin/scheduler/tick` (Bearer `ADMIN_TOKEN`).
Watchlist/alert/purchase routes need an `X-Client-Id` header (the frontend sends one automatically). Errors are
`{"error": {"code", "message", "request_id"}}`; every response carries `X-Request-ID`.

## 5. Security notes
API keys stay server-side (never sent to the browser, never logged). Only http(s) offer URLs are stored or rendered;
`javascript:` and credential-bearing URLs are rejected. The backend only calls the fixed provider endpoints – it never
fetches user-supplied URLs. CORS is limited to `CORS_ORIGINS`; `/api` is rate limited per IP; admin routes require a token.

export type Freshness = "live" | "cached" | "stale" | "unavailable";
export type LinkType = "exact_listing" | "aggregator_page" | "search_page" | "homepage";

export interface ProviderRun {
  provider: string;
  name?: string;
  status: "ok" | "empty" | "not_configured" | "error" | "rate_limited" | "cooling_down";
  listings: number;
  rejected?: number;
  error: string | null;
  duration_ms: number;
}

export interface ProductSummary {
  id: number;
  title: string;
  brand: string | null;
  category: string;
  image_url: string | null;
  storage_gb: number | null;
  ram_gb: number | null;
  colour: string | null;
  condition: string;
  screen_inches: number | null;
  offer_count: number;
  verified_offer_count: number;
  trusted_offer_count: number;
  preferred_stores: string[];
  previous_price: number | null;
  price_change: number | null;
  retailers: string[];
  best_price: number | null;
  best_retailer: string | null;
  best_freshness: Freshness | null;
  best_link_type: LinkType | null;
  last_verified_at: string | null;
  relevance?: number;
  query_mismatches?: string[];
}

export interface SearchParams {
  q: string;
  category?: string;
  brand?: string[];
  min_price?: number;
  max_price?: number;
  storage_gb?: number;
  ram_gb?: number;
  condition?: "new" | "refurbished" | "any";
  include_accessories?: boolean;
  all_stores?: boolean;
  sort?: "relevance" | "price_asc" | "price_desc" | "offers";
  page?: number;
  page_size?: number;
}

export interface SearchResponse {
  query: string;
  source: "live" | "cache";
  fetched_at: string;
  providers: ProviderRun[];
  partial: boolean;
  no_providers_configured: boolean;
  all_providers_failed: boolean;
  facets: { brands: string[]; categories: string[]; storage_gb: number[]; ram_gb: number[] };
  total: number;
  page: number;
  page_size: number;
  hidden_accessories: number;
  hidden_untrusted: number;
  results: ProductSummary[];
}

export interface Offer {
  offer_id: number;
  provider: string;
  provider_name: string;
  retailer: string | null;
  seller_name: string | null;
  listing_title: string;
  price: number | null;
  mrp: number | null;
  currency: string;
  shipping_cost: number | null;
  total_cost: number | null;
  availability: "in_stock" | "out_of_stock" | "preorder" | "unknown";
  condition: string;
  product_url: string | null;
  link_type: LinkType;
  image_url: string | null;
  rating: number | null;
  rating_count: number | null;
  warranty: string | null;
  fetched_at: string;
  last_verified_at: string | null;
  source_type: string;
  freshness_status: Freshness;
  verification_status: string;
  match_status: "verified" | "unverified";
  match_confidence: number;
  eligible_for_best_price: boolean;
  ineligible_reason: string | null;
  is_best_price: boolean;
  trusted_store: boolean;
  preferred_rank: number | null;
  vs_best_pct?: number | null;
  offer_notes?: string[];
}

export interface ScoreComponent {
  key: string;
  label: string;
  weight: number;
  score: number | null;
  explanation: string;
}

export interface Decision {
  verdict: "BUY_NOW" | "WAIT" | "CONSIDER_ALTERNATIVES" | "NOT_ENOUGH_DATA";
  label: string;
  headline: string;
  reasons: string[];
  limitations: string[];
  evidence_level: "low" | "medium" | "high";
  alternatives: { id: number; title: string; best_price: number; retailer: string | null; image_url: string | null }[];
}

export interface OfferTermResult {
  text: string; kind: string; banks: string[]; flat_off: number | null; percent: number | null; cap: number | null;
  min_purchase: number | null; code: string | null; saving: number; reason?: string;
}

export interface FinalPrice {
  stores: { offer_id: number; retailer: string; base_price: number; shipping: number | null; guaranteed_total: number | null;
    applied: OfferTermResult[]; not_applied: OfferTermResult[]; possible_total: number | null; unknowns: string[] }[];
  banks_mentioned: string[];
  selected_banks: string[];
  coupons_included: boolean;
  offers_data_available: boolean;
  assumptions: string[];
}

export interface Timing {
  available: boolean;
  reason: string | null;
  method?: string;
  stats: { highest: number | null; average: number | null; lowest: number | null; current: number | null };
  horizons: { key: "3d" | "1w" | "1m"; label: string; score: number; recommendation: string; tone: "good" | "fair" | "wait"; why: string[] }[];
}

export type AspectSentiment = "positive" | "negative" | "mixed" | "neutral";

export interface ReviewItem {
  id: number;
  title: string | null; text: string | null; user_name: string | null; source: string | null; rating: number | null;
  date: string | null; incentivized: boolean | null; sentiment: number; aspects: string[];
  aspect_sentiment: Record<string, AspectSentiment>;
  signals: string[];
  /** ids of near-identical reviews */
  duplicate_of: number[];
  /** false for a near-duplicate of an earlier review (listed, but not counted in the statistics) */
  counted: boolean;
  group: "flagged" | "other";
}

export interface ReviewAspect {
  aspect: string;
  mentions: number; positive: number; negative: number; mixed: number; neutral: number;
  /** mentions ÷ reviews in the sample */
  share: number;
  stance: "praised" | "complaint" | "mixed" | "neutral" | "limited";
  confidence: "low" | "medium" | "high";
  examples: { review_id: number; text: string; sentiment: number }[];
}

export interface ReviewUseCase { key: string; label: string; aspects: { aspect: string; why: string }[] }

export interface ReviewReliability {
  signals: { kind: "duplicate_text" | "incentivized" | "timing_cluster"; label: string; detail: string; review_ids: number[] }[];
  limitations: string[];
  checked: string[];
}

export interface Reviews {
  available: boolean;
  reason?: string;
  origin?: { source: string; live: boolean; fetched_at: string | null; stores: string[] };
  rating?: number | null;
  reviews_count?: number | null;
  distribution?: { stars: number; count: number }[];
  coverage?: { sample_size: number; total_ratings: number | null; coverage_pct: number | null; level: "low" | "medium" | "high";
    note: string; duplicates_excluded: number };
  summary?: string | null;
  aspects?: ReviewAspect[];
  aspect_keywords?: Record<string, string[]>;
  use_cases?: ReviewUseCase[];
  insights?: { type: "pro" | "con" | "point"; text: string }[];
  reviews?: ReviewItem[];
  reliability?: ReviewReliability;
  counts?: { flagged: number; other: number };
  sample_note?: string;
  method_note?: string;
  fetched_at?: string | null;
}

export interface ProductDetail {
  decision: Decision;
  timing: Timing;
  reviews: Reviews;
  final_price: FinalPrice;
  variants: { id: number; storage_gb: number | null; colour: string | null; best_price: number | null; title: string; image_url: string | null }[];
  deal: {
    score: number | null;
    label: string;
    completeness: number;
    insight: { kind: "good" | "warning" | "info"; title: string; body: string } | null;
    checks: { key: string; label: string; max_points: number; status: "pass" | "same" | "fail" | "na"; points: number; detail: string }[];
    price_changes: { date: string; from: number; to: number; change: number }[];
  };
  similar: { id: number; title: string; image_url: string | null; best_price: number; retailer: string | null; buy_url: string | null; link_type: LinkType | null }[];
  product: ProductSummary & {
    family: string | null;
    specs: Record<string, string>;
    identifiers: { kind: string; value: string }[];
    last_refreshed_at: string | null;
    created_at: string;
  };
  offers: Offer[];
  summary: {
    lowest_verified_price: number | null;
    highest_verified_price: number | null;
    price_difference: number | null;
    verified_offer_count: number;
    total_offer_count: number;
    shipping_note: string;
    /** Last confirmed trusted-store price, only when there is no current one. Reference only – never "current". */
    last_known?: { price: number; retailer: string; observed_at: string; date: string; days_ago: number; age: string } | null;
  };
  score: {
    score: number | null;
    confidence: number;
    verdict: string | null;
    reasons: string[];
    limitations: string[];
    components: ScoreComponent[];
  };
  prediction: {
    available: boolean;
    reason: string | null;
    predicted_price: number | null;
    horizon_days: number;
    slope_per_day: number | null;
    holdout_mae: number | null;
    days_used: number;
    method: string;
  };
  refresh_in_progress: boolean;
  /** true when Demo mode added simulated history to this product's graph and advice */
  demo_history?: boolean;
  demo_note?: string | null;
  affiliate_disclosure: string;
}

export interface OffersResponse {
  product_id: number;
  sort: string;
  offers: Offer[];
  hidden_untrusted: number;
}

export interface HistoryResponse {
  range: string;
  points: { observed_at: string; price: number; retailer: string; offer_id: number }[];
  series: { retailer: string; points: { observed_at: string; price: number }[] }[];
  daily_min: { date: string; min_price: number }[];
  observation_count: number;
  span_days: number;
  lowest: number | null;
  average: number | null;
  highest: number | null;
  latest: { price: number; retailer: string; observed_at: string; stores?: number } | null;
  /** One point per price check: the lowest price across stores at that moment. */
  lowest_series: { observed_at: string; price: number; retailer: string; stores: number; demo?: boolean }[];
  demo_points?: number;
  demo_note?: string | null;
  tracking_started_at: string | null;
  sufficient: boolean;
  note: string | null;
}

export interface RefreshResponse {
  status: string;
  providers: ProviderRun[];
  offers_updated?: number;
  refreshed_at?: string;
}

export interface HealthResponse {
  app: string;
  database: string;
  live_price_fetching: "operational" | "degraded" | "unverified" | "not_configured";
  configured_providers: string[];
  scheduler_running: boolean;
}

export interface ProviderStatus {
  id: string;
  name: string;
  source_type: string;
  state: "not_configured" | "cooling_down" | "working" | "failing" | "configured_untested";
  configured: boolean;
  required_env: string[];
  docs_url: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_error: string | null;
}

export interface ProvidersResponse {
  providers: ProviderStatus[];
  unsupported_sources: { name: string; reason: string }[];
}

export interface CategoriesResponse {
  categories: { id: string; name: string; tracked_products: number }[];
}

export interface HomeResponse {
  recently_tracked: ProductSummary[];
  popular: ProductSummary[];
  verified_deals: (ProductSummary & { mrp: number; discount_pct: number })[];
  deals_note: string;
}

export interface WatchlistResponse {
  items: (ProductSummary & {
    added_at: string;
    price_when_added: number | null;
    price_change: number | null;
    historical_min: number | null;
    alert: { id: number; target_price: number; active: boolean } | null;
  })[];
}

export interface AlertsResponse {
  alerts: {
    id: number;
    product_id: number;
    product_title: string;
    image_url: string | null;
    target_price: number;
    channel: string;
    email: string | null;
    active: boolean;
    armed: boolean;
    created_at: string;
    events: {
      triggered_price: number;
      retailer: string;
      offer_url: string | null;
      delivery_status: string;
      delivery_error: string | null;
      created_at: string;
    }[];
  }[];
}

// ---------------- Regret Shield ----------------
export type RegretResult = "BUY_NOW" | "WAIT" | "COMPARE_FIRST" | "INSUFFICIENT_DATA";
export interface RegretPreCheck {
  result: RegretResult;
  label: string;
  reasons: string[];
  evidence: { label: string; value: string | null; ok: boolean }[];
  missing: string[];
  limitations: string[];
  evidence_level: "low" | "medium" | "high";
  demo_history?: boolean;
  observed_at: string | null;
  best_offer: { retailer: string; price: number; product_url: string; link_type: string } | null;
}
export type PurchaseStatus =
  | "pending" | "price_drop" | "small_drop" | "no_drop" | "comparable_unavailable" | "stale_data" | "invalid_purchase_price";
export interface PurchaseDeadline { kind: "return" | "protection"; label: string; date: string; days_left: number; state: "passed" | "today" | "soon" | "upcoming" }
export interface Purchase {
  id: number; product_id: number; product_title: string; image_url: string | null;
  storage_gb: number | null; ram_gb: number | null; colour: string | null; condition: string;
  retailer: string; purchase_price: number; purchase_date: string; order_ref: string | null;
  return_deadline: string | null; protection_deadline: string | null; expected_costs: number | null; notify: boolean; email: string | null;
  status: PurchaseStatus; last_checked_at: string | null; created_at: string; unread_notifications: number;
  comparable: { status: "comparable" | "stale_data" | "comparable_unavailable"; offer_id?: number; price?: number; retailer?: string | null;
    product_url?: string; link_type?: string; freshness?: string; match_confidence?: number | null; reason: string | null };
  comparable_verified_at: string | null;
  deadlines: PurchaseDeadline[];
  difference: number | null; difference_pct: number | null; meaningful_drop: boolean;
  net_benefit: { amount: number; label: string; inputs: { difference: number; expected_costs: number } } | null;
  actions: string[]; notes: string[];
}
export interface PurchasesResponse {
  items: Purchase[];
  deadlines: (PurchaseDeadline & { purchase_id: number; product_title: string })[];
  price_drops: number[];
  thresholds: { min_drop_pct: number; min_drop_amount: number };
  email_ready?: boolean;
  monitoring: { scheduler_enabled: boolean; note: string };
}
export interface PurchaseInput {
  product_id: number; retailer: string; purchase_price: number; purchase_date: string;
  order_ref?: string | null; return_deadline?: string | null; protection_deadline?: string | null;
  expected_costs?: number | null; notify?: boolean; email?: string | null;
}
export interface PurchaseNotificationItem { id: number; purchase_id: number; kind: "price_drop" | "deadline" | "monitoring"; message: string; created_at: string; read: boolean; email_status?: string | null }
export interface PurchaseHistory {
  purchase_id: number; purchase_price: number;
  checks: { checked_at: string; status: PurchaseStatus; comparable_price: number | null; retailer: string | null; difference: number | null; offer_verified_at: string | null }[];
}

export interface CompareColumn {
  id: number; title: string; brand: string | null; category: string; image_url: string | null;
  storage_gb: number | null; ram_gb: number | null; colour: string | null; condition: string; screen_inches: number | null;
  specs: Record<string, string>;
  price: number | null; highest_price: number | null; best_store: string | null; best_url: string | null;
  best_link_type: LinkType | null; availability: Offer["availability"] | null; store_count: number;
  last_known: { price: number; retailer: string; date: string; age: string } | null;
  last_verified_at: string | null;
  deal_score: number | null; deal_label: string | null; buywise_score: number | null;
  decision: { verdict: Decision["verdict"]; label: string; headline: string };
  rating: number | null; ratings_count: number | null;
  praised: string[]; complaints: string[]; reviews_analysed: number;
  history: { lowest: number | null; average: number | null; highest: number | null };
}

export interface CompareResponse {
  products: CompareColumn[];
  missing: number[];
  max: number;
  summary: {
    overall: string | null;
    highlights: { key: "cheapest" | "deal" | "rating" | "stores"; product_id: number; label: string; text: string }[];
    differences: string[];
    notes: string[];
  } | null;
}

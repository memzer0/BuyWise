import { z } from "zod";
import type {
  AlertsResponse,
  CategoriesResponse,
  FinalPrice,
  HealthResponse,
  HistoryResponse,
  CompareResponse,
  HomeResponse,
  OffersResponse,
  Purchase,
  PurchaseHistory,
  PurchaseInput,
  PurchaseNotificationItem,
  PurchasesResponse,
  RegretPreCheck,
  ProductDetail,
  ProvidersResponse,
  RefreshResponse,
  SearchParams,
  SearchResponse,
  WatchlistResponse,
} from "../types/api";

// "same-origin" = the page is served by the BuyWise backend itself, so API calls use relative URLs.
const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
export const API_BASE =
  RAW_BASE === "same-origin" ? "" : RAW_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8765";

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  constructor(status: number, code: string, message: string, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

const errorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), request_id: z.string().nullish() }),
});

function clientId(): string {
  const key = "buywise.clientId";
  try {
    let id = localStorage.getItem(key);
    if (!id) {
      id = (crypto.randomUUID?.() ?? `${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, "").slice(0, 32);
      localStorage.setItem(key, id);
    }
    return id;
  } catch {
    return "anonymous-session-client";
  }
}

/** Demo mode (simulated history for products with little real data). Per browser; on unless switched off. */
const DEMO_KEY = "buywise.demo";
export function demoMode(): boolean {
  try { return localStorage.getItem(DEMO_KEY) !== "0"; } catch { return true; }
}
/** E-mail the shopper last used for alerts – remembered in this browser only, to prefill forms. */
export function savedEmail(): string {
  try { return localStorage.getItem("buywise.email") ?? ""; } catch { return ""; }
}
export function rememberEmail(email: string): void {
  try { if (email) localStorage.setItem("buywise.email", email); } catch { /* ignore */ }
}
export function setDemoMode(on: boolean): void {
  try { localStorage.setItem(DEMO_KEY, on ? "1" : "0"); } catch { /* storage unavailable – stays default */ }
}

async function request<T>(path: string, init: RequestInit & { admin?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", "X-Client-Id": clientId() };
  if (demoMode()) headers["X-BuyWise-Demo"] = "1";
  if (init.body) headers["Content-Type"] = "application/json";
  if (init.admin) headers["Authorization"] = `Bearer ${init.admin}`;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network_error", `Cannot reach the BuyWise server at ${API_BASE}. Is the backend running?`);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const parsed = errorSchema.safeParse(body);
    if (parsed.success) {
      throw new ApiError(res.status, parsed.data.error.code, parsed.data.error.message, parsed.data.error.request_id ?? undefined);
    }
    throw new ApiError(res.status, "http_error", `Request failed (HTTP ${res.status}).`);
  }
  return body as T;
}

export function toQuery(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  return sp.toString();
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("/api/health", { signal }),
  providers: (signal?: AbortSignal) => request<ProvidersResponse>("/api/providers/status", { signal }),
  categories: (signal?: AbortSignal) => request<CategoriesResponse>("/api/categories", { signal }),
  home: (signal?: AbortSignal) => request<HomeResponse>("/api/home", { signal }),
  search: (p: SearchParams, signal?: AbortSignal) => request<SearchResponse>(`/api/search?${toQuery({ ...p })}`, { signal }),
  suggestions: (q: string, signal?: AbortSignal) =>
    request<{ suggestions: string[] }>(`/api/suggestions?${toQuery({ q })}`, { signal }),
  product: (id: number, includeRefurbished: boolean, signal?: AbortSignal) =>
    request<ProductDetail>(`/api/products/${id}?${toQuery({ include_refurbished: includeRefurbished })}`, { signal }),
  offers: (id: number, sort: string, includeRefurbished: boolean, allStores: boolean, signal?: AbortSignal) =>
    request<OffersResponse>(
      `/api/products/${id}/offers?${toQuery({ sort, include_refurbished: includeRefurbished, all_stores: allStores })}`,
      { signal },
    ),
  finalPrice: (id: number, banks: string[], coupons: boolean, signal?: AbortSignal) =>
    request<FinalPrice>(`/api/products/${id}/final-price?${toQuery({ banks, coupons })}`, { signal }),
  history: (id: number, range: string, signal?: AbortSignal) =>
    request<HistoryResponse>(`/api/products/${id}/history?range=${range}`, { signal }),
  refresh: (id: number) => request<RefreshResponse>(`/api/products/${id}/refresh`, { method: "POST" }),
  watchlist: (signal?: AbortSignal) => request<WatchlistResponse>("/api/watchlist", { signal }),
  addWatch: (productId: number) =>
    request<{ id: number }>("/api/watchlist", { method: "POST", body: JSON.stringify({ product_id: productId }) }),
  removeWatch: (productId: number) => request<void>(`/api/watchlist/${productId}`, { method: "DELETE" }),
  alerts: (signal?: AbortSignal) => request<AlertsResponse>("/api/alerts", { signal }),
  compare: (ids: number[], signal?: AbortSignal) => request<CompareResponse>(`/api/compare?ids=${ids.join(",")}`, { signal }),
  createAlert: (body: { product_id: number; target_price: number; channel: "in_app" | "email"; email?: string }) =>
    request<{ id: number; delivery_note: string | null }>("/api/alerts", { method: "POST", body: JSON.stringify(body) }),
  deleteAlert: (id: number) => request<void>(`/api/alerts/${id}`, { method: "DELETE" }),
  regretShield: (id: number, signal?: AbortSignal) => request<RegretPreCheck>(`/api/products/${id}/regret-shield`, { signal }),
  purchases: (signal?: AbortSignal) => request<PurchasesResponse>("/api/purchases", { signal }),
  createPurchase: (body: PurchaseInput) => request<Purchase>("/api/purchases", { method: "POST", body: JSON.stringify(body) }),
  updatePurchase: (id: number, body: Partial<Omit<PurchaseInput, "product_id">>) =>
    request<Purchase>(`/api/purchases/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePurchase: (id: number) => request<void>(`/api/purchases/${id}`, { method: "DELETE" }),
  checkPurchase: (id: number) => request<Purchase>(`/api/purchases/${id}/check`, { method: "POST" }),
  purchaseHistory: (id: number, signal?: AbortSignal) => request<PurchaseHistory>(`/api/purchases/${id}/history`, { signal }),
  purchaseNotifications: (signal?: AbortSignal) =>
    request<{ items: PurchaseNotificationItem[]; unread: number }>("/api/purchases/notifications", { signal }),
  markPurchaseNotificationsRead: () => request<{ marked: number }>("/api/purchases/notifications/read", { method: "POST" }),
  assistantStatus: (signal?: AbortSignal) =>
    request<{ configured: boolean; provider: string | null; model: string | null }>("/api/assistant/status", { signal }),
  assistantChat: (messages: { role: "user" | "assistant"; content: string }[], productId?: number | null) =>
    request<{ reply: string; provider: string; model: string; grounded_on_product: boolean }>("/api/assistant/chat",
      { method: "POST", body: JSON.stringify({ messages, product_id: productId ?? null }) }),
  testEmail: (token: string, email: string) =>
    request<{ status: string; error: string | null }>("/api/admin/test-email", { method: "POST", admin: token, body: JSON.stringify({ email }) }),
  diagnostics: (token: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>("/api/admin/diagnostics", { admin: token, signal }),
};

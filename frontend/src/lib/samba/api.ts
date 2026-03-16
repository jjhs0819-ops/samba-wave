/**
 * SambaWave API client - 인증 없이 접근
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === 'production'
    ? 'https://samba-wave-production.up.railway.app'
    : 'http://localhost:28080')

const SAMBA_PREFIX = `${API_BASE}/api/v1/samba`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.detail || `HTTP ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : ({} as T);
}

// ── Products ──

export interface SambaProduct {
  id: string;
  name: string;
  name_en?: string;
  name_ja?: string;
  description?: string;
  category?: string;
  brand?: string;
  source_url?: string;
  source_site?: string;
  site_product_id?: string;
  source_price: number;
  cost: number;
  margin_rate: number;
  sale_price?: number;
  images?: string[];
  options?: unknown[];
  status: string;
  applied_policy_id?: string;
  market_prices?: Record<string, number>;
  registered_accounts?: string[];
  created_at: string;
  updated_at: string;
}

export const productApi = {
  list: (skip = 0, limit = 50, status?: string) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) params.set("status", status);
    return request<SambaProduct[]>(`${SAMBA_PREFIX}/products?${params}`);
  },
  get: (id: string) => request<SambaProduct>(`${SAMBA_PREFIX}/products/${id}`),
  search: (q: string) => request<SambaProduct[]>(`${SAMBA_PREFIX}/products/search?q=${encodeURIComponent(q)}`),
  create: (data: Partial<SambaProduct>) =>
    request<SambaProduct>(`${SAMBA_PREFIX}/products`, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaProduct>) =>
    request<SambaProduct>(`${SAMBA_PREFIX}/products/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/products/${id}`, { method: "DELETE" }),
};

// ── Orders ──

export interface SambaOrder {
  id: string;
  order_number: string;
  channel_id?: string;
  channel_name?: string;
  product_id?: string;
  product_name?: string;
  source_site?: string;
  customer_name?: string;
  customer_phone?: string;
  customer_address?: string;
  quantity: number;
  sale_price: number;
  cost: number;
  fee_rate: number;
  revenue: number;
  profit: number;
  profit_rate?: string;
  status: string;
  payment_status: string;
  shipping_status: string;
  shipping_company?: string;
  tracking_number?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
}

export const orderApi = {
  list: (skip = 0, limit = 50, status?: string) => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) params.set("status", status);
    return request<SambaOrder[]>(`${SAMBA_PREFIX}/orders?${params}`);
  },
  get: (id: string) => request<SambaOrder>(`${SAMBA_PREFIX}/orders/${id}`),
  search: (q: string) => request<SambaOrder[]>(`${SAMBA_PREFIX}/orders/search?q=${encodeURIComponent(q)}`),
  create: (data: Partial<SambaOrder>) =>
    request<SambaOrder>(`${SAMBA_PREFIX}/orders`, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaOrder>) =>
    request<SambaOrder>(`${SAMBA_PREFIX}/orders/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  updateStatus: (id: string, status: string) =>
    request<SambaOrder>(`${SAMBA_PREFIX}/orders/${id}/status`, { method: "PUT", body: JSON.stringify({ status }) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/orders/${id}`, { method: "DELETE" }),
};

// ── Channels ──

export interface SambaChannel {
  id: string;
  name: string;
  type: string;
  platform: string;
  fee_rate: number;
  products?: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export const channelApi = {
  list: (skip = 0, limit = 50) =>
    request<SambaChannel[]>(`${SAMBA_PREFIX}/channels?skip=${skip}&limit=${limit}`),
  get: (id: string) => request<SambaChannel>(`${SAMBA_PREFIX}/channels/${id}`),
  create: (data: Partial<SambaChannel>) =>
    request<SambaChannel>(`${SAMBA_PREFIX}/channels`, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaChannel>) =>
    request<SambaChannel>(`${SAMBA_PREFIX}/channels/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/channels/${id}`, { method: "DELETE" }),
};

// ── Policies ──

export interface SambaPolicy {
  id: string;
  name: string;
  site_name?: string;
  pricing?: Record<string, unknown>;
  market_policies?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PricePreview {
  cost: number;
  market_price: number;
  profit: number;
  profit_rate: number;
}

export const policyApi = {
  list: (skip = 0, limit = 50) =>
    request<SambaPolicy[]>(`${SAMBA_PREFIX}/policies?skip=${skip}&limit=${limit}`),
  get: (id: string) => request<SambaPolicy>(`${SAMBA_PREFIX}/policies/${id}`),
  create: (data: Partial<SambaPolicy>) =>
    request<SambaPolicy>(`${SAMBA_PREFIX}/policies`, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaPolicy>) =>
    request<SambaPolicy>(`${SAMBA_PREFIX}/policies/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/policies/${id}`, { method: "DELETE" }),
  calculatePrice: (id: string, cost: number, feeRate = 0) =>
    request<PricePreview>(`${SAMBA_PREFIX}/policies/${id}/calculate-price`, {
      method: "POST",
      body: JSON.stringify({ cost, fee_rate: feeRate }),
    }),
};

// ── Collector (수집 필터 + 수집 상품) ──

export interface SambaSearchFilter {
  id: string;
  source_site: string;
  name: string;
  keyword?: string;
  category_filter?: string;
  min_price?: number;
  max_price?: number;
  exclude_sold_out: boolean;
  is_active: boolean;
  last_collected_at?: string;
  created_at: string;
}

export interface SambaCollectedProduct {
  id: string;
  source_site: string;
  search_filter_id?: string;
  site_product_id?: string;
  name: string;
  brand?: string;
  original_price: number;
  sale_price: number;
  images?: string[];
  options?: unknown[];
  category?: string;
  status: string;
  applied_policy_id?: string;
  market_prices?: Record<string, number>;
  market_enabled?: Record<string, boolean>;
  registered_accounts?: string[];
  is_sold_out: boolean;
  created_at: string;
}

export const collectorApi = {
  // Filters
  listFilters: () => request<SambaSearchFilter[]>(`${SAMBA_PREFIX}/collector/filters`),
  createFilter: (data: Partial<SambaSearchFilter>) =>
    request<SambaSearchFilter>(`${SAMBA_PREFIX}/collector/filters`, { method: "POST", body: JSON.stringify(data) }),
  updateFilter: (id: string, data: Partial<SambaSearchFilter>) =>
    request<SambaSearchFilter>(`${SAMBA_PREFIX}/collector/filters/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteFilter: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/collector/filters/${id}`, { method: "DELETE" }),

  // Collected Products
  listProducts: (skip = 0, limit = 50, status?: string) => {
    const p = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) p.set("status", status);
    return request<SambaCollectedProduct[]>(`${SAMBA_PREFIX}/collector/products?${p}`);
  },
  searchProducts: (q: string) =>
    request<SambaCollectedProduct[]>(`${SAMBA_PREFIX}/collector/products/search?q=${encodeURIComponent(q)}`),
  getProduct: (id: string) => request<SambaCollectedProduct>(`${SAMBA_PREFIX}/collector/products/${id}`),
  createProduct: (data: Partial<SambaCollectedProduct>) =>
    request<SambaCollectedProduct>(`${SAMBA_PREFIX}/collector/products`, { method: "POST", body: JSON.stringify(data) }),
  bulkCreate: (items: Partial<SambaCollectedProduct>[]) =>
    request<{ created: number }>(`${SAMBA_PREFIX}/collector/products/bulk`, { method: "POST", body: JSON.stringify({ items }) }),
  updateProduct: (id: string, data: Partial<SambaCollectedProduct>) =>
    request<SambaCollectedProduct>(`${SAMBA_PREFIX}/collector/products/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProduct: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/collector/products/${id}`, { method: "DELETE" }),
};

// ── Market Accounts ──

export interface SambaMarketAccount {
  id: string;
  market_type: string;
  market_name: string;
  account_label: string;
  seller_id?: string;
  business_name?: string;
  is_active: boolean;
  additional_fields?: Record<string, unknown>;
  created_at: string;
}

export const accountApi = {
  list: () => request<SambaMarketAccount[]>(`${SAMBA_PREFIX}/accounts`),
  listActive: () => request<SambaMarketAccount[]>(`${SAMBA_PREFIX}/accounts/active`),
  getMarkets: () => request<unknown[]>(`${SAMBA_PREFIX}/accounts/markets`),
  get: (id: string) => request<SambaMarketAccount>(`${SAMBA_PREFIX}/accounts/${id}`),
  create: (data: Partial<SambaMarketAccount>) =>
    request<SambaMarketAccount>(`${SAMBA_PREFIX}/accounts`, { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<SambaMarketAccount>) =>
    request<SambaMarketAccount>(`${SAMBA_PREFIX}/accounts/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  toggle: (id: string) =>
    request<SambaMarketAccount>(`${SAMBA_PREFIX}/accounts/${id}/toggle`, { method: "PUT" }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/accounts/${id}`, { method: "DELETE" }),
};

// ── Shipments ──

export interface SambaShipment {
  id: string;
  product_id: string;
  target_account_ids?: string[];
  update_items?: string[];
  status: string;
  transmit_result?: Record<string, string>;
  completed_at?: string;
  created_at: string;
}

export const shipmentApi = {
  list: (skip = 0, limit = 50, status?: string) => {
    const p = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) p.set("status", status);
    return request<SambaShipment[]>(`${SAMBA_PREFIX}/shipments?${p}`);
  },
  listByProduct: (productId: string) =>
    request<SambaShipment[]>(`${SAMBA_PREFIX}/shipments/product/${productId}`),
  get: (id: string) => request<SambaShipment>(`${SAMBA_PREFIX}/shipments/${id}`),
  start: (productIds: string[], updateItems: string[], targetAccountIds: string[]) =>
    request<{ processed: number }>(`${SAMBA_PREFIX}/shipments/start`, {
      method: "POST",
      body: JSON.stringify({ product_ids: productIds, update_items: updateItems, target_account_ids: targetAccountIds }),
    }),
  retry: (id: string) =>
    request<SambaShipment>(`${SAMBA_PREFIX}/shipments/${id}/retry`, { method: "POST" }),
};

// ── Forbidden Words ──

export interface SambaForbiddenWord {
  id: string;
  word: string;
  type: string;
  scope: string;
  is_active: boolean;
  created_at: string;
}

export const forbiddenApi = {
  listWords: (type?: string) => {
    const p = type ? `?type=${type}` : "";
    return request<SambaForbiddenWord[]>(`${SAMBA_PREFIX}/forbidden/words${p}`);
  },
  createWord: (data: Partial<SambaForbiddenWord>) =>
    request<SambaForbiddenWord>(`${SAMBA_PREFIX}/forbidden/words`, { method: "POST", body: JSON.stringify(data) }),
  updateWord: (id: string, data: Partial<SambaForbiddenWord>) =>
    request<SambaForbiddenWord>(`${SAMBA_PREFIX}/forbidden/words/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  toggleWord: (id: string) =>
    request<SambaForbiddenWord>(`${SAMBA_PREFIX}/forbidden/words/${id}/toggle`, { method: "PUT" }),
  deleteWord: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/forbidden/words/${id}`, { method: "DELETE" }),
  validate: (name: string) =>
    request<{ is_valid: boolean; forbidden_found: string[]; deletion_found: string[]; clean_name: string }>(
      `${SAMBA_PREFIX}/forbidden/validate`, { method: "POST", body: JSON.stringify({ name }) }),
  clean: (name: string) =>
    request<{ clean_name: string }>(`${SAMBA_PREFIX}/forbidden/clean`, { method: "POST", body: JSON.stringify({ name }) }),

  // Settings
  getSetting: (key: string) => request<unknown>(`${SAMBA_PREFIX}/forbidden/settings/${key}`),
  saveSetting: (key: string, value: unknown) =>
    request<unknown>(`${SAMBA_PREFIX}/forbidden/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) }),
};

// ── Categories ──

export const categoryApi = {
  listMappings: () => request<unknown[]>(`${SAMBA_PREFIX}/categories/mappings`),
  createMapping: (data: { source_site: string; source_category: string; target_mappings?: unknown }) =>
    request<unknown>(`${SAMBA_PREFIX}/categories/mappings`, { method: "POST", body: JSON.stringify(data) }),
  updateMapping: (id: string, data: unknown) =>
    request<unknown>(`${SAMBA_PREFIX}/categories/mappings/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteMapping: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/categories/mappings/${id}`, { method: "DELETE" }),
  findMapping: (sourceSite: string, sourceCategory: string) =>
    request<unknown>(`${SAMBA_PREFIX}/categories/mappings/find?source_site=${encodeURIComponent(sourceSite)}&source_category=${encodeURIComponent(sourceCategory)}`),
  suggest: (sourceCategory: string, targetMarket: string) =>
    request<string[]>(`${SAMBA_PREFIX}/categories/suggest?source_category=${encodeURIComponent(sourceCategory)}&target_market=${encodeURIComponent(targetMarket)}`),
  getTree: (siteName: string) => request<unknown>(`${SAMBA_PREFIX}/categories/tree/${siteName}`),
  saveTree: (siteName: string, data: unknown) =>
    request<unknown>(`${SAMBA_PREFIX}/categories/tree/${siteName}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteTree: (siteName: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/categories/tree/${siteName}`, { method: "DELETE" }),
};

// ── Contacts ──

export interface SambaContactLog {
  id: string;
  order_id?: string;
  type: string;
  recipient?: string;
  message?: string;
  status: string;
  sent_at?: string;
  created_at: string;
}

export const contactApi = {
  list: (orderId?: string, status?: string) => {
    const p = new URLSearchParams();
    if (orderId) p.set("order_id", orderId);
    if (status) p.set("status", status);
    return request<SambaContactLog[]>(`${SAMBA_PREFIX}/contacts?${p}`);
  },
  create: (data: { order_id?: string; type: string; recipient?: string; message?: string }) =>
    request<SambaContactLog>(`${SAMBA_PREFIX}/contacts`, { method: "POST", body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`${SAMBA_PREFIX}/contacts/${id}`, { method: "DELETE" }),
  getStats: () => request<Record<string, number>>(`${SAMBA_PREFIX}/contacts/stats`),
  getTemplates: () => request<Record<string, unknown>>(`${SAMBA_PREFIX}/contacts/templates`),
};

// ── Returns ──

export interface SambaReturn {
  id: string;
  order_id: string;
  type: string;
  reason?: string;
  description?: string;
  quantity: number;
  requested_amount?: number;
  status: string;
  timeline?: { date: string; status: string; message: string }[];
  created_at: string;
}

export const returnApi = {
  list: (orderId?: string, status?: string, type?: string) => {
    const p = new URLSearchParams();
    if (orderId) p.set("order_id", orderId);
    if (status) p.set("status", status);
    if (type) p.set("type", type);
    return request<SambaReturn[]>(`${SAMBA_PREFIX}/returns?${p}`);
  },
  create: (data: Partial<SambaReturn>) =>
    request<SambaReturn>(`${SAMBA_PREFIX}/returns`, { method: "POST", body: JSON.stringify(data) }),
  get: (id: string) => request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}`),
  approve: (id: string) => request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}/approve`, { method: "PUT" }),
  reject: (id: string, reason: string) =>
    request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}/reject`, { method: "PUT", body: JSON.stringify({ reason }) }),
  complete: (id: string) => request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}/complete`, { method: "PUT" }),
  cancel: (id: string) => request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}/cancel`, { method: "PUT" }),
  addNote: (id: string, note: string) =>
    request<SambaReturn>(`${SAMBA_PREFIX}/returns/${id}/note`, { method: "POST", body: JSON.stringify({ note }) }),
  getStats: () => request<Record<string, number>>(`${SAMBA_PREFIX}/returns/stats`),
  getReasons: () => request<Record<string, { value: string; label: string }[]>>(`${SAMBA_PREFIX}/returns/reasons`),
};

// ── Analytics ──

export interface AnalyticsStats {
  total_sales: number;
  total_orders: number;
  total_profit: number;
  avg_order_value: number;
  profit_rate: number;
}

export const analyticsApi = {
  today: () => request<AnalyticsStats>(`${SAMBA_PREFIX}/analytics/today`),
  range: (startDate: string, endDate: string) =>
    request<AnalyticsStats>(`${SAMBA_PREFIX}/analytics/range?start_date=${startDate}&end_date=${endDate}`),
  byChannel: () => request<unknown[]>(`${SAMBA_PREFIX}/analytics/channels`),
  byProduct: () => request<unknown[]>(`${SAMBA_PREFIX}/analytics/products`),
  daily: (days = 30) => request<unknown[]>(`${SAMBA_PREFIX}/analytics/daily?days=${days}`),
  monthly: () => request<unknown[]>(`${SAMBA_PREFIX}/analytics/monthly`),
  kpi: () => request<Record<string, unknown>>(`${SAMBA_PREFIX}/analytics/kpi`),
  orderStatus: () => request<Record<string, number>>(`${SAMBA_PREFIX}/analytics/order-status`),
};

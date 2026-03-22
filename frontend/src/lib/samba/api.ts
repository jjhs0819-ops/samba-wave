/**
 * SambaWave API client - 인증 없이 접근
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ||
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
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`응답 JSON 파싱 실패: ${text.slice(0, 100)}`);
  }
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
  group_key?: string | null;
  group_product_no?: number | null;
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
  product_image?: string;
  source_site?: string;
  customer_name?: string;
  customer_phone?: string;
  customer_address?: string;
  quantity: number;
  sale_price: number;
  cost: number;
  shipping_fee: number;
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
  source?: string;
  shipment_id?: string;
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
  syncFromMarkets: (days = 7, accountId?: string) =>
    request<{ total_synced: number; results: { account: string; status: string; message?: string; fetched?: number; synced?: number }[] }>(
      `${SAMBA_PREFIX}/orders/sync-from-markets`, { method: "POST", body: JSON.stringify({ days, account_id: accountId || undefined }) }),
  approveCancel: (id: string) =>
    request<{ ok: boolean; message: string }>(`${SAMBA_PREFIX}/orders/${id}/approve-cancel`, { method: "POST" }),
  fetchProductImage: (url: string) =>
    request<{ image_url: string }>(`${SAMBA_PREFIX}/orders/fetch-product-image`, {
      method: "POST", body: JSON.stringify({ url }),
    }),
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
  extras?: {
    detail_template_id?: string;
    name_rule_id?: string;
    forbidden_text?: string;
    deletion_text?: string;
    forbidden_template_id?: string;
    deletion_template_id?: string;
  };
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
  aiChange: (command: string) =>
    request<{ ok: boolean; applied: number; changes: { policy_id: string; policy_name: string; field: string; market: string; before: number; after: number }[] }>(
      `${SAMBA_PREFIX}/policies/ai-change`,
      { method: "POST", body: JSON.stringify({ command }) }),
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
  requested_count?: number;
  applied_policy_id?: string;
  last_collected_at?: string;
  ss_brand_id?: number;
  ss_brand_name?: string;
  ss_manufacturer_id?: number;
  ss_manufacturer_name?: string;
  created_at: string;
}

export interface SambaCollectedProduct {
  id: string;
  source_site: string;
  search_filter_id?: string;
  site_product_id?: string;
  name: string;
  name_en?: string;
  name_ja?: string;
  brand?: string;
  original_price: number;
  sale_price: number;
  cost?: number;
  images?: string[];
  options?: unknown[];
  category?: string;
  category1?: string;
  category2?: string;
  category3?: string;
  category4?: string;
  detail_html?: string;
  detail_images?: string[];
  manufacturer?: string;
  origin?: string;
  material?: string;
  color?: string;
  status: string;
  applied_policy_id?: string;
  market_prices?: Record<string, number>;
  market_enabled?: Record<string, boolean>;
  registered_accounts?: string[];
  market_product_nos?: Record<string, string>;
  is_sold_out: boolean;
  sale_status?: string;
  kream_data?: Record<string, unknown>;
  style_code?: string;
  sex?: string;
  season?: string;
  care_instructions?: string;
  quality_guarantee?: string;
  price_before_change?: number;
  price_changed_at?: string;
  price_history?: Array<{
    date: string;
    sale_price: number;
    original_price: number;
    cost?: number;
    kream_fast_min?: number;
    kream_general_min?: number;
    options?: unknown[];
  }>;
  lock_delete?: boolean;
  lock_stock?: boolean;
  tags?: string[];
  monitor_priority?: string;
  last_refreshed_at?: string;
  refresh_error_count?: number;
  group_key?: string | null;
  group_product_no?: number | null;
  created_at: string;
  updated_at?: string;
}

export interface RefreshResult {
  total: number
  refreshed: number
  changed: number
  sold_out: number
  deleted: number
  retransmitted: number
  needs_extension: string[]
  errors: number
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
  getProductIdsWithOrders: () =>
    request<string[]>(`${SAMBA_PREFIX}/collector/products/with-orders`),
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
  resetRegistration: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/collector/products/${id}/reset-registration`, { method: "POST" }),

  // 재고/가격 갱신
  refresh: (productIds?: string[], autoRetransmit = true, searchFilterIds?: string[]) =>
    request<RefreshResult>(`${SAMBA_PREFIX}/collector/products/refresh`, {
      method: 'POST',
      body: JSON.stringify({ product_ids: productIds, search_filter_ids: searchFilterIds, auto_retransmit: autoRetransmit }),
    }),

  // Ken Burns 영상 생성 (R2/로컬 저장 후 URL 반환)
  generateVideo: (productId: string, maxImages = 3, durationPerImage = 1.0) =>
    request<{ success: boolean, video_url: string }>(`${SAMBA_PREFIX}/collector/products/generate-video`, {
      method: 'POST',
      body: JSON.stringify({ product_id: productId, max_images: maxImages, duration_per_image: durationPerImage }),
    }),

  // 모니터링 우선순위 변경
  updateMonitorPriority: (productIds: string[], priority: string) =>
    request<{ updated: number }>(`${SAMBA_PREFIX}/collector/products/monitor-priority`, {
      method: 'PUT',
      body: JSON.stringify({ product_ids: productIds, priority }),
    }),

  // Probe (소싱처/마켓 헬스체크)
  probeStatus: () =>
    request<Record<string, unknown>>(`${SAMBA_PREFIX}/collector/probe/status`),
  probeRun: () =>
    request<Record<string, unknown>>(`${SAMBA_PREFIX}/collector/probe/run`, { method: 'POST' }),
  autotuneStart: () =>
    request<{ ok: boolean; status: string }>(`${SAMBA_PREFIX}/collector/autotune/start`, { method: 'POST' }),
  autotuneStop: () =>
    request<{ ok: boolean; status: string }>(`${SAMBA_PREFIX}/collector/autotune/stop`, { method: 'POST' }),
  autotuneStatus: () =>
    request<{ running: boolean; last_tick: string | null; cycle_count: number }>(`${SAMBA_PREFIX}/collector/autotune/status`),
}

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

// ── 스스그룹 타입 ──

export interface GroupPreviewProduct {
  id: string
  name: string
  color: string | null
  sale_price: number | null
  thumbnail: string | null
  existing_product_no: string | null
}

export interface GroupPreviewGroup {
  group_key: string
  group_name: string
  products: GroupPreviewProduct[]
}

export interface GroupPreviewResponse {
  groups: GroupPreviewGroup[]
  singles: GroupPreviewProduct[]
  delete_count: number
  group_count: number
  single_count: number
}

export interface GroupSendResponse {
  group_results: { group_key: string; status: string; error?: string; group_product_no?: number }[]
  single_results: Record<string, unknown>
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
  start: (productIds: string[], updateItems: string[], targetAccountIds: string[], skipUnchanged = false) =>
    request<{
      processed: number
      skipped: number
      results: {
        product_id: string
        status: string
        transmit_result?: Record<string, string>
        transmit_error?: Record<string, string>
        error?: string
      }[]
    }>(`${SAMBA_PREFIX}/shipments/start`, {
      method: "POST",
      body: JSON.stringify({ product_ids: productIds, update_items: updateItems, target_account_ids: targetAccountIds, skip_unchanged: skipUnchanged }),
    }),
  retry: (id: string) =>
    request<SambaShipment>(`${SAMBA_PREFIX}/shipments/${id}/retry`, { method: "POST" }),
  marketDelete: (productIds: string[], targetAccountIds: string[]) =>
    request<{ processed: number; results: { product_id: string; delete_results: Record<string, string>; success_count: number }[] }>(
      `${SAMBA_PREFIX}/shipments/market-delete`, {
        method: "POST",
        body: JSON.stringify({ product_ids: productIds, target_account_ids: targetAccountIds }),
      }
    ),

  // 스스그룹 미리보기
  groupPreview: (searchFilterIds: string[], accountId: string) =>
    request<GroupPreviewResponse>(`${SAMBA_PREFIX}/shipments/group-preview`, {
      method: 'POST',
      body: JSON.stringify({ search_filter_ids: searchFilterIds, account_id: accountId }),
    }),

  // 스스그룹 전송
  groupSend: (groups: { group_key: string; product_ids: string[] }[], singles: string[], accountId: string) =>
    request<GroupSendResponse>(`${SAMBA_PREFIX}/shipments/group-send`, {
      method: 'POST',
      body: JSON.stringify({ groups, singles, account_id: accountId }),
    }),
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
  bulkSaveWords: (type: string, words: string[]) =>
    request<{ ok: boolean; created: number }>(`${SAMBA_PREFIX}/forbidden/words/bulk`, { method: "POST", body: JSON.stringify({ type, words }) }),
  validate: (name: string) =>
    request<{ is_valid: boolean; forbidden_found: string[]; deletion_found: string[]; clean_name: string }>(
      `${SAMBA_PREFIX}/forbidden/validate`, { method: "POST", body: JSON.stringify({ name }) }),
  clean: (name: string) =>
    request<{ clean_name: string }>(`${SAMBA_PREFIX}/forbidden/clean`, { method: "POST", body: JSON.stringify({ name }) }),

  // Settings
  getSetting: (key: string) => request<unknown>(`${SAMBA_PREFIX}/forbidden/settings/${key}`),
  saveSetting: (key: string, value: unknown) =>
    request<unknown>(`${SAMBA_PREFIX}/forbidden/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) }),

  // 태그 금지어 통합 조회
  getTagBannedWords: () =>
    request<{ rejected: string[]; brands: string[]; source_sites: string[] }>(`${SAMBA_PREFIX}/forbidden/tag-banned-words`),
};

// ── Proxy (외부 API 프록시) ──

export const proxyApi = {
  aligoRemain: () =>
    request<{ success: boolean; message: string; SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number }>(
      `${SAMBA_PREFIX}/proxy/aligo/remain`, { method: 'POST' }),
  smartstoreAuthTest: () =>
    request<{ success: boolean; message: string; token_preview?: string }>(
      `${SAMBA_PREFIX}/proxy/smartstore/auth-test`, { method: 'POST' }),
  elevenstAuthTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/11st/auth-test`, { method: 'POST' }),
  elevenstSellerInfo: () =>
    request<{ success: boolean; message: string; data?: Record<string, string> }>(
      `${SAMBA_PREFIX}/proxy/11st/seller-info`, { method: 'POST' }),
  coupangAuthTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/coupang/auth-test`, { method: 'POST' }),
  lotteonAuthTest: () =>
    request<{ success: boolean; message: string; data?: Record<string, string> }>(
      `${SAMBA_PREFIX}/proxy/lotteon/auth-test`, { method: 'POST' }),
  ssgAuthTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/ssg/auth-test`, { method: 'POST' }),
  gsshopAuthTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/gsshop/auth-test`, { method: 'POST' }),
  marketAuthTest: (marketKey: string) =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/market/auth-test/${marketKey}`, { method: 'POST' }),
  claudeTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/claude/test`, { method: 'POST' }),
  fireworksTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/fireworks/test`, { method: 'POST' }),
  geminiTest: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/gemini/test`, { method: 'POST' }),
  r2Test: () =>
    request<{ success: boolean; message: string }>(
      `${SAMBA_PREFIX}/proxy/r2/test`, { method: 'POST' }),
  listPresets: () =>
    request<{ success: boolean; presets: { key: string; label: string; desc: string; image: string | null }[] }>(
      `${SAMBA_PREFIX}/proxy/preset-images/list`),
  regeneratePreset: (presetKey: string, desc?: string, label?: string, saveOnly?: boolean) =>
    request<{ success: boolean; message: string; image?: string }>(
      `${SAMBA_PREFIX}/proxy/preset-images/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ preset_key: presetKey, desc, label, save_only: saveOnly }),
      }),
  uploadPresetImage: async (presetKey: string, file: File) => {
    const formData = new FormData()
    formData.append('preset_key', presetKey)
    formData.append('file', file)
    const res = await fetch(`${SAMBA_PREFIX}/proxy/preset-images/upload`, { method: 'POST', body: formData })
    return res.json() as Promise<{ success: boolean; message: string; image?: string }>
  },
  transformImages: (productIds: string[], scope: { thumbnail: boolean; additional: boolean; detail: boolean }, mode: string, modelPreset?: string) =>
    request<{ success: boolean; message: string; total_transformed: number; total_failed: number }>(
      `${SAMBA_PREFIX}/proxy/fireworks/transform`, {
        method: 'POST',
        body: JSON.stringify({ product_ids: productIds, scope, mode, model_preset: modelPreset }),
      }),
  transformByGroups: (groupIds: string[], scope: { thumbnail: boolean; additional: boolean; detail: boolean }, mode: string, modelPreset?: string) =>
    request<{ success: boolean; message: string; total_transformed: number; total_failed: number }>(
      `${SAMBA_PREFIX}/proxy/fireworks/transform`, {
        method: 'POST',
        body: JSON.stringify({ group_ids: groupIds, scope, mode, model_preset: modelPreset }),
      }),
  generateAiTags: (productIds: string[]) =>
    request<{ success: boolean; message: string; total_tagged: number; api_calls: number; input_tokens: number; output_tokens: number; cost_krw: number }>(
      `${SAMBA_PREFIX}/proxy/ai-tags/generate`, {
        method: 'POST',
        body: JSON.stringify({ product_ids: productIds }),
      }),
  generateAiTagsByGroups: (groupIds: string[]) =>
    request<{ success: boolean; message: string; total_tagged: number; api_calls: number; input_tokens: number; output_tokens: number; cost_krw: number }>(
      `${SAMBA_PREFIX}/proxy/ai-tags/generate`, {
        method: 'POST',
        body: JSON.stringify({ group_ids: groupIds }),
      }),
  // 이미지 필터링 (모델컷/연출컷/배너 자동 제거)
  filterProductImages: (productIds: string[], filterId?: string, scope?: string) =>
    request<{ success: boolean; results: Record<string, { action: string; removed?: number; kept?: number; count?: number }>; total: number; errors: Record<string, string> }>(
      `${SAMBA_PREFIX}/proxy/image-filter/filter`, {
        method: 'POST',
        body: JSON.stringify({ product_ids: productIds, filter_id: filterId || '', scope: scope || 'images' }),
      }),
  // 소싱처 검색/상세
  sourcingSearch: (site: string, keyword: string, page = 1) =>
    request<{ products: SambaCollectedProduct[]; total: number }>(
      `${SAMBA_PREFIX}/proxy/sourcing/${site}/search?keyword=${encodeURIComponent(keyword)}&page=${page}`),
  sourcingDetail: (site: string, productId: string) =>
    request<SambaCollectedProduct>(
      `${SAMBA_PREFIX}/proxy/sourcing/${site}/detail/${productId}`),
}

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
  aiSuggest: (data: { source_site: string; source_category: string; sample_products: string[]; target_markets?: string[] }) =>
    request<Record<string, string>>(`${SAMBA_PREFIX}/categories/ai-suggest`, { method: "POST", body: JSON.stringify(data) }),
  aiSuggestBulk: () =>
    request<{ mapped: number; updated: number; skipped: number; errors: string[] }>(
      `${SAMBA_PREFIX}/categories/ai-suggest-bulk`, { method: 'POST' }),
  seedMarketCategories: () =>
    request<{ ok: boolean; markets: Record<string, number> }>(
      `${SAMBA_PREFIX}/categories/markets/seed`, { method: 'POST' }),
  checkMarketRegistered: (market: string, mappingIds: string[]) =>
    request<{ registered_count: number }>(
      `${SAMBA_PREFIX}/categories/mappings/check-registered`,
      { method: 'POST', body: JSON.stringify({ market, mapping_ids: mappingIds }) }),
  checkAllMarketsRegistered: (mappingIds: string[]) =>
    request<{ blocked: Record<string, number> }>(
      `${SAMBA_PREFIX}/categories/mappings/check-registered-all`,
      { method: 'POST', body: JSON.stringify({ mapping_ids: mappingIds }) }),
  bulkDeleteMappings: (mappingIds: string[]) =>
    request<{ ok: boolean; deleted: number }>(
      `${SAMBA_PREFIX}/categories/mappings/bulk-delete`,
      { method: 'POST', body: JSON.stringify({ mapping_ids: mappingIds }) }),
  clearMarketColumn: (market: string, mappingIds: string[]) =>
    request<{ ok: boolean; cleared: number }>(
      `${SAMBA_PREFIX}/categories/mappings/clear-market`,
      { method: 'POST', body: JSON.stringify({ market, mapping_ids: mappingIds }) }),
  aiSeedMarket: (marketType: string) =>
    request<{ ok: boolean; market: string; count: number }>(
      `${SAMBA_PREFIX}/categories/markets/ai-seed/${marketType}`, { method: 'POST' }),
  aiSeedAll: () =>
    request<{ ok: boolean; results: Record<string, { ok: boolean; count?: number; error?: string }> }>(
      `${SAMBA_PREFIX}/categories/markets/ai-seed-all`, { method: 'POST' }),
  syncMarket: (marketType: string) =>
    request<{ ok: boolean; market: string; count: number }>(
      `${SAMBA_PREFIX}/categories/markets/sync/${marketType}`, { method: 'POST' }),
  syncAll: () =>
    request<{ ok: boolean; results: Record<string, unknown> }>(
      `${SAMBA_PREFIX}/categories/markets/sync-all`, { method: 'POST' }),
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

// ── Detail Templates ──

export interface SambaDetailTemplate {
  id: string;
  name: string;
  main_image_index: number;
  top_html?: string;
  bottom_html?: string;
  top_image_s3_key?: string;
  bottom_image_s3_key?: string;
  img_checks?: Record<string, boolean>;
  img_order?: string[];
  created_at: string;
  updated_at: string;
}

export const detailTemplateApi = {
  list: (skip = 0, limit = 50) =>
    request<SambaDetailTemplate[]>(`${SAMBA_PREFIX}/policies/detail-templates?skip=${skip}&limit=${limit}`),
  get: (id: string) =>
    request<SambaDetailTemplate>(`${SAMBA_PREFIX}/policies/detail-templates/${id}`),
  create: (data: Partial<SambaDetailTemplate>) =>
    request<SambaDetailTemplate>(`${SAMBA_PREFIX}/policies/detail-templates`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<SambaDetailTemplate>) =>
    request<SambaDetailTemplate>(`${SAMBA_PREFIX}/policies/detail-templates/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/policies/detail-templates/${id}`, { method: 'DELETE' }),
  getPresignedUrl: (id: string, position: 'top' | 'bottom', contentType: string) =>
    request<{ upload_url: string; s3_key: string }>(
      `${SAMBA_PREFIX}/policies/detail-templates/${id}/presigned-url`,
      { method: 'POST', body: JSON.stringify({ position, content_type: contentType }) },
    ),
  confirmUpload: (id: string, position: 'top' | 'bottom', s3Key: string) =>
    request<SambaDetailTemplate>(
      `${SAMBA_PREFIX}/policies/detail-templates/${id}/confirm-upload`,
      { method: 'POST', body: JSON.stringify({ position, s3_key: s3Key }) },
    ),
};

// ── Name Rules ──

export interface SambaNameRule {
  id: string;
  name: string;
  prefix?: string;
  suffix?: string;
  replacements?: Array<{ from: string; to: string; caseInsensitive?: boolean }>;
  replace_mode?: string;
  option_rules?: Array<{ from: string; to: string }>;
  name_composition?: string[];
  brand_display?: string;
  dedup_enabled?: boolean;
  created_at: string;
  updated_at: string;
}

export const nameRuleApi = {
  list: (skip = 0, limit = 50) =>
    request<SambaNameRule[]>(`${SAMBA_PREFIX}/policies/name-rules?skip=${skip}&limit=${limit}`),
  get: (id: string) =>
    request<SambaNameRule>(`${SAMBA_PREFIX}/policies/name-rules/${id}`),
  create: (data: Partial<SambaNameRule>) =>
    request<SambaNameRule>(`${SAMBA_PREFIX}/policies/name-rules`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<SambaNameRule>) =>
    request<SambaNameRule>(`${SAMBA_PREFIX}/policies/name-rules/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/policies/name-rules/${id}`, { method: 'DELETE' }),
};

// ── Monitor (워룸) ──

export interface MonitorEvent {
  id: string
  event_type: string
  severity: string
  source_site?: string
  market_type?: string
  product_id?: string
  product_name?: string
  summary: string
  detail?: Record<string, unknown>
  created_at: string
}

export interface DashboardStats {
  product_stats: {
    total: number
    by_source: Record<string, number>
    by_priority: Record<string, number>
    by_sale_status: Record<string, number>
  }
  refresh_stats: {
    last_refreshed_at: string | null
    refreshed_1h: number
    refreshed_24h: number
    error_products: number
  }
  price_change_stats: {
    changes_24h: number
    avg_change_pct: number
    top_changes: Array<{
      product_id: string
      name: string
      old: number
      new: number
      pct: number
      at: string
    }>
  }
  site_health: Record<string, {
    interval: number
    errors: number
    probe_ok: boolean | null
    latency_ms: number | null
    checked_at: string | null
  }>
  market_health: Record<string, {
    probe_ok: boolean | null
    latency_ms: number
    error?: string
    checked_at: string | null
  }>
  event_summary: {
    counts_24h: Record<string, number>
    recent_critical: MonitorEvent[]
    recent_warnings: MonitorEvent[]
  }
  hourly_changes: number[]
}

export interface RefreshLogEntry {
  ts: string
  site: string
  product_id: string
  name: string
  msg: string
  level: string
}

export interface RefreshLogsResponse {
  logs: RefreshLogEntry[]
  current_idx: number
  intervals: {
    intervals: Record<string, number>
    errors: Record<string, number>
    safe_intervals: Record<string, number>
  }
}

export const monitorApi = {
  dashboard: () =>
    request<DashboardStats>(`${SAMBA_PREFIX}/monitor/dashboard`),
  events: (params?: { type?: string; severity?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.type) qs.set('event_type', params.type)
    if (params?.severity) qs.set('severity', params.severity)
    if (params?.limit) qs.set('limit', String(params.limit))
    return request<MonitorEvent[]>(`${SAMBA_PREFIX}/monitor/events?${qs}`)
  },
  recentEvents: (limit = 50) =>
    request<MonitorEvent[]>(`${SAMBA_PREFIX}/monitor/events/recent?limit=${limit}`),
  priceChanges: () =>
    request<MonitorEvent[]>(`${SAMBA_PREFIX}/monitor/price-changes`),
  siteHealth: () =>
    request<{ sources: DashboardStats['site_health']; markets: DashboardStats['market_health'] }>(
      `${SAMBA_PREFIX}/monitor/site-health`,
    ),
  refreshLogs: (sinceIdx = 0) =>
    request<RefreshLogsResponse>(`${SAMBA_PREFIX}/monitor/refresh-logs?since_idx=${sinceIdx}`),
  storeScores: () =>
    request<Record<string, { account_id: string; account_label: string; market_type: string; grade: string; grade_code: string; good_service: Record<string, number> | null; penalty: number | null; penalty_rate: number | null; updated_at: string }>>(`${SAMBA_PREFIX}/monitor/store-scores`),
  refreshStoreScores: () =>
    request<{ success: boolean; accounts: number }>(`${SAMBA_PREFIX}/monitor/store-scores/refresh`, { method: 'POST' }),
}

// ── S3 이미지 헬퍼 ──

const S3_BUCKET = process.env.NEXT_PUBLIC_S3_BUCKET || ''
const S3_REGION = process.env.NEXT_PUBLIC_S3_REGION || 'ap-northeast-2'

/** S3 key → 공개 URL 변환 */
export function getS3Url(key: string): string {
  return `https://${S3_BUCKET}.s3.${S3_REGION}.amazonaws.com/${key}`
}

/** Presigned PUT URL로 파일 직접 업로드 */
export async function uploadToS3(presignedUrl: string, file: File): Promise<void> {
  const res = await fetch(presignedUrl, {
    method: 'PUT',
    headers: { 'Content-Type': file.type },
    body: file,
  })
  if (!res.ok) throw new Error(`S3 업로드 실패: ${res.status}`)
}

// ── 사용자(로그인 계정) 관리 ──

export interface SambaUser {
  id: string
  email?: string
  name?: string
  is_admin: boolean
  status: string
  created_at: string
  updated_at: string
}

export const userApi = {
  list: (skip = 0, limit = 50) =>
    request<SambaUser[]>(`${SAMBA_PREFIX}/users?skip=${skip}&limit=${limit}`),
  create: (data: { email: string; password: string; name: string; is_admin?: boolean }) =>
    request<SambaUser>(`${SAMBA_PREFIX}/users`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: { name?: string; email?: string; password?: string; is_admin?: boolean; status?: string }) =>
    request<SambaUser>(`${SAMBA_PREFIX}/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`${SAMBA_PREFIX}/users/${id}`, { method: 'DELETE' }),
  login: (email: string, password: string) =>
    request<SambaUser>(
      `${SAMBA_PREFIX}/users/login`, { method: 'POST', body: JSON.stringify({ email, password }) }
    ),
}

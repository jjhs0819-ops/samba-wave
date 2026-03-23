"use client";

import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  collectorApi,
  policyApi,
  forbiddenApi,
  accountApi,
  shipmentApi,
  proxyApi,
  nameRuleApi,
  categoryApi,
  type SambaCollectedProduct,
  type SambaPolicy,
  type SambaSearchFilter,
  type SambaMarketAccount,
  type SambaNameRule,
} from "@/lib/samba/api";
import { showAlert, showConfirm } from '@/components/samba/Modal'

// 마켓별 상품 검색 URL (구매페이지 바로가기용)
const MARKETS = [
  { id: "coupang", name: "쿠팡", url: "https://wing.coupang.com", searchUrl: "https://www.coupang.com/np/search?q=" },
  { id: "ssg", name: "신세계몰", url: "https://sellerpick.ssg.com", searchUrl: "https://www.ssg.com/search.ssg?query=" },
  { id: "smartstore", name: "스마트스토어", url: "https://sell.smartstore.naver.com", searchUrl: "https://search.shopping.naver.com/search/all?query=" },
  { id: "11st", name: "11번가", url: "https://spc.11st.co.kr", searchUrl: "https://search.11st.co.kr/Search.tmall?kwd=" },
  { id: "gmarket", name: "지마켓", url: "https://www.esmplus.com", searchUrl: "https://browse.gmarket.co.kr/search?keyword=" },
  { id: "auction", name: "옥션", url: "https://www.esmplus.com", searchUrl: "https://browse.auction.co.kr/search?keyword=" },
  { id: "gsshop", name: "GS샵", url: "https://partner.gsshop.com", searchUrl: "https://www.gsshop.com/shop/search/totalSearch.gs?tq=" },
  { id: "lotteon", name: "롯데ON", url: "https://partner.lotteon.com", searchUrl: "https://www.lotteon.com/search/search/search.ecn?render=search&platform=pc&q=" },
  { id: "lottehome", name: "롯데홈쇼핑", url: "https://partner.lottehome.com", searchUrl: "https://www.lotteimall.com/search/searchMain.lotte?searchKeyword=" },
  { id: "homeand", name: "홈앤쇼핑", url: "https://partner.homeandshopping.com", searchUrl: "https://www.hnsmall.com/search?keyword=" },
  { id: "hmall", name: "HMALL", url: "https://partner.hmall.com", searchUrl: "https://www.hmall.com/search?searchTerm=" },
  { id: "kream", name: "KREAM", url: "https://kream.co.kr", searchUrl: "https://kream.co.kr/search?keyword=" },
  { id: "ebay", name: "eBay", url: "https://www.ebay.com/sh/ovw", searchUrl: "https://www.ebay.com/sch/i.html?_nkw=" },
  { id: "lazada", name: "Lazada", url: "https://sellercenter.lazada.com", searchUrl: "https://www.lazada.com/catalog/?q=" },
  { id: "qoo10", name: "Qoo10", url: "https://qsm.qoo10.com", searchUrl: "https://www.qoo10.com/s?keyword=" },
  { id: "shopee", name: "Shopee", url: "https://seller.shopee.com", searchUrl: "https://shopee.com/search?keyword=" },
  { id: "shopify", name: "Shopify", url: "https://admin.shopify.com", searchUrl: "" },
  { id: "zoom", name: "Zum(줌)", url: "https://zum.com", searchUrl: "https://search.zum.com/search.zum?method=uni&query=" },
];

function fmt(n: number): string {
  return n.toLocaleString();
}

// 마켓별 상품 구매페이지 URL 생성 (상품번호가 있을 때만)
function buildMarketProductUrl(marketType: string, sellerId: string, productNo: string, storeSlug?: string): string {
  if (!productNo) return ''
  switch (marketType) {
    case 'smartstore':
      // 스토어 슬러그 우선 사용 (seller_id는 이메일일 수 있음)
      return `https://smartstore.naver.com/${storeSlug || sellerId}/products/${productNo}`
    case 'coupang':
      return `https://www.coupang.com/vp/products/${productNo}`
    case '11st':
      return `https://www.11st.co.kr/products/${productNo}`
    case 'gmarket':
      return `https://item.gmarket.co.kr/Item?goodscode=${productNo}`
    case 'auction':
      return `https://itempage3.auction.co.kr/DetailView.aspx?ItemNo=${productNo}`
    case 'ssg':
      return `https://www.ssg.com/item/itemView.ssg?itemId=${productNo}`
    case 'lotteon':
      return `https://www.lotteon.com/product/productDetail.lotte?spdNo=${productNo}`
    case 'gsshop':
      return `https://www.gsshop.com/prd/prd.gs?prdid=${productNo}`
    case 'lottehome':
      return `https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=${productNo}`
    case 'kream':
      return `https://kream.co.kr/products/${productNo}`
    case 'ebay':
      return `https://www.ebay.com/itm/${productNo}`
    default:
      return ''
  }
}

export default function ProductsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // URL searchParams에서 필터 읽기
  const filterByGroupId = searchParams.get("search_filter_id") || "";
  const filterGroupName = searchParams.get("group_name") || "";
  const highlightProductId = searchParams.get("highlight") || "";

  const [allProducts, setAllProducts] = useState<SambaCollectedProduct[]>([]);
  const [products, setProducts] = useState<SambaCollectedProduct[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([]);
  const [filterNameMap, setFilterNameMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  // Filters
  const [searchType, setSearchType] = useState("name");
  const [searchQ, setSearchQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [aiFilter, setAiFilter] = useState("");
  const [sortBy, setSortBy] = useState("collect-desc");
  const [pageSize, setPageSize] = useState(20);
  const [currentPage, setCurrentPage] = useState(1);
  const [viewMode, setViewMode] = useState<"card" | "compact" | "image">("card");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [orderProductIds, setOrderProductIds] = useState<Set<string>>(new Set());

  // Selection
  const [selectAll, setSelectAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // 상품별 로그 (업데이트 버튼 클릭 시 해당 상품 위에 표시)
  const [activeLog, setActiveLog] = useState<{ productId: string; message: string } | null>(null);
  // 작업 로그 (영상생성/이미지생성/태그생성 등)
  const [taskLogs, setTaskLogs] = useState<string[]>([]);
  const addTaskLog = (msg: string) => {
    const ts = new Date().toLocaleTimeString()
    setTaskLogs(prev => [...prev, `[${ts}] ${msg}`])
  }
  // AI 비용 추적
  const [lastAiUsage, setLastAiUsage] = useState<{ calls: number; tokens: number; cost: number; date: string } | null>(null);

  // AI 이미지 변환
  const [aiImgMode, setAiImgMode] = useState('background')
  const [aiModelPreset, setAiModelPreset] = useState('female_v1')
  const [aiImgTransforming, setAiImgTransforming] = useState(false)
  const [imgFiltering, setImgFiltering] = useState(false)
  const [imgFilterScope, setImgFilterScope] = useState<'images' | 'detail' | 'all'>('images')

  // AI 작업 진행 모달
  const [aiJobModal, setAiJobModal] = useState(false)
  const [aiJobTitle, setAiJobTitle] = useState('')
  const [aiJobLogs, setAiJobLogs] = useState<string[]>([])
  const [aiJobDone, setAiJobDone] = useState(false)
  const aiJobLogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (aiJobLogRef.current) aiJobLogRef.current.scrollTop = aiJobLogRef.current.scrollHeight
  }, [aiJobLogs])

  // 삭제 확인 모달
  const [deleteConfirm, setDeleteConfirm] = useState<{ ids: string[]; label: string } | null>(null);

  // 태그 일괄 입력
  const [showBulkTag, setShowBulkTag] = useState(false)
  const [bulkTagInput, setBulkTagInput] = useState('')

  // 카테고리 매핑 (source_site::source_category → { market: category })
  const [catMappingMap, setCatMappingMap] = useState<Map<string, Record<string, string>>>(new Map())

  // AI 태그 미리보기 모달
  const [showTagPreview, setShowTagPreview] = useState(false)
  const [tagPreviews, setTagPreviews] = useState<{ group_id: string; group_name: string; product_count: number; rep_name: string; tags: string[]; seo_keywords: string[] }[]>([])
  const [tagPreviewCost, setTagPreviewCost] = useState<{ api_calls: number; input_tokens: number; output_tokens: number; cost_krw: number } | null>(null)
  const [tagPreviewLoading, setTagPreviewLoading] = useState(false)
  const [removedTags, setRemovedTags] = useState<string[]>([])

  // 삭제어 목록 (등록 상품명 취소선 표시용)
  const [deletionWords, setDeletionWords] = useState<string[]>([]);
  // 상품명 규칙 목록 (상품명 조합 적용용)
  const [nameRules, setNameRules] = useState<SambaNameRule[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, pol, filters, words, accs, orderPids, rules] = await Promise.all([
        collectorApi.listProducts(0, 500).catch((e) => { console.error("listProducts error:", e); return []; }),
        policyApi.list().catch((e) => { console.error("listPolicies error:", e); return []; }),
        collectorApi.listFilters().catch(() => [] as SambaSearchFilter[]),
        forbiddenApi.listWords('deletion').catch(() => []),
        accountApi.listActive().catch(() => [] as SambaMarketAccount[]),
        collectorApi.getProductIdsWithOrders().catch(() => [] as string[]),
        nameRuleApi.list().catch(() => [] as SambaNameRule[]),
      ]);
      console.log("loaded products:", p.length, "policies:", pol.length);
      setAllProducts(p);
      setPolicies(pol);
      setAccounts(accs);
      setDeletionWords(words.filter(w => w.is_active).map(w => w.word));
      setNameRules(rules);
      setOrderProductIds(new Set(orderPids));
      const nameMap: Record<string, string> = {};
      filters.forEach((f: SambaSearchFilter) => { nameMap[f.id] = f.name; });
      setFilterNameMap(nameMap);
      // 카테고리 매핑 로드
      try {
        const mappings = await categoryApi.listMappings() as { source_site: string; source_category: string; target_mappings: Record<string, string> }[]
        if (Array.isArray(mappings)) {
          const map = new Map<string, Record<string, string>>()
          mappings.forEach(m => {
            map.set(`${m.source_site}::${m.source_category}`, m.target_mappings || {})
          })
          setCatMappingMap(map)
        }
      } catch { /* 매핑 로드 실패해도 무시 */ }
    } catch (e) {
      console.error("load error:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Apply filters / sort / pagination whenever dependencies change
  useEffect(() => {
    let filtered = [...allProducts];

    // URL에서 넘어온 상품 하이라이트 (카테고리 매핑에서 클릭)
    if (highlightProductId) {
      filtered = filtered.filter((p) => p.id === highlightProductId);
    }

    // URL에서 넘어온 그룹 필터
    if (filterByGroupId) {
      filtered = filtered.filter((p) => p.search_filter_id === filterByGroupId);
    }

    // Search
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      if (searchType === "name") {
        filtered = filtered.filter((p) => p.name.toLowerCase().includes(q));
      } else if (searchType === "filter") {
        const matchFilterIds = new Set(
          Object.entries(filterNameMap)
            .filter(([, name]) => name.toLowerCase().includes(q))
            .map(([id]) => id)
        );
        filtered = filtered.filter((p) => p.search_filter_id && matchFilterIds.has(p.search_filter_id));
      } else if (searchType === "no") {
        filtered = filtered.filter((p) => (p.site_product_id || "").toLowerCase().includes(q));
      } else if (searchType === "policy") {
        const matchPols = policies.filter((pol) => pol.name.toLowerCase().includes(q));
        const polIds = new Set(matchPols.map((pol) => pol.id));
        filtered = filtered.filter((p) => p.applied_policy_id && polIds.has(p.applied_policy_id));
      }
    }

    // Site filter
    if (siteFilter) filtered = filtered.filter((p) => p.source_site === siteFilter);

    // Status filter
    if (statusFilter === 'has_orders') {
      filtered = filtered.filter((p) => orderProductIds.has(p.id))
    } else if (statusFilter === 'free_ship') {
      filtered = filtered.filter((p) => p.free_shipping === true)
    } else if (statusFilter === 'same_day') {
      filtered = filtered.filter((p) => p.same_day_delivery === true)
    } else if (statusFilter === 'free_same') {
      filtered = filtered.filter((p) => p.free_shipping === true && p.same_day_delivery === true)
    } else if (statusFilter) {
      filtered = filtered.filter((p) => p.status === statusFilter)
    }

    // AI filter
    if (aiFilter === 'sold_out') filtered = filtered.filter(p => p.is_sold_out || p.sale_status === 'sold_out')
    if (aiFilter === 'ai_tag_yes') filtered = filtered.filter(p => (p.tags || []).includes('__ai_tagged__'))
    if (aiFilter === 'ai_tag_no') filtered = filtered.filter(p => !(p.tags || []).includes('__ai_tagged__'))
    if (aiFilter === 'ai_img_yes') filtered = filtered.filter(p => (p.images || []).some(u => u.includes('/transformed/') || u.includes('/static/images/ai_')))
    if (aiFilter === 'ai_img_no') filtered = filtered.filter(p => !(p.images || []).some(u => u.includes('/transformed/') || u.includes('/static/images/ai_')))
    if (aiFilter === 'filter_yes') filtered = filtered.filter(p => (p.tags || []).includes('__img_filtered__'))
    if (aiFilter === 'filter_no') filtered = filtered.filter(p => !(p.tags || []).includes('__img_filtered__'))
    if (aiFilter === 'img_edit_yes') filtered = filtered.filter(p => {
      const t = p.tags || []
      return t.includes('__ai_image__') || t.includes('__img_filtered__') || t.includes('__img_edited__')
    })
    if (aiFilter === 'img_edit_no') filtered = filtered.filter(p => {
      const t = p.tags || []
      return !t.includes('__ai_image__') && !t.includes('__img_filtered__') && !t.includes('__img_edited__')
    })
    if (aiFilter === 'video_yes') filtered = filtered.filter(p => !!p.video_url)
    if (aiFilter === 'video_no') filtered = filtered.filter(p => !p.video_url)
    if (aiFilter === 'has_orders') filtered = filtered.filter(p => orderProductIds.has(p.id))

    // Sort
    const isCollect = sortBy.startsWith("collect");
    const isDesc = sortBy.endsWith("desc");
    filtered.sort((a, b) => {
      const aD = isCollect ? (a.created_at || "") : (a.updated_at || a.created_at || "");
      const bD = isCollect ? (b.created_at || "") : (b.updated_at || b.created_at || "");
      return isDesc ? bD.localeCompare(aD) : aD.localeCompare(bD);
    });

    // Pagination
    if (pageSize > 0) {
      const start = (currentPage - 1) * pageSize
      filtered = filtered.slice(start, start + pageSize)
    }

    setProducts(filtered);
  }, [allProducts, searchQ, searchType, siteFilter, statusFilter, aiFilter, sortBy, pageSize, currentPage, policies, filterNameMap, filterByGroupId, highlightProductId, orderProductIds]);

  // 필터/정렬/페이지크기 변경 시 1페이지로 리셋 + 선택 초기화
  useEffect(() => { setCurrentPage(1); setSelectAll(false); setSelectedIds(new Set()) }, [searchQ, searchType, siteFilter, statusFilter, aiFilter, sortBy, pageSize, filterByGroupId]);

  const totalCount = useMemo(() => {
    let filtered = [...allProducts];
    if (filterByGroupId) filtered = filtered.filter((p) => p.search_filter_id === filterByGroupId);
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      switch (searchType) {
        case "name":
          filtered = filtered.filter((p) => p.name.toLowerCase().includes(q));
          break;
        case "filter": {
          const matchIds = new Set(
            Object.entries(filterNameMap)
              .filter(([, name]) => name.toLowerCase().includes(q))
              .map(([id]) => id)
          );
          filtered = filtered.filter((p) => p.search_filter_id && matchIds.has(p.search_filter_id));
          break;
        }
        case "no":
          filtered = filtered.filter((p) => (p.site_product_id || "").toLowerCase().includes(q));
          break;
        case "policy": {
          const matchPols = policies.filter((pol) => pol.name.toLowerCase().includes(q));
          const polIds = new Set(matchPols.map((pol) => pol.id));
          filtered = filtered.filter((p) => p.applied_policy_id && polIds.has(p.applied_policy_id));
          break;
        }
      }
    }
    if (siteFilter) filtered = filtered.filter((p) => p.source_site === siteFilter);
    if (statusFilter === 'has_orders') {
      filtered = filtered.filter((p) => orderProductIds.has(p.id))
    } else if (statusFilter) {
      filtered = filtered.filter((p) => p.status === statusFilter)
    }
    return filtered.length;
  }, [allProducts, searchQ, searchType, siteFilter, statusFilter, filterByGroupId, filterNameMap, policies]);

  const allSites = useMemo(() => [...new Set(allProducts.map(p => p.source_site))].sort(), [allProducts])

  const handleSearch = () => {
    // highlight 필터가 있으면 해제하고 전체 검색
    if (highlightProductId) {
      router.push(`/samba/products${searchQ.trim() ? `?q=${encodeURIComponent(searchQ)}` : ''}`)
    }
    setCurrentPage(1)
  };

  const handleDelete = (id: string) => {
    const p = allProducts.find((x) => x.id === id);
    if (p?.lock_delete) {
      showAlert('삭제잠금이 설정된 상품입니다. 잠금을 해제한 후 삭제하세요.')
      return;
    }
    setDeleteConfirm({ ids: [id], label: p ? `"${p.name.slice(0, 30)}"` : "이 상품" });
  };

  const handleBulkDelete = () => {
    if (selectedIds.size === 0) return;
    const locked = allProducts.filter((p) => selectedIds.has(p.id) && p.lock_delete);
    // 잠금 상품 제외하고 나머지만 삭제
    const deletableIds = [...selectedIds].filter(
      (id) => !allProducts.find((p) => p.id === id)?.lock_delete
    );
    if (deletableIds.length === 0) {
      showAlert('선택된 상품이 모두 삭제잠금 상태입니다.')
      return;
    }
    const lockMsg = locked.length > 0 ? ` (삭제잠금 ${locked.length}개 제외)` : '';
    setDeleteConfirm({ ids: deletableIds, label: `${deletableIds.length}개 상품${lockMsg}` });
  };

  const handleLockToggle = async (productId: string, field: 'lock_delete' | 'lock_stock', value: boolean) => {
    // 낙관적 업데이트 (새로고침 없이 즉시 반영)
    setAllProducts(prev => prev.map(p =>
      p.id === productId ? { ...p, [field]: value } : p
    ))
    try {
      await collectorApi.updateProduct(productId, { [field]: value } as Partial<SambaCollectedProduct>)
    } catch (e) {
      console.error(`${field} 변경 실패:`, e)
      showAlert(`${field === 'lock_stock' ? '재고잠금' : '삭제잠금'} 변경에 실패했습니다.`, 'error')
      // 실패 시 원복
      setAllProducts(prev => prev.map(p =>
        p.id === productId ? { ...p, [field]: !value } : p
      ))
    }
  };

  const confirmDelete = async () => {
    if (!deleteConfirm) return;
    await Promise.all(deleteConfirm.ids.map(id => collectorApi.deleteProduct(id).catch(() => {})))
    setSelectedIds(new Set());
    setSelectAll(false);
    setDeleteConfirm(null);
    load();
  };

  const handlePolicyChange = async (productId: string, policyId: string) => {
    await collectorApi.updateProduct(productId, { applied_policy_id: policyId || undefined } as Partial<SambaCollectedProduct>).catch(() => {});
    load();
  };

  const handleEnrich = async (productId: string) => {
    const product = allProducts.find((p) => p.id === productId)
    const productName = (product?.name || productId).slice(0, 25)
    setActiveLog({ productId, message: `[업데이트 중] ${productName}...` })
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === 'production' ? 'https://samba-wave-production.up.railway.app' : 'http://localhost:28080')
      const res = await fetch(`${apiBase}/api/v1/samba/collector/enrich/${productId}`, { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        const p = data.product
        const costVal = p?.cost || p?.sale_price
        const priceStr = costVal != null ? `₩${Number(costVal).toLocaleString()}` : '-'
        const stockStr = p?.sale_status === 'preorder' ? '판매예정' : p?.sale_status === 'sold_out' || p?.is_sold_out ? '품절' : '재고있음'
        const now = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        setActiveLog({ productId, message: `[${now}] ${productName} → ${priceStr} | ${stockStr}` })
        // 해당 상품만 갱신 (전체 새로고침 없음)
        if (p) {
          setAllProducts(prev => prev.map(item => item.id === productId ? { ...item, ...p } : item))
        }
      } else {
        setActiveLog({ productId, message: `[실패] ${productName} → ${data.detail || '상세 보강 실패'}` })
      }
    } catch {
      setActiveLog({ productId, message: `[오류] ${productName} → 서버 연결 실패` })
    }
  };

  const handleMarketDelete = async (productId: string) => {
    const p = allProducts.find(x => x.id === productId)
    const regAccIds = p?.registered_accounts ?? []
    if (!regAccIds.length) {
      showAlert('마켓에 등록된 계정이 없습니다.')
      return
    }
    if (!await showConfirm('마켓에서 상품을 삭제(판매중지)하시겠습니까?')) return
    try {
      const res = await shipmentApi.marketDelete([productId], regAccIds)
      const result = res?.results?.[0]
      if (result && result.success_count > 0) {
        showAlert(`마켓삭제 완료 (${result.success_count}개 마켓)`, 'success')
      } else {
        showAlert('마켓삭제 처리 완료 (일부 실패할 수 있음)')
      }
      load()
    } catch {
      showAlert('마켓삭제 중 오류가 발생했습니다.', 'error')
    }
  }

  const handleToggleMarket = async (productId: string, marketId: string) => {
    const product = allProducts.find((p) => p.id === productId);
    if (!product) return;
    const currentEnabled = (product.market_enabled || {}) as Record<string, boolean>;
    const isOn = currentEnabled[marketId] !== false;
    const newEnabled = { ...currentEnabled, [marketId]: !isOn };
    await collectorApi.updateProduct(productId, { market_enabled: newEnabled } as unknown as Partial<SambaCollectedProduct>).catch(() => {});
    // Optimistic update
    setAllProducts((prev) =>
      prev.map((p) =>
        p.id === productId ? { ...p, market_enabled: newEnabled } as unknown as SambaCollectedProduct : p
      )
    );
  };

  const handleSelectAll = (checked: boolean) => {
    setSelectAll(checked);
    if (checked) {
      setSelectedIds(new Set(products.map((p) => p.id)));
    } else {
      setSelectedIds(new Set());
    }
  };

  const handleCheckboxToggle = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0" }}>
      {/* AI 작업 진행 모달 */}
      {aiJobModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 99998,
          background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px',
            width: '520px', maxHeight: '70vh', display: 'flex', flexDirection: 'column',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              padding: '14px 20px', borderBottom: '1px solid #2D2D2D',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <span style={{ fontWeight: 700, fontSize: '0.9rem', color: '#E5E5E5' }}>{aiJobTitle}</span>
              {aiJobDone && (
                <button onClick={() => setAiJobModal(false)} style={{
                  background: 'none', border: 'none', color: '#888', fontSize: '1.1rem', cursor: 'pointer',
                }}>✕</button>
              )}
            </div>
            <div
              ref={aiJobLogRef}
              style={{
                flex: 1, overflow: 'auto', padding: '14px', fontFamily: 'monospace',
                fontSize: '0.68rem', lineHeight: 1.6, color: '#8A95B0',
                maxHeight: '50vh',
              }}
            >
              {aiJobLogs.map((line, i) => (
                <p key={i} style={{
                  margin: 0,
                  color: line.includes('완료') && !line.includes('실패') ? '#51CF66'
                    : line.includes('실패') || line.includes('오류') ? '#FF6B6B'
                    : '#8A95B0',
                }}>{line}</p>
              ))}
              {!aiJobDone && (
                <p style={{ margin: 0, color: '#FFB84D' }}>처리 중...</p>
              )}
            </div>
            {aiJobDone && (
              <div style={{ padding: '12px 20px', borderTop: '1px solid #2D2D2D', textAlign: 'right' }}>
                <button onClick={() => setAiJobModal(false)} style={{
                  padding: '6px 20px', borderRadius: '6px', fontSize: '0.8rem',
                  background: 'rgba(81,207,102,0.15)', border: '1px solid rgba(81,207,102,0.4)',
                  color: '#51CF66', cursor: 'pointer', fontWeight: 600,
                }}>확인</button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 삭제 확인 모달 */}
      {deleteConfirm && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 99999, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => setDeleteConfirm(null)}
        >
          <div
            style={{ background: "#1A1A1A", border: "1px solid #2D2D2D", borderRadius: "12px", padding: "28px 32px", minWidth: "320px", maxWidth: "480px" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 8px", fontSize: "1rem", fontWeight: 600, color: "#E5E5E5" }}>상품 삭제</h3>
            <p style={{ margin: "0 0 24px", fontSize: "0.875rem", color: "#888", lineHeight: 1.6 }}>
              {deleteConfirm.label}을(를) 삭제하시겠습니까?<br />
              <span style={{ color: "#FF6B6B", fontSize: "0.8rem" }}>삭제된 상품은 복구할 수 없습니다.</span>
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button
                onClick={() => setDeleteConfirm(null)}
                style={{ padding: "7px 20px", fontSize: "0.85rem", borderRadius: "6px", cursor: "pointer", border: "1px solid #3D3D3D", background: "transparent", color: "#888" }}
              >취소</button>
              <button
                onClick={confirmDelete}
                style={{ padding: "7px 20px", fontSize: "0.85rem", borderRadius: "6px", cursor: "pointer", border: "1px solid rgba(255,107,107,0.5)", background: "rgba(255,107,107,0.15)", color: "#FF6B6B", fontWeight: 600 }}
              >삭제</button>
            </div>
          </div>
        </div>
      )}
      {/* AI 태그 미리보기 모달 */}
      {showTagPreview && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => { setShowTagPreview(false); setRemovedTags([]) }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '28px 32px', minWidth: '500px', maxWidth: '700px', maxHeight: '80vh', overflowY: 'auto' }}
            onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: '#E5E5E5' }}>AI 태그 미리보기</h3>
            <p style={{ margin: '0 0 20px', fontSize: '0.75rem', color: '#888' }}>
              태그사전에 미등록된 태그를 X로 제거한 후 적용하세요
            </p>
            {tagPreviews.map((preview) => (
              <div key={preview.group_id} style={{ marginBottom: '20px', padding: '16px', background: '#0F0F0F', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span style={{ fontSize: '0.82rem', color: '#FFB84D', fontWeight: 600 }}>{preview.rep_name}</span>
                  <span style={{ fontSize: '0.7rem', color: '#666' }}>{preview.product_count}개 상품 | {preview.tags.length}개 태그</span>
                </div>
                <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ fontSize: '0.72rem', color: '#4C9AFF', fontWeight: 600, whiteSpace: 'nowrap' }}>SEO:</span>
                  <input
                    type="text"
                    defaultValue={preview.seo_keywords.join(', ')}
                    placeholder="SEO 키워드 (콤마 구분)"
                    onBlur={(e) => {
                      const newKws = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                      setTagPreviews(prev => prev.map(p =>
                        p.group_id === preview.group_id ? { ...p, seo_keywords: newKws } : p
                      ))
                    }}
                    onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                    style={{ flex: 1, fontSize: '0.72rem', padding: '3px 8px', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#4C9AFF', outline: 'none' }}
                  />
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
                  {preview.tags.map((tag, ti) => (
                    <span key={ti} style={{
                      fontSize: '0.78rem', padding: '4px 10px', borderRadius: '14px',
                      background: 'rgba(100,100,255,0.1)', border: '1px solid rgba(100,100,255,0.25)', color: '#8B8FD4',
                      display: 'inline-flex', alignItems: 'center', gap: '6px',
                    }}>
                      {tag}
                      <span
                        style={{ cursor: 'pointer', color: '#666', fontSize: '0.85rem', lineHeight: 1 }}
                        onClick={async () => {
                          setTagPreviews(prev => prev.map(p => ({
                            ...p, tags: p.tags.filter(t => t !== tag)
                          })))
                          const ban = await showConfirm(`"${tag}"을(를) 금지태그에 등록할까요?\n(등록하면 다음 AI태그 생성 시 자동 제외됩니다)`)
                          if (ban) {
                            setRemovedTags(prev => prev.includes(tag) ? prev : [...prev, tag])
                          }
                        }}
                      >&times;</span>
                    </span>
                  ))}
                </div>
                <input
                  type="text"
                  placeholder="추가 태그 입력 후 Enter (콤마 구분 가능)"
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      const input = (e.target as HTMLInputElement)
                      const newTags = input.value.split(',').map(t => t.trim()).filter(Boolean)
                      if (newTags.length === 0) return
                      setTagPreviews(prev => prev.map(p =>
                        p.group_id === preview.group_id
                          ? { ...p, tags: [...p.tags, ...newTags.filter(t => !p.tags.includes(t))] }
                          : p
                      ))
                      input.value = ''
                    }
                  }}
                  style={{
                    width: '100%', padding: '5px 10px', fontSize: '0.75rem',
                    background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px',
                    color: '#E5E5E5', outline: 'none',
                  }}
                />
              </div>
            ))}
            {removedTags.length > 0 && (
              <div style={{ marginBottom: '12px', padding: '10px 14px', background: 'rgba(255,107,107,0.06)', borderRadius: '6px', border: '1px solid rgba(255,107,107,0.15)' }}>
                <span style={{ fontSize: '0.72rem', color: '#FF6B6B', fontWeight: 600 }}>금지태그 등록 예정 ({removedTags.length}개): </span>
                <span style={{ fontSize: '0.72rem', color: '#888' }}>{removedTags.join(', ')}</span>
              </div>
            )}
            {tagPreviewCost && (
              <p style={{ margin: '0 0 16px', fontSize: '0.72rem', color: '#666', textAlign: 'right' }}>
                API {tagPreviewCost.api_calls}회 | {tagPreviewCost.input_tokens + tagPreviewCost.output_tokens} 토큰 | ~{tagPreviewCost.cost_krw}원
              </p>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => { setShowTagPreview(false); setRemovedTags([]) }}
                style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'transparent', color: '#888' }}>취소</button>
              <button onClick={async () => {
                const groups = tagPreviews.filter(p => p.tags.length > 0).map(p => ({ group_id: p.group_id, tags: p.tags, seo_keywords: p.seo_keywords }))
                if (groups.length === 0) { showAlert('적용할 태그가 없습니다'); return }
                try {
                  const res = await proxyApi.applyAiTags(groups, removedTags)
                  if (res.success) {
                    showAlert(res.message, 'success')
                    if (tagPreviewCost) {
                      const now = new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' })
                      setLastAiUsage({
                        calls: tagPreviewCost.api_calls,
                        tokens: tagPreviewCost.input_tokens + tagPreviewCost.output_tokens,
                        cost: tagPreviewCost.cost_krw,
                        date: now,
                      })
                    }
                    setShowTagPreview(false)
                    setSelectedIds(new Set()); setSelectAll(false)
                    load()
                  } else showAlert(res.message, 'error')
                } catch (e) {
                  showAlert(`태그 적용 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
                }
              }}
                style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(255,140,0,0.5)', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600 }}>
                전체 그룹에 적용 ({tagPreviews.reduce((s, p) => s + p.tags.length, 0)}개 태그)
              </button>
            </div>
          </div>
        </div>
      )}
      {/* 그룹 필터 배지 */}
      {filterByGroupId && (
        <div style={{
          display: "flex", alignItems: "center", gap: "8px",
          padding: "6px 12px", marginBottom: "12px", borderRadius: "8px",
          background: "rgba(255,140,0,0.08)", border: "1px solid rgba(255,140,0,0.3)",
          fontSize: "0.82rem",
        }}>
          <span style={{ color: "#888" }}>검색그룹:</span>
          <span style={{
            color: "#FF8C00", fontWeight: 600,
            background: "rgba(255,140,0,0.12)", border: "1px solid rgba(255,140,0,0.4)",
            padding: "1px 8px", borderRadius: "4px",
          }}>
            {filterGroupName || filterByGroupId}
          </span>
          <button
            onClick={() => router.push("/samba/products")}
            style={{
              marginLeft: "auto", background: "transparent", border: "1px solid #3D3D3D",
              color: "#888", padding: "2px 10px", borderRadius: "4px",
              fontSize: "0.75rem", cursor: "pointer",
            }}
          >
            전체보기
          </button>
        </div>
      )}
      {/* 상품 하이라이트 필터 배지 */}
      {highlightProductId && (
        <div style={{
          display: "flex", alignItems: "center", gap: "8px",
          padding: "6px 12px", marginBottom: "12px", borderRadius: "8px",
          background: "rgba(76,154,255,0.08)", border: "1px solid rgba(76,154,255,0.3)",
          fontSize: "0.82rem",
        }}>
          <span style={{ color: "#888" }}>선택 상품:</span>
          <span style={{ color: "#4C9AFF", fontWeight: 600 }}>
            {allProducts.find(p => p.id === highlightProductId)?.name?.slice(0, 40) || highlightProductId}
          </span>
          <button
            onClick={() => router.push("/samba/products")}
            style={{
              marginLeft: "auto", background: "transparent", border: "1px solid #3D3D3D",
              color: "#888", padding: "2px 10px", borderRadius: "4px",
              fontSize: "0.75rem", cursor: "pointer",
            }}
          >전체보기</button>
        </div>
      )}
      {/* KPI stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem" }}>
        <div style={{
          background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "12px",
          padding: "1.75rem", borderLeft: "3px solid #FF8C00",
          display: "flex", flexDirection: "column", gap: "4px",
        }}>
          <p style={{ fontSize: "0.75rem", color: "#888", fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", margin: 0 }}>수집상품 수</p>
          <p style={{ fontSize: "1.625rem", fontWeight: 800, color: "#E5E5E5", letterSpacing: "-0.02em", margin: 0 }}>
            {allProducts.length}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
          </p>
          <p style={{ fontSize: "0.75rem", color: "#666", margin: 0 }}>등록된 상품</p>
        </div>
        <div style={{
          background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "12px",
          padding: "1.75rem", borderLeft: "3px solid #FFB84D",
          display: "flex", flexDirection: "column", gap: "4px",
        }}>
          <p style={{ fontSize: "0.75rem", color: "#888", fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", margin: 0 }}>판매상품 수</p>
          <p style={{ fontSize: "1.625rem", fontWeight: 800, color: "#51CF66", letterSpacing: "-0.02em", margin: 0 }}>
            {allProducts.filter((p) => p.status === "registered").length}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
          </p>
          <p style={{ fontSize: "0.75rem", color: "#666", margin: 0 }}>판매중인 상품</p>
        </div>
      </div>

      {/* Filter area */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1rem", marginBottom: "1rem", fontSize: "0.875rem",
      }}>
        {/* 검색 조건 1줄 배치 */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
          <span style={{ color: "#888", whiteSpace: "nowrap", fontSize: "0.8125rem" }}>등록일자</span>
          <input type="date" style={{
            width: "130px", padding: "0.3rem 0.4rem", fontSize: "0.78rem",
            background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
            color: "#E5E5E5",
          }} />
          <span style={{ color: "#888" }}>~</span>
          <input type="date" style={{
            width: "130px", padding: "0.3rem 0.4rem", fontSize: "0.78rem",
            background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
            color: "#E5E5E5",
          }} />
          <select value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}
            style={{ padding: "0.3rem 0.4rem", fontSize: "0.78rem", background: "rgba(22,22,22,0.95)", border: "1px solid #353535", color: "#C5C5C5", borderRadius: "6px" }}>
            <option value="">소싱사이트</option>
            {allSites.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: "0.3rem 0.4rem", fontSize: "0.78rem", background: "rgba(22,22,22,0.95)", border: "1px solid #353535", color: "#C5C5C5", borderRadius: "6px" }}>
            <option value="">판매현황</option>
            <option value="registered">마켓등록</option>
            <option value="collected">미등록</option>
          </select>
          <select value={searchType} onChange={(e) => setSearchType(e.target.value)}
            style={{ padding: "0.3rem 0.4rem", fontSize: "0.78rem", background: "#1E1E1E", border: "1px solid #3D3D3D", borderRadius: "6px", color: "#C5C5C5", width: "90px" }}>
            <option value="name">상품명</option>
            <option value="filter">그룹</option>
            <option value="no">상품번호</option>
            <option value="policy">정책</option>
          </select>
          <input type="text" placeholder="검색어" value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            style={{
              flex: 1, minWidth: "120px", maxWidth: "200px",
              padding: "0.3rem 0.5rem", fontSize: "0.78rem",
              background: "#1E1E1E", border: "1px solid #3D3D3D", borderRadius: "6px",
              color: "#C5C5C5", outline: "none",
            }}
          />
          <button onClick={handleSearch}
            style={{
              background: "rgba(255,140,0,0.15)", border: "1px solid #FF8C00",
              color: "#FF8C00", padding: "0.3rem 0.625rem", borderRadius: "6px",
              fontSize: "0.78rem", whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer",
            }}>검색</button>
        </div>
      </div>

      {/* 작업 로그 패널 */}
      {taskLogs.length > 0 && (<div style={{ background: 'rgba(8,10,16,0.98)', border: '1px solid #1C1E2A', borderRadius: '8px', marginBottom: '8px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 14px', background: '#0A0D14', borderBottom: '1px solid #1C1E2A' }}>
          <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#9AA5C0' }}>작업 로그</span>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button onClick={() => navigator.clipboard.writeText(taskLogs.join('\n'))} style={{ padding: '2px 8px', fontSize: '0.68rem', background: 'transparent', border: '1px solid #252B3B', color: '#666', borderRadius: '3px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setTaskLogs([])} style={{ padding: '2px 8px', fontSize: '0.68rem', background: 'transparent', border: '1px solid #252B3B', color: '#666', borderRadius: '3px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={el => { if (el) el.scrollTop = el.scrollHeight }} style={{ maxHeight: '150px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.72rem', lineHeight: 1.7 }}>
          {taskLogs.map((msg, i) => {
            let color = '#555'
            if (msg.includes('실패') || msg.includes('오류')) color = '#FF6B6B'
            else if (msg.includes('완료') || msg.includes('성공')) color = '#51CF66'
            else if (msg.includes('생성 중') || msg.includes('처리 중')) color = '#FFB84D'
            return <div key={i} style={{ color }}>{msg}</div>
          })}
        </div>
      </div>)}

      {/* AI비용 + AI 이미지 변환 + 이미지 필터링 — 3단 나란히 배치 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '1rem' }}>
      {/* AI 비용 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(81,207,102,0.08)', border: '1px solid rgba(81,207,102,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#51CF66', fontWeight: 600 }}>AI 비용</span>
        {lastAiUsage ? (
          <>
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{lastAiUsage.calls}건</span>
            <span style={{ fontSize: '0.78rem', color: '#888' }}>·</span>
            <span style={{ fontSize: '0.78rem', color: '#FFB84D' }}>₩{lastAiUsage.cost.toLocaleString()}</span>
            <span style={{ fontSize: '0.7rem', color: '#555' }}>{lastAiUsage.date}</span>
          </>
        ) : (
          <span style={{ fontSize: '0.78rem', color: '#555' }}>사용 내역 없음</span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 이미지 변환</span>
        <select value={aiImgMode} onChange={e => setAiImgMode(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
          <option value="background">배경 제거</option>
          <option value="scene">연출컷</option>
          <option value="model">모델 착용</option>
        </select>
        {aiImgMode === 'model' && (
          <select value={aiModelPreset} onChange={e => setAiModelPreset(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
            <optgroup label="여성"><option value="female_v1">청순 생머리</option><option value="female_v2">시크 단발</option><option value="female_v3">건강 웨이브</option></optgroup>
            <optgroup label="남성"><option value="male_v1">깔끔 슬림</option><option value="male_v2">남성미 근육</option><option value="male_v3">훈남 스타일</option></optgroup>
            <optgroup label="키즈 여아"><option value="kids_girl_v1">긴머리 차분</option><option value="kids_girl_v2">단발 활발</option><option value="kids_girl_v3">양갈래 귀여움</option></optgroup>
            <optgroup label="키즈 남아"><option value="kids_boy_v1">밝은 정면</option><option value="kids_boy_v2">장난꾸러기</option><option value="kids_boy_v3">차분한</option></optgroup>
          </select>
        )}
        <span style={{ fontSize: '0.78rem', color: '#888' }}>({selectedIds.size}개 상품)</span>
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 이미지를 변환하시겠습니까?`)
            if (!ok) return
            const ids = [...selectedIds]
            setAiImgTransforming(true)
            setAiJobTitle(`AI 이미지변환 (${ids.length}개)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            let success = 0
            let fail = 0
            for (let i = 0; i < ids.length; i++) {
              const prod = allProducts.find(p => p.id === ids[i])
              const label = prod?.name?.slice(0, 30) || ids[i].slice(-8)
              try {
                const autoScope = { thumbnail: true, additional: true, detail: true }
                const res = await proxyApi.transformImages([ids[i]], autoScope, aiImgMode, aiModelPreset)
                if (res.success) { success++; addLog(`[${i + 1}/${ids.length}] ${label} — 완료`) }
                else { fail++; addLog(`[${i + 1}/${ids.length}] ${label} — 실패: ${res.message}`) }
              } catch (e) { fail++; addLog(`[${i + 1}/${ids.length}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
            }
            addLog(`\n완료: 성공 ${success}개 / 실패 ${fail}개`)
            setAiJobDone(true)
            setAiImgTransforming(false)
            setSelectedIds(new Set()); setSelectAll(false)
            load()
          }}
          disabled={aiImgTransforming || selectedIds.size === 0}
          style={{ marginLeft: 'auto', background: aiImgTransforming ? '#333' : 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)', color: aiImgTransforming ? '#888' : '#FF8C00', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: aiImgTransforming ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
        >{aiImgTransforming ? '변환중...' : '변환 실행'}</button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#818CF8', fontWeight: 600 }}>이미지 필터링</span>
        {(['images', 'detail', 'all'] as const).map(s => (
          <label key={s} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input type="radio" name="imgFilterScope" checked={imgFilterScope === s}
              onChange={() => setImgFilterScope(s)}
              style={{ accentColor: '#818CF8', width: '13px', height: '13px' }} />
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>
              {s === 'images' ? '대표+추가' : s === 'detail' ? '상세이미지' : '전체'}
            </span>
          </label>
        ))}
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const scopeLabel = imgFilterScope === 'images' ? '대표+추가이미지' : imgFilterScope === 'detail' ? '상세이미지' : '전체 이미지'
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 ${scopeLabel}를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
            if (!ok) return
            const ids = [...selectedIds]
            setImgFiltering(true)
            setAiJobTitle(`이미지 필터링 (${ids.length}개)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            let success = 0
            let fail = 0
            for (let i = 0; i < ids.length; i++) {
              const prod = allProducts.find(p => p.id === ids[i])
              const label = prod?.name?.slice(0, 30) || ids[i].slice(-8)
              try {
                const r = await proxyApi.filterProductImages([ids[i]], '', imgFilterScope)
                if (r.success) { success++; addLog(`[${i + 1}/${ids.length}] ${label} — 완료`) }
                else { fail++; addLog(`[${i + 1}/${ids.length}] ${label} — 실패`) }
              } catch (e) { fail++; addLog(`[${i + 1}/${ids.length}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
            }
            addLog(`\n완료: 성공 ${success}개 / 실패 ${fail}개`)
            setAiJobDone(true)
            setImgFiltering(false)
            const apiCalls = success + fail
            setLastAiUsage({ calls: apiCalls, tokens: apiCalls * 1000, cost: apiCalls * 15, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
            setSelectedIds(new Set()); setSelectAll(false)
            load()
          }}
          disabled={imgFiltering || selectedIds.size === 0}
          style={{ marginLeft: 'auto', background: imgFiltering ? '#333' : 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.35)', color: imgFiltering ? '#888' : '#818CF8', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: imgFiltering ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
        >{imgFiltering ? '필터링중...' : '필터링 실행'}</button>
      </div>
      </div>

      {/* Result header + action bar */}
      <div style={{
        background: "rgba(18,18,18,0.95)", border: "1px solid #2A2A2A", borderRadius: "8px",
        padding: "8px 14px", marginBottom: "1rem",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "8px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "5px", cursor: "pointer", margin: 0 }}>
            <input
              type="checkbox"
              checked={selectAll}
              onChange={(e) => handleSelectAll(e.target.checked)}
              style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "0.8rem", color: "#666", whiteSpace: "nowrap" }}>전체선택</span>
          </label>
          <span style={{ fontSize: "0.875rem", color: "#E5E5E5", fontWeight: 600, whiteSpace: "nowrap" }}>
            상품관리 <span style={{ color: "#FF8C00" }}>( 총 <span>{totalCount}</span>개 검색 )</span>
          </span>
          <button onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 영상을 생성하시겠습니까?`)
            if (!ok) return
            for (const pid of selectedIds) {
              const prod = products.find(p => p.id === pid)
              try {
                addTaskLog(`[영상생성] ${prod?.name?.slice(0, 25) || pid} — 생성 중...`)
                await collectorApi.generateVideo(pid, 3, 1.0)
                addTaskLog(`[영상생성] ${prod?.name?.slice(0, 25) || pid} — 완료`)
              } catch (e) {
                addTaskLog(`[영상생성] ${prod?.name?.slice(0, 25) || pid} — 실패: ${e instanceof Error ? e.message : e}`)
              }
            }
            load()
          }} style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(76,154,255,0.3)", borderRadius: "5px",
            color: "#4C9AFF", background: "rgba(76,154,255,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>영상생성</button>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid #3D3D3D", borderRadius: "5px",
            color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
          }}>AI상품명변경</button>
          <button onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품에 AI 태그를 생성하시겠습니까?\n(그룹별 대표 1개로 API 호출, 미리보기 후 확정)`)
            if (!ok) return
            setTagPreviewLoading(true)
            try {
              const res = await proxyApi.previewAiTags([...selectedIds])
              if (res.success) {
                setTagPreviews(res.previews)
                setTagPreviewCost({ api_calls: res.api_calls, input_tokens: res.input_tokens, output_tokens: res.output_tokens, cost_krw: res.cost_krw })
                setRemovedTags([])
                setShowTagPreview(true)
              } else showAlert(res.message, 'error')
            } catch (e) {
              showAlert(`태그 생성 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
            } finally {
              setTagPreviewLoading(false)
            }
          }} disabled={tagPreviewLoading} style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid #3D3D3D", borderRadius: "5px",
            color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: tagPreviewLoading ? "wait" : "pointer", whiteSpace: "nowrap", opacity: tagPreviewLoading ? 0.5 : 1,
          }}>{tagPreviewLoading ? 'AI태그 생성중...' : 'AI태그'}</button>
          <button onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 태그를 모두 삭제하시겠습니까?`)
            if (!ok) return
            await Promise.all([...selectedIds].map(id =>
              collectorApi.updateProduct(id, { tags: [], seo_keywords: [] } as Partial<SambaCollectedProduct>).catch(() => {})
            ))
            setAllProducts(prev => prev.map(p => selectedIds.has(p.id) ? { ...p, tags: [], seo_keywords: [] as string[] } : p))
            showAlert(`${selectedIds.size}개 상품 태그 삭제 완료`, 'success')
            setSelectedIds(new Set()); setSelectAll(false)
          }} style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(255,107,107,0.3)", borderRadius: "5px",
            color: "#FF6B6B", background: "rgba(255,107,107,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>태그 삭제</button>
          <button
            onClick={() => {
              if (selectedIds.size === 0) { showAlert('전송할 상품을 선택해주세요'); return }
              const ids = Array.from(selectedIds).join(',')
              const sites = [...new Set(
                Array.from(selectedIds).map(id => products.find(p => p.id === id)?.source_site).filter(Boolean)
              )].join(',')
              router.push(`/samba/shipments?selected=${encodeURIComponent(ids)}&sites=${encodeURIComponent(sites)}&autoAll=1`)
            }}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid #3D3D3D", borderRadius: "5px",
              color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
            }}>상품전송</button>
          <button
            onClick={handleBulkDelete}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid #3D3D3D", borderRadius: "5px",
              color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >상품삭제</button>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
              // 선택된 상품 중 등록된 계정이 있는 것만 대상
              const targets = allProducts.filter(p => selectedIds.has(p.id) && (p.registered_accounts?.length ?? 0) > 0)
              if (!targets.length) { showAlert('마켓에 등록된 상품이 없습니다.'); return }
              if (!await showConfirm(`${targets.length}개 상품을 마켓에서 삭제(판매중지)하시겠습니까?`)) return
              try {
                const productIds = targets.map(p => p.id)
                const allAccIds = [...new Set(targets.flatMap(p => p.registered_accounts ?? []))]
                await shipmentApi.marketDelete(productIds, allAccIds)
                showAlert(`${targets.length}개 상품 마켓삭제 완료`, 'success')
                load()
              } catch {
                showAlert('마켓삭제 중 오류가 발생했습니다.', 'error')
              }
            }}
            style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid #3D3D3D", borderRadius: "5px",
            color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
          }}>마켓삭제</button>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
              if (!await showConfirm(`${selectedIds.size}개 상품의 마켓 등록 정보를 초기화하시겠습니까?\n(마켓에서 이미 삭제된 상품의 등록 상태만 정리합니다)`)) return
              for (const id of selectedIds) {
                await collectorApi.resetRegistration(id).catch(() => {})
              }
              showAlert(`${selectedIds.size}개 상품 마켓 등록 정보 초기화 완료`, 'success')
              load()
            }}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid #3D3D3D", borderRadius: "5px",
              color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >강제삭제</button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => { setViewMode("compact"); setExpandedIds(new Set()) }}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "compact" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "compact" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "compact" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >간단보기</button>
          <button
            onClick={() => setViewMode("card")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "card" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "card" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "card" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >건별보기</button>
          <button
            onClick={() => setViewMode("image")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "image" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "image" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "image" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >이미지만보기</button>
          <select
            value={aiFilter}
            onChange={(e) => setAiFilter(e.target.value)}
            style={{ background: '#1A1A1A', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
          >
            <option value="">전체</option>
            <option value="sold_out">품절상품</option>
            <option value="ai_tag_yes">AI태그 적용</option>
            <option value="ai_tag_no">AI태그 미적용</option>
            <option value="ai_img_yes">AI이미지 적용</option>
            <option value="ai_img_no">AI이미지 미적용</option>
            <option value="filter_yes">필터링완료</option>
            <option value="filter_no">필터링미완료</option>
            <option value="img_edit_yes">이미지수정완료</option>
            <option value="img_edit_no">이미지수정미완료</option>
            <option value="video_yes">영상있음</option>
            <option value="video_no">영상없음</option>
            <option value="has_orders">판매이력상품</option>
          </select>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{
              width: "auto", padding: "0.25rem 0.5rem", fontSize: "0.75rem",
              background: "#1A1A1A", border: "1px solid #3D3D3D", color: "#C5C5C5", borderRadius: "6px",
            }}
          >
            <option value="collect-desc">수집일 최신순</option>
            <option value="collect-asc">수집일 오래된순</option>
            <option value="update-desc">업데이트일 최신순</option>
            <option value="update-asc">업데이트일 오래된순</option>
          </select>
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            style={{
              width: "auto", padding: "0.25rem 0.5rem", fontSize: "0.75rem",
              background: "#1A1A1A", border: "1px solid #3D3D3D", color: "#C5C5C5", borderRadius: "6px",
            }}
          >
            <option value={20}>20개씩</option>
            <option value={50}>50개씩</option>
            <option value={100}>100개씩</option>
            <option value={0}>전체</option>
          </select>
        </div>
      </div>

      {/* Product list */}
      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#555", fontSize: "0.9rem" }}>로딩 중...</div>
      ) : products.length === 0 ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#555", fontSize: "0.9rem" }}>
          등록된 상품이 없습니다
        </div>
      ) : viewMode === "image" ? (
        /* Image grid view */
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "8px" }}>
          {products.map((p) => (
            <div key={p.id} style={{
              background: "rgba(30,30,30,0.5)",
              border: selectedIds.has(p.id) ? "1px solid #FF8C00" : "1px solid #2D2D2D",
              borderRadius: "8px",
              overflow: "hidden", cursor: "pointer", position: "relative",
            }} onClick={() => handleCheckboxToggle(p.id, !selectedIds.has(p.id))}>
              <input
                type="checkbox"
                checked={selectedIds.has(p.id)}
                onChange={e => handleCheckboxToggle(p.id, e.target.checked)}
                onClick={e => e.stopPropagation()}
                style={{
                  position: "absolute", top: "6px", left: "6px", zIndex: 1,
                  accentColor: "#FF8C00", width: "14px", height: "14px", cursor: "pointer",
                }}
              />
              <ProductImage src={p.images?.[0]} name={p.name} size={140} />
              {(p.free_shipping || p.same_day_delivery) && (
                <div style={{ display: 'flex', gap: '3px', padding: '3px 8px 0' }}>
                  {p.free_shipping && <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(76,154,255,0.15)', color: '#4C9AFF', fontWeight: 600 }}>무배</span>}
                  {p.same_day_delivery && <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600 }}>당발</span>}
                </div>
              )}
              <div style={{ padding: "6px 8px" }}>
                <p style={{ fontSize: '0.7rem', color: '#C5C5C5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', margin: 0, display: 'flex', alignItems: 'center' }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</span>
                  {p.group_key && !p.group_product_no && (
                    <span style={{
                      background: 'rgba(81,207,102,0.15)', color: '#51CF66',
                      padding: '0.1rem 0.3rem', borderRadius: '4px',
                      fontSize: '0.6rem', marginLeft: '0.25rem', whiteSpace: 'nowrap',
                    }}>스스그룹</span>
                  )}
                  {p.group_product_no && (
                    <span style={{
                      background: 'rgba(76,154,255,0.15)', color: '#4C9AFF',
                      padding: '0.1rem 0.3rem', borderRadius: '4px',
                      fontSize: '0.6rem', marginLeft: '0.25rem', whiteSpace: 'nowrap',
                    }}>스스그룹등록</span>
                  )}
                </p>
                <p style={{ fontSize: "0.75rem", color: "#FF8C00", fontWeight: 600, margin: 0 }}>₩{fmt(p.sale_price)}</p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Card / Compact view — 2열 그리드 */
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: viewMode === "compact" ? "4px" : "8px" }}>
          {products.map((p, idx) => (
            <ProductCard
              key={p.id}
              product={p}
              idx={idx}
              compact={viewMode === "compact"}
              expanded={expandedIds.has(p.id)}
              onToggleExpand={() => setExpandedIds(prev => {
                const next = new Set(prev)
                next.has(p.id) ? next.delete(p.id) : next.add(p.id)
                return next
              })}
              policies={policies}
              accounts={accounts}
              nameRules={nameRules}
              selectedIds={selectedIds}
              filterNameMap={filterNameMap}
              deletionWords={deletionWords}
              onCheckboxToggle={handleCheckboxToggle}
              onDelete={handleDelete}
              onPolicyChange={handlePolicyChange}
              onToggleMarket={handleToggleMarket}
              onEnrich={handleEnrich}
              onLockToggle={handleLockToggle}
              onMarketDelete={handleMarketDelete}
              onAddTaskLog={addTaskLog}
              onProductUpdate={(productId, data) => {
                setProducts(prev => prev.map(pp => pp.id === productId ? { ...pp, ...data } : pp))
              }}
              onTagUpdate={async (productId, tags) => {
                // 낙관적 업데이트 (새로고침 없이 즉시 반영)
                setAllProducts(prev => prev.map(p =>
                  p.id === productId ? { ...p, tags } : p
                ))
                await collectorApi.updateProduct(productId, { tags } as Partial<SambaCollectedProduct>).catch(() => {})
              }}
              logMessage={activeLog?.productId === p.id ? activeLog.message : undefined}
              catMappingMap={catMappingMap}
            />
          ))}
        </div>
      )}

      {/* 페이지네이션 */}
      {pageSize > 0 && totalCount > pageSize && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '16px 0' }}>
          <button
            onClick={() => setCurrentPage(1)}
            disabled={currentPage === 1}
            style={{
              padding: '4px 8px', fontSize: '0.75rem', background: '#1A1A1A',
              border: '1px solid #3D3D3D', color: currentPage === 1 ? '#444' : '#C5C5C5',
              borderRadius: '4px', cursor: currentPage === 1 ? 'default' : 'pointer',
            }}
          >«</button>
          <button
            onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
            disabled={currentPage === 1}
            style={{
              padding: '4px 10px', fontSize: '0.75rem', background: '#1A1A1A',
              border: '1px solid #3D3D3D', color: currentPage === 1 ? '#444' : '#C5C5C5',
              borderRadius: '4px', cursor: currentPage === 1 ? 'default' : 'pointer',
            }}
          >‹</button>
          {Array.from({ length: Math.min(5, Math.ceil(totalCount / pageSize)) }, (_, i) => {
            const total = Math.ceil(totalCount / pageSize)
            let start = Math.max(1, currentPage - 2)
            if (start + 4 > total) start = Math.max(1, total - 4)
            const pg = start + i
            if (pg > total) return null
            return (
              <button
                key={pg}
                onClick={() => setCurrentPage(pg)}
                style={{
                  padding: '4px 10px', fontSize: '0.75rem',
                  background: pg === currentPage ? '#FF8C00' : '#1A1A1A',
                  border: `1px solid ${pg === currentPage ? '#FF8C00' : '#3D3D3D'}`,
                  color: pg === currentPage ? '#000' : '#C5C5C5',
                  borderRadius: '4px', cursor: 'pointer', fontWeight: pg === currentPage ? 700 : 400,
                }}
              >{pg}</button>
            )
          })}
          <button
            onClick={() => setCurrentPage((p) => Math.min(Math.ceil(totalCount / pageSize), p + 1))}
            disabled={currentPage === Math.ceil(totalCount / pageSize)}
            style={{
              padding: '4px 10px', fontSize: '0.75rem', background: '#1A1A1A',
              border: '1px solid #3D3D3D',
              color: currentPage === Math.ceil(totalCount / pageSize) ? '#444' : '#C5C5C5',
              borderRadius: '4px',
              cursor: currentPage === Math.ceil(totalCount / pageSize) ? 'default' : 'pointer',
            }}
          >›</button>
          <button
            onClick={() => setCurrentPage(Math.ceil(totalCount / pageSize))}
            disabled={currentPage === Math.ceil(totalCount / pageSize)}
            style={{
              padding: '4px 8px', fontSize: '0.75rem', background: '#1A1A1A',
              border: '1px solid #3D3D3D',
              color: currentPage === Math.ceil(totalCount / pageSize) ? '#444' : '#C5C5C5',
              borderRadius: '4px',
              cursor: currentPage === Math.ceil(totalCount / pageSize) ? 'default' : 'pointer',
            }}
          >»</button>
          <span style={{ fontSize: '0.75rem', color: '#666', marginLeft: '4px' }}>
            {currentPage} / {Math.ceil(totalCount / pageSize)} 페이지
          </span>
        </div>
      )}
    </div>
  );
}

/* ====== Product Card Component ====== */

interface ProductCardProps {
  product: SambaCollectedProduct;
  idx: number;
  policies: SambaPolicy[];
  accounts: SambaMarketAccount[];
  nameRules: SambaNameRule[];
  selectedIds: Set<string>;
  filterNameMap: Record<string, string>;
  deletionWords: string[];
  onCheckboxToggle: (id: string, checked: boolean) => void;
  onDelete: (id: string) => void;
  onPolicyChange: (productId: string, policyId: string) => void;
  onToggleMarket: (productId: string, marketId: string) => void;
  onEnrich: (productId: string) => void;
  onLockToggle: (productId: string, field: 'lock_delete' | 'lock_stock', value: boolean) => void;
  onTagUpdate: (productId: string, tags: string[]) => void;
  onMarketDelete: (productId: string) => void;
  onAddTaskLog: (msg: string) => void;
  onProductUpdate: (productId: string, data: Partial<SambaCollectedProduct>) => void;
  logMessage?: string;
  catMappingMap: Map<string, Record<string, string>>;
  compact?: boolean;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

function getSourceUrl(sourceSite: string, siteProductId: string | undefined): string {
  if (!siteProductId) return ''
  if (sourceSite === 'MUSINSA') return `https://www.musinsa.com/products/${siteProductId}`
  if (sourceSite === 'KREAM') return `https://kream.co.kr/products/${siteProductId}`
  return ''
}

// 상품명 조합 적용 (name_composition 태그 기반)
function composeProductName(
  product: SambaCollectedProduct,
  nameRule: SambaNameRule | undefined,
): string {
  if (!nameRule?.name_composition?.length) return product.name
  const seoKws = product.seo_keywords || []
  const tagMap: Record<string, string> = {
    '{상품명}': product.name || '',
    '{브랜드명}': product.brand || '',
    '{모델명}': product.model_no || '',
    '{사이트명}': product.source_site || '',
    '{상품번호}': product.site_product_id || '',
    '{검색키워드}': seoKws.slice(0, 3).join(' '),
  }
  // 조합 태그 순서대로 값 치환
  let composed = nameRule.name_composition
    .map(tag => tagMap[tag] ?? tag)
    .filter(v => v.trim() !== '')
    .join(' ')
  // 치환어 적용
  if (nameRule.replacements?.length) {
    for (const r of nameRule.replacements) {
      if (!r.from) continue
      const flags = r.caseInsensitive ? 'gi' : 'g'
      composed = composed.replace(new RegExp(r.from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), flags), r.to || '')
    }
  }
  // 중복 제거
  if (nameRule.dedup_enabled) {
    const words = composed.split(/\s+/)
    const seen = new Set<string>()
    const deduped: string[] = []
    for (const w of words) {
      const lower = w.toLowerCase()
      if (!seen.has(lower)) {
        seen.add(lower)
        deduped.push(w)
      }
    }
    composed = deduped.join(' ')
  }
  // prefix/suffix 적용
  if (nameRule.prefix) composed = `${nameRule.prefix} ${composed}`
  if (nameRule.suffix) composed = `${composed} ${nameRule.suffix}`
  return composed.trim()
}

// 삭제어 취소선이 적용된 등록 상품명 렌더링
function renderRegisteredName(name: string, deletionWords: string[]): React.ReactNode {
  if (!deletionWords.length) return name
  // 삭제어를 정규식으로 결합 (특수문자 이스케이프)
  const escaped = deletionWords.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const regex = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = name.split(regex)
  if (parts.length === 1) return name
  return parts.map((part, i) => {
    const isMatch = deletionWords.some(w => w.toLowerCase() === part.toLowerCase())
    if (isMatch) {
      return <span key={i} style={{ textDecoration: 'line-through', textDecorationColor: '#FF6B6B', color: '#666' }}>{part}</span>
    }
    return <span key={i}>{part}</span>
  })
}

function ProductCard({
  product: p, idx, policies, accounts, nameRules, selectedIds, filterNameMap, deletionWords,
  onCheckboxToggle, onDelete, onPolicyChange, onToggleMarket, onEnrich, onLockToggle, onTagUpdate, onMarketDelete, onAddTaskLog, onProductUpdate, logMessage,
  catMappingMap, compact, expanded, onToggleExpand,
}: ProductCardProps) {
  const [showPriceHistoryModal, setShowPriceHistoryModal] = useState(false)
  const [showImageModal, setShowImageModal] = useState(false)
  const [zoomImg, setZoomImg] = useState<string | null>(null)
  // 알림/확인 모달 (alert/confirm 대체)
  const [cardAlert, setCardAlert] = useState<{ msg: string; type?: 'success' | 'error' } | null>(null)
  const [cardConfirm, setCardConfirm] = useState<{ msg: string; onOk: () => void } | null>(null)
  const [imageTab, setImageTab] = useState<'main' | 'extra' | 'detail' | 'video'>('main')
  const [productImages, setProductImages] = useState<string[]>(p.images || [])
  const [detailImgList, setDetailImgList] = useState<string[]>(
    (p.detail_images && p.detail_images.length > 0)
      ? [...p.detail_images]
      : (p.detail_html || '').match(/src=["']([^"']+)["']/gi)
          ?.map((m: string) => m.replace(/src=["']/i, '').replace(/["']$/, '')) || []
  )
  // 원가: best_benefit_price(최대혜택가) > sale_price > original_price 순 우선
  const cost = p.cost || p.sale_price || p.original_price || 0;
  const policy = policies.find((pol) => pol.id === p.applied_policy_id);
  const pricing = (policy?.pricing || {}) as Record<string, number>;
  const marginRate = pricing.marginRate || 15;
  const extraCharge = pricing.extraCharge || 0;
  const shippingCost = pricing.shippingCost || 0;
  const feeRate = pricing.feeRate || 0;
  const minMarginAmount = pricing.minMarginAmount || 0;

  // Market price calculation matching original formula
  let base = cost;
  if (shippingCost > 0) base += shippingCost;
  // 마진 계산: 마진율 기반 마진이 최소마진보다 작으면 최소마진 적용
  let calcMarginAmt = Math.round(cost * marginRate / 100);
  if (minMarginAmount > 0 && calcMarginAmt < minMarginAmount) calcMarginAmt = minMarginAmount;
  let marketPrice = cost + calcMarginAmt + shippingCost;
  if (feeRate > 0 && marketPrice > 0) marketPrice = Math.ceil(marketPrice / (1 - feeRate / 100));
  if (extraCharge > 0) marketPrice += extraCharge;
  const profit = marketPrice - cost;

  const isActive = p.status === "registered" || p.status === "saved";
  const statusColor = isActive ? "#51CF66" : "#888";
  const statusBg = isActive ? "rgba(81,207,102,0.12)" : "rgba(100,100,100,0.15)";
  const statusText = p.status === "registered" ? "등록됨" : p.status === "saved" ? "저장됨" : "";

  // 날짜 포맷: YYYY-MM-DD HH:MM
  const fmtDate = (dt: string | undefined) => {
    if (!dt) return "-"
    const d = new Date(dt)
    if (isNaN(d.getTime())) return dt.slice(0, 10)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  const regDate = fmtDate(p.created_at)
  const updatedDate = fmtDate(p.updated_at)
  const no = String(idx + 1).padStart(6, "0");

  // 각 요소별 실제 금액 계산
  const usedMinMargin = minMarginAmount > 0 && Math.round(cost * marginRate / 100) < minMarginAmount
  const marginAmount = calcMarginAmt
  const feeAmount = feeRate > 0 && marketPrice > 0 ? Math.round(marketPrice * feeRate / 100) : 0

  // 계산방식 문자열: 모든 항목 표시 (0원 포함)
  const calcParts: string[] = [`원가 ${fmt(cost)}`]
  calcParts.push(usedMinMargin ? `마진 ${fmt(marginAmount)}(최소마진)` : `마진 ${fmt(marginAmount)}(${marginRate}%)`)
  calcParts.push(`배송비 ${fmt(shippingCost)}`)
  calcParts.push(`추가요금 ${fmt(extraCharge)}`)
  calcParts.push(`수수료 ${fmt(feeAmount)}(${feeRate}%)`)
  const calcStr = `₩${fmt(marketPrice)} = ${calcParts.join(' + ')}`

  // 마켓별 개별 가격 계산 (연결된 마켓정책 기반)
  // 마켓정책 값이 0이면 공통 정책값 사용 (0 = 미설정)
  const mp = (policy?.market_policies || {}) as Record<string, { accountId?: string; feeRate?: number; shippingCost?: number; marginRate?: number; brand?: string }>
  const marketPriceList = Object.entries(mp)
    .filter(([, v]) => v.accountId)
    .map(([marketName, v]) => {
      const mMargin = v.marginRate || marginRate
      const mShipping = (v.shippingCost ?? shippingCost) || shippingCost
      const mFee = v.feeRate || 0
      const mExtra = extraCharge
      // 마진 계산: 최소마진 적용
      let mMarginAmt = Math.round(cost * mMargin / 100)
      const mUsedMin = minMarginAmount > 0 && mMarginAmt < minMarginAmount
      if (mUsedMin) mMarginAmt = minMarginAmount
      let mPrice = cost + mMarginAmt + mShipping
      if (mFee > 0 && mPrice > 0) mPrice = Math.ceil(mPrice / (1 - mFee / 100))
      if (mExtra > 0) mPrice += mExtra
      const mFeeAmt = mFee > 0 && mPrice > 0 ? Math.round(mPrice * mFee / 100) : 0
      const parts: string[] = [`원가 ${fmt(cost)}`]
      parts.push(mUsedMin ? `마진 ${fmt(mMarginAmt)}(최소마진)` : `마진 ${fmt(mMarginAmt)}(${mMargin}%)`)
      parts.push(`배송비 ${fmt(mShipping)}`)
      parts.push(`추가요금 ${fmt(mExtra)}`)
      parts.push(`수수료 ${fmt(mFeeAmt)}(${mFee}%)`)
      return { marketName, price: mPrice, calcStr: `₩${fmt(mPrice)} = ${parts.join(' + ')}` }
    })

  const marketEnabled = (p.market_enabled || {}) as Record<string, boolean>;

  // 상품의 카테고리 매핑 조회
  const productCatMapping = useMemo(() => {
    const site = p.source_site || ''
    const cats = [p.category1, p.category2, p.category3, p.category4].filter(Boolean) as string[]
    if (cats.length === 0 && p.category) {
      cats.push(...p.category.split('>').map(c => c.trim()).filter(Boolean))
    }
    if (!site || cats.length === 0) return {}
    const leafPath = cats.join(' > ')
    return catMappingMap.get(`${site}::${leafPath}`) || {}
  }, [p.source_site, p.category, p.category1, p.category2, p.category3, p.category4, catMappingMap])

  // 등록된 계정 기반 마켓 정보 (등록한 마켓만 표시용)
  const regAccIds = p.registered_accounts ?? []
  const marketProductNos = p.market_product_nos || {}
  const registeredMarkets = useMemo(() => {
    return regAccIds
      .map(aid => accounts.find(a => a.id === aid))
      .filter((a): a is SambaMarketAccount => !!a)
      .map(acc => {
        const market = MARKETS.find(m => m.id === acc.market_type)
        // channelProductNo(구매페이지용) 우선, 없으면 originProductNo 사용
        const productNo = marketProductNos[acc.id] || marketProductNos[`${acc.id}_origin`] || ''
        // 마켓 상품번호가 있으면 구매페이지 직접 링크, 없으면 검색 URL
        const extras = (acc.additional_fields || {}) as Record<string, string>
        const url = buildMarketProductUrl(acc.market_type, acc.seller_id || '', productNo, extras.storeSlug)
          || (market?.searchUrl ? market.searchUrl + encodeURIComponent(p.name) : market?.url || '')
        return {
          marketId: acc.market_type,
          label: `${acc.market_name}(${acc.seller_id || acc.account_label || acc.business_name || '-'})`,
          url,
          accId: acc.id,
        }
      })
  }, [regAccIds, accounts, p.name, marketProductNos]) // eslint-disable-line react-hooks/exhaustive-deps

  const tdLabel: React.CSSProperties = { padding: "6px 8px", color: "#555", fontSize: "0.75rem", whiteSpace: "nowrap", verticalAlign: "middle" };
  const tdVal: React.CSSProperties = { padding: "6px 8px", verticalAlign: "middle" };

  return (
    <div style={{
      background: "rgba(22,22,22,0.9)", border: "1px solid #2A2A2A", borderRadius: "10px",
      overflow: "hidden",
    }}>
      {/* 업데이트 로그 바 */}
      {logMessage && (
        <div style={{
          padding: '6px 14px', fontSize: '0.75rem', color: '#FFB84D',
          background: 'rgba(255,140,0,0.08)', borderBottom: '1px solid rgba(255,140,0,0.15)',
          display: 'flex', alignItems: 'center', gap: '6px',
        }}>
          <span style={{ opacity: 0.7 }}>&#9654;</span>
          {logMessage}
        </div>
      )}
      {/* 가격/재고 이력 모달 */}
      {showPriceHistoryModal && (() => {
        const history = p.price_history || []
        const isKream = p.source_site === 'KREAM'
        // 원가(cost) 기준으로 최저/최고가 계산
        const costPrices = history.map(h => h.cost || h.sale_price).filter(Boolean)
        const currentPrice = costPrices[0] || cost || p.sale_price || 0
        const minPrice = costPrices.length ? Math.min(...costPrices) : 0
        const maxPrice = costPrices.length ? Math.max(...costPrices) : 0
        const minEntry = history.find(h => (h.cost || h.sale_price) === minPrice)
        const maxEntry = history.find(h => (h.cost || h.sale_price) === maxPrice)
        // KREAM 빠른배송/일반배송 현재가
        const kreamFastMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_fast_min as number || 0 : 0
        const kreamGeneralMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_general_min as number || 0 : 0
        const fmtDate = (d: string) => new Date(d).toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        const fmtShortDate = (d: string) => new Date(d).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

        return (
          <div
            style={{
              position: "fixed", inset: 0, zIndex: 9999,
              background: "rgba(0,0,0,0.75)", display: "flex",
              alignItems: "center", justifyContent: "center",
            }}
            onClick={() => setShowPriceHistoryModal(false)}
          >
            <div
              style={{
                background: "#1A1A1A", border: "1px solid #2D2D2D", borderRadius: "12px",
                width: "min(700px, 95vw)", maxHeight: "85vh", overflow: "hidden",
                display: "flex", flexDirection: "column",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* 헤더 */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 20px", borderBottom: "1px solid #2D2D2D",
              }}>
                <h3 style={{ margin: 0, fontSize: "0.9rem", fontWeight: 600, color: "#E5E5E5" }}>
                  가격 / 재고 이력
                </h3>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span style={{ fontSize: "0.75rem", color: "#666" }}>{history.length}건 기록</span>
                  <button
                    onClick={() => setShowPriceHistoryModal(false)}
                    style={{ background: "transparent", border: "none", color: "#888", fontSize: "1.2rem", cursor: "pointer" }}
                  >✕</button>
                </div>
              </div>

              {/* 상품 정보 + 요약 */}
              <div style={{ padding: "12px 20px", borderBottom: "1px solid #2D2D2D" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
                  <span style={{
                    fontSize: "0.65rem", padding: "2px 6px", borderRadius: "3px",
                    background: "rgba(255,140,0,0.15)", color: "#FF8C00", fontWeight: 600,
                  }}>{p.source_site}</span>
                  <span style={{ fontSize: "0.75rem", color: "#999" }}>{p.name}</span>
                </div>
                {costPrices.length > 0 && (
                  <div style={{ display: "flex", gap: "20px", fontSize: "0.78rem", flexWrap: "wrap" }}>
                    {isKream && kreamFastMin > 0 && (
                      <div>
                        <span style={{ color: "#666" }}>빠른배송 </span>
                        <span style={{ color: "#FF8C00", fontWeight: 600 }}>₩ {kreamFastMin.toLocaleString()}</span>
                      </div>
                    )}
                    {isKream && kreamGeneralMin > 0 && (
                      <div>
                        <span style={{ color: "#666" }}>일반배송 </span>
                        <span style={{ color: "#E5E5E5", fontWeight: 600 }}>₩ {kreamGeneralMin.toLocaleString()}</span>
                      </div>
                    )}
                    {!isKream && (
                      <div>
                        <span style={{ color: "#666" }}>현재가 </span>
                        <span style={{ color: "#E5E5E5", fontWeight: 600 }}>₩ {currentPrice.toLocaleString()}</span>
                      </div>
                    )}
                    <div>
                      <span style={{ color: "#666" }}>최저가 </span>
                      <span style={{ color: "#51CF66", fontWeight: 600 }}>₩ {minPrice.toLocaleString()}</span>
                      {minEntry && <span style={{ color: "#555", fontSize: "0.68rem" }}> ({fmtShortDate(minEntry.date)})</span>}
                    </div>
                    <div>
                      <span style={{ color: "#666" }}>최고가 </span>
                      <span style={{ color: "#FF6B6B", fontWeight: 600 }}>₩ {maxPrice.toLocaleString()}</span>
                      {maxEntry && <span style={{ color: "#555", fontSize: "0.68rem" }}> ({fmtShortDate(maxEntry.date)})</span>}
                    </div>
                  </div>
                )}
              </div>

              {/* 이력 테이블 */}
              <div style={{ overflowY: "auto", padding: "0" }}>
                {history.length === 0 ? (
                  <div style={{ padding: "2rem", textAlign: "center", color: "#555", fontSize: "0.85rem" }}>
                    가격 변동 이력 없음<br />
                    <span style={{ fontSize: "0.75rem", color: "#444" }}>업데이트 시 이력이 기록됩니다</span>
                  </div>
                ) : (
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #2D2D2D" }}>
                        <th style={{ padding: "8px 16px", textAlign: "left", color: "#888", fontWeight: 500 }}>날짜</th>
                        {isKream ? (
                          <>
                            <th style={{ padding: "8px 16px", textAlign: "right", color: "#888", fontWeight: 500 }}>빠른배송(₩)</th>
                            <th style={{ padding: "8px 16px", textAlign: "right", color: "#888", fontWeight: 500 }}>일반배송(₩)</th>
                          </>
                        ) : (
                          <th style={{ padding: "8px 16px", textAlign: "right", color: "#888", fontWeight: 500 }}>원가(₩)</th>
                        )}
                        <th style={{ padding: "8px 16px", textAlign: "right", color: "#888", fontWeight: 500 }}>재고(수량/O/X)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h, i) => {
                        const opts = (h.options || []) as Array<{ name?: string; price?: number; stock?: number; isSoldOut?: boolean }>
                        const inStockCount = opts.filter(o => !o.isSoldOut && (o.stock === undefined || o.stock > 0)).length
                        return (
                          <React.Fragment key={i}>
                            {/* 메인 행: 날짜 + 가격 + 옵션 요약 */}
                            <tr style={{ borderTop: i > 0 ? "1px solid #2D2D2D" : "none", background: "rgba(255,255,255,0.02)" }}>
                              <td style={{ padding: "8px 16px", color: "#C5C5C5", fontWeight: 600, fontSize: "0.78rem" }}>
                                {fmtDate(h.date)}
                              </td>
                              {isKream ? (
                                <>
                                  <td style={{ padding: "8px 16px", textAlign: "right", color: "#FF8C00", fontWeight: 600 }}>
                                    {(h as Record<string, unknown>).kream_fast_min ? `₩ ${((h as Record<string, unknown>).kream_fast_min as number).toLocaleString()}` : '-'}
                                  </td>
                                  <td style={{ padding: "8px 16px", textAlign: "right", color: "#FFB84D", fontWeight: 600 }}>
                                    {(h as Record<string, unknown>).kream_general_min ? `₩ ${((h as Record<string, unknown>).kream_general_min as number).toLocaleString()}` : '-'}
                                  </td>
                                </>
                              ) : (
                                <td style={{ padding: "8px 16px", textAlign: "right", color: "#FFB84D", fontWeight: 600 }}>
                                  ₩ {(h.cost || h.sale_price)?.toLocaleString() || '-'}
                                </td>
                              )}
                              <td style={{ padding: "8px 16px", textAlign: "right", color: "#888" }}>
                                {opts.length > 0 ? `${opts.length}개 옵션` : '-'}
                              </td>
                            </tr>
                            {/* 옵션 상세 행 */}
                            {opts.map((opt, oi) => {
                              const kOpt = opt as Record<string, unknown>
                              const soldOut = opt.isSoldOut || (opt.stock !== undefined && opt.stock <= 0)
                              const stockLabel = soldOut
                                ? '품절'
                                : opt.stock !== undefined
                                  ? `${opt.stock}개`
                                  : 'O'
                              return (
                                <tr key={oi} style={{ borderTop: "1px solid #1A1A1A" }}>
                                  <td style={{ padding: "4px 16px 4px 32px", color: "#666", fontSize: "0.73rem" }}>
                                    ㄴ {opt.name || `옵션${oi + 1}`}
                                  </td>
                                  {isKream ? (
                                    <>
                                      <td style={{ padding: "4px 16px", textAlign: "right", color: "#888", fontSize: "0.73rem" }}>
                                        {(kOpt.kreamFastPrice as number) > 0 ? `₩ ${(kOpt.kreamFastPrice as number).toLocaleString()}` : '-'}
                                      </td>
                                      <td style={{ padding: "4px 16px", textAlign: "right", color: "#888", fontSize: "0.73rem" }}>
                                        {(kOpt.kreamGeneralPrice as number) > 0 ? `₩ ${(kOpt.kreamGeneralPrice as number).toLocaleString()}` : '-'}
                                      </td>
                                    </>
                                  ) : (
                                    <td style={{ padding: "4px 16px", textAlign: "right", color: "#888", fontSize: "0.73rem" }}>
                                      ₩ {(h.cost || h.sale_price)?.toLocaleString()}
                                    </td>
                                  )}
                                  <td style={{
                                    padding: "4px 16px", textAlign: "right", fontSize: "0.73rem", fontWeight: 600,
                                    color: soldOut ? '#FF6B6B' : '#51CF66',
                                  }}>
                                    {stockLabel}
                                  </td>
                                </tr>
                              )
                            })}
                          </React.Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {/* 이미지 변경 모달 */}
      {showImageModal && (() => {
        // 대표이미지: 첫번째, 추가이미지: 나머지
        const mainImg = productImages[0] || ''
        const extraImgs = productImages.slice(1)
        // 상세페이지 이미지: detail_images 필드 우선, 없으면 detail_html에서 추출
        const detailImgs = detailImgList
            ?.map((url: string) => url.startsWith('//') ? `https:${url}` : url) || []

        const tabStyle = (active: boolean) => ({
          padding: '8px 16px', fontSize: '0.8rem', fontWeight: active ? 600 : 400,
          color: active ? '#FF8C00' : '#888', cursor: 'pointer',
          border: 'none', borderBottom: active ? '2px solid #FF8C00' : '2px solid transparent',
          background: 'transparent',
        })

        // 이미지 행 렌더
        const renderImageRow = (img: string, i: number, list: string[], setList: (imgs: string[]) => void, label?: string) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: '12px', padding: '8px', borderRadius: '8px',
            background: label ? 'rgba(255,140,0,0.06)' : 'rgba(30,30,30,0.5)',
            border: label ? '1px solid rgba(255,140,0,0.2)' : '1px solid #2D2D2D',
          }}>
            <img src={img} alt="" onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
              onClick={() => setZoomImg(img)}
              style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', flexShrink: 0, cursor: 'pointer' }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              {label && <span style={{ fontSize: '0.7rem', color: '#FF8C00', fontWeight: 600 }}>{label}</span>}
              <p style={{ margin: 0, fontSize: '0.68rem', color: '#555', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{img}</p>
            </div>
            <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
              {i > 0 && <button onClick={() => { const a = [...list]; [a[i-1], a[i]] = [a[i], a[i-1]]; setList(a) }}
                style={{ padding: '3px 8px', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer', border: '1px solid #2D2D2D', background: 'transparent', color: '#888' }}>▲</button>}
              {i < list.length - 1 && <button onClick={() => { const a = [...list]; [a[i+1], a[i]] = [a[i], a[i+1]]; setList(a) }}
                style={{ padding: '3px 8px', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer', border: '1px solid #2D2D2D', background: 'transparent', color: '#888' }}>▼</button>}
              <button onClick={() => {
                setCardConfirm({
                  msg: '이 이미지를 모든 상품에서 삭제하시겠습니까?',
                  onOk: async () => {
                    setCardConfirm(null)
                    try {
                      const field = list === detailImgList ? 'detail_images' : 'images'
                      const res = await collectorApi.bulkRemoveImage(img, field)
                      setList(list.filter((_, j) => j !== i))
                      setCardAlert({ msg: `${res.removed}개 상품에서 삭제 완료`, type: 'success' })
                    } catch (e) { setCardAlert({ msg: '추적삭제 실패: ' + (e instanceof Error ? e.message : String(e)), type: 'error' }) }
                  },
                })
              }}
                style={{ padding: '3px 8px', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer', border: '1px solid rgba(168,85,247,0.3)', background: 'rgba(168,85,247,0.08)', color: '#A855F7' }}>추적삭제</button>
              <button onClick={() => setList(list.filter((_, j) => j !== i))}
                style={{ padding: '3px 8px', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer', border: '1px solid rgba(255,107,107,0.3)', background: 'rgba(255,107,107,0.08)', color: '#FF6B6B' }}>삭제</button>
            </div>
          </div>
        )

        return (
          <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => setShowImageModal(false)}>
            <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', width: 'min(750px, 95vw)', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
              onClick={e => e.stopPropagation()}>
              {/* 헤더 + 탭 */}
              <div style={{ padding: '14px 20px 0', borderBottom: '1px solid #2D2D2D' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5' }}>이미지 변경</h3>
                    <p style={{ margin: 0, fontSize: '0.72rem', color: '#666' }}>{p.name?.slice(0, 50)}</p>
                  </div>
                  <button onClick={() => setShowImageModal(false)} style={{ background: 'transparent', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer' }}>✕</button>
                </div>
                <div style={{ display: 'flex', gap: '0' }}>
                  <button onClick={() => setImageTab('main')} style={tabStyle(imageTab === 'main')}>대표 이미지변경</button>
                  <button onClick={() => setImageTab('extra')} style={tabStyle(imageTab === 'extra')}>추가이미지 변경</button>
                  <button onClick={() => setImageTab('detail')} style={tabStyle(imageTab === 'detail')}>상세페이지 이미지</button>
                  <button onClick={() => setImageTab('video')} style={tabStyle(imageTab === 'video')}>영상</button>
                </div>
              </div>

              {/* 탭 내용 */}
              <div style={{ overflowY: 'auto', padding: '16px 20px', flex: 1 }}>
                {imageTab === 'main' && (
                  <div>
                    <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '12px' }}>
                      ※ 대표이미지를 변경하시면 모든 마켓의 대표이미지가 변경됩니다.
                    </p>
                    {mainImg ? (
                      <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-start' }}>
                        <div>
                          <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '6px' }}>[현재 대표이미지]</p>
                          <img src={mainImg} alt="대표이미지" onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                            onClick={() => setZoomImg(mainImg)}
                            style={{ width: 200, height: 200, objectFit: 'cover', borderRadius: '8px', border: '1px solid #2D2D2D', cursor: 'pointer' }} />
                          <p style={{ margin: '6px 0 0', fontSize: '0.65rem', color: '#555', wordBreak: 'break-all' }}>{mainImg}</p>
                        </div>
                        <div style={{ flex: 1 }}>
                          <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '6px' }}>이미지 URL 변경</p>
                          <div style={{ display: 'flex', gap: '6px' }}>
                            <input type="text" placeholder="http:// 를 포함한 이미지 경로" defaultValue=""
                              id="main-image-url-input"
                              style={{ flex: 1, fontSize: '0.78rem', padding: '6px 10px', background: '#1E1E1E', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px' }} />
                            <button onClick={() => {
                              const input = document.getElementById('main-image-url-input') as HTMLInputElement
                              if (input?.value.trim()) {
                                const newImgs = [input.value.trim(), ...productImages.slice(1)]
                                setProductImages(newImgs)
                                collectorApi.updateProduct(p.id, { images: newImgs } as Partial<SambaCollectedProduct>).then(() => {
                                  onProductUpdate(p.id, { images: newImgs })
                                }).catch(() => {})
                                input.value = ''
                              }
                            }} style={{ padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', border: '1px solid #FF8C00', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', cursor: 'pointer', whiteSpace: 'nowrap' }}>변경완료</button>
                          </div>
                          <button onClick={() => {
                            // 대표이미지 삭제 → 추가이미지[0]이 대표로 승격
                            const remaining = productImages.slice(1)
                            const newImgs = remaining.length > 0 ? remaining : []
                            setProductImages(newImgs)
                            collectorApi.updateProduct(p.id, { images: newImgs } as Partial<SambaCollectedProduct>).then(() => {
                              onProductUpdate(p.id, { images: newImgs })
                            }).catch(() => {})
                          }} style={{
                            marginTop: '8px', padding: '5px 14px', fontSize: '0.72rem', borderRadius: '6px',
                            border: '1px solid rgba(255,107,107,0.4)', background: 'rgba(255,107,107,0.08)',
                            color: '#FF6B6B', cursor: 'pointer', whiteSpace: 'nowrap',
                          }}>대표이미지 삭제</button>
                        </div>
                      </div>
                    ) : (
                      <div style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>대표이미지 없음</div>
                    )}
                  </div>
                )}

                {imageTab === 'extra' && (
                  <div>
                    <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '12px' }}>
                      ※ 추가이미지 순서를 변경하거나 삭제할 수 있습니다.
                    </p>
                    {extraImgs.length === 0 ? (
                      <div style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>추가이미지 없음</div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {extraImgs.map((img, i) => renderImageRow(img, i, extraImgs, async (newList) => {
                          const newImgs = [mainImg, ...newList]
                          try {
                            const updateData: Partial<SambaCollectedProduct> = { images: newImgs }
                            if (!(p.tags || []).includes('__img_edited__')) {
                              updateData.tags = [...(p.tags || []), '__img_edited__']
                            }
                            await collectorApi.updateProduct(p.id, updateData)
                            setProductImages(newImgs)
                            onProductUpdate(p.id, updateData)
                          } catch (e) {
                            console.error('[이미지삭제] 저장 실패:', e)
                            setCardAlert({ msg: '이미지 변경 저장 실패: ' + (e instanceof Error ? e.message : String(e)), type: 'error' })
                          }
                        }, i === 0 ? `추가 1` : undefined))}
                      </div>
                    )}
                    {/* URL로 추가 */}
                    <div style={{ display: 'flex', gap: '6px', marginTop: '12px' }}>
                      <input type="text" placeholder="추가할 이미지 URL" id="extra-image-url-input"
                        style={{ flex: 1, fontSize: '0.78rem', padding: '6px 10px', background: '#1E1E1E', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px' }} />
                      <button onClick={() => {
                        const input = document.getElementById('extra-image-url-input') as HTMLInputElement
                        if (input?.value.trim()) {
                          const newImgs = [...productImages, input.value.trim()]
                          setProductImages(newImgs)
                          collectorApi.updateProduct(p.id, { images: newImgs } as Partial<SambaCollectedProduct>).then(() => {
                            onProductUpdate(p.id, { images: newImgs })
                          }).catch(() => {})
                          input.value = ''
                        }
                      }} style={{ padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', border: '1px solid #3D3D3D', background: 'rgba(255,255,255,0.05)', color: '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap' }}>추가</button>
                    </div>
                  </div>
                )}

                {imageTab === 'detail' && (
                  <div>
                    <p style={{ fontSize: '0.72rem', color: '#888', marginBottom: '12px' }}>
                      ※ 상세페이지에 포함된 이미지입니다. ({detailImgs.length}개) — 클릭하여 삭제
                    </p>
                    {detailImgs.length === 0 ? (
                      <div style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>상세페이지 이미지 없음</div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {detailImgs.map((img, i) => renderImageRow(img, i, detailImgs, async (newList) => {
                          try {
                            const updateData: Partial<SambaCollectedProduct> = { detail_images: newList }
                            if (!(p.tags || []).includes('__img_edited__')) {
                              updateData.tags = [...(p.tags || []), '__img_edited__']
                            }
                            await collectorApi.updateProduct(p.id, updateData)
                            setDetailImgList(newList)
                            onProductUpdate(p.id, updateData)
                          } catch (e) {
                            console.error('[상세이미지삭제] 저장 실패:', e)
                            setCardAlert({ msg: '상세이미지 변경 저장 실패: ' + (e instanceof Error ? e.message : String(e)), type: 'error' })
                          }
                        }))}
                      </div>
                    )}
                  </div>
                )}

                {imageTab === 'video' && (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '20px 0', gap: '12px' }}>
                    {p.video_url ? (
                      <>
                        <video
                          src={p.video_url}
                          controls
                          style={{ width: '100%', maxWidth: '480px', borderRadius: '8px', border: '1px solid #2D2D2D' }}
                        />
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <a
                            href={p.video_url}
                            download={`${p.site_product_id || p.id}_video.mp4`}
                            style={{
                              fontSize: '0.78rem', padding: '6px 16px', borderRadius: '6px',
                              color: '#4C9AFF', border: '1px solid rgba(76,154,255,0.4)',
                              background: 'rgba(76,154,255,0.08)', textDecoration: 'none', cursor: 'pointer',
                            }}>다운로드</a>
                        </div>
                      </>
                    ) : (
                      <p style={{ fontSize: '0.8rem', color: '#666' }}>생성된 영상이 없습니다. 상단 영상생성 버튼으로 생성해주세요.</p>
                    )}
                  </div>
                )}

              </div>
            </div>

            {/* 이미지 확대 팝업 */}
            {zoomImg && (
              <div
                onClick={() => setZoomImg(null)}
                style={{
                  position: 'fixed', inset: 0, zIndex: 10000,
                  background: 'rgba(0,0,0,0.85)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer',
                }}
              >
                <img
                  src={zoomImg}
                  alt=""
                  onClick={e => e.stopPropagation()}
                  style={{
                    maxWidth: '90vw', maxHeight: '90vh',
                    objectFit: 'contain', borderRadius: '8px',
                    cursor: 'default',
                  }}
                />
                <button
                  onClick={() => setZoomImg(null)}
                  style={{
                    position: 'absolute', top: '20px', right: '20px',
                    background: 'rgba(0,0,0,0.5)', border: '1px solid #555',
                    color: '#ccc', fontSize: '1.2rem', padding: '4px 10px',
                    borderRadius: '6px', cursor: 'pointer',
                  }}
                >✕</button>
              </div>
            )}
          </div>
        )
      })()}

      {/* Card header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "7px 14px", background: "rgba(15,15,15,0.8)", borderBottom: "1px solid #222",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "0.75rem", color: "#666" }}>
          {compact && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggleExpand?.() }}
              style={{
                background: "none", border: "none", color: expanded ? "#FF8C00" : "#666",
                fontSize: "0.85rem", cursor: "pointer", padding: "0 2px", lineHeight: 1,
              }}
            >{expanded ? "−" : "+"}</button>
          )}
          <input
            type="checkbox"
            checked={selectedIds.has(p.id)}
            onChange={(e) => onCheckboxToggle(p.id, e.target.checked)}
            style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
          />
          <span style={{ color: "#FFFFFF", fontWeight: 600 }}>{p.site_product_id || no}</span>
          {p.source_site && (
            <span style={{
              fontSize: "0.7rem", color: "#FF8C00", background: "rgba(255,140,0,0.1)",
              border: "1px solid rgba(255,140,0,0.25)", borderRadius: "4px",
              padding: "2px 8px", whiteSpace: "nowrap",
            }}>{p.source_site}</span>
          )}
          <span>수집 <span style={{ color: "#888" }}>{regDate}</span></span>
          {p.updated_at && <span>최신화 <span style={{ color: "#888" }}>{updatedDate}</span></span>}
          {isActive && (
            <span style={{
              padding: "2px 10px", borderRadius: "4px", fontSize: "0.72rem", fontWeight: 500,
              background: statusBg, color: statusColor,
            }}>
              {statusText}
            </span>
          )}
          {p.sale_status === 'preorder' && (
            <span style={{
              padding: "2px 8px", borderRadius: "4px", fontSize: "0.72rem", fontWeight: 500,
              background: "rgba(100,130,255,0.12)", color: "#6B8AFF",
              border: "1px solid rgba(100,130,255,0.25)",
            }}>판매예정</span>
          )}
          {p.sale_status === 'sold_out' && (
            <span style={{
              padding: "2px 8px", borderRadius: "4px", fontSize: "0.72rem", fontWeight: 500,
              background: "rgba(255,107,107,0.12)", color: "#FF6B6B",
              border: "1px solid rgba(255,107,107,0.25)",
            }}>품절</span>
          )}
          {!(p.sale_status) && p.is_sold_out && (
            <span style={{
              padding: "2px 8px", borderRadius: "4px", fontSize: "0.72rem", fontWeight: 500,
              background: "rgba(255,107,107,0.12)", color: "#FF6B6B",
              border: "1px solid rgba(255,107,107,0.25)",
            }}>품절</span>
          )}
          {p.group_key && !p.group_product_no && (
            <span style={{
              padding: '2px 8px', borderRadius: '4px', fontSize: '0.72rem', fontWeight: 500,
              background: 'rgba(81,207,102,0.15)', color: '#51CF66',
              border: '1px solid rgba(81,207,102,0.25)',
            }}>스스그룹</span>
          )}
          {p.group_product_no && (
            <span style={{
              padding: '2px 8px', borderRadius: '4px', fontSize: '0.72rem', fontWeight: 500,
              background: 'rgba(76,154,255,0.15)', color: '#4C9AFF',
              border: '1px solid rgba(76,154,255,0.25)',
            }}>스스그룹등록</span>
          )}
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={p.lock_stock || false}
              onChange={(e) => onLockToggle(p.id, 'lock_stock', e.target.checked)}
              style={{ accentColor: "#51CF66", width: "12px", height: "12px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "0.7rem", color: "#888" }}>재고잠금</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={p.lock_delete || false}
              onChange={(e) => onLockToggle(p.id, 'lock_delete', e.target.checked)}
              style={{ accentColor: "#FF8C00", width: "12px", height: "12px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "0.7rem", color: "#888" }}>삭제잠금</span>
          </label>
          <button style={{
            fontSize: "0.7rem", padding: "3px 10px",
            border: "1px solid rgba(255,140,0,0.3)", borderRadius: "5px",
            color: "#FF8C00", background: "rgba(255,140,0,0.08)", cursor: "pointer",
          }}>수정</button>
          <button
            onClick={() => onDelete(p.id)}
            style={{
              fontSize: "0.7rem", padding: "3px 10px",
              border: "1px solid rgba(255,107,107,0.3)", borderRadius: "5px",
              color: "#FF6B6B", background: "rgba(255,107,107,0.08)", cursor: "pointer",
            }}
          >삭제</button>
        </div>
      </div>

      {/* Card body */}
      {(compact && !expanded) ? (
        /* 간단보기: 원 상품명 + 등록 상품명 + 브랜드 + 원가 한 줄 */
        <div style={{ padding: "8px 14px", display: "flex", gap: "10px", alignItems: "center", fontSize: "0.78rem" }}>
          <div onClick={() => { setProductImages(p.images || []); setShowImageModal(true) }} style={{ cursor: "pointer", flexShrink: 0 }}>
            <ProductImage src={p.images?.[0]} name={p.name} size={50} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ color: "#FFFFFF", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{p.name}</span>
              <button onClick={(e) => { e.stopPropagation(); setShowPriceHistoryModal(true) }}
                style={{ fontSize: "0.6rem", padding: "2px 5px", borderRadius: "3px", cursor: "pointer", border: "1px solid #2D2D2D", background: "transparent", color: "#888", whiteSpace: "nowrap" }}>이력</button>
              <button onClick={(e) => { e.stopPropagation(); const url = getSourceUrl(p.source_site, p.site_product_id); if (url) window.open(url, '_blank') }}
                style={{ fontSize: "0.6rem", padding: "2px 5px", borderRadius: "3px", cursor: "pointer", border: "1px solid #2D2D2D", background: "transparent", color: "#888", whiteSpace: "nowrap" }}>원문</button>
              <button onClick={(e) => { e.stopPropagation(); onEnrich(p.id) }}
                style={{ fontSize: "0.6rem", padding: "2px 5px", borderRadius: "3px", cursor: "pointer", border: "1px solid #2D2D2D", background: "transparent", color: "#888", whiteSpace: "nowrap" }}>업데이트</button>
              <span style={{ color: "#FFB84D", fontWeight: 600, flexShrink: 0 }}>₩{fmt(cost)}</span>
            </div>
            <div style={{ color: "#888", fontSize: "0.72rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {composeProductName(p, nameRules.find(r => r.id === (policy?.extras as Record<string, string> | undefined)?.name_rule_id))}
            </div>
          </div>
        </div>
      ) : (
      <div style={{ display: "flex", gap: "0", padding: "14px" }}>
        {/* Left: Image section */}
        <div style={{
          width: "130px", flexShrink: 0, display: "flex", flexDirection: "column",
          alignItems: "center", gap: "8px", paddingRight: "14px", borderRight: "1px solid #222",
        }}>
          <div onClick={() => { setProductImages(p.images || []); setShowImageModal(true) }} style={{ cursor: "pointer" }}>
            <ProductImage src={p.images?.[0]} name={p.name} size={110} />
          </div>
          <button
            onClick={() => { setProductImages(p.images || []); setShowImageModal(true); }}
            style={{
              fontSize: "0.68rem", color: "#666", background: "transparent",
              border: "1px solid #2D2D2D", borderRadius: "4px", padding: "3px 10px",
              cursor: "pointer", width: "100%",
            }}>이미지 변경</button>
          {/* 작업 뱃지 */}
          {((p.tags || []).includes('__img_filtered__') || (p.tags || []).includes('__ai_image__')) && (
            <div style={{ display: 'flex', gap: '3px', width: '100%' }}>
              {(p.tags || []).includes('__ai_image__') && (
                <span style={{ fontSize: '0.68rem', padding: '3px 10px', borderRadius: '4px', background: 'transparent', color: '#FF8C00', border: '1px solid rgba(255,140,0,0.3)', flex: 1, textAlign: 'center' }}>AI이미지</span>
              )}
              {(p.tags || []).includes('__img_filtered__') && (
                <span style={{ fontSize: '0.68rem', padding: '3px 10px', borderRadius: '4px', background: 'transparent', color: '#818CF8', border: '1px solid rgba(99,102,241,0.3)', flex: 1, textAlign: 'center' }}>이미지필터링</span>
              )}
            </div>
          )}
          {/* 무배당발 배지 */}
          {(p.free_shipping || p.same_day_delivery) && (
            <div style={{ display: 'flex', gap: '3px', width: '100%' }}>
              {p.free_shipping && (
                <span style={{ fontSize: '0.68rem', padding: '3px 10px', borderRadius: '4px', background: 'transparent', color: '#4C9AFF', border: '1px solid rgba(76,154,255,0.3)', flex: 1, textAlign: 'center' }}>무배</span>
              )}
              {p.same_day_delivery && (
                <span style={{ fontSize: '0.68rem', padding: '3px 10px', borderRadius: '4px', background: 'transparent', color: '#FF8C00', border: '1px solid rgba(255,140,0,0.3)', flex: 1, textAlign: 'center' }}>당발</span>
              )}
            </div>
          )}
        </div>

        {/* Right: Detail info */}
        <div style={{ flex: 1, paddingLeft: "16px" }}>
          {/* Action button bar */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "3px", marginBottom: "8px" }}>
            <button
              onClick={() => setShowPriceHistoryModal(true)}
              style={{
                fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
                color: "#999",
                border: "1px solid #2D2D2D",
                borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
              }}>가격변경이력</button>
            <button
              onClick={() => {
                const url = getSourceUrl(p.source_site, p.site_product_id)
                if (url) window.open(url, '_blank')
              }}
              style={{
                fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
                color: "#999", border: "1px solid #2D2D2D", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
              }}>원문링크</button>
            <button
              onClick={() => onEnrich(p.id)}
              style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#999", border: "1px solid #2D2D2D", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>가격재고업데이트</button>
            <button
              onClick={() => onMarketDelete(p.id)}
              style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#FF6B6B", border: "1px solid rgba(255,107,107,0.2)", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>마켓삭제</button>
            {/* 등록된 마켓 바로가기 — 등록한 계정만 표시 */}
            {p.status === "registered" && registeredMarkets.map(rm => (
              <button key={rm.accId}
                onClick={() => window.open(rm.url, '_blank')}
                style={{
                  fontSize: "0.65rem", padding: "2px 6px", background: "rgba(81,207,102,0.08)",
                  color: "#51CF66", border: "1px solid rgba(81,207,102,0.25)", borderRadius: "3px",
                  cursor: "pointer", whiteSpace: "nowrap",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(81,207,102,0.2)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'rgba(81,207,102,0.08)' }}
                title={`${rm.label} 상품 구매페이지 열기`}
              >{rm.label}</button>
            ))}
          </div>

          {/* Detail table */}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
            <colgroup>
              <col style={{ width: "80px" }} />
              <col />
            </colgroup>
            <tbody>
              {/* 원 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>원 상품명</td>
                <td style={tdVal}>
                  <span style={{ color: "#FFFFFF", fontWeight: 500 }}>{p.name}</span>
                </td>
              </tr>
              {/* 등록 상품명 (상품명 조합 + 삭제어 취소선 적용) */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>등록 상품명</td>
                <td style={tdVal}>
                  <span style={{ color: "#FFFFFF", fontSize: "0.8rem" }}>{renderRegisteredName(
                    composeProductName(p, nameRules.find(r => r.id === (policy?.extras as Record<string, string> | undefined)?.name_rule_id)),
                    deletionWords
                  )}</span>
                </td>
              </tr>
              {/* SEO 검색키워드 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>SEO</td>
                <td style={tdVal}>
                  <span style={{ color: (p.seo_keywords || []).length > 0 ? "#4C9AFF" : "#444", fontSize: "0.78rem" }}>
                    {(p.seo_keywords || []).join(', ') || '미설정 (AI태그 생성 필요)'}
                  </span>
                </td>
              </tr>
              {/* 영문 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>영문 상품명</td>
                <td style={tdVal}>
                  <input type="text" placeholder="영문 상품명 (English)" defaultValue={p.name_en || ""}
                    style={{ width: "100%", padding: "3px 7px", fontSize: "0.8rem", background: "#1A1A1A", border: "1px solid #2D2D2D", color: "#C5C5C5", borderRadius: "4px", outline: "none" }} />
                </td>
              </tr>
              {/* 일문 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>일문 상품명</td>
                <td style={tdVal}>
                  <input type="text" placeholder="일문 상품명 (日本語)" defaultValue={p.name_ja || ""}
                    style={{ width: "100%", padding: "3px 7px", fontSize: "0.8rem", background: "#1A1A1A", border: "1px solid #2D2D2D", color: "#C5C5C5", borderRadius: "4px", outline: "none" }} />
                </td>
              </tr>
              {/* 브랜드 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>브랜드</td>
                <td style={tdVal}>
                  <span style={{ color: "#888", fontSize: "0.8rem" }}>{p.brand || "-"}</span>
                </td>
              </tr>
              {/* 정상가 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>정상가</td>
                <td style={tdVal}>
                  <span style={{ color: "#C5C5C5", fontWeight: 600 }}>
                    {p.original_price > 0 ? `₩${fmt(p.original_price)}` : "-"}
                  </span>
                </td>
              </tr>
              {/* 할인가 (sale_price) */}
              {p.sale_price > 0 && p.sale_price < p.original_price && (
                <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                  <td style={tdLabel}>할인가</td>
                  <td style={tdVal}>
                    <span style={{ color: "#51CF66", fontWeight: 600 }}>₩{fmt(p.sale_price)}</span>
                    <span style={{ color: "#FF6B6B", fontSize: "0.72rem", marginLeft: "6px" }}>
                      {Math.round((1 - p.sale_price / p.original_price) * 100)}% 할인
                    </span>
                  </td>
                </tr>
              )}
              {/* 원가 (최대혜택가) */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>원가</td>
                <td style={tdVal}>
                  <span style={{ color: "#FFB84D", fontWeight: 600 }}>₩{fmt(cost)}</span>
                </td>
              </tr>
              {/* Market price — 마켓별 또는 공통 */}
              {marketPriceList.length > 0 ? marketPriceList.map((m) => (
                <tr key={m.marketName} style={{ borderBottom: "1px solid #1E1E1E" }}>
                  <td style={tdLabel}>{m.marketName}</td>
                  <td style={tdVal}>
                    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ color: "#FFB84D", fontWeight: 600 }}>₩{fmt(m.price)}</span>
                        {(() => {
                          const marketKey = MARKETS.find(mk => m.marketName.includes(mk.name))?.id
                            || m.marketName.toLowerCase().replace(/\s/g, '')
                          const mappedCat = productCatMapping[marketKey] || ''
                          return mappedCat ? (
                            <span style={{ fontSize: "0.68rem", color: "#888", background: "rgba(255,255,255,0.04)", padding: "1px 6px", borderRadius: "3px", border: "1px solid #2D2D2D" }}>{mappedCat}</span>
                          ) : (
                            <span style={{ fontSize: "0.68rem", color: "#555" }}>미매핑</span>
                          )
                        })()}
                      </div>
                      <span style={{ fontSize: "0.72rem", color: "#666" }}>{m.calcStr}</span>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                  <td style={tdLabel}>마켓가격</td>
                  <td style={tdVal}>
                    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                      <span style={{ color: "#FFB84D", fontWeight: 600 }}>₩{fmt(marketPrice)}</span>
                      <span style={{ fontSize: "0.72rem", color: "#666" }}>{calcStr}</span>
                    </div>
                  </td>
                </tr>
              )}
              {/* 카테고리 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>카테고리</td>
                <td style={tdVal}>
                  <span style={{ fontSize: "0.8rem", color: "#C5C5C5" }}>{p.category || "-"}</span>
                </td>
              </tr>
              {/* 상품정보 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={{ ...tdLabel, verticalAlign: "top", paddingTop: "10px" }}>상품정보</td>
                <td style={tdVal}>
                  {(() => {
                    const editableFields: { key: keyof SambaCollectedProduct; label: string }[] = [
                      { key: 'brand', label: '브랜드' },
                      { key: 'manufacturer', label: '제조사' },
                      { key: 'style_code', label: '품번' },
                      { key: 'origin', label: '제조국' },
                      { key: 'sex', label: '성별' },
                      { key: 'season', label: '시즌' },
                      { key: 'color', label: '색상' },
                      { key: 'material', label: '재질' },
                    ]
                    const readonlyFields = [
                      p.quality_guarantee && ['품질보증', p.quality_guarantee],
                      p.care_instructions && ['취급주의', p.care_instructions],
                    ].filter(Boolean) as [string, string][]
                    const inputStyle = { background: '#1A1A1A', border: '1px solid #333', color: '#C5C5C5', fontSize: '0.75rem', padding: '2px 6px', borderRadius: '3px', width: '140px', outline: 'none' }
                    return (
                      <div style={{ display: "flex", flexDirection: "column", gap: "3px", fontSize: "0.78rem" }}>
                        {editableFields.map(({ key, label }) => (
                          <span key={key} style={{ color: "#888", display: 'flex', alignItems: 'center', gap: '4px' }}>
                            {label}
                            <input
                              defaultValue={(p[key] as string) || ''}
                              style={inputStyle}
                              onBlur={(e) => {
                                const val = e.target.value.trim()
                                if (val !== ((p[key] as string) || '')) {
                                  collectorApi.updateProduct(p.id, { [key]: val } as Partial<SambaCollectedProduct>).then(() => {
                                    onProductUpdate(p.id, { [key]: val } as Partial<SambaCollectedProduct>)
                                    e.target.style.borderColor = '#51CF66'
                                    setTimeout(() => { e.target.style.borderColor = '#333' }, 1500)
                                  }).catch(() => {
                                    e.target.style.borderColor = '#FF6B6B'
                                    setTimeout(() => { e.target.style.borderColor = '#333' }, 1500)
                                  })
                                }
                              }}
                              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                            />
                          </span>
                        ))}
                        {readonlyFields.map(([label, val], i) => (
                          <span key={i} style={{ color: "#888" }}>{label} <span style={{ color: "#555", fontSize: '0.72rem' }}>{String(val).slice(0, 40)}{String(val).length > 40 ? '...' : ''}</span></span>
                        ))}
                      </div>
                    )
                  })()}
                </td>
              </tr>
              {/* 검색그룹 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>검색그룹</td>
                <td style={tdVal}>
                  {p.search_filter_id ? (
                    <span style={{ background: "rgba(255,140,0,0.08)", border: "1px solid rgba(255,140,0,0.25)", color: "rgba(255,180,100,0.85)", fontSize: "0.72rem", padding: "1px 8px", borderRadius: "10px" }}>
                      {filterNameMap[p.search_filter_id] || p.search_filter_id}
                    </span>
                  ) : <span style={{ color: "#444", fontSize: "0.75rem" }}>-</span>}
                </td>
              </tr>
              {/* 태그 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>태그</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", alignItems: "center" }}>
                    {(p.tags || []).filter(t => !t.startsWith('__')).map((tag, ti) => (
                      <span key={ti} style={{
                        fontSize: "0.7rem", padding: "1px 8px", borderRadius: "10px",
                        background: "rgba(100,100,255,0.1)", border: "1px solid rgba(100,100,255,0.25)", color: "#8B8FD4",
                        display: "inline-flex", alignItems: "center", gap: "4px",
                      }}>
                        {tag}
                        <span
                          style={{ cursor: "pointer", color: "#666", fontSize: "0.8rem", lineHeight: 1 }}
                          onClick={() => {
                            const newTags = (p.tags || []).filter(t => t !== tag)
                            onTagUpdate(p.id, newTags)
                          }}
                        >×</span>
                      </span>
                    ))}
                    <input
                      type="text"
                      placeholder="태그는 ','로 구분입력"
                      style={{ fontSize: "0.7rem", padding: "2px 7px", border: "1px solid #2D2D2D", borderRadius: "4px", color: "#C5C5C5", background: "#1A1A1A", outline: "none", width: "160px" }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          const input = e.currentTarget
                          const val = input.value.trim()
                          if (!val) return
                          const newTags = val.split(',').map(t => t.trim()).filter(Boolean)
                          const merged = [...new Set([...(p.tags || []), ...newTags])]
                          onTagUpdate(p.id, merged)
                          input.value = ''
                        }
                      }}
                    />
                    <button
                      style={{ fontSize: "0.68rem", padding: "2px 7px", border: "1px solid rgba(100,100,255,0.3)", borderRadius: "4px", color: "#8B8FD4", background: "rgba(100,100,255,0.08)", cursor: "pointer", whiteSpace: "nowrap" }}
                      onClick={() => {
                        const input = document.querySelector<HTMLInputElement>(`input[placeholder="태그는 ','로 구분입력"]`)
                        if (!input || !input.value.trim()) return
                        const newTags = input.value.trim().split(',').map(t => t.trim()).filter(Boolean)
                        const merged = [...new Set([...(p.tags || []), ...newTags])]
                        onTagUpdate(p.id, merged)
                        input.value = ''
                      }}
                    >추가</button>
                    {(p.tags || []).includes('__ai_tagged__') && (
                      <span style={{ fontSize: '0.62rem', padding: '1px 6px', background: 'rgba(255,140,0,0.12)', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '3px', color: '#FF8C00', fontWeight: 600, whiteSpace: 'nowrap' }}>AI</span>
                    )}
                  </div>
                </td>
              </tr>
              {/* 적용정책 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>적용정책</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                    <select
                      value={p.applied_policy_id || ""}
                      onChange={(e) => onPolicyChange(p.id, e.target.value)}
                      style={{
                        background: "rgba(22,22,22,0.9)", border: "1px solid #2D2D2D",
                        color: "#C5C5C5", borderRadius: "4px", padding: "2px 6px",
                        fontSize: "0.75rem", outline: "none",
                      }}
                    >
                      <option value="">정책 선택</option>
                      {policies.map((pol) => (
                        <option key={pol.id} value={pol.id}>{pol.name}</option>
                      ))}
                    </select>
                    {p.applied_policy_id && (
                      <button
                        onClick={() => window.location.href = `/samba/policies?highlight=${p.applied_policy_id}`}
                        style={{
                          background: "none", border: "1px solid #2D2D2D", borderRadius: "4px",
                          color: "#888", fontSize: "0.625rem", padding: "2px 6px",
                          cursor: "pointer", whiteSpace: "nowrap",
                        }}
                        onMouseEnter={e => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.borderColor = "rgba(255,140,0,0.4)" }}
                        onMouseLeave={e => { e.currentTarget.style.color = "#888"; e.currentTarget.style.borderColor = "#2D2D2D" }}
                        title="정책 페이지로 이동"
                      >이동</button>
                    )}
                  </div>
                </td>
              </tr>
              {/* Options */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>옵션</td>
                <td style={tdVal}>
                  {p.options && p.options.length > 0 ? (
                    <OptionPanel options={p.options} productCost={cost} productId={p.id} sourceSite={p.source_site} />
                  ) : (
                    <span style={{ color: "#444", fontSize: "0.75rem" }}>※ 옵션 미설정 -- 단일상품</span>
                  )}
                </td>
              </tr>
              {/* Market ON/OFF switches */}
              <tr>
                <td style={tdLabel}>ON-OFF</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center" }}>
                    {(() => {
                      // 등록된 마켓 타입만 ON-OFF 토글 표시
                      const regMarketTypes = new Set(registeredMarkets.map(rm => rm.marketId))
                      const visibleMarkets = MARKETS.filter(m => regMarketTypes.has(m.id))
                      if (visibleMarkets.length === 0) return <span style={{ color: '#555', fontSize: '0.72rem' }}>등록된 마켓이 없습니다</span>
                      return visibleMarkets.map((m) => {
                        const on = marketEnabled[m.id] !== false;
                        return (
                          <span key={m.id} style={{ display: "inline-flex", alignItems: "center", gap: "4px", marginRight: "10px", marginBottom: "2px" }}>
                            <button
                              onClick={() => onToggleMarket(p.id, m.id)}
                              style={{
                                width: "32px", height: "18px", borderRadius: "9px",
                                border: "none", cursor: "pointer", position: "relative",
                                background: on ? "#FF8C00" : "#333", transition: "background 0.2s",
                                padding: 0,
                              }}
                            >
                              <span style={{
                                position: "absolute", top: "2px",
                                left: on ? "14px" : "2px",
                                width: "14px", height: "14px", borderRadius: "50%",
                                background: "#fff", transition: "left 0.2s",
                              }} />
                            </button>
                            <span style={{ fontSize: "0.7rem", color: on ? "#C5C5C5" : "#555" }}>{m.name}</span>
                          </span>
                        );
                      })
                    })()}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      )}
      {/* 카드 알림 모달 */}

      {cardAlert && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 999999, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setCardAlert(null)}>
          <div style={{ background: '#1A1A1A', border: `1px solid ${cardAlert.type === 'error' ? 'rgba(255,107,107,0.4)' : 'rgba(34,197,94,0.4)'}`, borderRadius: '12px', padding: '24px 32px', minWidth: '320px', textAlign: 'center' }}
            onClick={e => e.stopPropagation()}>
            <p style={{ margin: '0 0 16px', color: '#E5E5E5', fontSize: '0.9rem' }}>{cardAlert.msg}</p>
            <button onClick={() => setCardAlert(null)}
              style={{ padding: '6px 24px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'rgba(50,50,50,0.6)', color: '#E5E5E5' }}>확인</button>
          </div>
        </div>
      )}
      {/* 카드 확인 모달 */}
      {cardConfirm && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 999999, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setCardConfirm(null)}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '24px 32px', minWidth: '320px', textAlign: 'center' }}
            onClick={e => e.stopPropagation()}>
            <p style={{ margin: '0 0 20px', color: '#E5E5E5', fontSize: '0.9rem' }}>{cardConfirm.msg}</p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '10px' }}>
              <button onClick={() => setCardConfirm(null)}
                style={{ padding: '6px 24px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'transparent', color: '#888' }}>취소</button>
              <button onClick={cardConfirm.onOk}
                style={{ padding: '6px 24px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(168,85,247,0.5)', background: 'rgba(168,85,247,0.15)', color: '#A855F7', fontWeight: 600 }}>확인</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ====== Option Panel Component ====== */

function OptionPanel({ options, productCost, productId, sourceSite }: { options: unknown[]; productCost: number; productId: string; sourceSite: string }) {
  const [open, setOpen] = useState(false);
  const [selectAll, setSelectAll] = useState(true);
  const [editingName, setEditingName] = useState<number | null>(null);
  const [localOpts, setLocalOpts] = useState(options as Record<string, unknown>[]);
  const [bulkModal, setBulkModal] = useState<'price' | 'stock' | 'addOption' | null>(null);
  const [bulkValue, setBulkValue] = useState('');
  const opts = localOpts;

  // 옵션 변경 시 즉시 API 저장
  const saveOptions = (newOpts: Record<string, unknown>[]) => {
    setLocalOpts(newOpts)
    collectorApi.updateProduct(productId, { options: newOpts } as Partial<SambaCollectedProduct>).catch(() => {})
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ color: "#888", fontSize: "0.78rem" }}>{opts.length}개 옵션</span>
        <button
          onClick={() => setOpen(!open)}
          style={{
            fontSize: "0.7rem", padding: "2px 8px",
            border: "1px solid #2D2D2D", borderRadius: "4px",
            color: "#888", background: "transparent", cursor: "pointer",
          }}
        >
          {open ? "접기" : "펼치기"}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: "8px" }}>
          {/* 안내문구 */}
          <p style={{ fontSize: "0.72rem", color: "#888", marginBottom: "0.75rem", lineHeight: 1.5 }}>
            ※ 옵션별로 가격 및 재고 수정이 가능합니다. 가격/재고를 수정하시면 해외 가격/재고는 무시되고, 수정하신 가격/재고로 반영됩니다.<br />
            ※ 체크박스에 체크되어 있는 상품만 마켓으로 전송됩니다. 전송을 원하지 않는 옵션은 체크를 해제하신 후 옵션저장 버튼을 클릭해주세요.
          </p>

          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #2D2D2D" }}>
                <th style={{ width: "36px", padding: "0.5rem", textAlign: "center" }}>
                  <input type="checkbox" checked={selectAll} onChange={(e) => setSelectAll(e.target.checked)} style={{ cursor: "pointer", accentColor: "#FF8C00" }} />
                </th>
                <th style={{ padding: "0.5rem", textAlign: "left", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  옵션명
                  <button
                    onClick={() => setEditingName(editingName === -1 ? null : -1)}
                    style={{ marginLeft: "0.4rem", fontSize: "0.7rem", padding: "1px 6px", background: editingName === -1 ? "rgba(255,140,0,0.3)" : "rgba(255,140,0,0.15)", color: "#FF8C00", border: "1px solid rgba(255,140,0,0.3)", borderRadius: "3px", cursor: "pointer" }}
                  >{editingName === -1 ? '편집완료' : '옵션명변경'}</button>
                  <button
                    onClick={() => { setBulkModal('addOption'); setBulkValue('') }}
                    style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}
                  >옵션추가</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  원가<br /><span style={{ fontSize: "0.7rem", color: "#555", fontWeight: 400 }}>(일반배송)</span>
                </th>
                {sourceSite === 'KREAM' && (
                  <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                    빠른배송<br /><span style={{ fontSize: "0.7rem", color: "#555", fontWeight: 400 }}>(KREAM)</span>
                  </th>
                )}
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  상품가
                  <button
                    onClick={() => { setBulkModal('price'); setBulkValue('') }}
                    style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}
                  >일괄수정</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  옵션재고
                  <button
                    onClick={() => { setBulkModal('stock'); setBulkValue('') }}
                    style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}
                  >일괄수정</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  마켓전송가격<br /><span style={{ fontSize: "0.7rem", color: "#666" }}>(마켓수수료 포함가격)</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {opts.map((o, idx) => {
                const isBrandDelivery = o.isBrandDelivery === true;
                const stock = o.stock !== undefined && o.stock !== null ? Number(o.stock) : -1;
                const isSoldOut = !isBrandDelivery && (o.isSoldOut === true || stock === 0);
                // 원가는 상품의 최대혜택가(cost)로 통일
                const optionCost = isSoldOut ? 0 : productCost;
                const optionSalePrice = Math.ceil(optionCost * 1.15); // 기본 15% 마진
                const isChecked = !isSoldOut;

                let stockDisplay: React.ReactNode;
                if (isBrandDelivery) {
                  stockDisplay = <span style={{ color: "#6B8AFF", fontWeight: 600, fontSize: "0.78rem" }}>브랜드배송</span>;
                } else if (isSoldOut) {
                  stockDisplay = <span style={{ color: "#FF6B6B", fontWeight: 600 }}>품절</span>;
                } else if (stock < 0 || stock >= 999) {
                  stockDisplay = (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <input type="number" data-option-stock="" placeholder="직접입력" style={{ width: "70px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }} />
                      <span style={{ fontSize: "0.72rem", color: "#51CF66" }}>{stock >= 999 ? "충분" : "재고있음"}</span>
                    </span>
                  );
                } else {
                  stockDisplay = (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <input type="number" data-option-stock="" defaultValue={stock} style={{ width: "60px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }} />
                      <span>개</span>
                    </span>
                  );
                }

                return (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(45,45,45,0.5)", opacity: isSoldOut ? 0.5 : 1 }}>
                    <td style={{ padding: "0.5rem", textAlign: "center" }}>
                      <input type="checkbox" defaultChecked={isChecked} style={{ cursor: "pointer", accentColor: "#FF8C00" }} />
                    </td>
                    <td style={{ padding: "0.5rem", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      {editingName === -1 ? (
                        <input
                          type="text"
                          defaultValue={String(o.name || o.value || `옵션${idx + 1}`)}
                          onBlur={(e) => {
                            const newOpts = [...opts]
                            newOpts[idx] = { ...newOpts[idx], name: e.target.value }
                            saveOptions(newOpts)
                          }}
                          style={{ width: "100%", background: "rgba(255,255,255,0.05)", border: "1px solid #FF8C00", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", fontSize: "0.875rem" }}
                        />
                      ) : (
                        String(o.name || o.value || `옵션${idx + 1}`)
                      )}
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#C5C5C5" }}>
                      {sourceSite === 'KREAM'
                        ? (Number(o.kreamGeneralPrice || o.kreamNormalPrice || o.price || 0) > 0 ? `₩${Number(o.kreamGeneralPrice || o.kreamNormalPrice || o.price || 0).toLocaleString()}` : '-')
                        : (optionCost > 0 ? `₩${optionCost.toLocaleString()}` : "-")
                      }
                    </td>
                    {sourceSite === 'KREAM' && (
                      <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#6B8AFF" }}>
                        {Number(o.kreamFastPrice || 0) > 0 ? `₩${Number(o.kreamFastPrice).toLocaleString()}` : '-'}
                      </td>
                    )}
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      <input
                        type="text"
                        inputMode="numeric"
                        data-option-price=""
                        defaultValue={optionSalePrice > 0 ? optionSalePrice.toLocaleString() : '0'}
                        onFocus={(e) => { e.target.value = e.target.value.replace(/,/g, '') }}
                        onBlur={(e) => {
                          const v = parseInt(e.target.value.replace(/,/g, ''), 10)
                          e.target.value = isNaN(v) ? '0' : v.toLocaleString()
                        }}
                        style={{ width: "100px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }}
                      />
                      <span>원</span>
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      {stockDisplay}
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right" }}>
                      <span style={{ color: "#555", fontSize: "0.75rem" }}>미계산</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* 일괄수정 모달 */}
          {bulkModal && (
            <div style={{
              position: 'fixed', inset: 0, zIndex: 99998,
              background: 'rgba(0,0,0,0.6)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }} onClick={() => setBulkModal(null)}>
              <div style={{
                background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '10px',
                padding: '20px 24px', width: 'min(360px, 90vw)',
              }} onClick={e => e.stopPropagation()}>
                <h4 style={{ margin: '0 0 12px', fontSize: '0.85rem', color: '#E5E5E5' }}>
                  {bulkModal === 'price' ? '상품가 일괄수정' : bulkModal === 'stock' ? '옵션재고 일괄수정' : '옵션 추가'}
                </h4>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="text"
                    inputMode={bulkModal === 'addOption' ? 'text' : 'numeric'}
                    autoFocus
                    placeholder={bulkModal === 'price' ? '가격 입력 (원)' : bulkModal === 'stock' ? '재고 입력 (개)' : '옵션명 입력'}
                    value={bulkValue}
                    onChange={e => setBulkValue(bulkModal === 'addOption' ? e.target.value : e.target.value.replace(/[^0-9]/g, ''))}
                    onKeyDown={e => {
                      if (e.key !== 'Enter') return
                      if (bulkModal === 'addOption') {
                        if (bulkValue.trim()) {
                          saveOptions([...opts, { name: bulkValue.trim(), price: productCost, stock: 0, isSoldOut: false }])
                          setBulkModal(null)
                        }
                      } else {
                        const v = parseInt(bulkValue, 10)
                        if (isNaN(v)) return
                        if (bulkModal === 'price') {
                          document.querySelectorAll<HTMLInputElement>('[data-option-price]').forEach(el => { el.value = v.toLocaleString() })
                          saveOptions(opts.map(o => ({ ...o, salePrice: v })))
                        } else {
                          document.querySelectorAll<HTMLInputElement>('[data-option-stock]').forEach(el => { el.value = String(v) })
                          saveOptions(opts.map(o => ({ ...o, stock: v })))
                        }
                        setBulkModal(null)
                      }
                    }}
                    style={{ flex: 1, padding: '8px 12px', fontSize: '0.85rem', background: '#1A1A1A', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px' }}
                  />
                  {bulkModal !== 'addOption' && <span style={{ color: '#888', fontSize: '0.8rem' }}>{bulkModal === 'price' ? '원' : '개'}</span>}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
                  <button onClick={() => setBulkModal(null)}
                    style={{ padding: '6px 16px', fontSize: '0.8rem', borderRadius: '6px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>취소</button>
                  <button onClick={() => {
                    if (bulkModal === 'addOption') {
                      if (bulkValue.trim()) {
                        saveOptions([...opts, { name: bulkValue.trim(), price: productCost, stock: 0, isSoldOut: false }])
                      }
                    } else {
                      const v = parseInt(bulkValue, 10)
                      if (isNaN(v)) return
                      if (bulkModal === 'price') {
                        document.querySelectorAll<HTMLInputElement>('[data-option-price]').forEach(el => { el.value = v.toLocaleString() })
                        saveOptions(opts.map(o => ({ ...o, salePrice: v })))
                      } else {
                        document.querySelectorAll<HTMLInputElement>('[data-option-stock]').forEach(el => { el.value = String(v) })
                        saveOptions(opts.map(o => ({ ...o, stock: v })))
                      }
                    }
                    setBulkModal(null)
                  }} style={{ padding: '6px 16px', fontSize: '0.8rem', borderRadius: '6px', border: 'none', background: '#FF8C00', color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
                    {bulkModal === 'addOption' ? '추가' : '적용'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ====== Product Image Component ====== */

function ProductImage({ src, name, size = 110 }: { src?: string; name: string; size?: number }) {
  const [error, setError] = useState(false);
  const firstChar = (name || "?")[0];

  if (!src || error) {
    return (
      <div style={{
        width: size, height: size, minWidth: size, borderRadius: "8px",
        border: "1px dashed #3D3D3D", display: "flex", alignItems: "center",
        justifyContent: "center", background: "#1A1A1A",
      }}>
        <span style={{ fontSize: size * 0.45, color: "#FF8C00", fontFamily: "sans-serif" }}>{firstChar}</span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={name}
      onError={() => setError(true)}
      style={{
        width: size, height: size, minWidth: size, objectFit: "cover",
        borderRadius: "8px", border: "1px solid #2D2D2D",
      }}
    />
  );
}

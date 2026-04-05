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
  detailTemplateApi,
  type SambaCollectedProduct,
  type SambaPolicy,
  type SambaSearchFilter,
  type SambaMarketAccount,
  type SambaNameRule,
  type SambaDetailTemplate,
} from "@/lib/samba/api";
import { showAlert, showConfirm } from '@/components/samba/Modal'
import ProductCard from './components/ProductCard'
import ProductImage from './components/ProductImage'

function fmt(n: number): string {
  return n.toLocaleString()
}

export default function ProductsPage() {
  useEffect(() => { document.title = 'SAMBA-상품관리' }, [])
  const searchParams = useSearchParams();
  const router = useRouter();

  // URL searchParams에서 필터 읽기
  const filterByGroupId = searchParams.get("search_filter_id") || "";
  const filterGroupName = searchParams.get("group_name") || "";

  // highlight는 로컬 state로 관리 → 새로고침 시 자동 해제
  const [highlightProductId, setHighlightProductId] = useState(searchParams.get("highlight") || "");
  useEffect(() => {
    const h = searchParams.get("highlight")
    if (h) {
      setHighlightProductId(h)
      // URL에서 highlight 파라미터 제거 (뒤로가기 히스토리 안 남김)
      const params = new URLSearchParams(searchParams.toString())
      params.delete("highlight")
      const qs = params.toString()
      router.replace(`/samba/products${qs ? `?${qs}` : ""}`)
    }
  }, [searchParams, router]);

  const [allProducts, setAllProducts] = useState<SambaCollectedProduct[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([]);
  const accountsMap = useMemo(() => new Map(accounts.map(a => [a.id, a])), [accounts])
  const [detailTemplates, setDetailTemplates] = useState<SambaDetailTemplate[]>([]);
  const [filterNameMap, setFilterNameMap] = useState<Record<string, string>>({});
  const [searchFilters, setSearchFilters] = useState<SambaSearchFilter[]>([]);
  const [loading, setLoading] = useState(true);
  // 서버사이드 페이지네이션 상태
  const [serverTotal, setServerTotal] = useState(0);
  const [serverSites, setServerSites] = useState<string[]>([]);

  // Filters
  const _initSearchType = searchParams.get("search_type") || "name";
  const _initSearch = searchParams.get("search") || "";
  // ID 검색은 내부 필터용 — 검색창에 표시하지 않음
  // highlight 파라미터가 있으면 해당 상품 ID로 검색
  const _highlightInit = searchParams.get("highlight") || ""
  const [_idFilter] = useState(
    _initSearchType === "id" ? _initSearch : (_highlightInit || "")
  );
  const [searchType, setSearchType] = useState(_initSearchType === "id" ? "name" : _initSearchType);
  const [searchQ, setSearchQ] = useState(_initSearchType === "id" ? "" : _initSearch);
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
  const [aiModelPreset, setAiModelPreset] = useState('auto')
  const [aiPresetList, setAiPresetList] = useState<{ key: string; label: string; desc: string; image: string | null }[]>([])
  const [aiImgTransforming, setAiImgTransforming] = useState(false)
  const [imgFiltering, setImgFiltering] = useState(false)
  const [imgFilterScopes, setImgFilterScopes] = useState<Set<string>>(new Set(['detail_images']))

  // AI 작업 진행 모달
  const [aiJobModal, setAiJobModal] = useState(false)
  const [aiJobTitle, setAiJobTitle] = useState('')
  const [aiJobLogs, setAiJobLogs] = useState<string[]>([])
  const [aiJobDone, setAiJobDone] = useState(false)
  const aiJobAbortRef = useRef(false)
  const aiJobLogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (aiJobLogRef.current) aiJobLogRef.current.scrollTop = aiJobLogRef.current.scrollHeight
  }, [aiJobLogs])

  // 프리셋 이미지 목록 로드
  useEffect(() => {
    proxyApi.listPresets().then(res => {
      if (res.success) setAiPresetList(res.presets)
    }).catch(() => {})
  }, [])


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

  // 서버사이드 페이지네이션 상품 로드 (counts도 함께 수신)
  const loadProducts = useCallback(async (page?: number) => {
    const targetPage = page ?? currentPage
    setLoading(true)
    try {
      const skip = (targetPage - 1) * pageSize
      // status 필터에서 특수값 분리
      const statusParam = (statusFilter === 'has_orders' || statusFilter === 'free_ship' || statusFilter === 'same_day' || statusFilter === 'free_same' || statusFilter === 'market_registered' || statusFilter === 'market_unregistered' || statusFilter === 'sold_out')
        ? statusFilter : statusFilter || undefined
      const aiParam = (aiFilter === 'has_orders') ? aiFilter : aiFilter || undefined
      const res = await collectorApi.scrollProducts({
        skip,
        limit: pageSize,
        search: searchQ.trim() || _idFilter || undefined,
        search_type: searchQ.trim() ? searchType : (_idFilter ? "id" : undefined),
        source_site: siteFilter || undefined,
        status: statusParam,
        ai_filter: aiParam,
        search_filter_id: filterByGroupId || undefined,
        sort_by: sortBy,
      })
      setAllProducts(res.items)
      setServerTotal(res.total)
      setServerSites(res.sites)
      // scroll 응답에 counts 포함 — 별도 API 불필요
      if (res.counts) setKpiCounts(res.counts)
    } catch (e) {
      console.error("loadProducts error:", e)
    } finally {
      setLoading(false)
    }
  }, [currentPage, pageSize, searchQ, searchType, siteFilter, statusFilter, aiFilter, filterByGroupId, sortBy])

  // 상품만 리로드 (삭제/수정 등 상품 변경 후 사용)
  const reloadProducts = useCallback(async () => {
    await loadProducts(currentPage)
  }, [loadProducts, currentPage])

  // 메타데이터 + 상품 병렬 로드 (초기 1회)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      // 메타데이터 8개 + 상품 scroll 동시 호출
      const statusParam = (statusFilter === 'has_orders' || statusFilter === 'free_ship' || statusFilter === 'same_day' || statusFilter === 'free_same' || statusFilter === 'market_registered' || statusFilter === 'market_unregistered' || statusFilter === 'sold_out')
        ? statusFilter : statusFilter || undefined
      const aiParam = (aiFilter === 'has_orders') ? aiFilter : aiFilter || undefined
      const [pol, filters, words, accs, orderPids, rules, mappings, tpls, productsRes] = await Promise.all([
        policyApi.list().catch(() => []),
        collectorApi.listFilters().catch(() => [] as SambaSearchFilter[]),
        forbiddenApi.listWords('deletion').catch(() => []),
        accountApi.listActive().catch(() => [] as SambaMarketAccount[]),
        collectorApi.getProductIdsWithOrders().catch(() => [] as string[]),
        nameRuleApi.list().catch(() => [] as SambaNameRule[]),
        categoryApi.listMappings().catch(() => []) as Promise<{ source_site: string; source_category: string; target_mappings: Record<string, string> }[]>,
        detailTemplateApi.list().catch(() => [] as SambaDetailTemplate[]),
        collectorApi.scrollProducts({
          skip: 0,
          limit: pageSize,
          search: searchQ.trim() || _idFilter || undefined,
          search_type: searchQ.trim() ? searchType : (_idFilter ? "id" : undefined),
          source_site: siteFilter || undefined,
          status: statusParam,
          ai_filter: aiParam,
          search_filter_id: filterByGroupId || undefined,
          sort_by: sortBy,
        }).catch(() => null),
      ])
      setPolicies(pol)
      setAccounts(accs)
      setDetailTemplates(tpls)
      setDeletionWords(words.filter((w: { is_active?: boolean }) => w.is_active !== false).map((w: { word: string }) => w.word))
      setNameRules(rules)
      setOrderProductIds(new Set(orderPids))
      const nameMap: Record<string, string> = {}
      filters.forEach((f: SambaSearchFilter) => { nameMap[f.id] = f.name })
      setFilterNameMap(nameMap)
      setSearchFilters(filters)
      if (Array.isArray(mappings)) {
        const map = new Map<string, Record<string, string>>()
        mappings.forEach(m => {
          map.set(`${m.source_site}::${m.source_category}`, m.target_mappings || {})
        })
        setCatMappingMap(map)
      }
      // 상품 데이터 세팅
      if (productsRes) {
        setAllProducts(productsRes.items)
        setServerTotal(productsRes.total)
        setServerSites(productsRes.sites)
        if (productsRes.counts) setKpiCounts(productsRes.counts)
      }
    } catch (e) {
      console.error("load error:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // 필터/정렬 변경 시 1페이지로 리셋 + 선택 초기화 (디바운싱 300ms, 초기 로드 제외)
  const filterTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const filterInitRef = useRef(true)
  useEffect(() => {
    if (filterInitRef.current) { filterInitRef.current = false; return }
    setSelectAll(false)
    setSelectedIds(new Set())
    setCurrentPage(1)
    if (filterTimerRef.current) clearTimeout(filterTimerRef.current)
    filterTimerRef.current = setTimeout(() => {
      loadProducts(1)
    }, 300)
    return () => { if (filterTimerRef.current) clearTimeout(filterTimerRef.current) }
  // searchType은 검색어가 있을 때만 재조회 트리거 (빈 검색어에서 드롭박스 변경 시 불필요한 로딩 방지)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQ, searchQ.trim() ? searchType : '', siteFilter, statusFilter, aiFilter, sortBy, filterByGroupId])

  // 페이지 변경 시 서버에서 해당 페이지 로드
  const totalPages = Math.max(1, Math.ceil(serverTotal / pageSize))
  const goToPage = useCallback((page: number) => {
    const p = Math.max(1, Math.min(page, totalPages))
    setCurrentPage(p)
    setSelectAll(false)
    setSelectedIds(new Set())
    loadProducts(p)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [totalPages, loadProducts])

  // pageSize 변경 시 1페이지로 리셋 (초기 로드 제외)
  const pageSizeInitRef = useRef(true)
  useEffect(() => {
    if (pageSizeInitRef.current) { pageSizeInitRef.current = false; return }
    loadProducts(1)
  }, [pageSize])

  // highlight 시 해당 상품만 표시, 아니면 전체
  const products = highlightProductId
    ? allProducts.filter(p => p.id === highlightProductId)
    : allProducts

  // KPI 카드용 — scroll 응답에 counts 포함, 별도 API 호출 불필요
  const [kpiCounts, setKpiCounts] = useState({ total: 0, registered: 0, policy_applied: 0, sold_out: 0 })
  const registeredCount = kpiCounts.registered

  const totalCount = serverTotal;

  const allSites = serverSites

  const handleSearch = () => {
    // highlight + 그룹 필터 무조건 해제
    if (highlightProductId) setHighlightProductId("")
    if (filterByGroupId) {
      router.replace('/samba/products')
    }
    setCurrentPage(1)
  };

  const handleDelete = (id: string) => {
    const p = allProducts.find((x) => x.id === id);
    if (p?.lock_delete) {
      showAlert('삭제잠금이 설정된 상품입니다. 잠금을 해제한 후 삭제하세요.')
      return;
    }
    if ((p?.registered_accounts?.length ?? 0) > 0) {
      showAlert('마켓에 등록된 상품입니다. 마켓삭제 후 진행하세요.')
      return;
    }
    setDeleteConfirm({ ids: [id], label: p ? `"${p.name.slice(0, 30)}"` : "이 상품" });
  };

  const handleBulkDelete = () => {
    if (selectedIds.size === 0) return;
    const selected = allProducts.filter(p => selectedIds.has(p.id))
    const locked = selected.filter(p => p.lock_delete)
    const registered = selected.filter(p => !p.lock_delete && (p.registered_accounts?.length ?? 0) > 0)
    const deletableIds = selected
      .filter(p => !p.lock_delete && !(p.registered_accounts?.length))
      .map(p => p.id)
    if (deletableIds.length === 0) {
      const reasons = [
        locked.length > 0 ? `삭제잠금 ${locked.length}개` : '',
        registered.length > 0 ? `마켓등록 ${registered.length}개` : '',
      ].filter(Boolean).join(', ')
      showAlert(`삭제 가능한 상품이 없습니다 (${reasons})`)
      return;
    }
    const excludes = [
      locked.length > 0 ? `잠금 ${locked.length}개` : '',
      registered.length > 0 ? `마켓등록 ${registered.length}개` : '',
    ].filter(Boolean)
    const excludeMsg = excludes.length > 0 ? ` (${excludes.join(', ')} 제외)` : ''
    setDeleteConfirm({ ids: deletableIds, label: `${deletableIds.length}개 상품${excludeMsg}` });
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
    if (!deleteConfirm) return
    const ids = deleteConfirm.ids
    setDeleteConfirm(null)
    setAiJobTitle(`삭제 (${ids.length}건)`)
    setAiJobLogs([`${ids.length}건 일괄 삭제 중...`])
    setAiJobDone(false)
    setAiJobModal(true)
    const idSet = new Set(ids)
    try {
      const res = await collectorApi.bulkDeleteProducts(ids)
      setAiJobLogs(prev => [...prev, `${res.deleted}건 삭제 완료 ✓`])
    } catch {
      setAiJobLogs(prev => [...prev, `삭제 실패 ✗`])
    }
    setAiJobDone(true)
    setSelectedIds(new Set())
    setSelectAll(false)
    reloadProducts()
  }

  const handlePolicyChange = async (productId: string, policyId: string) => {
    // 낙관적 업데이트
    setAllProducts(prev => prev.map(p =>
      p.id === productId ? { ...p, applied_policy_id: policyId || undefined } as SambaCollectedProduct : p
    ))
    await collectorApi.updateProduct(productId, { applied_policy_id: policyId || undefined } as Partial<SambaCollectedProduct>).catch(() => {})
  };

  const handleEnrich = async (productId: string) => {
    const product = allProducts.find((p) => p.id === productId)
    const productName = (product?.name || productId).slice(0, 25)
    setActiveLog({ productId, message: `[업데이트 중] ${productName}...` })
    try {
      const { API_BASE_URL: apiBase } = await import('@/config/api')
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
    const productName = (p?.name || productId).slice(0, 20)
    const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setAiJobTitle(`마켓삭제 - ${productName}`)
    setAiJobLogs([])
    setAiJobDone(false)
    setAiJobModal(true)
    try {
      const res = await shipmentApi.marketDelete([productId], regAccIds)
      const result = res?.results?.[0]
      if (result?.delete_results) {
        const entries = Object.entries(result.delete_results as Record<string, string>)
        const logs = entries.map(([accId, status]) => {
          const acc = accountsMap.get(accId)
          const label = acc ? acc.market_type : accId.slice(0, 8)
          const isOk = status === 'success' || status.includes('성공')
          return `[${ts()}] ${productName} → ${label}: ${isOk ? '✓' : '✗'}`
        })
        logs.push(`[${ts()}] 완료 — 성공 ${result.success_count}/${entries.length}`)
        setAiJobLogs(logs)
        const successAccIds = entries.filter(([, s]) => s === 'success' || (s as string).includes('성공')).map(([id]) => id)
        setAllProducts(prev => prev.map(pp => {
          if (pp.id !== productId) return pp
          const remaining = (pp.registered_accounts ?? []).filter(id => !successAccIds.includes(id))
          return { ...pp, registered_accounts: remaining, status: remaining.length === 0 ? 'collected' : pp.status } as SambaCollectedProduct
        }))
      } else {
        setAiJobLogs([`[${ts()}] ${productName} → ✓`])
      }
    } catch {
      setAiJobLogs([`[${ts()}] ${productName} → ✗ 오류`])
    }
    setAiJobDone(true)
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

  const handleSelectAll = async (checked: boolean) => {
    setSelectAll(checked);
    if (checked) {
      // 전체 검색 결과 ID를 서버에서 조회
      if (serverTotal > products.length) {
        try {
          const statusParam = statusFilter || undefined
          const aiParam = aiFilter || undefined
          const res = await collectorApi.scrollProducts({
            skip: 0, limit: serverTotal,
            search: searchQ.trim() || undefined,
            search_type: searchQ.trim() ? searchType : undefined,
            source_site: siteFilter || undefined,
            status: statusParam,
            ai_filter: aiParam,
            search_filter_id: filterByGroupId || undefined,
            sort_by: sortBy,
          })
          setSelectedIds(new Set(res.items.map((p: SambaCollectedProduct) => p.id)));
        } catch {
          setSelectedIds(new Set(products.map((p) => p.id)));
        }
      } else {
        setSelectedIds(new Set(products.map((p) => p.id)));
      }
    } else {
      setSelectedIds(new Set());
    }
  };

  // 성능 최적화: 안정적인 콜백 참조로 ProductCard 불필요한 리렌더 방지
  const handleProductUpdate = useCallback((productId: string, data: Partial<SambaCollectedProduct>) => {
    setAllProducts(prev => prev.map(pp => pp.id === productId ? { ...pp, ...data } : pp))
  }, [])

  const handleTagUpdate = useCallback(async (productId: string, tags: string[]) => {
    const userTags = tags.filter(t => !t.startsWith('__'))
    const clearSeo = userTags.length === 0
    setAllProducts(prev => prev.map(p =>
      p.id === productId ? { ...p, tags, ...(clearSeo ? { seo_keywords: [] } : {}) } : p
    ))
    const updateData: Partial<SambaCollectedProduct> = { tags }
    if (clearSeo) updateData.seo_keywords = []
    await collectorApi.updateProduct(productId, updateData).catch(() => {})
  }, [])

  const handleToggleExpand = useCallback((productId: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      next.has(productId) ? next.delete(productId) : next.add(productId)
      return next
    })
  }, [])

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
                  background: 'none', border: 'none', color: '#888', fontSize: '0.77rem', cursor: 'pointer',
                }}>✕</button>
              )}
            </div>
            <div
              ref={aiJobLogRef}
              style={{
                flex: 1, overflow: 'auto', padding: '14px', fontFamily: 'monospace',
                fontSize: '0.68rem', lineHeight: 1.6, color: '#8A95B0',
                transform: 'scale(0.7)', transformOrigin: 'top left', width: '142.8%',
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
            <div style={{ padding: '12px 20px', borderTop: '1px solid #2D2D2D', display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              {!aiJobDone && (
                <button onClick={() => { aiJobAbortRef.current = true }} style={{
                  padding: '6px 20px', borderRadius: '6px', fontSize: '0.56rem',
                  background: 'rgba(255,107,107,0.15)', border: '1px solid rgba(255,107,107,0.4)',
                  color: '#FF6B6B', cursor: 'pointer', fontWeight: 600,
                }}>중단</button>
              )}
              {aiJobDone && (
                <button onClick={() => setAiJobModal(false)} style={{
                  padding: '6px 20px', borderRadius: '6px', fontSize: '0.56rem',
                  background: 'rgba(81,207,102,0.15)', border: '1px solid rgba(81,207,102,0.4)',
                  color: '#51CF66', cursor: 'pointer', fontWeight: 600,
                }}>확인</button>
              )}
            </div>
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
                    // 태그 로컬 반영
                    const tagMap = new Map(tagPreviews.map(tp => [tp.group_id, { tags: tp.tags, seo: tp.seo_keywords }]))
                    setAllProducts(prev => prev.map(pp => {
                      const entry = pp.search_filter_id ? tagMap.get(pp.search_filter_id) : undefined
                      if (!entry) return pp
                      const existing = (pp.tags || []).filter(t => t.startsWith('__'))
                      return { ...pp, tags: [...existing, '__ai_tagged__', ...entry.tags], seo_keywords: entry.seo } as SambaCollectedProduct
                    }))
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
            onClick={() => setHighlightProductId("")}
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
            {kpiCounts.total.toLocaleString()}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
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
            {registeredCount.toLocaleString()}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
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
            <option value="market_registered">마켓등록</option>
            <option value="market_unregistered">미등록</option>
            <option value="sold_out">품절상품</option>
          </select>
          <select value={searchType} onChange={(e) => setSearchType(e.target.value)}
            style={{ padding: "0.3rem 0.4rem", fontSize: "0.78rem", background: "#1E1E1E", border: "1px solid #3D3D3D", borderRadius: "6px", color: "#C5C5C5", width: "90px" }}>
            <option value="name">검색항목</option>
            <option value="brand">브랜드</option>
            <option value="name_all">상품명+등록명</option>
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
      <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 1.3fr 1fr', gap: '8px', marginBottom: '1rem' }}>
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
          <option value="model_to_product">모델→상품</option>
          <option value="scene">연출컷</option>
          <option value="model">모델 착용</option>
        </select>
        {aiImgMode === 'model' && (
          <select
            value={aiModelPreset}
            onChange={e => setAiModelPreset(e.target.value)}
            style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}
          >
            <option value="auto">자동 (성별·연령 판별)</option>
            {['여성', '남성', '키즈 여아', '키즈 남아'].map(group => {
              const groupPresets = aiPresetList.filter(p => {
                if (group === '여성') return p.key.startsWith('female_')
                if (group === '남성') return p.key.startsWith('male_')
                if (group === '키즈 여아') return p.key.startsWith('kids_girl_')
                return p.key.startsWith('kids_boy_')
              })
              if (!groupPresets.length) return null
              return (
                <optgroup key={group} label={group}>
                  {groupPresets.map(p => (
                    <option key={p.key} value={p.key}>{p.label.replace(/^.*—\s*/, '')}</option>
                  ))}
                </optgroup>
              )
            })}
          </select>
        )}
        <span style={{ fontSize: '0.78rem', color: '#888' }}>({selectedIds.size}개 상품)</span>
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 이미지를 변환하시겠습니까?`)
            if (!ok) return
            const ids = [...selectedIds]
            const ts = () => new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
            setAiImgTransforming(true)
            aiJobAbortRef.current = false
            setAiJobTitle(`AI 이미지변환 (${ids.length}개)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            const startTime = ts()
            addLog(`시작: ${startTime} (${ids.length}개 상품)`)
            let success = 0
            let fail = 0
            for (let i = 0; i < ids.length; i++) {
              if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${i}/${ids.length})`); break }
              const prod = allProducts.find(p => p.id === ids[i])
              const label = prod?.name?.slice(0, 30) || ids[i].slice(-8)
              setAiJobTitle(`AI 이미지변환 [${i + 1}/${ids.length}] ${label}`)
              try {
                const autoScope = { thumbnail: true, additional: true, detail: true }
                const res = await proxyApi.transformImages([ids[i]], autoScope, aiImgMode, aiModelPreset)
                if (res.success && res.total_transformed > 0) { success++; addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — 완료 (${res.total_transformed}장)`) }
                else { fail++; addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — 실패: ${res.message || '변환된 이미지 0장'}`) }
              } catch (e) { fail++; addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
            }
            const endTime = ts()
            setAiJobTitle(`AI 이미지변환 완료 (${success}/${ids.length})`)
            addLog(`\n완료: 성공 ${success}개 / 실패 ${fail}개`)
            addLog(`시작 ${startTime} → 종료 ${endTime}`)
            setAiJobDone(true)
            setAiImgTransforming(false)
            setSelectedIds(new Set()); setSelectAll(false)
            reloadProducts()
          }}
          disabled={aiImgTransforming || selectedIds.size === 0}
          style={{ marginLeft: 'auto', background: aiImgTransforming ? '#333' : 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)', color: aiImgTransforming ? '#888' : '#FF8C00', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: aiImgTransforming ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
        >{aiImgTransforming ? '변환중...' : '변환 실행'}</button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#818CF8', fontWeight: 600 }}>이미지 필터링</span>
        {([['images', '대표'], ['detail_images', '추가'], ['detail', '상세']] as const).map(([key, label]) => (
          <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input type="checkbox" checked={imgFilterScopes.has(key)}
              onChange={() => setImgFilterScopes(prev => {
                const next = new Set(prev)
                if (next.has(key)) next.delete(key); else next.add(key)
                return next
              })}
              style={{ accentColor: '#818CF8', width: '13px', height: '13px' }} />
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{label}</span>
          </label>
        ))}
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
            if (imgFilterScopes.size === 0) { showAlert('필터링 대상을 선택해주세요'); return }
            const scopeLabel = [...imgFilterScopes].map(s => s === 'images' ? '대표' : s === 'detail_images' ? '추가' : '상세').join('+')
            const scope = imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') && imgFilterScopes.has('detail') ? 'all' : imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') ? 'images' : imgFilterScopes.has('detail') ? 'detail' : [...imgFilterScopes][0] || 'images'
            const ok = await showConfirm(`선택된 ${selectedIds.size}개 상품의 ${scopeLabel} 이미지를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
            if (!ok) return
            const ids = [...selectedIds]
            setImgFiltering(true)
            aiJobAbortRef.current = false
            setAiJobTitle(`이미지 필터링 (${ids.length}개)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            const ts = () => new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
            let success = 0
            let fail = 0
            let totalTall = 0
            let totalVisionRemoved = 0
            const startTime = ts()
            for (let i = 0; i < ids.length; i++) {
              if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${i}/${ids.length})`); break }
              const prod = allProducts.find(p => p.id === ids[i])
              const prodName = prod?.name?.slice(0, 25) || ids[i].slice(-8)
              const prodNo = prod?.site_product_id || ids[i].slice(-8)
              const prodBrand = prod?.brand || '-'
              const label = `${prodBrand} / ${prodNo} / ${prodName}${prod?.name && prod.name.length > 25 ? '...' : ''}`
              setAiJobTitle(`이미지 필터링 [${i + 1}/${ids.length}] ${prodBrand} / ${prodNo}`)
              try {
                const steps: string[] = []
                // 1) 프론트에서 추가이미지 비율 체크 (세로 2배 이상 → 제거)
                if (prod && (scope === 'detail_images' || scope === 'images' || scope === 'all')) {
                  const imgs = prod.images || []
                  if (imgs.length > 1) {
                    const tallCheck = await Promise.all(imgs.slice(1).map(url =>
                      new Promise<boolean>(resolve => {
                        const img = new window.Image()
                        img.onload = () => {
                          const isTall = img.naturalHeight > img.naturalWidth * 2
                          resolve(isTall)
                        }
                        img.onerror = () => resolve(false)
                        img.src = url
                        setTimeout(() => resolve(false), 10000)
                      })
                    ))
                    const tallUrls = imgs.slice(1).filter((_, i) => tallCheck[i])
                    if (tallUrls.length > 0) {
                      const kept = imgs.filter(u => !tallUrls.includes(u))
                      await collectorApi.updateProduct(ids[i], { images: kept })
                      totalTall += tallUrls.length
                      steps.push(`긴이미지 ${tallUrls.length}장 제거`)
                    }
                  }
                }
                // 2) 백엔드 이미지 필터링
                const r = await proxyApi.filterProductImages([ids[i]], '', scope)
                if (r.success) {
                  success++
                  const removed = r.total_removed || 0
                  totalVisionRemoved += removed
                  if (removed > 0) steps.push(`필터 ${removed}장 제거`)
                  else steps.push('필터 변동없음')
                  addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — ${steps.join(' → ')}`)
                } else { fail++; addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — ${steps.length > 0 ? steps.join(' → ') + ' → ' : ''}실패`) }
              } catch (e) { fail++; addLog(`[${ts()}] [${i + 1}/${ids.length}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
            }
            const summary = [`성공 ${success}개`, `실패 ${fail}개`]
            if (totalTall > 0) summary.push(`긴이미지 ${totalTall}장 제거`)
            if (totalVisionRemoved > 0) summary.push(`필터 ${totalVisionRemoved}장 제거`)
            setAiJobTitle(`이미지 필터링 완료 (${success}/${ids.length})`)
            addLog(`\n완료: ${summary.join(' / ')}`)
            addLog(`시작 ${startTime} → 종료 ${ts()}`)
            setAiJobDone(true)
            setImgFiltering(false)
            const apiCalls = success + fail
            setLastAiUsage({ calls: apiCalls, tokens: apiCalls * 1000, cost: apiCalls * 15, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
            setSelectedIds(new Set()); setSelectAll(false)
            reloadProducts()
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
          </label>
          <span style={{ fontSize: "0.875rem", color: "#E5E5E5", fontWeight: 600, whiteSpace: "nowrap" }}>
            상품관리 <span style={{ color: "#FF8C00" }}>( 총 <span>{totalCount.toLocaleString()}</span>개 검색 )</span>
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
            reloadProducts()
          }} style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(76,154,255,0.3)", borderRadius: "5px",
            color: "#4C9AFF", background: "rgba(76,154,255,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>영상</button>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid #3D3D3D", borderRadius: "5px",
            color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
          }}>AI상품명</button>
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
            await collectorApi.bulkUpdateTags([...selectedIds], [], [])
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
              window.location.href = `/samba/shipments?selected=${encodeURIComponent(ids)}&sites=${encodeURIComponent(sites)}&autoAll=1&priceOnly=1`
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
              const ids = [...selectedIds]
              if (!await showConfirm(`${ids.length}개 상품을 수집차단 + 삭제하시겠습니까?\n(동일 상품이 다시 수집되지 않습니다)`)) return
              try {
                const res = await collectorApi.blockAndDelete(ids)
                showAlert(`차단 ${res.blocked}건, 삭제 ${res.deleted}건 완료`, 'success')
                setSelectedIds(new Set()); setSelectAll(false)
                reloadProducts()
              } catch (e) { showAlert(`수집차단 실패: ${e instanceof Error ? e.message : ''}`) }
            }}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid rgba(255,107,107,0.3)", borderRadius: "5px",
              color: "#FF6B6B", background: "rgba(255,107,107,0.08)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >수집차단</button>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
              const targets = allProducts.filter(p => selectedIds.has(p.id) && (p.registered_accounts?.length ?? 0) > 0)
              if (!targets.length) { showAlert('마켓에 등록된 상품이 없습니다.'); return }
              if (!await showConfirm(`${targets.length}개 상품을 마켓에서 삭제(판매중지)하시겠습니까?`)) return
              aiJobAbortRef.current = false
              setAiJobTitle(`마켓삭제 (${targets.length}건)`)
              setAiJobLogs([])
              setAiJobDone(false)
              setAiJobModal(true)
              let totalOk = 0, totalFail = 0
              // 로그를 배열 ref로 관리 — spread 복사 O(n²) 방지
              const logsRef: string[] = []
              const flushLogs = () => setAiJobLogs([...logsRef])
              // 성공 계정 누적 (루프 끝나고 한번에 상품 상태 갱신)
              const successMap = new Map<string, string[]>()
              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
              for (let i = 0; i < targets.length; i++) {
                if (aiJobAbortRef.current) { logsRef.push(`\n⛔ 사용자 중단 (${i}/${targets.length})`); flushLogs(); break }
                const t = targets[i]
                const name = t.name.slice(0, 20)
                try {
                  const accIds = t.registered_accounts ?? []
                  const res = await shipmentApi.marketDelete([t.id], accIds)
                  const result = res?.results?.[0]
                  if (result?.delete_results) {
                    const entries = Object.entries(result.delete_results as Record<string, string>)
                    const successAccIds: string[] = []
                    for (const [accId, status] of entries) {
                      const acc = accountsMap.get(accId)
                      const label = acc ? acc.market_type : accId.slice(0, 8)
                      const isOk = status === 'success' || status.includes('성공')
                      if (isOk) { totalOk++; successAccIds.push(accId) } else totalFail++
                      logsRef.push(`[${ts()}] [${i + 1}/${targets.length}] ${name} → ${label}: ${isOk ? '✓' : '✗'}`)
                    }
                    if (successAccIds.length) successMap.set(t.id, successAccIds)
                  } else {
                    totalOk++
                    logsRef.push(`[${ts()}] [${i + 1}/${targets.length}] ${name} → ✓`)
                  }
                } catch {
                  totalFail++
                  logsRef.push(`[${ts()}] [${i + 1}/${targets.length}] ${name} → ✗`)
                }
                flushLogs()
                await new Promise(r => setTimeout(r, 50))
              }
              // 상품 상태 한번에 갱신
              if (successMap.size > 0) {
                setAllProducts(prev => prev.map(pp => {
                  const removedAccs = successMap.get(pp.id)
                  if (!removedAccs) return pp
                  const remaining = (pp.registered_accounts ?? []).filter(id => !removedAccs.includes(id))
                  return { ...pp, registered_accounts: remaining, status: remaining.length === 0 ? 'collected' : pp.status } as SambaCollectedProduct
                }))
              }
              logsRef.push(``, `성공 ${totalOk} / 실패 ${totalFail}`)
              flushLogs()
              setAiJobDone(true)
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
              const ids = Array.from(selectedIds)
              setAiJobTitle(`강제삭제 (${ids.length}건)`)
              setAiJobLogs([`${ids.length}건 초기화 중...`])
              setAiJobDone(false)
              setAiJobModal(true)
              const idSet = new Set(ids)
              try {
                const res = await collectorApi.bulkResetRegistration(ids)
                setAiJobLogs(prev => [...prev, `${res.reset}건 초기화 완료 ✓`])
                setAllProducts(prev => prev.map(p =>
                  idSet.has(p.id) ? { ...p, registered_accounts: null, market_product_nos: null, status: 'collected' } as unknown as SambaCollectedProduct : p
                ))
              } catch {
                setAiJobLogs(prev => [...prev, `초기화 실패 ✗`])
              }
              setAiJobDone(true)
            }}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid #3D3D3D", borderRadius: "5px",
              color: "#B0B0B0", background: "rgba(50,50,50,0.6)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >강제삭제</button>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('상품을 선택해주세요'); return }
              // 선택된 상품의 group_key 수집
              const selectedProducts = allProducts.filter(p => selectedIds.has(p.id))
              const groupKeys = new Set(selectedProducts.map(p => p.group_key).filter(Boolean))
              if (groupKeys.size === 0) { showAlert('선택한 상품에 그룹 정보가 없습니다'); return }
              // 동일 그룹의 모든 상품 찾기
              const groupIds = allProducts
                .filter(p => p.group_key && groupKeys.has(p.group_key))
                .map(p => p.id)
              if (!await showConfirm(`선택한 ${selectedIds.size}건의 그룹(${groupKeys.size}개) 전체 ${groupIds.length}건을 삭제하시겠습니까?`)) return
              setAiJobTitle(`그룹상품삭제 (${groupIds.length}건)`)
              setAiJobLogs([`${groupKeys.size}개 그룹, ${groupIds.length}건 삭제 중...`])
              setAiJobDone(false)
              setAiJobModal(true)
              const idSet = new Set(groupIds)
              try {
                const res = await collectorApi.bulkDeleteProducts(groupIds)
                setAiJobLogs(prev => [...prev, `${res.deleted}건 삭제 완료 ✓`])
              } catch {
                setAiJobLogs(prev => [...prev, `삭제 실패 ✗`])
              }
              setAiJobDone(true)
              setSelectedIds(new Set())
              setSelectAll(false)
              reloadProducts()
            }}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid #FF6B6B", borderRadius: "5px",
              color: "#FF6B6B", background: "rgba(255,107,107,0.1)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >그룹상품삭제</button>
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
          >간단</button>
          <button
            onClick={() => setViewMode("card")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "card" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "card" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "card" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >자세히</button>
          <button
            onClick={() => setViewMode("image")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "image" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "image" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "image" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >사진</button>
          <select
            value={aiFilter}
            onChange={(e) => setAiFilter(e.target.value)}
            style={{ background: '#1A1A1A', border: '1px solid #3D3D3D', color: '#E5E5E5', borderRadius: '6px', padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
          >
            <option value="">전체</option>
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
          <span style={{ fontSize: '0.75rem', color: '#888' }}>
            {fmt(allProducts.length)} / {fmt(serverTotal)}
          </span>
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
              <div onClick={(e) => { e.stopPropagation(); router.push(`/samba/products?search_type=id&search=${p.id}&highlight=${p.id}`); }} style={{ cursor: 'pointer' }}>
                <ProductImage src={p.images?.[0]} name={p.name} size={140} />
              </div>
              {(p.free_shipping || p.same_day_delivery) && (
                <div style={{ display: 'flex', gap: '3px', padding: '3px 8px 0' }}>
                  {p.free_shipping && <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(76,154,255,0.15)', color: '#4C9AFF', fontWeight: 600 }}>무배</span>}
                  {p.same_day_delivery && <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600 }}>당발</span>}
                </div>
              )}
              <div style={{ padding: "6px 8px" }}>
                <p style={{ fontSize: '0.7rem', color: '#C5C5C5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', margin: 0, display: 'flex', alignItems: 'center' }}>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</span>
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
              onToggleExpand={() => handleToggleExpand(p.id)}
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
              onProductUpdate={handleProductUpdate}
              onTagUpdate={handleTagUpdate}
              logMessage={activeLog?.productId === p.id ? activeLog.message : undefined}
              catMappingMap={catMappingMap}
              filters={searchFilters}
              detailTemplates={detailTemplates}
            />
          ))}
        </div>
      )}

      {/* 페이지네이션 */}
      {serverTotal > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.25rem', padding: '1rem 0', flexWrap: 'wrap' }}>
          <button onClick={() => goToPage(1)} disabled={currentPage === 1}
            style={{ padding: '4px 8px', fontSize: '0.75rem', border: '1px solid #2D2D2D', borderRadius: '4px', background: 'transparent', color: currentPage === 1 ? '#444' : '#C5C5C5', cursor: currentPage === 1 ? 'default' : 'pointer' }}>{'<<'}</button>
          <button onClick={() => goToPage(currentPage - 1)} disabled={currentPage === 1}
            style={{ padding: '4px 8px', fontSize: '0.75rem', border: '1px solid #2D2D2D', borderRadius: '4px', background: 'transparent', color: currentPage === 1 ? '#444' : '#C5C5C5', cursor: currentPage === 1 ? 'default' : 'pointer' }}>{'<'}</button>
          {(() => {
            const pages: number[] = []
            const start = Math.max(1, currentPage - 4)
            const end = Math.min(totalPages, start + 9)
            for (let i = start; i <= end; i++) pages.push(i)
            return pages.map(p => (
              <button key={p} onClick={() => goToPage(p)}
                style={{ padding: '4px 10px', fontSize: '0.75rem', border: p === currentPage ? '1px solid #FF8C00' : '1px solid #2D2D2D', borderRadius: '4px', background: p === currentPage ? 'rgba(255,140,0,0.15)' : 'transparent', color: p === currentPage ? '#FF8C00' : '#C5C5C5', cursor: 'pointer', fontWeight: p === currentPage ? 700 : 400 }}>{p}</button>
            ))
          })()}
          <button onClick={() => goToPage(currentPage + 1)} disabled={currentPage === totalPages}
            style={{ padding: '4px 8px', fontSize: '0.75rem', border: '1px solid #2D2D2D', borderRadius: '4px', background: 'transparent', color: currentPage === totalPages ? '#444' : '#C5C5C5', cursor: currentPage === totalPages ? 'default' : 'pointer' }}>{'>'}</button>
          <button onClick={() => goToPage(totalPages)} disabled={currentPage === totalPages}
            style={{ padding: '4px 8px', fontSize: '0.75rem', border: '1px solid #2D2D2D', borderRadius: '4px', background: 'transparent', color: currentPage === totalPages ? '#444' : '#C5C5C5', cursor: currentPage === totalPages ? 'default' : 'pointer' }}>{'>>'}</button>
          <span style={{ fontSize: '0.75rem', color: '#888', marginLeft: '0.5rem' }}>
            {fmt(serverTotal)}건 / {currentPage}/{fmt(totalPages)}p
          </span>
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1) }}
            style={{ marginLeft: '0.5rem', padding: '3px 6px', fontSize: '0.75rem', background: '#111520', border: '1px solid #2A3040', color: '#C5C5C5', borderRadius: '4px' }}>
            <option value={20}>20건</option>
            <option value={50}>50건</option>
            <option value={100}>100건</option>
          </select>
        </div>
      )}
    </div>
  );
}


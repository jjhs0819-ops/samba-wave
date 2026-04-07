"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  collectorApi,
  policyApi,
  proxyApi,
  aiSourcingApi,
  categoryApi,
  accountApi,
  API_BASE,
  type SambaSearchFilter,
  type SambaPolicy,
  type SambaMarketAccount,
  type RefreshResult,
  type AISourcingResult,
  type AISourcingCombination,
} from "@/lib/samba/api";
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SITE_COLORS, SOURCING_SEARCH_URLS } from '@/lib/samba/constants'
import { fmtDate as _fmtDate } from '@/lib/samba/utils'

const fmtDate = (iso: string | undefined | null) => _fmtDate(iso, '.')

const SITES = [
  { id: 'MUSINSA', label: '무신사' },
  { id: 'KREAM', label: 'KREAM' },
  { id: 'DANAWA', label: '다나와' },
  { id: 'FashionPlus', label: '패션플러스' },
  { id: 'Nike', label: 'Nike' },
  { id: 'Adidas', label: 'Adidas' },
  { id: 'ABCmart', label: 'ABC마트' },
  { id: 'GrandStage', label: '그랜드스테이지' },
  { id: 'REXMONDE', label: '렉스몬드' },
  { id: 'SSG', label: '신세계몰' },
  { id: 'LOTTEON', label: '롯데ON' },
  { id: 'GSShop', label: 'GSShop' },
  { id: 'ElandMall', label: '이랜드몰' },
  { id: 'SSF', label: 'SSF샵' },
]

const SITE_OPTIONS: Record<string, { id: string; label: string }[]> = {
  MUSINSA: [
    { id: 'excludePreorder', label: '예약배송 수집제외' },
    { id: 'excludeBoutique', label: '부티끄 수집제외' },
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  KREAM: [],
  FashionPlus: [],
  SSG: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  LOTTEON: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
}

// 매핑 대상 마켓 목록
// 카테고리 수 기준 정렬 (DB동기화 > 하드코딩 순)
const MAPPING_MARKETS = [
  { id: 'smartstore', name: '스마트스토어' },  // 4964
  { id: 'coupang', name: '쿠팡' },            // 73
  { id: 'gmarket', name: '지마켓' },          // 45
  { id: 'kream', name: 'KREAM' },             // 39
  { id: 'auction', name: '옥션' },            // 36
  { id: '11st', name: '11번가' },             // 36
  { id: 'ssg', name: 'SSG' },                 // 35
  { id: 'lotteon', name: '롯데ON' },          // 30
  { id: 'gsshop', name: 'GSSHOP' },           // 29
  { id: 'hmall', name: 'HMALL' },             // 28
  { id: 'lottehome', name: '롯데홈쇼핑' },     // 24
  { id: 'homeand', name: '홈앤쇼핑' },         // 23
  { id: 'ebay', name: 'eBay' },               // 10
  { id: 'shopee', name: 'Shopee' },           // 8
  { id: 'lazada', name: 'Lazada' },           // 8
  { id: 'shopify', name: 'Shopify' },         // 8
  { id: 'playauto', name: '플레이오토' },       // 7
  { id: 'cafe24', name: '카페24' },            // 7
  { id: 'toss', name: '토스' },               // 6
  { id: 'amazon', name: '아마존' },            // 6
  { id: 'qoo10', name: 'Qoo10' },             // 6
  { id: 'rakuten', name: '라쿠텐' },           // 6
  { id: 'buyma', name: '바이마' },             // 6
  { id: 'zoom', name: 'Zum(줌)' },            // 6
  { id: 'poison', name: '포이즌' },            // 6
]

// 매핑 모달 — 마켓별 카테고리 입력 + 자동완성
function MappingMarketRow({ marketType, marketName, value, onChange, onClear }: { marketType: string; marketName: string; value: string; onChange: (v: string) => void; onClear: () => void }) {
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSugg, setShowSugg] = useState(false)
  return (
    <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
      <span style={{ fontSize: '0.8rem', color: '#888', minWidth: '100px' }}>{marketName}</span>
      <div style={{ flex: 1, position: 'relative' }}>
        <input
          type="text"
          value={value}
          onChange={async e => {
            const val = e.target.value
            onChange(val)
            if (val.length >= 2) {
              try {
                const res = await categoryApi.suggest(val, marketType)
                setSuggestions(Array.isArray(res) ? res.slice(0, 8) : [])
                setShowSugg(true)
              } catch { setSuggestions([]) }
            } else { setSuggestions([]); setShowSugg(false) }
          }}
          onFocus={() => { if (suggestions.length > 0) setShowSugg(true) }}
          onBlur={() => setTimeout(() => setShowSugg(false), 200)}
          placeholder="카테고리 검색 (2자 이상 입력)"
          style={{ width: '100%', fontSize: '0.78rem', padding: '5px 10px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', outline: 'none' }}
        />
        {showSugg && suggestions.length > 0 && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', maxHeight: '200px', overflowY: 'auto', marginTop: '2px' }}>
            {suggestions.map((s, i) => (
              <div key={i}
                onMouseDown={() => { onChange(s); setShowSugg(false) }}
                style={{ padding: '6px 10px', fontSize: '0.72rem', color: '#C5C5C5', cursor: 'pointer', borderBottom: i < suggestions.length - 1 ? '1px solid #2D2D2D' : 'none' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,140,0,0.1)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >{s}</div>
            ))}
          </div>
        )}
      </div>
      {value && (
        <button onClick={onClear}
          style={{ color: '#666', cursor: 'pointer', background: 'none', border: 'none', fontSize: '1rem' }}>&times;</button>
      )}
    </div>
  )
}

export default function CollectorPage() {
  useEffect(() => { document.title = 'SAMBA-상품수집' }, [])
  const router = useRouter();
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);

  // URL collect
  const [collectUrl, setCollectUrl] = useState("");
  const [collecting, setCollecting] = useState(false);
  const [collectDetailImages, setCollectDetailImages] = useState(false);
  const [collectLog, setCollectLog] = useState<string[]>(["[대기] 수집 결과가 여기에 표시됩니다..."]);
  const [selectedSite, setSelectedSite] = useState("MUSINSA");
  const [checkedOptions, setCheckedOptions] = useState<Record<string, boolean>>({
    excludePreorder: true,
    excludeBoutique: true,
    maxDiscount: true,
  });

  // 카테고리 자동분류 옵션
  const [brandScanning, setBrandScanning] = useState(false)
  const [brandCategories, setBrandCategories] = useState<{ categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }[]>([])
  const [brandSelectedCats, setBrandSelectedCats] = useState<Set<string>>(new Set())
  const [brandTotal, setBrandTotal] = useState(0)

  // 롯데ON 브랜드 선택 모달
  const [showBrandModal, setShowBrandModal] = useState(false)
  const [brandModalList, setBrandModalList] = useState<{ name: string; count: number }[]>([])
  const [brandModalSelected, setBrandModalSelected] = useState<Set<string>>(new Set())
  const [brandModalKeyword, setBrandModalKeyword] = useState('')
  const [brandModalParsed, setBrandModalParsed] = useState<{ brand: string; keyword: string; gf: string } | null>(null)

  // 일괄 갱신
  const [refreshing, setRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState<RefreshResult | null>(null)
  const [showRefreshModal, setShowRefreshModal] = useState(false)
  // AI 비용 추적
  const [lastAiUsage, setLastAiUsage] = useState<{ calls: number; tokens: number; cost: number; date: string } | null>(null)

  // AI 태그 미리보기 모달
  const [showTagPreview, setShowTagPreview] = useState(false)
  const [tagPreviews, setTagPreviews] = useState<{ group_id: string; group_name: string; product_count: number; rep_name: string; tags: string[]; seo_keywords: string[] }[]>([])
  const [tagPreviewCost, setTagPreviewCost] = useState<{ api_calls: number; input_tokens: number; output_tokens: number; cost_krw: number } | null>(null)
  const [tagPreviewLoading, setTagPreviewLoading] = useState(false)
  const [removedTags, setRemovedTags] = useState<string[]>([])

  // AI 이미지 변환
  const [aiImgScope, setAiImgScope] = useState({ thumbnail: true, additional: false, detail: false })
  const [aiImgMode, setAiImgMode] = useState('background')
  const [aiModelPreset, setAiModelPreset] = useState('auto')
  const [aiImgTransforming, setAiImgTransforming] = useState(false)
  const [aiPresetList, setAiPresetList] = useState<{ key: string; label: string; desc: string; image: string | null }[]>([])
  // AI 작업 진행 모달
  const [aiJobModal, setAiJobModal] = useState(false)
  const [aiJobTitle, setAiJobTitle] = useState('')
  const [aiJobLogs, setAiJobLogs] = useState<string[]>([])
  const [aiJobDone, setAiJobDone] = useState(false)
  const aiJobAbortRef = useRef(false)
  const aiJobLogRef = useRef<HTMLDivElement>(null)

  // 이미지 필터링 (모델컷/연출컷/배너 제거)
  const [imgFiltering, setImgFiltering] = useState(false)
  const [imgFilterScopes, setImgFilterScopes] = useState<Set<string>>(new Set(['detail_images']))

  // 카테고리 매핑 모달
  const [showMappingModal, setShowMappingModal] = useState(false)
  const [mappingFilter, setMappingFilter] = useState<SambaSearchFilter | null>(null)
  const [mappingData, setMappingData] = useState<Record<string, string>>({})
  const [mappingLoading, setMappingLoading] = useState(false)
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])

  // Proxy & auth status
  const [proxyStatus, setProxyStatus] = useState<"checking" | "ok" | "error">("checking");
  const [proxyText, setProxyText] = useState("프록시 서버 확인 중...");
  const [musinsaAuth, setMusinsaAuth] = useState<"checking" | "ok" | "error">("checking");
  const [musinsaAuthText, setMusinsaAuthText] = useState("인증 상태 확인 중...");

  // 트리 + 드릴다운
  const [tree, setTree] = useState<SambaSearchFilter[]>([])
  const [drillSite, setDrillSite] = useState<string | null>(null)
  const [drillBrand, setDrillBrand] = useState<string | null>(null)
  const [drillGroup, setDrillGroup] = useState<string | null>(null)
  const [drillEntry, setDrillEntry] = useState<'site' | 'brand' | null>('site')

  // Group table filters
  const [siteFilter, setSiteFilter] = useState("");
  const [aiFilter, setAiFilter] = useState("");
  const [collectFilter, setCollectFilter] = useState("")
  const [marketRegFilter, setMarketRegFilter] = useState("")
  const [tagRegFilter, setTagRegFilter] = useState("")
  const [policyRegFilter, setPolicyRegFilter] = useState("")
  const [sortBy, setSortBy] = useState("lastCollectedAt_desc");
  const [selectAll, setSelectAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // AI 소싱기 상태
  const [showAiSourcingModal, setShowAiSourcingModal] = useState(false)
  const [aiSourcingStep, setAiSourcingStep] = useState<'config' | 'analyzing' | 'confirm'>('config')
  const [aiMonth, setAiMonth] = useState(new Date().getMonth() + 1) // 현재월
  const [aiMainCategory, setAiMainCategory] = useState('패션의류')
  const [aiExcelFile, setAiExcelFile] = useState<File | null>(null)
  const [aiTargetCount, setAiTargetCount] = useState(10000)
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [aiLogs, setAiLogs] = useState<string[]>([])
  const [aiResult, setAiResult] = useState<AISourcingResult | null>(null)
  const [aiSelectedCombos, setAiSelectedCombos] = useState<Set<number>>(new Set())
  const [aiExcludedBrands, setAiExcludedBrands] = useState<Set<string>>(new Set())
  const [aiExcludedKeywords, setAiExcludedKeywords] = useState<Set<string>>(new Set())
  const [aiMinCount, setAiMinCount] = useState(0) // 최소 상품수 필터
  const [aiCreating, setAiCreating] = useState(false)
  const [aiSourceSite, setAiSourceSite] = useState('MUSINSA') // 수집 소싱처 선택

  const logRef = useRef<HTMLDivElement>(null);
  const collectAbortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [f, pol] = await Promise.all([
      collectorApi.listFilters().catch(() => []),
      policyApi.list().catch(() => []),
    ]);
    setFilters(f);
    setPolicies(pol);
    setLoading(false);
  }, []);

  const loadTree = useCallback(async () => {
    try {
      const data = await collectorApi.getFilterTree()
      setTree(data)
    } catch { /* 트리 로드 실패 무시 */ }
  }, [])

  useEffect(() => { load(); loadTree(); }, [load, loadTree]);
  useEffect(() => {
    proxyApi.listPresets().then(res => { if (res.success) setAiPresetList(res.presets) }).catch(() => {})
    accountApi.list().then(setAccounts).catch(() => {})
  }, [])
  useEffect(() => {
    if (aiJobLogRef.current) aiJobLogRef.current.scrollTop = aiJobLogRef.current.scrollHeight
  }, [aiJobLogs])

  // 드롭다운 필터 변경 시 drillBrand 활성 상태면 selectedIds를 displayedFilters 기준으로 재동기화
  useEffect(() => {
    if (drillBrand) {
      setSelectedIds(new Set(displayedFilters.map(f => f.id)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tagRegFilter, collectFilter, marketRegFilter, policyRegFilter, aiFilter])

  // 프록시 & 무신사 인증 상태 확인
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setProxyStatus("ok"); setProxyText(data.message || "프록시 서버 정상 작동 중"); }
        else { setProxyStatus("error"); setProxyText(data.message || "프록시 서버 연결 실패"); }
      })
      .catch(() => { setProxyStatus("error"); setProxyText("백엔드 서버 연결 실패"); });

    fetch(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setMusinsaAuth("ok"); setMusinsaAuthText(data.message || "무신사 인증 완료"); }
        else { setMusinsaAuth("error"); setMusinsaAuthText(data.message || "무신사 인증 필요"); }
      })
      .catch(() => { setMusinsaAuth("error"); setMusinsaAuthText("백엔드 서버 연결 실패"); });
  }, []);

  const addLog = useCallback((msg: string) => {
    const time = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setCollectLog((prev) => [...prev, `[${time}] ${msg}`].slice(-30));
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 50);
  }, []);

  // URL → 그룹 생성만 (수집 X)
  const handleCreateGroup = async () => {
    if (!collectUrl.trim()) return;
    setCollecting(true);
    addLog(`그룹 생성 중: ${collectUrl}`);
    try {
      // URL 도메인과 선택된 소싱처 불일치 검증
      const site = selectedSite
      try {
        const host = new URL(collectUrl).hostname
        const siteHostMap: Record<string, string[]> = {
          MUSINSA: ['musinsa.com'], KREAM: ['kream.co.kr'], FashionPlus: ['fashionplus.co.kr'],
          Nike: ['nike.com'], Adidas: ['adidas.co.kr', 'adidas.com'],
          ABCmart: ['a-rt.com'], GrandStage: ['a-rt.com'], REXMONDE: ['okmall.com'],
          LOTTEON: ['lotteon.com'], GSShop: ['gsshop.com'], ElandMall: ['elandmall.com'],
          SSF: ['ssfshop.com'], SSG: ['ssg.com'],
        }
        const allowedHosts = siteHostMap[site] || []
        if (allowedHosts.length > 0 && !allowedHosts.some(h => host.includes(h))) {
          showAlert(`선택한 소싱처(${site})와 URL 도메인(${host})이 일치하지 않습니다`, 'error')
          setCollecting(false)
          return
        }
      } catch { /* URL이 아닌 경우 검증 스킵 */ }

      // URL에서 키워드 추출 (소싱처별 파라미터)
      let keyword = ""
      let isUrl = false
      try {
        const parsed = new URL(collectUrl)
        isUrl = true
        keyword = parsed.searchParams.get("keyword")
          || parsed.searchParams.get("searchWord")
          || parsed.searchParams.get("q")
          || parsed.searchParams.get("query")
          || parsed.searchParams.get("kwd")
          || parsed.searchParams.get("tq")
          || parsed.searchParams.get("tab")
          || ""
      } catch {
        // URL이 아닌 경우 검색어 자체를 키워드로 사용
        keyword = collectUrl.trim()
      }

      // 그룹이름 자동 생성: 소싱처_키워드
      const groupName = keyword ? `${site}_${keyword.replace(/\s+/g, '_')}` : `${site}_${new Date().toLocaleDateString("ko-KR")}`;

      // 무신사 옵션 URL 파라미터로 저장
      let keywordUrl = collectUrl;
      if (site === "MUSINSA") {
        // 평문 키워드인 경우 무신사 검색 URL 자동 구성
        let u: URL
        if (!isUrl) {
          u = new URL("https://www.musinsa.com/search/goods")
          u.searchParams.set("keyword", keyword)
        } else {
          try { u = new URL(collectUrl) } catch { u = new URL("https://www.musinsa.com/search/goods"); u.searchParams.set("keyword", keyword) }
        }
        if (checkedOptions['excludePreorder']) u.searchParams.set("excludePreorder", "1");
        if (checkedOptions['excludeBoutique']) u.searchParams.set("excludeBoutique", "1");
        if (checkedOptions['maxDiscount']) u.searchParams.set("maxDiscount", "1");
        keywordUrl = u.toString();
      }
      // 패션플러스: 평문 키워드 → 검색 URL 자동 구성
      if (site === 'FashionPlus' && !isUrl) {
        const u = new URL('https://www.fashionplus.co.kr/search/goods/result')
        u.searchParams.set('searchWord', keyword)
        if (checkedOptions['skipDetail']) u.searchParams.set('skipDetail', '1')
        keywordUrl = u.toString()
      } else if (checkedOptions['skipDetail'] && keywordUrl.startsWith('http')) {
        const u = new URL(keywordUrl)
        u.searchParams.set('skipDetail', '1')
        keywordUrl = u.toString()
      }

      // 소싱처 범용 검색 총 상품수 조회
      let requestedCount = 100
      try {
        const countResult = await proxyApi.searchCount(site, keyword, isUrl ? keywordUrl : '')
        if (countResult.totalCount > 0) {
          requestedCount = countResult.totalCount
          addLog(`검색 결과: ${requestedCount.toLocaleString()}개 상품`)
        }
      } catch { /* 조회 실패 시 기본값 100 유지 */ }

      const created = await collectorApi.createFilter({
        source_site: site,
        name: groupName,
        keyword: keywordUrl,
        requested_count: requestedCount,
      });

      addLog(`그룹 생성 완료: "${created.name}" (${site}, ${requestedCount.toLocaleString()}개)`);
      setCollectUrl("");
      load(); loadTree();
    } catch (e) {
      addLog(`그룹 생성 실패: ${e instanceof Error ? e.message : "오류"}`);
    }
    setCollecting(false);
  };

  const handleDeleteSelectedGroups = async () => {
    // 체크된 그룹이 없으면 현재 보이는 그룹 전체를 대상으로
    // displayedFilters와 교집합으로 실제 대상 결정
    const displayedIds = new Set(displayedFilters.map(f => f.id))
    const baseIds = selectedIds.size > 0
      ? new Set([...selectedIds].filter(id => displayedIds.has(id)))
      : displayedIds
    if (baseIds.size === 0) {
      showAlert(`삭제 대상이 없습니다. (selectedIds=${selectedIds.size}, displayed=${displayedFilters.length}, drillBrand=${drillBrand || '없음'})`)
      return
    }

    // 선택된 그룹 + 하위 그룹 모두 수집 (사이트 필터 적용 시 같은 사이트만)
    const allIds = new Set(baseIds)
    const findChildren = (parentId: string) => {
      for (const f of filters) {
        if (f.parent_id === parentId && !allIds.has(f.id)) {
          if (siteFilter && f.source_site && f.source_site !== siteFilter) continue
          allIds.add(f.id)
          findChildren(f.id)
        }
      }
    }
    for (const id of baseIds) findChildren(id)

    const childCount = allIds.size - baseIds.size
    const label = selectedIds.size > 0 ? '선택된' : '표시된'
    const msg = childCount > 0
      ? `${label} ${baseIds.size}개 + 하위 ${childCount}개 (총 ${allIds.size}개) 그룹과 상품을 모두 삭제하시겠습니까?`
      : `${label} ${baseIds.size}개 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`
    if (!await showConfirm(msg)) return;
    for (const id of allIds) {
      try {
        const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: id })
        // 마켓 등록 상품 체크
        const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
        if (registered.length > 0) {
          showAlert(`마켓등록 상품이 ${registered.length}건 있어서 삭제할 수 없습니다`, 'error')
          continue
        }
        const productIds = res.items.map(p => p.id)
        if (productIds.length > 0) {
          await collectorApi.bulkDeleteProducts(productIds)
        }
      } catch { /* 상품 없으면 무시 */ }
      await collectorApi.deleteFilter(id).catch(() => {});
    }
    setSelectedIds(new Set());
    setSelectAll(false);
    load(); loadTree();
  };

  const handleCollectGroups = async () => {
    // 체크된 그룹이 없으면 현재 보이는 그룹 전체 수집
    // displayedFilters와 교집합으로 실제 대상 결정
    const targetFilters = selectedIds.size > 0
      ? displayedFilters.filter(f => selectedIds.has(f.id))
      : displayedFilters
    const targetIds = targetFilters.map(f => f.id)
    if (targetIds.length === 0) {
      addLog("수집할 그룹이 없습니다.")
      return
    }
    const totalReq = targetFilters.reduce((s, f) => s + (f.requested_count || 0), 0)
    const ok = await showConfirm(`${selectedIds.size > 0 ? '선택된' : '표시된'} ${targetIds.length}개 그룹 상품수집을 시작하시겠습니까?\n(요청 ${totalReq.toLocaleString()}건, 중복 상품은 자동 스킵)`)
    if (!ok) return
    const abort = new AbortController()
    collectAbortRef.current = abort
    setCollecting(true)
    addLog(`${targetIds.length}개 그룹 상품수집 시작...`)

    for (const id of targetIds) {
      if (abort.signal.aborted) break
      const f = filters.find((x) => x.id === id)
      if (!f) continue
      // 그룹 전환 시 렌더링 보장
      await new Promise(r => setTimeout(r, 100))
      addLog(`[${f.name}] 수집 요청 중...`)

      try {
        // Job 생성
        const res = await fetch(
          `${API_BASE}/api/v1/samba/collector/collect-filter/${id}`,
          { method: 'POST' }
        )
        if (!res.ok) {
          const errData = await res.json().catch(() => null)
          addLog(`[${f.name}] 수집 실패: ${errData?.detail || `HTTP ${res.status}`}`)
          continue
        }
        const { job_id } = await res.json() as { job_id: string }
        // 수집 시작 로그 생략

        // 폴링으로 진행률 추적
        let lastCurrent = 0
        while (!abort.signal.aborted) {
          await new Promise(r => setTimeout(r, 1000))
          if (abort.signal.aborted) break

          try {
            const jobRes = await fetch(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
            if (!jobRes.ok) break
            const job = await jobRes.json() as {
              status: string; current: number; total: number
              progress: number; result?: { saved?: number; skipped?: number; policy?: string; message?: string }
              error?: string
            }

            if (job.current > lastCurrent) {
              addLog(`[${f.name}] [${job.current}/${job.total}] 수집 중... (${job.progress}%)`)
              lastCurrent = job.current
              load()
            }

            if (job.status === 'completed') {
              const saved = job.result?.saved ?? 0
              const skipped = job.result?.skipped ?? 0
              const policy = job.result?.policy || ''
              const parts = [`신규 ${saved}건`]
              if (skipped > 0) parts.push(`중복 ${skipped}건`)
              if (policy) parts.push(policy)
              addLog(`[${f.name}] 수집 완료: ${parts.join(' | ')}`)
              await new Promise(r => setTimeout(r, 100))
              break
            }
            if (job.status === 'failed') {
              addLog(`[${f.name}] 수집 실패: ${job.error || '알 수 없는 오류'}`)
              await new Promise(r => setTimeout(r, 100))
              break
            }
          } catch {
            // 네트워크 오류 시 재시도
          }
        }
      } catch (e) {
        addLog(`[${f.name}] 수집 오류: ${(e as Error).message}`)
      }
    }
    setCollecting(false)
    collectAbortRef.current = null
    // 수집 완료 후 요청수를 수집수에 자동 동기화
    await syncRequestedCounts()
    load(); loadTree()
  }

  // 요청수 ↔ 수집수 자동 동기화 (수집 완료 후 호출)
  const syncRequestedCounts = async () => {
    try {
      const latestFilters = await collectorApi.listFilters()
      const mismatch = latestFilters.filter(
        (f: SambaSearchFilter) => !f.is_folder && (f.requested_count || 0) !== ((f as unknown as Record<string, number>).collected_count || 0)
      )
      for (const f of mismatch) {
        const cc = (f as unknown as Record<string, number>).collected_count || 0
        if (cc > 0) {
          await collectorApi.updateFilter(f.id, { requested_count: cc })
        }
      }
      if (mismatch.length > 0) addLog(`[동기화] ${mismatch.length}개 그룹 요청수 → 수집수 자동 동기화`)
    } catch { /* 동기화 실패해도 수집 흐름은 유지 */ }
  }

  const handleStopCollect = () => {
    collectAbortRef.current?.abort();
    addLog('수집 중단 요청...');
  };

  const handleClearLog = () => { setCollectLog(["로그가 초기화되었습니다."]); };
  const handleCopyLog = () => { navigator.clipboard.writeText(collectLog.join("\n")).catch(() => {}); };

  const handleCheckboxToggle = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    setSelectAll(checked);
    setSelectedIds(checked ? new Set(displayedFilters.map((f) => f.id)) : new Set());
  };

  const handlePolicyApply = async (filterId: string, policyId: string) => {
    try {
      await collectorApi.updateFilter(filterId, { applied_policy_id: policyId } as Partial<SambaSearchFilter>)
    } catch (e) {
      console.error('정책 적용 실패:', e)
      showAlert('정책 적용에 실패했습니다.', 'error')
      return
    }
    load(); loadTree();
  };

  // 그룹이름 수정
  const handleUpdateGroupName = async (filterId: string, newName: string) => {
    if (!newName.trim()) return;
    try {
      await collectorApi.updateFilter(filterId, { name: newName.trim() })
    } catch (e) {
      console.error('그룹이름 수정 실패:', e)
      showAlert('그룹이름 수정에 실패했습니다.', 'error')
      return
    }
    load(); loadTree();
  };

  // 요청상품수 수정
  const handleUpdateRequestedCount = async (filterId: string, count: number) => {
    if (isNaN(count) || count < 1) return;
    try {
      await collectorApi.updateFilter(filterId, { requested_count: count })
    } catch (e) {
      console.error('요청수 변경 실패:', e)
      showAlert('요청수 변경에 실패했습니다.', 'error')
      return
    }
    load(); loadTree();
  };

  // 수집상품수 클릭 → 상품관리 이동
  const handleGoToProducts = (f: SambaSearchFilter) => {
    const count = (f as unknown as Record<string, number>).collected_count ?? 0;
    if (count === 0) return;
    router.push(`/samba/products?search_filter_id=${f.id}&group_name=${encodeURIComponent(f.name)}`);
  };

  // 일괄 갱신 핸들러
  const handleRefresh = async () => {
    setRefreshing(true)
    const filterIds = selectedIds.size > 0 ? [...selectedIds] : undefined
    addLog(filterIds ? `선택된 ${filterIds.length}개 그룹 갱신 시작...` : '전체 일괄 갱신 시작...')
    try {
      const result = await collectorApi.refresh(undefined, true, filterIds)
      setRefreshResult(result)
      setShowRefreshModal(true)
      addLog(
        `갱신 완료: ${result.refreshed}건 갱신, ${result.changed}건 변동, ` +
        `${result.sold_out}건 품절, ${result.retransmitted}건 재전송`
      )
      load(); loadTree()
    } catch (e) {
      addLog(`갱신 실패: ${e instanceof Error ? e.message : '오류'}`)
      showAlert('일괄 갱신에 실패했습니다.', 'error')
    }
    setRefreshing(false)
  }

  // 그룹명에서 브랜드/카테고리 파싱: "MUSINSA_나이키_운동화" → {brand:"나이키", category:"운동화"}
  const parseGroupName = (name: string, site: string) => {
    let rest = name
    const prefixes = [site + '_', site.toLowerCase() + '_', '무신사_']
    for (const p of prefixes) {
      if (rest.toLowerCase().startsWith(p.toLowerCase())) {
        rest = rest.slice(p.length)
        break
      }
    }
    const parts = rest.split('_')
    if (parts.length >= 2) return { brand: parts[0], category: parts.slice(1).join('_') }
    const spaceParts = rest.split(' ')
    if (spaceParts.length >= 2) return { brand: spaceParts[0], category: spaceParts.slice(1).join(' ') }
    return { brand: rest, category: '' }
  }

  // 필터링 + 정렬 (메모이제이션)
  const displayedFilters = useMemo(() => {
    let result = [...filters]
    if (siteFilter) result = result.filter((f) => f.source_site === siteFilter)
    // 드릴다운 브랜드 선택 시 해당 브랜드 그룹만 표시
    if (drillBrand) {
      result = result.filter(f => {
        const parsed = parseGroupName(f.name, f.source_site || '')
        return parsed.brand === drillBrand
      })
    }
    if (aiFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const aiTagCount = r.ai_tagged_count ?? 0
        const aiImgCount = r.ai_image_count ?? 0
        switch (aiFilter) {
          case 'ai_tag_yes': return aiTagCount > 0
          case 'ai_tag_no': return aiTagCount === 0
          case 'ai_img_yes': return aiImgCount > 0
          case 'ai_img_no': return aiImgCount === 0
          default: return true
        }
      })
    }
    if (collectFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.collected_count ?? 0
        if (collectFilter === 'collected') return cnt > 0
        if (collectFilter === 'uncollected') return cnt === 0
        return true
      })
    }
    if (marketRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.market_registered_count ?? 0
        const total = r.collected_count ?? 0
        if (marketRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (marketRegFilter === 'partial') return cnt > 0 && cnt < total
        if (marketRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    if (tagRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.ai_tagged_count ?? 0
        const total = r.collected_count ?? 0
        if (tagRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (tagRegFilter === 'partial') return cnt > 0 && cnt < total
        if (tagRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    if (policyRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.policy_applied_count ?? 0
        const total = r.collected_count ?? 0
        if (policyRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (policyRegFilter === 'partial') return cnt > 0 && cnt < total
        if (policyRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    const [sortField, sortDir] = sortBy.split('_')
    result.sort((a, b) => {
      const va = sortField === 'lastCollectedAt' ? (a.last_collected_at || '') : (a.created_at || '')
      const vb = sortField === 'lastCollectedAt' ? (b.last_collected_at || '') : (b.created_at || '')
      return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
    })
    return result
  }, [filters, siteFilter, drillBrand, aiFilter, collectFilter, marketRegFilter, tagRegFilter, policyRegFilter, sortBy])



  return (
    <div style={{ color: '#E5E5E5' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0', padding: '0.5rem 1rem' }}>
      {/* 프록시 + 무신사 인증 상태 (1줄) */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '16px', padding: '6px 14px',
        borderRadius: '8px', marginBottom: '12px',
        background: 'rgba(255,140,0,0.07)', border: '1px solid rgba(255,140,0,0.2)',
        fontSize: '0.78rem',
      }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: proxyStatus === 'ok' ? '#51CF66' : proxyStatus === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: proxyStatus === 'ok' ? '#51CF66' : '#888' }}>{proxyText}</span>
        <span style={{ color: '#2D2D2D' }}>|</span>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: musinsaAuth === 'ok' ? '#51CF66' : musinsaAuth === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: musinsaAuth === 'ok' ? '#51CF66' : '#888' }}>{musinsaAuthText}</span>
        <button
          onClick={() => {
            setProxyStatus('checking')
            setProxyText('프록시 서버 확인 중...')
            fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`)
              .then(r => r.json())
              .then(data => {
                if (data.status === 'ok') { setProxyStatus('ok'); setProxyText(data.message || '프록시 서버 정상 작동 중') }
                else { setProxyStatus('error'); setProxyText(data.message || '프록시 서버 연결 실패') }
              })
              .catch(() => { setProxyStatus('error'); setProxyText('백엔드 서버 연결 실패') })
          }}
          style={{
            marginLeft: 'auto', background: 'transparent', border: '1px solid #3D3D3D',
            color: '#888', padding: '2px 10px', borderRadius: '4px', fontSize: '0.72rem', cursor: 'pointer',
          }}
        >재확인</button>
      </div>

      {/* 소싱처 선택 + URL 입력 영역 */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1.25rem", marginBottom: "1rem",
      }}>
        {/* 소싱처 선택 버튼 */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "0.875rem" }}>
          {/* 1행: 소싱처 버튼 + AI소싱기 */}
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
            {SITES.map((site) => (
              <button
                key={site.id}
                onClick={() => {
                  setSelectedSite(site.id)
                  setCollectUrl("")
                  setCheckedOptions(site.id === 'MUSINSA'
                    ? { excludePreorder: true, excludeBoutique: true, maxDiscount: true }
                    : {}
                  )
                }}
                style={{
                  padding: "0.35rem 0.875rem", borderRadius: "20px", fontSize: "0.8rem",
                  fontWeight: selectedSite === site.id ? 700 : 400, cursor: "pointer",
                  border: selectedSite === site.id ? "1px solid #FF8C00" : "1px solid #3D3D3D",
                  background: selectedSite === site.id ? "rgba(255,140,0,0.15)" : "transparent",
                  color: selectedSite === site.id ? "#FF8C00" : "#C5C5C5",
                  transition: "all 0.15s",
                }}
              >{site.label}</button>
            ))}
            <button
              onClick={() => {
                setShowAiSourcingModal(true)
                setAiSourcingStep('config')
                setAiResult(null)
                setAiLogs([])
                setAiSelectedCombos(new Set())
                setAiExcludedBrands(new Set())
                setAiExcludedKeywords(new Set())
              }}
              style={{
                marginLeft: 'auto', padding: '0.6rem 1.2rem', borderRadius: '6px',
                background: 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                color: '#fff', fontWeight: 600, fontSize: '0.82rem',
                border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              AI 소싱기
            </button>
          </div>
          {/* 2행: 선택된 소싱처 검색 조건 체크박스 (동적) */}
          {(SITE_OPTIONS[selectedSite] || []).length > 0 && (
            <div style={{ display: "flex", gap: "14px", paddingLeft: "4px" }}>
              {(SITE_OPTIONS[selectedSite] || []).map((opt) => (
                <label key={opt.id} style={{ display: "flex", alignItems: "center", gap: "5px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!checkedOptions[opt.id]}
                    onChange={(e) => setCheckedOptions((prev) => ({ ...prev, [opt.id]: e.target.checked }))}
                    style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "0.78rem", color: "#999" }}>{opt.label}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* URL 입력 */}
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.625rem" }}>
          <input
            type="text"
            value={collectUrl}
            onChange={(e) => setCollectUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateGroup()}
            placeholder={
              selectedSite === "MUSINSA" ? "브랜드명 또는 URL (예: 나이키, https://www.musinsa.com/search/goods?keyword=나이키)" :
              selectedSite === "KREAM" ? "https://kream.co.kr/search?keyword=나이키" :
              selectedSite === "LOTTEON" ? "키워드 또는 URL (예: 나이키, https://www.lotteon.com/search/...)" :
              "URL을 입력하세요"
            }
            style={{
              flex: 1, padding: "0.6rem 0.8rem", fontSize: "0.82rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
              color: "#E5E5E5", outline: "none",
            }}
          />
          {(selectedSite === 'MUSINSA' || selectedSite === 'LOTTEON') && (
            <button onClick={async () => {
              if (!collectUrl.trim()) { showAlert('URL 또는 키워드를 입력하세요'); return }
              setBrandScanning(true)
              setBrandCategories([]); setBrandSelectedCats(new Set())

              const parsed = (() => { try { return new URL(collectUrl) } catch { return null } })()
              // /brand/{name}/products 경로 패턴 지원
              const pathBrandMatch = parsed?.pathname.match(/\/brand\/([^/]+)/)
              const brand = parsed?.searchParams.get('brand') || pathBrandMatch?.[1] || ''
              const keyword = parsed?.searchParams.get('keyword') || parsed?.searchParams.get('searchWord') || (!brand ? collectUrl.trim() : '')
              const gf = parsed?.searchParams.get('gf') || 'A'
              if (!brand && !keyword) { showAlert('브랜드 또는 키워드를 확인하세요'); setBrandScanning(false); return }

              // 롯데ON: 브랜드 탐색 후 선택 모달 표시
              if (selectedSite === 'LOTTEON') {
                try {
                  const discoverKeyword = keyword || brand
                  const res = await collectorApi.brandDiscover(discoverKeyword, 'LOTTEON')
                  // 키워드와 정확 일치하는 브랜드만 기본 체크 (공백 제거 후 비교)
                  const normalizedKeyword = discoverKeyword.replace(/\s/g, '').toLowerCase()
                  const defaultSelected = new Set(
                    res.brands
                      .filter(b => b.name.replace(/\s/g, '').toLowerCase() === normalizedKeyword)
                      .map(b => b.name)
                  )
                  setBrandModalList(res.brands)
                  setBrandModalSelected(defaultSelected)
                  setBrandModalKeyword(discoverKeyword)
                  setBrandModalParsed({ brand, keyword, gf })
                  setShowBrandModal(true)
                } catch (e) { showAlert(e instanceof Error ? e.message : '브랜드 탐색 실패', 'error') }
                setBrandScanning(false)
                return
              }

              // 무신사: 기존 동작 유지
              try {
                const res = await collectorApi.brandScan(brand, gf, keyword, selectedSite)
                setBrandCategories(res.categories)
                setBrandTotal(res.total)
                setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                addLog(`[카테고리스캔] ${keyword || brand}: ${res.groupCount}개 카테고리, 총 ${res.total}건`)
              } catch (e) { showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
              setBrandScanning(false)
            }} disabled={brandScanning}
              style={{ padding: '0.6rem 1rem', background: brandScanning ? '#333' : 'transparent', border: '1px solid #FF8C00', borderRadius: '6px', color: '#FF8C00', fontSize: '0.82rem', fontWeight: 600, cursor: brandScanning ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
              {brandScanning ? '탐색 중...' : '카테고리 스캔'}
            </button>
          )}
          <button
            onClick={async () => {
              // 카테고리 스캔 결과가 있으면 선택된 카테고리별 그룹 생성
              if (brandCategories.length > 0 && brandSelectedCats.size > 0) {
                const selected = brandCategories.filter(c => brandSelectedCats.has(c.categoryCode))
                if (selected.length === 0) { showAlert('카테고리를 선택하세요'); return }
                const parsed = (() => { try { return new URL(collectUrl) } catch { return null } })()
                const pathBrandMatch = parsed?.pathname.match(/\/brand\/([^/]+)/)
                const brand = parsed?.searchParams.get('brand') || pathBrandMatch?.[1] || ''
                const keyword = parsed?.searchParams.get('keyword') || parsed?.searchParams.get('searchWord') || (!brand ? collectUrl.trim() : '')
                const gf = parsed?.searchParams.get('gf') || 'A'
                try {
                  const res = await collectorApi.brandCreateGroups({
                    brand, brand_name: keyword || brand, gf,
                    categories: selected,
                    requested_count_per_group: -1,
                    real_total: brandTotal,
                    options: checkedOptions,
                    source_site: selectedSite,
                    selected_brands: brandModalParsed ? Array.from(brandModalSelected) : undefined,
                  })
                  addLog(`[카테고리분류] ${res.created}개 그룹 생성 완료`)
                  showAlert(`${res.created}개 그룹이 생성되었습니다`, 'success')
                  addLog(`[카테고리분류] ${res.created}개 그룹 생성 (카테고리 간 중복은 수집 시 자동 스킵)`)
                  setBrandCategories([]); setBrandSelectedCats(new Set())
                  load(); loadTree()
                } catch (e) { showAlert(e instanceof Error ? e.message : '그룹 생성 실패', 'error') }
              } else {
                // 카테고리 스캔 없으면 기존 단일 그룹 생성
                handleCreateGroup()
              }
            }}
            disabled={collecting}
            style={{
              background: "linear-gradient(135deg, #FF8C00, #FFB84D)", color: "#fff",
              padding: "0.6rem 1.2rem", borderRadius: "6px", fontWeight: 600, fontSize: "0.82rem",
              whiteSpace: "nowrap", cursor: collecting ? "not-allowed" : "pointer",
              border: "none", opacity: collecting ? 0.6 : 1,
            }}
          >
            {collecting ? "생성중..." : brandCategories.length > 0 ? `그룹 생성 (${brandSelectedCats.size}개)` : "그룹 생성"}
          </button>
        </div>

        {/* 카테고리 스캔 결과 */}
        {brandCategories.length > 0 && (
          <div style={{ marginTop: '0.5rem' }}>
              <div style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem', maxHeight: '350px', overflowY: 'auto' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span style={{ fontSize: '0.78rem', color: '#888' }}>
                    {brandCategories.length}개 카테고리 / {brandTotal.toLocaleString()}건
                    (선택 {brandSelectedCats.size}개)
                  </span>
                  <div style={{ display: 'flex', gap: '0.25rem' }}>
                    <button onClick={() => setBrandSelectedCats(new Set(brandCategories.map(c => c.categoryCode)))}
                      style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>전체선택</button>
                    <button onClick={() => setBrandSelectedCats(new Set())}
                      style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>전체해제</button>
                    <button onClick={() => { setBrandCategories([]); setBrandSelectedCats(new Set()) }}
                      style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}>초기화</button>
                  </div>
                </div>
                {brandCategories.map(cat => (
                  <label key={cat.categoryCode} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.2rem 0', cursor: 'pointer', fontSize: '0.78rem' }}>
                    <input type="checkbox" checked={brandSelectedCats.has(cat.categoryCode)}
                      onChange={e => {
                        const next = new Set(brandSelectedCats)
                        if (e.target.checked) next.add(cat.categoryCode); else next.delete(cat.categoryCode)
                        setBrandSelectedCats(next)
                      }} style={{ accentColor: '#FF8C00' }} />
                    <span style={{ color: '#E5E5E5', flex: 1 }}>{cat.path}</span>
                    <span style={{ color: '#FF8C00', fontWeight: 600, fontSize: '0.72rem' }}>{cat.count.toLocaleString()}건</span>
                  </label>
                ))}
                <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'flex-end' }}>
                  <button onClick={async () => {
                    const selected = brandCategories.filter(c => brandSelectedCats.has(c.categoryCode))
                    if (selected.length === 0) { showAlert('카테고리를 선택하세요'); return }
                    const parsed = (() => { try { return new URL(collectUrl) } catch { return null } })()
                    const pathBrandMatch = parsed?.pathname.match(/\/brand\/([^/]+)/)
                    const brand = parsed?.searchParams.get('brand') || pathBrandMatch?.[1] || ''
                    const keyword = parsed?.searchParams.get('keyword') || parsed?.searchParams.get('searchWord') || (!brand ? collectUrl.trim() : '')
                    const gf = parsed?.searchParams.get('gf') || 'A'
                    try {
                      const res = await collectorApi.brandCreateGroups({
                        brand, brand_name: keyword || brand, gf,
                        categories: selected,
                        requested_count_per_group: -1,
                        real_total: brandTotal,
                        options: checkedOptions,
                        source_site: selectedSite,
                        selected_brands: brandModalParsed ? Array.from(brandModalSelected) : undefined,
                      })
                      addLog(`[카테고리분류] ${res.created}개 그룹 생성 완료`)
                      showAlert(`${res.created}개 그룹이 생성되었습니다`, 'success')
                      setBrandCategories([]); setBrandSelectedCats(new Set())
                      load()
                    } catch (e) { showAlert(e instanceof Error ? e.message : '그룹 생성 실패', 'error') }
                  }}
                    style={{ padding: '0.4rem 1rem', background: '#FF8C00', border: 'none', borderRadius: '6px', color: '#fff', fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer' }}>
                    선택 그룹 생성 ({brandSelectedCats.size}개)
                  </button>
                </div>
              </div>
            </div>
        )}
      </div>

      {/* 롯데ON 브랜드 선택 모달 */}
      {showBrandModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '10px',
            padding: '1.5rem', width: '420px', maxWidth: '90vw',
          }}>
            {/* 모달 헤더 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#E5E5E5' }}>
                브랜드 선택 — &quot;{brandModalKeyword}&quot;
              </span>
              <button
                onClick={() => setShowBrandModal(false)}
                style={{ background: 'none', border: 'none', color: '#666', fontSize: '1.1rem', cursor: 'pointer' }}
              >&times;</button>
            </div>

            {/* 전체선택/해제 */}
            <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '0.75rem' }}>
              <button
                onClick={() => setBrandModalSelected(new Set(brandModalList.map(b => b.name)))}
                style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}
              >전체선택</button>
              <button
                onClick={() => setBrandModalSelected(new Set())}
                style={{ fontSize: '0.72rem', padding: '3px 8px', borderRadius: '4px', border: '1px solid #3D3D3D', background: 'transparent', color: '#888', cursor: 'pointer' }}
              >전체해제</button>
              <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: '#666', alignSelf: 'center' }}>
                {brandModalSelected.size}/{brandModalList.length}개 선택
              </span>
            </div>

            {/* 브랜드 목록 */}
            <div style={{ maxHeight: '300px', overflowY: 'auto', marginBottom: '1rem' }}>
              {brandModalList.map(b => (
                <label key={b.name} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.3rem 0', cursor: 'pointer', fontSize: '0.82rem' }}>
                  <input
                    type="checkbox"
                    checked={brandModalSelected.has(b.name)}
                    onChange={e => {
                      const next = new Set(brandModalSelected)
                      if (e.target.checked) next.add(b.name); else next.delete(b.name)
                      setBrandModalSelected(next)
                    }}
                    style={{ accentColor: '#FF8C00' }}
                  />
                  <span style={{ color: '#E5E5E5', flex: 1 }}>{b.name}</span>
                  <span style={{ color: '#FF8C00', fontWeight: 600, fontSize: '0.75rem' }}>{b.count.toLocaleString()}건</span>
                </label>
              ))}
            </div>

            {/* 취소 / 스캔 진행 버튼 */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button
                onClick={() => setShowBrandModal(false)}
                style={{ padding: '0.5rem 1rem', background: 'transparent', border: '1px solid #3D3D3D', borderRadius: '6px', color: '#888', fontSize: '0.82rem', cursor: 'pointer' }}
              >취소</button>
              <button
                onClick={async () => {
                  if (brandModalSelected.size === 0) { showAlert('브랜드를 1개 이상 선택하세요'); return }
                  setShowBrandModal(false)
                  setBrandScanning(true)
                  setBrandCategories([]); setBrandSelectedCats(new Set())
                  const { brand, keyword, gf } = brandModalParsed || { brand: '', keyword: brandModalKeyword, gf: 'A' }
                  const selectedBrands = Array.from(brandModalSelected)
                  try {
                    const res = await collectorApi.brandScan(brand, gf, keyword, 'LOTTEON', selectedBrands)
                    setBrandCategories(res.categories)
                    setBrandTotal(res.total)
                    setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                    addLog(`[카테고리스캔] ${keyword || brand} (${selectedBrands.length}개 브랜드): ${res.groupCount}개 카테고리, 총 ${res.total}건`)
                  } catch (e) { showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
                  setBrandScanning(false)
                }}
                disabled={brandModalSelected.size === 0}
                style={{
                  padding: '0.5rem 1.2rem', background: brandModalSelected.size === 0 ? '#333' : '#FF8C00',
                  border: 'none', borderRadius: '6px', color: '#fff', fontSize: '0.82rem',
                  fontWeight: 600, cursor: brandModalSelected.size === 0 ? 'not-allowed' : 'pointer',
                }}
              >카테고리 스캔 진행 ({brandModalSelected.size}개)</button>
            </div>
          </div>
        </div>
      )}

      {/* 로그현황 */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        overflow: "hidden", marginBottom: "1rem",
      }}>
        <div style={{
          padding: "8px 16px", borderBottom: "1px solid #2D2D2D",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#C5C5C5" }}>로그현황</span>
          <div style={{ display: "flex", gap: "4px" }}>
            {collecting && (
              <button onClick={handleStopCollect} style={{
                fontSize: "0.75rem", color: "#FF6B6B", background: "rgba(255,100,100,0.1)",
                border: "1px solid rgba(255,100,100,0.4)", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
              }}>수집 중단</button>
            )}
            <button onClick={handleCopyLog} style={{
              fontSize: "0.75rem", color: "#888", background: "transparent",
              border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
            }}>복사</button>
            <button onClick={handleClearLog} style={{
              fontSize: "0.75rem", color: "#888", background: "transparent",
              border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
            }}>초기화</button>
          </div>
        </div>
        <div
          ref={logRef}
          style={{
            height: "160px", overflowY: "auto", padding: "10px 16px",
            fontFamily: "monospace", fontSize: "0.78rem", color: "#8A95B0", zoom: "0.7",
            background: "#080A10", lineHeight: 1.6,
          }}
        >
          {collectLog.map((line, i) => (
            <p key={i} style={{
              color: line.includes("완료") ? "#51CF66"
                : line.includes("실패") || line.includes("오류") ? "#FF6B6B"
                : line.includes("대기") || line.includes("초기화") ? "#555"
                : "#8A95B0",
              margin: 0,
            }}>
              {line}
            </p>
          ))}
        </div>
      </div>

      {/* AI비용 + AI이미지변환 + 이미지필터링 — 3단 나란히 배치 */}
      <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 1.3fr 1fr', gap: '8px', marginTop: '1.25rem' }}>
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
        {/* AI 이미지 변환 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 이미지 변환</span>
          <select value={aiImgMode} onChange={e => setAiImgMode(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
            <option value="background">배경 제거</option>
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
          <span style={{ fontSize: '0.78rem', color: '#888' }}>({selectedIds.size}개 그룹)</span>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
              // displayedFilters와 교집합으로 실제 대상 결정
              const activeIds = [...selectedIds].filter(id => displayedFilters.some(f => f.id === id))
              if (activeIds.length === 0) { showAlert('현재 필터에 해당하는 그룹이 없습니다'); return }
              // 그룹에 속한 상품 조회 → AI 미변환 상품만 추출
              const productIds: string[] = []
              let skippedAi = 0
              for (const gid of activeIds) {
                try {
                  const products = await collectorApi.listProducts(0, 10000, gid)
                  if (Array.isArray(products)) {
                    for (const p of products) {
                      if ((p.tags || []).includes('__ai_image__')) { skippedAi++; continue }
                      productIds.push(p.id)
                    }
                  }
                } catch { /* 스킵 */ }
              }
              if (productIds.length === 0) { showAlert(skippedAi > 0 ? `모든 상품이 이미 AI 변환 완료 (${skippedAi}건 스킵)` : '선택된 그룹에 상품이 없습니다'); return }
              const skipMsg = skippedAi > 0 ? `\n(AI 변환 완료 ${skippedAi}건 스킵)` : ''
              const ok = await showConfirm(`${activeIds.length}개 그룹 (${productIds.length}개 상품)의 이미지를 변환하시겠습니까?${skipMsg}`)
              if (!ok) return
              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
              setAiImgTransforming(true)
              aiJobAbortRef.current = false
              setAiJobTitle(`AI 이미지변환 (${productIds.length}개)`)
              setAiJobLogs([])
              setAiJobDone(false)
              setAiJobModal(true)
              const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
              const startTime = ts()
              addLog(`시작: ${startTime} (${productIds.length}개 상품)`)
              let success = 0
              let fail = 0
              for (let i = 0; i < productIds.length; i++) {
                if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${i}/${productIds.length})`); break }
                const label = productIds[i].slice(-8)
                setAiJobTitle(`AI 이미지변환 [${i + 1}/${productIds.length}]`)
                try {
                  const res = await proxyApi.transformImages([productIds[i]], { thumbnail: true, additional: true, detail: true }, aiImgMode, aiModelPreset)
                  if (res.success) { success++; addLog(`[${ts()}] [${i + 1}/${productIds.length}] ${label} — 완료`) }
                  else { fail++; addLog(`[${ts()}] [${i + 1}/${productIds.length}] ${label} — 실패: ${res.message}`) }
                } catch (e) { fail++; addLog(`[${ts()}] [${i + 1}/${productIds.length}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
              }
              const endTime = ts()
              setAiJobTitle(`AI 이미지변환 완료 (${success}/${productIds.length})`)
              addLog(`\n완료: 성공 ${success}개 / 실패 ${fail}개`)
              addLog(`시작 ${startTime} → 종료 ${endTime}`)
              setAiJobDone(true)
              setAiImgTransforming(false)
              const cnt = success
              setLastAiUsage({ calls: cnt, tokens: cnt * 2000, cost: cnt * 3, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
              setSelectedIds(new Set()); setSelectAll(false)
            }}
            disabled={aiImgTransforming || selectedIds.size === 0}
            style={{ marginLeft: 'auto', background: aiImgTransforming ? '#333' : 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)', color: aiImgTransforming ? '#888' : '#FF8C00', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: aiImgTransforming ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
          >{aiImgTransforming ? '변환중...' : '변환 실행'}</button>
        </div>

        {/* 이미지 필터링 */}
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
              if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
              if (imgFilterScopes.size === 0) { showAlert('필터링 대상을 선택해주세요'); return }
              // displayedFilters와 교집합으로 실제 대상 결정
              const activeGroupIds = [...selectedIds].filter(id => displayedFilters.some(f => f.id === id))
              if (activeGroupIds.length === 0) { showAlert('현재 필터에 해당하는 그룹이 없습니다'); return }
              const scopeLabel = [...imgFilterScopes].map(s => s === 'images' ? '대표' : s === 'detail_images' ? '추가' : '상세').join('+')
              const ok = await showConfirm(`선택된 ${activeGroupIds.length}개 그룹의 ${scopeLabel} 이미지를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
              if (!ok) return
              const scope = imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') && imgFilterScopes.has('detail') ? 'all' : imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') ? 'images' : imgFilterScopes.has('detail') ? 'detail' : [...imgFilterScopes][0] || 'images'
              setImgFiltering(true)
              aiJobAbortRef.current = false
              setAiJobTitle(`이미지 필터링 (${activeGroupIds.length}개 그룹)`)
              setAiJobLogs([])
              setAiJobDone(false)
              setAiJobModal(true)
              const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
              const startTime = ts()
              let success = 0
              let fail = 0
              let totalTall = 0
              let totalVisionRemoved = 0
              try {
                // 그룹별로 상품 목록을 가져와 상품관리와 동일하게 개별 처리
                const groupIds = activeGroupIds
                let totalProducts = 0
                let processedProducts = 0
                for (let gi = 0; gi < groupIds.length; gi++) {
                  if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단`); break }
                  const gid = groupIds[gi]
                  const groupLabel = tree.find(t => t.id === gid)?.keyword?.slice(0, 20) || gid.slice(-8)
                  addLog(`\n[그룹 ${gi + 1}/${groupIds.length}] ${groupLabel} — 상품 조회중...`)
                  try {
                    const { items: products } = await collectorApi.scrollProducts({ search_filter_id: gid, limit: 10000 })
                    totalProducts += products.length
                    addLog(`[그룹 ${gi + 1}/${groupIds.length}] ${groupLabel} — ${products.length}개 상품`)
                    if (gi === 0 && products.length > 0) addLog(`\n시작: ${startTime} (${totalProducts}개 상품)\n`)
                    for (let i = 0; i < products.length; i++) {
                      if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${processedProducts}/${totalProducts})`); break }
                      const prod = products[i]
                      const prodName = prod.name?.slice(0, 25) || '이름없음'
                      const prodNo = prod.site_product_id || prod.id.slice(-8)
                      const prodBrand = prod.brand || '-'
                      const label = `${prodBrand} / ${prodNo} / ${prodName}${prod.name && prod.name.length > 25 ? '...' : ''}`
                      processedProducts++
                      setAiJobTitle(`이미지 필터링 [${processedProducts}/${totalProducts}] ${prodBrand} / ${prodNo}`)
                      try {
                        const steps: string[] = []
                        // 1) 프론트에서 추가이미지 비율 체크 (세로 2배 이상 → 제거)
                        if (scope === 'detail_images' || scope === 'images' || scope === 'all') {
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
                            const tallUrls = imgs.slice(1).filter((_, idx) => tallCheck[idx])
                            if (tallUrls.length > 0) {
                              const kept = imgs.filter(u => !tallUrls.includes(u))
                              await collectorApi.updateProduct(prod.id, { images: kept })
                              totalTall += tallUrls.length
                              steps.push(`긴이미지 ${tallUrls.length}장 제거`)
                            }
                          }
                        }
                        // 2) 백엔드 이미지 필터링 (CLIP)
                        const r = await proxyApi.filterProductImages([prod.id], '', scope)
                        if (r.success) {
                          success++
                          const removed = r.total_removed || 0
                          totalVisionRemoved += removed
                          if (removed > 0) steps.push(`CLIP ${removed}장 제거`)
                          else steps.push('CLIP 변동없음')
                          addLog(`[${ts()}] [${processedProducts}/${totalProducts}] ${label} — ${steps.join(' → ')}`)
                        } else { fail++; addLog(`[${ts()}] [${processedProducts}/${totalProducts}] ${label} — ${steps.length > 0 ? steps.join(' → ') + ' → ' : ''}실패`) }
                      } catch (e) { fail++; addLog(`[${ts()}] [${processedProducts}/${totalProducts}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
                    }
                  } catch (e) {
                    addLog(`[그룹 ${gi + 1}/${groupIds.length}] ${groupLabel} — 상품 조회 실패: ${e instanceof Error ? e.message : ''}`)
                  }
                }
                const summary = [`성공 ${success}개`, `실패 ${fail}개`]
                if (totalTall > 0) summary.push(`긴이미지 ${totalTall}장 제거`)
                if (totalVisionRemoved > 0) summary.push(`CLIP ${totalVisionRemoved}장 제거`)
                const endTime = ts()
                setAiJobTitle(`이미지 필터링 완료 (${success}/${totalProducts})`)
                addLog(`\n완료: ${summary.join(' / ')}`)
                addLog(`시작 ${startTime} → 종료 ${endTime}`)
              } catch (e) { addLog(`오류: ${e instanceof Error ? e.message : '오류'}`) }
              finally {
                setAiJobDone(true)
                setImgFiltering(false)
                const apiCalls = success + fail
                setLastAiUsage({ calls: apiCalls, tokens: apiCalls * 1000, cost: apiCalls * 15, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
                setSelectedIds(new Set()); setSelectAll(false)
                load(); loadTree()
              }
            }}
            disabled={imgFiltering || selectedIds.size === 0}
            style={{ marginLeft: 'auto', background: imgFiltering ? '#333' : 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.35)', color: imgFiltering ? '#888' : '#818CF8', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: imgFiltering ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
          >{imgFiltering ? '필터링중...' : `필터링 실행 (${selectedIds.size}개)`}</button>
        </div>
      </div>

      {/* 검색그룹 드릴다운 */}
      <div style={{ marginTop: '1rem' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: '0.75rem', flexWrap: 'wrap', gap: '8px',
        }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>검색그룹 목록</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <select value={collectFilter} onChange={e => setCollectFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: collectFilter ? '#F59E0B' : '#888', cursor: 'pointer' }}>
              <option value="">상품수집</option>
              <option value="collected">수집</option>
              <option value="uncollected">미수집</option>
            </select>
            <select value={marketRegFilter} onChange={e => setMarketRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: marketRegFilter ? '#4C9AFF' : '#888', cursor: 'pointer' }}>
              <option value="">마켓등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={tagRegFilter} onChange={e => setTagRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: tagRegFilter ? '#51CF66' : '#888', cursor: 'pointer' }}>
              <option value="">태그등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={policyRegFilter} onChange={e => setPolicyRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: policyRegFilter ? '#FF8C00' : '#888', cursor: 'pointer' }}>
              <option value="">정책등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <button
              onClick={handleDeleteSelectedGroups}
              style={{
                background: 'rgba(255,100,100,0.1)', border: '1px solid rgba(255,100,100,0.3)',
                color: '#FF6B6B', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              그룹 삭제
            </button>
            <button
              onClick={handleCollectGroups}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              상품수집
            </button>
            <button
              onClick={async () => {
                const targets = selectedIds.size > 0
                  ? displayedFilters.filter(f => selectedIds.has(f.id))
                  : displayedFilters
                if (targets.length === 0) { showAlert('동기화할 그룹이 없습니다'); return }
                const mismatch = targets.filter(f => (f.requested_count || 0) !== (f.collected_count || 0))
                if (mismatch.length === 0) { showAlert('모든 그룹이 이미 동기화되어 있습니다', 'info'); return }
                if (!await showConfirm(`${mismatch.length}개 그룹의 요청수를 수집수로 동기화하시겠습니까?`)) return
                let synced = 0
                for (const f of mismatch) {
                  try {
                    await collectorApi.updateFilter(f.id, { requested_count: f.collected_count || 0 })
                    synced++
                  } catch { /* skip */ }
                }
                showAlert(`${synced}개 그룹 동기화 완료`, 'success')
                load(); loadTree()
              }}
              style={{
                background: 'rgba(100,200,255,0.1)', border: '1px solid rgba(100,200,255,0.3)',
                color: '#64C8FF', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              수집동기화
            </button>
            <button
                onClick={async () => {
                  // 표시된 그룹에서 브랜드 정보 추출
                  const sampleFilter = displayedFilters[0]
                  if (!sampleFilter) { showAlert('표시된 그룹이 없습니다'); return }
                  const parsed = (() => { try { return new URL(sampleFilter.keyword || '') } catch { return null } })()
                  const brand = parsed?.searchParams.get('brand') || ''
                  const gf = parsed?.searchParams.get('gf') || 'A'
                  if (!brand) { showAlert('브랜드 정보를 찾을 수 없습니다 (그룹 URL에 brand 파라미터 필요)'); return }
                  const brandName = drillBrand || brand
                  const ok = await showConfirm(`${brandName} 추가수집을 실행하시겠습니까?\n\n• 신규 카테고리 → 그룹 자동 생성\n• 기존 카테고리 → 요청수 갱신 후 수집`)
                  if (!ok) return
                  addLog(`[추가수집] ${brandName} 카테고리 스캔 중...`)
                  try {
                    const res = await collectorApi.brandRefresh({ brand, brand_name: brandName, gf, options: checkedOptions })
                    addLog(`[추가수집] ${res.message}`)
                    await load(); await loadTree()
                    // 갱신 후 자동 수집 시작
                    const updatedFilters = (await collectorApi.listFilters()).filter(f => {
                      const p = (() => { try { return new URL(f.keyword || '') } catch { return null } })()
                      return p?.searchParams.get('brand') === brand
                    })
                    if (updatedFilters.length > 0) {
                      const collectOk = await showConfirm(`${res.message}\n\n${updatedFilters.length}개 그룹 상품수집을 시작하시겠습니까?`)
                      if (collectOk) {
                        const abort = new AbortController()
                        collectAbortRef.current = abort
                        setCollecting(true)
                        addLog(`${updatedFilters.length}개 그룹 상품수집 시작...`)
                        for (const f of updatedFilters) {
                          if (abort.signal.aborted) break
                          addLog(`[${f.name}] 수집 요청 중...`)
                          try {
                            const r = await fetch(`${API_BASE}/api/v1/samba/collector/collect-filter/${f.id}`, { method: 'POST' })
                            if (!r.ok) { addLog(`[${f.name}] 수집 실패: HTTP ${r.status}`); continue }
                            const { job_id } = await r.json()
                            // 수집 시작 로그 생략
                            let lastCurrent = 0
                            while (!abort.signal.aborted) {
                              await new Promise(r => setTimeout(r, 1000))
                              if (abort.signal.aborted) break
                              const jr = await fetch(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                              if (!jr.ok) break
                              const job = await jr.json()
                              if (job.current > lastCurrent) { addLog(`[${f.name}] [${job.current}/${job.total}] 수집 중... (${job.progress}%)`); lastCurrent = job.current }
                              if (job.status === 'completed') {
                                const _s = job.result?.saved ?? 0, _sk = job.result?.skipped ?? 0, _p = job.result?.policy || ''
                                const _parts = [`신규 ${_s}건`]
                                if (_sk > 0) _parts.push(`중복 ${_sk}건`)
                                if (_p) _parts.push(_p)
                                addLog(`[${f.name}] 수집 완료: ${_parts.join(' | ')}`)
                                break
                              }
                              if (job.status === 'failed') { addLog(`[${f.name}] 수집 실패: ${job.error || '오류'}`); break }
                            }
                          } catch (e) { addLog(`[${f.name}] 수집 오류: ${(e as Error).message}`) }
                        }
                        setCollecting(false)
                        await syncRequestedCounts()
                        load(); loadTree()
                      }
                    }
                  } catch (e) { showAlert(e instanceof Error ? e.message : '추가수집 실패', 'error') }
                }}
                style={{
                  background: 'rgba(81,207,102,0.1)', border: '1px solid rgba(81,207,102,0.35)',
                  color: '#51CF66', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
                }}
              >
                추가수집
              </button>
            <button
              disabled={tagPreviewLoading}
              onClick={async () => {
                // 체크박스로 선택된 그룹만 (드릴다운 단독 선택은 무시 — 전체 처리)
                const isDrillOnly = drillGroup && selectedIds.size === 1 && selectedIds.has(drillGroup)
                const checkedIds = selectAll ? displayedFilters.map(f => f.id) : isDrillOnly ? [] : [...selectedIds]
                // displayedFilters와 교집합으로 실제 대상 결정
                const targetFilters = checkedIds.length > 0
                  ? displayedFilters.filter(f => checkedIds.includes(f.id))
                  : [...displayedFilters]
                if (targetFilters.length === 0) { showAlert('검색그룹이 없습니다'); return }
                const ok = await showConfirm(`${checkedIds.length > 0 ? '선택된' : '전체'} ${targetFilters.length}개 그룹의 상품에 AI 태그를 생성하시겠습니까?\n(그룹별 대표 1개로 API 호출, 미리보기 후 확정)`)
                if (!ok) return
                setTagPreviewLoading(true)
                try {
                  addLog(`[AI태그] ${targetFilters.length}개 그룹 태그 생성 시작...`)
                  const allPreviews: typeof tagPreviews = []
                  let totalCalls = 0, totalInput = 0, totalOutput = 0, totalCost = 0
                  for (let i = 0; i < targetFilters.length; i++) {
                    const f = targetFilters[i]
                    await new Promise(r => setTimeout(r, 50))
                    try {
                      const res = await proxyApi.previewAiTags([], [f.id])
                      if (res.success && res.previews?.length > 0) {
                        allPreviews.push(...res.previews)
                        totalCalls += res.api_calls || 0
                        totalInput += res.input_tokens || 0
                        totalOutput += res.output_tokens || 0
                        totalCost += res.cost_krw || 0
                        const tags = res.previews[0]?.tags || []
                        const seo = res.previews[0]?.seo_keywords || []
                        addLog(`[AI태그] [${i + 1}/${targetFilters.length}] ${f.name} → SEO: ${seo.join(', ')} | 태그: ${tags.length}개`)
                      } else {
                        addLog(`[AI태그] [${i + 1}/${targetFilters.length}] ${f.name} → 태그 없음`)
                      }
                    } catch (e) {
                      addLog(`[AI태그] [${i + 1}/${targetFilters.length}] ${f.name} → 실패: ${e instanceof Error ? e.message : '오류'}`)
                    }
                  }
                  addLog(`[AI태그] 완료: ${allPreviews.length}/${targetFilters.length}개 그룹 | API ${totalCalls}회 | ${totalCost.toFixed(0)}원`)
                  if (allPreviews.length > 0) {
                    setTagPreviews(allPreviews)
                    setTagPreviewCost({ api_calls: totalCalls, input_tokens: totalInput, output_tokens: totalOutput, cost_krw: totalCost })
                    setRemovedTags([])
                    setShowTagPreview(true)
                  } else {
                    showAlert('생성된 태그가 없습니다', 'info')
                  }
                } catch (e) {
                  showAlert(`태그 생성 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
                } finally {
                  setTagPreviewLoading(false)
                }
              }}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem',
                cursor: tagPreviewLoading ? 'not-allowed' : 'pointer', opacity: tagPreviewLoading ? 0.6 : 1,
              }}
            >
              {tagPreviewLoading ? '태그 생성중...' : 'AI태그'}
            </button>
          </div>
        </div>

        <div style={{
          marginBottom: '0.75rem', padding: '0.5rem 0.875rem', borderRadius: '8px',
          background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.2)',
          fontSize: '0.8rem', color: '#888',
        }}>
          ※ 정책 우선순위: <span style={{ color: '#FF8C00' }}>[상품별 개별정책]</span> → <span style={{ color: '#FF8C00' }}>[카테고리 정책]</span> 순으로 적용됩니다
          <span style={{ float: 'right', color: '#E5E5E5', fontWeight: 600 }}>
            수집 <span style={{ color: '#FF8C00' }}>{filters.reduce((s, f) => s + ((f as unknown as Record<string, number>).collected_count ?? 0), 0).toLocaleString()}</span>
            <span style={{ color: '#555' }}> / </span>
            요청 <span style={{ color: '#FFB84D' }}>{filters.filter(f => !f.is_folder).reduce((s, f) => s + (f.requested_count ?? 0), 0).toLocaleString()}</span>
          </span>
        </div>

        {/* 검색그룹 드릴다운 — 사이트 > 브랜드 > 카테고리 > 상세(링크/정책/스스브랜드/수집/요청/생성일) */}
        {(() => {
          // 헬퍼: 사이트 하위 모든 리프 그룹
          const getAllLeaves = (node: SambaSearchFilter | undefined): SambaSearchFilter[] => {
            if (!node) return []
            const result: SambaSearchFilter[] = []
            const walk = (n: SambaSearchFilter) => {
              if (!n.is_folder) result.push(n)
              ;(n.children || []).forEach(walk)
            }
            ;(node.children || []).forEach(walk)
            return result
          }
          // 전체 사이트별 리프 + 브랜드/카테고리 파싱 (크로스 필터용)
          const allLeafInfosRaw = tree.flatMap(s =>
            getAllLeaves(s).map(l => {
              const parsed = parseGroupName(l.name, s.source_site || '')
              return { ...l, _siteId: s.id, _siteSite: s.source_site || '', _brand: parsed.brand, _category: parsed.category }
            })
          )
          // 상품수집 + 태그등록 + 정책등록 드롭박스 필터 적용
          let allLeafInfos = [...allLeafInfosRaw]
          if (collectFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const cnt = (l as unknown as Record<string, number>).collected_count ?? 0
              return collectFilter === 'collected' ? cnt > 0 : cnt === 0
            })
          }
          if (tagRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const r = l as unknown as Record<string, number>
              const cnt = r.ai_tagged_count ?? 0
              const total = r.collected_count ?? 0
              if (tagRegFilter === 'registered') return cnt > 0 && cnt >= total
              if (tagRegFilter === 'partial') return cnt > 0 && cnt < total
              if (tagRegFilter === 'unregistered') return cnt === 0
              return true
            })
          }
          if (policyRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const hasPolicy = !!(l as unknown as Record<string, string>).applied_policy_id
              if (policyRegFilter === 'registered') return hasPolicy
              if (policyRegFilter === 'unregistered') return !hasPolicy
              return true
            })
          }
          // 크로스 필터: 사이트 목록 (선택된 브랜드 기준 필터)
          const baseSites = collectFilter
            ? tree.filter(s => allLeafInfos.some(l => l._siteId === s.id))
            : tree
          const filteredSites = drillBrand
            ? baseSites.filter(s => allLeafInfos.some(l => l._siteId === s.id && l._brand === drillBrand))
            : baseSites
          // 크로스 필터: 브랜드 목록 (선택된 사이트 기준 필터)
          const brandLeaves = drillSite
            ? allLeafInfos.filter(l => l._siteId === drillSite)
            : allLeafInfos
          const brandMap = new Map<string, number>()
          brandLeaves.forEach(l => brandMap.set(l._brand, (brandMap.get(l._brand) || 0) + 1))
          const brands = Array.from(brandMap.entries()).sort((a, b) => a[0].localeCompare(b[0], 'ko'))
          // 카테고리 그룹 (사이트+브랜드 교차 필터)
          let catLeaves = allLeafInfos
          if (drillSite) catLeaves = catLeaves.filter(l => l._siteId === drillSite)
          if (drillBrand) catLeaves = catLeaves.filter(l => l._brand === drillBrand)
          const catGroups = (drillSite && drillBrand) ? catLeaves.sort((a, b) => a._category.localeCompare(b._category, 'ko')) : []
          // 선택된 그룹 상세
          const selectedFilter = drillGroup ? filters.find(fl => fl.id === drillGroup) : null
          const selectedCount = selectedFilter ? ((selectedFilter as unknown as Record<string, number>).collected_count ?? 0) : 0

          // 헤더·본문 너비 통일 (합계 100%)
          // 사이트8 브랜드8 카테고리24 링크15 정책10 수집8 요청6 생성일11 매핑10
          const colW = ['8%', '8%', '24%', '15%', '10%', '8%', '6%', '11%', '10%']
          const colBase = { borderRight: '1px solid #2D2D2D', maxHeight: '320px', overflowY: 'auto' as const, boxSizing: 'border-box' as const, textAlign: 'center' as const }
          const colStyle = (i: number) => ({ ...colBase, width: colW[i], flexShrink: 0 })
          const detColStyle = (i: number) => ({ ...colBase, width: colW[i], flexShrink: 0, padding: '0.5rem 0.5rem' })
          const itemSt = (sel: boolean) => ({
            padding: '0.5rem 0.75rem', fontSize: '0.8125rem',
            color: sel ? '#FF8C00' : '#C5C5C5', cursor: 'pointer' as const,
            background: sel ? 'rgba(255,140,0,0.08)' : 'transparent',
            transition: 'background 0.15s',
            display: 'flex' as const, alignItems: 'center' as const, gap: '4px',
          })

          return (
            <div style={{
              background: 'rgba(30,30,30,0.5)', border: '1px solid #2D2D2D',
              borderRadius: '8px', overflow: 'hidden', marginBottom: '1rem',
            }}>
              {/* 헤더 */}
              <div style={{ display: 'flex', borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
                {['사이트', '브랜드', '카테고리', '링크', '정책', '수집', '요청', '생성일/최근수집', '매핑'].map((h, i) => (
                  <div key={h} style={{
                    width: colW[i], flexShrink: 0, boxSizing: 'border-box' as const,
                    padding: '0.5rem 0.5rem', textAlign: 'center' as const,
                    fontSize: '0.72rem', fontWeight: 600,
                    color: (i === 0 && (drillEntry === 'site' || drillSite)) || (i === 1 && (drillEntry === 'brand' || drillBrand)) || (i === 2 && drillGroup) ? '#FF8C00' : '#888',
                    borderRight: i < 8 ? '1px solid #2D2D2D' : 'none',
                    cursor: i < 3 ? 'pointer' : 'default',
                  }}
                  onClick={() => {
                    if (i === 0) { setDrillEntry('site'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 1) { setDrillEntry('brand'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 2) { setDrillGroup(null) }
                  }}
                  >{h}</div>
                ))}
              </div>

              {/* 컬럼 */}
              <div style={{ display: 'flex' }}>
                {/* 1. 사이트: 사이트 헤더 클릭 시 전체 표시 / 브랜드 선택 시 연관만 표시 */}
                <div style={colStyle(0)}>
                  {(drillEntry === 'site' || drillBrand) ? (
                    filteredSites.length === 0 ? (
                      <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>그룹 없음</div>
                    ) : filteredSites.map(s => (
                      <div key={s.id} style={itemSt(drillSite === s.id)}
                        onClick={() => { setDrillSite(drillSite === s.id ? null : s.id); setDrillGroup(null) }}
                        onMouseEnter={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'transparent' }}
                      >
                        {s.source_site || s.name}
                        <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#555' }}>
                          {drillBrand
                            ? allLeafInfos.filter(l => l._siteId === s.id && l._brand === drillBrand).length
                            : getAllLeaves(s).length}
                        </span>
                      </div>
                    ))
                  ) : null}
                </div>
                {/* 2. 브랜드: 브랜드 헤더 클릭 시 전체 표시 / 사이트 선택 시 연관만 표시 */}
                <div style={colStyle(1)}>
                  {(drillEntry === 'brand' || drillSite) ? (
                    brands.length > 0 ? brands.map(([brand, count]) => (
                      <div key={brand} style={itemSt(drillBrand === brand)}
                        onClick={() => {
                          const toggling = drillBrand === brand
                          setDrillBrand(toggling ? null : brand)
                          setDrillGroup(null)
                          if (!toggling) {
                            // 브랜드 선택 시 해당 브랜드의 모든 카테고리 그룹 자동 선택
                            let leaves = allLeafInfos
                            if (drillSite) leaves = leaves.filter(l => l._siteId === drillSite)
                            leaves = leaves.filter(l => l._brand === brand)
                            setSelectedIds(new Set(leaves.map(l => l.id)))
                          } else {
                            setSelectedIds(new Set())
                          }
                        }}
                        onMouseEnter={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'transparent' }}
                      >
                        {brand}
                        <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#555' }}>{count}</span>
                      </div>
                    )) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>브랜드 없음</div>
                  ) : null}
                </div>
                {/* 3. 카테고리: 사이트 또는 브랜드 선택 후 연관 표시 */}
                <div style={colStyle(2)}>
                  {(drillSite || drillBrand) ? (catGroups.length > 0 ? (<>
                    {catGroups.map(g => (
                      <div key={g.id} style={itemSt(drillGroup === g.id)}
                        onClick={() => { setDrillGroup(g.id); setSelectedIds(new Set([g.id])) }}
                        onMouseEnter={e => { if (drillGroup !== g.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillGroup !== g.id) e.currentTarget.style.background = 'transparent' }}
                      >
                        {g._category || g.name}
                        {(g as unknown as Record<string, number>).ai_tagged_count > 0 && (
                          <span style={{ fontSize: '0.55rem', padding: '0 3px', borderRadius: '3px', background: 'rgba(81,207,102,0.15)', color: '#51CF66', border: '1px solid rgba(81,207,102,0.3)' }}>T</span>
                        )}
                        <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#FF8C00' }}>{(g.collected_count ?? 0).toLocaleString()}</span>
                      </div>
                    ))}
                  </>) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>항목 없음</div>
                  ) : null}
                </div>
                {/* 4. 링크 + 삭제 체크 */}
                <div style={detColStyle(3)}>
                  {selectedFilter ? (() => {
                    // 소싱 URL 결정: category_filter(저장된 URL) > 사이트별 검색URL 생성
                    const storedUrl = (selectedFilter as unknown as Record<string, string>).category_filter || ''
                    const kw = selectedFilter.keyword || ''
                    const site = selectedFilter.source_site || ''
                    // keyword가 이미 URL이면 그대로 사용
                    const kwIsUrl = kw.startsWith('http://') || kw.startsWith('https://')
                    const linkUrl = storedUrl || (kwIsUrl ? kw : (SOURCING_SEARCH_URLS[site] ? SOURCING_SEARCH_URLS[site] + encodeURIComponent(kw) : ''))
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {linkUrl ? (
                          <a href={linkUrl} target="_blank" rel="noopener noreferrer" style={{
                            color: '#7EB5D0', fontSize: '0.7rem', wordBreak: 'break-all',
                            textDecoration: 'underline', textUnderlineOffset: '2px', flex: 1,
                          }}>{kw || linkUrl.replace(/https?:\/\/[^/]+/, '').slice(0, 40)}...</a>
                        ) : <span style={{ color: '#555', fontSize: '0.75rem', flex: 1 }}>-</span>}
                        <button
                          onClick={async () => {
                            if (!await showConfirm(`"${selectedFilter.name}" 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`)) return
                            try {
                              const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: selectedFilter.id })
                              const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
                              if (registered.length > 0) {
                                showAlert(`마켓등록 상품이 ${registered.length}건 있어서 삭제할 수 없습니다`, 'error')
                                return
                              }
                              const pIds = res.items.map(p => p.id)
                              if (pIds.length > 0) await collectorApi.bulkDeleteProducts(pIds)
                            } catch { /* 상품 없으면 무시 */ }
                            await collectorApi.deleteFilter(selectedFilter.id)
                            setDrillGroup(null)
                            load(); loadTree()
                          }}
                          style={{
                            background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)',
                            color: '#FF6B6B', fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px',
                            cursor: 'pointer', flexShrink: 0,
                          }}
                        >삭제</button>
                      </div>
                    )
                  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                {/* 5. 정책 */}
                <div style={detColStyle(4)}>
                  {selectedFilter ? (
                    <select
                      key={selectedFilter.id}
                      defaultValue={(selectedFilter as unknown as Record<string, string>).applied_policy_id || ''}
                      onChange={e => handlePolicyApply(selectedFilter.id, e.target.value)}
                      style={{
                        width: '100%', padding: '0.2rem 0.2rem', fontSize: '0.72rem',
                        background: 'rgba(22,22,22,0.95)', border: '1px solid #353535',
                        color: '#C5C5C5', borderRadius: '4px',
                      }}
                    >
                      <option value="">정책 선택</option>
                      {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : (drillBrand && catGroups.length > 0) ? (
                    <select onChange={async (e) => {
                      const policyId = e.target.value
                      if (!policyId) return
                      const policyName = policies.find(p => p.id === policyId)?.name || ''
                      if (!await showConfirm(`${drillBrand} 브랜드의 ${catGroups.length}개 그룹에 "${policyName}" 정책을 일괄 적용하시겠습니까?`)) { e.target.value = ''; return }
                      let applied = 0
                      for (const g of catGroups) {
                        try {
                          await collectorApi.updateFilter(g.id, { applied_policy_id: policyId } as Partial<SambaSearchFilter>)
                          applied++
                        } catch { /* 무시 */ }
                      }
                      showAlert(`${applied}/${catGroups.length}개 그룹에 정책 적용 완료`, 'success')
                      e.target.value = ''
                      load(); loadTree()
                    }} style={{
                      width: '100%', padding: '0.2rem 0.2rem', fontSize: '0.68rem',
                      background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.3)',
                      color: '#FF8C00', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                    }}>
                      <option value="">일괄적용 ({catGroups.length})</option>
                      {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                {/* 6. 수집 */}
                <div style={detColStyle(5)}>
                  {selectedFilter ? (
                    <span onClick={() => handleGoToProducts(selectedFilter)} style={{
                      color: selectedCount > 0 ? '#FF8C00' : '#555', fontWeight: 600, fontSize: '0.82rem',
                      cursor: selectedCount > 0 ? 'pointer' : 'default',
                      textDecoration: selectedCount > 0 ? 'underline' : 'none',
                    }}>{selectedCount.toLocaleString()}</span>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 8. 요청 */}
                <div style={detColStyle(6)}>
                  {selectedFilter ? (
                    <input
                      key={selectedFilter.id + (selectedFilter.requested_count ?? 100)}
                      type="text" inputMode="numeric" pattern="[0-9]*"
                      defaultValue={selectedFilter.requested_count ?? 100}
                      onBlur={e => {
                        const v = parseInt(e.target.value, 10)
                        if (!isNaN(v) && v !== (selectedFilter.requested_count ?? 100)) handleUpdateRequestedCount(selectedFilter.id, v)
                      }}
                      style={{
                        width: '50px', textAlign: 'center', background: 'transparent',
                        border: '1px solid #3D3D3D', color: '#4C9AFF', fontSize: '0.78rem',
                        fontWeight: 600, padding: '0.1rem 0.2rem', borderRadius: '4px', outline: 'none',
                      }}
                      onFocus={e => { e.currentTarget.style.borderColor = '#4C9AFF' }}
                      onBlurCapture={e => { e.currentTarget.style.borderColor = '#3D3D3D' }}
                    />
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 9. 생성일/최근수집 */}
                <div style={detColStyle(7)}>
                  {selectedFilter ? (
                    <div style={{ fontSize: '0.68rem', color: '#888' }}>
                      {fmtDate(selectedFilter.created_at)}<br />{fmtDate(selectedFilter.last_collected_at)}
                    </div>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 10. 매핑 */}
                <div style={{ ...detColStyle(8), borderRight: 'none' }}>
                  {selectedFilter ? (() => {
                    const tm = (selectedFilter as SambaSearchFilter).target_mappings || {}
                    const mappedCount = Object.keys(tm).length
                    return (
                      <button
                        onClick={() => {
                          setMappingFilter(selectedFilter as SambaSearchFilter)
                          setMappingData({ ...tm })
                          setShowMappingModal(true)
                        }}
                        style={{
                          padding: '0.2rem 0.5rem', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer',
                          background: mappedCount > 0 ? 'rgba(81,207,102,0.1)' : 'rgba(255,140,0,0.1)',
                          border: `1px solid ${mappedCount > 0 ? 'rgba(81,207,102,0.3)' : 'rgba(255,140,0,0.3)'}`,
                          color: mappedCount > 0 ? '#51CF66' : '#FF8C00',
                        }}
                      >{mappedCount > 0 ? `${mappedCount}개 매핑` : '매핑'}</button>
                    )
                  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
              </div>
            </div>
          )
        })()}
      </div>


      {/* 갱신 결과 모달 */}
      {showRefreshModal && refreshResult && (
        <div
          onClick={() => setShowRefreshModal(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(0,0,0,0.6)", display: "flex",
            alignItems: "center", justifyContent: "center",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#1A1A1A", border: "1px solid #2D2D2D",
              borderRadius: "12px", padding: "1.5rem", minWidth: "360px",
              maxWidth: "440px",
            }}
          >
            <h3 style={{
              fontSize: "1rem", fontWeight: 700, color: "#E5E5E5",
              marginBottom: "1rem", margin: 0, paddingBottom: "0.75rem",
              borderBottom: "1px solid #2D2D2D",
            }}>
              일괄 갱신 결과
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.625rem", marginTop: "1rem" }}>
              {[
                { label: "전체 대상", value: refreshResult.total, color: "#C5C5C5" },
                { label: "갱신 완료", value: refreshResult.refreshed, color: "#51CF66" },
                { label: "가격/재고 변동", value: refreshResult.changed, color: "#FFD93D" },
                { label: "품절 전환", value: refreshResult.sold_out, color: "#FF6B6B" },
                { label: "자동 재전송", value: refreshResult.retransmitted, color: "#4C9AFF" },
                { label: "확장앱 필요", value: refreshResult.needs_extension.length, color: "#CC5DE8" },
                { label: "오류", value: refreshResult.errors, color: "#FF6B6B" },
              ].map((item) => (
                <div key={item.label} style={{
                  display: "flex", justifyContent: "space-between",
                  alignItems: "center", padding: "0.375rem 0",
                }}>
                  <span style={{ fontSize: "0.85rem", color: "#999" }}>{item.label}</span>
                  <span style={{ fontSize: "0.95rem", fontWeight: 700, color: item.color }}>
                    {item.value}건
                  </span>
                </div>
              ))}
            </div>
            <button
              onClick={() => setShowRefreshModal(false)}
              style={{
                width: "100%", marginTop: "1.25rem", padding: "0.625rem",
                background: "rgba(255,140,0,0.15)", border: "1px solid rgba(255,140,0,0.35)",
                color: "#FF8C00", borderRadius: "8px", fontSize: "0.85rem",
                fontWeight: 600, cursor: "pointer",
              }}
            >
              확인
            </button>
          </div>
        </div>
      )}

      {/* ═══ 카테고리 매핑 모달 ═══ */}
      {showMappingModal && mappingFilter && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setShowMappingModal(false)}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '28px 32px', minWidth: '500px', maxWidth: '700px', maxHeight: '80vh', overflowY: 'auto' }}
            onClick={e => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: '#E5E5E5' }}>카테고리 매핑</h3>
            <p style={{ margin: '0 0 16px', fontSize: '0.75rem', color: '#888' }}>
              {mappingFilter.name} — 각 마켓별 카테고리를 지정하세요
            </p>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
              <button
                disabled={mappingLoading}
                onClick={async () => {
                  setMappingLoading(true)
                  try {
                    const products = await collectorApi.scrollProducts({ skip: 0, limit: 5, search_filter_id: mappingFilter.id })
                    const rep = products.items[0]
                    if (!rep) { showAlert('상품이 없습니다', 'error'); return }
                    const res = await categoryApi.aiSuggest({
                      source_site: rep.source_site || mappingFilter.source_site,
                      source_category: [rep.category1, rep.category2, rep.category3, rep.category4].filter(Boolean).join(' > ') || rep.category || '',
                      sample_products: products.items.slice(0, 5).map(p => p.name || ''),
                      sample_tags: rep.tags?.filter((t: string) => !t.startsWith('__')) || [],
                      target_markets: MAPPING_MARKETS.map(m => m.id),
                    })
                    if (res) {
                      const newMapping: Record<string, string> = { ...mappingData }
                      for (const [market, cat] of Object.entries(res)) {
                        if (cat) newMapping[market] = cat as string
                      }
                      setMappingData(newMapping)
                      showAlert('AI 매핑 추천 완료', 'success')
                    }
                  } catch (e) { showAlert(e instanceof Error ? e.message : 'AI 매핑 실패', 'error') }
                  finally { setMappingLoading(false) }
                }}
                style={{ padding: '7px 20px', fontSize: '0.82rem', borderRadius: '6px', cursor: mappingLoading ? 'not-allowed' : 'pointer', border: '1px solid rgba(255,140,0,0.5)', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600, opacity: mappingLoading ? 0.6 : 1 }}
              >{mappingLoading ? 'AI 분석중...' : 'AI 매핑'}</button>
              <button
                onClick={async () => {
                  if (!await showConfirm('이 그룹의 카테고리 매핑을 모두 초기화하시겠습니까?')) return
                  setMappingData({})
                  try {
                    await collectorApi.updateFilter(mappingFilter.id, { target_mappings: {} } as Partial<SambaSearchFilter>)
                    showAlert('매핑 초기화 완료', 'success')
                    load(); loadTree()
                  } catch (e) { showAlert(e instanceof Error ? e.message : '초기화 실패', 'error') }
                }}
                style={{ padding: '7px 20px', fontSize: '0.82rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(255,107,107,0.5)', background: 'rgba(255,107,107,0.1)', color: '#FF6B6B' }}
              >매핑 초기화</button>
            </div>

            {MAPPING_MARKETS.map(m => (
              <MappingMarketRow key={m.id} marketType={m.id} marketName={m.name} value={mappingData[m.id] || ''} onChange={val => setMappingData(prev => ({ ...prev, [m.id]: val }))} onClear={() => setMappingData(prev => { const n = { ...prev }; delete n[m.id]; return n })} />
            ))}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
              <button onClick={() => setShowMappingModal(false)}
                style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'transparent', color: '#888' }}>취소</button>
              <button onClick={async () => {
                try {
                  const clean = Object.fromEntries(Object.entries(mappingData).filter(([, v]) => v))
                  await collectorApi.updateFilter(mappingFilter.id, { target_mappings: clean } as Partial<SambaSearchFilter>)
                  setShowMappingModal(false)
                  showAlert('매핑 저장 완료', 'success')
                  load(); loadTree()
                } catch (e) { showAlert(e instanceof Error ? e.message : '저장 실패', 'error') }
              }}
                style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(81,207,102,0.5)', background: 'rgba(81,207,102,0.15)', color: '#51CF66', fontWeight: 600 }}>
                저장 ({Object.values(mappingData).filter(Boolean).length}개 마켓)
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ AI 태그 미리보기 모달 ═══ */}
      {showTagPreview && (
        <div data-tag-preview-modal style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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
                  <div>
                    <span style={{ fontSize: '0.82rem', color: '#FFB84D', fontWeight: 600 }}>{preview.group_name}</span>
                    {preview.rep_name && preview.rep_name !== preview.group_name && (
                      <span style={{ fontSize: '0.7rem', color: '#888', marginLeft: '6px' }}>({preview.rep_name})</span>
                    )}
                  </div>
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
                    load(); loadTree()
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

      {/* ═══ AI 소싱기 모달 ═══ */}
      {showAiSourcingModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => !aiAnalyzing && setShowAiSourcingModal(false)}>
          <div onClick={e => e.stopPropagation()} style={{
            background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px',
            width: aiSourcingStep === 'confirm' ? '900px' : '560px',
            maxHeight: '85vh', overflow: 'auto',
          }}>
            {/* 헤더 */}
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #2D2D2D',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.1rem' }}>🤖</span>
                <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>AI 소싱기</span>
                <span style={{ fontSize: '0.75rem', color: '#888', marginLeft: '4px' }}>
                  {aiSourcingStep === 'config' ? '1/3 데이터소스 설정' :
                   aiSourcingStep === 'analyzing' ? '2/3 분석 중' : '3/3 결과 확인'}
                </span>
              </div>
              {!aiAnalyzing && (
                <button onClick={() => setShowAiSourcingModal(false)} style={{
                  background: 'none', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer',
                }}>✕</button>
              )}
            </div>

            {/* STEP 1: 월 + 대카테고리 설정 */}
            {aiSourcingStep === 'config' && (
              <div style={{ padding: '20px' }}>
                {/* 월 + 대카테고리 (핵심 2개 입력) */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                  <div>
                    <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>분석 월 (작년)</label>
                    <select value={aiMonth} onChange={e => setAiMonth(Number(e.target.value))} style={{
                      width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                      borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                    }}>
                      {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                        <option key={m} value={m}>{m}월</option>
                      ))}
                    </select>
                    <span style={{ fontSize: '0.7rem', color: '#555', marginTop: '4px', display: 'block' }}>
                      {new Date().getFullYear() - 1}년 {aiMonth}월 데이터
                    </span>
                  </div>
                  <div>
                    <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>대 카테고리</label>
                    <select value={aiMainCategory} onChange={e => setAiMainCategory(e.target.value)} style={{
                      width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                      borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                    }}>
                      <option value="패션의류">패션의류</option>
                      <option value="패션잡화">패션잡화</option>
                      <option value="스포츠/레저">스포츠/레저</option>
                      <option value="패션전체">패션전체 (의류+잡화)</option>
                    </select>
                  </div>
                </div>

                {/* 수집 소싱처 선택 */}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '8px' }}>수집 소싱처</label>
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {SITES.map(s => (
                      <button key={s.id} onClick={() => setAiSourceSite(s.id)} style={{
                        padding: '6px 14px', borderRadius: '6px', fontSize: '0.78rem', cursor: 'pointer',
                        fontWeight: aiSourceSite === s.id ? 700 : 400,
                        background: aiSourceSite === s.id ? 'rgba(255,140,0,0.15)' : '#111',
                        border: aiSourceSite === s.id ? '1px solid #FF8C00' : '1px solid #2D2D2D',
                        color: aiSourceSite === s.id ? '#FF8C00' : '#888',
                      }}>{s.label}</button>
                    ))}
                  </div>
                </div>

                {/* 자동 조회 범위 */}
                <div style={{
                  background: 'rgba(108,92,231,0.08)', border: '1px solid rgba(108,92,231,0.25)',
                  borderRadius: '8px', padding: '12px 14px', marginBottom: '16px', fontSize: '0.78rem',
                }}>
                  <div style={{ color: '#A29BFE', fontWeight: 600, marginBottom: '6px' }}>자동 조회 범위</div>
                  <div style={{ color: '#999', lineHeight: 1.6 }}>
                    <span style={{ color: '#4C9AFF' }}>무신사</span>:{' '}
                    {aiMainCategory === '패션의류' ? '상의, 아우터, 바지, 원피스/스커트, 속옷/슬립웨어' :
                     aiMainCategory === '패션잡화' ? '가방, 신발, 시계/주얼리, 패션소품' :
                     aiMainCategory === '스포츠/레저' ? '스포츠/레저' : '전체 10개 카테고리'}
                    <br />
                    <span style={{ color: '#51CF66' }}>네이버 데이터랩</span>:{' '}
                    {aiMainCategory === '패션전체' ? '패션의류 + 패션잡화' : aiMainCategory} 인기검색어 TOP 500
                  </div>
                </div>

                {/* 엑셀 업로드 + 최소 상품수 */}
                <div style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px',
                }}>
                  <div style={{
                    background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>판매 엑셀 (선택)</span>
                      <span style={{ fontSize: '0.72rem', color: '#888' }}>정확도 향상</span>
                    </div>
                    <input type="file" accept=".xlsx,.xlsm,.xls,.csv"
                      onChange={e => setAiExcelFile(e.target.files?.[0] || null)}
                      style={{ fontSize: '0.8rem', color: '#888' }}
                    />
                    {aiExcelFile && (
                      <span style={{ fontSize: '0.75rem', color: '#FFB84D', display: 'block', marginTop: '4px' }}>
                        {aiExcelFile.name}
                      </span>
                    )}
                  </div>
                  <div style={{
                    background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>최소 상품수</span>
                      <span style={{ fontSize: '0.72rem', color: '#888' }}>미만 그룹 배제</span>
                    </div>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={aiMinCount || ''}
                      onChange={e => setAiMinCount(Number(e.target.value.replace(/[^0-9]/g, '')) || 0)}
                      placeholder="0"
                      style={{
                        width: '100%', padding: '6px 10px', background: '#0A0A0A', border: '1px solid #3D3D3D',
                        borderRadius: '6px', color: '#FFB84D', fontSize: '0.9rem', fontWeight: 600,
                      }}
                    />
                  </div>
                </div>

                {/* 시작 버튼 */}
                <button
                  onClick={async () => {
                    setAiSourcingStep('analyzing')
                    setAiAnalyzing(true)
                    setAiLogs([`[시작] ${new Date().getFullYear() - 1}년 ${aiMonth}월 / ${aiMainCategory} 분석 시작...`])
                    let gotResult = false
                    try {
                      const resp = await aiSourcingApi.analyzeFull({
                        month: aiMonth,
                        main_category: aiMainCategory,
                        target_count: aiTargetCount,
                        file: aiExcelFile || undefined,
                      })
                      // HTTP 에러 체크
                      if (!resp.ok) {
                        const errText = await resp.text()
                        throw new Error(`서버 오류 (${resp.status}): ${errText.slice(0, 200)}`)
                      }
                      const reader = resp.body?.getReader()
                      if (!reader) throw new Error('스트리밍 응답 없음')
                      const decoder = new TextDecoder()
                      let buffer = ''
                      const processLine = (line: string) => {
                        if (line.startsWith('event: ')) return
                        if (!line.startsWith('data: ')) return
                        try {
                          const payload = JSON.parse(line.slice(6))
                          if (typeof payload === 'string') {
                            setAiLogs(prev => [...prev, payload])
                          } else if (payload.brands && payload.combinations) {
                            gotResult = true
                            const result = payload as AISourcingResult
                            setAiResult(result)
                            // IP위험 브랜드 표시만 (제외하지 않음 — 사용자가 판단)
                            setAiExcludedBrands(new Set())
                setAiExcludedKeywords(new Set())
                            // 전체 조합 기본 선택
                            const all = new Set<number>()
                            result.combinations.forEach((_c: AISourcingCombination, i: number) => {
                              all.add(i)
                            })
                            setAiSelectedCombos(all)
                          } else if (payload.step) {
                            setAiLogs(prev => [...prev, `[${payload.step}] ${payload.count}개 처리`])
                          } else if (payload.message) {
                            setAiLogs(prev => [...prev, payload.message])
                          }
                        } catch { /* JSON 파싱 실패 무시 */ }
                      }
                      while (true) {
                        const { done, value } = await reader.read()
                        if (done) break
                        buffer += decoder.decode(value, { stream: true })
                        const lines = buffer.split('\n')
                        buffer = lines.pop() || ''
                        for (const line of lines) processLine(line)
                      }
                      // 남은 버퍼 처리
                      if (buffer.trim()) processLine(buffer.trim())
                      // 결과가 있을 때만 confirm 단계로 전환
                      if (gotResult) {
                        setAiSourcingStep('confirm')
                      } else {
                        setAiLogs(prev => [...prev, '[오류] 분석 결과를 받지 못했습니다. 백엔드 로그를 확인해주세요.'])
                      }
                    } catch (err) {
                      setAiLogs(prev => [...prev, `[오류] ${err instanceof Error ? err.message : '분석 실패'}`])
                    }
                    setAiAnalyzing(false)
                  }}
                  style={{
                    width: '100%', padding: '10px', borderRadius: '8px',
                    background: 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                    color: '#fff', fontWeight: 700, fontSize: '0.9rem',
                    border: 'none', cursor: 'pointer',
                  }}
                >
                  AI 분석 시작
                </button>
              </div>
            )}

            {/* STEP 2: 분석 중 */}
            {aiSourcingStep === 'analyzing' && (
              <div style={{ padding: '20px' }}>
                <div style={{
                  background: '#080A10', borderRadius: '8px', padding: '14px',
                  height: '300px', overflowY: 'auto', fontFamily: 'monospace',
                  fontSize: '0.62rem', lineHeight: 1.5, color: '#8A95B0',
                }}>
                  {aiLogs.map((line, i) => (
                    <p key={i} style={{
                      margin: 0,
                      color: line.includes('완료') || line.includes('성공') ? '#51CF66'
                        : line.includes('오류') || line.includes('실패') ? '#FF6B6B'
                        : line.includes('시작') ? '#4C9AFF' : '#8A95B0',
                    }}>{line}</p>
                  ))}
                </div>
                {!aiAnalyzing && (
                  <div style={{ marginTop: '12px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    {aiResult && (
                      <button onClick={() => setAiSourcingStep('confirm')} style={{
                        padding: '8px 20px', borderRadius: '6px',
                        background: 'rgba(81,207,102,0.2)', border: '1px solid rgba(81,207,102,0.5)',
                        color: '#51CF66', cursor: 'pointer', fontWeight: 600,
                      }}>결과 확인 →</button>
                    )}
                    <button onClick={() => setShowAiSourcingModal(false)} style={{
                      padding: '8px 20px', borderRadius: '6px',
                      background: 'transparent', border: '1px solid #3D3D3D',
                      color: '#888', cursor: 'pointer',
                    }}>닫기</button>
                  </div>
                )}
              </div>
            )}

            {/* STEP 3: 결과 확인 + 컨펌 */}
            {aiSourcingStep === 'confirm' && aiResult && (
              <div style={{ padding: '20px' }}>
                {/* 요약 */}
                <div style={{
                  display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '16px',
                }}>
                  {[
                    { label: '발견 브랜드', value: aiResult.summary.total_brands_found, color: '#4C9AFF' },
                    { label: '발견 키워드쌍', value: aiResult.summary.total_pairs || 0, color: '#E5A0FF' },
                    { label: 'IP안전', value: aiResult.summary.safe_brands, color: '#51CF66' },
                    { label: '생성 그룹', value: aiResult.summary.total_combinations, color: '#FFB84D' },
                    { label: '예상 상품', value: aiResult.summary.total_estimated_products.toLocaleString(), color: '#A29BFE' },
                  ].map(s => (
                    <div key={s.label} style={{
                      background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px',
                      padding: '10px', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: s.color }}>{s.value}</div>
                      <div style={{ fontSize: '0.72rem', color: '#888' }}>{s.label}</div>
                    </div>
                  ))}
                </div>

                {/* 선택된 소싱처 표시 */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px',
                  background: 'rgba(255,140,0,0.06)', border: '1px solid rgba(255,140,0,0.2)',
                  borderRadius: '8px', padding: '8px 14px',
                }}>
                  <span style={{ fontSize: '0.78rem', color: '#FF8C00', fontWeight: 600 }}>수집 소싱처: {SITES.find(s => s.id === aiSourceSite)?.label || aiSourceSite}</span>
                  <span style={{ fontSize: '0.7rem', color: '#666' }}>그룹명: {aiSourceSite}_브랜드_키워드</span>
                </div>

                {/* 근거 데이터 */}
                {(() => {
                  // 소싱처별 브랜드 + 키워드 그룹핑
                  const sourceMap: Record<string, { brands: string[]; keywords: string[] }> = {}
                  aiResult.brands.forEach(b => {
                    const src = b.source || '기타'
                    if (!sourceMap[src]) sourceMap[src] = { brands: [], keywords: [] }
                    if (!sourceMap[src].brands.includes(b.brand)) sourceMap[src].brands.push(b.brand)
                    ;[...(b.keywords || []), ...(b.categories || [])].forEach(kw => {
                      if (kw && !sourceMap[src].keywords.includes(kw)) sourceMap[src].keywords.push(kw)
                    })
                  })
                  const entries = Object.entries(sourceMap)
                  if (entries.length === 0) return null
                  return (
                    <div style={{ marginBottom: '14px', padding: '12px 14px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', maxHeight: '300px', overflowY: 'auto' }}>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '8px', fontWeight: 600 }}>분석 근거 <span style={{ color: '#555', fontWeight: 400 }}>— 클릭하여 제외</span></div>
                      {entries.map(([src, data]) => (
                        <div key={src} style={{ marginBottom: '6px', fontSize: '0.78rem', lineHeight: 1.8, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '2px' }}>
                          <span style={{ color: '#FFB84D', fontWeight: 600 }}>{src}</span>
                          <span style={{ color: '#666' }}> : </span>
                          {data.brands.map(brand => {
                            const excluded = aiExcludedBrands.has(brand)
                            return (
                              <span key={brand}
                                onClick={() => {
                                  const next = new Set(aiExcludedBrands)
                                  if (excluded) {
                                    next.delete(brand)
                                    const addIdxs = new Set(aiSelectedCombos)
                                    aiResult.combinations.forEach((c, i) => {
                                      if (c.brand === brand) addIdxs.add(i)
                                    })
                                    setAiSelectedCombos(addIdxs)
                                  } else {
                                    next.add(brand)
                                    const removeIdxs = new Set(aiSelectedCombos)
                                    aiResult.combinations.forEach((c, i) => {
                                      if (c.brand === brand) removeIdxs.delete(i)
                                    })
                                    setAiSelectedCombos(removeIdxs)
                                  }
                                  setAiExcludedBrands(next)
                                }}
                                style={{
                                  cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                                  background: excluded ? 'rgba(255,107,107,0.1)' : 'rgba(255,255,255,0.05)',
                                  color: excluded ? '#FF6B6B' : '#E5E5E5',
                                  textDecoration: excluded ? 'line-through' : 'none',
                                  opacity: excluded ? 0.5 : 1, transition: 'all 0.15s',
                                }}
                              >{brand}</span>
                            )
                          })}
                          {data.keywords.length > 0 && (
                            <>
                              <span style={{ color: '#666' }}> / </span>
                              {data.keywords.map(kw => {
                                // 키워드 제외 시 해당 키워드를 가진 조합 체크 해제
                                const kwExcluded = aiExcludedBrands.has(`__kw__${kw}`)
                                return (
                                  <span key={kw}
                                    onClick={() => {
                                      const kwKey = `__kw__${kw}`
                                      const next = new Set(aiExcludedBrands)
                                      if (kwExcluded) {
                                        next.delete(kwKey)
                                        const addIdxs = new Set(aiSelectedCombos)
                                        aiResult.combinations.forEach((c, i) => {
                                          if ((c.keyword || c.category) === kw) addIdxs.add(i)
                                        })
                                        setAiSelectedCombos(addIdxs)
                                      } else {
                                        next.add(kwKey)
                                        const removeIdxs = new Set(aiSelectedCombos)
                                        aiResult.combinations.forEach((c, i) => {
                                          if ((c.keyword || c.category) === kw) removeIdxs.delete(i)
                                        })
                                        setAiSelectedCombos(removeIdxs)
                                      }
                                      setAiExcludedBrands(next)
                                    }}
                                    style={{
                                      cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                                      background: kwExcluded ? 'rgba(255,107,107,0.1)' : 'rgba(76,154,255,0.08)',
                                      color: kwExcluded ? '#FF6B6B' : '#4C9AFF',
                                      textDecoration: kwExcluded ? 'line-through' : 'none',
                                      opacity: kwExcluded ? 0.5 : 1, transition: 'all 0.15s',
                                    }}
                                  >{kw}</span>
                                )
                              })}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )
                })()}

                {/* IP위험 브랜드 — 취소선 표시, 클릭으로 제외/포함 전환 */}
                {(() => {
                  const unsafeBrands = aiResult.brands.filter(b => !b.is_safe)
                  if (unsafeBrands.length === 0) return null
                  return (
                    <div style={{ marginBottom: '14px', padding: '12px 14px', background: 'rgba(255,107,107,0.04)', border: '1px solid rgba(255,107,107,0.15)', borderRadius: '8px' }}>
                      <div style={{ fontSize: '0.75rem', color: '#FF6B6B', marginBottom: '8px', fontWeight: 600 }}>
                        IP위험 브랜드 ({unsafeBrands.length}개)
                        {aiExcludedBrands.size > 0 && <span style={{ color: '#888', fontWeight: 400 }}> — {aiExcludedBrands.size}개 제외</span>}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {unsafeBrands.map(b => {
                          const excluded = aiExcludedBrands.has(b.brand)
                          return (
                            <span key={b.brand}
                              onClick={() => {
                                const next = new Set(aiExcludedBrands)
                                if (excluded) {
                                  next.delete(b.brand)
                                  const addIdxs = new Set(aiSelectedCombos)
                                  aiResult.combinations.forEach((c, i) => {
                                    if (c.brand === b.brand) addIdxs.add(i)
                                  })
                                  setAiSelectedCombos(addIdxs)
                                } else {
                                  next.add(b.brand)
                                  const removeIdxs = new Set(aiSelectedCombos)
                                  aiResult.combinations.forEach((c, i) => {
                                    if (c.brand === b.brand) removeIdxs.delete(i)
                                  })
                                  setAiSelectedCombos(removeIdxs)
                                }
                                setAiExcludedBrands(next)
                              }}
                              title={b.safety_reason}
                              style={{
                                fontSize: '0.75rem', padding: '3px 10px', borderRadius: '12px', cursor: 'pointer',
                                background: excluded ? 'rgba(255,107,107,0.12)' : 'rgba(255,107,107,0.06)',
                                border: `1px solid rgba(255,107,107,${excluded ? '0.4' : '0.2'})`,
                                color: '#FF6B6B',
                                textDecoration: 'line-through',
                                opacity: excluded ? 0.5 : 1,
                                transition: 'all 0.15s',
                              }}
                            >
                              {b.brand}
                            </span>
                          )
                        })}
                      </div>
                      <div style={{ fontSize: '0.68rem', color: '#666', marginTop: '6px' }}>
                        취소선 = IP위험 · 클릭하여 제외 (흐리게 처리됨)
                      </div>
                    </div>
                  )
                })()}

                {/* 조합 테이블 */}
                <div style={{ maxHeight: '350px', overflowY: 'auto', marginBottom: '12px' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2D2D2D', position: 'sticky', top: 0, background: '#1A1A1A' }}>
                        <th style={{ padding: '8px 6px', textAlign: 'left', width: '36px' }}>
                          <input type="checkbox"
                            checked={(() => {
                              const selectable = aiResult.combinations.filter(c => !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                              const selectedSelectable = selectable.filter((c, i) => aiSelectedCombos.has(aiResult.combinations.indexOf(c)))
                              return selectable.length > 0 && selectedSelectable.length === selectable.length
                            })()}
                            onChange={e => {
                              if (e.target.checked) {
                                const all = new Set<number>()
                                aiResult.combinations.forEach((c, i) => {
                                  if (!aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount) all.add(i)
                                })
                                setAiSelectedCombos(all)
                              } else {
                                setAiSelectedCombos(new Set())
                              }
                            }}
                            style={{ accentColor: '#FF8C00' }}
                          />
                        </th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>소싱처</th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>브랜드</th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>키워드</th>
                        <th style={{ padding: '8px 6px', textAlign: 'right', color: '#888' }}>예상상품수</th>
                        <th style={{ padding: '8px 6px', textAlign: 'center', color: '#888' }}>
                          <span>IP안전</span>
                          {aiResult.combinations.some(c => !c.is_safe && aiSelectedCombos.has(aiResult.combinations.indexOf(c))) && (
                            <button
                              onClick={() => {
                                const next = new Set(aiSelectedCombos)
                                aiResult.combinations.forEach((c, i) => {
                                  if (!c.is_safe) next.delete(i)
                                })
                                setAiSelectedCombos(next)
                              }}
                              style={{
                                marginLeft: '4px', fontSize: '0.65rem', padding: '1px 6px', borderRadius: '3px',
                                background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                                color: '#FF6B6B', cursor: 'pointer',
                              }}
                            >위험 해제</button>
                          )}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {aiResult.combinations.map((combo, idx) => {
                        const isExcluded = aiExcludedBrands.has(combo.brand) || aiExcludedBrands.has(`__kw__${combo.keyword || combo.category}`)
                        if (combo.estimated_count < aiMinCount) return null
                        return (
                          <tr key={idx} style={{
                            borderBottom: '1px solid #1D1D1D',
                            background: isExcluded ? 'rgba(255,107,107,0.04)' : aiSelectedCombos.has(idx) ? 'rgba(108,92,231,0.06)' : 'transparent',
                            opacity: isExcluded ? 0.4 : 1,
                          }}>
                            <td style={{ padding: '6px' }}>
                              <input type="checkbox"
                                checked={aiSelectedCombos.has(idx)}
                                disabled={isExcluded}
                                onChange={e => {
                                  const next = new Set(aiSelectedCombos)
                                  e.target.checked ? next.add(idx) : next.delete(idx)
                                  setAiSelectedCombos(next)
                                }}
                                style={{ accentColor: '#FF8C00' }}
                              />
                            </td>
                            <td style={{ padding: '6px', color: SITE_COLORS[combo.source_site] || '#888' }}>
                              {combo.source_site}
                            </td>
                            <td style={{ padding: '6px', color: !combo.is_safe ? '#FF6B6B' : isExcluded ? '#888' : '#E5E5E5', fontWeight: 500, textDecoration: !combo.is_safe ? 'line-through' : 'none' }}>{combo.brand}</td>
                            <td style={{ padding: '6px', color: '#C5C5C5' }}>{combo.keyword || combo.category}</td>
                            <td style={{ padding: '6px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                              {combo.estimated_count.toLocaleString()}
                            </td>
                            <td style={{ padding: '6px', textAlign: 'center' }}>
                              {combo.is_safe
                                ? <span style={{ color: '#51CF66', fontSize: '0.85rem' }}>안전</span>
                                : <span style={{ color: '#FF6B6B', fontSize: '0.85rem' }}>위험</span>
                              }
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* 선택 요약 + 버튼 */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '0.82rem', color: '#888' }}>
                    {aiResult.combinations.filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`)).length}개 선택 / 예상{' '}
                    {aiResult.combinations
                      .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`))
                      .reduce((s, c) => s + c.estimated_count, 0)
                      .toLocaleString()}개 상품
                  </span>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={() => {
                      setAiSourcingStep('config')
                      setAiResult(null)
                    }} style={{
                      padding: '8px 16px', borderRadius: '6px',
                      background: 'transparent', border: '1px solid #3D3D3D',
                      color: '#888', cursor: 'pointer',
                    }}>다시 설정</button>
                    <button
                      onClick={async () => {
                        const selected = aiResult.combinations
                          .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                          .map(c => ({ ...c, source_site: aiSourceSite }))
                        if (selected.length === 0) return showAlert('조합을 선택해주세요', 'error')
                        const totalEst = selected.reduce((s, c) => s + c.estimated_count, 0)
                        const site = SITES.find(s => s.id === aiSourceSite)
                        const ok = await showConfirm(
                          `${selected.length}개 검색그룹을 생성하시겠습니까?\n소싱처: ${site?.label || aiSourceSite}\n예상 상품수: ${totalEst.toLocaleString()}개`
                        )
                        if (!ok) return
                        setAiCreating(true)
                        try {
                          const res = await aiSourcingApi.createGroups(selected)
                          showAlert(`${res.created}개 검색그룹 생성 완료`, 'success')
                          setShowAiSourcingModal(false)
                          load(); loadTree()
                        } catch (err) {
                          showAlert(`그룹 생성 실패: ${err instanceof Error ? err.message : '오류'}`, 'error')
                        }
                        setAiCreating(false)
                      }}
                      disabled={aiCreating || aiSelectedCombos.size === 0}
                      style={{
                        padding: '8px 20px', borderRadius: '6px',
                        background: aiCreating ? 'rgba(108,92,231,0.1)' : 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                        color: '#fff', fontWeight: 700, fontSize: '0.85rem',
                        border: 'none', cursor: aiCreating ? 'not-allowed' : 'pointer',
                        opacity: aiSelectedCombos.size === 0 ? 0.5 : 1,
                      }}
                    >
                      {aiCreating ? '생성중...' : `${aiSelectedCombos.size}개 그룹 생성`}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
      {/* AI 작업 진행 모달 */}
      {aiJobModal && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: '#1E1E1E', border: '1px solid #333', borderRadius: '12px', padding: '1.5rem', width: '500px', maxHeight: '70vh', display: 'flex', flexDirection: 'column' }}>
            <h3 style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: '#FF8C00' }}>{aiJobTitle}</h3>
            <div ref={aiJobLogRef} style={{ flex: 1, overflowY: 'auto', background: '#111', borderRadius: '8px', padding: '0.75rem', fontSize: '0.75rem', fontFamily: 'monospace', color: '#CCC', maxHeight: '50vh', lineHeight: 1.6 }}>
              {aiJobLogs.map((msg, i) => {
                let color = '#CCC'
                if (msg.includes('완료')) color = '#51CF66'
                if (msg.includes('실패') || msg.includes('오류')) color = '#FF6B6B'
                if (msg.includes('시작')) color = '#4C9AFF'
                return <div key={i} style={{ color }}>{msg}</div>
              })}
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
              {!aiJobDone && (
                <button onClick={() => { aiJobAbortRef.current = true }} style={{ flex: 1, padding: '0.5rem', background: 'rgba(255,107,107,0.15)', border: '1px solid rgba(255,107,107,0.4)', borderRadius: '6px', color: '#FF6B6B', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>중단</button>
              )}
              {aiJobDone && (
                <button onClick={() => setAiJobModal(false)} style={{ flex: 1, padding: '0.5rem', background: '#333', border: '1px solid #555', borderRadius: '6px', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.8rem' }}>닫기</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

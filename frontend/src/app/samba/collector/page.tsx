"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  collectorApi,
  policyApi,
  proxyApi,
  accountApi,
  type SambaSearchFilter,
  type SambaPolicy,
  type SambaMarketAccount,
  type RefreshResult,
} from "@/lib/samba/api/commerce";
import { fetchWithAuth, API_BASE } from "@/lib/samba/api/shared";
import {
  type AISourcingResult,
} from "@/lib/samba/api/operations";
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SOURCING_SEARCH_URLS } from '@/lib/samba/constants'
import { fmtDate as _fmtDate, fmtTime } from '@/lib/samba/utils'
import { fmtNum } from '@/lib/samba/styles'
import { SITES, SITE_OPTIONS } from './constants'
import AiJobModal from './components/AiJobModal'
import DeleteJobModal from './components/DeleteJobModal'
import MappingModal from './components/MappingModal'
import TagPreviewModal, { type TagPreview, type TagPreviewCost } from './components/TagPreviewModal'
import AiSourcingModal from './components/AiSourcingModal'
import MusinsaBrandModal from './components/MusinsaBrandModal'
import LotteOnBrandModal from './components/LotteOnBrandModal'

const fmtDate = (iso: string | undefined | null) => _fmtDate(iso, '.')

export default function CollectorPage() {
  useEffect(() => { document.title = 'SAMBA-상품수집' }, [])
  const router = useRouter();
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [, setLoading] = useState(true);

  // URL collect
  const [collectUrl, setCollectUrl] = useState("");
  const [collecting, setCollecting] = useState(false);
  const [collectDetailImages, setCollectDetailImages] = useState(false);
  const [collectLog, setCollectLog] = useState<string[]>(["[대기] 수집 결과가 여기에 표시됩니다..."]);
  const [collectQueueStatus, setCollectQueueStatus] = useState<{
    running: Array<{ filter_name: string; source_site: string }>
    pending: Array<{ filter_name: string; source_site: string }>
  }>({ running: [], pending: [] })
  const collectQueuePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [selectedSite, setSelectedSite] = useState("MUSINSA");
  const [checkedOptions, setCheckedOptions] = useState<Record<string, boolean>>({
    excludePreorder: true,
    excludeBoutique: true,
    maxDiscount: true,
  });

  // 무신사 브랜드 선택 모달
  const [brandSearchResults, setBrandSearchResults] = useState<Array<{ brandCode: string; brandName: string }>>([])
  const [showMusinsaBrandModal, setShowMusinsaBrandModal] = useState(false)
  const [pendingKeyword, setPendingKeyword] = useState("")
  const [detectedBrandCode, setDetectedBrandCode] = useState("")
  const [selectedBrandCodes, setSelectedBrandCodes] = useState<Set<string>>(new Set())
  const [brandModalAction, setBrandModalAction] = useState<'scan' | 'create'>('create')
  const pendingScanGf = useRef("A")

  // 카테고리 자동분류 옵션
  const [brandScanning, setBrandScanning] = useState(false)
  const [brandCategories, setBrandCategories] = useState<{ categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }[]>([])
  const [brandSelectedCats, setBrandSelectedCats] = useState<Set<string>>(new Set())
  const [brandTotal, setBrandTotal] = useState(0)

  // 롯데ON 브랜드 선택 모달
  const [showBrandModal, setShowBrandModal] = useState(false)
  const [brandModalList, setBrandModalList] = useState<{ name: string; count: number; id?: string }[]>([])
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
  const [tagPreviews, setTagPreviews] = useState<TagPreview[]>([])
  const [tagPreviewCost, setTagPreviewCost] = useState<TagPreviewCost | null>(null)
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

  // 그룹 삭제 진행 모달
  const [deleteJobModal, setDeleteJobModal] = useState(false)
  const [deleteJobLogs, setDeleteJobLogs] = useState<string[]>([])
  const [deleteJobDone, setDeleteJobDone] = useState(false)

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
  const collectLogSinceRef = useRef(0);
  const collectLogPollingRef = useRef(false);
  const manualCollectRef = useRef(false); // 수동 수집 진행 중 플래그 (자동 감지 종료 판단 방지)

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
  // 프록시 & 무신사 인증 상태 확인
  useEffect(() => {
    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/proxy-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setProxyStatus("ok"); setProxyText(data.message || "프록시 서버 정상 작동 중"); }
        else { setProxyStatus("error"); setProxyText(data.message || "프록시 서버 연결 실패"); }
      })
      .catch(() => { setProxyStatus("error"); setProxyText("백엔드 서버 연결 실패"); });

    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setMusinsaAuth("ok"); setMusinsaAuthText(data.message || "무신사 인증 완료"); }
        else { setMusinsaAuth("error"); setMusinsaAuthText(data.message || "무신사 인증 필요"); }
      })
      .catch(() => { setMusinsaAuth("error"); setMusinsaAuthText("백엔드 서버 연결 실패"); });
  }, []);

  const addLog = useCallback((msg: string) => {
    const time = fmtTime();
    const line = `[${time}] ${msg}`
    setCollectLog((prev) => [...prev, line].slice(-30));
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 50);
  }, []);

  // 수집 로그 링 버퍼 폴링 (서버 로그 — collecting 시작 즉시 폴링)
  useEffect(() => {
    if (!collecting) return
    collectLogPollingRef.current = true
    let checkCount = 0

    const doPoll = async () => {
      if (!collectLogPollingRef.current) return
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-logs?since_idx=${collectLogSinceRef.current}`)
        if (!res.ok) return
        const data = await res.json() as { logs: string[]; current_idx: number }
        if (data.current_idx < collectLogSinceRef.current) {
          collectLogSinceRef.current = 0
          return
        }
        if (data.logs.length > 0) {
          setCollectLog(prev => [...prev, ...data.logs].slice(-30))
          setTimeout(() => {
            if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
          }, 50)
        }
        collectLogSinceRef.current = data.current_idx

        // 5초마다 수집 잡 완료 여부 확인 (자동 감지로 시작된 경우)
        // 수동 수집 진행 중이면 스킵 — 잡 간 간극에서 오검출 방지
        checkCount++
        if (checkCount % 10 === 0 && !manualCollectRef.current) {
          const jRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=running&limit=5`)
          if (jRes.ok) {
            const jobs = await jRes.json() as Array<{ job_type: string; status: string }>
            const stillRunning = jobs.some(j => j.job_type === 'collect')
            if (!stillRunning) {
              const pRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=pending&limit=5`)
              const pJobs = pRes.ok ? await pRes.json() as Array<{ job_type: string }> : []
              const stillPending = pJobs.some(j => j.job_type === 'collect')
              if (!stillPending) {
                setCollecting(false)
                load()
              }
            }
          }
        }
      } catch { /* 네트워크 오류 무시 */ }
    }

    doPoll() // 즉시 첫 poll (500ms 첫 딜레이 제거)
    const timer = setInterval(doPoll, 500)
    return () => { clearInterval(timer); collectLogPollingRef.current = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collecting])

  // 페이지 로드 시 진행 중인 수집 Job 자동 감지 + 로그 복원
  useEffect(() => {
    const detectRunningCollect = async () => {
      try {
        // RUNNING 또는 PENDING 수집 잡이 있는지 확인
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=running&limit=5`)
        if (!res.ok) return
        const jobs = await res.json() as Array<{ job_type: string; status: string }>
        const hasCollect = jobs.some(j => j.job_type === 'collect' && (j.status === 'running' || j.status === 'pending'))
        if (!hasCollect) {
          // PENDING도 확인
          const pRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=pending&limit=5`)
          if (pRes.ok) {
            const pJobs = await pRes.json() as Array<{ job_type: string; status: string }>
            const hasPending = pJobs.some(j => j.job_type === 'collect')
            if (!hasPending) return
          } else return
        }
        // 진행 중 수집 잡 발견 → 링 버퍼에서 기존 로그 복원
        const logRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-logs?since_idx=0`)
        if (logRes.ok) {
          const logData = await logRes.json() as { logs: string[]; current_idx: number }
          if (logData.logs.length > 0) {
            setCollectLog(logData.logs.slice(-30))
          }
          collectLogSinceRef.current = logData.current_idx
        }
        setCollecting(true)
      } catch { /* 무시 */ }
    }
    detectRunningCollect()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 수집 Job 큐 상태 폴링 (5초 간격, 수집 중일 때만)
  useEffect(() => {
    if (!collecting) {
      setCollectQueueStatus({ running: [], pending: [] })
      return
    }
    const fetchStatus = async () => {
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-queue-status`)
        if (res.ok) {
          const data = await res.json() as {
            running: Array<{ filter_name: string; source_site: string }>
            pending: Array<{ filter_name: string; source_site: string }>
          }
          setCollectQueueStatus(data)
        }
      } catch { /* 무시 */ }
    }
    const delay = setTimeout(() => {
      fetchStatus()
      collectQueuePollRef.current = setInterval(fetchStatus, 5000)
    }, 1000)
    return () => { clearTimeout(delay); if (collectQueuePollRef.current) clearInterval(collectQueuePollRef.current) }
  }, [collecting])

  // 브랜드 코드를 포함하여 그룹 생성 (내부 실행)
  const executeCreateGroup = async (brandCode?: string) => {
    const input = collectUrl.trim()
    if (!input) return
    setCollecting(true)
    addLog(`그룹 생성 중: ${input}${brandCode ? ` (브랜드: ${brandCode})` : ''}`)
    try {
      const site = selectedSite
      try {
        const host = new URL(input).hostname
        const siteHostMap: Record<string, string[]> = {
          MUSINSA: ['musinsa.com'], KREAM: ['kream.co.kr'], FashionPlus: ['fashionplus.co.kr'],
          Nike: ['nike.com'], Adidas: ['adidas.co.kr', 'adidas.com'],
          ABCmart: ['a-rt.com'], REXMONDE: ['okmall.com'],
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

      let keyword = ""
      let isUrl = false
      try {
        const parsed = new URL(input)
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
        keyword = input
      }

      const groupName = keyword ? `${site}_${keyword.replace(/\s+/g, '_')}` : `${site}_${new Date().toLocaleDateString("ko-KR")}`

      let keywordUrl = input
      if (site === "MUSINSA") {
        let u: URL
        if (!isUrl) {
          u = new URL("https://www.musinsa.com/search/goods")
          u.searchParams.set("keyword", keyword)
        } else {
          try { u = new URL(input) } catch { u = new URL("https://www.musinsa.com/search/goods"); u.searchParams.set("keyword", keyword) }
        }
        // 브랜드 코드 추가
        if (brandCode) u.searchParams.set("brand", brandCode)
        if (checkedOptions['excludePreorder']) u.searchParams.set("excludePreorder", "1")
        if (checkedOptions['excludeBoutique']) u.searchParams.set("excludeBoutique", "1")
        if (checkedOptions['maxDiscount']) u.searchParams.set("maxDiscount", "1")
        if (checkedOptions['includeSoldOut']) u.searchParams.set("includeSoldOut", "1")
        keywordUrl = u.toString()
      }
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
      // 최대혜택가 옵션 (MUSINSA 외 소싱처)
      if (checkedOptions['maxDiscount'] && site !== 'MUSINSA' && keywordUrl.startsWith('http')) {
        const u = new URL(keywordUrl)
        u.searchParams.set('maxDiscount', '1')
        keywordUrl = u.toString()
      }
      // 품절상품 포함 옵션 (MUSINSA 외 소싱처)
      if (checkedOptions['includeSoldOut'] && site !== 'MUSINSA' && keywordUrl.startsWith('http')) {
        const u = new URL(keywordUrl)
        u.searchParams.set('includeSoldOut', '1')
        keywordUrl = u.toString()
      }

      let requestedCount = 100
      try {
        const countResult = await proxyApi.searchCount(site, keyword, keywordUrl)
        if (countResult.totalCount > 0) {
          requestedCount = countResult.totalCount
          addLog(`검색 결과: ${fmtNum(requestedCount)}개 상품`)
        }
      } catch { /* 조회 실패 시 기본값 100 유지 */ }

      const created = await collectorApi.createFilter({
        source_site: site,
        name: groupName,
        keyword: keywordUrl,
        requested_count: requestedCount,
      })

      addLog(`그룹 생성 완료: "${created.name}" (${site}, ${fmtNum(requestedCount)}개)`)
      setCollectUrl("")
      load(); loadTree()
    } catch (e) {
      addLog(`그룹 생성 실패: ${e instanceof Error ? e.message : "오류"}`)
    }
    setCollecting(false)
  }

  // URL → 그룹 생성 (무신사 평문 키워드 시 브랜드 검색 먼저)
  const handleCreateGroup = async () => {
    const input = collectUrl.trim()
    if (!input) return

    // 무신사 + 평문 키워드인 경우 브랜드 검색
    if (selectedSite === 'MUSINSA') {
      let isUrl = false
      let hasBrand = false
      try {
        const parsed = new URL(input)
        isUrl = true
        hasBrand = !!parsed.searchParams.get('brand')
      } catch { /* 평문 키워드 */ }

      if (!isUrl && !hasBrand) {
        try {
          setCollecting(true)
          addLog(`브랜드 검색 중: ${input}`)
          const res = await proxyApi.brandSearch(input)
          if (res.brands && res.brands.length > 0) {
            if (res.brands.length === 1) {
              addLog(`브랜드 자동 선택: ${res.brands[0].brandName} (${res.brands[0].brandCode})`)
              await executeCreateGroup(res.brands[0].brandCode)
              return
            }
            setPendingKeyword(input)
            setBrandSearchResults(res.brands)
            setSelectedBrandCodes(new Set())
            setBrandModalAction('create')
            setShowMusinsaBrandModal(true)
            setCollecting(false)
            return
          }
          addLog('매칭 브랜드 없음 → 키워드 검색으로 진행')
        } catch {
        }
        setCollecting(false)
      }
    }
    await executeCreateGroup()
  }

  // 무신사 브랜드 선택 모달 확인 — 선택된 브랜드들로 액션 실행
  const handleBrandConfirm = async (codes: Set<string>) => {
    setShowMusinsaBrandModal(false)
    setBrandSearchResults([])
    const brandList = [...codes]
    if (brandList.length > 0) setDetectedBrandCode(brandList[0])

    if (brandModalAction === 'scan') {
      setBrandScanning(true)
      try {
        const keyword = pendingKeyword
        const gf = pendingScanGf.current
        addLog(`[카테고리스캔] 무신사 "${keyword}" 스캔 시작... (${fmtNum(brandList.length)}개 브랜드)`)
        const allCategories: { categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }[] = []
        let totalCount = 0
        for (const code of brandList.length > 0 ? brandList : ['']) {
          const res = await collectorApi.brandScan(code, gf, keyword)
          allCategories.push(...res.categories)
          totalCount += res.total
          if (code) addLog(`[카테고리스캔] ${keyword || code}: ${fmtNum(res.groupCount)}개 카테고리, ${fmtNum(res.total)}건`)
        }
        setBrandCategories(allCategories)
        setBrandTotal(totalCount)
        setBrandSelectedCats(new Set(allCategories.map(c => c.categoryCode)))
        addLog(`[카테고리스캔] 합계: ${fmtNum(allCategories.length)}개 카테고리, 총 ${fmtNum(totalCount)}건`)
      } catch (e) { addLog(`[카테고리스캔] 무신사 스캔 실패: ${e instanceof Error ? e.message : '오류'}`); showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
      setBrandScanning(false)
    } else {
      for (const code of brandList.length > 0 ? brandList : [undefined]) {
        await executeCreateGroup(code)
      }
    }
  }

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

    // 진행 모달 열기
    const allIdsArr = [...allIds]
    const nameMap = new Map(filters.map(f => [f.id, f.name]))
    setDeleteJobLogs([`🗑️ 총 ${allIdsArr.length}개 그룹 삭제 시작...`])
    setDeleteJobDone(false)
    setDeleteJobModal(true)

    let doneCount = 0
    let skipCount = 0
    for (const id of allIdsArr) {
      const groupName = nameMap.get(id) || id
      setDeleteJobLogs(prev => [...prev, `[${doneCount + skipCount + 1}/${allIdsArr.length}] "${groupName}" 처리 중...`])
      try {
        const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: id })
        // 마켓 등록 상품 체크
        const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
        if (registered.length > 0) {
          setDeleteJobLogs(prev => [...prev, `  ⚠️ 마켓등록 상품 ${fmtNum(registered.length)}건 — 삭제 건너뜀`])
          skipCount++
          continue
        }
        const productIds = res.items.map(p => p.id)
        if (productIds.length > 0) {
          setDeleteJobLogs(prev => [...prev, `  상품 ${fmtNum(productIds.length)}건 삭제 중...`])
          await collectorApi.bulkDeleteProducts(productIds)
        }
      } catch { /* 상품 없으면 무시 */ }
      await collectorApi.deleteFilter(id).catch(() => {})
      doneCount++
      setDeleteJobLogs(prev => [...prev, `  ✅ 삭제 완료`])
    }

    setDeleteJobLogs(prev => [...prev, ``, `🎉 완료 — ${doneCount}개 삭제${skipCount > 0 ? `, ${skipCount}개 건너뜀` : ''}`])
    setDeleteJobDone(true)
    setSelectedIds(new Set());
    setSelectAll(false);
    load(); loadTree();
  };

  const handleCollectGroups = async () => {
    // 체크된 그룹이 있으면 체크박스 기준, 없고 상세뷰(drillGroup)가 열려있으면 해당 그룹만, 그 외 전체
    // displayedFilters와 교집합으로 실제 대상 결정
    const targetFilters = drillGroup
      ? displayedFilters.filter(f => f.id === drillGroup)
      : selectedIds.size > 0
        ? displayedFilters.filter(f => selectedIds.has(f.id))
        : displayedFilters
    const sortedTargetFilters = [...targetFilters].sort((a, b) => (b.requested_count || 0) - (a.requested_count || 0))
    const targetIds = sortedTargetFilters.map(f => f.id)
    if (targetIds.length === 0) {
      addLog("수집할 그룹이 없습니다.")
      return
    }
    const totalReq = targetFilters.reduce((s, f) => s + (f.requested_count || 0), 0)
    const label = selectedIds.size > 0 ? '선택된' : drillGroup ? '선택된' : '표시된'
    const ok = await showConfirm(`${label} ${fmtNum(targetIds.length)}개 그룹 상품수집을 시작하시겠습니까?\n(요청 ${fmtNum(totalReq)}건, 중복 상품은 자동 스킵)`)
    if (!ok) return
    const abort = new AbortController()
    collectAbortRef.current = abort
    manualCollectRef.current = true
    setCollecting(true)
    addLog(`${fmtNum(targetIds.length)}개 그룹 상품수집 시작...`)

    for (let gi = 0; gi < targetIds.length; gi++) {
      const id = targetIds[gi]
      if (abort.signal.aborted) break
      const f = filters.find((x) => x.id === id)
      if (!f) continue
      const gp = `[${gi + 1}/${targetIds.length}]`
      // 그룹 전환 시 렌더링 보장
      await new Promise(r => setTimeout(r, 100))
      addLog(`${gp} [${f.name}] 수집 요청 중...`)

      try {
        // Job 생성
        const res = await fetchWithAuth(
          `${API_BASE}/api/v1/samba/collector/collect-filter/${id}?group_index=${gi + 1}&group_total=${targetIds.length}`,
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
            const jobRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
            if (!jobRes.ok) break
            const job = await jobRes.json() as {
              status: string; current: number; total: number
              progress: number; result?: { saved?: number; skipped?: number; policy?: string; message?: string; in_stock_count?: number; sold_out_count?: number }
              error?: string
            }

            if (job.current > lastCurrent) {
              addLog(`${gp} [${f.name}] [${fmtNum(job.current)}/${fmtNum(job.total)}] 수집 중... (${job.progress}%)`)
              lastCurrent = job.current
              load()
            }

            if (job.status === 'completed') {
              const saved = job.result?.saved ?? 0
              const skipped = job.result?.skipped ?? 0
              const policy = job.result?.policy || ''
              const inStock = job.result?.in_stock_count ?? 0
              const soldOut = job.result?.sold_out_count ?? 0
              const parts = [`신규 ${fmtNum(saved)}건`]
              if (inStock > 0 || soldOut > 0) parts.push(`재고 ${fmtNum(inStock)}건 | 품절 ${fmtNum(soldOut)}건`)
              if (skipped > 0) parts.push(`중복/스킵 ${fmtNum(skipped)}건`)
              if (policy) parts.push(policy)
              addLog(`${gp} [${f.name}] 수집 완료: ${parts.join(' | ')}`)
              await new Promise(r => setTimeout(r, 100))
              break
            }
            if (job.status === 'failed') {
              addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '알 수 없는 오류'}`)
              await new Promise(r => setTimeout(r, 100))
              break
            }
          } catch {
            // 네트워크 오류 시 재시도
          }
        }
      } catch (e) {
        addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`)
      }
    }
    manualCollectRef.current = false
    setCollecting(false)
    collectAbortRef.current = null
    // 수집 완료 후 수집한 그룹만 요청수→수집수 동기화
    await syncRequestedCounts(targetIds)
    load(); loadTree()
  }

  // 요청수 ↔ 수집수 자동 동기화 (수집한 그룹만)
  const syncRequestedCounts = async (groupIds?: string[]) => {
    try {
      const latestFilters = await collectorApi.listFilters()
      // groupIds가 주어지면 해당 그룹만, 아니면 전체
      const scope = groupIds
        ? latestFilters.filter((f: SambaSearchFilter) => groupIds.includes(f.id))
        : latestFilters
      const mismatch = scope.filter(
        (f: SambaSearchFilter) => !f.is_folder && (f.requested_count || 0) !== ((f as unknown as Record<string, number>).collected_count || 0)
      )
      for (const f of mismatch) {
        const cc = (f as unknown as Record<string, number>).collected_count || 0
        if (cc > 0) {
          await collectorApi.updateFilter(f.id, { requested_count: cc })
        }
      }
      if (mismatch.length > 0) addLog(`[동기화] ${fmtNum(mismatch.length)}개 그룹 요청수 → 수집수 자동 동기화`)
    } catch { /* 동기화 실패해도 수집 흐름은 유지 */ }
  }

  const handleStopCollect = async () => {
    collectAbortRef.current?.abort()
    addLog('수집 중단 요청...')
    setCollecting(false)
    try {
      await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/cancel-collect`, { method: 'POST' })
    } catch { /* 취소 실패는 무시 */ }
  }

  const handleClearLog = () => {
    setCollectLog(["로그가 초기화되었습니다."])
    collectLogSinceRef.current = 0
    fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-logs/clear`, { method: 'POST' }).catch(() => {})
  };
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
    addLog(filterIds ? `선택된 ${fmtNum(filterIds.length)}개 그룹 갱신 시작...` : '전체 일괄 갱신 시작...')
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
    // Nike 등 단일 브랜드 사이트: 사이트명 자체가 브랜드
    const singleBrandMap: Record<string, string> = { Nike: '나이키' }
    if (singleBrandMap[site]) {
      return { brand: singleBrandMap[site], category: rest }
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
    // 드릴다운 사이트 선택 시 해당 사이트 그룹만 표시
    if (drillSite) {
      const drillSiteName = tree.find(s => s.id === drillSite)?.source_site
      if (drillSiteName) result = result.filter(f => f.source_site === drillSiteName)
    }
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
  }, [filters, siteFilter, drillSite, tree, drillBrand, aiFilter, collectFilter, marketRegFilter, tagRegFilter, policyRegFilter, sortBy])

  // 드롭다운 필터 변경 시 drillBrand 활성 상태면 selectedIds를 displayedFilters 기준으로 재동기화
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
            fetchWithAuth(`${API_BASE}/api/v1/samba/collector/proxy-status`)
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
                disabled={site.disabled}
                onClick={() => {
                  if (site.disabled) return
                  setSelectedSite(site.id)
                  setCollectUrl("")
                  setCheckedOptions(Object.fromEntries(
                    (SITE_OPTIONS[site.id] || []).map(opt => [opt.id, opt.id === 'includeSoldOut' ? false : true])
                  ))
                }}
                style={{
                  padding: "0.35rem 0.875rem", borderRadius: "20px", fontSize: "0.8rem",
                  fontWeight: selectedSite === site.id ? 700 : 400,
                  cursor: site.disabled ? "not-allowed" : "pointer",
                  border: site.disabled ? "1px solid #2A2A2A" : selectedSite === site.id ? "1px solid #FF8C00" : "1px solid #3D3D3D",
                  background: site.disabled ? "transparent" : selectedSite === site.id ? "rgba(255,140,0,0.15)" : "transparent",
                  color: site.disabled ? "#555" : selectedSite === site.id ? "#FF8C00" : "#C5C5C5",
                  opacity: site.disabled ? 0.6 : 1,
                  transition: "all 0.15s",
                }}
              >{site.label}{site.disabled ? ' (예정)' : ''}</button>
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
            <div style={{ display: "flex", gap: "14px", paddingLeft: "4px", alignItems: "center" }}>
              {(SITE_OPTIONS[selectedSite] || []).map((opt) => (
                <label key={opt.id} style={{ display: "flex", alignItems: "center", gap: "5px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!checkedOptions[opt.id]}
                    onChange={(e) => setCheckedOptions((prev) => ({ ...prev, [opt.id]: e.target.checked }))}
                    style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "0.78rem", color: "#999" }}>{opt.label}</span>
                  {opt.warn && checkedOptions[opt.id] && (
                    <span style={{ fontSize: "0.7rem", color: "#FF6B35" }}>{opt.warn}</span>
                  )}
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
            onChange={(e) => { setCollectUrl(e.target.value); setDetectedBrandCode('') }}
            onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault() }}
            placeholder={
              selectedSite === "MUSINSA" ? "키워드 또는 URL (예: 나이키, https://www.musinsa.com/search/goods?keyword=나이키)" :
              selectedSite === "KREAM" ? "키워드 또는 URL (예: 나이키, https://kream.co.kr/search?keyword=나이키)" :
              selectedSite === "DANAWA" ? "키워드 또는 URL (예: 에어팟, https://search.danawa.com/dsearch.php?keyword=에어팟)" :
              selectedSite === "FashionPlus" ? "키워드 또는 URL (예: 나이키, https://www.fashionplus.co.kr/search/goods/result?searchWord=나이키)" :
              selectedSite === "Nike" ? "키워드 또는 URL (예: 에어포스, https://www.nike.com/kr/w?q=에어포스)" :
              selectedSite === "Adidas" ? "키워드 또는 URL (예: 삼바, https://www.adidas.co.kr/search?q=삼바)" :
              selectedSite === "ABCmart" ? "키워드 또는 URL (예: 나이키, https://www.a-rt.com/abc/display/search?keyword=나이키)" :
              selectedSite === "REXMONDE" ? "키워드 또는 URL (예: 나이키, https://www.okmall.com/search?keyword=나이키)" :
              selectedSite === "SSG" ? "키워드 또는 URL (예: 나이키, https://www.ssg.com/search.ssg?query=나이키)" :
              selectedSite === "LOTTEON" ? "키워드 또는 URL (예: 나이키, https://www.lotteon.com/search?query=나이키)" :
              selectedSite === "GSShop" ? "키워드 또는 URL (예: 내셔널지오그래픽, https://www.gsshop.com/search?tq=내셔널지오그래픽)" :
              selectedSite === "ElandMall" ? "키워드 또는 URL (예: 나이키, https://www.elandmall.com/search?kwd=나이키)" :
              selectedSite === "SSF" ? "키워드 또는 URL (예: 나이키, https://www.ssfshop.com/search?keyword=나이키)" :
              "키워드 또는 URL을 입력하세요"
            }
            style={{
              flex: 1, padding: "0.6rem 0.8rem", fontSize: "0.82rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
              color: "#E5E5E5", outline: "none",
            }}
          />
          {(selectedSite === 'MUSINSA' || selectedSite === 'LOTTEON' || selectedSite === 'GSShop' || selectedSite === 'ABCmart' || selectedSite === 'Nike' || selectedSite === 'SSG' || selectedSite === 'FashionPlus' || selectedSite === 'KREAM') && (
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

              // 롯데ON / SSG / 패션플러스: 브랜드 탐색 후 선택 모달 표시
              if (selectedSite === 'LOTTEON' || selectedSite === 'SSG' || selectedSite === 'FashionPlus') {
                try {
                  const discoverKeyword = keyword || brand
                  const res = await collectorApi.brandDiscover(discoverKeyword, selectedSite)
                  setBrandModalList(res.brands)
                  setBrandModalSelected(new Set())
                  setBrandModalKeyword(discoverKeyword)
                  setBrandModalParsed({ brand, keyword, gf })
                  setShowBrandModal(true)
                } catch (e) { showAlert(e instanceof Error ? e.message : '브랜드 탐색 실패', 'error') }
                setBrandScanning(false)
                return
              }

              // GS샵: 키워드만으로 바로 스캔 (백화점 탭) + 진행 상황 폴링
              if (selectedSite === 'GSShop') {
                const scanKeyword = keyword || brand || collectUrl.trim()
                addLog(`[카테고리스캔] GS샵 백화점 "${scanKeyword}" 스캔 시작...`)
                // 진행 상황 폴링 (3초 간격)
                const pollId = setInterval(async () => {
                  try {
                    const p = await collectorApi.gsshopScanProgress()
                    if (p.stage === 'search') {
                      addLog(`[카테고리스캔] 검색 중... ${p.page}페이지, ${fmtNum(p.products ?? 0)}개 상품 발견`)
                    } else if (p.stage === 'detail') {
                      const done = (p.detail_ok ?? 0) + (p.detail_fail ?? 0)
                      addLog(`[카테고리스캔] 상세 조회 중... ${fmtNum(done)}/${fmtNum(p.detail_total ?? 0)}건 (성공: ${fmtNum(p.detail_ok ?? 0)}, 실패: ${fmtNum(p.detail_fail ?? 0)})`)
                    }
                  } catch { /* 폴링 실패 무시 */ }
                }, 3000)
                try {
                  const res = await collectorApi.brandScan('', 'A', scanKeyword, 'GSSHOP')
                  clearInterval(pollId)
                  setBrandCategories(res.categories)
                  setBrandTotal(res.total)
                  setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                  addLog(`[카테고리스캔] 완료: ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
                } catch (e) {
                  clearInterval(pollId)
                  showAlert(e instanceof Error ? e.message : '스캔 실패', 'error')
                }
                setBrandScanning(false)
                return
              }

              // ABC마트: 키워드만으로 바로 스캔
              if (selectedSite === 'ABCmart') {
                const scanKeyword = keyword || brand || collectUrl.trim()
                addLog(`[카테고리스캔] ABC마트 "${scanKeyword}" 스캔 시작...`)
                try {
                  const res = await collectorApi.brandScan('', 'A', scanKeyword, 'ABCmart')
                  setBrandCategories(res.categories)
                  setBrandTotal(res.total)
                  setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                  addLog(`[카테고리스캔] ABC마트: ${scanKeyword} → ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
                } catch (e) { addLog(`[카테고리스캔] ABC마트 스캔 실패: ${e instanceof Error ? e.message : '오류'}`); showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
                setBrandScanning(false)
                return
              }

              // 나이키: 키워드만으로 바로 스캔
              if (selectedSite === 'Nike') {
                const scanKeyword = keyword || brand || collectUrl.trim()
                addLog(`[카테고리스캔] Nike "${scanKeyword}" 스캔 시작...`)
                try {
                  const res = await collectorApi.brandScan('', 'A', scanKeyword, 'Nike')
                  setBrandCategories(res.categories)
                  setBrandTotal(res.total)
                  setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                  addLog(`[카테고리스캔] Nike: ${scanKeyword} → ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
                } catch (e) { addLog(`[카테고리스캔] Nike 스캔 실패: ${e instanceof Error ? e.message : '오류'}`); showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
                setBrandScanning(false)
                return
              }

              // KREAM: 키워드만으로 바로 스캔
              if (selectedSite === 'KREAM') {
                const scanKeyword = keyword || brand || collectUrl.trim()
                addLog(`[카테고리스캔] KREAM "${scanKeyword}" 스캔 시작...`)
                try {
                  const res = await collectorApi.brandScan('', 'A', scanKeyword, 'KREAM')
                  setBrandCategories(res.categories)
                  setBrandTotal(res.total)
                  setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                  addLog(`[카테고리스캔] KREAM: ${scanKeyword} → ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
                } catch (e) { addLog(`[카테고리스캔] KREAM 스캔 실패: ${e instanceof Error ? e.message : '오류'}`); showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
                setBrandScanning(false)
                return
              }

              // 무신사: 평문 키워드이고 브랜드 코드 없으면 브랜드 검색 모달 표시
              if (!brand && !parsed) {
                try {
                  const brandRes = await proxyApi.brandSearch(keyword)
                  if (brandRes.brands && brandRes.brands.length > 0) {
                    setPendingKeyword(keyword)
                    pendingScanGf.current = gf
                    setBrandSearchResults(brandRes.brands)
                    setSelectedBrandCodes(new Set())
                    setBrandModalAction('scan')
                    setShowMusinsaBrandModal(true)
                    setBrandScanning(false)
                    return
                  }
                } catch { /* 브랜드 검색 실패 시 키워드로 진행 */ }
              }
              addLog(`[카테고리스캔] ${selectedSite} "${keyword || brand}" 스캔 시작...`)
              try {
                const res = await collectorApi.brandScan(brand, gf, keyword, selectedSite)
                setBrandCategories(res.categories)
                setBrandTotal(res.total)
                setBrandSelectedCats(new Set(res.categories.map(c => c.categoryCode)))
                addLog(`[카테고리스캔] ${keyword || brand}: ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
              } catch (e) { addLog(`[카테고리스캔] ${selectedSite} 스캔 실패: ${e instanceof Error ? e.message : '오류'}`); showAlert(e instanceof Error ? e.message : '스캔 실패', 'error') }
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
                const brand = parsed?.searchParams.get('brand') || pathBrandMatch?.[1] || detectedBrandCode || ''
                const keyword = parsed?.searchParams.get('keyword') || parsed?.searchParams.get('searchWord') || (!brand ? collectUrl.trim() : '')
                const gf = parsed?.searchParams.get('gf') || 'A'
                try {
                  const res = await collectorApi.brandCreateGroups({
                    brand, brand_name: pendingKeyword || keyword || brand, gf,
                    categories: selected,
                    requested_count_per_group: -1,
                    real_total: brandTotal,
                    options: checkedOptions,
                    source_site: selectedSite,
                    selected_brands: brandModalParsed ? Array.from(brandModalSelected) : undefined,
                    // SSG repBrandId 필터: 선택된 브랜드 id 목록 전달
                    brand_ids: brandModalParsed
                      ? brandModalList.filter(b => brandModalSelected.has(b.name) && b.id).map(b => b.id as string)
                      : undefined,
                  })
                  addLog(`[카테고리분류] ${fmtNum(res.created)}개 그룹 생성 완료`)
                  showAlert(`${fmtNum(res.created)}개 그룹이 생성되었습니다`, 'success')
                  addLog(`[카테고리분류] ${fmtNum(res.created)}개 그룹 생성 (카테고리 간 중복은 수집 시 자동 스킵)`)
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
          {/* 1상품수집 버튼 — 무신사 전용 */}
          {selectedSite === 'MUSINSA' && (
            <button
              onClick={async () => {
                const url = collectUrl.trim()
                if (!url) { showAlert('URL을 입력하세요'); return }
                setCollecting(true)
                addLog(`[1상품수집] ${url} 수집 시작...`)
                try {
                  const res = await collectorApi.collectSingleMusinsa(url)
                  addLog(`[1상품수집] 완료: 상품번호 ${res.product_no} (${res.brand})`)
                  showAlert('1상품 수집 완료', 'success')
                  setCollectUrl('')
                  load(); loadTree()
                } catch (e) {
                  addLog(`[1상품수집] 실패: ${e instanceof Error ? e.message : '오류'}`)
                  showAlert(e instanceof Error ? e.message : '수집 실패', 'error')
                }
                setCollecting(false)
              }}
              disabled={collecting}
              style={{
                background: collecting ? '#333' : 'transparent',
                border: '1px solid #51CF66',
                color: '#51CF66',
                padding: '0.6rem 1rem', borderRadius: '6px', fontWeight: 600, fontSize: '0.82rem',
                whiteSpace: 'nowrap', cursor: collecting ? 'not-allowed' : 'pointer', opacity: collecting ? 0.6 : 1,
              }}
            >
              1상품수집
            </button>
          )}
        </div>

        {/* 롯데ON 브랜드 선택 — 무신사 모달 스타일 */}

        {/* 카테고리 스캔 결과 */}
        {brandCategories.length > 0 && (
          <div style={{ marginTop: '0.5rem' }}>
              <div style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem', maxHeight: '350px', overflowY: 'auto' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span style={{ fontSize: '0.78rem', color: '#888' }}>
                    {fmtNum(brandCategories.length)}개 카테고리 / {fmtNum(brandTotal)}건
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
                    <span style={{ color: '#FF8C00', fontWeight: 600, fontSize: '0.72rem' }}>{fmtNum(cat.count)}건</span>
                  </label>
                ))}
              </div>
            </div>
        )}
      </div>

      {/* 롯데ON 브랜드 선택 모달 — 제거됨, 인라인 섹션으로 이동 */}

      {/* 무신사 브랜드 선택 모달 */}
      <MusinsaBrandModal
        open={showMusinsaBrandModal}
        brandSearchResults={brandSearchResults}
        pendingKeyword={pendingKeyword}
        selectedBrandCodes={selectedBrandCodes}
        setSelectedBrandCodes={setSelectedBrandCodes}
        onClose={() => { setShowMusinsaBrandModal(false); setCollecting(false) }}
        onConfirm={handleBrandConfirm}
      />

      {/* 롯데ON / SSG 브랜드 선택 모달 */}
      <LotteOnBrandModal
        open={showBrandModal}
        brandModalList={brandModalList}
        brandModalSelected={brandModalSelected}
        brandModalKeyword={brandModalKeyword}
        brandModalParsed={brandModalParsed}
        selectedSite={selectedSite}
        setBrandModalSelected={setBrandModalSelected}
        onClose={() => setShowBrandModal(false)}
        onScanStart={() => { setBrandScanning(true); setBrandCategories([]); setBrandSelectedCats(new Set()) }}
        onScanDone={(categories, total) => {
          setBrandCategories(categories)
          setBrandTotal(total)
          setBrandSelectedCats(new Set(categories.map(c => c.categoryCode)))
          setBrandScanning(false)
        }}
        addLog={addLog}
      />

      {/* 로그현황 */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        overflow: "hidden", marginBottom: "1rem",
      }}>
        <div style={{
          padding: "8px 16px", borderBottom: "1px solid #2D2D2D",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#C5C5C5" }}>로그현황</span>
            {(() => {
              const { running, pending } = collectQueueStatus
              const hasActivity = running.length > 0 || pending.length > 0
              // 브랜드별 그룹핑
              const groupByBrand = (items: Array<{ filter_name: string; source_site: string }>) => {
                const brands = new Map<string, number>()
                for (const item of items) {
                  const parsed = parseGroupName(item.filter_name, item.source_site)
                  const brand = parsed.brand || item.source_site || '알수없음'
                  brands.set(brand, (brands.get(brand) || 0) + 1)
                }
                return brands
              }
              const runBrands = groupByBrand(running)
              const penBrands = groupByBrand(pending)
              const formatBrands = (brands: Map<string, number>, total: number) => {
                const entries = [...brands.entries()]
                if (entries.length === 0) return ''
                if (entries.length <= 2) return entries.map(([b, c]) => c > 1 ? `${b} ${c}건` : b).join('/')
                return `${entries[0][0]} 외 ${entries.length - 1}개`
              }
              return (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem' }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
                    background: running.length > 0 ? '#51CF66' : pending.length > 0 ? '#FAB005' : '#444',
                  }} />
                  {running.length > 0 && (
                    <span style={{ color: '#51CF66' }}>
                      {formatBrands(runBrands, running.length)} 진행 {fmtNum(running.length)}건
                    </span>
                  )}
                  {pending.length > 0 && (
                    <span style={{ color: '#FAB005' }}>
                      {running.length > 0 ? '+ ' : ''}{formatBrands(penBrands, pending.length)} 대기 {fmtNum(pending.length)}건
                    </span>
                  )}
                  {!hasActivity && <span style={{ color: '#555' }}>대기 잡 없음</span>}
                </div>
              )
            })()}
          </div>
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
              <span style={{ fontSize: '0.78rem', color: '#FFB84D' }}>₩{fmtNum(lastAiUsage.cost)}</span>
              <span style={{ fontSize: '0.7rem', color: '#555' }}>{lastAiUsage.date}</span>
            </>
          ) : (
            <span style={{ fontSize: '0.78rem', color: '#555' }}>사용 내역 없음</span>
          )}
        </div>
        {/* AI 이미지 변환 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 이미지 변환</span>
          {([['thumbnail', '대표'], ['additional', '추가'], ['detail', '상세']] as const).map(([key, label]) => (
            <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
              <input type="checkbox" checked={aiImgScope[key]}
                onChange={() => setAiImgScope(prev => ({ ...prev, [key]: !prev[key] }))}
                style={{ accentColor: '#FF8C00', width: '13px', height: '13px' }} />
              <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{label}</span>
            </label>
          ))}
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
          <span style={{ fontSize: '0.78rem', color: '#888' }}>({selectedIds.size}개 그룹)</span>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
              // displayedFilters와 교집합으로 실제 대상 결정
              const activeIds = [...selectedIds].filter(id => displayedFilters.some(f => f.id === id))
              if (activeIds.length === 0) { showAlert('현재 필터에 해당하는 그룹이 없습니다'); return }
              if (!aiImgScope.thumbnail && !aiImgScope.additional && !aiImgScope.detail) { showAlert('변환 대상 이미지를 선택해주세요 (대표/추가/상세)'); return }
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
              if (productIds.length === 0) { showAlert(skippedAi > 0 ? `모든 상품이 이미 AI 변환 완료 (${fmtNum(skippedAi)}건 스킵)` : '선택된 그룹에 상품이 없습니다'); return }
              const skipMsg = skippedAi > 0 ? `\n(AI 변환 완료 ${fmtNum(skippedAi)}건 스킵)` : ''
              const scopeLabel = [aiImgScope.thumbnail && '대표', aiImgScope.additional && '추가', aiImgScope.detail && '상세'].filter(Boolean).join('+')
              const ok = await showConfirm(`${fmtNum(activeIds.length)}개 그룹 (${fmtNum(productIds.length)}개 상품)의 ${scopeLabel} 이미지를 변환하시겠습니까?${skipMsg}`)
              if (!ok) return
              const ts = fmtTime
              setAiImgTransforming(true)
              aiJobAbortRef.current = false
              setAiJobTitle(`AI 이미지변환 (${fmtNum(productIds.length)}개)`)
              setAiJobLogs([])
              setAiJobDone(false)
              setAiJobModal(true)
              const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
              const startTime = ts()
              addLog(`시작: ${startTime} (${fmtNum(productIds.length)}개 상품)`)
              let success = 0
              let fail = 0
              for (let i = 0; i < productIds.length; i++) {
                if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${fmtNum(i)}/${fmtNum(productIds.length)})`); break }
                const label = productIds[i].slice(-8)
                setAiJobTitle(`AI 이미지변환 [${fmtNum(i + 1)}/${fmtNum(productIds.length)}]`)
                try {
                  const res = await proxyApi.transformImages([productIds[i]], aiImgScope, aiImgMode, aiModelPreset)
                  if (res.success) { success++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 완료`) }
                  else { fail++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 실패: ${res.message}`) }
                } catch (e) { fail++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
              }
              const endTime = ts()
              setAiJobTitle(`AI 이미지변환 완료 (${fmtNum(success)}/${fmtNum(productIds.length)})`)
              addLog(`\n완료: 성공 ${fmtNum(success)}개 / 실패 ${fmtNum(fail)}개`)
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
              const ok = await showConfirm(`선택된 ${fmtNum(activeGroupIds.length)}개 그룹의 ${scopeLabel} 이미지를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
              if (!ok) return
              const scope = imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') && imgFilterScopes.has('detail') ? 'all' : imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') ? 'images' : imgFilterScopes.has('detail') ? 'detail' : [...imgFilterScopes][0] || 'images'
              setImgFiltering(true)
              aiJobAbortRef.current = false
              setAiJobTitle(`이미지 필터링 (${fmtNum(activeGroupIds.length)}개 그룹)`)
              setAiJobLogs([])
              setAiJobDone(false)
              setAiJobModal(true)
              const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
              const ts = fmtTime
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
                  addLog(`\n[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — 상품 조회중...`)
                  try {
                    const { items: products } = await collectorApi.scrollProducts({ search_filter_id: gid, limit: 10000 })
                    totalProducts += products.length
                    addLog(`[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — ${fmtNum(products.length)}개 상품`)
                    if (gi === 0 && products.length > 0) addLog(`\n시작: ${startTime} (${fmtNum(totalProducts)}개 상품)\n`)
                    for (let i = 0; i < products.length; i++) {
                      if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${fmtNum(processedProducts)}/${fmtNum(totalProducts)})`); break }
                      const prod = products[i]
                      const prodName = prod.name?.slice(0, 25) || '이름없음'
                      const prodNo = prod.site_product_id || prod.id.slice(-8)
                      const prodBrand = prod.brand || '-'
                      const label = `${prodBrand} / ${prodNo} / ${prodName}${prod.name && prod.name.length > 25 ? '...' : ''}`
                      processedProducts++
                      setAiJobTitle(`이미지 필터링 [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${prodBrand} / ${prodNo}`)
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
                              steps.push(`긴이미지 ${fmtNum(tallUrls.length)}장 제거`)
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
                          addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — ${steps.join(' → ')}`)
                        } else { fail++; addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — ${steps.length > 0 ? steps.join(' → ') + ' → ' : ''}실패`) }
                      } catch (e) { fail++; addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
                    }
                  } catch (e) {
                    addLog(`[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — 상품 조회 실패: ${e instanceof Error ? e.message : ''}`)
                  }
                }
                const summary = [`성공 ${fmtNum(success)}개`, `실패 ${fmtNum(fail)}개`]
                if (totalTall > 0) summary.push(`긴이미지 ${fmtNum(totalTall)}장 제거`)
                if (totalVisionRemoved > 0) summary.push(`CLIP ${fmtNum(totalVisionRemoved)}장 제거`)
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
              <option value="registered">전체등록</option>
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
                if (!await showConfirm(`${fmtNum(mismatch.length)}개 그룹의 요청수를 수집수로 동기화하시겠습니까?`)) return
                let synced = 0
                for (const f of mismatch) {
                  try {
                    await collectorApi.updateFilter(f.id, { requested_count: f.collected_count || 0 })
                    synced++
                  } catch { /* skip */ }
                }
                showAlert(`${fmtNum(synced)}개 그룹 동기화 완료`, 'success')
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
                  const sourceSite = sampleFilter.source_site || 'MUSINSA'
                  const parsed = (() => { try { return new URL(sampleFilter.keyword || '') } catch { return null } })()
                  const gf = parsed?.searchParams.get('gf') || 'A'
                  // 소싱처별 브랜드/키워드 추출
                  let brand = ''
                  if (sourceSite === 'MUSINSA') {
                    brand = parsed?.searchParams.get('brand') || ''
                  } else if (sourceSite === 'Nike') {
                    brand = parsed?.searchParams.get('q') || ''
                  } else if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') {
                    brand = parsed?.searchParams.get('searchWord') || ''
                  } else if (sourceSite === 'GSShop') {
                    brand = parsed?.searchParams.get('tq') || ''
                  } else if (sourceSite === 'LOTTEON') {
                    brand = parsed?.searchParams.get('q') || ''
                  } else {
                    brand = parsed?.searchParams.get('q') || parsed?.searchParams.get('brand') || parsed?.searchParams.get('searchWord') || parsed?.searchParams.get('tq') || ''
                  }
                  if (!brand) { showAlert(`${sourceSite}에서 브랜드 정보를 찾을 수 없습니다`); return }

                  // 여러 소싱처·브랜드 혼재 시 오류 — drillBrand가 없을 때만 체크
                  if (!drillBrand) {
                    const mixedSite = displayedFilters.some(f => f.source_site !== sourceSite)
                    if (mixedSite) {
                      showAlert('여러 소싱처가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'warning')
                      return
                    }
                    const extractB = (f: (typeof displayedFilters)[0]) => {
                      const p = (() => { try { return new URL(f.keyword || '') } catch { return null } })()
                      if (sourceSite === 'MUSINSA') return p?.searchParams.get('brand') || ''
                      if (sourceSite === 'Nike') return p?.searchParams.get('q') || ''
                      if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') return p?.searchParams.get('searchWord') || ''
                      if (sourceSite === 'GSShop') return p?.searchParams.get('tq') || ''
                      if (sourceSite === 'LOTTEON') return p?.searchParams.get('q') || ''
                      return p?.searchParams.get('q') || p?.searchParams.get('brand') || p?.searchParams.get('searchWord') || p?.searchParams.get('tq') || ''
                    }
                    const mixedBrand = displayedFilters.some(f => extractB(f) !== brand)
                    if (mixedBrand) {
                      showAlert('여러 브랜드가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'warning')
                      return
                    }
                  }

                  const brandName = drillBrand || brand
                  // 선택된 카테고리 코드 추출
                  const selectedCategories: string[] = []
                  if (drillGroup) {
                    // 트리에서 단일 카테고리 선택
                    const sf = filters.find(f => f.id === drillGroup)
                    if (sf) {
                      if (sourceSite === 'MUSINSA') {
                        const catParam = (() => { try { return new URL(sf.keyword || '').searchParams.get('category') } catch { return null } })()
                        if (catParam) selectedCategories.push(catParam)
                      } else {
                        const cf = (sf as unknown as Record<string, string>).category_filter
                        if (cf) selectedCategories.push(cf)
                      }
                    }
                  } else if (selectedIds.size > 0 && selectedIds.size < displayedFilters.length) {
                    // 체크박스로 일부 카테고리 선택
                    for (const sf of displayedFilters.filter(f => selectedIds.has(f.id))) {
                      if (sourceSite === 'MUSINSA') {
                        const catParam = (() => { try { return new URL(sf.keyword || '').searchParams.get('category') } catch { return null } })()
                        if (catParam) selectedCategories.push(catParam)
                      } else {
                        const cf = (sf as unknown as Record<string, string>).category_filter
                        if (cf) selectedCategories.push(cf)
                      }
                    }
                  }
                  const scopeText = selectedCategories.length > 0
                    ? `\n\n대상: 선택 카테고리 ${selectedCategories.length}개`
                    : '\n\n대상: 전체 카테고리'
                  const ok = await showConfirm(`${brandName} 추가수집을 실행하시겠습니까?\n\n• 신규 카테고리 → 그룹 자동 생성\n• 기존 카테고리 → 요청수 갱신 후 수집${scopeText}`)
                  if (!ok) return
                  addLog(`[추가수집] ${brandName} 카테고리 스캔 중...${selectedCategories.length > 0 ? ` (선택 ${selectedCategories.length}개)` : ''}`)
                  try {
                    const res = await collectorApi.brandRefresh({ brand, brand_name: brandName, gf, options: checkedOptions, source_site: sourceSite, categories: selectedCategories.length > 0 ? selectedCategories : undefined })
                    addLog(`[추가수집] ${res.message}`)
                    await load(); await loadTree()
                    // 갱신 후 자동 수집 시작 — 선택된 범위만 대상
                    let updatedFilters: typeof filters
                    if (drillGroup) {
                      const refreshed = (await collectorApi.listFilters()).find(f => f.id === drillGroup)
                      updatedFilters = refreshed ? [refreshed] : []
                    } else if (res.filter_ids && res.filter_ids.length > 0) {
                      // 백엔드가 반환한 filter_ids 직접 사용 (brand 매칭 오류/race condition 방지)
                      const idSet = new Set(res.filter_ids)
                      const allFilters = await collectorApi.listFilters()
                      updatedFilters = allFilters.filter(f => idSet.has(f.id))
                    } else if (selectedCategories.length > 0) {
                      const catSet = new Set(selectedCategories)
                      updatedFilters = (await collectorApi.listFilters()).filter(f => {
                        if (f.source_site !== sourceSite) return false
                        let fCat = ''
                        if (sourceSite === 'MUSINSA') {
                          try { fCat = new URL(f.keyword || '').searchParams.get('category') || '' } catch { /* */ }
                        } else {
                          fCat = (f as unknown as Record<string, string>).category_filter || ''
                        }
                        return fCat !== '' && catSet.has(fCat)
                      })
                    } else {
                      updatedFilters = (await collectorApi.listFilters()).filter(f => {
                        if (f.source_site !== sourceSite) return false
                        const p = (() => { try { return new URL(f.keyword || '') } catch { return null } })()
                        if (sourceSite === 'MUSINSA') return p?.searchParams.get('brand') === brand
                        if (sourceSite === 'Nike') return p?.searchParams.get('q') === brand
                        if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') return p?.searchParams.get('searchWord') === brand
                        if (sourceSite === 'GSShop') return p?.searchParams.get('tq') === brand
                        if (sourceSite === 'LOTTEON') return p?.searchParams.get('q') === brand
                        return p?.searchParams.get('q') === brand || p?.searchParams.get('brand') === brand
                      })
                    }
                    if (updatedFilters.length > 0) {
                      const collectOk = await showConfirm(`${res.message}\n\n${fmtNum(updatedFilters.length)}개 그룹 상품수집을 시작하시겠습니까?`)
                      if (collectOk) {
                        updatedFilters = [...updatedFilters].sort((a, b) => (b.requested_count || 0) - (a.requested_count || 0))
                        const abort = new AbortController()
                        collectAbortRef.current = abort
                        manualCollectRef.current = true
                        setCollecting(true)
                        addLog(`${fmtNum(updatedFilters.length)}개 그룹 상품수집 시작...`)
                        for (let gi = 0; gi < updatedFilters.length; gi++) {
                          const f = updatedFilters[gi]
                          if (abort.signal.aborted) break
                          const gp = `[${gi + 1}/${updatedFilters.length}]`
                          addLog(`${gp} [${f.name}] 수집 요청 중...`)
                          try {
                            const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/collect-filter/${f.id}?group_index=${gi + 1}&group_total=${updatedFilters.length}`, { method: 'POST' })
                            if (!r.ok) { addLog(`[${f.name}] 수집 실패: HTTP ${r.status}`); continue }
                            const { job_id } = await r.json()
                            // 수집 시작 로그 생략
                            let lastCurrent = 0
                            while (!abort.signal.aborted) {
                              await new Promise(r => setTimeout(r, 1000))
                              if (abort.signal.aborted) break
                              const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                              if (!jr.ok) break
                              const job = await jr.json()
                              if (job.current > lastCurrent) { addLog(`${gp} [${f.name}] [${fmtNum(job.current)}/${fmtNum(job.total)}] 수집 중... (${job.progress}%)`); lastCurrent = job.current }
                              if (job.status === 'completed') {
                                break
                              }
                              if (job.status === 'failed') { addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '오류'}`); break }
                            }
                          } catch (e) { addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`) }
                        }
                        manualCollectRef.current = false
                        setCollecting(false)
                        await syncRequestedCounts(updatedFilters.map(f => f.id))
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
                // selectedIds 기준으로 대상 결정 (드릴다운 클릭도 selectedIds에 포함됨)
                const checkedIds = selectAll ? displayedFilters.map(f => f.id) : [...selectedIds]
                // displayedFilters와 교집합으로 실제 대상 결정
                const targetFilters = checkedIds.length > 0
                  ? displayedFilters.filter(f => checkedIds.includes(f.id))
                  : [...displayedFilters]
                if (targetFilters.length === 0) { showAlert('검색그룹이 없습니다'); return }
                const ok = await showConfirm(`${checkedIds.length > 0 ? '선택된' : '전체'} ${fmtNum(targetFilters.length)}개 그룹의 상품에 AI 태그를 생성하시겠습니까?\n(그룹별 대표 1개로 API 호출, 미리보기 후 확정)`)
                if (!ok) return
                setTagPreviewLoading(true)
                try {
                  addLog(`[AI태그] ${fmtNum(targetFilters.length)}개 그룹 태그 생성 시작...`)
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
                        addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → SEO: ${seo.join(', ')} | 태그: ${fmtNum(tags.length)}개`)
                      } else {
                        addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → 태그 없음`)
                      }
                    } catch (e) {
                      addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → 실패: ${e instanceof Error ? e.message : '오류'}`)
                    }
                  }
                  addLog(`[AI태그] 완료: ${fmtNum(allPreviews.length)}/${fmtNum(targetFilters.length)}개 그룹 | API ${fmtNum(totalCalls)}회 | ${fmtNum(Number(totalCost.toFixed(0)))}원`)
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
            수집 <span style={{ color: '#FF8C00' }}>{fmtNum(filters.reduce((s, f) => s + ((f as unknown as Record<string, number>).collected_count ?? 0), 0))}</span>
            <span style={{ color: '#555' }}> / </span>
            요청 <span style={{ color: '#FFB84D' }}>{fmtNum(filters.filter(f => !f.is_folder).reduce((s, f) => s + (f.requested_count ?? 0), 0))}</span>
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
          if (marketRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const r = l as unknown as Record<string, number>
              const cnt = r.market_registered_count ?? 0
              const total = r.collected_count ?? 0
              if (marketRegFilter === 'registered') return cnt > 0 && cnt >= total
              if (marketRegFilter === 'partial') return cnt > 0 && cnt < total
              if (marketRegFilter === 'unregistered') return cnt === 0
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
          const brandMap = new Map<string, { count: number; collected: number }>()
          brandLeaves.forEach(l => {
            const prev = brandMap.get(l._brand) || { count: 0, collected: 0 }
            brandMap.set(l._brand, {
              count: prev.count + 1,
              collected: prev.collected + ((l as unknown as Record<string, number>).collected_count ?? 0)
            })
          })
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
          // 사이트12 브랜드13 카테고리22 링크15 정책10 수집8 요청6 생성일11 매핑3
          const colW = ['12%', '13%', '22%', '15%', '10%', '8%', '6%', '11%', '3%']
          const colBase = { borderRight: '1px solid #2D2D2D', maxHeight: '320px', overflowY: 'auto' as const, boxSizing: 'border-box' as const, textAlign: 'left' as const }
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
                        <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: '#FF8C00', fontWeight: 600 }}>
                          {(() => {
                            const leaves = allLeafInfos.filter(l => l._siteId === s.id)
                            const collected = leaves.reduce((sum, l) => sum + ((l as unknown as Record<string, number>).collected_count ?? 0), 0)
                            return `${leaves.length}(${fmtNum(collected)})`
                          })()}
                        </span>
                      </div>
                    ))
                  ) : null}
                </div>
                {/* 2. 브랜드: 브랜드 헤더 클릭 시 전체 표시 / 사이트 선택 시 연관만 표시 */}
                <div style={colStyle(1)}>
                  {(drillEntry === 'brand' || drillSite) ? (
                    brands.length > 0 ? brands.map(([brand, info]) => (
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
                        <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: '#FF8C00', fontWeight: 600 }}>{info.count}({fmtNum(info.collected)})</span>
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
                        <span style={{ marginLeft: 'auto', fontSize: '0.74rem', color: '#FF8C00', fontWeight: 600 }}>{fmtNum(g.collected_count ?? 0)}</span>
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
                    // storedUrl은 실제 URL인 경우만 사용 (카테고리 코드는 무시)
                    const validStoredUrl = storedUrl.startsWith('http') ? storedUrl : ''
                    const linkUrl = validStoredUrl || (kwIsUrl ? kw : (SOURCING_SEARCH_URLS[site] ? SOURCING_SEARCH_URLS[site] + encodeURIComponent(kw) : ''))
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {linkUrl ? (
                          <a href={linkUrl} target="_blank" rel="noopener noreferrer" style={{
                            color: '#7EB5D0', fontSize: '0.7rem', wordBreak: 'break-all',
                            textDecoration: 'underline', textUnderlineOffset: '2px', flex: 1,
                          }}>{(() => { try { return decodeURIComponent(linkUrl.replace(/https?:\/\/[^/]+/, '')).slice(0, 40) } catch { return linkUrl.replace(/https?:\/\/[^/]+/, '').slice(0, 40) } })()}...</a>
                        ) : <span style={{ color: '#555', fontSize: '0.75rem', flex: 1 }}>-</span>}
                        <button
                          onClick={async () => {
                            if (!await showConfirm(`"${selectedFilter.name}" 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`)) return
                            try {
                              const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: selectedFilter.id })
                              const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
                              if (registered.length > 0) {
                                showAlert(`마켓등록 상품이 ${fmtNum(registered.length)}건 있어서 삭제할 수 없습니다`, 'error')
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
                      if (!await showConfirm(`${drillBrand} 브랜드의 ${fmtNum(catGroups.length)}개 그룹에 "${policyName}" 정책을 일괄 적용하시겠습니까?`)) { e.target.value = ''; return }
                      let applied = 0
                      for (const g of catGroups) {
                        try {
                          await collectorApi.updateFilter(g.id, { applied_policy_id: policyId } as Partial<SambaSearchFilter>)
                          applied++
                        } catch { /* 무시 */ }
                      }
                      showAlert(`${fmtNum(applied)}/${fmtNum(catGroups.length)}개 그룹에 정책 적용 완료`, 'success')
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
                    }}>{fmtNum(selectedCount)}</span>
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
                      >{mappedCount > 0 ? fmtNum(mappedCount) : '+'}</button>
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
                    {fmtNum(item.value)}건
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
      {/* 카테고리 매핑 모달 */}
      <MappingModal
        open={showMappingModal}
        filter={mappingFilter}
        mappingData={mappingData}
        mappingLoading={mappingLoading}
        setMappingData={setMappingData}
        setMappingLoading={setMappingLoading}
        onClose={() => setShowMappingModal(false)}
        onSaved={() => { load(); loadTree() }}
      />

      {/* AI 태그 미리보기 모달 */}
      <TagPreviewModal
        open={showTagPreview}
        tagPreviews={tagPreviews}
        tagPreviewCost={tagPreviewCost}
        removedTags={removedTags}
        setTagPreviews={setTagPreviews}
        setRemovedTags={setRemovedTags}
        setLastAiUsage={setLastAiUsage}
        setSelectedIds={setSelectedIds}
        setSelectAll={setSelectAll}
        onClose={() => setShowTagPreview(false)}
        onApplied={() => { load(); loadTree() }}
      />

      {/* AI 소싱기 모달 */}
      <AiSourcingModal
        open={showAiSourcingModal}
        aiSourcingStep={aiSourcingStep}
        aiMonth={aiMonth}
        aiMainCategory={aiMainCategory}
        aiExcelFile={aiExcelFile}
        aiTargetCount={aiTargetCount}
        aiAnalyzing={aiAnalyzing}
        aiLogs={aiLogs}
        aiResult={aiResult}
        aiSelectedCombos={aiSelectedCombos}
        aiExcludedBrands={aiExcludedBrands}
        aiExcludedKeywords={aiExcludedKeywords}
        aiMinCount={aiMinCount}
        aiCreating={aiCreating}
        aiSourceSite={aiSourceSite}
        setAiSourcingStep={setAiSourcingStep}
        setAiMonth={setAiMonth}
        setAiMainCategory={setAiMainCategory}
        setAiExcelFile={setAiExcelFile}
        setAiTargetCount={setAiTargetCount}
        setAiAnalyzing={setAiAnalyzing}
        setAiLogs={setAiLogs}
        setAiResult={setAiResult}
        setAiSelectedCombos={setAiSelectedCombos}
        setAiExcludedBrands={setAiExcludedBrands}
        setAiExcludedKeywords={setAiExcludedKeywords}
        setAiMinCount={setAiMinCount}
        setAiCreating={setAiCreating}
        setAiSourceSite={setAiSourceSite}
        onClose={() => setShowAiSourcingModal(false)}
        onCreated={() => { load(); loadTree() }}
      />
    </div>
      {/* 그룹 삭제 진행 모달 */}
      <DeleteJobModal
        open={deleteJobModal}
        logs={deleteJobLogs}
        done={deleteJobDone}
        onClose={() => setDeleteJobModal(false)}
      />
      {/* AI 작업 진행 모달 */}
      <AiJobModal
        open={aiJobModal}
        title={aiJobTitle}
        logs={aiJobLogs}
        done={aiJobDone}
        abortRef={aiJobAbortRef}
        onClose={() => setAiJobModal(false)}
      />
    </div>
  );
}

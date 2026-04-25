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
import { fmtTime } from '@/lib/samba/utils'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'
import AiJobModal from './components/AiJobModal'
import DeleteJobModal from './components/DeleteJobModal'
import MappingModal from './components/MappingModal'
import TagPreviewModal from './components/TagPreviewModal'
import AiSourcingModal from './components/AiSourcingModal'
import SourcingUrlPanel from './components/SourcingUrlPanel'
import DuplicatesModal from './components/DuplicatesModal'
import DrilldownGroupTable from './components/DrilldownGroupTable'
import AiToolsPanel from './components/AiToolsPanel'
import CollectorStatusPanel from './components/CollectorStatusPanel'
import useProxyAuth from './hooks/useProxyAuth'
import useAiTools from './hooks/useAiTools'

const FIXED_REQUESTED_COUNT = 1000

export default function CollectorPage() {
  useEffect(() => { document.title = 'SAMBA-상품수집' }, [])
  const router = useRouter();
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [, setLoading] = useState(true);

  // URL collect
  const [collectUrl, setCollectUrl] = useState("");
  const [collecting, setCollecting] = useState(false);
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
  const [refreshResult] = useState<RefreshResult | null>(null)
  const [showRefreshModal, setShowRefreshModal] = useState(false)
  // AI 도구 관련 상태(태그 미리보기/이미지 변환/작업 진행 모달/AI 비용)는 useAiTools 훅으로 추출
  const {
    lastAiUsage, setLastAiUsage,
    showTagPreview, setShowTagPreview,
    tagPreviews, setTagPreviews,
    tagPreviewCost, setTagPreviewCost,
    tagPreviewLoading, setTagPreviewLoading,
    removedTags, setRemovedTags,
    aiImgScope, setAiImgScope,
    aiImgMode, setAiImgMode,
    aiModelPreset, setAiModelPreset,
    aiImgTransforming, setAiImgTransforming,
    aiPresetList,
    aiJobModal, setAiJobModal,
    aiJobTitle, setAiJobTitle,
    aiJobLogs, setAiJobLogs,
    aiJobDone, setAiJobDone,
    aiJobAbortRef,
  } = useAiTools()

  // 그룹 삭제 진행 모달
  const [deleteJobModal, setDeleteJobModal] = useState(false)
  const [deleteJobLogs, setDeleteJobLogs] = useState<string[]>([])
  const [deleteJobDone, setDeleteJobDone] = useState(false)

  // 이미지 필터링 (모델컷/연출컷/배너 제거)
  const [imgFiltering, setImgFiltering] = useState(false)
  const [imgFilterScopes, setImgFilterScopes] = useState<Set<string>>(new Set(['detail_images']))

  // 중복 상품 모달
  const [showDuplicatesModal, setShowDuplicatesModal] = useState(false)

  // 카테고리 매핑 모달
  const [showMappingModal, setShowMappingModal] = useState(false)
  const [mappingFilter, setMappingFilter] = useState<SambaSearchFilter | null>(null)
  const [mappingData, setMappingData] = useState<Record<string, string>>({})
  const [mappingLoading, setMappingLoading] = useState(false)
  const [, setAccounts] = useState<SambaMarketAccount[]>([])

  // Proxy & auth status
  const {
    proxyStatus,
    proxyText,
    musinsaAuth,
    musinsaAuthText,
    setProxyStatus,
    setProxyText,
  } = useProxyAuth();

  // 트리 + 드릴다운
  const [tree, setTree] = useState<SambaSearchFilter[]>([])
  const [drillSite, setDrillSite] = useState<string | null>(null)
  const [drillBrand, setDrillBrand] = useState<string | null>(null)
  const [drillGroup, setDrillGroup] = useState<string | null>(null)
  const [drillEntry, setDrillEntry] = useState<'site' | 'brand' | null>('site')

  // Group table filters
  const [siteFilter] = useState("");
  const [aiFilter] = useState("");
  const [collectFilter, setCollectFilter] = useState("")
  const [marketRegFilter, setMarketRegFilter] = useState("")
  const [tagRegFilter, setTagRegFilter] = useState("")
  const [policyRegFilter, setPolicyRegFilter] = useState("")
  const [sortBy] = useState("lastCollectedAt_desc");
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
    accountApi.list().then(setAccounts).catch(() => {})
  }, [])
  const addLog = useCallback((msg: string) => {
    const time = fmtTime();
    const line = `[${time}] ${msg}`
    setCollectLog((prev) => [...prev, line].slice(-30));
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 50);
  }, []);

  // 수집 로그 링 버퍼 폴링 (서버 로그 — collecting 또는 brandScanning 시 폴링)
  useEffect(() => {
    if (!collecting && !brandScanning) return
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
  }, [collecting, brandScanning])

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

      let groupName = keyword ? `${site}_${keyword.replace(/\s+/g, '_')}` : `${site}_${new Date().toLocaleDateString("ko-KR")}`

      // NAVERSTORE: 스토어명 + 카테고리명으로 그룹명 구성 (3단 드릴다운 지원)
      // URL → /url-info 호출하여 storeName + categoryName 획득
      // 결과: "NAVERSTORE_coming_스니커즈" → 브랜드=coming, 카테고리=스니커즈
      if (site === 'NAVERSTORE' && isUrl && (input.includes('smartstore.naver.com') || input.includes('brand.naver.com'))) {
        try {
          const infoRes = await fetchWithAuth(
            `${API_BASE}/api/v1/samba/naverstore-sourcing/url-info?store_url=${encodeURIComponent(input)}`
          )
          if (infoRes.ok) {
            const info = await infoRes.json()
            const storeName = (info.storeName || '').trim()
            const categoryName = (info.categoryName || '전체상품').trim()
            if (storeName) {
              groupName = `NAVERSTORE_${storeName}_${categoryName.replace(/\s+/g, '_')}`
            }
          }
        } catch {
          /* url-info 실패 시 기존 groupName 유지 */
        }
      }

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

      const requestedCount = FIXED_REQUESTED_COUNT
      try {
        const countResult = await proxyApi.searchCount(site, keyword, keywordUrl)
        if (countResult.totalCount > 0) {
          void countResult.totalCount
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
      showAlert(`삭제 대상이 없습니다. (selectedIds=${fmtNum(selectedIds.size)}, displayed=${fmtNum(displayedFilters.length)}, drillBrand=${drillBrand || '없음'})`)
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
      ? `${label} ${fmtNum(baseIds.size)}개 + 하위 ${fmtNum(childCount)}개 (총 ${fmtNum(allIds.size)}개) 그룹과 상품을 모두 삭제하시겠습니까?`
      : `${label} ${fmtNum(baseIds.size)}개 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`
    if (!await showConfirm(msg)) return;

    // 진행 모달 열기
    const allIdsArr = [...allIds]
    const nameMap = new Map(filters.map(f => [f.id, f.name]))
    setDeleteJobLogs([`🗑️ 총 ${fmtNum(allIdsArr.length)}개 그룹 삭제 시작...`])
    setDeleteJobDone(false)
    setDeleteJobModal(true)

    let doneCount = 0
    let skipCount = 0
    for (const id of allIdsArr) {
      const groupName = nameMap.get(id) || id
      setDeleteJobLogs(prev => [...prev, `[${fmtNum(doneCount + skipCount + 1)}/${fmtNum(allIdsArr.length)}] "${groupName}" 처리 중...`])
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

    setDeleteJobLogs(prev => [...prev, ``, `🎉 완료 — ${fmtNum(doneCount)}개 삭제${skipCount > 0 ? `, ${fmtNum(skipCount)}개 건너뜀` : ''}`])
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
    const sortedTargetFilters = [...targetFilters].sort((a, b) => {
      const remB = (b.requested_count || 0) - ((b as unknown as Record<string, number>).collected_count || 0)
      const remA = (a.requested_count || 0) - ((a as unknown as Record<string, number>).collected_count || 0)
      if (remB !== remA) return remB - remA
      return (b.requested_count || 0) - (a.requested_count || 0)
    })
    const targetIds = sortedTargetFilters.map(f => f.id)
    if (targetIds.length === 0) {
      addLog("수집할 그룹이 없습니다.")
      return
    }
    const totalReq = targetFilters.reduce((s, f) => s + (f.requested_count || 0), 0)
    const label = selectedIds.size > 0 ? '선택된' : drillGroup ? '선택된' : '표시된'
    // 단일 브랜드이면 brand-collect-all 단일 Job으로 처리 (MUSINSA, ABCmart, SSG, GSShop 지원)
    const _allMusinsa = sortedTargetFilters.every(f => f.source_site === 'MUSINSA')
    const _allABCmart = sortedTargetFilters.every(f => f.source_site === 'ABCmart')
    const _allSSG = sortedTargetFilters.every(f => f.source_site === 'SSG')
    const _allGS = sortedTargetFilters.every(f => f.source_site === 'GSShop')
    const _getBrandKey = (f: SambaSearchFilter) => {
      try {
        const p = new URL(f.keyword || '')
        if (f.source_site === 'MUSINSA') return p.searchParams.get('brand') || ''
        if (f.source_site === 'ABCmart') return p.searchParams.get('searchWord') || ''
        if (f.source_site === 'SSG') return p.searchParams.get('query') || ''
        if (f.source_site === 'GSShop') return p.searchParams.get('tq') || ''
        return ''
      } catch { return '' }
    }
    const _musinsaBrand = _allMusinsa && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
    const _abcBrand = _allABCmart && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
    const _ssgBrand = _allSSG && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
    const _gsBrand = _allGS && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
    const _brandValue = _musinsaBrand || _abcBrand || _ssgBrand || _gsBrand
    const _brandSite = _allMusinsa ? 'MUSINSA' : _allABCmart ? 'ABCmart' : _allSSG ? 'SSG' : _allGS ? 'GSShop' : ''
    // 해당 브랜드의 전체 그룹 수 확인 — 선택된 수와 일치할 때만 브랜드전체수집
    const _totalMusinsaBrandCount = _musinsaBrand ? filters.filter(f => f.source_site === 'MUSINSA' && _getBrandKey(f) === _musinsaBrand).length : 0
    const _totalAbcBrandCount = _abcBrand ? filters.filter(f => f.source_site === 'ABCmart' && _getBrandKey(f) === _abcBrand).length : 0
    const _totalSsgBrandCount = _ssgBrand ? filters.filter(f => f.source_site === 'SSG' && _getBrandKey(f) === _ssgBrand).length : 0
    const _totalGsBrandCount = _gsBrand ? filters.filter(f => f.source_site === 'GSShop' && _getBrandKey(f) === _gsBrand).length : 0
    const _sameBrand = (
      (_musinsaBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalMusinsaBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _musinsaBrand)) ||
      (_abcBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalAbcBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _abcBrand)) ||
      (_ssgBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalSsgBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _ssgBrand)) ||
      (_gsBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalGsBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _gsBrand))
    )

    const ok = await showConfirm(
      _sameBrand
        ? `${label} ${fmtNum(targetIds.length)}개 그룹 브랜드 전체수집을 시작하시겠습니까?`
        : `${label} ${fmtNum(targetIds.length)}개 그룹 상품수집을 시작하시겠습니까?\n(요청 ${fmtNum(totalReq)}건, 중복 상품은 자동 스킵)`
    )
    if (!ok) return
    const abort = new AbortController()
    collectAbortRef.current = abort
    manualCollectRef.current = true
    setCollecting(true)

    if (_sameBrand && _brandSite) {
      // 브랜드 전체수집 — 단일 Job (MUSINSA/ABCmart/SSG/GSShop)
      const _searchKeyword = (() => {
        try {
          const p = new URL(sortedTargetFilters[0].keyword || '')
          if (_brandSite === 'MUSINSA') return p.searchParams.get('keyword') || _brandValue
          if (_brandSite === 'SSG') return p.searchParams.get('query') || _brandValue
          if (_brandSite === 'GSShop') return p.searchParams.get('tq') || _brandValue
          // ABCmart: searchWord
          return p.searchParams.get('searchWord') || _brandValue
        } catch { return _brandValue }
      })()
      addLog(`[브랜드전체수집] '${_searchKeyword}' ${fmtNum(targetIds.length)}개 그룹 단일 Job 시작...`)
      try {
        const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/brand-collect-all`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filter_ids: targetIds,
            source_site: _brandSite,
            keyword: _searchKeyword,
            brand: _musinsaBrand,
            gf: (() => { try { return new URL(sortedTargetFilters[0].keyword || '').searchParams.get('gf') || 'A' } catch { return 'A' } })(),
            exclude_preorder: checkedOptions.excludePreorder ?? true,
            exclude_boutique: checkedOptions.excludeBoutique ?? true,
            use_max_discount: checkedOptions.maxDiscount ?? false,
            include_sold_out: checkedOptions.includeSoldOut ?? false,
          }),
        })
        if (!r.ok) {
          addLog(`[브랜드전체수집] 시작 실패: HTTP ${r.status}`)
        } else {
          const { job_id } = await r.json() as { job_id: string }
          addLog(`[브랜드전체수집] Job 생성 완료 — 백그라운드 실행 중 (페이지 이탈해도 계속 수집됩니다)`)
          let _pendingLoggedAt = 0
          while (!abort.signal.aborted) {
            await new Promise(resolve => setTimeout(resolve, 2000))
            if (abort.signal.aborted) break
            const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
            if (!jr.ok) break
            const jobData = await jr.json() as { status: string; result?: Record<string, number>; error?: string }
            if (jobData.status === 'pending') {
              const now = Date.now()
              if (now - _pendingLoggedAt > 10000) {
                addLog(`[브랜드전체수집] 대기 중 — 다른 브랜드수집 완료 후 자동 시작...`)
                _pendingLoggedAt = now
              }
              continue
            }
            if (jobData.status === 'completed') {
              addLog(`[브랜드전체수집] 완료 — 저장 ${fmtNum(jobData.result?.saved ?? 0)}건`)
              await load(); await loadTree()
              break
            }
            if (jobData.status === 'failed') {
              addLog(`[브랜드전체수집] 실패: ${jobData.error || '오류'}`)
              await load(); await loadTree()
              break
            }
          }
        }
      } catch (e) { addLog(`[브랜드전체수집] 오류: ${(e as Error).message}`) }
    } else {
      // 기타 소싱처 — 기존 순차 Job 루프
      addLog(`${fmtNum(targetIds.length)}개 그룹 상품수집 시작...`)
      for (let gi = 0; gi < targetIds.length; gi++) {
        const id = targetIds[gi]
        if (abort.signal.aborted) break
        const f = filters.find((x) => x.id === id)
        if (!f) continue
        const gp = `[${fmtNum(gi + 1)}/${fmtNum(targetIds.length)}]`
        await new Promise(r => setTimeout(r, 100))
        try {
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
          let lastCurrent = 0
          while (!abort.signal.aborted) {
            await new Promise(r => setTimeout(r, 1000))
            if (abort.signal.aborted) break
            try {
              const jobRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
              if (!jobRes.ok) break
              const job = await jobRes.json() as {
                status: string; current: number; total: number
                progress: number; result?: { saved?: number; skipped?: number; policy?: string; in_stock_count?: number; sold_out_count?: number }
                error?: string
              }
              if (job.current > lastCurrent) { lastCurrent = job.current; load() }
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
                break
              }
              if (job.status === 'failed') { addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '알 수 없는 오류'}`); break }
            } catch { /* 재시도 */ }
          }
        } catch (e) { addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`) }
      }
    }

    manualCollectRef.current = false
    setCollecting(false)
    collectAbortRef.current = null
    await syncRequestedCounts(targetIds)
    load(); loadTree()
  }

  // 요청수 ↔ 수집수 자동 동기화 (수집한 그룹만)
  const syncRequestedCounts = async (_groupIds?: string[]) => {
    // 자동 동기화 제거 — 사용자 설정값 보존
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

  // 중복상품 모달 필터: 드릴다운 기준만 사용 (selectedSite 탭은 무관)
  const _activeSite = drillSite ? tree.find(s => s.id === drillSite)?.source_site : undefined
  const _modalFilterIds = drillBrand ? displayedFilters.map(f => f.id) : undefined

  // 드롭다운 필터 변경 시 drillBrand 활성 상태면 selectedIds를 displayedFilters 기준으로 재동기화

  // 드릴다운 테이블 추가수집 핸들러 (브랜드/카테고리 단위)
  const handleBrandRefresh = async () => {
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
        showAlert('여러 소싱처가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'error')
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
        showAlert('여러 브랜드가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'error')
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
      ? `\n\n대상: 선택 카테고리 ${fmtNum(selectedCategories.length)}개`
      : '\n\n대상: 전체 카테고리'
    const ok = await showConfirm(`${brandName} 추가수집을 실행하시겠습니까?\n\n• 신규 카테고리 → 그룹 자동 생성\n• 기존 카테고리 → 요청수 갱신 후 수집${scopeText}`)
    if (!ok) return
    addLog(`[추가수집] ${brandName} 카테고리 스캔 중...${selectedCategories.length > 0 ? ` (선택 ${fmtNum(selectedCategories.length)}개)` : ''}`)
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
          const abort = new AbortController()
          collectAbortRef.current = abort
          manualCollectRef.current = true
          setCollecting(true)

          // 브랜드 전체수집: 단일 Job으로 수집 후 카테고리 배분 (MUSINSA/ABCmart/SSG/GSShop)
          if (sourceSite === 'MUSINSA' || sourceSite === 'ABCmart' || sourceSite === 'SSG' || sourceSite === 'GSShop') {
            let _searchKeyword = brand
            if (updatedFilters.length > 0) {
              try {
                const _p = new URL(updatedFilters[0].keyword || '')
                if (sourceSite === 'MUSINSA') _searchKeyword = _p.searchParams.get('keyword') || brand
                else if (sourceSite === 'SSG') _searchKeyword = _p.searchParams.get('query') || brand
                else if (sourceSite === 'GSShop') _searchKeyword = _p.searchParams.get('tq') || brand
                else _searchKeyword = _p.searchParams.get('searchWord') || brand
              } catch { /* fallback */ }
            }
            addLog(`[브랜드전체수집] '${_searchKeyword}' ${fmtNum(updatedFilters.length)}개 그룹 단일 Job 시작...`)
            try {
              const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/brand-collect-all`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  filter_ids: updatedFilters.map(f => f.id),
                  source_site: sourceSite,
                  keyword: _searchKeyword,
                  brand: brand,
                  gf: gf,
                  exclude_preorder: checkedOptions.excludePreorder ?? true,
                  exclude_boutique: checkedOptions.excludeBoutique ?? true,
                  use_max_discount: checkedOptions.maxDiscount ?? false,
                  include_sold_out: checkedOptions.includeSoldOut ?? false,
                }),
              })
              if (!r.ok) {
                addLog(`[브랜드전체수집] 시작 실패: HTTP ${r.status}`)
              } else {
                const { job_id } = await r.json()
                addLog(`[브랜드전체수집] Job 생성 완료 — 백그라운드 실행 중 (페이지 이탈해도 계속 수집됩니다)`)
                while (!abort.signal.aborted) {
                  await new Promise(resolve => setTimeout(resolve, 2000))
                  if (abort.signal.aborted) break
                  const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                  if (!jr.ok) break
                  const jobData = await jr.json() as { status: string; current: number; total: number; result?: Record<string, number>; error?: string }
                  if (jobData.status === 'completed') {
                    addLog(`[브랜드전체수집] 완료 — 저장 ${fmtNum(jobData.result?.saved ?? 0)}건`)
                    await load(); await loadTree()
                    break
                  }
                  if (jobData.status === 'failed') {
                    addLog(`[브랜드전체수집] 실패: ${jobData.error || '오류'}`)
                    await load(); await loadTree()
                    break
                  }
                }
              }
            } catch (e) { addLog(`[브랜드전체수집] 오류: ${(e as Error).message}`) }
          } else {
            // 기타 소싱처: 기존 카테고리별 순차 수집
            updatedFilters = [...updatedFilters].sort((a, b) => {
              const remB = (b.requested_count || 0) - ((b as unknown as Record<string, number>).collected_count || 0)
              const remA = (a.requested_count || 0) - ((a as unknown as Record<string, number>).collected_count || 0)
              if (remB !== remA) return remB - remA
              return (b.requested_count || 0) - (a.requested_count || 0)
            })
            addLog(`${fmtNum(updatedFilters.length)}개 그룹 상품수집 시작...`)
            for (let gi = 0; gi < updatedFilters.length; gi++) {
              const f = updatedFilters[gi]
              if (abort.signal.aborted) break
              const gp = `[${fmtNum(gi + 1)}/${fmtNum(updatedFilters.length)}]`
              try {
                const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/collect-filter/${f.id}?group_index=${gi + 1}&group_total=${updatedFilters.length}`, { method: 'POST' })
                if (!r.ok) { addLog(`[${f.name}] 수집 실패: HTTP ${r.status}`); continue }
                const { job_id } = await r.json()
                while (!abort.signal.aborted) {
                  await new Promise(r => setTimeout(r, 1000))
                  if (abort.signal.aborted) break
                  const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                  if (!jr.ok) break
                  const job = await jr.json()
                  if (job.status === 'completed') break
                  if (job.status === 'failed') { addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '오류'}`); break }
                }
              } catch (e) { addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`) }
            }
          }

          manualCollectRef.current = false
          setCollecting(false)
          await syncRequestedCounts(updatedFilters.map(f => f.id))
          load(); loadTree()
        }
      }
    } catch (e) { showAlert(e instanceof Error ? e.message : '수집 실패', 'error') }
  }

  // AI 태그 미리보기 핸들러 (선택/전체 그룹 대표 1개씩 호출)
  const handleAiTagPreview = async () => {
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
  }

  // AI 태그 일괄 삭제 핸들러
  const handleClearAiTags = async () => {
    const checkedIds = selectAll ? displayedFilters.map(f => f.id) : [...selectedIds]
    const targetFilters = displayedFilters.filter(f => checkedIds.includes(f.id))
    if (targetFilters.length === 0) { showAlert('검색그룹을 선택해주세요'); return }
    const ok = await showConfirm(`${fmtNum(targetFilters.length)}개 그룹의 AI 태그를 전체 삭제하시겠습니까?`)
    if (!ok) return
    try {
      const groupIds = targetFilters.map(f => f.id)
      const res = await proxyApi.clearAiTags(groupIds)
      if (res.success) {
        showAlert(res.message, 'success')
        addLog(`[태그삭제] ${fmtNum(targetFilters.length)}개 그룹 AI 태그 삭제 완료`)
      } else showAlert(res.message, 'error')
    } catch (e) {
      showAlert(`태그 삭제 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0', padding: '0.5rem 1rem' }}>
      <CollectorStatusPanel
        section="status"
        proxyStatus={proxyStatus}
        proxyText={proxyText}
        musinsaAuth={musinsaAuth}
        musinsaAuthText={musinsaAuthText}
        setProxyStatus={setProxyStatus}
        setProxyText={setProxyText}
      />

      <SourcingUrlPanel
        selectedSite={selectedSite}
        setSelectedSite={setSelectedSite}
        collectUrl={collectUrl}
        setCollectUrl={setCollectUrl}
        checkedOptions={checkedOptions}
        setCheckedOptions={setCheckedOptions}
        brandScanning={brandScanning}
        setBrandScanning={setBrandScanning}
        brandCategories={brandCategories}
        setBrandCategories={setBrandCategories}
        brandSelectedCats={brandSelectedCats}
        setBrandSelectedCats={setBrandSelectedCats}
        brandTotal={brandTotal}
        setBrandTotal={setBrandTotal}
        detectedBrandCode={detectedBrandCode}
        setDetectedBrandCode={setDetectedBrandCode}
        setShowAiSourcingModal={setShowAiSourcingModal}
        setAiSourcingStep={setAiSourcingStep}
        setAiResult={setAiResult}
        setAiLogs={setAiLogs}
        setAiSelectedCombos={setAiSelectedCombos}
        setAiExcludedBrands={setAiExcludedBrands}
        setAiExcludedKeywords={setAiExcludedKeywords}
        showMusinsaBrandModal={showMusinsaBrandModal}
        setShowMusinsaBrandModal={setShowMusinsaBrandModal}
        brandSearchResults={brandSearchResults}
        setBrandSearchResults={setBrandSearchResults}
        pendingKeyword={pendingKeyword}
        setPendingKeyword={setPendingKeyword}
        selectedBrandCodes={selectedBrandCodes}
        setSelectedBrandCodes={setSelectedBrandCodes}
        setBrandModalAction={setBrandModalAction}
        pendingScanGf={pendingScanGf}
        handleBrandConfirm={handleBrandConfirm}
        showBrandModal={showBrandModal}
        setShowBrandModal={setShowBrandModal}
        brandModalList={brandModalList}
        setBrandModalList={setBrandModalList}
        brandModalSelected={brandModalSelected}
        setBrandModalSelected={setBrandModalSelected}
        brandModalKeyword={brandModalKeyword}
        setBrandModalKeyword={setBrandModalKeyword}
        brandModalParsed={brandModalParsed}
        setBrandModalParsed={setBrandModalParsed}
        collecting={collecting}
        setCollecting={setCollecting}
        handleCreateGroup={handleCreateGroup}
        load={load}
        loadTree={loadTree}
        addLog={addLog}
      />

      <CollectorStatusPanel
        section="log"
        collectLog={collectLog}
        collecting={collecting}
        collectQueueStatus={collectQueueStatus}
        logRef={logRef}
        handleStopCollect={handleStopCollect}
        handleCopyLog={handleCopyLog}
        handleClearLog={handleClearLog}
        parseGroupName={parseGroupName}
      />

      <AiToolsPanel
        lastAiUsage={lastAiUsage}
        aiImgScope={aiImgScope}
        aiImgMode={aiImgMode}
        aiModelPreset={aiModelPreset}
        aiPresetList={aiPresetList}
        aiImgTransforming={aiImgTransforming}
        imgFiltering={imgFiltering}
        imgFilterScopes={imgFilterScopes}
        selectedIds={selectedIds}
        displayedFilters={displayedFilters}
        tree={tree}
        aiJobAbortRef={aiJobAbortRef}
        setAiImgScope={setAiImgScope}
        setAiImgMode={setAiImgMode}
        setAiModelPreset={setAiModelPreset}
        setAiImgTransforming={setAiImgTransforming}
        setImgFiltering={setImgFiltering}
        setImgFilterScopes={setImgFilterScopes}
        setSelectedIds={setSelectedIds}
        setSelectAll={setSelectAll}
        setLastAiUsage={setLastAiUsage}
        setAiJobModal={setAiJobModal}
        setAiJobTitle={setAiJobTitle}
        setAiJobLogs={setAiJobLogs}
        setAiJobDone={setAiJobDone}
        load={load}
        loadTree={loadTree}
      />

      <DrilldownGroupTable
        filters={filters}
        tree={tree}
        policies={policies}
        drillSite={drillSite}
        drillBrand={drillBrand}
        drillGroup={drillGroup}
        drillEntry={drillEntry}
        setDrillSite={setDrillSite}
        setDrillBrand={setDrillBrand}
        setDrillGroup={setDrillGroup}
        setDrillEntry={setDrillEntry}
        collectFilter={collectFilter}
        marketRegFilter={marketRegFilter}
        tagRegFilter={tagRegFilter}
        policyRegFilter={policyRegFilter}
        setCollectFilter={setCollectFilter}
        setMarketRegFilter={setMarketRegFilter}
        setTagRegFilter={setTagRegFilter}
        setPolicyRegFilter={setPolicyRegFilter}
        setSelectedIds={setSelectedIds}
        setShowDuplicatesModal={setShowDuplicatesModal}
        setShowMappingModal={setShowMappingModal}
        setMappingFilter={setMappingFilter}
        setMappingData={setMappingData}
        tagPreviewLoading={tagPreviewLoading}
        handleDeleteSelectedGroups={handleDeleteSelectedGroups}
        handleCollectGroups={handleCollectGroups}
        handlePolicyApply={handlePolicyApply}
        handleUpdateRequestedCount={handleUpdateRequestedCount}
        handleGoToProducts={handleGoToProducts}
        handleBrandRefresh={handleBrandRefresh}
        handleAiTagPreview={handleAiTagPreview}
        handleClearAiTags={handleClearAiTags}
        parseGroupName={parseGroupName}
        load={load}
        loadTree={loadTree}
      />


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
      {/* 중복 상품 모달 */}
      <DuplicatesModal
        open={showDuplicatesModal}
        sourceSite={_activeSite}
        filterIds={_modalFilterIds}
        onClose={() => setShowDuplicatesModal(false)}
        onDeleted={() => { load(); loadTree() }}
      />
    </div>
  );
}

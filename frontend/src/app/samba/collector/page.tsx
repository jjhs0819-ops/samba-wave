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
import { performCollectGroups, performStopCollect } from './utils/collectActions'
import { performBrandRefresh } from './utils/brandRefreshAction'
import { performCreateGroup } from './utils/createGroupAction'
import { performDeleteSelectedGroups } from './utils/groupActions'
import { useDisplayedFilters, parseGroupName } from './hooks/useDisplayedFilters'
import { performAiTagPreview, performClearAiTags } from './utils/aiTagActions'

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

  const executeCreateGroup = (brandCode?: string) => performCreateGroup({
    brandCode, collectUrl, selectedSite, checkedOptions,
    setCollecting, setCollectUrl, addLog, load, loadTree,
  })

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

  const handleDeleteSelectedGroups = () => performDeleteSelectedGroups({
    displayedFilters, selectedIds, drillBrand, filters, siteFilter,
    setDeleteJobLogs, setDeleteJobDone, setDeleteJobModal,
    setSelectedIds, setSelectAll, load, loadTree,
  })

  const handleCollectGroups = async () => {
    await performCollectGroups({
      drillGroup, displayedFilters, selectedIds, filters, checkedOptions,
      collectAbortRef, manualCollectRef, setCollecting, addLog, load, loadTree,
    })
    await syncRequestedCounts()
  }

  const syncRequestedCounts = async () => { /* 자동 동기화 제거 — 사용자 설정값 보존 */ }

  const handleStopCollect = () => performStopCollect({ collectAbortRef, addLog, setCollecting })

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

  const displayedFilters = useDisplayedFilters({
    filters, tree, siteFilter, drillSite, drillBrand,
    aiFilter, collectFilter, marketRegFilter, tagRegFilter, policyRegFilter, sortBy,
  })

  // 중복상품 모달 필터: 드릴다운 기준만 사용 (selectedSite 탭은 무관)
  const _activeSite = drillSite ? tree.find(s => s.id === drillSite)?.source_site : undefined
  const _modalFilterIds = drillBrand ? displayedFilters.map(f => f.id) : undefined

  // 드롭다운 필터 변경 시 drillBrand 활성 상태면 selectedIds를 displayedFilters 기준으로 재동기화

  // 드릴다운 테이블 추가수집 핸들러 (브랜드/카테고리 단위)
  const handleBrandRefresh = () => performBrandRefresh({
    displayedFilters, drillBrand, drillGroup, selectedIds, filters, checkedOptions,
    collectAbortRef, manualCollectRef, setCollecting, addLog, load, loadTree,
  })

  const handleAiTagPreview = () => performAiTagPreview({
    selectAll, selectedIds, displayedFilters,
    setTagPreviewLoading, addLog, setTagPreviews, setTagPreviewCost,
    setRemovedTags, setShowTagPreview,
  })
  const handleClearAiTags = () => performClearAiTags({
    selectAll, selectedIds, displayedFilters, addLog,
  })

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

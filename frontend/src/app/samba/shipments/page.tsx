'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
import { shipmentApi, accountApi, collectorApi, policyApi, categoryApi, type SambaShipment, type SambaMarketAccount, type SambaCollectedProduct, type SambaSearchFilter, type SambaPolicy } from '@/lib/samba/api'
import { MARKET_TYPE_TO_POLICY_KEY as SHARED_POLICY_KEY } from '@/lib/samba/markets'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SITE_COLORS } from '@/lib/samba/constants'
import { inputStyle } from '@/lib/samba/styles'

const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  pending:      { bg: 'rgba(100,100,100,0.15)', text: '#888', label: '대기중' },
  transmitting: { bg: 'rgba(255,211,61,0.15)', text: '#FFD93D', label: '전송중' },
  completed:    { bg: 'rgba(81,207,102,0.15)', text: '#51CF66', label: '완료' },
  partial:      { bg: 'rgba(255,140,0,0.15)', text: '#FF8C00', label: '부분완료' },
  failed:       { bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B', label: '실패' },
}

const SOURCE_SITES = ['전체', 'MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'GrandStage', 'OKmall', 'SSG', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

// 영문 market_type → 한글 정책 키 (markets.ts에서 import)
const MARKET_TYPE_TO_POLICY_KEY = SHARED_POLICY_KEY

export default function ShipmentsPage() {
  const searchParams = useSearchParams()
  const [products, setProducts] = useState<SambaCollectedProduct[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [shipments, setShipments] = useState<SambaShipment[]>([])
  const [filters, setFilters] = useState<SambaSearchFilter[]>([])
  const [policies, setPolicies] = useState<SambaPolicy[]>([])
  const [loading, setLoading] = useState(true)

  // 필터
  const [searchField, setSearchField] = useState('name')
  const [searchText, setSearchText] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [siteFilter, setSiteFilter] = useState('전체')
  const [registrationFilter, setRegistrationFilter] = useState('전체')
  const [sortBy, setSortBy] = useState('updated_at_desc')
  const [totalCount, setTotalCount] = useState(0)

  // 선택
  const [selectedProducts, setSelectedProducts] = useState<string[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
  const [selectedMarkets, setSelectedMarkets] = useState<string[]>([])
  // 마켓 타입 → 해당 마켓의 모든 계정 ID
  const getAccountIdsByMarkets = useCallback((marketTypes: string[]) =>
    accounts.filter(a => marketTypes.includes(a.market_type)).map(a => a.id),
  [accounts])
  const [updateItems, setUpdateItems] = useState({ all: false, price: true, thumb: false, detail: false })
  const [skipEnabled, setSkipEnabled] = useState(false)
  const [loopEnabled, setLoopEnabled] = useState(false)
  const [selectedSites, setSelectedSites] = useState<string[]>([])

  // 전송 로그
  const [logMessages, setLogMessages] = useState<string[]>(['— 전송 시작 버튼을 누르면 로그가 여기에 실시간으로 표시됩니다 —'])
  const [transmitting, setTransmitting] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const progressRef = useRef<NodeJS.Timeout | null>(null)
  const abortRef = useRef(false)
  const activeJobIdRef = useRef('')
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [loopRestart, setLoopRestart] = useState(false)

  // 컴포넌트 언마운트 시 잡 폴링 정리
  useEffect(() => {
    return () => { if (jobPollRef.current) clearInterval(jobPollRef.current) }
  }, [])

  // handleStart 최신 참조를 유지하는 ref (stale closure 방지)
  const handleStartRef = useRef<(targetIds?: string[]) => Promise<void>>(async () => {})

  // 무한반복: 3분 대기 후 미등록 필터 + 전체 선택 + 재시작
  useEffect(() => {
    if (!loopRestart) return
    setLoopRestart(false)
    // 미등록 상품 전체 선택
    const unregistered = products.filter(p => !(p.registered_accounts?.length)).map(p => p.id)
    if (unregistered.length > 0) {
      setSelectedProducts(unregistered)
      setTimeout(() => handleStartRef.current(unregistered), 300)
    } else {
      setTransmitting(false)
    }
  }, [loopRestart, products])

  // 페이지 이탈 시 비상정지 (전송 중일 때만)
  const transmittingRef = useRef(false)
  useEffect(() => { transmittingRef.current = transmitting }, [transmitting])
  useEffect(() => {
    const stopAll = () => {
      if (!transmittingRef.current) return
      import('@/config/api').then(({ API_BASE_URL }) => {
        navigator.sendBeacon(`${API_BASE_URL}/api/v1/samba/shipments/emergency-stop`)
      }).catch(() => {})
    }
    window.addEventListener('beforeunload', stopAll)
    return () => {
      window.removeEventListener('beforeunload', stopAll)
      if (!transmittingRef.current) return
      import('@/config/api').then(({ API_BASE_URL }) => {
        fetch(`${API_BASE_URL}/api/v1/samba/shipments/emergency-stop`, { method: 'POST' }).catch(() => {})
      }).catch(() => {})
    }
  }, [])

  // 카테고리 매핑 데이터
  const [categoryMappings, setCategoryMappings] = useState<{ source_site: string; source_category: string; target_mappings: Record<string, string> }[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    // URL에서 선택된 상품 ID 먼저 확인
    const preIds = new URLSearchParams(window.location.search).get('selected')?.split(',').filter(Boolean) || []

    // 검색 조건에 따라 서버 API 파라미터 구성
    const scrollParams: Record<string, string | number> = { skip: (currentPage - 1) * pageSize, limit: pageSize }
    if (searchText.trim()) {
      scrollParams.search = searchText.trim()
      const typeMap: Record<string, string> = { name: 'name', brand: 'brand', name_all: 'name_all', group: 'filter', no: 'no', policy: 'policy' }
      scrollParams.search_type = typeMap[searchField] || 'name'
    }
    if (siteFilter !== '전체') scrollParams.source_site = siteFilter
    if (registrationFilter !== '전체') scrollParams.status = registrationFilter === '등록' ? 'market_registered' : registrationFilter === '미등록' ? 'market_unregistered' : ''
    if (sortBy) scrollParams.sort_by = sortBy

    // 선택된 상품이 있으면 해당 상품만 조회, 없으면 scroll API
    const productPromise = preIds.length > 0
      ? collectorApi.getProductsByIds(preIds).catch(() => [] as SambaCollectedProduct[])
      : collectorApi.scrollProducts(scrollParams).then(r => { setTotalCount(r.total || 0); return r.items }).catch(() => [] as SambaCollectedProduct[])

    const [p, a, s, f, pol, cm] = await Promise.all([
      productPromise,
      accountApi.listActive().catch(() => []),
      shipmentApi.list(0, 100).catch(() => []),
      collectorApi.listFilters().catch(() => []),
      policyApi.list().catch(() => []),
      categoryApi.listMappings().catch(() => []),
    ])
    setProducts(p)
    setAccounts(a)
    setShipments(s)
    setFilters(f)
    setPolicies(pol)
    setCategoryMappings(Array.isArray(cm) ? cm as typeof categoryMappings : [])
    setLoading(false)
  }, [searchText, searchField, siteFilter, registrationFilter, sortBy, currentPage, pageSize]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])
  useEffect(() => { return () => { if (progressRef.current) clearInterval(progressRef.current) } }, [])

  // URL에서 선택된 상품 ID 자동 적용 + 필터링
  const preSelectedIds = searchParams.get('selected')?.split(',') || []
  const preSelectedSites = searchParams.get('sites')?.split(',') || []
  const autoAll = searchParams.get('autoAll') === '1'
  const priceOnly = searchParams.get('priceOnly') === '1'
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    if (products.length === 0 || policies.length === 0) return
    initializedRef.current = true

    if (preSelectedIds.length > 0) {
      const ids = preSelectedIds.filter(id => products.some(p => p.id === id))
      if (ids.length > 0) setSelectedProducts(ids)
    }
    if (preSelectedSites.length > 0) {
      setSelectedSites(preSelectedSites.filter(s => s))
    }
    if (autoAll && accounts.length > 0) {
      setUpdateItems(priceOnly
        ? { all: false, price: true, thumb: false, detail: false }
        : { all: true, price: true, thumb: true, detail: true }
      )
      // 선택된 상품의 카테고리 매핑에 연결된 마켓만 체크
      const selectedProds = preSelectedIds.map(id => products.find(p => p.id === id)).filter(Boolean)
      const mappedMarketTypes = new Set<string>()
      for (const prod of selectedProds) {
        if (!prod) continue
        const cats = [prod.category1, prod.category2, prod.category3, prod.category4].filter(Boolean)
        const catPath = cats.join(' > ')
        if (!catPath) continue
        const mapping = categoryMappings.find(m =>
          m.source_site === prod.source_site && m.source_category === catPath
        )
        if (mapping?.target_mappings) {
          for (const marketKey of Object.keys(mapping.target_mappings)) {
            if (mapping.target_mappings[marketKey]) {
              mappedMarketTypes.add(marketKey)
            }
          }
        }
      }
      const targetTypes = mappedMarketTypes.size > 0
        ? [...mappedMarketTypes].filter(t => accounts.some(a => a.market_type === t))
        : [...new Set(accounts.map(a => a.market_type))]
      setSelectedMarkets(targetTypes)
      setSelectedAccounts(getAccountIdsByMarkets(targetTypes))
    }
  }, [products, accounts, policies, categoryMappings]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleProduct = (id: string) => setSelectedProducts(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  const toggleAllProducts = () => {
    const pageIds = pageProducts.map(p => p.id)
    const allChecked = pageIds.every(id => selectedProducts.includes(id))
    setSelectedProducts(allChecked ? [] : pageIds)
  }
  const toggleAccount = (id: string) => setSelectedAccounts(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  const allSites = SOURCE_SITES.filter(s => s !== '전체')
  const toggleSite = (site: string) => setSelectedSites(prev => prev.includes(site) ? prev.filter(x => x !== site) : [...prev, site])
  const toggleAllSites = () => setSelectedSites(prev => prev.length === allSites.length ? [] : [...allSites])

  // 필터 이름 맵 (매 렌더마다 재생성 방지)
  const filterNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const f of filters) map[f.id] = f.name
    return map
  }, [filters])

  // 서버에서 필터/정렬/페이지네이션 완료된 상태 — 프론트 필터링 불필요
  const filteredProducts = products

  // 서버 페이지네이션 — products가 이미 현재 페이지분
  const pageProducts = filteredProducts

  // 등록된 마켓 목록 (동적)
  const registeredMarkets = useMemo(() => {
    const marketSet = new Set<string>()
    for (const p of products) {
      for (const aid of (p.registered_accounts || [])) {
        const acc = accounts.find(a => a.id === aid)
        if (acc) marketSet.add(acc.market_type)
      }
    }
    const marketNameMap: Record<string, string> = {}
    for (const acc of accounts) {
      if (!marketNameMap[acc.market_type]) marketNameMap[acc.market_type] = acc.market_name
    }
    return [...marketSet].map(type => ({ type, name: marketNameMap[type] || type }))
  }, [products, accounts])

  const handleMarketDelete = async () => {
    if (selectedAccounts.length === 0) { showAlert('마켓 계정을 선택해주세요'); return }
    // 비상정지 해제 (이전 중단 상태 초기화)
    try {
      const { API_BASE_URL: apiBase } = await import('@/config/api')
      await fetch(`${apiBase}/api/v1/samba/shipments/emergency-clear`, { method: 'POST' })
    } catch { /* ignore */ }
    // 등록된 마켓이 있는 상품만 필터
    const targetProducts = selectedProducts.filter(pid => {
      const p = products.find(x => x.id === pid)
      return p && (p.registered_accounts || []).some(aid => selectedAccounts.includes(aid))
    })
    if (targetProducts.length === 0) { showAlert('선택된 소싱사이트/마켓에 해당하는 등록 상품이 없습니다'); return }

    const targetLabels = selectedAccounts.map(aid => {
      const acc = accounts.find(a => a.id === aid)
      return acc ? `${acc.market_name}(${acc.seller_id || '-'})` : aid
    }).join(', ')
    if (!await showConfirm(`${targetProducts.length}개 상품을 ${targetLabels}에서 마켓삭제하시겠습니까?`)) return

    setTransmitting(true)
    const ts = () => new Date().toLocaleTimeString()
    // 로그를 ref 배열로 관리 — spread O(n²) 방지
    const addLog = (msg: string) => setLogMessages(prev => [...prev, msg])
    const accLabelMap: Record<string, string> = {}
    for (const acc of accounts) {
      accLabelMap[acc.id] = `${acc.market_name}(${acc.seller_id || acc.business_name || '-'})`
    }
    const targetAccLabels = selectedAccounts.map(aid => accLabelMap[aid] || aid).join(', ')
    addLog(`[${ts()}] 마켓삭제 시작 — 상품 ${targetProducts.length}개, ${targetAccLabels}`)

    let totalSuccess = 0
    let totalFail = 0
    for (let i = 0; i < targetProducts.length; i++) {
      const pid = targetProducts[i]
      const prod = products.find(p => p.id === pid)
      const prodName = prod?.name?.slice(0, 30) || pid
      try {
        const res = await shipmentApi.marketDelete([pid], selectedAccounts)
        const r = res.results?.[0]
        if (r) {
          for (const [aid, st] of Object.entries(r.delete_results)) {
            const accLabel = accLabelMap[aid] || aid
            if (st === 'success') {
              addLog(`[${ts()}] [${i + 1}/${targetProducts.length}] ${prodName} → ${accLabel}: 삭제 성공`)
              totalSuccess++
            } else {
              addLog(`[${ts()}] [${i + 1}/${targetProducts.length}] ${prodName} → ${accLabel}: ${st}`)
              totalFail++
            }
          }
        }
      } catch (e) {
        addLog(`[${ts()}] [${i + 1}/${targetProducts.length}] ${prodName}: 오류 — ${e instanceof Error ? e.message : ''}`)
        totalFail++
      }
    }
    addLog(`[${ts()}] 마켓삭제 완료 — 성공 ${totalSuccess}건, 실패 ${totalFail}건`)
    await load()
    setTransmitting(false)
  }

  const handleStart = async (targetIds?: string[]) => {
    const inputIds = targetIds || selectedProducts
    if (inputIds.length === 0) { showAlert('상품을 선택해주세요'); return }
    if (selectedAccounts.length === 0) { showAlert('마켓 계정을 선택해주세요'); return }
    if (selectedSites.length === 0) { showAlert('소싱사이트를 선택해주세요'); return }

    // 비상정지 해제 (이전 중단 상태 초기화)
    try {
      const { API_BASE_URL: apiBase } = await import('@/config/api')
      await fetch(`${apiBase}/api/v1/samba/shipments/emergency-clear`, { method: 'POST' })
    } catch { /* ignore */ }

    // 소싱사이트 체크 + 현재 필터에 표시된 상품만 전송
    const siteSet = new Set(selectedSites)
    const filteredSet = new Set(filteredProducts.map(p => p.id))
    const visibleSelected = (targetIds || inputIds).filter(id => {
      if (!targetIds && !filteredSet.has(id)) return false
      const prod = products.find(p => p.id === id)
      return prod ? siteSet.has(prod.source_site) : false
    })
    if (visibleSelected.length === 0) { showAlert('선택된 소싱사이트에 해당하는 상품이 없습니다'); return }

    setTransmitting(true)

    const ts = () => new Date().toLocaleTimeString()
    const addLog = (msg: string) => setLogMessages(prev => [...prev, msg])

    // 계정 ID → 표시명 매핑
    const accountLabelMap: Record<string, string> = {}
    for (const acc of accounts) {
      accountLabelMap[acc.id] = `${acc.market_name}(${acc.seller_id || acc.account_label || acc.business_name || '-'})`
    }

    // 정책 적용된 상품만 전송 대상 (미적용 상품은 사전 제외)
    const policyProducts = visibleSelected.filter(pid => {
      const prod = products.find(p => p.id === pid)
      return !!prod?.applied_policy_id
    })
    const noPolicyCount = visibleSelected.length - policyProducts.length
    const total = policyProducts.length

    if (total === 0) {
      addLog(`[${ts()}] 전송 대상 없음 — 선택된 ${visibleSelected.length}개 상품 중 정책 적용된 상품이 없습니다`)
      setTransmitting(false)
      return
    }

    if (noPolicyCount > 0) {
      addLog(`[${ts()}] 정책 미적용 ${noPolicyCount}개 제외 (선택 ${visibleSelected.length}개 → 전송 대상 ${total}개)`)
    }

    setProgress({ current: 0, total })

    // 정책 연결 계정 ∩ UI 선택 마켓 = 실제 전송 대상
    const selectedSet = new Set(selectedAccounts)
    const effectiveAccountSet = new Set<string>()
    for (const pid of policyProducts) {
      const prod = products.find(p => p.id === pid)
      const policy = policies.find(p => p.id === prod?.applied_policy_id)
      if (!policy?.market_policies || typeof policy.market_policies !== 'object') continue
      const mp = policy.market_policies as Record<string, { accountId?: string; accountIds?: string[] }>
      for (const marketPolicy of Object.values(mp)) {
        const ids = marketPolicy.accountIds?.length
          ? marketPolicy.accountIds
          : (marketPolicy.accountId ? [marketPolicy.accountId] : [])
        ids.forEach((id: string) => { if (selectedSet.has(id)) effectiveAccountSet.add(id) })
      }
    }
    const effectiveLabels = [...effectiveAccountSet].map(aid => accountLabelMap[aid] || aid)
    abortRef.current = false
    addLog(`[${ts()}] 전송 시작 — 상품 ${total}개, ${effectiveLabels.length > 0 ? effectiveLabels.join(', ') : '연결 계정 없음'}`)

    const items: string[] = []
    if (updateItems.price) items.push('price', 'stock')
    if (updateItems.thumb) items.push('image')
    if (updateItems.detail) items.push('description')

    // 전송 태스크 사전 준비
    type TransmitTask = { idx: number, pid: string, prodLabel: string, targetAccIds: string[] }
    const tasks: TransmitTask[] = []
    let skipCount = 0
    for (let i = 0; i < policyProducts.length; i++) {
      const pid = policyProducts[i]
      const prod = products.find(p => p.id === pid)
      const prodName = prod?.name || pid
      const policy = policies.find(p => p.id === prod?.applied_policy_id)
      const targetAccIds: string[] = []
      if (policy?.market_policies && typeof policy.market_policies === 'object') {
        const mp = policy.market_policies as Record<string, { accountId?: string; accountIds?: string[] }>
        for (const marketPolicy of Object.values(mp)) {
          const ids = marketPolicy.accountIds?.length
            ? marketPolicy.accountIds
            : (marketPolicy.accountId ? [marketPolicy.accountId] : [])
          ids.forEach((id: string) => { if (selectedSet.has(id) && !targetAccIds.includes(id)) targetAccIds.push(id) })
        }
      }
      if (targetAccIds.length === 0) { skipCount++; continue }
      const siteProductId = prod?.site_product_id || ''
      const prodLabel = siteProductId ? `${prodName} (${siteProductId})` : prodName
      tasks.push({ idx: i + 1, pid, prodLabel, targetAccIds })
    }

    if (skipCount > 0) {
      addLog(`[${ts()}] 선택 마켓 미연결 ${skipCount}개 스킵 → 실제 전송 ${tasks.length}개`)
    }
    setProgress({ current: 0, total: tasks.length })

    // Job 큐로 백그라운드 전송 (건수 무관)
    try {
      const allPids = tasks.map(t => t.pid)
      const allAccIds = [...effectiveAccountSet]
      const { API_BASE_URL: apiBase } = await import('@/config/api')
      const res = await fetch(`${apiBase}/api/v1/samba/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_type: 'transmit',
          payload: {
            product_ids: allPids,
            update_items: items,
            target_account_ids: allAccIds,
            skip_unchanged: skipEnabled,
          },
        }),
      })
      const jobData = await res.json()
      const jobId = jobData.id || ''
      activeJobIdRef.current = jobId
      setProgress({ current: 0, total: tasks.length })
      // 전송 진행 폴링 + 실시간 로그 (동시 요청 방지)
      let logSince = 0
      let polling = false
      if (jobPollRef.current) clearInterval(jobPollRef.current)
      jobPollRef.current = setInterval(async () => {
        if (polling) return
        polling = true
        try {
          const [jr, lr] = await Promise.all([
            fetch(`${apiBase}/api/v1/samba/jobs/${jobId}`),
            fetch(`${apiBase}/api/v1/samba/jobs/${jobId}/logs?since=${logSince}`),
          ])
          const j = await jr.json()
          const logData = await lr.json()
          const cur = j.progress_current || 0
          const tot = j.progress_total || tasks.length
          setProgress({ current: cur, total: tot })
          const newLogs = logData.logs || []
          if (newLogs.length > 0) {
            for (const log of newLogs) {
              setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${log}`])
            }
            logSince += newLogs.length
          }
          if (j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled') {
            if (jobPollRef.current) { clearInterval(jobPollRef.current); jobPollRef.current = null }
            if (j.error) addLog(`[${new Date().toLocaleTimeString()}] ${j.error}`)
            setTransmitting(false)
            activeJobIdRef.current = ''
            load()
          }
        } catch { /* ignore */ }
        polling = false
      }, 500)
    } catch (e) {
      addLog(`[${ts()}] 전송 실패: ${e instanceof Error ? e.message : '오류'}`)
      setTransmitting(false)
    }
  }

  // handleStart가 항상 최신 클로저를 참조하도록 ref 갱신
  handleStartRef.current = handleStart

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 이전 단계 연결 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <a href="/samba/policies" style={{ fontSize: '0.75rem', color: '#888', textDecoration: 'none' }}>← 정책관리</a>
        <a href="/samba/categories" style={{ fontSize: '0.75rem', color: '#888', textDecoration: 'none' }}>← 카테고리매핑</a>
        <a href="/samba/products" style={{ fontSize: '0.75rem', color: '#888', textDecoration: 'none' }}>← 상품관리</a>
      </div>

      {/* 전송 설정 패널 */}
      <div style={{ background: 'rgba(14,14,20,0.98)', border: '1px solid #1E2030', borderRadius: '8px', marginBottom: '10px', fontSize: '0.8rem' }}>
        {/* 검색항목 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #181C28', gap: '8px' }}>
          <span style={{ minWidth: '72px', color: '#666', fontSize: '0.78rem' }}>검색항목</span>
          <select value={searchField} onChange={e => setSearchField(e.target.value)} style={{ ...inputStyle, width: '100px' }}>
            <option value="name">검색항목</option>
            <option value="brand">브랜드</option>
            <option value="name_all">상품명+등록명</option>
            <option value="group">그룹</option>
            <option value="no">상품번호</option>
            <option value="policy">정책</option>
          </select>
          <input type="text" value={searchText} onChange={e => setSearchText(e.target.value)} placeholder={searchField === 'name' ? '상품명 검색' : searchField === 'no' ? '상품번호 검색' : '그룹명 검색'} style={{ ...inputStyle, width: '200px' }} />
        </div>
        {/* 소싱사이트 필터 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #181C28', gap: '8px' }}>
          <span style={{ minWidth: '72px', color: '#666', fontSize: '0.78rem' }}>소싱사이트</span>
          <select value={siteFilter} onChange={e => setSiteFilter(e.target.value)} style={{ ...inputStyle, width: '140px' }}>
            {SOURCE_SITES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        {/* 마켓등록 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #181C28', gap: '8px' }}>
          <span style={{ minWidth: '72px', color: '#666', fontSize: '0.78rem' }}>마켓등록</span>
          <select value={registrationFilter} onChange={e => setRegistrationFilter(e.target.value)} style={{ ...inputStyle, width: '100px' }}>
            <option>전체</option><option>등록</option><option>미등록</option>
          </select>
        </div>
        {/* 실패건처리 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', gap: '8px', flexWrap: 'wrap', borderBottom: '1px solid #181C28' }}>
          <span style={{ minWidth: '72px', color: '#666', fontSize: '0.78rem' }}>실패건처리</span>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.78rem', color: '#8A95B0', cursor: 'pointer' }}>
            <input type="checkbox" style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} /> 재고연동 실패 건
          </label>
          <button style={{ padding: '4px 14px', fontSize: '0.78rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}>실패건 마켓상품삭제</button>
        </div>

        {/* 검색하기 버튼 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '2px solid #181C28', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button onClick={load} style={{ padding: '6px 40px', fontSize: '0.875rem', fontWeight: 700, background: '#2A2F3E', border: '1px solid #3D4560', color: '#E5E5E5', borderRadius: '6px', cursor: 'pointer' }}>검색하기</button>
            <button onClick={() => { setSearchText(''); setSiteFilter('전체'); setRegistrationFilter('전체'); setSearchField('name') }} style={{ padding: '6px 24px', fontSize: '0.875rem', background: 'transparent', border: '1px solid #2A3040', color: '#9AA5C0', borderRadius: '6px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>

        {/* 소싱사이트 체크박스 */}
        <div style={{ padding: '10px 16px 12px', borderBottom: '1px solid #181C28' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#C5C5C5', marginBottom: '10px', paddingBottom: '6px', borderBottom: '1px solid #1C1E2A' }}>소싱사이트</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 24px' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.8rem', color: '#C5C5C5', cursor: 'pointer', fontWeight: 600 }}>
              <input type="checkbox" checked={selectedSites.length === allSites.length} onChange={toggleAllSites} style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
              전체
            </label>
            {allSites.map(site => (
              <label key={site} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.8rem', color: '#8A95B0', cursor: 'pointer' }}>
                <input type="checkbox" checked={selectedSites.includes(site)} onChange={() => toggleSite(site)} style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
                {site}
              </label>
            ))}
          </div>
        </div>

        {/* 업데이트 항목 */}
        <div style={{ padding: '10px 16px 12px', borderBottom: '1px solid #181C28' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#C5C5C5', marginBottom: '10px', paddingBottom: '6px', borderBottom: '1px solid #1C1E2A' }}>업데이트 항목</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 20px' }}>
            {[
              { key: 'all', label: '전체' }, { key: 'price', label: '가격/재고' },
              { key: 'thumb', label: '썸네일' }, { key: 'detail', label: '상세페이지' },
            ].map(item => (
              <label key={item.key} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: '#8A95B0', cursor: 'pointer' }}>
                <input type="checkbox" checked={updateItems[item.key as keyof typeof updateItems]}
                  onChange={() => {
                    if (item.key === 'all') {
                      setUpdateItems({ all: !updateItems.all, price: !updateItems.all, thumb: !updateItems.all, detail: !updateItems.all })
                    } else {
                      setUpdateItems(prev => {
                        const next = { ...prev, [item.key]: !prev[item.key as keyof typeof prev] }
                        // 개별 항목 변경 시 전체 체크 자동 동기화
                        next.all = next.price && next.thumb && next.detail
                        return next
                      })
                    }
                  }}
                  style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
                {item.label}
              </label>
            ))}
          </div>
        </div>

        {/* 스킵 설정 */}
        <div style={{ padding: '10px 16px 12px', borderBottom: '1px solid #181C28' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#C5C5C5', marginBottom: '10px', paddingBottom: '6px', borderBottom: '1px solid #1C1E2A' }}>스킵 설정</div>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.8rem', color: '#8A95B0', cursor: 'pointer' }}>
            <input type="checkbox" checked={skipEnabled} onChange={() => setSkipEnabled(!skipEnabled)} style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
            업데이트 스킵
          </label>
          <span style={{ fontSize: '0.72rem', color: '#555', marginLeft: '4px' }}>마켓 전송 가격에 영향을 미치는 요인(원가, 수수료, 배송비, 추가요금, 마진율)에 변동이 없으면 전송하지 않고 건너뜀</span>
        </div>

        {/* 마켓 체크박스 (마켓별 통합 — 선택 시 해당 마켓의 모든 계정에 전송) */}
        <div style={{ padding: '10px 16px 12px' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#C5C5C5', marginBottom: '8px', paddingBottom: '6px', borderBottom: '1px solid #1C1E2A' }}>마켓</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 20px' }}>
            {accounts.length === 0 ? (
              <span style={{ color: '#555', fontSize: '0.8rem' }}>설정 탭에서 마켓을 등록해주세요</span>
            ) : (
              <>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.8rem', color: '#FF8C00', cursor: 'pointer', fontWeight: 600 }}>
                  <input type="checkbox"
                    checked={(() => {
                      const allTypes = [...new Set(accounts.map(a => a.market_type))]
                      return allTypes.length > 0 && allTypes.every(t => selectedMarkets.includes(t))
                    })()}
                    onChange={() => {
                      const allTypes = [...new Set(accounts.map(a => a.market_type))]
                      const allSelected = allTypes.every(t => selectedMarkets.includes(t))
                      if (allSelected) {
                        setSelectedMarkets([])
                        setSelectedAccounts([])
                      } else {
                        setSelectedMarkets(allTypes)
                        setSelectedAccounts(getAccountIdsByMarkets(allTypes))
                      }
                    }}
                    style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
                  전체
                </label>
                {[...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()].map(([type, name]) => (
                  <label key={type} style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', fontSize: '0.8rem', color: '#8A95B0', cursor: 'pointer' }}>
                    <input type="checkbox" checked={selectedMarkets.includes(type)}
                      onChange={() => {
                        const next = selectedMarkets.includes(type) ? selectedMarkets.filter(m => m !== type) : [...selectedMarkets, type]
                        setSelectedMarkets(next)
                        setSelectedAccounts(getAccountIdsByMarkets(next))
                      }}
                      style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }} />
                    {name}
                  </label>
                ))}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 전송 로그 */}
      <div style={{ background: 'rgba(8,10,16,0.98)', border: '1px solid #1C1E2A', borderRadius: '8px', marginBottom: '12px', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', background: '#0A0D14', borderBottom: '1px solid #1C1E2A' }}>
          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#9AA5C0' }}>전송 로그</span>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ padding: '3px 10px', fontSize: '0.72rem', background: 'transparent', border: '1px solid #252B3B', color: '#666', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['로그가 초기화되었습니다.'])} style={{ padding: '3px 10px', fontSize: '0.72rem', background: 'transparent', border: '1px solid #252B3B', color: '#666', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
            <button onClick={handleMarketDelete} disabled={transmitting}
              style={{ padding: '4px 14px', fontSize: '0.78rem', background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.35)', color: '#FF6B6B', borderRadius: '4px', cursor: transmitting ? 'not-allowed' : 'pointer', fontWeight: 600 }}>마켓삭제</button>
            {transmitting ? (
              <button onClick={async () => {
                abortRef.current = true
                try {
                  const { API_BASE_URL: apiBase } = await import('@/config/api')
                  await fetch(`${apiBase}/api/v1/samba/shipments/emergency-stop`, { method: 'POST' })
                  activeJobIdRef.current = ''
                } catch { /* ignore */ }
                setTransmitting(false)
              }}
                style={{ padding: '4px 16px', fontSize: '0.78rem', background: 'rgba(255,50,50,0.3)', color: '#FF4444', border: '1px solid rgba(255,50,50,0.6)', borderRadius: '4px', cursor: 'pointer', fontWeight: 700 }}
              >전송 중단</button>
            ) : (<>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: loopEnabled ? '#FF8C00' : '#666', cursor: 'pointer' }}>
                <input type="checkbox" checked={loopEnabled} onChange={() => setLoopEnabled(!loopEnabled)} style={{ accentColor: '#FF8C00', width: '13px', height: '13px' }} />
                무한반복
              </label>
              <button onClick={() => handleStart()}
                style={{ padding: '4px 14px', fontSize: '0.78rem', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', border: '1px solid rgba(255,140,0,0.4)', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}
              >선택전송</button>
              <button onClick={() => handleStart(filteredProducts.map(p => p.id))}
                style={{ padding: '4px 14px', fontSize: '0.78rem', background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}
              >검색결과전송 ({totalCount})</button>
            </>)}
          </div>
        </div>
        <div
          ref={el => { if (el) el.scrollTop = el.scrollHeight }}
          style={{ height: '250px', overflowY: 'auto', padding: '10px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.73rem', lineHeight: 1.8, color: '#4A5568' }}
        >
          {logMessages.map((msg, i) => {
            let color = '#DCE0E8'
            if (msg.includes('전송 완료') || msg.includes('전송 시작') || msg.includes('마켓삭제')) color = '#8A95B0'
            else if (msg.includes('실패') || msg.includes('오류')) color = '#C4736E'
            else if (msg.includes('스킵')) color = '#888'
            else if (msg.includes('성공')) color = '#7BAF7E'
            return <div key={i} style={{ color }}>{msg}</div>
          })}
        </div>
        {/* 프로그레스바 */}
        {transmitting && progress.total > 0 && progress.current > 0 && (
          <div style={{ padding: '6px 14px 8px', borderTop: '1px solid #1C1E2A' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontSize: '0.75rem', color: '#7B8DB0' }}>{progress.current}/{progress.total} 처리 중...</span>
            </div>
            <div style={{ background: '#111520', borderRadius: '4px', height: '5px', overflow: 'hidden' }}>
              <div style={{ background: 'linear-gradient(90deg,#FF8C00,#FFB84D)', height: '100%', width: `${(progress.current / progress.total) * 100}%`, transition: 'width 0.3s' }} />
            </div>
          </div>
        )}
      </div>

      {/* 상품 목록 테이블 */}
      <div style={{ background: 'rgba(30,30,30,0.5)', border: '1px solid #2D2D2D', borderRadius: '12px', overflow: 'hidden' }}>
        {/* 상단 탭 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid #2D2D2D', gap: '8px' }}>
          <span style={{ fontSize: '0.8rem', color: '#888' }}>총 <span style={{ color: '#FF8C00', fontWeight: 600 }}>{totalCount.toLocaleString()}</span> 개의 상품이 검색되었습니다.</span>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...inputStyle, width: '250px', marginLeft: 'auto' }}>
            <option value="updated_at_desc">상품업데이트 날짜순 ▼</option>
            <option value="updated_at_asc">상품업데이트 날짜순 ▲</option>
            <option value="collected_at_desc">상품수집 날짜순 ▼</option>
            <option value="collected_at_asc">상품수집 날짜순 ▲</option>
            {registeredMarkets.flatMap(m => [
              <option key={`${m.type}_asc`} value={`market_${m.type}_asc`}>{m.name} ▲</option>,
              <option key={`${m.type}_desc`} value={`market_${m.type}_desc`}>{m.name} ▼</option>,
            ])}
          </select>
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(1) }} style={{ ...inputStyle, width: '80px' }}>
            <option value={20}>20개</option>
            <option value={50}>50개</option>
            <option value={100}>100개</option>
            <option value={200}>200개</option>
            <option value={99999}>전체</option>
          </select>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
          <thead>
            <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #2D2D2D' }}>
              <th style={{ width: '36px', padding: '0.625rem' }}><input type="checkbox" checked={pageProducts.length > 0 && pageProducts.every(p => selectedProducts.includes(p.id))} onChange={toggleAllProducts} style={{ accentColor: '#F59E0B' }} /></th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#888', width: '40px' }}>No</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>상품번호</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>사이트</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>상품명</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#888' }}>상품업데이트</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#888' }}>마켓 전송</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</td></tr>
            ) : totalCount === 0 ? (
              <tr><td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>상품이 없습니다</td></tr>
            ) : filteredProducts.map((p, idx) => {
              const regAccounts = p.registered_accounts || []
              const regMarkets = regAccounts.map(aid => accounts.find(a => a.id === aid)?.market_name).filter(Boolean)
              const optCount = (p.options || []).length
              return (
                <tr key={p.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)', verticalAlign: 'top' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ padding: '0.625rem 0.5rem', textAlign: 'center' }}>
                    <input type="checkbox" checked={selectedProducts.includes(p.id)} onChange={() => toggleProduct(p.id)} style={{ accentColor: '#F59E0B' }} />
                  </td>
                  <td style={{ padding: '0.625rem 0.5rem', textAlign: 'center', color: '#666', fontSize: '0.72rem' }}>{(currentPage - 1) * pageSize + idx + 1}</td>
                  <td style={{ padding: '0.625rem 0.5rem', color: '#666', fontSize: '0.72rem' }}>{p.site_product_id || '-'}</td>
                  <td style={{ padding: '0.625rem 0.5rem' }}>
                    <span style={{ display: 'inline-block', padding: '1px 8px', borderRadius: '4px', fontSize: '0.68rem', fontWeight: 600, color: SITE_COLORS[p.source_site] || '#888', background: `${SITE_COLORS[p.source_site] || '#888'}18`, border: `1px solid ${SITE_COLORS[p.source_site] || '#888'}40` }}>{p.source_site}</span>
                  </td>
                  <td style={{ padding: '0.625rem 0.5rem' }}>
                    <div>
                      <a href={`/samba/products?highlight=${p.id}`} style={{ color: '#DCE0E8', textDecoration: 'none', fontSize: '0.8rem', cursor: 'pointer' }}
                        onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
                        onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
                      >
                        [{p.site_product_id || ''}] {p.name} {optCount > 0 ? <span style={{ color: '#DCE0E8' }}>[옵션수:{optCount}]</span> : ''}
                      </a>
                    </div>
                    {regMarkets.length > 0 && (
                      <div style={{ fontSize: '0.72rem', color: '#888', marginTop: '2px' }}>
                        (등록된 마켓 : {regMarkets.map((m, i) => (
                          <span key={i}><span style={{ color: '#FF8C00' }}>{m}</span>{i < regMarkets.length - 1 ? ' / ' : ''}</span>
                        ))})
                      </div>
                    )}
                  </td>
                  <td style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#666' }}>
                    {p.updated_at ? (() => {
                      const d = new Date(p.updated_at)
                      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                    })() : '-'}
                  </td>
                  <td style={{ padding: '0.625rem 0.5rem', fontSize: '0.72rem', color: '#666' }}>
                    {(() => {
                      const regAccs = (p.registered_accounts || [])
                      if (regAccs.length === 0) return <span style={{ color: '#555', textAlign: 'center', display: 'block' }}>-</span>
                      const sent = p.last_sent_data || {}
                      return regAccs.map(aid => {
                        const acc = accounts.find(a => a.id === aid)
                        if (!acc) return null
                        const sentAt = sent[aid]?.sent_at
                        const timeLabel = sentAt ? (() => {
                          const d = new Date(sentAt)
                          return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                        })() : ''
                        return (
                          <div key={aid} style={{ fontSize: '0.68rem' }}>
                            <span style={{ color: '#51CF66' }}>{acc.market_name}({acc.seller_id || acc.account_label || '-'})</span>
                            {timeLabel && <span style={{ color: '#555' }}> {timeLabel}</span>}
                          </div>
                        )
                      })
                    })()}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* 페이지네이션 */}
        {totalCount > pageSize && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px', padding: '12px 0' }}>
            <button
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              style={{ padding: '4px 10px', fontSize: '0.78rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: currentPage <= 1 ? '#444' : '#C5C5C5', cursor: currentPage <= 1 ? 'default' : 'pointer' }}
            >◀</button>
            {Array.from({ length: Math.ceil(totalCount / pageSize) }, (_, i) => i + 1)
              .filter(page => Math.abs(page - currentPage) <= 2 || page === 1 || page === Math.ceil(totalCount / pageSize))
              .map((page, i, arr) => (
                <span key={page}>
                  {i > 0 && arr[i - 1] !== page - 1 && <span style={{ color: '#555' }}>…</span>}
                  <button
                    onClick={() => setCurrentPage(page)}
                    style={{
                      padding: '4px 10px', fontSize: '0.78rem', borderRadius: '4px', cursor: 'pointer',
                      background: page === currentPage ? 'rgba(255,140,0,0.2)' : 'transparent',
                      border: page === currentPage ? '1px solid #FF8C00' : '1px solid #2D2D2D',
                      color: page === currentPage ? '#FF8C00' : '#C5C5C5',
                      fontWeight: page === currentPage ? 600 : 400,
                    }}
                  >{page}</button>
                </span>
              ))}
            <button
              disabled={currentPage >= Math.ceil(totalCount / pageSize)}
              onClick={() => setCurrentPage(p => p + 1)}
              style={{ padding: '4px 10px', fontSize: '0.78rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: currentPage >= Math.ceil(totalCount / pageSize) ? '#444' : '#C5C5C5', cursor: currentPage >= Math.ceil(totalCount / pageSize) ? 'default' : 'pointer' }}
            >▶</button>
            <span style={{ fontSize: '0.72rem', color: '#666', marginLeft: '8px' }}>
              {totalCount}개 중 {(currentPage - 1) * pageSize + 1}~{Math.min(currentPage * pageSize, totalCount)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

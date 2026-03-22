'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
import { shipmentApi, accountApi, collectorApi, policyApi, type SambaShipment, type SambaMarketAccount, type SambaCollectedProduct, type SambaSearchFilter, type SambaPolicy } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'

const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  pending:      { bg: 'rgba(100,100,100,0.15)', text: '#888', label: '대기중' },
  transmitting: { bg: 'rgba(255,211,61,0.15)', text: '#FFD93D', label: '전송중' },
  completed:    { bg: 'rgba(81,207,102,0.15)', text: '#51CF66', label: '완료' },
  partial:      { bg: 'rgba(255,140,0,0.15)', text: '#FF8C00', label: '부분완료' },
  failed:       { bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B', label: '실패' },
}

const SOURCE_SITES = ['전체', 'MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'GrandStage', 'OKmall', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

// 영문 market_type → 한글 정책 키 역매핑
const MARKET_TYPE_TO_POLICY_KEY: Record<string, string> = {
  'coupang': '쿠팡', 'ssg': '신세계몰', 'smartstore': '스마트스토어',
  '11st': '11번가', 'gmarket': '지마켓', 'auction': '옥션',
  'gsshop': 'GS샵', 'lotteon': '롯데ON', 'lottehome': '롯데홈쇼핑',
  'homeand': '홈앤쇼핑', 'hmall': 'HMALL', 'kream': 'KREAM',
  'ebay': 'eBay', 'lazada': 'Lazada', 'qoo10': 'Qoo10',
  'shopee': 'Shopee', 'shopify': 'Shopify', 'zoom': 'Zum(줌)',
}

const inputStyle = {
  padding: '4px 8px',
  fontSize: '0.78rem',
  background: '#111520',
  border: '1px solid #2A3040',
  color: '#C5C5C5',
  borderRadius: '4px',
  outline: 'none',
  boxSizing: 'border-box' as const,
}

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
  const [pageSize, setPageSize] = useState(50)
  const [currentPage, setCurrentPage] = useState(1)
  const [siteFilter, setSiteFilter] = useState('전체')
  const [registrationFilter, setRegistrationFilter] = useState('전체')
  const [sortBy, setSortBy] = useState('updated_at_desc')

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

  // 전송 중 새로고침/탭닫기 방지
  useEffect(() => {
    if (!transmitting) return
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [transmitting])

  const load = useCallback(async () => {
    setLoading(true)
    const [p, a, s, f, pol] = await Promise.all([
      collectorApi.listProducts(0, 500).catch(() => []),
      accountApi.listActive().catch(() => []),
      shipmentApi.list(0, 100).catch(() => []),
      collectorApi.listFilters().catch(() => []),
      policyApi.list().catch(() => []),
    ])
    setProducts(p)
    setAccounts(a)
    setShipments(s)
    setFilters(f)
    setPolicies(pol)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { return () => { if (progressRef.current) clearInterval(progressRef.current) } }, [])

  // URL에서 선택된 상품 ID 자동 적용 + 필터링
  const preSelectedIds = searchParams.get('selected')?.split(',') || []
  const preSelectedSites = searchParams.get('sites')?.split(',') || []
  const autoAll = searchParams.get('autoAll') === '1'
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    if (products.length === 0) return
    initializedRef.current = true

    if (preSelectedIds.length > 0) {
      const ids = preSelectedIds.filter(id => products.some(p => p.id === id))
      if (ids.length > 0) setSelectedProducts(ids)
    }
    if (preSelectedSites.length > 0) {
      setSelectedSites(preSelectedSites.filter(s => s))
    }
    if (autoAll && accounts.length > 0) {
      setUpdateItems({ all: true, price: true, thumb: true, detail: true })
      const allTypes = [...new Set(accounts.map(a => a.market_type))]
      setSelectedMarkets(allTypes)
      setSelectedAccounts(getAccountIdsByMarkets(allTypes))
    }
  }, [products, accounts]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleProduct = (id: string) => setSelectedProducts(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  const toggleAllProducts = () => setSelectedProducts(prev => prev.length === filteredProducts.length ? [] : filteredProducts.map(p => p.id))
  const toggleAccount = (id: string) => setSelectedAccounts(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  const toggleSite = (site: string) => setSelectedSites(prev => prev.includes(site) ? prev.filter(x => x !== site) : [...prev, site])

  // 필터 이름 맵 (매 렌더마다 재생성 방지)
  const filterNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const f of filters) map[f.id] = f.name
    return map
  }, [filters])

  const filteredProducts = useMemo(() => {
    const q = searchText.trim().toLowerCase()
    return products.filter(p => {
      if (siteFilter !== '전체' && p.source_site !== siteFilter) return false
      // 마켓등록 필터
      if (registrationFilter === '등록' && !(p.registered_accounts?.length)) return false
      if (registrationFilter === '미등록' && (p.registered_accounts?.length ?? 0) > 0) return false
      if (!q) return true
      switch (searchField) {
        case 'name':
          return p.name.toLowerCase().includes(q)
        case 'no':
          return (p.site_product_id || '').toLowerCase().includes(q)
        case 'group':
          return (filterNameMap[p.search_filter_id || ''] || '').toLowerCase().includes(q)
        default:
          return true
      }
    }).sort((a, b) => {
      // market_xxx_desc / market_xxx_asc 패턴 감지
      const marketMatch = sortBy.match(/^market_(.+?)_(asc|desc)$/)
      if (marketMatch) {
        const marketType = marketMatch[1]
        const mul = marketMatch[2] === 'desc' ? -1 : 1
        const getMarketTime = (p: typeof a) => {
          const accIds = (p.registered_accounts || [])
          const accId = accIds.find(aid => {
            const acc = accounts.find(x => x.id === aid)
            return acc?.market_type === marketType
          })
          if (!accId) return ''
          const s = shipments.filter(x => x.product_id === p.id && x.account_id === accId && x.completed_at)
            .sort((x, y) => new Date(y.completed_at!).getTime() - new Date(x.completed_at!).getTime())[0]
          return s?.completed_at || ''
        }
        const va = getMarketTime(a), vb = getMarketTime(b)
        return va > vb ? mul : va < vb ? -mul : 0
      }
      const isDesc = sortBy.endsWith('_desc')
      const field = sortBy.replace(/_desc$|_asc$/, '')
      const mul = isDesc ? -1 : 1
      const getVal = (p: typeof a) => {
        switch (field) {
          case 'updated_at': return p.updated_at || ''
          case 'collected_at': return p.collected_at || p.created_at || ''
          default: return p.updated_at || ''
        }
      }
      return getVal(a) > getVal(b) ? mul : getVal(a) < getVal(b) ? -mul : 0
    })
  }, [products, siteFilter, registrationFilter, searchText, searchField, filterNameMap, sortBy, accounts, shipments])

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
    // 등록된 마켓이 있는 상품만 필터
    const targetProducts = selectedProducts.filter(pid => {
      const p = products.find(x => x.id === pid)
      return p && (p.registered_accounts || []).some(aid => selectedAccounts.includes(aid))
    })
    if (targetProducts.length === 0) { showAlert('선택된 상품 중 등록된 마켓이 없습니다'); return }
    if (selectedAccounts.length === 0) { showAlert('마켓 계정을 선택해주세요'); return }

    const targetLabels = selectedAccounts.map(aid => {
      const acc = accounts.find(a => a.id === aid)
      return acc ? `${acc.market_name}(${acc.seller_id || '-'})` : aid
    }).join(', ')
    if (!await showConfirm(`${targetProducts.length}개 상품을 ${targetLabels}에서 마켓삭제하시겠습니까?`)) return

    setTransmitting(true)
    const ts = () => new Date().toLocaleTimeString()
    const addLog = (msg: string) => setLogMessages(prev => [...prev, msg])
    addLog(`[${ts()}] 마켓삭제 시작 — 상품 ${targetProducts.length}개`)

    try {
      const res = await shipmentApi.marketDelete(targetProducts, selectedAccounts)
      let totalSuccess = 0
      let totalFail = 0
      for (const r of res.results) {
        const prod = products.find(p => p.id === r.product_id)
        const prodName = prod?.name || r.product_id
        if (r.success_count > 0) {
          addLog(`[${ts()}]   ${prodName}: ${r.success_count}개 마켓 삭제 성공`)
          totalSuccess += r.success_count
        }
        const fails = Object.entries(r.delete_results).filter(([, st]) => st !== 'success')
        for (const [aid, msg] of fails) {
          const acc = accounts.find(a => a.id === aid)
          addLog(`[${ts()}]   ${prodName} → ${acc?.market_name || aid}: ${msg}`)
          totalFail++
        }
      }
      addLog(`[${ts()}] 마켓삭제 완료 — 성공 ${totalSuccess}건, 실패 ${totalFail}건`)
      await load()
    } catch (e) {
      addLog(`[${ts()}] 마켓삭제 오류: ${e}`)
    }
    setTransmitting(false)
  }

  const handleStart = async () => {
    if (selectedProducts.length === 0) { showAlert('상품을 선택해주세요'); return }
    if (selectedAccounts.length === 0) { showAlert('마켓 계정을 선택해주세요'); return }

    setTransmitting(true)

    const ts = () => new Date().toLocaleTimeString()
    const addLog = (msg: string) => setLogMessages(prev => [...prev, msg])

    // 계정 ID → 표시명 매핑
    const accountLabelMap: Record<string, string> = {}
    for (const acc of accounts) {
      accountLabelMap[acc.id] = `${acc.market_name}(${acc.seller_id || acc.account_label || acc.business_name || '-'})`
    }

    // 정책 적용된 상품만 전송 대상 (미적용 상품은 사전 제외)
    const policyProducts = selectedProducts.filter(pid => {
      const prod = products.find(p => p.id === pid)
      return !!prod?.applied_policy_id
    })
    const total = policyProducts.length

    if (total === 0) {
      addLog(`[${ts()}] 전송 대상 없음 — 선택된 상품에 적용된 정책이 없습니다`)
      setTransmitting(false)
      return
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

    let successCount = 0
    let failCount = 0
    let skipCount = 0

    // 에러 메시지 요약 (너무 긴 메시지 truncate)
    const shortenError = (msg: string): string => {
      if (msg.length <= 80) return msg
      const apiMatch = msg.match(/API (?:에러|ERROR)[^:]*:\s*(.+)/)
      if (apiMatch) {
        const inner = apiMatch[1]
        const first = inner.split(',')[0].trim().replace(/^\[/, '')
        const count = (inner.match(/,/g) || []).length
        return count > 0 ? `${first} 외 ${count}건` : first
      }
      return msg.slice(0, 77) + '...'
    }

    // 마켓별 결과 수집
    type MarketLogEntry = { idx: number, prodLabel: string, status: string, error?: string }
    const marketGrouped: Record<string, MarketLogEntry[]> = {}
    const marketOrder: string[] = []

    // 전송 태스크 사전 준비
    type TransmitTask = { idx: number, pid: string, prodLabel: string, targetAccIds: string[] }
    const tasks: TransmitTask[] = []
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

    // 순차 전송 (상품당 이미지 동시 4장)
    const BATCH_SIZE = 1
    let doneCount = 0
    for (let b = 0; b < tasks.length; b += BATCH_SIZE) {
      if (abortRef.current) {
        addLog(`[${ts()}] ⛔ 전송 강제 중단 — ${doneCount}/${total} 완료 시점에서 중단됨`)
        break
      }
      const batch = tasks.slice(b, b + BATCH_SIZE)
      const promises = batch.map(async (task) => {
        if (abortRef.current) return
        try {
          const res = await shipmentApi.start([task.pid], items, task.targetAccIds, skipEnabled)
          const r = res.results?.[0]
          if (!r) {
            for (const aid of task.targetAccIds) {
              const label = accountLabelMap[aid] || aid
              if (!marketGrouped[label]) { marketGrouped[label] = []; marketOrder.push(label) }
              marketGrouped[label].push({ idx: task.idx, prodLabel: task.prodLabel, status: 'failed', error: '응답 없음' })
              failCount++
            }
            return
          }
          if (r.status === 'skipped') { skipCount++; return }
          const txResult = r.transmit_result || {}
          const txError = r.transmit_error || {}
          for (const [accId, status] of Object.entries(txResult)) {
            const label = accountLabelMap[accId] || accId
            if (status === 'success') {
              addLog(`[${ts()}] [${task.idx}/${total}] ${task.prodLabel} → ${label}: 성공`)
              successCount++
            } else if (status === 'skipped') {
              skipCount++
            } else {
              addLog(`[${ts()}] [${task.idx}/${total}] ${task.prodLabel} → ${label}: 실패 — ${shortenError(txError[accId] || '알 수 없는 오류')}`)
              failCount++
            }
          }
        } catch (e) {
          const msg = e instanceof Error ? e.message : '전송 실패'
          for (const aid of task.targetAccIds) {
            const label = accountLabelMap[aid] || aid
            addLog(`[${ts()}] [${task.idx}/${total}] ${task.prodLabel} → ${label}: 실패 — ${shortenError(msg)}`)
            failCount++
          }
        }
      })
      await Promise.all(promises)
      doneCount += batch.length
      setProgress({ current: doneCount, total })
    }

    // 최종 요약
    const summaryParts: string[] = []
    if (successCount > 0) summaryParts.push(`성공 ${successCount}건`)
    if (failCount > 0) summaryParts.push(`실패 ${failCount}건`)
    if (skipCount > 0) summaryParts.push(`스킵 ${skipCount}건`)
    addLog(`[${ts()}] 전송 완료 — ${summaryParts.length > 0 ? summaryParts.join(', ') : '처리 없음'}`)

    setProgress({ current: total, total })

    if (loopEnabled && !abortRef.current) {
      addLog(`[${ts()}] 무한반복 모드 — 상품 새로고침 후 재시작...`)
      await load()
      // 새로고침 후 즉시 재시작
      setTimeout(() => handleStart(), 1000)
    } else {
      setTimeout(() => { setTransmitting(false); load() }, 2000)
    }
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: '1.25rem' }} />

      {/* 전송 설정 패널 */}
      <div style={{ background: 'rgba(14,14,20,0.98)', border: '1px solid #1E2030', borderRadius: '8px', marginBottom: '10px', fontSize: '0.8rem' }}>
        {/* 검색항목 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', borderBottom: '1px solid #181C28', gap: '8px' }}>
          <span style={{ minWidth: '72px', color: '#666', fontSize: '0.78rem' }}>검색항목</span>
          <select value={searchField} onChange={e => setSearchField(e.target.value)} style={{ ...inputStyle, width: '100px' }}>
            <option value="name">상품명</option>
            <option value="no">상품번호</option>
            <option value="group">그룹명</option>
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
            <button style={{ padding: '6px 24px', fontSize: '0.875rem', background: 'transparent', border: '1px solid #2A3040', color: '#9AA5C0', borderRadius: '6px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>

        {/* 소싱사이트 체크박스 */}
        <div style={{ padding: '10px 16px 12px', borderBottom: '1px solid #181C28' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#C5C5C5', marginBottom: '10px', paddingBottom: '6px', borderBottom: '1px solid #1C1E2A' }}>소싱사이트</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 24px' }}>
            {SOURCE_SITES.filter(s => s !== '전체').map(site => (
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
              <button onClick={() => { abortRef.current = true }}
                style={{ padding: '4px 16px', fontSize: '0.78rem', background: 'rgba(255,107,107,0.2)', color: '#FF6B6B', border: '1px solid rgba(255,107,107,0.5)', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}
              >강제 중단</button>
            ) : (<>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: loopEnabled ? '#FF8C00' : '#666', cursor: 'pointer' }}>
                <input type="checkbox" checked={loopEnabled} onChange={() => setLoopEnabled(!loopEnabled)} style={{ accentColor: '#FF8C00', width: '13px', height: '13px' }} />
                무한반복
              </label>
              <button onClick={handleStart}
                style={{ padding: '4px 16px', fontSize: '0.78rem', background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}
              >전송 시작</button>
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
            else if (msg.includes('성공')) color = '#7BAF7E'
            return <div key={i} style={{ color }}>{msg}</div>
          })}
        </div>
        {/* 프로그레스바 */}
        {transmitting && (
          <div style={{ padding: '6px 14px 8px', borderTop: '1px solid #1C1E2A' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontSize: '0.75rem', color: '#7B8DB0' }}>{progress.current}/{progress.total} 처리 중...</span>
            </div>
            <div style={{ background: '#111520', borderRadius: '4px', height: '5px', overflow: 'hidden' }}>
              <div style={{ background: 'linear-gradient(90deg,#FF8C00,#FFB84D)', height: '100%', width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%`, transition: 'width 0.3s' }} />
            </div>
          </div>
        )}
      </div>

      {/* 상품 목록 테이블 */}
      <div style={{ background: 'rgba(30,30,30,0.5)', border: '1px solid #2D2D2D', borderRadius: '12px', overflow: 'hidden' }}>
        {/* 상단 탭 */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid #2D2D2D', gap: '8px' }}>
          <span style={{ fontSize: '0.8rem', color: '#888' }}>총 <span style={{ color: '#FF8C00', fontWeight: 600 }}>{filteredProducts.length.toLocaleString()}</span> 개의 상품이 검색되었습니다.</span>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...inputStyle, width: '250px', marginLeft: 'auto' }}>
            <option value="updated_at_desc">상품업데이트 날짜순 ▼</option>
            <option value="updated_at_asc">상품업데이트 날짜순 ▲</option>
            <option value="collected_at_desc">상품수집 날짜순 ▼</option>
            <option value="collected_at_asc">상품수집 날짜순 ▲</option>
            {registeredMarkets.flatMap(m => [
              <option key={`${m.type}_asc`} value={`market_${m.type}_asc`}>{m.name} 업데이트 날짜순 ▲</option>,
              <option key={`${m.type}_desc`} value={`market_${m.type}_desc`}>{m.name} 업데이트 날짜순 ▼</option>,
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
              <th style={{ width: '36px', padding: '0.625rem' }}><input type="checkbox" checked={selectedProducts.length === filteredProducts.length && filteredProducts.length > 0} onChange={toggleAllProducts} style={{ accentColor: '#F59E0B' }} /></th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>No</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>사이트</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'left', fontSize: '0.72rem', color: '#888' }}>상품명</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#888' }}>상품업데이트</th>
              <th style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#888' }}>마켓 전송</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</td></tr>
            ) : filteredProducts.length === 0 ? (
              <tr><td colSpan={6} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>상품이 없습니다</td></tr>
            ) : filteredProducts.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((p, idx) => {
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
                  <td style={{ padding: '0.625rem 0.5rem', color: '#666', fontSize: '0.72rem' }}>{p.site_product_id || idx + 1}</td>
                  <td style={{ padding: '0.625rem 0.5rem', fontSize: '0.75rem', color: '#888' }}>{p.source_site}</td>
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
                      // 해당 상품의 최근 shipment에서 전송 시간 조회
                      const productShipments = shipments.filter(s => s.product_id === p.id && s.completed_at)
                      const lastShipment = productShipments.sort((a, b) => new Date(b.completed_at!).getTime() - new Date(a.completed_at!).getTime())[0]
                      const lastTime = lastShipment?.completed_at ? (() => {
                        const d = new Date(lastShipment.completed_at!)
                        return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
                      })() : ''
                      const marketLabels = regAccs.map(aid => {
                        const acc = accounts.find(a => a.id === aid)
                        return acc ? `${acc.market_name}(${acc.seller_id || acc.account_label || '-'})` : null
                      }).filter(Boolean).join(', ')
                      return (
                        <span style={{ fontSize: '0.68rem' }}>
                          <span style={{ color: '#51CF66' }}>{marketLabels}</span>
                          {lastTime && <span style={{ color: '#555' }}> {lastTime}</span>}
                        </span>
                      )
                    })()}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* 페이지네이션 */}
        {filteredProducts.length > pageSize && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px', padding: '12px 0' }}>
            <button
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              style={{ padding: '4px 10px', fontSize: '0.78rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: currentPage <= 1 ? '#444' : '#C5C5C5', cursor: currentPage <= 1 ? 'default' : 'pointer' }}
            >◀</button>
            {Array.from({ length: Math.ceil(filteredProducts.length / pageSize) }, (_, i) => i + 1)
              .filter(page => Math.abs(page - currentPage) <= 2 || page === 1 || page === Math.ceil(filteredProducts.length / pageSize))
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
              disabled={currentPage >= Math.ceil(filteredProducts.length / pageSize)}
              onClick={() => setCurrentPage(p => p + 1)}
              style={{ padding: '4px 10px', fontSize: '0.78rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: currentPage >= Math.ceil(filteredProducts.length / pageSize) ? '#444' : '#C5C5C5', cursor: currentPage >= Math.ceil(filteredProducts.length / pageSize) ? 'default' : 'pointer' }}
            >▶</button>
            <span style={{ fontSize: '0.72rem', color: '#666', marginLeft: '8px' }}>
              {filteredProducts.length}개 중 {(currentPage - 1) * pageSize + 1}~{Math.min(currentPage * pageSize, filteredProducts.length)}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

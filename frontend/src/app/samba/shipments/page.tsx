'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { shipmentApi, accountApi, collectorApi, type SambaShipment, type SambaMarketAccount, type SambaCollectedProduct, type SambaSearchFilter } from '@/lib/samba/api'
import { showAlert } from '@/components/samba/Modal'

const STATUS_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  pending:      { bg: 'rgba(100,100,100,0.15)', text: '#888', label: '대기중' },
  transmitting: { bg: 'rgba(255,211,61,0.15)', text: '#FFD93D', label: '전송중' },
  completed:    { bg: 'rgba(81,207,102,0.15)', text: '#51CF66', label: '완료' },
  partial:      { bg: 'rgba(255,140,0,0.15)', text: '#FF8C00', label: '부분완료' },
  failed:       { bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B', label: '실패' },
}

const SOURCE_SITES = ['전체', 'MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'GrandStage', 'OKmall', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

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
  const [products, setProducts] = useState<SambaCollectedProduct[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [shipments, setShipments] = useState<SambaShipment[]>([])
  const [filters, setFilters] = useState<SambaSearchFilter[]>([])
  const [loading, setLoading] = useState(true)

  // 필터
  const [searchField, setSearchField] = useState('name')
  const [searchText, setSearchText] = useState('')
  const [pageSize, setPageSize] = useState(50)
  const [siteFilter, setSiteFilter] = useState('전체')
  const [registrationFilter, setRegistrationFilter] = useState('전체')

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
  const [selectedSites, setSelectedSites] = useState<string[]>([])

  // 전송 로그
  const [logMessages, setLogMessages] = useState<string[]>(['— 전송 시작 버튼을 누르면 로그가 여기에 실시간으로 표시됩니다 —'])
  const [transmitting, setTransmitting] = useState(false)
  const [progress, setProgress] = useState({ current: 0, total: 0 })
  const progressRef = useRef<NodeJS.Timeout | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    const [p, a, s, f] = await Promise.all([
      collectorApi.listProducts(0, 500).catch(() => []),
      accountApi.listActive().catch(() => []),
      shipmentApi.list(0, 100).catch(() => []),
      collectorApi.listFilters().catch(() => []),
    ])
    setProducts(p)
    setAccounts(a)
    setShipments(s)
    setFilters(f)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { return () => { if (progressRef.current) clearInterval(progressRef.current) } }, [])

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
    })
  }, [products, siteFilter, searchText, searchField, filterNameMap])

  const handleStart = async () => {
    if (selectedProducts.length === 0) { showAlert('상품을 선택해주세요'); return }
    if (selectedAccounts.length === 0) { showAlert('마켓 계정을 선택해주세요'); return }

    setTransmitting(true)
    const total = selectedProducts.length
    setProgress({ current: 0, total })
    setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 전송 시작 - ${total}개 상품, ${selectedAccounts.length}개 계정`])

    let current = 0
    progressRef.current = setInterval(() => {
      current += 1
      setProgress(prev => ({ ...prev, current: Math.min(current, total) }))
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] [${current}/${total}] 전송 처리 중...`])
      if (current >= total && progressRef.current) clearInterval(progressRef.current)
    }, 400)

    try {
      const items = []
      if (updateItems.price) items.push('price', 'stock')
      if (updateItems.thumb) items.push('image')
      if (updateItems.detail) items.push('description')
      await shipmentApi.start(selectedProducts, items, selectedAccounts, skipEnabled)
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 전송 완료!`])
    } catch (e) {
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 오류: ${e instanceof Error ? e.message : '전송 실패'}`])
    }

    if (progressRef.current) clearInterval(progressRef.current)
    setProgress(prev => ({ ...prev, current: total }))
    setTimeout(() => { setTransmitting(false); load() }, 2000)
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
                    if (item.key === 'all') setUpdateItems({ all: !updateItems.all, price: !updateItems.all, thumb: !updateItems.all, detail: !updateItems.all })
                    else setUpdateItems(prev => ({ ...prev, [item.key]: !prev[item.key as keyof typeof prev] }))
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
            ) : [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()].map(([type, name]) => (
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
            <button style={{ padding: '4px 14px', fontSize: '0.78rem', background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.35)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer', fontWeight: 600 }}>삭제</button>
            <button onClick={handleStart} disabled={transmitting}
              style={{ padding: '4px 16px', fontSize: '0.78rem', background: transmitting ? '#333' : 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', border: 'none', borderRadius: '4px', cursor: transmitting ? 'not-allowed' : 'pointer', fontWeight: 600 }}
            >{transmitting ? '전송 중...' : '전송 시작'}</button>
          </div>
        </div>
        <div style={{ height: '200px', overflowY: 'auto', padding: '10px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.73rem', lineHeight: 1.8, color: '#4A5568' }}>
          {logMessages.map((msg, i) => <div key={i} style={{ color: msg.includes('오류') ? '#FF6B6B' : msg.includes('완료') ? '#51CF66' : '#374151' }}>{msg}</div>)}
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
          <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))} style={{ ...inputStyle, width: '80px', marginLeft: 'auto' }}>
            <option value={50}>50개</option>
            <option value={100}>100개</option>
            <option value={200}>200개</option>
            <option value={500}>500개</option>
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
            ) : filteredProducts.slice(0, pageSize).map((p, idx) => {
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
                      <a href={`/samba/products?highlight=${p.id}`} style={{ color: '#4C9AFF', textDecoration: 'none', fontSize: '0.8rem', cursor: 'pointer' }}
                        onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
                        onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
                      >
                        [{p.site_product_id || ''}] {p.name} {optCount > 0 ? <span style={{ color: '#4C9AFF' }}>[옵션수:{optCount}]</span> : ''}
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
                  <td style={{ padding: '0.625rem 0.5rem', textAlign: 'center', fontSize: '0.72rem', color: '#666' }}>
                    {(p.registered_accounts || []).length > 0
                      ? <span style={{ color: '#51CF66' }}>전송완료</span>
                      : <span style={{ color: '#555' }}>-</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

'use client'

import { useEffect, useState, useCallback } from 'react'
import { analyticsApi, accountApi, orderApi, type AnalyticsStats, type SambaMarketAccount, type SambaOrder } from '@/lib/samba/api'

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

const SOURCE_SITES = ['MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'GrandStage', 'OKmall', 'SSG', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

const ORDER_STATUSES = [
  { key: 'pending', label: '주문확인' },
  { key: 'shipped', label: '배송중' },
  { key: 'office_arrived', label: '사무실도착' },
  { key: 'domestic', label: '국내배송' },
  { key: 'cancel_req', label: '취소요청' },
  { key: 'exchange_req', label: '교환요청' },
  { key: 'return_req', label: '반품요청' },
  { key: 'cancel_done', label: '취소/반품/교환/완료' },
  { key: 'delivered', label: '배송완료' },
]
const COLORS = ['#FF8C00', '#4C9AFF', '#51CF66', '#CC5DE8', '#FFD93D', '#FF6B6B', '#20C997', '#F06595', '#845EF7', '#FFA94D', '#66D9E8', '#E599F7']

interface SalesRow {
  name: string
  orders: number
  sales: number
  profit: number
}

interface DailyRow {
  date: string
  orders: number
  sales: number
  profit: number
}

export default function AnalyticsPage() {
  const [loading, setLoading] = useState(true)
  const [marketAccounts, setMarketAccounts] = useState<SambaMarketAccount[]>([])
  const [orders, setOrders] = useState<SambaOrder[]>([])

  // 검색 조건 (localStorage 복원)
  const now = new Date()
  const [searchYear, setSearchYear] = useState(() => {
    if (typeof window === 'undefined') return now.getFullYear()
    try { const s = localStorage.getItem('samba_analytics_search'); return s ? JSON.parse(s).year ?? now.getFullYear() : now.getFullYear() } catch { return now.getFullYear() }
  })
  const [searchMonth, setSearchMonth] = useState(() => {
    if (typeof window === 'undefined') return 0
    try { const s = localStorage.getItem('samba_analytics_search'); return s ? JSON.parse(s).month ?? 0 : 0 } catch { return 0 }
  })
  const [selectedMarkets, setSelectedMarkets] = useState<string[]>(() => {
    if (typeof window === 'undefined') return []
    try { const s = localStorage.getItem('samba_analytics_search'); return s ? JSON.parse(s).markets ?? [] : [] } catch { return [] }
  })
  const [selectedSites, setSelectedSites] = useState<string[]>(() => {
    if (typeof window === 'undefined') return [...SOURCE_SITES]
    try { const s = localStorage.getItem('samba_analytics_search'); return s ? JSON.parse(s).sites ?? [...SOURCE_SITES] : [...SOURCE_SITES] } catch { return [...SOURCE_SITES] }
  })
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(() => {
    if (typeof window === 'undefined') return ORDER_STATUSES.map(s => s.key)
    try { const s = localStorage.getItem('samba_analytics_search'); return s ? JSON.parse(s).statuses ?? ORDER_STATUSES.map(s => s.key) : ORDER_STATUSES.map(s => s.key) } catch { return ORDER_STATUSES.map(s => s.key) }
  })

  const toggleItem = (arr: string[], setArr: (v: string[]) => void, item: string) => {
    setArr(arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item])
  }

  const load = useCallback(async () => {
    try {
      localStorage.setItem('samba_analytics_search', JSON.stringify({
        year: searchYear, month: searchMonth, markets: selectedMarkets, sites: selectedSites, statuses: selectedStatuses,
      }))
    } catch {}

    setLoading(true)
    try {
      const allOrders = await orderApi.list(0, 500).catch(() => [])
      setOrders(allOrders)
    } catch {}
    setLoading(false)
  }, [searchYear, searchMonth, selectedMarkets, selectedSites, selectedStatuses])

  useEffect(() => { load() }, [load])
  useEffect(() => { accountApi.listActive().then(setMarketAccounts).catch(() => {}) }, [])

  // 기간 + 주문상태 필터링
  const filteredOrders = orders.filter(o => {
    const d = new Date(o.created_at)
    if (d.getFullYear() !== searchYear) return false
    if (searchMonth > 0 && d.getMonth() + 1 !== searchMonth) return false
    // 주문상태 필터 (전체 선택이 아닌 경우)
    if (selectedStatuses.length > 0 && selectedStatuses.length < ORDER_STATUSES.length) {
      if (!selectedStatuses.includes(o.status)) return false
    }
    return true
  })

  // 소싱처별 매출 집계
  const siteRows: SalesRow[] = (() => {
    const map: Record<string, SalesRow> = {}
    for (const o of filteredOrders) {
      const site = o.source_site || '기타'
      if (!map[site]) map[site] = { name: site, orders: 0, sales: 0, profit: 0 }
      map[site].orders += 1
      map[site].sales += o.sale_price || 0
      map[site].profit += (o.sale_price || 0) - (o.cost || 0)
    }
    return Object.values(map).sort((a, b) => b.sales - a.sales)
  })()

  // 판매마켓별 매출 집계
  const marketRows: SalesRow[] = (() => {
    const map: Record<string, SalesRow> = {}
    for (const o of filteredOrders) {
      const market = o.channel_name || '기타'
      if (!map[market]) map[market] = { name: market, orders: 0, sales: 0, profit: 0 }
      map[market].orders += 1
      map[market].sales += o.sale_price || 0
      map[market].profit += (o.sale_price || 0) - (o.cost || 0)
    }
    return Object.values(map).sort((a, b) => b.sales - a.sales)
  })()

  // 일별 매출 집계
  const dailyRows: DailyRow[] = (() => {
    const map: Record<string, DailyRow> = {}
    for (const o of filteredOrders) {
      const date = o.created_at.slice(0, 10)
      if (!map[date]) map[date] = { date, orders: 0, sales: 0, profit: 0 }
      map[date].orders += 1
      map[date].sales += o.sale_price || 0
      map[date].profit += (o.sale_price || 0) - (o.cost || 0)
    }
    return Object.values(map).sort((a, b) => a.date.localeCompare(b.date))
  })()

  // 전체 합계
  const totalSales = filteredOrders.reduce((s, o) => s + (o.sale_price || 0), 0)
  const totalProfit = filteredOrders.reduce((s, o) => s + (o.sale_price || 0) - (o.cost || 0), 0)
  const totalOrders = filteredOrders.length

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '50vh', color: '#555' }}>로딩 중...</div>
  }

  // 가로 바 차트 렌더러
  const renderBarTable = (rows: SalesRow[], label: string) => {
    const maxSales = Math.max(...rows.map(r => r.sales), 1)
    return (
      <div>
        {rows.length === 0 ? (
          <p style={{ color: '#555', fontSize: '0.875rem', padding: '2rem 0', textAlign: 'center' }}>데이터가 없습니다</p>
        ) : rows.map((r, i) => {
          const pct = (r.sales / maxSales) * 100
          return (
            <div key={r.name} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
              <span style={{ fontSize: '0.8rem', color: COLORS[i % COLORS.length], minWidth: '90px', textAlign: 'right', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.name}</span>
              <div style={{ flex: 1, height: '22px', background: 'rgba(45,45,45,0.5)', borderRadius: '4px', overflow: 'hidden', position: 'relative' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: COLORS[i % COLORS.length], borderRadius: '4px', transition: 'width 0.5s ease', minWidth: pct > 0 ? '2px' : '0' }} />
              </div>
              <span style={{ fontSize: '0.75rem', color: '#888', minWidth: '40px', textAlign: 'right' }}>{r.orders}건</span>
              <span style={{ fontSize: '0.75rem', color: '#E5E5E5', minWidth: '90px', textAlign: 'right' }}>₩{r.sales.toLocaleString()}</span>
              <span style={{ fontSize: '0.75rem', color: r.profit >= 0 ? '#51CF66' : '#FF6B6B', minWidth: '80px', textAlign: 'right' }}>₩{r.profit.toLocaleString()}</span>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>매출통계</h2>
        <p style={{ fontSize: '0.875rem', color: '#888' }}>소싱처별 · 마켓별 · 일별 매출 현황</p>
      </div>

      {/* 검색 조건 */}
      <div style={{ ...card, padding: '1.25rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
          <select value={searchYear} onChange={e => setSearchYear(Number(e.target.value))}
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', outline: 'none', cursor: 'pointer' }}>
            {[2024, 2025, 2026].map(y => <option key={y} value={y}>{y}년</option>)}
          </select>
          <select value={searchMonth} onChange={e => setSearchMonth(Number(e.target.value))}
            style={{ padding: '0.375rem 0.5rem', fontSize: '0.8125rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', outline: 'none', cursor: 'pointer' }}>
            <option value={0}>전체</option>
            {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}월</option>)}
          </select>
          <button onClick={load}
            style={{ padding: '0.375rem 0.875rem', fontSize: '0.8125rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '4px', fontWeight: 600, cursor: 'pointer' }}>매출검색</button>
          <span style={{ marginLeft: 'auto', fontSize: '0.8125rem', color: '#888' }}>
            총 <span style={{ color: '#FF8C00', fontWeight: 700 }}>{totalOrders}</span>건 · 매출 <span style={{ color: '#FF8C00', fontWeight: 700 }}>₩{totalSales.toLocaleString()}</span> · 수익 <span style={{ color: '#51CF66', fontWeight: 700 }}>₩{totalProfit.toLocaleString()}</span>
          </span>
        </div>

        {/* 마켓 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.625rem 0', borderTop: '1px solid #2D2D2D', flexWrap: 'wrap' }}>
          <span style={{ color: '#888', fontSize: '0.8125rem', minWidth: '65px', flexShrink: 0 }}>마켓</span>
          {(() => {
            const marketNames = [...new Set([...marketAccounts.map(a => a.market_name)])]
            const allMarkets = marketNames.length > 0 ? marketNames : ['스마트스토어', '11번가']
            const isAll = selectedMarkets.length === 0 || selectedMarkets.length === allMarkets.length
            return (
              <>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', color: '#888', cursor: 'pointer' }}>
                  <input type="checkbox" checked={isAll} onChange={() => setSelectedMarkets(isAll ? [] : [...allMarkets])} /> 전체
                </label>
                {allMarkets.map(name => (
                  <label key={name} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={isAll || selectedMarkets.includes(name)} onChange={() => {
                      if (isAll) setSelectedMarkets(allMarkets.filter(m => m !== name))
                      else toggleItem(selectedMarkets, setSelectedMarkets, name)
                    }} style={{ accentColor: '#FF8C00' }} />
                    <span style={{ color: '#FF8C00' }}>{name}</span>
                  </label>
                ))}
              </>
            )
          })()}
        </div>

        {/* 소싱사이트 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.625rem 0', borderTop: '1px solid #2D2D2D', flexWrap: 'wrap' }}>
          <span style={{ color: '#888', fontSize: '0.8125rem', minWidth: '65px', flexShrink: 0 }}>소싱사이트</span>
          {(() => {
            const isAll = selectedSites.length === SOURCE_SITES.length || selectedSites.length === 0
            return (
              <>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', color: '#888', cursor: 'pointer' }}>
                  <input type="checkbox" checked={isAll} onChange={() => setSelectedSites(isAll ? [] : [...SOURCE_SITES])} /> 전체
                </label>
                {SOURCE_SITES.map(site => (
                  <label key={site} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={isAll || selectedSites.includes(site)} onChange={() => {
                      if (isAll) setSelectedSites(SOURCE_SITES.filter(s => s !== site))
                      else toggleItem(selectedSites, setSelectedSites, site)
                    }} style={{ accentColor: '#FF8C00' }} />
                    <span style={{ color: '#FF8C00' }}>{site}</span>
                  </label>
                ))}
              </>
            )
          })()}
        </div>

        {/* 주문상태 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.625rem 0', borderTop: '1px solid #2D2D2D', flexWrap: 'wrap' }}>
          <span style={{ color: '#888', fontSize: '0.8125rem', minWidth: '65px', flexShrink: 0 }}>주문상태</span>
          {(() => {
            const allKeys = ORDER_STATUSES.map(s => s.key)
            const isAll = selectedStatuses.length === allKeys.length || selectedStatuses.length === 0
            return (
              <>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', color: '#888', cursor: 'pointer' }}>
                  <input type="checkbox" checked={isAll} onChange={() => setSelectedStatuses(isAll ? [] : [...allKeys])} /> 전체
                </label>
                {ORDER_STATUSES.map(st => (
                  <label key={st.key} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8125rem', cursor: 'pointer' }}>
                    <input type="checkbox" checked={isAll || selectedStatuses.includes(st.key)} onChange={() => {
                      if (isAll) setSelectedStatuses(allKeys.filter(k => k !== st.key))
                      else toggleItem(selectedStatuses, setSelectedStatuses, st.key)
                    }} style={{ accentColor: '#FF8C00' }} />
                    <span style={{ color: '#FF8C00' }}>{st.label}</span>
                  </label>
                ))}
              </>
            )
          })()}
        </div>
      </div>

      {/* 소싱처별 매출 */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600 }}>소싱처별 매출</h3>
          <span style={{ fontSize: '0.75rem', color: '#666' }}>{siteRows.length}개 소싱처</span>
        </div>
        {renderBarTable(siteRows, '소싱처')}
      </div>

      {/* 판매마켓별 매출 */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600 }}>판매마켓별 매출</h3>
          <span style={{ fontSize: '0.75rem', color: '#666' }}>{marketRows.length}개 마켓</span>
        </div>
        {renderBarTable(marketRows, '마켓')}
      </div>

      {/* 일별 매출 */}
      <div style={{ ...card, padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600 }}>일별 매출</h3>
          <span style={{ fontSize: '0.75rem', color: '#666' }}>{dailyRows.length}일</span>
        </div>
        {dailyRows.length === 0 ? (
          <p style={{ color: '#555', fontSize: '0.875rem', padding: '2rem 0', textAlign: 'center' }}>데이터가 없습니다</p>
        ) : (
          <>
            {/* 바 차트 */}
            <div style={{ overflowX: 'auto', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '4px', height: '140px', minWidth: `${dailyRows.length * 30}px` }}>
                {dailyRows.map((d, i) => {
                  const maxSales = Math.max(...dailyRows.map(r => r.sales), 1)
                  const pct = (d.sales / maxSales) * 100
                  return (
                    <div key={d.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', height: '100%', justifyContent: 'flex-end', minWidth: '24px' }}>
                      {d.sales > 0 && <span style={{ fontSize: '0.5625rem', color: '#555', whiteSpace: 'nowrap' }}>₩{(d.sales / 10000).toFixed(0)}만</span>}
                      <div
                        style={{ width: '100%', height: `${Math.max(pct, d.sales > 0 ? 4 : 1)}%`, background: d.sales > 0 ? '#FF8C00' : 'rgba(45,45,45,0.5)', borderRadius: '3px 3px 0 0', minHeight: '2px', transition: 'height 0.3s' }}
                        title={`${d.date}: ₩${d.sales.toLocaleString()} / ${d.orders}건 / 수익 ₩${d.profit.toLocaleString()}`}
                      />
                      <span style={{ fontSize: '0.5625rem', color: '#555', whiteSpace: 'nowrap' }}>{d.date.slice(5)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
            {/* 테이블 */}
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                    {['날짜', '주문수', '매출', '수익'].map((h, i) => (
                      <th key={h} style={{ textAlign: i === 0 ? 'left' : 'right', padding: '0.5rem 0.75rem', color: '#888', fontWeight: 500, fontSize: '0.75rem' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...dailyRows].reverse().map(d => (
                    <tr key={d.date} style={{ borderBottom: '1px solid rgba(45,45,45,0.3)' }}>
                      <td style={{ padding: '0.5rem 0.75rem', color: '#E5E5E5' }}>{d.date}</td>
                      <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right', color: '#888' }}>{d.orders}건</td>
                      <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>₩{d.sales.toLocaleString()}</td>
                      <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right', color: d.profit >= 0 ? '#51CF66' : '#FF6B6B' }}>₩{d.profit.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

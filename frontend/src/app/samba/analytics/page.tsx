'use client'

import { useEffect, useState, useCallback } from 'react'
import { accountApi, orderApi, type SambaMarketAccount, type SambaOrder } from '@/lib/samba/api'
import { useLocalStorageState } from '@/hooks/useLocalStorageState'
import { STORAGE_KEYS } from '@/lib/samba/constants'

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

const SOURCE_SITES = ['MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'GrandStage', 'OKmall', 'SSG', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

// 주문상태 목록
const ORDER_STATUSES = [
  { key: 'pending', label: '주문접수' },
  { key: 'wait_ship', label: '배송대기중' },
  { key: 'arrived', label: '사무실도착' },
  { key: 'ship_failed', label: '송장전송실패' },
  { key: 'shipping', label: '배송중' },
  { key: 'delivered', label: '배송완료' },
  { key: 'cancelling', label: '취소중' },
  { key: 'returning', label: '반품중' },
  { key: 'exchanging', label: '교환중' },
  { key: 'cancel_requested', label: '취소요청' },
  { key: 'return_requested', label: '반품요청' },
  { key: 'cancelled', label: '취소완료' },
  { key: 'returned', label: '반품완료' },
  { key: 'exchanged', label: '교환완료' },
]
// 기본 선택 상태
const DEFAULT_STATUSES = ['pending', 'wait_ship', 'arrived', 'shipping', 'delivered']

/** 검색 조건 저장 구조 */
interface AnalyticsSearch {
  year: number
  month: number
  markets: string[]
  sites: string[]
  statuses: string[]
}

// 월별 집계 셀
interface MonthlyCell {
  sales: number
  orders: number
}

// 숫자 포맷
const fmt = (n: number) => n.toLocaleString()

export default function AnalyticsPage() {
  useEffect(() => { document.title = 'SAMBA-분석' }, [])
  const [loading, setLoading] = useState(true)
  const [marketAccounts, setMarketAccounts] = useState<SambaMarketAccount[]>([])
  const [orders, setOrders] = useState<SambaOrder[]>([])

  // 검색 조건 (localStorage 자동 복원/저장)
  const now = new Date()
  const defaultSearch: AnalyticsSearch = {
    year: now.getFullYear(),
    month: 0,
    markets: [],
    sites: [],
    statuses: DEFAULT_STATUSES,
  }
  const [search, setSearch] = useLocalStorageState<AnalyticsSearch>(
    STORAGE_KEYS.ANALYTICS_SEARCH,
    defaultSearch,
  )
  // localStorage에 저장된 이전 상태 키가 유효하지 않으면 전체 리셋
  const validKeys = new Set(ORDER_STATUSES.map(s => s.key))
  useEffect(() => {
    const hasInvalid = search.statuses.some(k => !validKeys.has(k))
    if (hasInvalid || search.statuses.length === 0) {
      setSearch(prev => ({ ...prev, statuses: DEFAULT_STATUSES, markets: [], sites: [] }))
    }
  }, [])
  const searchYear = search.year
  const searchMonth = search.month
  const selectedMarkets = search.markets
  const selectedSites = search.sites
  const selectedStatuses = search.statuses
  const setSearchYear = (v: number) => setSearch(prev => ({ ...prev, year: v }))
  const setSearchMonth = (v: number) => setSearch(prev => ({ ...prev, month: v }))
  const setSelectedMarkets = (v: string[]) => setSearch(prev => ({ ...prev, markets: v }))
  const setSelectedSites = (v: string[]) => setSearch(prev => ({ ...prev, sites: v }))
  const setSelectedStatuses = (v: string[]) => setSearch(prev => ({ ...prev, statuses: v }))

  const toggleItem = (arr: string[], setArr: (v: string[]) => void, item: string) => {
    setArr(arr.includes(item) ? arr.filter(x => x !== item) : [...arr, item])
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const allOrders = await orderApi.list(0, 500).catch(() => [])
      setOrders(allOrders)
      if (search.sites.length === 0) {
        const collectedSites = [...new Set(allOrders.map(o => o.source_site).filter((s): s is string => !!s))]
          .filter(s => SOURCE_SITES.includes(s))
        if (collectedSites.length > 0) setSelectedSites(collectedSites)
      }
    } catch {}
    setLoading(false)
  }, [search])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    accountApi.listActive().then(accounts => {
      setMarketAccounts(accounts)
      if (search.markets.length === 0) {
        const registeredMarkets = [...new Set(accounts.map(a => a.market_name))]
        if (registeredMarkets.length > 0) setSelectedMarkets(registeredMarkets)
      }
    }).catch(() => {})
  }, [])

  // 기간 + 주문상태 필터링
  const filteredOrders = orders.filter(o => {
    const d = new Date(o.created_at)
    if (d.getFullYear() !== searchYear) return false
    if (searchMonth > 0 && d.getMonth() + 1 !== searchMonth) return false
    if (selectedStatuses.length > 0 && selectedStatuses.length < ORDER_STATUSES.length) {
      if (!selectedStatuses.includes(o.status)) return false
    }
    return true
  })

  // 전체 합계
  const totalSales = filteredOrders.reduce((s, o) => s + (o.sale_price || 0), 0)
  const totalOrders = filteredOrders.length

  // ──────────────────────────────────────────────
  // 월별 집계 함수: groupKey로 12개월 × 카테고리 집계
  // ──────────────────────────────────────────────
  const buildMonthlyTable = (
    getKey: (o: SambaOrder) => string,
  ): { columns: string[], data: Record<number, Record<string, MonthlyCell>> } => {
    const colSet = new Set<string>()
    // data[month][column] = { sales, orders }
    const data: Record<number, Record<string, MonthlyCell>> = {}
    for (let m = 1; m <= 12; m++) data[m] = {}

    for (const o of filteredOrders) {
      const d = new Date(o.created_at)
      if (d.getFullYear() !== searchYear) continue
      const month = d.getMonth() + 1
      const key = getKey(o)
      colSet.add(key)
      if (!data[month][key]) data[month][key] = { sales: 0, orders: 0 }
      data[month][key].sales += o.sale_price || 0
      data[month][key].orders += 1
    }

    const columns = [...colSet].sort()
    return { columns, data }
  }

  // 마켓별 통계
  const marketTable = buildMonthlyTable(o => o.channel_name || '기타')
  // 수집사이트별 통계
  const siteTable = buildMonthlyTable(o => o.source_site || '미등록상품')
  // 주문상태별 통계
  const statusLabelMap: Record<string, string> = {}
  for (const s of ORDER_STATUSES) statusLabelMap[s.key] = s.label
  const statusTable = buildMonthlyTable(o => statusLabelMap[o.status] || o.status)

  // 테이블 셀 스타일
  const thStyle: React.CSSProperties = {
    padding: '8px 12px',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#B0B0B0',
    borderBottom: '2px solid #3D3D3D',
    borderRight: '1px solid #2D2D2D',
    textAlign: 'center',
    whiteSpace: 'nowrap',
  }
  const tdStyle: React.CSSProperties = {
    padding: '6px 10px',
    fontSize: '0.75rem',
    color: '#D0D0D0',
    borderBottom: '1px solid #2D2D2D',
    borderRight: '1px solid #2D2D2D',
    textAlign: 'right',
    whiteSpace: 'nowrap',
  }
  const tdEmptyStyle: React.CSSProperties = {
    ...tdStyle,
    textAlign: 'center',
    color: '#555',
  }

  // 월별 테이블 렌더러
  const renderMonthlyTable = (
    title: string,
    columns: string[],
    data: Record<number, Record<string, MonthlyCell>>,
  ) => {
    // 열별 합계
    const colTotals: Record<string, MonthlyCell> = {}
    for (const col of columns) {
      colTotals[col] = { sales: 0, orders: 0 }
      for (let m = 1; m <= 12; m++) {
        const cell = data[m]?.[col]
        if (cell) {
          colTotals[col].sales += cell.sales
          colTotals[col].orders += cell.orders
        }
      }
    }
    // 전체 합계
    const grandTotal: MonthlyCell = { sales: 0, orders: 0 }
    for (const col of columns) {
      grandTotal.sales += colTotals[col].sales
      grandTotal.orders += colTotals[col].orders
    }
    // 월별 합계
    const monthTotals: Record<number, MonthlyCell> = {}
    for (let m = 1; m <= 12; m++) {
      monthTotals[m] = { sales: 0, orders: 0 }
      for (const col of columns) {
        const cell = data[m]?.[col]
        if (cell) {
          monthTotals[m].sales += cell.sales
          monthTotals[m].orders += cell.orders
        }
      }
    }

    return (
      <div style={{ ...card, padding: '1.25rem', marginBottom: '1.5rem' }}>
        <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#FF8C00', marginBottom: '1rem' }}>{title}</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: `${(columns.length + 2) * 120}px` }}>
            <thead>
              <tr>
                <th style={{ ...thStyle, position: 'sticky', left: 0, background: '#1A1A1A', zIndex: 1 }}></th>
                {columns.map(col => (
                  <th key={col} style={thStyle}>{col}</th>
                ))}
                <th style={{ ...thStyle, color: '#FF8C00', fontWeight: 700 }}>합계</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 12 }, (_, i) => i + 1).map(month => {
                const hasData = monthTotals[month].orders > 0
                return (
                  <tr key={month} style={{ background: hasData ? 'transparent' : 'rgba(40,50,40,0.15)' }}>
                    <td style={{ ...tdStyle, textAlign: 'center', fontWeight: 600, position: 'sticky', left: 0, background: hasData ? '#1E1E1E' : 'rgba(30,40,30,0.6)', zIndex: 1 }}>
                      {month}월
                    </td>
                    {columns.map(col => {
                      const cell = data[month]?.[col]
                      if (!cell || cell.orders === 0) {
                        return <td key={col} style={tdEmptyStyle}>-</td>
                      }
                      return (
                        <td key={col} style={tdStyle}>
                          <div>{fmt(cell.sales)}</div>
                          <div style={{ fontSize: '0.625rem', color: '#888' }}>({fmt(cell.orders)}건)</div>
                        </td>
                      )
                    })}
                    <td style={{ ...tdStyle, fontWeight: 700, color: '#FF8C00' }}>
                      {hasData ? (
                        <>
                          <div>{fmt(monthTotals[month].sales)}</div>
                          <div style={{ fontSize: '0.625rem', color: '#888' }}>({fmt(monthTotals[month].orders)}건)</div>
                        </>
                      ) : '-'}
                    </td>
                  </tr>
                )
              })}
              {/* 합계 행 */}
              <tr style={{ background: 'rgba(30,30,30,0.8)', borderTop: '2px solid #3D3D3D' }}>
                <td style={{ ...tdStyle, textAlign: 'center', fontWeight: 700, position: 'sticky', left: 0, background: '#1A1A1A', zIndex: 1, borderTop: '2px solid #3D3D3D' }}>
                  합계
                </td>
                {columns.map(col => {
                  const total = colTotals[col]
                  const pct = grandTotal.sales > 0 ? ((total.sales / grandTotal.sales) * 100).toFixed(1) : '0.0'
                  return (
                    <td key={col} style={{ ...tdStyle, fontWeight: 600, borderTop: '2px solid #3D3D3D' }}>
                      {total.orders > 0 ? (
                        <>
                          <div>{fmt(total.sales)}</div>
                          <div style={{ fontSize: '0.625rem', color: '#888' }}>({pct}%)</div>
                        </>
                      ) : '-'}
                    </td>
                  )
                })}
                <td style={{ ...tdStyle, fontWeight: 700, color: '#FF8C00', borderTop: '2px solid #3D3D3D' }}>
                  <div>{fmt(grandTotal.sales)}</div>
                  <div style={{ fontSize: '0.625rem', color: '#888' }}>({fmt(grandTotal.orders)}건)</div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '50vh', color: '#555' }}>로딩 중...</div>
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>매출통계</h2>
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
            총 <span style={{ color: '#FF8C00', fontWeight: 700 }}>{totalOrders}</span>건 · 매출 <span style={{ color: '#FF8C00', fontWeight: 700 }}>₩{totalSales.toLocaleString()}</span>
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

      {/* 마켓별 통계 */}
      {renderMonthlyTable('마켓별 통계', marketTable.columns, marketTable.data)}

      {/* 수집사이트별 통계 */}
      {renderMonthlyTable('수집사이트별 통계', siteTable.columns, siteTable.data)}

      {/* 주문상태별 통계 */}
      {renderMonthlyTable('주문상태별 통계', statusTable.columns, statusTable.data)}
    </div>
  )
}

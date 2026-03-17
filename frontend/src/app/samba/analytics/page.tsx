'use client'

import { useEffect, useState, useCallback } from 'react'
import { analyticsApi, type AnalyticsStats } from '@/lib/samba/api'

interface ChannelRow { channel_name: string; total_sales: number; total_orders: number; total_profit: number }
interface ProductRow { product_name: string; total_sales: number; total_orders: number; total_profit: number }
interface DailyRow { date: string; total_sales: number; total_orders: number; total_profit: number }

const EMPTY_STATS: AnalyticsStats = { total_sales: 0, total_orders: 0, total_profit: 0, avg_order_value: 0, profit_rate: 0 }

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

const STATUS_LABEL: Record<string, string> = {
  pending: '대기중', shipped: '배송중', delivered: '배송완료', cancelled: '취소됨', returned: '반품됨',
}

// 순수 CSS 가로 바 차트 컴포넌트
function BarChart({ data }: { data: DailyRow[] }) {
  if (data.length === 0) return <p style={{ color: '#555', fontSize: '0.875rem', padding: '1rem 0' }}>데이터가 없습니다</p>

  const maxSales = Math.max(...data.map(d => d.total_sales), 1)
  const last14 = data.slice(-14)

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', height: '140px', padding: '0 0.5rem' }}>
        {last14.map((d, i) => {
          const pct = (d.total_sales / maxSales) * 100
          return (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', height: '100%', justifyContent: 'flex-end' }}>
              <span style={{ fontSize: '0.625rem', color: '#555', whiteSpace: 'nowrap' }}>
                {d.total_sales > 0 ? `₩${(d.total_sales / 10000).toFixed(0)}만` : ''}
              </span>
              <div
                style={{
                  width: '100%',
                  height: `${Math.max(pct, d.total_sales > 0 ? 4 : 1)}%`,
                  background: d.total_sales > 0
                    ? `linear-gradient(to top, #FF8C00, rgba(255,140,0,0.4))`
                    : 'rgba(45,45,45,0.5)',
                  borderRadius: '3px 3px 0 0',
                  transition: 'height 0.3s ease',
                  minHeight: '2px',
                  cursor: 'default',
                  position: 'relative',
                }}
                title={`${d.date}: ₩${d.total_sales.toLocaleString()} / ${d.total_orders}건`}
              />
              <span style={{ fontSize: '0.5625rem', color: '#555', transform: 'rotate(-30deg)', transformOrigin: 'top center', whiteSpace: 'nowrap' }}>
                {d.date.slice(5)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  const [todayStats, setTodayStats] = useState<AnalyticsStats>(EMPTY_STATS)
  const [monthStats, setMonthStats] = useState<AnalyticsStats>(EMPTY_STATS)
  const [channels, setChannels] = useState<ChannelRow[]>([])
  const [products, setProducts] = useState<ProductRow[]>([])
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [orderStatus, setOrderStatus] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'channel' | 'product'>('channel')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const now = new Date()
      const startOfMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`
      const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`

      const [t, m, ch, pr, d, os] = await Promise.all([
        analyticsApi.today().catch(() => EMPTY_STATS),
        analyticsApi.range(startOfMonth, today).catch(() => EMPTY_STATS),
        analyticsApi.byChannel().catch(() => []),
        analyticsApi.byProduct().catch(() => []),
        analyticsApi.daily(30).catch(() => []),
        analyticsApi.orderStatus().catch(() => ({})),
      ])

      setTodayStats(t ?? EMPTY_STATS)
      setMonthStats(m ?? EMPTY_STATS)
      setChannels((ch as ChannelRow[]) ?? [])
      setProducts((pr as ProductRow[]) ?? [])
      setDaily((d as DailyRow[]) ?? [])
      setOrderStatus(os ?? {})
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '50vh', color: '#555' }}>로딩 중...</div>
  }

  const kpiItems = [
    { label: '오늘 매출', value: `₩${todayStats.total_sales.toLocaleString()}`, sub: `${todayStats.total_orders}건`, color: '#FF8C00' },
    { label: '오늘 수익', value: `₩${todayStats.total_profit.toLocaleString()}`, sub: `수익률 ${todayStats.profit_rate.toFixed(1)}%`, color: '#51CF66' },
    { label: '이번달 매출', value: `₩${monthStats.total_sales.toLocaleString()}`, sub: `${monthStats.total_orders}건`, color: '#4C9AFF' },
    { label: '이번달 수익', value: `₩${monthStats.total_profit.toLocaleString()}`, sub: `수익률 ${monthStats.profit_rate.toFixed(1)}%`, color: '#CC5DE8' },
  ]

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>매출통계</h2>
        <p style={{ fontSize: '0.875rem', color: '#888' }}>판매 현황과 수익성을 분석합니다</p>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        {kpiItems.map((kpi) => (
          <div key={kpi.label} style={{ ...card, padding: '1.25rem' }}>
            <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.5rem' }}>{kpi.label}</p>
            <p style={{ fontSize: '1.375rem', fontWeight: 700, color: kpi.color, marginBottom: '0.25rem' }}>{kpi.value}</p>
            <p style={{ fontSize: '0.75rem', color: '#555' }}>{kpi.sub}</p>
          </div>
        ))}
      </div>

      {/* Bar Chart - Daily Trend */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5' }}>일별 매출 추이 (최근 14일)</h3>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>최근 {daily.length}일 데이터</span>
        </div>
        <BarChart data={daily} />
      </div>

      {/* Order Status Distribution */}
      {Object.keys(orderStatus).length > 0 && (
        <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '1.25rem' }}>주문 상태 분포</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.75rem' }}>
            {Object.entries(orderStatus).map(([status, count]) => (
              <div key={status} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.875rem', textAlign: 'center' }}>
                <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.5rem' }}>{STATUS_LABEL[status] || status}</p>
                <p style={{ fontSize: '1.375rem', fontWeight: 700, color: '#FF8C00' }}>{count}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Channel / Product tabs */}
      <div style={{ ...card, padding: '1.5rem' }}>
        <div style={{ display: 'flex', gap: '0', borderBottom: '1px solid #2D2D2D', marginBottom: '1.25rem' }}>
          {(['channel', 'product'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{ padding: '0.625rem 1.25rem', background: 'none', border: 'none', borderBottom: activeTab === tab ? '2px solid #FF8C00' : '2px solid transparent', color: activeTab === tab ? '#FF8C00' : '#666', fontSize: '0.875rem', fontWeight: activeTab === tab ? 600 : 400, cursor: 'pointer', transition: 'all 0.2s', marginBottom: '-1px' }}
            >
              {tab === 'channel' ? '채널별 매출' : '상품별 매출'}
            </button>
          ))}
        </div>

        {activeTab === 'channel' ? (
          channels.length === 0 ? (
            <p style={{ color: '#555', fontSize: '0.875rem' }}>채널 데이터가 없습니다</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                  {['채널', '주문수', '매출', '수익'].map((h, i) => (
                    <th key={h} style={{ textAlign: i === 0 ? 'left' : 'right', padding: '0.625rem 1rem', color: '#888', fontWeight: 500, fontSize: '0.8125rem' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {channels.map((ch, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '0.75rem 1rem', color: '#FF8C00' }}>{ch.channel_name || '-'}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#888' }}>{ch.total_orders?.toLocaleString() ?? 0}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>₩{ch.total_sales?.toLocaleString() ?? 0}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#51CF66' }}>₩{ch.total_profit?.toLocaleString() ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        ) : (
          products.length === 0 ? (
            <p style={{ color: '#555', fontSize: '0.875rem' }}>상품 데이터가 없습니다</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                  {['상품명', '주문수', '매출', '수익'].map((h, i) => (
                    <th key={h} style={{ textAlign: i === 0 ? 'left' : 'right', padding: '0.625rem 1rem', color: '#888', fontWeight: 500, fontSize: '0.8125rem' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {products.map((pr, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <td style={{ padding: '0.75rem 1rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pr.product_name || '-'}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#888' }}>{pr.total_orders?.toLocaleString() ?? 0}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>₩{pr.total_sales?.toLocaleString() ?? 0}</td>
                    <td style={{ padding: '0.75rem 1rem', textAlign: 'right', color: '#51CF66' }}>₩{pr.total_profit?.toLocaleString() ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  )
}

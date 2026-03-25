"use client"

import { useEffect, useState, useCallback } from "react"
import { orderApi, collectorApi, type SambaOrder } from "@/lib/samba/api"

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

// 날짜 포맷: 3. 14. 형식
function formatShortDate(d: Date) {
  return `${d.getMonth() + 1}. ${d.getDate()}.`
}

export default function SambaDashboard() {
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [collectedCount, setCollectedCount] = useState(0)
  const [loading, setLoading] = useState(true)

  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  const load = useCallback(async () => {
    setLoading(true)
    // 대시보드는 최근 주문 20건 + 상품 카운트만 (빠른 로딩)
    const [o, counts] = await Promise.all([
      orderApi.list(0, 20).catch(() => []),
      collectorApi.productCounts().catch(() => ({ total: 0, registered: 0, policy_applied: 0, sold_out: 0 })),
    ])
    setOrders(o)
    setCollectedCount(counts.total)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // KPI 계산
  const totalSales = orders.reduce((s, o) => s + (o.sale_price || 0), 0)
  const thisMonthOrders = orders.filter(o => {
    const d = new Date(o.created_at)
    return d.getFullYear() === year && d.getMonth() === month
  })
  const thisMonthCount = thisMonthOrders.length
  const lastMonthOrders = orders.filter(o => {
    const d = new Date(o.created_at)
    const lm = month === 0 ? 11 : month - 1
    const ly = month === 0 ? year - 1 : year
    return d.getFullYear() === ly && d.getMonth() === lm
  })

  // 주문이행율 (배송완료 / 전체)
  const deliveredCount = thisMonthOrders.filter(o => o.status === 'delivered').length
  const fulfillmentRate = thisMonthCount > 0 ? Math.round((deliveredCount / thisMonthCount) * 100) : 100

  // 등록된 상품 수
  const registeredCount = 0 // 수집상품 중 registered_accounts가 있는 것

  // 최근 일주일 매출 데이터
  const weeklyData = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(now)
    d.setDate(now.getDate() - (6 - i))
    d.setHours(0, 0, 0, 0)
    const nextD = new Date(d)
    nextD.setDate(nextD.getDate() + 1)

    const dayOrders = orders.filter(o => {
      const od = new Date(o.created_at)
      return od >= d && od < nextD
    })
    const totalSale = dayOrders.reduce((s, o) => s + (o.sale_price || 0), 0)
    const deliveredSale = dayOrders.filter(o => o.status === 'delivered').reduce((s, o) => s + (o.sale_price || 0), 0)
    const rate = dayOrders.length > 0 ? Math.round((dayOrders.filter(o => o.status === 'delivered').length / dayOrders.length) * 100) : 0

    return { date: d, totalSale, deliveredSale, rate }
  })

  // 금월/전월 비교
  const thisMonthSales = thisMonthOrders.reduce((s, o) => s + (o.sale_price || 0), 0)
  const thisMonthDeliveredSales = thisMonthOrders.filter(o => o.status === 'delivered').reduce((s, o) => s + (o.sale_price || 0), 0)
  const thisMonthFulfillment = thisMonthCount > 0 ? Math.round((deliveredCount / thisMonthCount) * 100) : 0

  const lastMonthSales = lastMonthOrders.reduce((s, o) => s + (o.sale_price || 0), 0)
  const lastMonthDelivered = lastMonthOrders.filter(o => o.status === 'delivered')
  const lastMonthDeliveredSales = lastMonthDelivered.reduce((s, o) => s + (o.sale_price || 0), 0)
  const lastMonthFulfillment = lastMonthOrders.length > 0 ? Math.round((lastMonthDelivered.length / lastMonthOrders.length) * 100) : 0

  // 전월대비 증감
  const salesChange = lastMonthSales > 0 ? (((thisMonthSales - lastMonthSales) / lastMonthSales) * 100).toFixed(1) : '0'

  if (loading && orders.length === 0) {
    return <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: '2rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>대시보드</h2>
          <p style={{ fontSize: '0.8125rem', color: '#888' }}>{year}년 · 누적 현황</p>
        </div>
        <p style={{ fontSize: '0.875rem', color: '#888' }}>{year}년 {month + 1}월 {now.getDate()}일</p>
      </div>

      {/* KPI 카드 4개 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>총 매출 (누적)</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>₩{totalSales.toLocaleString()}</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>{orders.length.toLocaleString()}건</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>이번 달 주문</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>{thisMonthCount}건</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>{month + 1}월 기준 · {Number(salesChange) >= 0 ? '▲' : '▼'}{Math.abs(Number(salesChange))}%</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>수집상품</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>{collectedCount}개</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>등록된 상품</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>주문이행율</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>{fulfillmentRate}%</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>이번 달 기준</p>
        </div>
      </div>

      {/* 최근 일주일 매출 + 금월/전월 비교 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
        {/* 최근 일주일 매출 */}
        <div style={{ ...card, padding: '1.5rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>최근 일주일 매출</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ textAlign: 'left', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>날짜</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>총매출</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>이행매출</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>주문이행율</th>
              </tr>
            </thead>
            <tbody>
              {weeklyData.map((d) => (
                <tr key={d.date.toISOString()} style={{ borderBottom: '1px solid rgba(45,45,45,0.3)' }}>
                  <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>{formatShortDate(d.date)}</td>
                  <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{d.totalSale.toLocaleString()}</td>
                  <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{d.deliveredSale.toLocaleString()}</td>
                  <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>{d.rate}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 금월/전월 비교 */}
        <div style={{ ...card, padding: '1.5rem' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>금월 / 전월 비교</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ textAlign: 'left', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>구분</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>총매출</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>이행매출</th>
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>주문이행율</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid rgba(45,45,45,0.3)' }}>
                <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>금월</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{thisMonthSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{thisMonthDeliveredSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>{thisMonthFulfillment}%</td>
              </tr>
              <tr>
                <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>전월</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{lastMonthSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{lastMonthDeliveredSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>{lastMonthFulfillment}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* 월별 매출 추이 */}
      <div style={{ ...card, padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <div>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>월별 매출 추이</h3>
            <p style={{ fontSize: '0.75rem', color: '#888' }}>{year}년 마켓별 월간 매출액</p>
          </div>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: '#888' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#FF8C00' }} /> 전체매출
            </span>
          </div>
        </div>
        {/* 간이 바 차트 */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.5rem', height: '160px', paddingTop: '1rem' }}>
          {(() => {
            const monthlySales = Array.from({ length: 12 }, (_, j) =>
              orders.filter(o => { const d = new Date(o.created_at); return d.getFullYear() === year && d.getMonth() === j })
                .reduce((s, o) => s + (o.sale_price || 0), 0)
            )
            const maxSales = Math.max(...monthlySales, 1)
            return monthlySales.map((monthSales, i) => {
            const heightPct = (monthSales / maxSales) * 100

            return (
              <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.375rem' }}>
                {monthSales > 0 && (
                  <span style={{ fontSize: '0.625rem', color: '#888' }}>₩{(monthSales / 1000).toFixed(0)}K</span>
                )}
                <div style={{ width: '100%', background: i === month ? '#FF8C00' : 'rgba(255,140,0,0.3)', borderRadius: '4px 4px 0 0', height: `${Math.max(heightPct, 2)}%`, minHeight: '2px', transition: 'height 0.3s' }} />
                <span style={{ fontSize: '0.6875rem', color: i === month ? '#FF8C00' : '#666' }}>{i + 1}월</span>
              </div>
            )
          })
          })()}
        </div>
      </div>

    </div>
  )
}

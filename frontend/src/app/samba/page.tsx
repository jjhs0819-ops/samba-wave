"use client"

import { useEffect, useState, useCallback } from "react"
import { orderApi, collectorApi, type DashboardStats } from "@/lib/samba/api"

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
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [collectedCount, setCollectedCount] = useState(0)
  const [loading, setLoading] = useState(true)

  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth()

  const load = useCallback(async () => {
    setLoading(true)
    const [s, counts] = await Promise.all([
      orderApi.dashboardStats().catch(() => null),
      collectorApi.productCounts().catch(() => ({ total: 0, registered: 0, policy_applied: 0, sold_out: 0 })),
    ])
    setStats(s)
    setCollectedCount(counts.total)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // 집계 데이터에서 KPI 추출
  const thisMonthSales = stats?.thisMonth.sales || 0
  const thisMonthCount = stats?.thisMonth.count || 0
  const thisMonthFulfillmentSales = stats?.thisMonth.fulfillmentSales || 0
  const thisMonthFulfillment = thisMonthSales > 0 ? Math.round(thisMonthFulfillmentSales / thisMonthSales * 100) : 0
  const lastMonthSales = stats?.lastMonth.sales || 0
  const lastMonthFulfillmentSales = stats?.lastMonth.fulfillmentSales || 0
  const lastMonthFulfillment = lastMonthSales > 0 ? Math.round(lastMonthFulfillmentSales / lastMonthSales * 100) : 0
  const salesChange = stats?.salesChange || 0
  const weeklyData = (stats?.weekly || []).map(w => ({
    date: new Date(w.date),
    totalSale: w.sales,
    fulfillmentSale: w.fulfillmentSales,
    rate: w.sales > 0 ? Math.round(w.fulfillmentSales / w.sales * 100) : 0,
  }))
  const monthlyData = stats?.monthly || []

  if (loading && !stats) {
    return <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
  }

  // 선 그래프 렌더링
  const renderLineChart = () => {
    const W = 720
    const H = 180
    const padL = 45
    const padR = 20
    const padT = 20
    const padB = 30
    const chartW = W - padL - padR
    const chartH = H - padT - padB

    const allValues = monthlyData.flatMap(d => [d.sales, d.fulfillmentSales])
    const maxVal = Math.max(...allValues, 1000)
    // Y축 눈금 계산 (천원 단위)
    const maxK = Math.ceil(maxVal / 1000)
    const step = maxK <= 5 ? 1 : maxK <= 20 ? 5 : maxK <= 100 ? 20 : maxK <= 500 ? 100 : Math.ceil(maxK / 5 / 100) * 100
    const yMax = Math.ceil(maxK / step) * step
    const gridLines = []
    for (let v = 0; v <= yMax; v += step) gridLines.push(v)

    const getX = (i: number) => padL + (i / 11) * chartW
    const getY = (v: number) => padT + chartH - (v / 1000 / yMax) * chartH

    // 총매출 선
    const totalPoints = monthlyData.map((d, i) => `${getX(i)},${getY(d.sales)}`).join(' ')
    // 이행매출 선
    const fulfillmentPoints = monthlyData.map((d, i) => `${getX(i)},${getY(d.fulfillmentSales)}`).join(' ')

    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible' }}>
        {/* Y축 눈금선 + 라벨 */}
        {gridLines.map(v => {
          const y = padT + chartH - (v / yMax) * chartH
          return (
            <g key={v}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="#2D2D2D" strokeWidth={1} />
              <text x={padL - 6} y={y + 4} textAnchor="end" fill="#666" fontSize="10">{v.toLocaleString()}</text>
            </g>
          )
        })}
        {/* X축 라벨 */}
        {monthlyData.map((_, i) => (
          <text key={i} x={getX(i)} y={H - 5} textAnchor="middle" fill={i === month ? '#FF8C00' : '#666'} fontSize="11" fontWeight={i === month ? 700 : 400}>{i + 1}월</text>
        ))}
        {/* 총매출 선 */}
        <polyline points={totalPoints} fill="none" stroke="rgba(255,140,0,0.4)" strokeWidth={2} />
        {/* 이행매출 선 */}
        <polyline points={fulfillmentPoints} fill="none" stroke="#FF8C00" strokeWidth={2} />
        {/* 총매출 점 + 값 */}
        {monthlyData.map((d, i) => {
          const x = getX(i)
          const y = getY(d.sales)
          const kVal = Math.round(d.sales / 1000)
          return (
            <g key={`t-${i}`}>
              <circle cx={x} cy={y} r={3} fill="rgba(255,140,0,0.4)" />
              {kVal > 0 && <text x={x} y={y - 10} textAnchor="middle" fill="#888" fontSize="9">{kVal.toLocaleString()}</text>}
            </g>
          )
        })}
        {/* 이행매출 점 + 값 */}
        {monthlyData.map((d, i) => {
          const x = getX(i)
          const y = getY(d.fulfillmentSales)
          const kVal = Math.round(d.fulfillmentSales / 1000)
          return (
            <g key={`f-${i}`}>
              <circle cx={x} cy={y} r={3} fill="#FF8C00" />
              {kVal > 0 && <text x={x} y={y - 10} textAnchor="middle" fill="#FF8C00" fontSize="9" fontWeight={600}>{kVal.toLocaleString()}</text>}
            </g>
          )
        })}
      </svg>
    )
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
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>총 매출 (금월)</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>₩{thisMonthSales.toLocaleString()}</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>{thisMonthCount.toLocaleString()}건</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>이행매출 (금월)</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>₩{thisMonthFulfillmentSales.toLocaleString()}</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>{month + 1}월 기준 · {Number(salesChange) >= 0 ? '▲' : '▼'}{Math.abs(Number(salesChange))}%</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>수집상품</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>{collectedCount.toLocaleString()}개</p>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginTop: '0.5rem' }}>등록된 상품</p>
        </div>
        <div style={{ ...card, padding: '1.5rem', borderColor: 'rgba(255,140,0,0.25)' }}>
          <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '0.5rem' }}>주문이행율</p>
          <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FF8C00' }}>{thisMonthFulfillment}%</p>
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
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>이행율</th>
              </tr>
            </thead>
            <tbody>
              {weeklyData.map((d) => (
                <tr key={d.date.toISOString()} style={{ borderBottom: '1px solid rgba(45,45,45,0.3)' }}>
                  <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>{formatShortDate(d.date)}</td>
                  <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{d.totalSale.toLocaleString()}</td>
                  <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{d.fulfillmentSale.toLocaleString()}</td>
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
                <th style={{ textAlign: 'right', padding: '0.625rem 0', color: '#888', fontWeight: 500 }}>이행율</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid rgba(45,45,45,0.3)' }}>
                <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>금월</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{thisMonthSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{thisMonthFulfillmentSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>{thisMonthFulfillment}%</td>
              </tr>
              <tr>
                <td style={{ padding: '0.625rem 0', color: '#E5E5E5' }}>전월</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{lastMonthSales.toLocaleString()}</td>
                <td style={{ padding: '0.625rem 0', textAlign: 'right', color: '#E5E5E5' }}>₩{lastMonthFulfillmentSales.toLocaleString()}</td>
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
            <p style={{ fontSize: '0.75rem', color: '#888' }}>{year}년 월간 매출액 (단위: 천원)</p>
          </div>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: '#888' }}>
              <span style={{ width: '12px', height: '2px', background: 'rgba(255,140,0,0.4)' }} /> 총매출
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.75rem', color: '#FF8C00' }}>
              <span style={{ width: '12px', height: '2px', background: '#FF8C00' }} /> 이행매출
            </span>
          </div>
        </div>
        {renderLineChart()}
      </div>

    </div>
  )
}

'use client'

import { Tooltip, ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, BarChart, Bar, Legend } from 'recharts'
import { fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'

interface ChartProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>[]
  height?: number
}

// 매출 추이 라인차트
export function RevenueTrendLine({ data, height = 280 }: ChartProps) {
  // 훅은 early return 앞에서 호출 — React 훅 규칙
  const c = useTheme()
  if (!data.length) return <p style={{ color: c.textMuted, fontSize: '0.8rem' }}>데이터 없음</p>

  const formatted = data.map(d => ({
    date: (d.date || d.month || '').slice(-5),
    sales: d.sales || 0,
    profit: d.profit || 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={formatted}>
        <CartesianGrid strokeDasharray="3 3" stroke={c.border} />
        <XAxis dataKey="date" tick={{ fill: c.textSub, fontSize: 11 }} />
        <YAxis tick={{ fill: c.textSub, fontSize: 11 }} tickFormatter={v => `${Math.round(v / 10000)}만`} />
        <Tooltip formatter={(v) => `${fmtNum(Number(v))}원`} contentStyle={{ background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: 6 }} labelStyle={{ color: c.textSub }} />
        <Legend />
        <Line type="monotone" dataKey="sales" name="매출" stroke="#FF8C00" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="profit" name="이익" stroke="#22C55E" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

// 브랜드/소싱처 매출 바차트
export function SalesBarChart({ data, height = 280, nameKey = 'name', valueKey = 'sales' }: ChartProps & { nameKey?: string; valueKey?: string }) {
  // 훅은 early return 앞에서 호출 — React 훅 규칙
  const c = useTheme()
  if (!data.length) return <p style={{ color: c.textMuted, fontSize: '0.8rem' }}>데이터 없음</p>

  const formatted = data.slice(0, 10).map(d => ({
    name: (d[nameKey] || '미분류').slice(0, 12),
    value: d[valueKey] || 0,
    profit: d.profit || 0,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={formatted} layout="vertical">
        <CartesianGrid strokeDasharray="3 3" stroke={c.border} />
        <XAxis type="number" tick={{ fill: c.textSub, fontSize: 11 }} tickFormatter={v => `${Math.round(v / 10000)}만`} />
        <YAxis type="category" dataKey="name" tick={{ fill: c.text, fontSize: 11 }} width={100} />
        <Tooltip formatter={(v) => `${fmtNum(Number(v))}원`} contentStyle={{ background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: 6 }} labelStyle={{ color: c.textSub }} />
        <Bar dataKey="value" name="매출" fill="#FF8C00" radius={[0, 4, 4, 0]} />
        <Bar dataKey="profit" name="이익" fill="#22C55E" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

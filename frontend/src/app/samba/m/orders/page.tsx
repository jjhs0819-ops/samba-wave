'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { orderApi, type SambaOrder } from '@/lib/samba/api/commerce'
import { sourcingAccountApi, type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { fetchWithAuth, SAMBA_PREFIX } from '@/lib/samba/legacy'
import { useTheme } from '@/lib/samba/useTheme'
import { fmtNum } from '@/lib/samba/styles'
import MobileOrderCard from './MobileOrderCard'

/** 모바일에서 다루는 상태는 2개뿐 — 처리해야 할 것과 처리한 것 */
const TABS = [
  { key: 'pending', label: '신규주문' },
  { key: 'wait_ship', label: '배송대기' },
] as const

type TabKey = (typeof TABS)[number]['key']

interface OfficeShipping {
  name: string
  phone: string
  address: string
  address_detail: string
}

export default function MobileOrdersPage() {
  const c = useTheme()
  const [tab, setTab] = useState<TabKey>('pending')
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [accounts, setAccounts] = useState<SambaSourcingAccount[]>([])
  const [officePhone, setOfficePhone] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => { document.title = 'SAMBA-모바일 주문처리' }, [])

  const loadOrders = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const rows = await orderApi.list(0, 200, tab)
      setOrders(rows)
    } catch (e) {
      setError(e instanceof Error ? e.message : '주문 조회 실패')
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => { loadOrders() }, [loadOrders])

  // 소싱계정 + 사무실 배송정보는 1회만
  useEffect(() => {
    sourcingAccountApi.list()
      .then((rows) => {
        const order: Record<string, number> = { MUSINSA: 0, LOTTEON: 1, SSG: 2 }
        setAccounts(
          [...rows].sort(
            (a, b) =>
              (order[a.site_name] ?? 99) - (order[b.site_name] ?? 99) ||
              a.site_name.localeCompare(b.site_name),
          ),
        )
      })
      .catch(() => setAccounts([]))

    fetchWithAuth(`${SAMBA_PREFIX}/proxy/config/office-shipping`)
      .then((res) => (res.ok ? res.json() : null))
      .then((office: OfficeShipping | null) => setOfficePhone(office?.phone || ''))
      .catch(() => setOfficePhone(''))
  }, [])

  const patchOrder = useCallback((id: string, data: Partial<SambaOrder>) => {
    setOrders((prev) => prev.map((o) => (o.id === id ? { ...o, ...data } : o)))
  }, [])

  return (
    <div style={{ background: c.pageBg, color: c.text, minHeight: '100dvh', padding: '0.75rem', paddingBottom: '2rem' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.625rem' }}>
        <div style={{ fontSize: '1.125rem', fontWeight: 700 }}>
          주문처리 <span style={{ color: c.textMuted, fontSize: '0.875rem', fontWeight: 500 }}>{fmtNum(orders.length)}건</span>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            onClick={loadOrders}
            style={{ padding: '0.375rem 0.75rem', borderRadius: '8px', border: `1px solid ${c.btnBorder}`, background: c.btnBg, color: c.btnText, fontSize: '0.875rem' }}
          >
            새로고침
          </button>
          <Link
            href="/samba/orders"
            style={{ padding: '0.375rem 0.75rem', borderRadius: '8px', border: `1px solid ${c.btnBorder}`, background: c.btnBg, color: c.btnText, fontSize: '0.875rem' }}
          >
            PC화면
          </Link>
        </div>
      </div>

      {/* 탭 */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
        {TABS.map((t) => {
          const on = tab === t.key
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                flex: 1,
                padding: '0.625rem',
                borderRadius: '8px',
                border: `1px solid ${on ? c.primary : c.chipNeutralBorder}`,
                background: on ? c.primary : c.chipNeutralBg,
                color: on ? '#fff' : c.chipNeutralText,
                fontSize: '0.9375rem',
                fontWeight: 700,
              }}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      {!officePhone && (
        <div style={{ padding: '0.625rem', marginBottom: '0.75rem', borderRadius: '8px', background: c.accentBg, color: c.text, fontSize: '0.8125rem' }}>
          설정 &gt; 사무실 배송정보에 전화번호가 없습니다. 수령인 연락처가 비어 자동입력이 막힙니다.
        </div>
      )}

      {error && (
        <div style={{ padding: '0.625rem', marginBottom: '0.75rem', borderRadius: '8px', background: c.danger, color: '#fff', fontSize: '0.8125rem' }}>
          {error}
        </div>
      )}

      {loading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: c.textMuted }}>불러오는 중...</div>
      ) : orders.length === 0 ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: c.textMuted }}>처리할 주문이 없습니다</div>
      ) : (
        orders.map((o) => (
          <MobileOrderCard
            key={o.id}
            order={o}
            c={c}
            sourcingAccounts={accounts}
            officePhone={officePhone}
            onPatch={patchOrder}
          />
        ))
      )}
    </div>
  )
}

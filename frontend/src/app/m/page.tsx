'use client'

// 폰 전용 간편 주문 뷰 — 아이디/비번 로그인(기존 JWT 재사용) 후 최근 주문 카드형 표시.
// 기존 orderApi/userApi/useTheme 그대로 사용. 백엔드/DB 변경 없음.

import { useCallback, useEffect, useState } from 'react'
import { userApi } from '@/lib/samba/api/operations'
import { orderApi } from '@/lib/samba/api/commerce'
import type { SambaOrder } from '@/lib/samba/api/commerce'
import { useTheme } from '@/lib/samba/useTheme'
import { STORAGE_KEYS } from '@/lib/samba/constants'
import { fmtNum } from '@/lib/samba/styles'

// KST 기준 'YYYY-MM-DD' (sv-SE 로케일이 ISO 포맷 반환)
const kstDate = (offsetDays = 0): string => {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' })
}

// KST 결제일시 표기 (paid_at 없으면 created_at 폴백)
const fmtKst = (iso?: string): string => {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 마켓명: 판매채널별칭 → 채널명 → source
const marketOf = (o: SambaOrder): string =>
  o.sales_channel_alias || o.channel_name || o.source || o.source_site || '-'

// 결제금액: 고객결제금액 우선, 없으면 판매가
const amountOf = (o: SambaOrder): number =>
  o.total_payment_amount != null ? o.total_payment_amount : o.sale_price

// 미발송 판정: 송장 없음 + 취소 아님
const isUnshipped = (o: SambaOrder): boolean => {
  const st = (o.status || '').toLowerCase()
  const cancelled = /취소|cancel|refund|반품/.test(st)
  return !o.tracking_number && !cancelled
}

type RangeKey = 'today' | '7d' | '30d'
const RANGE_DAYS: Record<RangeKey, number> = { today: 0, '7d': 6, '30d': 29 }

export default function SambaMobileOrdersPage() {
  const c = useTheme()

  const [ready, setReady] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)

  // 로그인 폼
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 주문 데이터
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [totalSale, setTotalSale] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [tab, setTab] = useState<'all' | 'unshipped'>('all')
  const [range, setRange] = useState<RangeKey>('7d')

  const loadOrders = useCallback(async (r: RangeKey) => {
    setLoading(true)
    setLoadError('')
    try {
      const start = kstDate(-RANGE_DAYS[r])
      const end = kstDate(0)
      const res = await orderApi.listByDateRangePaged({
        start,
        end,
        skip: 0,
        limit: 200,
        sort_by: 'date_desc',
      })
      setOrders(res.items || [])
      setTotalCount(res.total_count || 0)
      setTotalSale(res.total_sale || 0)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '주문을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [])

  // 최초 진입 — 로그인 상태 확인
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEYS.SAMBA_USER)
      const user = raw ? JSON.parse(raw) : null
      if (user?.access_token || user?.token) {
        setLoggedIn(true)
      }
    } catch {
      // 무시 — 로그인 폼 노출
    }
    setReady(true)
  }, [])

  // 로그인되면 주문 로드
  useEffect(() => {
    if (loggedIn) loadOrders(range)
  }, [loggedIn, range, loadOrders])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoginError('')
    if (!email.trim() || !password.trim()) {
      setLoginError('아이디와 비밀번호를 입력해주세요')
      return
    }
    setSubmitting(true)
    try {
      const user = await userApi.login(email.trim(), password)
      const token = user.access_token || user.token
      if (!token) {
        setLoginError('로그인 응답에 토큰이 없습니다')
        return
      }
      localStorage.setItem('samba_token', token)
      document.cookie = `samba_user=${token}; path=/; max-age=${60 * 60 * 24 * 30}; SameSite=Lax`
      localStorage.setItem(STORAGE_KEYS.SAMBA_USER, JSON.stringify(user))
      setLoggedIn(true)
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : '로그인에 실패했습니다')
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_KEYS.SAMBA_USER)
    localStorage.removeItem('samba_token')
    document.cookie = 'samba_user=; path=/; max-age=0'
    setLoggedIn(false)
    setOrders([])
    setEmail('')
    setPassword('')
  }

  const shown = tab === 'unshipped' ? orders.filter(isUnshipped) : orders
  const unshippedCount = orders.filter(isUnshipped).length

  // ── 로딩 게이트 ──
  if (!ready) {
    return (
      <div style={{ minHeight: '100vh', background: c.pageBg }} />
    )
  }

  // ── 로그인 폼 ──
  if (!loggedIn) {
    return (
      <div
        style={{
          minHeight: '100vh',
          background: c.pageBg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '1.25rem',
        }}
      >
        <form
          onSubmit={handleLogin}
          style={{
            width: '100%',
            maxWidth: 380,
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: 16,
            padding: '1.75rem 1.25rem',
          }}
        >
          <h1 style={{ margin: 0, marginBottom: 4, fontSize: 20, fontWeight: 700, color: c.text }}>
            삼바 주문 보기
          </h1>
          <p style={{ margin: 0, marginBottom: 18, fontSize: 13, color: c.textMuted }}>
            아이디(이메일)와 비밀번호로 로그인
          </p>

          <input
            type="email"
            inputMode="email"
            autoComplete="username"
            placeholder="이메일"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              width: '100%',
              padding: '0.85rem 0.9rem',
              marginBottom: 10,
              fontSize: 16,
              background: c.inputBg,
              color: c.text,
              border: `1px solid ${c.border}`,
              borderRadius: 10,
              outline: 'none',
            }}
          />
          <input
            type="password"
            autoComplete="current-password"
            placeholder="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{
              width: '100%',
              padding: '0.85rem 0.9rem',
              marginBottom: 12,
              fontSize: 16,
              background: c.inputBg,
              color: c.text,
              border: `1px solid ${c.border}`,
              borderRadius: 10,
              outline: 'none',
            }}
          />

          {loginError && (
            <div style={{ marginBottom: 12, fontSize: 13, color: c.danger }}>{loginError}</div>
          )}

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: '100%',
              padding: '0.9rem',
              fontSize: 16,
              fontWeight: 700,
              background: c.btnSolidBg,
              color: c.btnSolidText,
              border: 'none',
              borderRadius: 10,
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? '로그인 중…' : '로그인'}
          </button>
        </form>
      </div>
    )
  }

  // ── 주문 화면 ──
  const rangeLabel: Record<RangeKey, string> = { today: '오늘', '7d': '7일', '30d': '30일' }

  return (
    <div style={{ minHeight: '100vh', background: c.pageBg, color: c.text }}>
      {/* 상단 고정 바 */}
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          background: c.surface,
          borderBottom: `1px solid ${c.border}`,
          padding: '0.65rem 0.85rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>삼바 주문</span>
          <button
            onClick={handleLogout}
            style={{
              fontSize: 12,
              padding: '0.3rem 0.6rem',
              background: c.btnBg,
              color: c.btnText,
              border: `1px solid ${c.btnBorder}`,
              borderRadius: 8,
            }}
          >
            로그아웃
          </button>
        </div>

        {/* 기간 선택 */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {(Object.keys(RANGE_DAYS) as RangeKey[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              style={{
                flex: 1,
                fontSize: 13,
                padding: '0.4rem 0',
                background: range === r ? c.btnSolidBg : c.btnBg,
                color: range === r ? c.btnSolidText : c.btnText,
                border: `1px solid ${range === r ? c.btnSolidBg : c.btnBorder}`,
                borderRadius: 8,
                fontWeight: range === r ? 700 : 400,
              }}
            >
              {rangeLabel[r]}
            </button>
          ))}
          <button
            onClick={() => loadOrders(range)}
            style={{
              fontSize: 13,
              padding: '0.4rem 0.7rem',
              background: c.btnBg,
              color: c.btnText,
              border: `1px solid ${c.btnBorder}`,
              borderRadius: 8,
            }}
          >
            새로고침
          </button>
        </div>

        {/* 탭 */}
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={() => setTab('all')}
            style={{
              flex: 1,
              fontSize: 13,
              padding: '0.45rem 0',
              background: tab === 'all' ? c.accentBg : c.btnBg,
              color: c.btnText,
              border: `1px solid ${c.btnBorder}`,
              borderRadius: 8,
              fontWeight: tab === 'all' ? 700 : 400,
            }}
          >
            전체 {fmtNum(orders.length)}
          </button>
          <button
            onClick={() => setTab('unshipped')}
            style={{
              flex: 1,
              fontSize: 13,
              padding: '0.45rem 0',
              background: tab === 'unshipped' ? c.accentBg : c.btnBg,
              color: c.btnText,
              border: `1px solid ${c.btnBorder}`,
              borderRadius: 8,
              fontWeight: tab === 'unshipped' ? 700 : 400,
            }}
          >
            미발송 {fmtNum(unshippedCount)}
          </button>
        </div>
      </div>

      {/* 요약 */}
      <div style={{ padding: '0.6rem 0.85rem', fontSize: 12, color: c.textSub }}>
        기간 총 {fmtNum(totalCount)}건 · 매출 {fmtNum(Math.round(totalSale))}원
      </div>

      {/* 상태 메시지 */}
      {loading && (
        <div style={{ padding: '1.5rem 0.85rem', textAlign: 'center', color: c.textMuted }}>
          불러오는 중…
        </div>
      )}
      {loadError && !loading && (
        <div style={{ padding: '1.5rem 0.85rem', textAlign: 'center', color: c.danger }}>
          {loadError}
        </div>
      )}
      {!loading && !loadError && shown.length === 0 && (
        <div style={{ padding: '2rem 0.85rem', textAlign: 'center', color: c.textMuted }}>
          표시할 주문이 없습니다
        </div>
      )}

      {/* 카드 목록 */}
      <div style={{ padding: '0 0.85rem 2rem' }}>
        {shown.map((o) => {
          const unship = isUnshipped(o)
          return (
            <div
              key={o.id}
              style={{
                background: c.surface,
                border: `1px solid ${c.border}`,
                borderRadius: 12,
                padding: '0.75rem 0.8rem',
                marginBottom: 10,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 12, color: c.textMuted }}>{fmtKst(o.paid_at || o.created_at)}</span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    padding: '0.15rem 0.5rem',
                    borderRadius: 999,
                    background: unship ? c.accentBg : c.surfaceAlt,
                    color: unship ? c.warn : c.success,
                  }}
                >
                  {unship ? '미발송' : '발송'}
                </span>
              </div>

              <div style={{ fontSize: 12, color: c.link, fontWeight: 600, marginBottom: 2 }}>
                {marketOf(o)}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.35, marginBottom: 2 }}>
                {o.product_name || '(상품명 없음)'}
              </div>
              {o.product_option && (
                <div style={{ fontSize: 12, color: c.textSub, marginBottom: 4 }}>
                  옵션: {o.product_option}
                </div>
              )}

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginTop: 6,
                  paddingTop: 6,
                  borderTop: `1px solid ${c.border}`,
                }}
              >
                <span style={{ fontSize: 12, color: c.textSub }}>
                  {o.customer_name || '-'} · 수량 {fmtNum(o.quantity)}
                </span>
                <span style={{ fontSize: 15, fontWeight: 700 }}>
                  {fmtNum(Math.round(amountOf(o)))}원
                </span>
              </div>

              <div style={{ fontSize: 11, color: c.textMuted, marginTop: 4 }}>
                주문 {o.order_number}
                {o.tracking_number ? ` · 송장 ${o.shipping_company || ''} ${o.tracking_number}` : ''}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

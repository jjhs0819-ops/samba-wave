'use client'

// 폰 전용 간편 주문 뷰 — 아이디/비번 로그인(기존 JWT 재사용) 후 최근 주문 카드형 표시.
// 기존 orderApi/userApi/useTheme 그대로 사용. 백엔드/DB 변경 없음.

import { useCallback, useEffect, useMemo, useState } from 'react'
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

// 발주번호(소싱처 주문번호) 입력 여부
const hasOrderNo = (o: SambaOrder): boolean =>
  !!(o.sourcing_order_number && o.sourcing_order_number.trim())

// 발송/미발송/취소 판정 — 백엔드 기준(order/model.py)과 일치
// 발송키워드(shipping_status 한글 원본) + 취소/반품/교환 제외 상태
const SHIPPED_KEYWORDS = ['배송중', '배송완료', '구매확정', '국내배송중', '송장전송완료']
const EXCLUDED_STATUSES = [
  'cancel_requested', 'cancelling', 'cancelled',
  'return_requested', 'returning', 'returned', 'return_completed',
  'exchange_requested', 'exchanging', 'exchanged', 'exchange_pending', 'exchange_done',
  'ship_failed', 'undeliverable',
]

// 취소/반품/교환 등 집계 제외 상태
const isCancelled = (o: SambaOrder): boolean => {
  const st = (o.status || '').toLowerCase()
  if (EXCLUDED_STATUSES.includes(st)) return true
  const ss = o.shipping_status || ''
  return /취소|반품|교환/.test(ss)
}

// 발송됨: 송장 있음 또는 배송키워드 + 취소류 아님
const isShipped = (o: SambaOrder): boolean => {
  if (isCancelled(o)) return false
  const hasTrk = !!(o.tracking_number && o.tracking_number.trim())
  const ss = o.shipping_status || ''
  const kw = SHIPPED_KEYWORDS.some((k) => ss.includes(k))
  return hasTrk || kw
}

// 미발송: 취소류도 발송도 아님 (아직 배송 전)
const isUnshipped = (o: SambaOrder): boolean => !isCancelled(o) && !isShipped(o)

type RangeKey = 'today' | 'yesterday' | '7d'
// 각 기간의 시작/끝 날짜 오프셋 (KST 기준, 0=오늘, -1=어제)
const RANGE_OFFSET: Record<RangeKey, { start: number; end: number }> = {
  today: { start: 0, end: 0 },
  yesterday: { start: -1, end: -1 },
  '7d': { start: -6, end: 0 },
}

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
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [tab, setTab] = useState<'all' | 'unshipped'>('all')
  const [range, setRange] = useState<RangeKey>('today')
  const [market, setMarket] = useState<string>('') // '' = 전체 판매처
  const [orderInput, setOrderInput] = useState<'all' | 'has' | 'none'>('all') // 발주번호 입력 여부

  const loadOrders = useCallback(async (r: RangeKey) => {
    setLoading(true)
    setLoadError('')
    try {
      const start = kstDate(RANGE_OFFSET[r].start)
      const end = kstDate(RANGE_OFFSET[r].end)
      const res = await orderApi.listByDateRangePaged({
        start,
        end,
        skip: 0,
        limit: 200,
        sort_by: 'date_desc',
      })
      setOrders(res.items || [])
      setTotalCount(res.total_count || 0)
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

  // 로드된 주문에서 판매처 목록 추출 (건수순 정렬)
  const marketList = useMemo(() => {
    const counts = new Map<string, number>()
    for (const o of orders) {
      const m = marketOf(o)
      counts.set(m, (counts.get(m) || 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [orders])

  // 선택 판매처가 목록에 없으면 전체로 간주
  const activeMarket = marketList.some(([m]) => m === market) ? market : ''

  const shown = orders
    .filter((o) => (tab === 'unshipped' ? isUnshipped(o) : true))
    .filter((o) => (activeMarket ? marketOf(o) === activeMarket : true))
    .filter((o) =>
      orderInput === 'all' ? true : orderInput === 'has' ? hasOrderNo(o) : !hasOrderNo(o),
    )
  const unshippedCount = orders.filter(isUnshipped).length
  // 표시(필터 적용)된 주문 기준 매출 합계
  const shownSale = shown.reduce((s, o) => s + (amountOf(o) || 0), 0)

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
  const rangeLabel: Record<RangeKey, string> = { today: '오늘', yesterday: '어제', '7d': '7일' }

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
          <img src="/logo.png" alt="삼바" style={{ height: 26, width: 'auto' }} />
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
          {(Object.keys(RANGE_OFFSET) as RangeKey[]).map((r) => (
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

        {/* 판매처 필터 */}
        <select
          value={activeMarket}
          onChange={(e) => setMarket(e.target.value)}
          style={{
            width: '100%',
            marginTop: 8,
            padding: '0.5rem 0.6rem',
            fontSize: 14,
            background: c.inputBg,
            color: c.text,
            border: `1px solid ${c.border}`,
            borderRadius: 8,
            outline: 'none',
          }}
        >
          <option value="">전체 판매처 ({fmtNum(orders.length)})</option>
          {marketList.map(([m, cnt]) => (
            <option key={m} value={m}>
              {m} ({fmtNum(cnt)})
            </option>
          ))}
        </select>

        {/* 발주번호 입력 필터 */}
        <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
          {([
            ['all', '전체'],
            ['has', '입력'],
            ['none', '미입력'],
          ] as [typeof orderInput, string][]).map(([key, label]) => {
            const cnt =
              key === 'all'
                ? orders.length
                : key === 'has'
                  ? orders.filter(hasOrderNo).length
                  : orders.filter((o) => !hasOrderNo(o)).length
            return (
              <button
                key={key}
                onClick={() => setOrderInput(key)}
                style={{
                  flex: 1,
                  fontSize: 13,
                  padding: '0.4rem 0',
                  background: orderInput === key ? c.accentBg : c.btnBg,
                  color: c.btnText,
                  border: `1px solid ${c.btnBorder}`,
                  borderRadius: 8,
                  fontWeight: orderInput === key ? 700 : 400,
                }}
              >
                발주 {label} {fmtNum(cnt)}
              </button>
            )
          })}
        </div>
      </div>

      {/* 요약 */}
      <div style={{ padding: '0.6rem 0.85rem', fontSize: 12, color: c.textSub }}>
        표시 {fmtNum(shown.length)}건 · 매출 {fmtNum(Math.round(shownSale))}원 · 기간 총 {fmtNum(totalCount)}건
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
          // 뱃지 3종: 취소/반품 · 발송 · 미발송
          const badge = isCancelled(o)
            ? { text: '취소/반품', bg: c.surfaceAlt, fg: c.danger }
            : isShipped(o)
              ? { text: '발송', bg: c.surfaceAlt, fg: c.success }
              : { text: '미발송', bg: c.accentBg, fg: c.warn }
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
                    background: badge.bg,
                    color: badge.fg,
                  }}
                >
                  {badge.text}
                </span>
              </div>

              {/* 썸네일 + 상품정보 */}
              <div style={{ display: 'flex', gap: 10 }}>
                {o.product_image ? (
                  <img
                    src={o.product_image}
                    alt=""
                    loading="lazy"
                    style={{
                      width: 60,
                      height: 60,
                      objectFit: 'cover',
                      borderRadius: 8,
                      border: `1px solid ${c.border}`,
                      flexShrink: 0,
                      background: c.surfaceAlt,
                    }}
                    onError={(e) => {
                      ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                    }}
                  />
                ) : null}
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 12, color: c.link, fontWeight: 600, marginBottom: 2 }}>
                    {marketOf(o)}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.35, marginBottom: 2 }}>
                    {o.product_name || '(상품명 없음)'}
                  </div>
                  {o.product_option && (
                    <div style={{ fontSize: 12, color: c.textSub }}>옵션: {o.product_option}</div>
                  )}
                  {o.source_site && (
                    <div style={{ fontSize: 12, marginTop: 2 }}>
                      {o.source_url ? (
                        <a
                          href={o.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: c.link, textDecoration: 'underline' }}
                        >
                          소싱처: {o.source_site} ↗
                        </a>
                      ) : (
                        <span style={{ color: c.textSub }}>소싱처: {o.source_site}</span>
                      )}
                    </div>
                  )}
                </div>
              </div>

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

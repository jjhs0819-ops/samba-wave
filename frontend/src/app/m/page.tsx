'use client'

// 폰 전용 간편 주문 뷰 — 아이디/비번 로그인(기존 JWT 재사용) 후 최근 주문 카드형 표시.
// 기존 orderApi/userApi/useTheme 그대로 사용. 백엔드/DB 변경 없음.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { userApi } from '@/lib/samba/api/operations'
import { orderApi, collectorApi, accountApi } from '@/lib/samba/api/commerce'
import type { SambaOrder, SambaMarketAccount } from '@/lib/samba/api/commerce'
import { useTheme } from '@/lib/samba/useTheme'
import { STORAGE_KEYS } from '@/lib/samba/constants'
import { fmtNum } from '@/lib/samba/styles'
import { STATUS_MAP } from '@/app/samba/orders/constants'
import { useOrderLinks } from '@/app/samba/orders/hooks/useOrderLinks'
import { useSettlement } from '@/app/samba/orders/hooks/useSettlement'

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

// 플레이오토 파생주문(사본-취소마감/반품마감, ★교환주문) — 수집 제외 대상.
// 백엔드 is_derived_order(playauto.py)와 동일 판정. 폰 목록에서 숨김.
const isDerivedOrder = (o: SambaOrder): boolean => {
  const n = o.product_name || ''
  return n.startsWith('[사본-') || n.includes('★교환주문')
}

// source_url 도메인 → 소싱처 코드 (PC OrderInfoCell.tsx의 sourceFromUrl과 동일 매핑)
const sourceSiteFromUrl = (url?: string | null): string => {
  const u = String(url || '').trim()
  if (!u) return ''
  const host = (() => {
    try {
      return new URL(u).hostname.toLowerCase()
    } catch {
      return u.toLowerCase()
    }
  })()
  if (host.includes('musinsa.com')) return 'MUSINSA'
  if (host.includes('kream.co.kr')) return 'KREAM'
  if (host.includes('snkrdunk.com')) return 'SNKRDUNK'
  if (host.includes('fashionplus.co.kr')) return 'FashionPlus'
  if (host.includes('grandstage.a-rt.com')) return 'ABCmart'
  if (host.includes('abcmart.a-rt.com') || host.includes('abcmart.co.kr')) return 'ABCmart'
  if (host.includes('nike.com')) return 'Nike'
  if (host.includes('ssg.com')) return 'SSG'
  if (host.includes('lotteon.com')) return 'LOTTEON'
  if (host.includes('gsshop.com')) return 'GSShop'
  return ''
}

// 발주번호(소싱처 주문번호) 입력 여부
const hasOrderNo = (o: SambaOrder): boolean =>
  !!(o.sourcing_order_number && o.sourcing_order_number.trim())

// 발송/미발송/취소 판정 — 백엔드 기준(order.py EXCLUDED_ORDER_STATUSES)과 완전히 일치
// status 컬럼만 기준 — shipping_status/tracking_number는 일절 관여 금지(PC와 동일 규칙)
// 크림 등 배송중(delivering) 주문은 status='pending' 유지 + tracking_number 선반영되므로
// tracking_number/shipping_status로 판정하면 미발송 목록에서 누락됨 (2026-08-03 PC/모바일 불일치 사고)
const CANCEL_RETURN_EXCHANGE_STATUSES = [
  'cancel_requested', 'cancelling', 'cancelled',
  'return_requested', 'returning', 'returned', 'return_completed',
  'exchange_requested', 'exchanging', 'exchanged', 'exchange_pending', 'exchange_done',
  'ship_failed', 'undeliverable',
]
const SHIPPED_STATUSES = ['shipping', 'delivered', 'confirmed']

// 취소/반품/교환 등 집계 제외 상태
const isCancelled = (o: SambaOrder): boolean =>
  CANCEL_RETURN_EXCHANGE_STATUSES.includes((o.status || '').toLowerCase())

// 발송됨: status 컬럼이 발송/배송완료/구매확정
const isShipped = (o: SambaOrder): boolean =>
  SHIPPED_STATUSES.includes((o.status || '').toLowerCase())

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

  // 마켓 계정 — PC 주문화면과 동일하게 useOrderLinks에 그대로 넘겨 원문/판매링크 생성 위임
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const { handleSourceLink, handleMarketLink } = useOrderLinks(accounts)

  // 정산금 — PC 주문화면과 동일한 계산(크림 수수료 차감 포함) 공유
  const { getRevenue } = useSettlement()

  useEffect(() => {
    accountApi.listActiveCached(setAccounts)
  }, [])

  // 주문 데이터
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [tab, setTab] = useState<'all' | 'unshipped'>('unshipped')
  const [range, setRange] = useState<RangeKey>('today')
  const [market, setMarket] = useState<string>('') // '' = 전체 판매처
  const [orderInput, setOrderInput] = useState<'all' | 'has' | 'none'>('all') // 발주번호 입력 여부

  // 수집상품 폴백 맵 — 주문 product_image/source가 비면 collected_product에서 보충(KREAM/POIZON 등)
  const [cpImages, setCpImages] = useState<Record<string, string>>({})
  const [cpSourceSite, setCpSourceSite] = useState<Record<string, string>>({})
  const [cpSourceUrl, setCpSourceUrl] = useState<Record<string, string>>({})

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
      // 사본/교환 파생주문은 목록에서 제외 (PC 수집 제외 정책과 동일)
      setOrders((res.items || []).filter((o) => !isDerivedOrder(o)))
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

  // 주문의 collected_product_id 로 이미지/소싱처 폴백 조회 (PC 주문화면과 동일)
  const cpIdsKey = useMemo(() => {
    const ids = [...new Set(orders.map((o) => o.collected_product_id).filter((id): id is string => !!id))]
    ids.sort()
    return ids.join(',')
  }, [orders])

  useEffect(() => {
    const ids = cpIdsKey ? cpIdsKey.split(',') : []
    if (ids.length === 0) {
      setCpImages({})
      setCpSourceSite({})
      setCpSourceUrl({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const rows = await collectorApi.getProductsByIds(ids)
        if (cancelled) return
        const imgs: Record<string, string> = {}
        const sites: Record<string, string> = {}
        const urls: Record<string, string> = {}
        for (const row of rows) {
          if (Array.isArray(row.images) && row.images[0]) imgs[row.id] = String(row.images[0])
          if (row.source_site) sites[row.id] = row.source_site
          if (row.source_url) urls[row.id] = row.source_url
        }
        setCpImages(imgs)
        setCpSourceSite(sites)
        setCpSourceUrl(urls)
      } catch {
        if (!cancelled) {
          setCpImages({})
          setCpSourceSite({})
          setCpSourceUrl({})
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [cpIdsKey])

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

  // 현재 탭(전체/미발송) 적용된 주문 — 판매처·발주필터 카운트는 전부 이 기준으로 통일해야
  // "필터엔 2건인데 실제론 1건"처럼 탭에 걸러진 건이 카운트에만 남는 불일치가 안 생김
  const tabFiltered = useMemo(
    () => orders.filter((o) => (tab === 'unshipped' ? isUnshipped(o) : true)),
    [orders, tab],
  )

  // 판매처 목록 추출 (건수순 정렬) — 현재 탭 기준
  const marketList = useMemo(() => {
    const counts = new Map<string, number>()
    for (const o of tabFiltered) {
      const m = marketOf(o)
      counts.set(m, (counts.get(m) || 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [tabFiltered])

  // 선택 판매처가 목록에 없으면 전체로 간주
  const activeMarket = marketList.some(([m]) => m === market) ? market : ''

  const shown = tabFiltered
    .filter((o) => (activeMarket ? marketOf(o) === activeMarket : true))
    .filter((o) =>
      orderInput === 'all' ? true : orderInput === 'has' ? hasOrderNo(o) : !hasOrderNo(o),
    )
  const unshippedCount = orders.filter(isUnshipped).length
  // 표시(필터 적용)된 주문 기준 매출 합계
  const shownSale = shown.reduce((s, o) => s + (amountOf(o) || 0), 0)
  // 정산금 합계 — 취소/반품류는 정산 대상이 아니라 제외
  const shownSettle = shown.reduce((s, o) => s + (isCancelled(o) ? 0 : getRevenue(o) || 0), 0)

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
          <option value="">전체 판매처 ({fmtNum(tabFiltered.length)})</option>
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
                ? tabFiltered.length
                : key === 'has'
                  ? tabFiltered.filter(hasOrderNo).length
                  : tabFiltered.filter((o) => !hasOrderNo(o)).length
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
      {/* 한 줄 유지 — 좌: 건수·매출 / 우: 정산금 합계 (2행 줄바꿈 방지 nowrap) */}
      <div
        style={{
          padding: '0.6rem 0.85rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          fontSize: 12,
          color: c.textSub,
          whiteSpace: 'nowrap',
        }}
      >
        <span>
          표시 {fmtNum(shown.length)}건 · 매출 {fmtNum(Math.round(shownSale))}원
        </span>
        <span style={{ fontWeight: 700, color: c.text }}>
          정산 {fmtNum(Math.round(shownSettle))}원
        </span>
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
          // 상태 뱃지: PC 주문화면 상태 드롭다운(o.status → STATUS_MAP)과 동일 소스·라벨
          const statusInfo = STATUS_MAP[o.status]
          const badge = statusInfo
            ? { text: statusInfo.label, bg: statusInfo.bg, fg: statusInfo.text }
            : { text: o.status || '-', bg: c.surfaceAlt, fg: c.textSub }
          const cpid = o.collected_product_id || ''
          // 주문 값 우선, 없으면 collected_product 폴백 (KREAM/POIZON 등 이미지 누락 대응)
          const imgSrc = o.product_image || (cpid ? cpImages[cpid] : '') || ''
          // 원문링크: 주문 source_url 우선, 없으면 수집상품 폴백 (PC handleSourceLink와 동일 우선순위)
          const srcUrl = o.source_url || (cpid ? cpSourceUrl[cpid] : '') || ''
          // 소싱처 라벨: source_url 도메인 우선 → 수집상품 source_site.
          // o.source_site는 라벨에 쓰지 않음 — 판매처(KREAM 등) 레거시값이 섞여있어 오표시 원인이었음
          // (PC OrderInfoCell.tsx sourceBadgeLabel과 동일 우선순위).
          const srcSite = sourceSiteFromUrl(srcUrl) || (cpid ? cpSourceSite[cpid] : '') || ''
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

              {/* 썸네일 + 상품정보 — 이미지 없거나 로드 실패 시 PC와 동일하게 "No IMG" 박스 표시 */}
              <div style={{ display: 'flex', gap: 10 }}>
                <div
                  onClick={() => handleSourceLink(o)}
                  style={{
                    width: 60,
                    height: 60,
                    borderRadius: 8,
                    border: `1px solid ${c.border}`,
                    flexShrink: 0,
                    background: c.surfaceAlt,
                    cursor: 'pointer',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  {imgSrc && (
                    <img
                      src={imgSrc}
                      alt=""
                      loading="lazy"
                      referrerPolicy="no-referrer"
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      onError={(e) => {
                        ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                        const ph = e.currentTarget.nextElementSibling as HTMLElement | null
                        if (ph) ph.style.display = 'flex'
                      }}
                    />
                  )}
                  <span
                    style={{
                      display: imgSrc ? 'none' : 'flex',
                      position: 'absolute',
                      inset: 0,
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 10,
                      color: c.textMuted,
                      textAlign: 'center',
                    }}
                  >
                    No IMG
                  </span>
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    onClick={() => handleMarketLink(o)}
                    style={{ fontSize: 12, color: c.link, fontWeight: 600, marginBottom: 2, cursor: 'pointer' }}
                  >
                    {marketOf(o)}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.35, marginBottom: 2 }}>
                    {o.product_name || '(상품명 없음)'}
                  </div>
                  {o.product_option && (
                    <div style={{ fontSize: 12, color: c.textSub }}>옵션: {o.product_option}</div>
                  )}
                  {srcSite && (
                    <div
                      onClick={() => handleSourceLink(o)}
                      style={{ fontSize: 12, marginTop: 2, color: c.link, textDecoration: 'underline', cursor: 'pointer' }}
                    >
                      {srcSite} ↗
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
                {/* 우측: 결제금액(큰 글씨) + 그 아래 정산금. 정산 미산출(0)이면 숨김 */}
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 15, fontWeight: 700 }}>
                    {fmtNum(Math.round(amountOf(o)))}원
                  </div>
                  {getRevenue(o) > 0 && (
                    <div style={{ fontSize: 12, color: c.textSub, marginTop: 1 }}>
                      정산 {fmtNum(Math.round(getRevenue(o)))}원
                    </div>
                  )}
                </div>
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

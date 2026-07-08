'use client'

import { useCallback, useEffect, useState } from 'react'
import { accountApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { storeCareApi, sourcingAccountApi, type StoreCareSchedule, type StoreCarePurchase, type StoreCareMarketMetric, type MetricRecommendation, type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { card as baseCard, fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'
import { dark as c } from '@/lib/samba/colors'
import { btn, btnDisabled } from '@/lib/samba/buttons'

const card = { ...baseCard, padding: '20px' }

const inputStyle = {
  padding: '8px 10px', fontSize: '0.82rem', background: c.inputBg,
  border: `1px solid ${c.border}`, borderRadius: '6px', color: c.text,
  width: '100%', boxSizing: 'border-box' as const,
}

const MARKET_COLORS: Record<string, string> = {
  smartstore: '#03C75A', coupang: '#E6282B', '11st': '#FF0038',
  lotteon: '#E30613', ssg: '#FF5452', gsshop: '#EC297B',
  lottehome: '#D40030', kream: '#000', ebay: '#E53238',
  toss: '#0064FF', rakuten: '#BF0000', amazon: '#FF9900',
}

const fmt = fmtNum

function getStatusBadge(status: string) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    running: { bg: 'rgba(81,207,102,0.15)', color: c.success, label: '실행중' },
    scheduled: { bg: 'rgba(76,154,255,0.15)', color: c.link, label: '예약됨' },
    paused: { bg: 'rgba(255,211,61,0.15)', color: c.warn, label: '일시정지' },
    completed: { bg: 'rgba(138,149,176,0.15)', color: c.textSub, label: '완료' },
    failed: { bg: 'rgba(255,107,107,0.15)', color: c.danger, label: '실패' },
  }
  const s = map[status] || map.completed
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: s.bg, color: s.color, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

const MARKET_NAME: Record<string, string> = { '11st': '11번가', ssg: 'SSG', gsshop: 'GS샵' }
// 가구매 마켓 → SambaSourcingAccount.site_name (자동로그인 계정 필터용)
const PURCHASE_SITE_NAME: Record<string, string> = { ssg: 'SSG', gsshop: 'GSShop', '11st': '11ST' }

// 부족분 계산 (백엔드 recommend_purchase_qty 와 동일 공식) — 수동 N 입력용
function deficitQty(target: { metric: string; value: number }, current: number | null, n: number | null): number | null {
  if (current == null) return null
  const t = target.value / 100, cur = current / 100
  const met = target.metric === 'soldout_rate' ? cur < t : cur >= t
  if (met) return 0 // 이미 목표 달성 — N 없어도 0개
  if (n == null || !Number.isFinite(n) || n <= 0) return null // 미달 → N 필요
  if (target.metric === 'order_fulfillment') {
    return Math.max(0, Math.ceil(n * (t - cur) / (1 - t) - 1e-9))
  }
  // soldout_rate 미달(cur >= t)
  return Math.max(0, Math.floor(cur * n / t - n + 1e-9) + 1)
}

function targetLabel(target: { metric: string; op: string; value: number }): string {
  const name = target.metric === 'soldout_rate' ? '품절률' : '주문이행'
  return `${name} ${target.op} ${target.value}%`
}


export default function StoreCare() {
  const c = useTheme()
  useEffect(() => { document.title = 'SAMBA-스토어케어' }, [])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [schedules, setSchedules] = useState<StoreCareSchedule[]>([])
  const [purchases, setPurchases] = useState<StoreCarePurchase[]>([])
  const [metrics, setMetrics] = useState<StoreCareMarketMetric[]>([])
  const [recs, setRecs] = useState<MetricRecommendation[]>([])
  const [nInput, setNInput] = useState<Record<string, string>>({})
  const [stats, setStats] = useState({ total: 0, success: 0, failed: 0, total_amount: 0 })
  const [tab, setTab] = useState<'overview' | 'schedule' | 'history' | 'metrics' | 'purchase'>('metrics')
  const [collecting, setCollecting] = useState(false)
  const [collectingAcc, setCollectingAcc] = useState('') // 계정별 수집 중인 account_id
  const [loading, setLoading] = useState(true)
  // 가구매(M1 — SSG 수동 1건)
  const [purchaseAccounts, setPurchaseAccounts] = useState<SambaSourcingAccount[]>([])
  const [purchaseForm, setPurchaseForm] = useState({ market: 'ssg', account_id: '', product_url: '', option: '', quantity: 1 })
  const [purchaseResult, setPurchaseResult] = useState('')
  const [purchaseRunning, setPurchaseRunning] = useState(false)
  // 저장 상품 (가구매 북마크) — 이름으로 URL 저장/불러오기
  const [savedProducts, setSavedProducts] = useState<Array<{ id: string; name: string; market_type: string; product_url: string }>>([])
  const [selectedSavedId, setSelectedSavedId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    const [accs, scheds, purs, st, mets, rcs] = await Promise.all([
      accountApi.listActive().catch(() => []),
      storeCareApi.listSchedules().catch(() => []),
      storeCareApi.listPurchases(50).catch(() => []),
      storeCareApi.stats().catch(() => ({ total: 0, success: 0, failed: 0, total_amount: 0 })),
      storeCareApi.listMetrics().catch(() => []),
      storeCareApi.recommendations().catch(() => []),
    ])
    setAccounts(accs)
    setSchedules(scheds)
    setPurchases(purs)
    setStats(st)
    setMetrics(mets)
    setRecs(rcs)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // 새로고침 — 계정별 수집은 각 계정 카드의 '수집' 버튼으로. 여기선 최신값 재조회만.
  const runCollect = useCallback(async () => {
    setCollecting(true)
    try {
      const [mets, rcs] = await Promise.all([
        storeCareApi.listMetrics().catch(() => []),
        storeCareApi.recommendations().catch(() => []),
      ])
      setMetrics(mets)
      setRecs(rcs)
    } finally {
      setCollecting(false)
    }
  }, [])

  // 계정별 수집 — 그 계정 셀러센터에 로그인된 상태에서 눌러야 정확함(로그인된 계정 기준 스크랩)
  const collectOne = useCallback(async (acc: SambaMarketAccount) => {
    setCollectingAcc(acc.id)
    try {
      await storeCareApi.collectMetrics([acc.market_type], acc.id, acc.account_label).catch(() => {})
      await new Promise(r => setTimeout(r, 6000))
      const mets = await storeCareApi.listMetrics().catch(() => [])
      setMetrics(mets)
    } finally {
      setCollectingAcc('')
    }
  }, [])

  // 가구매 — SSG 소싱계정(자동로그인용) 로드
  useEffect(() => {
    sourcingAccountApi.list()
      .then(accs => setPurchaseAccounts(accs.filter(a => ['SSG', 'GSShop', '11ST'].includes(a.site_name) && a.is_active)))
      .catch(() => {})
  }, [])

  // 저장 상품 — 로드 + 저장/불러오기/삭제
  const loadSavedProducts = useCallback(() => {
    storeCareApi.listSavedProducts().then(setSavedProducts).catch(() => {})
  }, [])
  useEffect(() => { loadSavedProducts() }, [loadSavedProducts])

  const applySavedProduct = useCallback((id: string) => {
    setSelectedSavedId(id)
    const p = savedProducts.find(x => x.id === id)
    if (p) setPurchaseForm(f => ({ ...f, market: p.market_type, product_url: p.product_url }))
  }, [savedProducts])

  const saveCurrentProduct = useCallback(async () => {
    const url = purchaseForm.product_url.trim()
    if (!url) { setPurchaseResult('저장할 상품 URL을 먼저 입력하세요.'); return }
    const name = (typeof window !== 'undefined' ? window.prompt('상품 이름 (예: 신발끈)') : '') || ''
    if (!name.trim()) return
    try {
      await storeCareApi.createSavedProduct({ name: name.trim(), market_type: purchaseForm.market, product_url: url })
      loadSavedProducts()
      setPurchaseResult(`저장됨: ${name.trim()}`)
    } catch (e) {
      setPurchaseResult(`저장 실패: ${(e as Error).message}`)
    }
  }, [purchaseForm, loadSavedProducts])

  const deleteSavedProduct = useCallback(async (id: string) => {
    try {
      await storeCareApi.deleteSavedProduct(id)
      setSelectedSavedId(prev => (prev === id ? '' : prev))
      loadSavedProducts()
    } catch (e) {
      setPurchaseResult(`삭제 실패: ${(e as Error).message}`)
    }
  }, [loadSavedProducts])

  const runPurchase = useCallback(async () => {
    if (!purchaseForm.product_url.trim()) { setPurchaseResult('상품 URL을 입력하세요.'); return }
    setPurchaseRunning(true)
    setPurchaseResult('실행 중… (자동로그인 + 장바구니 담기, 최대 2분)')
    try {
      const r = await storeCareApi.runPurchase({
        market_type: purchaseForm.market,
        product_url: purchaseForm.product_url.trim(),
        option: purchaseForm.option.trim() || undefined,
        quantity: purchaseForm.quantity || 1,
        account_id: purchaseForm.account_id || undefined,
      })
      if (r.ok) setPurchaseResult('✅ 장바구니 담기 완료!')
      else setPurchaseResult(`❌ 실패: ${r.result?.error || r.error || '알 수 없음'}`)
    } catch (e) {
      setPurchaseResult(`❌ 오류: ${(e as Error).message}`)
    } finally {
      setPurchaseRunning(false)
    }
  }, [purchaseForm])

  // KPI
  const todayTotal = stats.total_amount
  const todaySuccess = stats.success
  const todayFailed = stats.failed
  const activeSchedules = schedules.filter(s => s.status !== 'paused').length

  // 마켓별 요약
  const marketSummary = schedules.map(s => {
    const mPurchases = purchases.filter(p => p.market_type === s.market_type && p.status === 'completed')
    return {
      ...s,
      market: s.market_type,
      color: MARKET_COLORS[s.market_type] || c.textMuted,
      todayDone: mPurchases.length,
      todayAmount: mPurchases.reduce((sum, p) => sum + p.amount, 0),
    }
  })

  // 점수수집 대상 셀러 계정 (SSG/11번가/GS) — 계정별 카드/수집
  const METRICS_MARKETS = ['ssg', '11st', 'gsshop']
  const sellerAccounts = accounts.filter(a => METRICS_MARKETS.includes(a.market_type))

  return (
    <div style={{ padding: '0' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: c.text, margin: 0 }}>스토어케어</h2>
          <p style={{ fontSize: '0.78rem', color: c.textSub, marginTop: '4px' }}>마켓 점수 관리 · 자동 가구매 · 모니터링</p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {(['overview', 'schedule', 'history', 'metrics', 'purchase'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
              background: tab === t ? c.primary : c.surfaceAlt,
              color: tab === t ? '#fff' : c.textSub,
              border: tab === t ? 'none' : `1px solid ${c.border}`,
            }}>
              {{ overview: '종합현황', schedule: '스케줄 관리', history: '구매 이력', metrics: '마켓점수', purchase: '가구매' }[t]}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: c.textMuted }}>로딩 중...</div>
      ) : (
        <>
          {/* KPI 카드 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: c.textSub, marginBottom: '4px' }}>오늘 가구매</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: c.success }}>{fmt(todaySuccess)}건</div>
              {todayFailed > 0 && <div style={{ fontSize: '0.7rem', color: c.danger, marginTop: '2px' }}>실패 {fmt(todayFailed)}건</div>}
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: c.textSub, marginBottom: '4px' }}>오늘 구매액</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: c.text }}>₩{fmt(todayTotal)}</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: c.textSub, marginBottom: '4px' }}>활성 스케줄</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: c.text }}>{fmt(activeSchedules)}개</div>
              <div style={{ fontSize: '0.7rem', color: c.textSub, marginTop: '2px' }}>전체 {fmt(schedules.length)}개</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: c.textSub, marginBottom: '4px' }}>연결 마켓</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: c.text }}>{fmtNum(accounts.length)}개</div>
            </div>
          </div>

          {/* 종합현황 탭 */}
          {tab === 'overview' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {/* 마켓별 현황 */}
              <div style={card}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, marginBottom: '16px' }}>마켓별 가구매 현황</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {marketSummary.map(m => (
                    <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', background: c.surfaceAlt, borderRadius: '8px', border: `1px solid ${c.border}` }}>
                      <div style={{ width: '4px', height: '36px', borderRadius: '2px', background: m.color }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: c.text }}>{m.account_label}</div>
                        <div style={{ fontSize: '0.72rem', color: c.textSub, marginTop: '2px' }}>
                          오늘 {fmt(m.todayDone)}/{fmt(m.daily_target)}건 · ₩{fmt(m.todayAmount)}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        {getStatusBadge(m.status)}
                        <div style={{ fontSize: '0.68rem', color: c.textMuted, marginTop: '4px' }}>다음: {m.next_run_at ? new Date(m.next_run_at).toLocaleTimeString('ko', { hour: '2-digit', minute: '2-digit' }) : '-'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 최근 구매 이력 */}
              <div style={card}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, marginBottom: '16px' }}>최근 가구매</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {purchases.slice(0, 5).map(h => (
                    <div key={h.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: c.surfaceAlt, borderRadius: '8px' }}>
                      <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market_type] || c.textMuted }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '0.78rem', color: c.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.product_name}</div>
                        <div style={{ fontSize: '0.68rem', color: c.textSub }}>{h.created_at}</div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '0.78rem', fontWeight: 600, color: h.status === 'completed' ? c.success : c.danger }}>
                          ₩{fmt(h.amount)}
                        </div>
                        {h.order_no && <div style={{ fontSize: '0.65rem', color: c.textMuted }}>{h.order_no}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 스케줄 관리 탭 */}
          {tab === 'schedule' && (
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, margin: 0 }}>가구매 스케줄</h3>
                <button style={{
                  ...btn('primary'), padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px',
                }}>
                  + 스케줄 추가
                </button>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${c.border}` }}>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>마켓</th>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>계정</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>간격</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>일일 목표</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>오늘 진행</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>다음 실행</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>상태</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {schedules.map(s => (
                    <tr key={s.id} style={{ borderBottom: `1px solid ${c.border}` }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[s.market_type] || c.textMuted }} />
                          <span style={{ fontSize: '0.82rem', color: c.text }}>{s.market_type}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px', fontSize: '0.82rem', color: c.text }}>{s.account_label}</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: c.text }}>{s.interval_hours}시간</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: c.text }}>{fmt(s.daily_target)}건</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <span style={{ fontSize: '0.82rem', color: s.daily_done >= s.daily_target ? c.success : c.warn, fontWeight: 600 }}>
                          {fmt(s.daily_done)}/{fmt(s.daily_target)}
                        </span>
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.78rem', color: c.textSub }}>{s.next_run_at ? new Date(s.next_run_at).toLocaleString('ko') : '-'}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{getStatusBadge(s.status)}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                          <button onClick={async () => {
                            await storeCareApi.toggleSchedule(s.id).catch(() => {})
                            load()
                          }} style={{ fontSize: '0.72rem', padding: '3px 8px', background: c.surfaceAlt, border: `1px solid ${c.border}`, color: c.text, borderRadius: '4px', cursor: 'pointer' }}>
                            {s.status === 'paused' ? '재개' : '정지'}
                          </button>
                          <button onClick={async () => {
                            await storeCareApi.deleteSchedule(s.id).catch(() => {})
                            load()
                          }} style={{ fontSize: '0.72rem', padding: '3px 8px', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: c.danger, borderRadius: '4px', cursor: 'pointer' }}>
                            삭제
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 구매 이력 탭 */}
          {tab === 'history' && (
            <div style={card}>
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, marginBottom: '16px' }}>가구매 이력</h3>
              {purchases.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: c.textMuted, fontSize: '0.85rem' }}>아직 가구매 이력이 없습니다</div>
              ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${c.border}` }}>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>마켓</th>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>상품명</th>
                    <th style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>금액</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>주문번호</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>상태</th>
                    <th style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: c.textSub, fontWeight: 500 }}>일시</th>
                  </tr>
                </thead>
                <tbody>
                  {purchases.map(h => (
                    <tr key={h.id} style={{ borderBottom: `1px solid ${c.border}` }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market_type] || c.textMuted }} />
                          <span style={{ fontSize: '0.82rem', color: c.text }}>{h.market_type}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px', fontSize: '0.82rem', color: c.text, maxWidth: '250px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.product_name}</td>
                      <td style={{ padding: '10px', textAlign: 'right', fontSize: '0.82rem', fontWeight: 600, color: c.text }}>₩{fmt(h.amount)}</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: c.textSub }}>{h.order_no || '-'}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{getStatusBadge(h.status)}</td>
                      <td style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: c.textSub }}>{h.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              )}
            </div>
          )}

          {/* 마켓 점수·품절률 탭 */}
          {tab === 'metrics' && (
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <div>
                  <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, margin: 0 }}>마켓 점수 · 품절률 (계정별)</h3>
                  <p style={{ fontSize: '0.72rem', color: c.textSub, marginTop: '4px' }}>각 계정 셀러센터에 로그인된 상태에서 계정 카드의 &lsquo;수집&rsquo;을 누르면 그 계정 점수가 수집돼요. 확장앱 설치·로그인된 PC에서 실행.</p>
                </div>
                <button onClick={runCollect} disabled={collecting} style={{
                  ...btn('primary'), padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px',
                  ...(collecting ? btnDisabled : null),
                }}>
                  {collecting ? '새로고침…' : '🔄 새로고침'}
                </button>
              </div>

              {/* 💰 추천 구매 갯수 (부족분 계산) */}
              {recs.length > 0 && (
                <div style={{ marginBottom: '18px', padding: '14px', background: 'rgba(255,140,0,0.06)', border: '1px solid rgba(255,140,0,0.25)', borderRadius: '10px' }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: c.text, marginBottom: '10px' }}>💰 추천 구매 갯수 (목표 도달 부족분)</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: `1px solid ${c.border}` }}>
                        {['마켓', '목표', '현재', '전체주문수(N)', '추천 구매'].map(h => (
                          <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: '0.72rem', color: c.textSub, fontWeight: 500 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {recs.map(r => {
                        const nStr = nInput[r.market_type] ?? (r.denom != null ? String(r.denom) : '')
                        const nVal = nStr.trim() === '' ? null : Number(nStr.replace(/,/g, ''))
                        const qty = deficitQty(r.target, r.current_value, nVal)
                        const ok = r.current_value != null
                        return (
                          <tr key={r.market_type} style={{ borderBottom: `1px solid ${c.border}` }}>
                            <td style={{ padding: '8px', fontSize: '0.82rem', color: c.text, fontWeight: 600 }}>
                              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[r.market_type] || c.textMuted, marginRight: '6px' }} />
                              {MARKET_NAME[r.market_type] || r.market_type}
                            </td>
                            <td style={{ padding: '8px', fontSize: '0.78rem', color: c.text }}>{targetLabel(r.target)}</td>
                            <td style={{ padding: '8px', fontSize: '0.82rem', fontWeight: 600, color: ok ? c.text : c.danger }}>
                              {ok ? `${r.current_value}%` : '수집 필요'}
                            </td>
                            <td style={{ padding: '8px' }}>
                              <input
                                type="text"
                                inputMode="numeric"
                                placeholder="N 입력"
                                value={nStr}
                                onChange={e => setNInput(prev => ({ ...prev, [r.market_type]: e.target.value }))}
                                style={{ width: '90px', padding: '4px 8px', fontSize: '0.8rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '5px', color: c.text }}
                              />
                            </td>
                            <td style={{ padding: '8px' }}>
                              {qty == null ? (
                                <span style={{ fontSize: '0.78rem', color: c.textSub }}>{nVal == null ? 'N 입력 시 계산' : '—'}</span>
                              ) : (
                                <span style={{ fontSize: '1.05rem', fontWeight: 700, color: qty > 0 ? c.text : c.success }}>{fmt(qty)}개</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  <div style={{ fontSize: '0.68rem', color: c.textMuted, marginTop: '8px' }}>
                    N(전체 주문수)을 입력하면 목표 도달에 필요한 최소 가구매 갯수가 계산돼요. (자동 N 수집은 2단계에서 추가)
                  </div>
                </div>
              )}

              {sellerAccounts.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: c.textMuted, fontSize: '0.85rem' }}>
                  연결된 SSG/11번가/GS 셀러 계정이 없습니다. 설정 &gt; 마켓계정에서 계정을 추가하세요.
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
                  {sellerAccounts.map(acc => {
                    const m = metrics.find(x => x.market_type === acc.market_type && (x.account_id || '') === acc.id)
                    const isC = collectingAcc === acc.id
                    return (
                      <div key={acc.id} style={{ padding: '14px', background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[acc.market_type] || c.textMuted, flexShrink: 0 }} />
                          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: c.text }}>{MARKET_NAME[acc.market_type] || acc.market_type}</span>
                          <span style={{ fontSize: '0.74rem', color: c.textSub, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>· {acc.account_label}</span>
                          <button onClick={() => collectOne(acc)} disabled={isC} style={{ marginLeft: 'auto', fontSize: '0.68rem', padding: '3px 10px', borderRadius: '6px', cursor: isC ? 'default' : 'pointer', border: 'none', background: isC ? c.surfaceAlt : c.primary, color: isC ? c.textSub : '#fff', fontWeight: 600, whiteSpace: 'nowrap', flexShrink: 0 }}>
                            {isC ? '수집중…' : '수집'}
                          </button>
                        </div>
                        {m ? (
                          <>
                            {m.status === 'failed' && <div style={{ fontSize: '0.68rem', color: c.danger, marginBottom: '6px' }}>수집 실패</div>}
                            <div style={{ display: 'flex', gap: '16px', marginBottom: '10px' }}>
                              <div>
                                <div style={{ fontSize: '0.65rem', color: c.textSub }}>대표점수</div>
                                <div style={{ fontSize: '1.3rem', fontWeight: 700, color: c.text }}>{m.score != null ? fmtNum(m.score) : '-'}</div>
                              </div>
                              <div>
                                <div style={{ fontSize: '0.65rem', color: c.textSub }}>품절률</div>
                                <div style={{ fontSize: '1.3rem', fontWeight: 700, color: c.text }}>
                                  {m.soldout_rate != null ? `${m.soldout_rate}%` : '-'}
                                  {m.soldout_rate_prev != null && <span style={{ fontSize: '0.62rem', color: c.textMuted, marginLeft: '4px' }}>(전 {m.soldout_rate_prev}%)</span>}
                                </div>
                              </div>
                              <div>
                                <div style={{ fontSize: '0.65rem', color: c.textSub }}>패널티</div>
                                <div style={{ fontSize: '1.3rem', fontWeight: 700, color: m.penalty ? c.danger : c.success }}>{m.penalty != null ? fmtNum(m.penalty) : '-'}</div>
                              </div>
                            </div>
                            {m.grade && <div style={{ fontSize: '0.72rem', color: c.text, marginBottom: '6px' }}>등급: {m.grade}</div>}
                            {m.metrics && Object.keys(m.metrics).length > 0 && (
                              <div style={{ borderTop: `1px solid ${c.border}`, paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                {Object.entries(m.metrics as Record<string, { value?: number; level?: string }>).map(([k, v]) => (
                                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem' }}>
                                    <span style={{ color: c.textSub }}>{k}</span>
                                    <span style={{ color: c.text }}>
                                      {v && typeof v === 'object' ? `${v.value ?? ''}${v.level ? ` · ${v.level}` : ''}` : String(v)}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                            <div style={{ fontSize: '0.62rem', color: c.textMuted, marginTop: '8px' }}>
                              {m.collected_at ? new Date(m.collected_at).toLocaleString('ko') : ''}{m.period_label ? ` · 평가기간 ${m.period_label}` : ''}
                            </div>
                            {m.status === 'failed' && m.error && <div style={{ fontSize: '0.62rem', color: c.danger, marginTop: '4px' }}>{m.error}</div>}
                          </>
                        ) : (
                          <div style={{ fontSize: '0.72rem', color: c.textMuted, padding: '10px 0' }}>
                            아직 수집 안 됨 — 이 계정 셀러센터에 로그인 후 <b style={{ color: c.text }}>수집</b>을 눌러주세요.
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* 가구매 탭 (M1 — SSG 수동 1건 장바구니 담기) */}
          {tab === 'purchase' && (
            <div style={card}>
              <div style={{ marginBottom: '16px' }}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: c.text, margin: 0 }}>가구매 (셀프구매)</h3>
                <p style={{ fontSize: '0.72rem', color: c.textSub, marginTop: '4px' }}>
                  저장된 계정으로 자동로그인 → 옵션 선택 → 장바구니 담기. 결제(폰 QR)·일시품절 원복은 다음 단계. (확장앱 설치된 PC에서 실행)
                </p>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '560px' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.72rem', color: c.textSub }}>마켓</span>
                  <select value={purchaseForm.market} onChange={e => setPurchaseForm(f => ({ ...f, market: e.target.value, account_id: '' }))} style={inputStyle}>
                    <option value="ssg">SSG</option>
                    <option value="gsshop">GS샵 (셀렉터 라이브보정)</option>
                    <option value="11st">11번가 (셀렉터 라이브보정)</option>
                  </select>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.72rem', color: c.textSub }}>{MARKET_NAME[purchaseForm.market] || purchaseForm.market} 계정 (자동로그인)</span>
                  <select value={purchaseForm.account_id} onChange={e => setPurchaseForm(f => ({ ...f, account_id: e.target.value }))} style={inputStyle}>
                    <option value="">기본 계정 (사이트 기본 로그인 계정)</option>
                    {purchaseAccounts.filter(a => a.site_name === PURCHASE_SITE_NAME[purchaseForm.market]).map(a => (
                      <option key={a.id} value={a.id}>{a.account_label} ({a.username})</option>
                    ))}
                  </select>
                  {purchaseAccounts.filter(a => a.site_name === PURCHASE_SITE_NAME[purchaseForm.market]).length === 0 && (
                    <span style={{ fontSize: '0.66rem', color: c.warn }}>저장된 {MARKET_NAME[purchaseForm.market] || purchaseForm.market} 계정 없음 → 설정 &gt; 소싱계정 관리에서 추가</span>
                  )}
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '0.72rem', color: c.textSub }}>상품 URL ({MARKET_NAME[purchaseForm.market] || purchaseForm.market})</span>
                  {savedProducts.filter(p => p.market_type === purchaseForm.market).length > 0 && (
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginBottom: '2px' }}>
                      <select value={selectedSavedId} onChange={e => applySavedProduct(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
                        <option value="">📁 저장된 상품 불러오기…</option>
                        {savedProducts.filter(p => p.market_type === purchaseForm.market).map(p => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                      {selectedSavedId && (
                        <button type="button" onClick={() => deleteSavedProduct(selectedSavedId)} title="이 저장 상품 삭제" style={{ padding: '0 10px', borderRadius: '6px', border: `1px solid ${c.danger}`, background: 'rgba(255,80,80,0.1)', color: c.danger, cursor: 'pointer' }}>🗑</button>
                      )}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <input type="text" placeholder="https://www.ssg.com/item/itemView.ssg?itemId=..." value={purchaseForm.product_url} onChange={e => { setSelectedSavedId(''); setPurchaseForm(f => ({ ...f, product_url: e.target.value })) }} style={{ ...inputStyle, flex: 1 }} />
                    <button type="button" onClick={saveCurrentProduct} title="현재 URL을 이름 붙여 저장" style={{ padding: '0 12px', borderRadius: '6px', border: `1px solid ${c.success}`, background: 'rgba(80,200,120,0.12)', color: c.success, cursor: 'pointer', whiteSpace: 'nowrap', fontSize: '0.78rem', fontWeight: 600 }}>💾 저장</button>
                  </div>
                </label>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 2 }}>
                    <span style={{ fontSize: '0.72rem', color: c.textSub }}>
                      옵션 (선택){(() => {
                        const s = (purchaseForm.option || '').trim()
                        if (!s) return ''
                        let n = 0
                        for (const tok of s.split(',')) {
                          const m = tok.trim().match(/^(\d+)\s*[~-]\s*(\d+)$/)
                          if (m) n += Math.abs(Number(m[2]) - Number(m[1])) + 1
                          else if (tok.trim()) n += 1
                        }
                        return n > 1 ? ` · ${fmtNum(Math.min(n, 100))}개 담기` : ''
                      })()}
                    </span>
                    <input type="text" placeholder="예: 1~30 (범위) · 1,3,5 · 270" value={purchaseForm.option} onChange={e => setPurchaseForm(f => ({ ...f, option: e.target.value }))} style={inputStyle} />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                    <span style={{ fontSize: '0.72rem', color: c.textSub }}>수량</span>
                    <input type="number" min={1} value={purchaseForm.quantity} onChange={e => setPurchaseForm(f => ({ ...f, quantity: Math.max(1, Number(e.target.value) || 1) }))} style={inputStyle} />
                  </label>
                </div>
                <button onClick={runPurchase} disabled={purchaseRunning} style={{
                  ...btn('primary'), marginTop: '4px', padding: '10px', fontSize: '0.85rem', borderRadius: '8px', fontWeight: 700,
                  ...(purchaseRunning ? btnDisabled : null),
                }}>
                  {purchaseRunning ? '실행 중…' : '지금 실행 (장바구니 담기)'}
                </button>
                {purchaseResult && (
                  <div style={{ padding: '12px', borderRadius: '8px', fontSize: '0.8rem', background: c.surfaceAlt, border: `1px solid ${c.border}`, color: c.text, whiteSpace: 'pre-wrap' }}>
                    {purchaseResult}
                  </div>
                )}
              </div>
              <div style={{ fontSize: '0.66rem', color: c.textMuted, marginTop: '14px' }}>
                M2: 옵션 범위/다건 담기 지원 — 예 &quot;1~30&quot; = 옵션 30개를 한 탭에서 누적 담기. 결제·일시품절 원복은 다음 단계.
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

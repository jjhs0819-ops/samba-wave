'use client'

import { useCallback, useEffect, useState } from 'react'
import { accountApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { storeCareApi, type StoreCareSchedule, type StoreCarePurchase, type StoreCareMarketMetric, type MetricRecommendation } from '@/lib/samba/api/operations'
import { card as baseCard, fmtNum } from '@/lib/samba/styles'

const card = { ...baseCard, padding: '20px' }

const MARKET_COLORS: Record<string, string> = {
  smartstore: '#03C75A', coupang: '#E6282B', '11st': '#FF0038',
  lotteon: '#E30613', ssg: '#FF5452', gsshop: '#EC297B',
  lottehome: '#D40030', kream: '#000', ebay: '#E53238',
  toss: '#0064FF', rakuten: '#BF0000', amazon: '#FF9900',
}

const fmt = fmtNum

function getStatusBadge(status: string) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    running: { bg: 'rgba(81,207,102,0.15)', color: '#51CF66', label: '실행중' },
    scheduled: { bg: 'rgba(76,154,255,0.15)', color: '#4C9AFF', label: '예약됨' },
    paused: { bg: 'rgba(255,211,61,0.15)', color: '#FFD33D', label: '일시정지' },
    completed: { bg: 'rgba(138,149,176,0.15)', color: '#8A95B0', label: '완료' },
    failed: { bg: 'rgba(255,107,107,0.15)', color: '#FF6B6B', label: '실패' },
  }
  const s = map[status] || map.completed
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: s.bg, color: s.color, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

const MARKET_NAME: Record<string, string> = { '11st': '11번가', ssg: 'SSG', gsshop: 'GS샵' }

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
  useEffect(() => { document.title = 'SAMBA-스토어케어' }, [])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [schedules, setSchedules] = useState<StoreCareSchedule[]>([])
  const [purchases, setPurchases] = useState<StoreCarePurchase[]>([])
  const [metrics, setMetrics] = useState<StoreCareMarketMetric[]>([])
  const [recs, setRecs] = useState<MetricRecommendation[]>([])
  const [nInput, setNInput] = useState<Record<string, string>>({})
  const [stats, setStats] = useState({ total: 0, success: 0, failed: 0, total_amount: 0 })
  const [tab, setTab] = useState<'overview' | 'schedule' | 'history' | 'metrics'>('overview')
  const [collecting, setCollecting] = useState(false)
  const [loading, setLoading] = useState(true)

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

  const runCollect = useCallback(async () => {
    setCollecting(true)
    try {
      await storeCareApi.collectMetrics().catch(() => {})
      // 확장앱이 포털을 열어 스크래핑하는 시간 — 잠시 후 재조회
      await new Promise(r => setTimeout(r, 6000))
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
      color: MARKET_COLORS[s.market_type] || '#888',
      todayDone: mPurchases.length,
      todayAmount: mPurchases.reduce((sum, p) => sum + p.amount, 0),
    }
  })

  return (
    <div style={{ padding: '0' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>스토어케어</h2>
          <p style={{ fontSize: '0.78rem', color: '#8A95B0', marginTop: '4px' }}>마켓 점수 관리 · 자동 가구매 · 모니터링</p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {(['overview', 'schedule', 'history', 'metrics'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
              background: tab === t ? '#FF8C00' : 'rgba(255,255,255,0.05)',
              color: tab === t ? '#000' : '#8A95B0',
              border: tab === t ? 'none' : '1px solid #2D2D2D',
            }}>
              {{ overview: '종합현황', schedule: '스케줄 관리', history: '구매 이력', metrics: '마켓점수' }[t]}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
      ) : (
        <>
          {/* KPI 카드 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>오늘 가구매</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#51CF66' }}>{fmt(todaySuccess)}건</div>
              {todayFailed > 0 && <div style={{ fontSize: '0.7rem', color: '#FF6B6B', marginTop: '2px' }}>실패 {fmt(todayFailed)}건</div>}
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>오늘 구매액</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#FF8C00' }}>₩{fmt(todayTotal)}</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>활성 스케줄</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#4C9AFF' }}>{fmt(activeSchedules)}개</div>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginTop: '2px' }}>전체 {fmt(schedules.length)}개</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>연결 마켓</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#E5E5E5' }}>{fmtNum(accounts.length)}개</div>
            </div>
          </div>

          {/* 종합현황 탭 */}
          {tab === 'overview' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {/* 마켓별 현황 */}
              <div style={card}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>마켓별 가구매 현황</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {marketSummary.map(m => (
                    <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                      <div style={{ width: '4px', height: '36px', borderRadius: '2px', background: m.color }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#E5E5E5' }}>{m.account_label}</div>
                        <div style={{ fontSize: '0.72rem', color: '#8A95B0', marginTop: '2px' }}>
                          오늘 {fmt(m.todayDone)}/{fmt(m.daily_target)}건 · ₩{fmt(m.todayAmount)}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        {getStatusBadge(m.status)}
                        <div style={{ fontSize: '0.68rem', color: '#555', marginTop: '4px' }}>다음: {m.next_run_at ? new Date(m.next_run_at).toLocaleTimeString('ko', { hour: '2-digit', minute: '2-digit' }) : '-'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 최근 구매 이력 */}
              <div style={card}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>최근 가구매</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {purchases.slice(0, 5).map(h => (
                    <div key={h.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                      <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market_type] || '#888' }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '0.78rem', color: '#E5E5E5', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.product_name}</div>
                        <div style={{ fontSize: '0.68rem', color: '#8A95B0' }}>{h.created_at}</div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: '0.78rem', fontWeight: 600, color: h.status === 'completed' ? '#51CF66' : '#FF6B6B' }}>
                          ₩{fmt(h.amount)}
                        </div>
                        {h.order_no && <div style={{ fontSize: '0.65rem', color: '#555' }}>{h.order_no}</div>}
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
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', margin: 0 }}>가구매 스케줄</h3>
                <button style={{
                  padding: '6px 14px', fontSize: '0.78rem', background: '#FF8C00', color: '#000',
                  border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
                }}>
                  + 스케줄 추가
                </button>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>마켓</th>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>계정</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>간격</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>일일 목표</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>오늘 진행</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>다음 실행</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>상태</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {schedules.map(s => (
                    <tr key={s.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[s.market_type] || '#888' }} />
                          <span style={{ fontSize: '0.82rem', color: '#E5E5E5' }}>{s.market_type}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px', fontSize: '0.82rem', color: '#C5C5C5' }}>{s.account_label}</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: '#C5C5C5' }}>{s.interval_hours}시간</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: '#C5C5C5' }}>{fmt(s.daily_target)}건</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <span style={{ fontSize: '0.82rem', color: s.daily_done >= s.daily_target ? '#51CF66' : '#FFD33D', fontWeight: 600 }}>
                          {fmt(s.daily_done)}/{fmt(s.daily_target)}
                        </span>
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.78rem', color: '#8A95B0' }}>{s.next_run_at ? new Date(s.next_run_at).toLocaleString('ko') : '-'}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{getStatusBadge(s.status)}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                          <button onClick={async () => {
                            await storeCareApi.toggleSchedule(s.id).catch(() => {})
                            load()
                          }} style={{ fontSize: '0.72rem', padding: '3px 8px', background: 'rgba(255,255,255,0.05)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer' }}>
                            {s.status === 'paused' ? '재개' : '정지'}
                          </button>
                          <button onClick={async () => {
                            await storeCareApi.deleteSchedule(s.id).catch(() => {})
                            load()
                          }} style={{ fontSize: '0.72rem', padding: '3px 8px', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer' }}>
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
              <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>가구매 이력</h3>
              {purchases.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>아직 가구매 이력이 없습니다</div>
              ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>마켓</th>
                    <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>상품명</th>
                    <th style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>금액</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>주문번호</th>
                    <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>상태</th>
                    <th style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>일시</th>
                  </tr>
                </thead>
                <tbody>
                  {purchases.map(h => (
                    <tr key={h.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market_type] || '#888' }} />
                          <span style={{ fontSize: '0.82rem', color: '#E5E5E5' }}>{h.market_type}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px', fontSize: '0.82rem', color: '#C5C5C5', maxWidth: '250px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.product_name}</td>
                      <td style={{ padding: '10px', textAlign: 'right', fontSize: '0.82rem', fontWeight: 600, color: '#E5E5E5' }}>₩{fmt(h.amount)}</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{h.order_no || '-'}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{getStatusBadge(h.status)}</td>
                      <td style={{ padding: '10px', textAlign: 'right', fontSize: '0.75rem', color: '#8A95B0' }}>{h.created_at}</td>
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
                  <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', margin: 0 }}>마켓 점수 · 품절률</h3>
                  <p style={{ fontSize: '0.72rem', color: '#8A95B0', marginTop: '4px' }}>파트너/셀러 포털에서 수집 · 확장앱이 설치·로그인된 PC에서 실행됩니다</p>
                </div>
                <button onClick={runCollect} disabled={collecting} style={{
                  padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', fontWeight: 600,
                  cursor: collecting ? 'default' : 'pointer',
                  background: collecting ? 'rgba(255,255,255,0.08)' : '#FF8C00',
                  color: collecting ? '#8A95B0' : '#000', border: 'none',
                }}>
                  {collecting ? '수집 중…' : '지금 수집'}
                </button>
              </div>

              {/* 💰 추천 구매 갯수 (부족분 계산) */}
              {recs.length > 0 && (
                <div style={{ marginBottom: '18px', padding: '14px', background: 'rgba(255,140,0,0.06)', border: '1px solid rgba(255,140,0,0.25)', borderRadius: '10px' }}>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#FF8C00', marginBottom: '10px' }}>💰 추천 구매 갯수 (목표 도달 부족분)</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                        {['마켓', '목표', '현재', '전체주문수(N)', '추천 구매'].map(h => (
                          <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: '0.72rem', color: '#8A95B0', fontWeight: 500 }}>{h}</th>
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
                          <tr key={r.market_type} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                            <td style={{ padding: '8px', fontSize: '0.82rem', color: '#E5E5E5', fontWeight: 600 }}>
                              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[r.market_type] || '#888', marginRight: '6px' }} />
                              {MARKET_NAME[r.market_type] || r.market_type}
                            </td>
                            <td style={{ padding: '8px', fontSize: '0.78rem', color: '#C5C5C5' }}>{targetLabel(r.target)}</td>
                            <td style={{ padding: '8px', fontSize: '0.82rem', fontWeight: 600, color: ok ? '#E5E5E5' : '#FF6B6B' }}>
                              {ok ? `${r.current_value}%` : '수집 필요'}
                            </td>
                            <td style={{ padding: '8px' }}>
                              <input
                                type="text"
                                inputMode="numeric"
                                placeholder="N 입력"
                                value={nStr}
                                onChange={e => setNInput(prev => ({ ...prev, [r.market_type]: e.target.value }))}
                                style={{ width: '90px', padding: '4px 8px', fontSize: '0.8rem', background: '#1A1A1A', border: '1px solid #3D3D3D', borderRadius: '5px', color: '#E5E5E5' }}
                              />
                            </td>
                            <td style={{ padding: '8px' }}>
                              {qty == null ? (
                                <span style={{ fontSize: '0.78rem', color: '#8A95B0' }}>{nVal == null ? 'N 입력 시 계산' : '—'}</span>
                              ) : (
                                <span style={{ fontSize: '1.05rem', fontWeight: 700, color: qty > 0 ? '#FF8C00' : '#51CF66' }}>{fmt(qty)}개</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  <div style={{ fontSize: '0.68rem', color: '#666', marginTop: '8px' }}>
                    N(전체 주문수)을 입력하면 목표 도달에 필요한 최소 가구매 갯수가 계산돼요. (자동 N 수집은 2단계에서 추가)
                  </div>
                </div>
              )}

              {metrics.length === 0 ? (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
                  아직 수집된 점수가 없습니다. ‘지금 수집’을 눌러주세요.
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
                  {metrics.map(m => (
                    <div key={m.id} style={{ padding: '14px', background: 'rgba(255,255,255,0.02)', border: '1px solid #2D2D2D', borderRadius: '10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[m.market_type] || '#888' }} />
                        <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#E5E5E5' }}>{m.market_type}</span>
                        {m.status === 'failed' && <span style={{ fontSize: '0.68rem', color: '#FF6B6B' }}>수집 실패</span>}
                        <span style={{ marginLeft: 'auto', fontSize: '0.65rem', color: '#555' }}>
                          {m.collected_at ? new Date(m.collected_at).toLocaleString('ko') : ''}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: '16px', marginBottom: '10px' }}>
                        <div>
                          <div style={{ fontSize: '0.65rem', color: '#8A95B0' }}>대표점수</div>
                          <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#4C9AFF' }}>{m.score != null ? m.score : '-'}</div>
                        </div>
                        <div>
                          <div style={{ fontSize: '0.65rem', color: '#8A95B0' }}>품절률</div>
                          <div style={{ fontSize: '1.3rem', fontWeight: 700, color: '#FF8C00' }}>
                            {m.soldout_rate != null ? `${m.soldout_rate}%` : '-'}
                            {m.soldout_rate_prev != null && <span style={{ fontSize: '0.62rem', color: '#555', marginLeft: '4px' }}>(전 {m.soldout_rate_prev}%)</span>}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: '0.65rem', color: '#8A95B0' }}>패널티</div>
                          <div style={{ fontSize: '1.3rem', fontWeight: 700, color: m.penalty ? '#FF6B6B' : '#51CF66' }}>{m.penalty != null ? m.penalty : '-'}</div>
                        </div>
                      </div>
                      {m.grade && <div style={{ fontSize: '0.72rem', color: '#C5C5C5', marginBottom: '6px' }}>등급: {m.grade}</div>}
                      {m.metrics && Object.keys(m.metrics).length > 0 && (
                        <div style={{ borderTop: '1px solid #2D2D2D', paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {Object.entries(m.metrics as Record<string, { value?: number; level?: string }>).map(([k, v]) => (
                            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem' }}>
                              <span style={{ color: '#8A95B0' }}>{k}</span>
                              <span style={{ color: '#E5E5E5' }}>
                                {v && typeof v === 'object' ? `${v.value ?? ''}${v.level ? ` · ${v.level}` : ''}` : String(v)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                      {m.period_label && <div style={{ fontSize: '0.65rem', color: '#555', marginTop: '8px' }}>평가기간 {m.period_label}</div>}
                      {m.status === 'failed' && m.error && <div style={{ fontSize: '0.65rem', color: '#FF6B6B', marginTop: '6px' }}>{m.error}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

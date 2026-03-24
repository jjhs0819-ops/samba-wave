'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { accountApi, orderApi, type SambaMarketAccount, type SambaOrder } from '@/lib/samba/api'

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
  padding: '20px',
}

const MARKET_COLORS: Record<string, string> = {
  smartstore: '#03C75A', coupang: '#E6282B', '11st': '#FF0038',
  lotteon: '#E30613', ssg: '#FF5452', gsshop: '#EC297B',
  lottehome: '#D40030', kream: '#000', ebay: '#E53238',
  toss: '#0064FF', rakuten: '#BF0000', amazon: '#FF9900',
}

function fmt(n: number) { return n.toLocaleString() }

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

// 가구매 더미 데이터 (실제 API 연동 전 UI 확인용)
const DUMMY_SCHEDULES = [
  { id: '1', market: 'smartstore', account_label: '메인스토어', interval_hours: 6, next_run: '2026-03-25 06:00', status: 'scheduled', daily_target: 3, daily_done: 1 },
  { id: '2', market: 'coupang', account_label: '쿠팡 메인', interval_hours: 8, next_run: '2026-03-25 08:00', status: 'scheduled', daily_target: 2, daily_done: 0 },
  { id: '3', market: '11st', account_label: '11번가', interval_hours: 12, next_run: '2026-03-25 12:00', status: 'paused', daily_target: 2, daily_done: 2 },
]

const DUMMY_HISTORY = [
  { id: 'h1', market: 'smartstore', product_name: 'GJ X ALLEN IVERSON 그래픽 반팔티', amount: 32000, status: 'completed', created_at: '2026-03-24 18:32:00', order_no: 'FP-20260324-001' },
  { id: 'h2', market: 'smartstore', product_name: '나이키 에어맥스 97', amount: 189000, status: 'completed', created_at: '2026-03-24 14:15:00', order_no: 'FP-20260324-002' },
  { id: 'h3', market: 'coupang', product_name: '아디다스 삼바 OG', amount: 139000, status: 'failed', created_at: '2026-03-24 10:02:00', order_no: '' },
  { id: 'h4', market: 'smartstore', product_name: '뉴발란스 993', amount: 259000, status: 'completed', created_at: '2026-03-23 22:10:00', order_no: 'FP-20260323-003' },
  { id: 'h5', market: '11st', product_name: '나이키 덩크 로우', amount: 119000, status: 'completed', created_at: '2026-03-23 16:45:00', order_no: 'FP-20260323-004' },
]

export default function StoreCare() {
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [tab, setTab] = useState<'overview' | 'schedule' | 'history'>('overview')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const accs = await accountApi.listActive().catch(() => [])
    setAccounts(accs)
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  // KPI 계산 (더미 기반)
  const todayPurchases = DUMMY_HISTORY.filter(h => h.created_at.startsWith('2026-03-24'))
  const todayTotal = todayPurchases.reduce((s, h) => s + h.amount, 0)
  const todaySuccess = todayPurchases.filter(h => h.status === 'completed').length
  const todayFailed = todayPurchases.filter(h => h.status === 'failed').length
  const activeSchedules = DUMMY_SCHEDULES.filter(s => s.status !== 'paused').length

  // 마켓별 요약
  const marketSummary = DUMMY_SCHEDULES.map(s => ({
    ...s,
    color: MARKET_COLORS[s.market] || '#888',
    todayDone: DUMMY_HISTORY.filter(h => h.market === s.market && h.created_at.startsWith('2026-03-24') && h.status === 'completed').length,
    todayAmount: DUMMY_HISTORY.filter(h => h.market === s.market && h.created_at.startsWith('2026-03-24') && h.status === 'completed').reduce((s, h) => s + h.amount, 0),
  }))

  return (
    <div style={{ padding: '0' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>스토어케어</h2>
          <p style={{ fontSize: '0.78rem', color: '#8A95B0', marginTop: '4px' }}>마켓 점수 관리 · 자동 가구매 · 모니터링</p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {(['overview', 'schedule', 'history'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
              background: tab === t ? '#FF8C00' : 'rgba(255,255,255,0.05)',
              color: tab === t ? '#000' : '#8A95B0',
              border: tab === t ? 'none' : '1px solid #2D2D2D',
            }}>
              {{ overview: '종합현황', schedule: '스케줄 관리', history: '구매 이력' }[t]}
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
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#51CF66' }}>{todaySuccess}건</div>
              {todayFailed > 0 && <div style={{ fontSize: '0.7rem', color: '#FF6B6B', marginTop: '2px' }}>실패 {todayFailed}건</div>}
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>오늘 구매액</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#FF8C00' }}>₩{fmt(todayTotal)}</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>활성 스케줄</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#4C9AFF' }}>{activeSchedules}개</div>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginTop: '2px' }}>전체 {DUMMY_SCHEDULES.length}개</div>
            </div>
            <div style={card}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>연결 마켓</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#E5E5E5' }}>{accounts.length}개</div>
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
                          오늘 {m.todayDone}/{m.daily_target}건 · ₩{fmt(m.todayAmount)}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        {getStatusBadge(m.status)}
                        <div style={{ fontSize: '0.68rem', color: '#555', marginTop: '4px' }}>다음: {m.next_run.split(' ')[1]}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 최근 구매 이력 */}
              <div style={card}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>최근 가구매</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {DUMMY_HISTORY.slice(0, 5).map(h => (
                    <div key={h.id} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px' }}>
                      <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market] || '#888' }} />
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
                  {DUMMY_SCHEDULES.map(s => (
                    <tr key={s.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[s.market] || '#888' }} />
                          <span style={{ fontSize: '0.82rem', color: '#E5E5E5' }}>{s.market}</span>
                        </div>
                      </td>
                      <td style={{ padding: '10px', fontSize: '0.82rem', color: '#C5C5C5' }}>{s.account_label}</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: '#C5C5C5' }}>{s.interval_hours}시간</td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.82rem', color: '#C5C5C5' }}>{s.daily_target}건</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <span style={{ fontSize: '0.82rem', color: s.daily_done >= s.daily_target ? '#51CF66' : '#FFD33D', fontWeight: 600 }}>
                          {s.daily_done}/{s.daily_target}
                        </span>
                      </td>
                      <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.78rem', color: '#8A95B0' }}>{s.next_run}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>{getStatusBadge(s.status)}</td>
                      <td style={{ padding: '10px', textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                          <button style={{ fontSize: '0.72rem', padding: '3px 8px', background: 'rgba(255,255,255,0.05)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer' }}>
                            {s.status === 'paused' ? '재개' : '정지'}
                          </button>
                          <button style={{ fontSize: '0.72rem', padding: '3px 8px', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer' }}>
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
                  {DUMMY_HISTORY.map(h => (
                    <tr key={h.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ padding: '10px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: MARKET_COLORS[h.market] || '#888' }} />
                          <span style={{ fontSize: '0.82rem', color: '#E5E5E5' }}>{h.market}</span>
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
            </div>
          )}
        </>
      )}
    </div>
  )
}

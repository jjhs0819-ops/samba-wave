'use client'

import React, { useCallback, useEffect, useRef, useState, memo } from 'react'
import { monitorApi, collectorApi, type DashboardStats, type MonitorEvent, type RefreshLogEntry } from '@/lib/samba/api'

const POLL_INTERVAL = 30_000
const LOG_POLL_INTERVAL = 5_000

// 오토튠 실시간 로그 (독립 컴포넌트 — 대시보드 리렌더링 영향 없음)
const AutotuneLogPanel = memo(function AutotuneLogPanel({ siteColors, onStatusChange }: {
  siteColors: Record<string, string>
  onStatusChange?: (running: boolean, cycles: number, lastTick: string | null) => void
}) {
  const [logs, setLogs] = useState<RefreshLogEntry[]>([])
  const [intervals, setIntervals] = useState<Record<string, number>>({})
  const sinceIdxRef = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const [res, atStatus] = await Promise.all([
          monitorApi.refreshLogs(sinceIdxRef.current),
          collectorApi.autotuneStatus().catch(() => null),
        ])
        if (res.current_idx < sinceIdxRef.current) {
          sinceIdxRef.current = 0
          return
        }
        if (res.logs.length > 0) {
          setLogs(prev => {
            const next = [...prev, ...res.logs]
            return next.length > 300 ? next.slice(next.length - 300) : next
          })
          sinceIdxRef.current = res.current_idx
          requestAnimationFrame(() => {
            if (containerRef.current) {
              containerRef.current.scrollTop = containerRef.current.scrollHeight
            }
          })
        }
        if (res.intervals?.intervals) {
          setIntervals(res.intervals.intervals)
        }
        // 오토튠 상태 부모에 전달
        if (atStatus && onStatusChange) {
          onStatusChange(atStatus.running, atStatus.cycle_count, atStatus.last_tick)
        }
      } catch { /* 무시 */ }
    }
    poll()
    timerRef.current = setInterval(poll, LOG_POLL_INTERVAL)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [onStatusChange])

  return (
    <div style={{ background: 'rgba(8,10,16,0.98)', border: '1px solid #1C1E2A', borderRadius: '8px', marginBottom: '12px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', background: '#0A0D14', borderBottom: '1px solid #1C1E2A' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#9AA5C0' }}>오토튠 실시간 로그</span>
          <span style={{ fontSize: '0.65rem', color: '#666' }}>5초 폴링</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {Object.keys(intervals).length > 0 && (
            <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.7rem' }}>
              {Object.entries(intervals).map(([site, interval]) => (
                <span key={site} style={{ color: siteColors[site] || '#888' }}>
                  {site} {(interval as number).toFixed(1)}s
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div
        ref={containerRef}
        style={{ height: '250px', overflowY: 'auto', padding: '10px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.73rem', lineHeight: 1.8, color: '#4A5568' }}
      >
        {logs.length === 0 ? (
          <div style={{ color: '#555', textAlign: 'center', padding: '1.5rem 0' }}>
            갱신 로그 대기 중...
          </div>
        ) : (
          logs.map((log, i) => {
            let color = '#DCE0E8'
            if (log.msg.includes('실패') || log.msg.includes('오류') || log.msg.includes('차단')) color = '#C4736E'
            else if (log.msg.includes('전송')) color = '#FFFFFF'
            else if (log.msg.includes('스킵')) color = '#888'
            else if (log.msg.includes('변동')) color = '#FFD93D'
            else if (log.msg.includes('성공')) color = '#7BAF7E'
            return <div key={`${log.ts}-${i}`} style={{ color }}>{log.msg}</div>
          })
        )}
      </div>
    </div>
  )
})

// 색상 상수
const SEV_COLORS: Record<string, string> = {
  critical: '#FF6B6B',
  warning: '#FFD93D',
  info: '#4C9AFF',
}

const PRIORITY_COLORS: Record<string, string> = {
  hot: '#FF6B6B',
  warm: '#FFD93D',
  cold: '#666',
}

const STATUS_COLORS: Record<string, string> = {
  in_stock: '#51CF66',
  sold_out: '#FF6B6B',
  preorder: '#4C9AFF',
}

const LOG_LEVEL_COLORS: Record<string, string> = {
  info: '#4C9AFF',
  warning: '#FFD93D',
  error: '#FF6B6B',
}

const SITE_COLORS: Record<string, string> = {
  MUSINSA: '#4C9AFF',
  KREAM: '#51CF66',
  Nike: '#FF6B6B',
  ABCmart: '#FFD93D',
  Adidas: '#A78BFA',
  GrandStage: '#F472B6',
  LOTTEON: '#FB923C',
  GSShop: '#34D399',
}

const card: React.CSSProperties = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
  padding: '1.25rem',
}

type EventFilter = 'all' | 'critical' | 'price_changed' | 'sold_out' | 'system'
const SYSTEM_TYPES = ['refresh_batch', 'scheduler_tick', 'rate_limited', 'api_structure_changed', 'probe_failed']

type StoreScore = {
  account_id: string; account_label: string; market_type: string
  grade: string; grade_code: string
  good_service: Record<string, number> | null
  penalty: number | null; penalty_rate: number | null
  product_count?: number; max_products?: number
  updated_at: string
}

export default function WarroomPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [events, setEvents] = useState<MonitorEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [lastFetched, setLastFetched] = useState<Date | null>(null)
  const [storeScores, setStoreScores] = useState<Record<string, StoreScore>>({})
  const [scoreTab, setScoreTab] = useState('smartstore')
  const [showPenaltyGuide, setShowPenaltyGuide] = useState(false)
  const [scoreRefreshing, setScoreRefreshing] = useState(false)
  const nextPollRef = useRef(POLL_INTERVAL / 1000)
  const [eventFilter, setEventFilter] = useState<EventFilter>('all')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 실시간 로그 상태

  // 소싱처/마켓 상태
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // 오토튠 상태
  const [autotuneRunning, setAutotuneRunning] = useState(false)
  const [autotuneCycles, setAutotuneCycles] = useState(0)
  const [autotuneLastTick, setAutotuneLastTick] = useState<string | null>(null)
  const [autotuneTarget, setAutotuneTarget] = useState('all')
  const handleAutotuneStatus = useCallback((running: boolean, cycles: number, lastTick: string | null) => {
    setAutotuneRunning(running)
    setAutotuneCycles(cycles)
    setAutotuneLastTick(lastTick)
  }, [])

  const runProbe = async () => {
    setProbeLoading(true)
    try {
      const data = await collectorApi.probeRun() as Record<string, Record<string, Record<string, unknown>>>
      setProbeData(data)
    } catch { /* ignore */ }
    setProbeLoading(false)
  }

  const load = useCallback(async () => {
    try {
      const [dashboard, recentEvents, probeStatus, atStatus, scores] = await Promise.all([
        monitorApi.dashboard().catch(() => null),
        monitorApi.recentEvents(20).catch(() => []),
        collectorApi.probeStatus().catch(() => ({})) as Promise<Record<string, Record<string, Record<string, unknown>>>>,
        collectorApi.autotuneStatus().catch(() => ({ running: false, last_tick: null, cycle_count: 0, target: 'registered' })),
        monitorApi.storeScores().catch(() => ({})),
      ])
      if (dashboard) setStats(dashboard)
      setEvents(recentEvents)
      if (probeStatus && Object.keys(probeStatus).length > 0) setProbeData(probeStatus)
      setAutotuneRunning(atStatus.running)
      setAutotuneCycles(atStatus.cycle_count)
      if (atStatus.target) setAutotuneTarget(atStatus.target)
      if (scores && Object.keys(scores).length > 0) setStoreScores(scores)
      setAutotuneLastTick(atStatus.last_tick)
      setLastFetched(new Date())
      nextPollRef.current = POLL_INTERVAL / 1000
    } catch {
      // 무시
    } finally {
      setLoading(false)
    }
  }, [])

  // 로그 폴링은 AutotuneLogPanel 내부에서 독립적으로 처리

  useEffect(() => {
    load()
  }, [load])

  // 시간 차이 표시
  const timeAgo = (date: Date | null) => {
    if (!date) return '-'
    const diff = Math.floor((Date.now() - date.getTime()) / 1000)
    if (diff < 60) return `${diff}초 전`
    if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
    return `${Math.floor(diff / 3600)}시간 전`
  }

  const isoTimeAgo = (iso: string | null) => {
    if (!iso) return '-'
    return timeAgo(new Date(iso))
  }

  // 이벤트 필터링
  const filteredEvents = events.map(e => ({
    ...e,
    summary: e.summary?.replace(/오토튠\(registered\)\s*—\s*/, '') ?? e.summary,
  })).filter(e => {
    // info severity 이벤트 중 재전송/변동 없는 건 숨기기
    const d = e.detail as Record<string, unknown> | undefined
    if (e.event_type === 'scheduler_tick' && d) {
      const hasChange = (d.retransmitted as number || 0) > 0 || (d.changed as number || 0) > 0 || (d.sold_out as number || 0) > 0 || (d.deleted as number || 0) > 0
      if (!hasChange) return false
    }
    if (eventFilter === 'all') return true
    if (eventFilter === 'critical') return e.severity === 'critical' || e.severity === 'warning'
    if (eventFilter === 'price_changed') return e.event_type === 'price_changed'
    if (eventFilter === 'sold_out') return e.event_type === 'sold_out'
    if (eventFilter === 'system') return SYSTEM_TYPES.includes(e.event_type)
    return true
  })

  if (loading || !stats) {
    return (
      <div style={{ color: '#888', textAlign: 'center', padding: '4rem' }}>
        대시보드 로딩 중...
      </div>
    )
  }

  const { product_stats, refresh_stats, price_change_stats, site_health, market_health, event_summary, hourly_changes } = stats

  // 가로 바 차트 최대값
  const maxBySource = Math.max(...Object.values(product_stats.by_source), 1)
  const maxHourly = Math.max(...hourly_changes, 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* A. 상단 상태바 */}
      <div
        style={{
          ...card,
          padding: '0.75rem 1.25rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderColor: '#FF8C00',
          borderWidth: '1px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: autotuneRunning ? '#51CF66' : '#FF6B6B', display: 'inline-block' }} />
          <span style={{ fontWeight: 700, color: '#FF8C00', fontSize: '0.875rem' }}>오토튠 실시간 모니터링</span>
          {autotuneRunning && <span style={{ fontSize: '0.75rem', color: '#51CF66' }}>실행 중 ({autotuneCycles}회)</span>}
          {!autotuneRunning && <span style={{ fontSize: '0.75rem', color: '#FF6B6B' }}>정지</span>}
        </div>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.8rem', color: '#888', alignItems: 'center' }}>
          <button
            onClick={async () => {
              try {
                if (autotuneRunning) {
                  await collectorApi.autotuneStop()
                  setAutotuneRunning(false)
                } else {
                  await collectorApi.autotuneStart('registered')
                  setAutotuneRunning(true)
                  setAutotuneCycles(0)
                }
              } catch { /* ignore */ }
            }}
            style={{
              padding: '0.25rem 0.75rem',
              background: autotuneRunning ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)',
              border: `1px solid ${autotuneRunning ? 'rgba(239,68,68,0.35)' : 'rgba(34,197,94,0.35)'}`,
              borderRadius: '6px',
              color: autotuneRunning ? '#EF4444' : '#22C55E',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >{autotuneRunning ? '정지' : '시작'}</button>
        </div>
      </div>

      {/* A-2. 마켓별 스토어 현황 분석 */}
      {(() => {
        const MARKET_TABS = [
          { key: 'smartstore', label: '스마트스토어', color: '#51CF66' },
          { key: 'coupang', label: '쿠팡', color: '#FF6B6B' },
          { key: '11st', label: '11번가', color: '#FFD93D' },
          { key: 'lotteon', label: '롯데ON', color: '#FB923C' },
          { key: 'ssg', label: 'SSG', color: '#A78BFA' },
        ]
        const GRADE_COLORS: Record<string, string> = {
          '빅파워': '#FF8C00', '파워': '#4C9AFF', '프리미엄': '#51CF66', '새싹': '#34D399', '씨앗': '#888',
          '연결됨': '#51CF66', '등록됨': '#4C9AFF', '인증 실패': '#FF6B6B', 'Vendor ID 없음': '#FFD93D',
        }
        const tabAccounts = Object.values(storeScores).filter(s => s.market_type === scoreTab)

        return (
          <div style={{ ...card, padding: '1rem 1.25rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.875rem', fontWeight: 700, color: '#E5E5E5' }}>스토어 현황 분석</span>
                <span style={{ fontSize: '0.7rem', color: '#666' }}>{tabAccounts.length}개 계정</span>
              </div>
              <button
                onClick={async () => {
                  setScoreRefreshing(true)
                  try {
                    await monitorApi.refreshStoreScores()
                    const scores = await monitorApi.storeScores()
                    if (scores) setStoreScores(scores)
                  } catch { /* ignore */ }
                  setScoreRefreshing(false)
                }}
                style={{
                  padding: '0.2rem 0.6rem', fontSize: '0.72rem', borderRadius: '5px', cursor: 'pointer',
                  background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.3)', color: '#FF8C00',
                }}
              >{scoreRefreshing ? '조회 중...' : '등급 새로고침'}</button>
              {scoreTab === 'smartstore' && (
                <button
                  onClick={() => setShowPenaltyGuide(true)}
                  style={{
                    padding: '0.2rem 0.6rem', fontSize: '0.72rem', borderRadius: '5px', cursor: 'pointer',
                    background: 'rgba(66,133,244,0.1)', border: '1px solid rgba(66,133,244,0.3)', color: '#4285F4',
                  }}
                >판매관리 기준</button>
              )}
            </div>
            {/* 마켓 탭 */}
            <div style={{ display: 'flex', gap: '0', marginBottom: '0.75rem', borderBottom: '1px solid #2D2D2D' }}>
              {MARKET_TABS.map(tab => (
                <button key={tab.key} onClick={() => setScoreTab(tab.key)} style={{
                  padding: '0.4rem 1rem', fontSize: '0.78rem', fontWeight: scoreTab === tab.key ? 600 : 400, cursor: 'pointer',
                  background: 'transparent', border: 'none', color: scoreTab === tab.key ? tab.color : '#666',
                  borderBottom: scoreTab === tab.key ? `2px solid ${tab.color}` : '2px solid transparent',
                }}>{tab.label}</button>
              ))}
            </div>
            {/* 계정 카드 */}
            {tabAccounts.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.8rem' }}>
                등급 새로고침 버튼을 눌러 계정 정보를 조회하세요
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem' }}>
                {tabAccounts.map(acc => (
                  <div key={acc.account_id} style={{
                    background: 'rgba(20,20,20,0.6)', border: '1px solid #2D2D2D', borderRadius: '10px', padding: '0.875rem',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.6rem' }}>
                      <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#E5E5E5' }}>{acc.account_label}</span>
                      {acc.grade && (
                        <span style={{
                          fontSize: '0.7rem', fontWeight: 700, padding: '2px 8px', borderRadius: '4px',
                          background: `${GRADE_COLORS[acc.grade] || '#888'}20`,
                          color: GRADE_COLORS[acc.grade] || '#888',
                          border: `1px solid ${GRADE_COLORS[acc.grade] || '#888'}50`,
                        }}>{acc.grade}</span>
                      )}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                      <div>
                        <div style={{ fontSize: '0.65rem', color: '#666', marginBottom: '0.3rem' }}>굿서비스 점수</div>
                        {acc.good_service ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                            {Object.entries(acc.good_service).map(([k, v]) => (
                              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem' }}>
                                <span style={{ color: '#999' }}>{k}</span>
                                <span style={{ color: v >= 80 ? '#51CF66' : v >= 50 ? '#FFD93D' : '#FF6B6B', fontWeight: 600 }}>{v}점</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <span style={{ fontSize: '0.7rem', color: '#555' }}>—</span>
                        )}
                      </div>
                      <div>
                        <div style={{ fontSize: '0.65rem', color: '#666', marginBottom: '0.3rem' }}>판매 패널티</div>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.4rem' }}>
                          <span style={{
                            fontSize: '0.85rem', fontWeight: 700,
                            color: (acc.penalty ?? 0) > 0 ? '#FF6B6B' : '#51CF66',
                          }}>{acc.penalty ?? 0}점</span>
                          <span style={{ fontSize: '0.68rem', color: '#888' }}>{acc.penalty_rate ?? 0}%</span>
                        </div>
                      </div>
                      {(acc.max_products !== undefined && acc.max_products > 0) && (
                      <div>
                        <div style={{ fontSize: '0.65rem', color: '#666', marginBottom: '0.3rem' }}>등록 상품</div>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.4rem' }}>
                          <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#4C9AFF' }}>
                            {(acc.product_count ?? 0).toLocaleString()}
                          </span>
                          <span style={{ fontSize: '0.68rem', color: '#888' }}>/ {acc.max_products.toLocaleString()}</span>
                        </div>
                      </div>
                      )}
                    </div>
                    {acc.updated_at && (
                      <div style={{ fontSize: '0.58rem', color: '#444', marginTop: '0.4rem', textAlign: 'right' }}>
                        {new Date(acc.updated_at).toLocaleString('ko')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })()}

      {/* B. KPI 카드 행 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem' }}>
        {/* 전체 상품 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>전체 상품</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#E5E5E5' }}>
            {product_stats.total.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem', display: 'flex', gap: '0.5rem' }}>
            {Object.entries(product_stats.by_priority).map(([k, v]) => (
              <span key={k} style={{ color: PRIORITY_COLORS[k] || '#888' }}>
                {k} {v}
              </span>
            ))}
          </div>
        </div>

        {/* 24시간 오토튠 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>24시간 오토튠</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#4C9AFF' }}>
            {refresh_stats.refreshed_24h.toLocaleString()}
          </div>
        </div>

        {/* 가격 변동 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>가격 변동</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FFD93D' }}>
            {price_change_stats.changes_24h}건
          </div>
          <div style={{ fontSize: '0.7rem', color: price_change_stats.avg_change_pct < 0 ? '#FF6B6B' : '#51CF66', marginTop: '0.25rem' }}>
            평균 {price_change_stats.avg_change_pct > 0 ? '+' : ''}{price_change_stats.avg_change_pct}%
          </div>
        </div>

        {/* 에러 상품 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>에러 상품</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: refresh_stats.error_products > 0 ? '#FF6B6B' : '#51CF66' }}>
            {refresh_stats.error_products}
          </div>
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem' }}>
            연속실패
          </div>
        </div>
      </div>

      {/* C. 소싱처/마켓 헬스 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        {/* 소싱처 헬스 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>소싱처 상태</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ textAlign: 'left', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>소싱처</th>
                <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>상태</th>
                <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>인터벌</th>
                <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>에러</th>
                <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>응답</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(site_health).map(([site, h]) => (
                <tr key={site} style={{ borderBottom: '1px solid #1D1D1D' }}>
                  <td style={{ padding: '0.4rem 0.5rem', color: '#E5E5E5' }}>{site}</td>
                  <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center' }}>
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                      color: h.probe_ok === true ? '#51CF66' : h.probe_ok === false ? '#FF6B6B' : '#888',
                      fontSize: '0.75rem',
                    }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
                        background: h.probe_ok === true ? '#51CF66' : h.probe_ok === false ? '#FF6B6B' : '#888',
                      }} />
                      {h.probe_ok === true ? '정상' : h.probe_ok === false ? '이상' : site === 'KREAM' ? '확장앱' : '-'}
                    </span>
                  </td>
                  <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center', color: h.interval > 2 ? '#FFD93D' : '#E5E5E5' }}>
                    {h.interval.toFixed(1)}s
                  </td>
                  <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center', color: h.errors > 0 ? '#FF6B6B' : '#E5E5E5' }}>
                    {h.errors}
                  </td>
                  <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center', color: '#E5E5E5' }}>
                    {h.latency_ms != null ? `${h.latency_ms}ms` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 마켓 헬스 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>마켓 상태</div>
          {Object.keys(market_health).length === 0 ? (
            <div style={{ fontSize: '0.8rem', color: '#666', padding: '1rem 0' }}>마켓 Probe 데이터 없음</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                  <th style={{ textAlign: 'left', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>마켓</th>
                  <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>상태</th>
                  <th style={{ textAlign: 'center', padding: '0.4rem 0.5rem', color: '#888', fontWeight: 500 }}>응답</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(market_health).map(([mt, h]) => (
                  <tr key={mt} style={{ borderBottom: '1px solid #1D1D1D' }}>
                    <td style={{ padding: '0.4rem 0.5rem', color: '#E5E5E5' }}>{mt}</td>
                    <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center' }}>
                      <span style={{
                        display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                        color: h.probe_ok ? '#51CF66' : '#FF6B6B',
                        fontSize: '0.75rem',
                      }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
                          background: h.probe_ok ? '#51CF66' : '#FF6B6B',
                        }} />
                        {h.probe_ok ? '정상' : h.error || '이상'}
                      </span>
                    </td>
                    <td style={{ padding: '0.4rem 0.5rem', textAlign: 'center', color: '#E5E5E5' }}>
                      {h.latency_ms}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* D. 가격 변동 추이 + TOP 10 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        {/* 24시간 세로 바 차트 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>24시간 가격 변동 추이</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '2px', height: '120px' }}>
            {hourly_changes.map((v, i) => {
              const heightPct = (v / maxHourly) * 100
              return (
                <div
                  key={i}
                  style={{
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    height: '100%',
                  }}
                >
                  {v > 0 && (
                    <span style={{ fontSize: '0.6rem', color: '#888', marginBottom: '2px' }}>{v}</span>
                  )}
                  <div
                    style={{
                      width: '100%',
                      height: `${Math.max(heightPct, v > 0 ? 4 : 1)}%`,
                      background: v > 0 ? '#FF8C00' : '#2D2D2D',
                      borderRadius: '2px 2px 0 0',
                      minHeight: '2px',
                      transition: 'height 0.3s',
                    }}
                  />
                </div>
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', fontSize: '0.6rem', color: '#666' }}>
            <span>0시</span>
            <span>6시</span>
            <span>12시</span>
            <span>18시</span>
            <span>23시</span>
          </div>
        </div>

        {/* TOP 10 가격 변동 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>가격 변동 TOP 10</div>
          {price_change_stats.top_changes.length === 0 ? (
            <div style={{ fontSize: '0.8rem', color: '#666', padding: '1rem 0' }}>최근 24시간 가격 변동 없음</div>
          ) : (
            <div style={{ fontSize: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              {price_change_stats.top_changes.map((c, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    padding: '0.3rem 0',
                    borderBottom: '1px solid #1D1D1D',
                  }}
                >
                  <span style={{ color: '#888', minWidth: '1rem' }}>{i + 1}</span>
                  <span style={{ flex: 1, color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.name || c.product_id}
                  </span>
                  <span style={{ color: '#888', whiteSpace: 'nowrap' }}>
                    ₩{c.old.toLocaleString()}
                  </span>
                  <span style={{ color: '#888' }}>→</span>
                  <span style={{ color: '#E5E5E5', whiteSpace: 'nowrap' }}>
                    ₩{c.new.toLocaleString()}
                  </span>
                  <span style={{
                    color: c.pct < 0 ? '#FF6B6B' : '#51CF66',
                    fontWeight: 600,
                    minWidth: '3rem',
                    textAlign: 'right',
                  }}>
                    {c.pct > 0 ? '+' : ''}{c.pct}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* E. 상품 분포 (3개 가로 바) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
        {/* 소싱처별 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>소싱처별 분포</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {Object.entries(product_stats.by_source)
              .sort((a, b) => b[1] - a[1])
              .map(([site, cnt]) => (
                <div key={site} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.7rem', color: '#888', minWidth: '5rem' }}>{site}</span>
                  <div style={{ flex: 1, height: '14px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${(cnt / maxBySource) * 100}%`,
                      height: '100%',
                      background: SITE_COLORS[site] || '#FF8C00',
                      borderRadius: '3px',
                      transition: 'width 0.3s',
                    }} />
                  </div>
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{cnt}</span>
                </div>
              ))}
          </div>
        </div>

        {/* 우선순위별 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>우선순위별 분포</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {['hot', 'warm', 'cold'].map(p => {
              const cnt = product_stats.by_priority[p] || 0
              const maxP = Math.max(...Object.values(product_stats.by_priority), 1)
              return (
                <div key={p} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.7rem', color: PRIORITY_COLORS[p], minWidth: '3rem', fontWeight: 600 }}>{p}</span>
                  <div style={{ flex: 1, height: '14px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${(cnt / maxP) * 100}%`,
                      height: '100%',
                      background: PRIORITY_COLORS[p],
                      borderRadius: '3px',
                      transition: 'width 0.3s',
                    }} />
                  </div>
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{cnt}</span>
                </div>
              )
            })}
          </div>
        </div>

        {/* 상태별 */}
        <div style={card}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00', marginBottom: '0.75rem' }}>판매상태별 분포</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {Object.entries(product_stats.by_sale_status).map(([status, cnt]) => {
              const maxS = Math.max(...Object.values(product_stats.by_sale_status), 1)
              return (
                <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <span style={{ fontSize: '0.7rem', color: STATUS_COLORS[status] || '#888', minWidth: '4.5rem' }}>{status}</span>
                  <div style={{ flex: 1, height: '14px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${(cnt / maxS) * 100}%`,
                      height: '100%',
                      background: STATUS_COLORS[status] || '#666',
                      borderRadius: '3px',
                      transition: 'width 0.3s',
                    }} />
                  </div>
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{cnt}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* F. 오토튠 실시간 로그 (독립 컴포넌트) */}
      <AutotuneLogPanel
        siteColors={SITE_COLORS}
        onStatusChange={handleAutotuneStatus}
      />

      {/* G. 이벤트 타임라인 */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00' }}>이벤트 타임라인</div>
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            {([
              ['all', '전체'],
              ['critical', '중요'],
              ['price_changed', '가격변동'],
              ['sold_out', '품절'],
              ['system', '시스템'],
            ] as [EventFilter, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setEventFilter(key)}
                style={{
                  padding: '0.25rem 0.75rem',
                  fontSize: '0.7rem',
                  borderRadius: '4px',
                  border: '1px solid',
                  borderColor: eventFilter === key ? '#FF8C00' : '#3D3D3D',
                  background: eventFilter === key ? 'rgba(255,140,0,0.15)' : 'transparent',
                  color: eventFilter === key ? '#FF8C00' : '#888',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {filteredEvents.length === 0 ? (
          <div style={{ fontSize: '0.8rem', color: '#666', padding: '1rem 0', textAlign: 'center' }}>이벤트 없음</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', maxHeight: '360px', overflow: 'auto' }}>
            {filteredEvents.map(e => {
              const t = new Date(e.created_at)
              const timeStr = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
              const d = e.detail as Record<string, unknown> | undefined
              // detail에서 표시할 태그 목록 생성
              const detailTags: { label: string; value: string; color: string }[] = []
              if (d) {
                if (d.old_price != null && d.new_price != null) {
                  const diff = d.diff_pct as number | undefined
                  const sign = diff && diff > 0 ? '+' : ''
                  detailTags.push({
                    label: '가격',
                    value: `₩${Number(d.old_price).toLocaleString()} → ₩${Number(d.new_price).toLocaleString()}${diff != null ? ` (${sign}${diff}%)` : ''}`,
                    color: (diff ?? 0) > 0 ? '#FF6B6B' : '#51CF66',
                  })
                }
                if (typeof d.refreshed === 'number' && d.refreshed > 0)
                  detailTags.push({ label: '갱신', value: `${d.refreshed}건`, color: '#4C9AFF' })
                if (typeof d.changed === 'number' && d.changed > 0)
                  detailTags.push({ label: '변동', value: `${d.changed}건`, color: '#FFD93D' })
                if (typeof d.sold_out === 'number' && d.sold_out > 0)
                  detailTags.push({ label: '품절', value: `${d.sold_out}건`, color: '#FF6B6B' })
                if (typeof d.retransmitted === 'number' && d.retransmitted > 0)
                  detailTags.push({ label: '재전송', value: `${d.retransmitted}건`, color: '#A78BFA' })
                if (typeof d.deleted === 'number' && d.deleted > 0)
                  detailTags.push({ label: '삭제', value: `${d.deleted}건`, color: '#FF6B6B' })
                if (typeof d.count === 'number' && d.count > 0 && detailTags.length === 0)
                  detailTags.push({ label: '건수', value: `${d.count}건`, color: '#4C9AFF' })
                if (d.error && typeof d.error === 'string')
                  detailTags.push({ label: '에러', value: String(d.error).slice(0, 60), color: '#FF6B6B' })
                if (Array.isArray(d.missing_fields) && d.missing_fields.length > 0)
                  detailTags.push({ label: '누락필드', value: (d.missing_fields as string[]).join(', '), color: '#FFD93D' })
              }
              return (
                <div
                  key={e.id}
                  style={{
                    padding: '0.4rem 0.5rem',
                    borderRadius: '6px',
                    background: e.severity === 'critical' ? 'rgba(255,107,107,0.08)' : 'transparent',
                    borderBottom: '1px solid #1A1A1A',
                  }}
                >
                  {/* 메인 로그 */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: SEV_COLORS[e.severity] || '#666',
                      marginTop: '4px', flexShrink: 0,
                    }} />
                    <span style={{ fontSize: '0.75rem', color: '#666', minWidth: '3rem', flexShrink: 0 }}>{timeStr}</span>
                    <span style={{ fontSize: '0.8rem', color: '#E5E5E5', flex: 1 }}>{e.summary}</span>
                    {e.source_site && (
                      <span style={{
                        fontSize: '0.65rem', color: SITE_COLORS[e.source_site] || '#888',
                        padding: '0.1rem 0.3rem', borderRadius: '3px',
                        background: 'rgba(255,255,255,0.05)', flexShrink: 0,
                      }}>
                        {e.source_site}
                      </span>
                    )}
                  </div>
                  {/* 변동 정보 — 배지 제거, summary에 포함 */}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 소싱처/마켓 상태 대시보드 */}
      <div style={{ ...card, padding: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#51CF66' }}>소싱처/마켓 상태</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>소싱처 API 구조 변경 및 마켓 인증 상태를 실시간으로 확인합니다.</span>
          <button
            onClick={runProbe}
            disabled={probeLoading}
            style={{ marginLeft: 'auto', background: probeLoading ? 'rgba(50,50,50,0.5)' : 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: probeLoading ? '#666' : '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: probeLoading ? 'default' : 'pointer' }}
          >{probeLoading ? '체크 중...' : '수동 체크'}</button>
        </div>

        {/* 소싱처 */}
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#888', marginBottom: '0.5rem' }}>소싱처</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {Object.entries(probeData?.sources || {}).length === 0 ? (
              <span style={{ fontSize: '0.8125rem', color: '#555' }}>수동 체크 버튼으로 상태를 확인하세요</span>
            ) : (
              Object.entries(probeData?.sources || {}).map(([site, info]) => {
                const d = info as Record<string, unknown>
                const isOk = d.ok === true
                const latency = Number(d.latency_ms || 0)
                const missing = (d.missing_fields as string[]) || []
                const error = d.error as string | null
                const checkedAt = d.checked_at ? new Date(d.checked_at as string).toLocaleString('ko-KR', { hour12: false }) : '-'
                return (
                  <div key={site} style={{ padding: '0.625rem 1rem', borderRadius: '8px', minWidth: '200px', background: isOk ? 'rgba(81,207,102,0.08)' : 'rgba(255,107,107,0.08)', border: `1px solid ${isOk ? 'rgba(81,207,102,0.3)' : 'rgba(255,107,107,0.3)'}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: isOk ? '#51CF66' : '#FF6B6B' }} />
                      <span style={{ fontWeight: 600, fontSize: '0.875rem', color: '#E5E5E5' }}>{site}</span>
                      <span style={{ fontSize: '0.75rem', color: '#888' }}>{latency}ms</span>
                    </div>
                    {missing.length > 0 && <div style={{ fontSize: '0.75rem', color: '#FFD93D' }}>누락 필드: {missing.join(', ')}</div>}
                    {error && <div style={{ fontSize: '0.75rem', color: '#FF6B6B' }}>{error}</div>}
                    <div style={{ fontSize: '0.6875rem', color: '#555', marginTop: '0.25rem' }}>{checkedAt}</div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* 마켓 */}
        <div>
          <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#888', marginBottom: '0.5rem' }}>마켓</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {Object.entries(probeData?.markets || {}).length === 0 ? (
              <span style={{ fontSize: '0.8125rem', color: '#555' }}>수동 체크 버튼으로 상태를 확인하세요</span>
            ) : (
              Object.entries(probeData?.markets || {}).map(([mt, info]) => {
                const d = info as Record<string, unknown>
                const isOk = d.ok === true
                const latency = Number(d.latency_ms || 0)
                const error = d.error as string | null
                const checkedAt = d.checked_at ? new Date(d.checked_at as string).toLocaleString('ko-KR', { hour12: false }) : '-'
                return (
                  <div key={mt} style={{ padding: '0.5rem 0.875rem', borderRadius: '8px', minWidth: '140px', background: isOk ? 'rgba(81,207,102,0.06)' : error === '설정 없음' ? 'rgba(100,100,100,0.1)' : 'rgba(255,107,107,0.06)', border: `1px solid ${isOk ? 'rgba(81,207,102,0.25)' : error === '설정 없음' ? 'rgba(100,100,100,0.3)' : 'rgba(255,107,107,0.25)'}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginBottom: '0.125rem' }}>
                      <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: isOk ? '#51CF66' : error === '설정 없음' ? '#555' : '#FF6B6B' }} />
                      <span style={{ fontWeight: 600, fontSize: '0.8125rem', color: '#E5E5E5' }}>{mt}</span>
                      {latency > 0 && <span style={{ fontSize: '0.6875rem', color: '#888' }}>{latency}ms</span>}
                    </div>
                    {error && <div style={{ fontSize: '0.6875rem', color: error === '설정 없음' ? '#666' : '#FF6B6B' }}>{error}</div>}
                    <div style={{ fontSize: '0.625rem', color: '#555' }}>{checkedAt}</div>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>
      {/* 스마트스토어 판매관리 기준 모달 */}
      {showPenaltyGuide && (
        <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', background: 'rgba(0,0,0,0.7)', zIndex: 9999, display: 'flex', justifyContent: 'center', alignItems: 'center' }} onClick={() => setShowPenaltyGuide(false)}>
          <div style={{ background: '#1A1A1A', border: '1px solid #333', borderRadius: '12px', width: '90%', maxWidth: '900px', maxHeight: '85vh', overflow: 'auto', padding: '2rem' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#4285F4' }}>스마트스토어 판매관리 프로그램</h2>
              <button onClick={() => setShowPenaltyGuide(false)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.5rem', cursor: 'pointer' }}>x</button>
            </div>
            <p style={{ fontSize: '0.8125rem', color: '#AAA', marginBottom: '1.5rem', lineHeight: 1.6 }}>
              소비자 권익을 해칠 수 있는 판매활동이 확인되면 페널티가 부여되며, 점수가 누적되면 단계적 제재를 받습니다.
            </p>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FF8C00', marginBottom: '0.75rem' }}>페널티 부과 기준</h3>
            <div style={{ overflowX: 'auto', marginBottom: '1.5rem' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem', minWidth: '700px' }}>
                <thead>
                  <tr style={{ background: 'rgba(255,140,0,0.1)' }}>
                    <th style={{ padding: '0.5rem', textAlign: 'left', color: '#FFB84D', borderBottom: '1px solid #333' }}>항목</th>
                    <th style={{ padding: '0.5rem', textAlign: 'left', color: '#FFB84D', borderBottom: '1px solid #333' }}>상세 기준</th>
                    <th style={{ padding: '0.5rem', textAlign: 'center', color: '#FFB84D', borderBottom: '1px solid #333' }}>일반</th>
                    <th style={{ padding: '0.5rem', textAlign: 'center', color: '#FFB84D', borderBottom: '1px solid #333' }}>오늘출발</th>
                    <th style={{ padding: '0.5rem', textAlign: 'center', color: '#FFB84D', borderBottom: '1px solid #333' }}>정기구독</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['발송처리 지연', '발송처리기한까지 미발송', '1점', '1점', '1점'],
                    ['발송처리 지연 (4영업일)', '발송처리기한 +4영업일 경과 후 미발송', '3점', '3점', '3점'],
                    ['발송지연 후 미발송', '발송지연 처리 후 발송예정일까지 미발송', '2점', '3점', '3점'],
                    ['허위 송장 (국내)', '송장 입력 +2영업일까지 배송상태 없음', '3점', '3점', '3점'],
                    ['허위 송장 (해외)', '송장 입력 +15영업일까지 배송상태 없음', '3점', '3점', '3점'],
                    ['품절취소', '취소 사유가 품절', '2점', '2점', '3점'],
                    ['품절취소 (선물하기)', '선물하기 주문 품절 취소', '3점', '3점', '-'],
                    ['반품 처리지연', '수거 완료일 +3영업일 이상 경과', '1점', '1점', '1점'],
                    ['교환 처리지연', '수거 완료일 +3영업일 이상 경과', '1점', '1점', '1점'],
                  ].map(([item, desc, normal, today, sub], i) => (
                    <tr key={i} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ padding: '0.5rem', color: '#E5E5E5', fontWeight: 600 }}>{item}</td>
                      <td style={{ padding: '0.5rem', color: '#AAA' }}>{desc}</td>
                      <td style={{ padding: '0.5rem', textAlign: 'center', color: '#FF6B6B', fontWeight: 600 }}>{normal}</td>
                      <td style={{ padding: '0.5rem', textAlign: 'center', color: '#FF6B6B', fontWeight: 600 }}>{today}</td>
                      <td style={{ padding: '0.5rem', textAlign: 'center', color: '#FF6B6B', fontWeight: 600 }}>{sub}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FF8C00', marginBottom: '0.75rem' }}>발송처리기한</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.5rem' }}>
              {[
                ['일반 발송', '결제완료일 + 3영업일'],
                ['오늘 출발', '설정시간 내 결제 → 당일 / 이후 → +1영업일'],
                ['정기 구독', '결제완료일 + 1영업일'],
                ['희망배송일', '희망배송일 당일'],
              ].map(([type, limit], i) => (
                <div key={i} style={{ background: 'rgba(30,30,30,0.8)', padding: '0.625rem 0.75rem', borderRadius: '6px', border: '1px solid #2D2D2D' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#FFB84D' }}>{type}</span>
                  <span style={{ fontSize: '0.75rem', color: '#AAA', marginLeft: '0.5rem' }}>{limit}</span>
                </div>
              ))}
            </div>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FF8C00', marginBottom: '0.75rem' }}>단계별 제재</h3>
            <p style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.75rem' }}>최근 30일 페널티 10점 이상 + 페널티 비율 40% 이상 시 적용 (마지막 제재일로부터 1년간 누적)</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem' }}>
              <div style={{ background: 'rgba(255,200,50,0.08)', padding: '1rem', borderRadius: '8px', border: '1px solid rgba(255,200,50,0.2)' }}>
                <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#FFD93D', marginBottom: '0.5rem' }}>1단계 — 주의</div>
                <p style={{ fontSize: '0.7rem', color: '#AAA', lineHeight: 1.5 }}>최초 발생 시 주의 통보. 제재 없음.</p>
              </div>
              <div style={{ background: 'rgba(255,140,0,0.08)', padding: '1rem', borderRadius: '8px', border: '1px solid rgba(255,140,0,0.2)' }}>
                <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#FF8C00', marginBottom: '0.5rem' }}>2단계 — 경고</div>
                <p style={{ fontSize: '0.7rem', color: '#AAA', lineHeight: 1.5 }}>7일간 신규 상품 등록 금지 (센터 + API)</p>
              </div>
              <div style={{ background: 'rgba(255,80,80,0.08)', padding: '1rem', borderRadius: '8px', border: '1px solid rgba(255,80,80,0.2)' }}>
                <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#FF6B6B', marginBottom: '0.5rem' }}>3단계 — 이용제한</div>
                <p style={{ fontSize: '0.7rem', color: '#AAA', lineHeight: 1.5 }}>판매 활동 전면 제한, 정산 비즈월렛 전환</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

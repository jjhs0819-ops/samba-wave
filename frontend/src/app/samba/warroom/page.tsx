'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { monitorApi, collectorApi, type DashboardStats, type MonitorEvent, type RefreshLogEntry } from '@/lib/samba/api'

const POLL_INTERVAL = 30_000
const LOG_POLL_INTERVAL = 5_000

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

export default function WarroomPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [events, setEvents] = useState<MonitorEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [lastFetched, setLastFetched] = useState<Date | null>(null)
  const [nextPoll, setNextPoll] = useState(POLL_INTERVAL / 1000)
  const [eventFilter, setEventFilter] = useState<EventFilter>('all')
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 실시간 로그 상태
  const [refreshLogs, setRefreshLogs] = useState<RefreshLogEntry[]>([])
  const [logSinceIdx, setLogSinceIdx] = useState(0)
  const [siteIntervals, setSiteIntervals] = useState<Record<string, number>>({})
  const logContainerRef = useRef<HTMLDivElement>(null)
  const logTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 소싱처/마켓 상태
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // 오토튠 상태
  const [autotuneRunning, setAutotuneRunning] = useState(false)
  const [autotuneCycles, setAutotuneCycles] = useState(0)
  const [autotuneLastTick, setAutotuneLastTick] = useState<string | null>(null)

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
      const [dashboard, recentEvents, probeStatus, atStatus] = await Promise.all([
        monitorApi.dashboard().catch(() => null),
        monitorApi.recentEvents(20).catch(() => []),
        collectorApi.probeStatus().catch(() => ({})) as Promise<Record<string, Record<string, Record<string, unknown>>>>,
        collectorApi.autotuneStatus().catch(() => ({ running: false, last_tick: null, cycle_count: 0 })),
      ])
      if (dashboard) setStats(dashboard)
      setEvents(recentEvents)
      if (probeStatus && Object.keys(probeStatus).length > 0) setProbeData(probeStatus)
      setAutotuneRunning(atStatus.running)
      setAutotuneCycles(atStatus.cycle_count)
      setAutotuneLastTick(atStatus.last_tick)
      setLastFetched(new Date())
      setNextPoll(POLL_INTERVAL / 1000)
    } catch {
      // 무시
    } finally {
      setLoading(false)
    }
  }, [])

  // 실시간 로그 폴링
  const loadLogs = useCallback(async () => {
    try {
      const res = await monitorApi.refreshLogs(logSinceIdx)
      if (res.logs.length > 0) {
        setRefreshLogs(prev => {
          const next = [...prev, ...res.logs]
          // 최대 300건 유지
          return next.length > 300 ? next.slice(next.length - 300) : next
        })
        setLogSinceIdx(res.current_idx)
        // 자동 스크롤
        requestAnimationFrame(() => {
          if (logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
          }
        })
      }
      if (res.intervals?.intervals) {
        setSiteIntervals(res.intervals.intervals)
      }
    } catch {
      // 무시
    }
  }, [logSinceIdx])

  useEffect(() => {
    load()
    loadLogs()
    timerRef.current = setInterval(load, POLL_INTERVAL)
    logTimerRef.current = setInterval(loadLogs, LOG_POLL_INTERVAL)
    countdownRef.current = setInterval(() => {
      setNextPoll(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (countdownRef.current) clearInterval(countdownRef.current)
      if (logTimerRef.current) clearInterval(logTimerRef.current)
    }
  }, [load, loadLogs])

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
  const filteredEvents = events.filter(e => {
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
          <span>마지막 갱신: {timeAgo(lastFetched)}</span>
          <span>다음 폴링: {nextPoll}초 후</span>
          <button
            onClick={async () => {
              try {
                if (autotuneRunning) {
                  await collectorApi.autotuneStop()
                  setAutotuneRunning(false)
                } else {
                  await collectorApi.autotuneStart()
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
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem' }}>
            마지막 {isoTimeAgo(refresh_stats.last_refreshed_at)}
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

      {/* F. 오토튠 실시간 로그 */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FF8C00' }}>오토튠 실시간 로그</span>
            <span style={{ fontSize: '0.65rem', color: '#666' }}>5초 폴링</span>
          </div>
          {Object.keys(siteIntervals).length > 0 && (
            <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.7rem' }}>
              {Object.entries(siteIntervals).map(([site, interval]) => (
                <span key={site} style={{ color: SITE_COLORS[site] || '#888' }}>
                  {site} {interval.toFixed(1)}s
                </span>
              ))}
            </div>
          )}
        </div>
        <div
          ref={logContainerRef}
          style={{
            maxHeight: '240px',
            overflow: 'auto',
            background: '#0A0A0A',
            borderRadius: '6px',
            padding: '0.5rem',
            fontFamily: 'monospace',
            fontSize: '0.72rem',
            lineHeight: '1.5',
          }}
        >
          {refreshLogs.length === 0 ? (
            <div style={{ color: '#555', textAlign: 'center', padding: '1.5rem 0' }}>
              갱신 로그 대기 중...
            </div>
          ) : (
            refreshLogs.map((log, i) => {
              const t = new Date(log.ts)
              const timeStr = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}:${String(t.getSeconds()).padStart(2, '0')}`
              return (
                <div
                  key={`${log.ts}-${i}`}
                  style={{
                    display: 'flex',
                    gap: '0.5rem',
                    padding: '0.15rem 0',
                    borderBottom: '1px solid #1A1A1A',
                    color: LOG_LEVEL_COLORS[log.level] || '#888',
                  }}
                >
                  <span style={{ color: '#555', flexShrink: 0 }}>{timeStr}</span>
                  <span style={{
                    color: SITE_COLORS[log.site] || '#888',
                    minWidth: '4.5rem',
                    flexShrink: 0,
                  }}>
                    {log.site}
                  </span>
                  <span style={{
                    color: log.level === 'error' ? '#FF6B6B' : log.level === 'warning' ? '#FFD93D' : '#E5E5E5',
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {log.msg}
                  </span>
                  {log.name && (
                    <span style={{ color: '#555', flexShrink: 0, maxWidth: '10rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {log.name}
                    </span>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

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
              return (
                <div
                  key={e.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '0.75rem',
                    padding: '0.4rem 0.5rem',
                    borderRadius: '6px',
                    background: e.severity === 'critical' ? 'rgba(255,107,107,0.08)' : 'transparent',
                    borderBottom: '1px solid #1A1A1A',
                  }}
                >
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: SEV_COLORS[e.severity] || '#666',
                    marginTop: '4px', flexShrink: 0,
                  }} />
                  <span style={{ fontSize: '0.75rem', color: '#666', minWidth: '3rem', flexShrink: 0 }}>{timeStr}</span>
                  <span style={{
                    fontSize: '0.7rem',
                    padding: '0.1rem 0.4rem',
                    borderRadius: '3px',
                    background: `${SEV_COLORS[e.severity] || '#666'}22`,
                    color: SEV_COLORS[e.severity] || '#666',
                    flexShrink: 0,
                  }}>
                    {e.severity}
                  </span>
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
    </div>
  )
}

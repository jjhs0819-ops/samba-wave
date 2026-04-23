'use client'

import React, { useCallback, useEffect, useRef, useState, memo } from 'react'
import { collectorApi } from '@/lib/samba/api/commerce'
import { fetchWithAuth } from '@/lib/samba/api/shared'
import { monitorApi, type DashboardStats, type MonitorEvent, type RefreshLogEntry } from '@/lib/samba/api/operations'
import { SITE_COLORS } from '@/lib/samba/constants'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'

const POLL_INTERVAL = 30_000
const LOG_POLL_INTERVAL = 500

// 오토튠 실시간 로그 (독립 컴포넌트 — 대시보드 리렌더링 영향 없음)
const AutotuneLogPanel = memo(function AutotuneLogPanel({ siteColors, onStatusChange, externalRunning }: {
  siteColors: Record<string, string>
  onStatusChange?: (running: boolean, cycles: number, lastTick: string | null, refreshed: number) => void
  externalRunning?: boolean
}) {
  const [logs, setLogs] = useState<RefreshLogEntry[]>([])
  const [intervals, setIntervals] = useState<Record<string, number>>({})
  const sinceIdxRef = useRef(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 단일 useEffect로 폴링 관리 — 타이머 중복 방지
  const pollingRef = useRef(false)

  // 마운트 시 오토튠 상태 자동 감지 (탭 재진입 대응)
  const [selfDetectedRunning, setSelfDetectedRunning] = useState(false)
  const isRunning = externalRunning || selfDetectedRunning

  useEffect(() => {
    // 마운트 직후 서버 상태 확인 — running이면 자동 폴링 시작
    collectorApi.autotuneStatus().then(st => {
      if (st) {
        if (onStatusChange) onStatusChange(st.running, st.cycle_count, st.last_tick, st.refreshed_count || 0)
        if (st.running) setSelfDetectedRunning(true)
      }
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // 오토튠 꺼져있으면 폴링 안 함
    if (!isRunning) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      return
    }

    // 이미 타이머가 있으면 중복 생성 안 함
    if (timerRef.current) return

    const poll = async () => {
      if (pollingRef.current) return
      pollingRef.current = true
      try {
        const atStatus = await collectorApi.autotuneStatus().catch(() => null)
        if (atStatus) {
          if (onStatusChange) onStatusChange(atStatus.running, atStatus.cycle_count, atStatus.last_tick, atStatus.refreshed_count || 0)
          if (!atStatus.running) setSelfDetectedRunning(false)
        }
        // running 상태와 무관하게 로그 폴링 유지 (별도 스레드 타이밍 차이 대응)
        const idx = sinceIdxRef.current
        const res = await monitorApi.refreshLogs(idx)
        if (res.current_idx < idx) {
          sinceIdxRef.current = 0
          pollingRef.current = false
          return
        }
        if (res.logs.length > 0 && res.current_idx > idx) {
          sinceIdxRef.current = res.current_idx
          setLogs(prev => {
            const next = [...prev, ...res.logs]
            return next.slice(-30)
          })
          requestAnimationFrame(() => {
            if (containerRef.current) {
              containerRef.current.scrollTop = containerRef.current.scrollHeight
            }
          })
        }
        if (res.intervals?.intervals) {
          setIntervals(res.intervals.intervals)
        }
      } catch { /* 무시 */ }
      pollingRef.current = false
    }
    poll()
    timerRef.current = setInterval(poll, LOG_POLL_INTERVAL)

    return () => {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    }
  }, [isRunning, onStatusChange])

  return (
    <div style={{ background: 'rgba(8,10,16,0.98)', border: '1px solid #1C1E2A', borderRadius: '8px', marginBottom: '12px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', background: '#0A0D14', borderBottom: '1px solid #1C1E2A' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#9AA5C0' }}>오토튠 실시간 로그</span>
          <span style={{ fontSize: '0.65rem', color: '#666' }}>실시간</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {Object.keys(intervals).length > 0 && (
            <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.7rem' }}>
              {Object.entries(intervals).filter(([, v]) => (v as number) > 0).map(([site, interval]) => (
                <span key={site} style={{ color: siteColors[site] || '#888' }}>
                  {site} {(interval as number).toFixed(1)}s
                </span>
              ))}
            </div>
          )}
          <button onClick={() => {
            const text = logs.map(l => l.msg).join('\n')
            navigator.clipboard.writeText(text)
          }} style={{ padding: '2px 8px', fontSize: '0.65rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
          <button onClick={async () => {
            setLogs([]); sinceIdxRef.current = 0
            try {
              const { API_BASE_URL: apiBase } = await import('@/config/api')
              await fetchWithAuth(`${apiBase}/api/v1/samba/monitor/refresh-logs/clear`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
            } catch { /* ignore */ }
          }} style={{ padding: '2px 8px', fontSize: '0.65rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
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
            let fontWeight: number | string = 400
            if (log.msg.includes('쿠키 로테이션')) { color = '#FFFFFF'; fontWeight = 700 }
            else if (log.msg.includes('실패') || log.msg.includes('오류') || log.msg.includes('차단')) color = '#C4736E'
            else if (log.msg.includes('품절')) color = '#A78BFA'
            else if (log.msg.includes('사이클 완료')) { color = '#4C9AFF'; fontWeight = 700 }
            else if (log.msg.includes('전송완료')) {
              if (log.msg.includes('가격변동') && log.msg.includes('재고전송')) color = '#4C9AFF'  // 가격+재고 동시 전송
              else if (log.msg.includes('재고전송')) color = '#FFD93D'  // 재고만
              // 가격변동만 → 기본색(흰색) 유지
            }
            else if (log.msg.includes('스킵')) color = '#888'
            else if (log.msg.includes('재고변동')) color = '#FFD93D'
            else if (log.msg.includes('성공')) color = '#7BAF7E'
            return <div key={`${log.ts}-${i}`} style={{ color, fontWeight }}>{fmtTextNumbers(log.msg)}</div>
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

const card: React.CSSProperties = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
  padding: '1.25rem',
}

type StoreScore = {
  account_id: string; account_label: string; market_type: string
  grade: string; grade_code: string
  good_service: Record<string, number> | null
  penalty: number | null; penalty_rate: number | null
  product_count?: number; max_products?: number
  updated_at: string
}

export default function WarroomPage() {
  useEffect(() => { document.title = 'SAMBA-오토튠' }, [])
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [events, setEvents] = useState<MonitorEvent[]>([])
  const [siteChanges, setSiteChanges] = useState<Record<string, Record<string, Array<{ id: string; product_id: string | null; product_name: string | null; detail: Record<string, unknown> | null; created_at: string }>>>>({})

  const [loading, setLoading] = useState(true)
  const [lastFetched, setLastFetched] = useState<Date | null>(null)
  const [storeScores, setStoreScores] = useState<Record<string, StoreScore>>({})
  const [scoreTab, setScoreTab] = useState('smartstore')
  const [showPenaltyGuide, setShowPenaltyGuide] = useState(false)
  const [scoreRefreshing, setScoreRefreshing] = useState(false)
  const nextPollRef = useRef(POLL_INTERVAL / 1000)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 실시간 로그 상태

  // 소싱처/마켓 상태
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // 오토튠 상태
  const [autotuneRunning, setAutotuneRunning] = useState(false)
  const [autotuneCycles, setAutotuneCycles] = useState(0)
  const [autotuneRestarts, setAutotuneRestarts] = useState(0)
  const [singleProductNo, setSingleProductNo] = useState('')
  const [singleRefreshing, setSingleRefreshing] = useState(false)
  const [autotuneRefreshed, setAutotuneRefreshed] = useState(0)
  const [autotuneLastTick, setAutotuneLastTick] = useState<string | null>(null)
  const prevCyclesRef = useRef(0)
  const falseCountRef = useRef(0)

  // 소싱처별 인터벌 설정
  const INTERVAL_SITES = [
    { key: 'MUSINSA', label: '무신사' },
    { key: 'KREAM', label: 'KREAM' },
    { key: 'DANAWA', label: '다나와' },
    { key: 'FashionPlus', label: '패션플러스' },
    { key: 'Nike', label: 'Nike' },
    { key: 'Adidas', label: 'Adidas' },
    { key: 'ABCmart', label: 'ABC마트' },
    { key: 'REXMONDE', label: '렉스몬드' },
    { key: 'SSG', label: 'SSG' },
    { key: 'LOTTEON', label: '롯데ON' },
    { key: 'GSShop', label: 'GSShop' },
    { key: 'ElandMall', label: '이랜드몰' },
    { key: 'SSF', label: 'SSF샵' },
  ]
  const [siteIntervals, setSiteIntervals] = useState<Record<string, string>>({})
  const intervalTimerRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  // 마운트 시 서버에서 현재 인터벌 로드
  useEffect(() => {
    collectorApi.autotuneStatus().then(res => {
      if (res.site_intervals) {
        const init: Record<string, string> = {}
        for (const [site, val] of Object.entries(res.site_intervals)) {
          init[site] = String(val)
        }
        setSiteIntervals(init)
      }
    }).catch(() => {})
  }, [])

  const handleIntervalChange = useCallback((site: string, value: string) => {
    setSiteIntervals(prev => ({ ...prev, [site]: value }))
    // 디바운스 — 0.5초 후 자동 저장
    if (intervalTimerRef.current[site]) clearTimeout(intervalTimerRef.current[site])
    intervalTimerRef.current[site] = setTimeout(async () => {
      const num = parseFloat(value)
      if (isNaN(num) || num < 0 || num > 60) return
      try {
        await collectorApi.autotuneUpdateInterval(site, num)
      } catch { /* ignore */ }
    }, 500)
  }, [])
  // ── 등급 분류(hot/warm/cold) ON/OFF ──
  const [priorityEnabled, setPriorityEnabled] = useState(true)
  useEffect(() => {
    collectorApi.autotuneGetPriority().then(res => {
      setPriorityEnabled(res.priority_enabled)
    }).catch(() => {})
  }, [])
  const handlePriorityToggle = useCallback(async () => {
    const next = !priorityEnabled
    setPriorityEnabled(next)
    try {
      await collectorApi.autotuneSetPriority(next)
    } catch { setPriorityEnabled(!next) }
  }, [priorityEnabled])

  // ── 오토튠 필터 (소싱처/판매처 체크박스) ──
  const [filterSources, setFilterSources] = useState<string[] | null>(null) // null=전체
  const [filterMarkets, setFilterMarkets] = useState<string[] | null>(null) // null=전체
  const [availSources, setAvailSources] = useState<string[]>([])
  const [availMarkets, setAvailMarkets] = useState<string[]>([])
  const filterTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    collectorApi.autotuneGetFilters().then(res => {
      setAvailSources(res.available_sources)
      setAvailMarkets(res.available_markets)
      setFilterSources(res.enabled_sources)
      setFilterMarkets(res.enabled_markets)
    }).catch(() => {})
  }, [])

  const saveFilters = useCallback((sources: string[] | null, markets: string[] | null) => {
    if (filterTimerRef.current) clearTimeout(filterTimerRef.current)
    filterTimerRef.current = setTimeout(async () => {
      try {
        await collectorApi.autotuneSetFilters(sources, markets)
      } catch { /* ignore */ }
    }, 500)
  }, [])

  const toggleSource = useCallback((site: string) => {
    setFilterSources(prev => {
      const all = availSources
      const current = prev ?? [...all]
      const next = current.includes(site) ? current.filter(s => s !== site) : [...current, site]
      const result = next.length === all.length ? null : next.length === 0 ? null : next
      saveFilters(result, filterMarkets)
      return result
    })
  }, [availSources, filterMarkets, saveFilters])

  const toggleMarket = useCallback((marketType: string) => {
    setFilterMarkets(prev => {
      const all = availMarkets
      const current = prev ?? [...all]
      const next = current.includes(marketType) ? current.filter(m => m !== marketType) : [...current, marketType]
      const result = next.length === all.length ? null : next.length === 0 ? null : next
      saveFilters(filterSources, result)
      return result
    })
  }, [availMarkets, filterSources, saveFilters])

  const handleAutotuneStatus = useCallback((running: boolean, cycles: number, lastTick: string | null, refreshed: number) => {
    // 별도 스레드 타이밍 차이 대응 — 3회 연속 false일 때만 정지 표시
    if (!running) {
      falseCountRef.current++
      if (falseCountRef.current < 3) return  // 일시적 false 무시
    } else {
      falseCountRef.current = 0
    }
    setAutotuneRunning(running)
    setAutotuneCycles(cycles)
    setAutotuneLastTick(lastTick)
    setAutotuneRefreshed(refreshed)
    // 사이클 완료 시 이벤트 타임라인 갱신
    if (cycles > prevCyclesRef.current) {
      prevCyclesRef.current = cycles
      monitorApi.recentEvents(30).then(ev => setEvents(ev)).catch(() => {})
      monitorApi.siteChanges(5).then(c => { if (c && Object.keys(c).length > 0) setSiteChanges(c) }).catch(() => {})
    }
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
      const [dashboard, recentEvents, probeStatus, atStatus, scores, changes] = await Promise.all([
        monitorApi.dashboard().catch(() => null),
        monitorApi.recentEvents(30).catch(() => []),
        collectorApi.probeStatus().catch(() => ({})) as Promise<Record<string, Record<string, Record<string, unknown>>>>,
        collectorApi.autotuneStatus().catch(() => ({ running: false, last_tick: null, cycle_count: 0, restart_count: 0, target: 'registered', refreshed_count: 0, breaker_tripped: {} as Record<string, number> })) as ReturnType<typeof collectorApi.autotuneStatus>,
        monitorApi.storeScores().catch(() => ({})),
        monitorApi.siteChanges(5).catch(() => ({})),
      ])
      if (dashboard) setStats(dashboard)
      setEvents(recentEvents)
      if (changes && Object.keys(changes).length > 0) setSiteChanges(changes)
      if (probeStatus && Object.keys(probeStatus).length > 0) setProbeData(probeStatus)
      // 오토튠 상태는 handleAutotuneStatus를 통해 처리 (falseCountRef 가드 적용, 경쟁 상태 방지)
      handleAutotuneStatus(atStatus.running, atStatus.cycle_count, atStatus.last_tick, atStatus.refreshed_count || 0)
      setAutotuneRestarts(atStatus.restart_count || 0)
      if (scores && Object.keys(scores).length > 0) setStoreScores(scores)
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
    const poll = setInterval(() => load(), POLL_INTERVAL)
    return () => clearInterval(poll)
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

  // 이벤트 필터링 — scheduler_tick 소싱처별 최신 2건 표시
  const filteredEvents = (() => {
    const mapped = events.map(e => ({
      ...e,
      summary: e.summary?.replace(/오토튠\(registered\)\s*—\s*/, '') ?? e.summary,
    }))
    // scheduler_tick 소싱처별 최신 2건만 유지
    const tickCountBySite: Record<string, number> = {}
    const deduped = mapped.filter(e => {
      if (e.event_type === 'scheduler_tick') {
        const siteKey = e.source_site || '_none'
        tickCountBySite[siteKey] = (tickCountBySite[siteKey] || 0) + 1
        if (tickCountBySite[siteKey] > 2) return false
      }
      return true
    })
    return deduped
  })()

  // scheduler_tick 이벤트를 소싱처별로 그룹핑
  const tickEventsBySite = (() => {
    const ticks = filteredEvents.filter(e => e.event_type === 'scheduler_tick')
    const groups: Record<string, typeof ticks> = {}
    for (const e of ticks) {
      const siteKey = e.source_site || '기타'
      if (!groups[siteKey]) groups[siteKey] = []
      groups[siteKey].push(e)
    }
    return groups
  })()
  const nonTickEvents = [] as typeof filteredEvents

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
          flexDirection: 'column',
          gap: '0.5rem',
          borderColor: '#FF8C00',
          borderWidth: '1px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: autotuneRunning ? '#51CF66' : '#FF6B6B', display: 'inline-block' }} />
            <span style={{ fontWeight: 700, color: '#FF8C00', fontSize: '0.875rem' }}>오토튠 실시간 모니터링</span>
            {autotuneRunning && <span style={{ fontSize: '0.75rem', color: '#51CF66' }}>실행 중 ({autotuneCycles}회)</span>}
            {autotuneRunning && autotuneRestarts > 0 && <span style={{ fontSize: '0.75rem', color: '#FF6B6B' }}>재시작 {autotuneRestarts}회</span>}
            {!autotuneRunning && <span style={{ fontSize: '0.75rem', color: '#FF6B6B' }}>정지</span>}
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.8rem', color: '#888', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="상품번호"
              value={singleProductNo}
              onChange={e => setSingleProductNo(e.target.value)}
              style={{
                width: '110px', padding: '0.25rem 0.5rem',
                background: '#1A1A1A', border: '1px solid #3D3D3D', borderRadius: '6px',
                color: '#E5E5E5', fontSize: '0.75rem', outline: 'none',
              }}
              onKeyDown={e => { if (e.key === 'Enter' && singleProductNo.trim()) document.getElementById('btn-autotune-start')?.click() }}
            />
            <button
            id="btn-autotune-start"
            onClick={async () => {
              try {
                const { API_BASE_URL: apiBase } = await import('@/config/api')
                await fetchWithAuth(`${apiBase}/api/v1/samba/shipments/emergency-clear`, { method: 'POST' })
                const pno = singleProductNo.trim() || undefined
                const res = await collectorApi.autotuneStart('registered', pno)
                if (!res.ok) {
                  const { showAlert } = await import('@/components/samba/Modal')
                  showAlert(res.error || '시작 실패', 'error')
                  return
                }
                falseCountRef.current = 0
                setAutotuneRunning(true)
                setAutotuneCycles(0)
                if (pno) setSingleProductNo('')
              } catch { /* ignore */ }
            }}
            style={{
              padding: '0.25rem 0.75rem',
              background: 'rgba(34,197,94,0.12)',
              border: '1px solid rgba(34,197,94,0.35)',
              borderRadius: '6px',
              color: '#22C55E',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >시작</button>
          <button
            onClick={async () => {
              try {
                const { API_BASE_URL: apiBase } = await import('@/config/api')
                await fetchWithAuth(`${apiBase}/api/v1/samba/collector/autotune/stop`, { method: 'POST' })
                setAutotuneRunning(false)
              } catch { /* ignore */ }
            }}
            style={{
              padding: '0.25rem 0.75rem',
              background: 'rgba(239,68,68,0.12)',
              border: '1px solid rgba(239,68,68,0.35)',
              borderRadius: '6px',
              color: '#EF4444',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
            >작업취소</button>
            <button
              onClick={handlePriorityToggle}
              style={{
                padding: '0.25rem 0.75rem',
                background: priorityEnabled ? 'rgba(76,154,255,0.12)' : 'rgba(255,255,255,0.06)',
                border: `1px solid ${priorityEnabled ? 'rgba(76,154,255,0.35)' : 'rgba(255,255,255,0.15)'}`,
                borderRadius: '6px',
                color: priorityEnabled ? '#4C9AFF' : '#666',
                fontSize: '0.8125rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >등급분류 {priorityEnabled ? 'ON' : 'OFF'}</button>
          </div>
        </div>
        {/* 소싱처 체크박스 */}
        {availSources.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.75rem', color: '#9AA5C0', fontWeight: 600, whiteSpace: 'nowrap' }}>소싱처</span>
            {availSources.map(src => {
              const checked = filterSources === null || filterSources.includes(src)
              const labelMap: Record<string, string> = { MUSINSA: '무신사', KREAM: 'KREAM', DANAWA: '다나와', FashionPlus: '패션플러스', Nike: 'Nike', Adidas: 'Adidas', ABCmart: 'ABC마트', REXMONDE: '렉스몬드', SSG: 'SSG', LOTTEON: '롯데ON', GSShop: 'GSShop', ElandMall: '이랜드몰', SSF: 'SSF샵' }
              return (
                <label key={src} style={{ display: 'flex', alignItems: 'center', gap: '2px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSource(src)}
                    style={{ accentColor: '#FF8C00', width: 13, height: 13, cursor: 'pointer' }}
                  />
                  <span style={{ fontSize: '0.7rem', color: checked ? '#ddd' : '#666', whiteSpace: 'nowrap' }}>{labelMap[src] || src}</span>
                </label>
              )
            })}
          </div>
        )}
        {/* 판매처 체크박스 (마켓 단위) */}
        {availMarkets.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.75rem', color: '#9AA5C0', fontWeight: 600, whiteSpace: 'nowrap' }}>판매처</span>
            {availMarkets.map(mt => {
              const checked = filterMarkets === null || filterMarkets.includes(mt)
              const marketLabel: Record<string, string> = { smartstore: '스마트스토어', coupang: '쿠팡', '11st': '11번가', auction: '옥션', gmarket: 'G마켓', lotteon: '롯데ON', ssg: 'SSG', tmon: '티몬', wemakeprice: '위메프', kream: 'KREAM', playauto: '플레이오토', gsshop: 'GS샵', elandmall: '이랜드몰', ssf: 'SSF샵' }
              return (
                <label key={mt} style={{ display: 'flex', alignItems: 'center', gap: '2px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleMarket(mt)}
                    style={{ accentColor: '#4C9AFF', width: 13, height: 13, cursor: 'pointer' }}
                  />
                  <span style={{ fontSize: '0.7rem', color: checked ? '#ddd' : '#666', whiteSpace: 'nowrap' }}>{marketLabel[mt] || mt}</span>
                </label>
              )
            })}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', color: '#9AA5C0', fontWeight: 600, whiteSpace: 'nowrap' }}>수집인터벌</span>
          {INTERVAL_SITES.map(({ key, label }) => (
            <span key={key} style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <span style={{ fontSize: '0.7rem', color: '#aaa', whiteSpace: 'nowrap' }}>{label}</span>
              <input
                type="text"
                inputMode="decimal"
                value={siteIntervals[key] ?? ''}
                onChange={e => handleIntervalChange(key, e.target.value)}
                style={{
                  width: '2.5rem',
                  padding: '0.1rem 0.25rem',
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  borderRadius: '4px',
                  color: '#FF8C00',
                  fontSize: '0.75rem',
                  textAlign: 'center',
                  outline: 'none',
                }}
                onFocus={e => { e.target.style.borderColor = '#FF8C00' }}
                onBlur={e => { e.target.style.borderColor = 'rgba(255,255,255,0.15)' }}
              />
            </span>
          ))}
          <span style={{ fontSize: '0.65rem', color: '#666' }}>초</span>
        </div>
      </div>

      {/* 오토튠 실시간 로그 (시작/강제중단 버튼 바로 아래) */}
      <AutotuneLogPanel
        siteColors={SITE_COLORS}
        onStatusChange={handleAutotuneStatus}
        externalRunning={autotuneRunning}
      />

      {/* 이벤트 타임라인 (로그 아래) */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.96rem', fontWeight: 600, color: '#FF8C00' }}>이벤트 타임라인</div>
        </div>

        {filteredEvents.length === 0 ? (
          <div style={{ fontSize: '0.96rem', color: '#666', padding: '1rem 0', textAlign: 'center' }}>이벤트 없음</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', maxHeight: '420px', overflow: 'auto' }}>
            {/* 소싱처별 오토튠 사이클 그룹 */}
            {Object.keys(tickEventsBySite).length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.25rem' }}>
                {Object.entries(tickEventsBySite).map(([siteName, siteEvents]) => {
                  const cycles = siteEvents.length
                  const siteColor = SITE_COLORS[siteName] || '#888'
                  return (
                    <div key={siteName} style={{
                      flex: '1 1 200px',
                      padding: '0.5rem 0.6rem',
                      borderRadius: '6px',
                      border: `1px solid ${siteColor}30`,
                      background: `${siteColor}08`,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.3rem' }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: siteColor, flexShrink: 0 }} />
                        <span style={{ fontSize: '0.9rem', fontWeight: 600, color: siteColor }}>{siteName}</span>
                        <span style={{ fontSize: '0.78rem', color: '#666', marginLeft: 'auto' }}>
                          {cycles > 1 ? `최근 ${cycles}사이클` : ''}
                        </span>
                      </div>
                      {siteEvents.map((ev, ci) => {
                        const _d = ev.detail as Record<string, unknown> | undefined
                        const total = _d?.total as number | undefined
                        const ok = _d?.ok as number | undefined
                        const errs = _d?.errors as number | undefined
                        const rate = _d?.rate as number | undefined
                        const dur = _d?.duration_sec as number | undefined
                        const priceTx = _d?.price_transmit as number | undefined
                        const stockTx = _d?.stock_transmit as number | undefined
                        const deleted = _d?.deleted as number | undefined
                        const startedAt = _d?.started_at as string | undefined
                        const endedAt = _d?.ended_at as string | undefined
                        const fmtTime = (iso?: string) => {
                          if (!iso) return ''
                          const d = new Date(iso)
                          return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
                        }
                        const timeRange = startedAt && endedAt ? `${fmtTime(startedAt)}~${fmtTime(endedAt)}` : ''
                        return (
                          <div key={ci} style={{ marginBottom: ci < cycles - 1 ? '0.3rem' : 0, paddingBottom: ci < cycles - 1 ? '0.3rem' : 0, borderBottom: ci < cycles - 1 ? '1px solid #ffffff10' : 'none' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', alignItems: 'center' }}>
                              {timeRange && <span style={{ fontSize: '0.72rem', color: '#999' }}>{timeRange}</span>}
                              {total != null && (
                                <span style={{ fontSize: '0.78rem', color: '#aaa' }}>대상 {fmtNum(total)}</span>
                              )}
                              {ok != null && (
                                <span style={{ fontSize: '0.78rem', color: '#51CF66' }}>성공 {fmtNum(ok)}</span>
                              )}
                              {errs != null && errs > 0 && (
                                <span style={{ fontSize: '0.78rem', color: '#FF6B6B' }}>실패 {fmtNum(errs)}</span>
                              )}
                              {dur != null && (
                                <span style={{ fontSize: '0.78rem', color: '#888' }}>{Math.round(dur)}초</span>
                              )}
                              {rate != null && (
                                <span style={{ fontSize: '0.78rem', color: '#51CF66', fontWeight: 600 }}>{fmtNum(rate)}건/초</span>
                              )}
                            </div>
                            {((priceTx && priceTx > 0) || (stockTx && stockTx > 0) || (deleted && deleted > 0)) && (
                              <div style={{ display: 'flex', gap: '0.3rem', marginTop: '0.2rem' }}>
                                {priceTx != null && priceTx > 0 && (
                                  <span style={{ fontSize: '0.72rem', padding: '0.05rem 0.3rem', borderRadius: '3px', background: '#FFB34715', color: '#FFB347', border: '1px solid #FFB34730' }}>
                                    가격전송 {fmtNum(priceTx)}
                                  </span>
                                )}
                                {stockTx != null && stockTx > 0 && (
                                  <span style={{ fontSize: '0.72rem', padding: '0.05rem 0.3rem', borderRadius: '3px', background: '#A78BFA15', color: '#A78BFA', border: '1px solid #A78BFA30' }}>
                                    재고전송 {fmtNum(stockTx)}
                                  </span>
                                )}
                                {deleted != null && deleted > 0 && (
                                  <span style={{ fontSize: '0.72rem', padding: '0.05rem 0.3rem', borderRadius: '3px', background: '#FF6B6B15', color: '#FF6B6B', border: '1px solid #FF6B6B30' }}>
                                    삭제 {fmtNum(deleted)}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
            {/* 소싱처별 최근 수정 상품 내역 */}
            {Object.keys(tickEventsBySite).length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.25rem' }}>
                {Object.keys(tickEventsBySite).map(siteName => {
                  const sitePriceChanges = siteChanges[siteName]?.price_changed ?? []
                  const siteSoldOuts = siteChanges[siteName]?.sold_out ?? []
                  // autotune 사이클 tick에서 가격변동 상품 추출 (LOTTEON 등 price_changed 이벤트 없는 소싱처)
                  type TickPriceItem = { pid: string; site_product_id?: string; name: string; old_price: number; new_price: number }
                  type TickStockItem = { pid: string; site_product_id?: string; name: string; sale_status?: string }
                  const latestTick = tickEventsBySite[siteName]?.[0]
                  const latestTickDetail = latestTick?.detail as Record<string, unknown> | undefined
                  const tickPriceItems = (latestTickDetail?.price_changed_items as TickPriceItem[] | undefined) ?? []
                  const tickStockItems = (latestTickDetail?.stock_changed_items as TickStockItem[] | undefined) ?? []
                  const tickEndedAt = latestTickDetail?.ended_at as string | undefined
                  // DB 이벤트에 없는 항목만 tick에서 보충 (중복 방지), 합산 5개 제한
                  const tickPriceSlice = tickPriceItems.slice(0, Math.max(0, 5 - sitePriceChanges.length))
                  const tickStockSlice = tickStockItems.slice(0, Math.max(0, 5 - siteSoldOuts.length))
                  if (sitePriceChanges.length === 0 && siteSoldOuts.length === 0 && tickPriceSlice.length === 0 && tickStockSlice.length === 0) return null
                  const siteColor = SITE_COLORS[siteName] || '#888'
                  const fmtT = (iso: string) => {
                    const d = new Date(iso)
                    return `${d.getMonth() + 1}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
                  }
                  const shortId = (id: string | null) => id ? id.slice(-8) : '-'
                  return (
                    <div key={`changes-${siteName}`} style={{
                      flex: '1 1 200px',
                      padding: '0.5rem 0.6rem',
                      borderRadius: '6px',
                      border: `1px solid ${siteColor}20`,
                      background: `${siteColor}05`,
                    }}>
                      <div style={{ fontSize: '0.78rem', color: '#666', marginBottom: '0.3rem', fontWeight: 600 }}>
                        {siteName} 점검
                      </div>
                      {siteSoldOuts.map(ev => {
                        const d = ev.detail
                        const sitePid = (d?.site_product_id as string | undefined) || shortId(ev.product_id)
                        const status = d?.sale_status as string | undefined
                        return (
                          <div key={ev.id} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginBottom: '0.15rem' }}>
                            <span style={{ fontSize: '0.72rem', color: '#666', flexShrink: 0 }}>{fmtT(ev.created_at)}</span>
                            <span style={{ fontSize: '0.72rem', color: '#aaa', fontFamily: 'monospace' }}>{sitePid}</span>
                            <span style={{ fontSize: '0.72rem', color: '#A78BFA' }}>재고변동</span>
                            <span style={{ fontSize: '0.72rem', color: status === 'SUSPENSION' ? '#FF6B6B' : '#51CF66' }}>
                              {status === 'SUSPENSION' ? '품절' : status ?? '변동'}
                            </span>
                          </div>
                        )
                      })}
                      {sitePriceChanges.map(ev => {
                        const d = ev.detail
                        const sitePid = (d?.site_product_id as string | undefined) || shortId(ev.product_id)
                        const oldP = d?.old_price as number | undefined
                        const newP = d?.new_price as number | undefined
                        const pct = d?.diff_pct as number | undefined
                        const sign = pct != null && pct > 0 ? '+' : ''
                        return (
                          <div key={ev.id} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginBottom: '0.15rem' }}>
                            <span style={{ fontSize: '0.72rem', color: '#666', flexShrink: 0 }}>{fmtT(ev.created_at)}</span>
                            <span style={{ fontSize: '0.72rem', color: '#aaa', fontFamily: 'monospace' }}>{sitePid}</span>
                            <span style={{ fontSize: '0.72rem', color: '#FFB347' }}>가격변동</span>
                            {oldP != null && newP != null && (
                              <span style={{ fontSize: '0.72rem', color: (pct ?? 0) > 0 ? '#FF6B6B' : '#51CF66' }}>
                                ₩{fmtNum(oldP)}→₩{fmtNum(newP)}{pct != null ? ` (${sign}${pct}%)` : ''}
                              </span>
                            )}
                          </div>
                        )
                      })}
                      {/* tick 가격변동 (DB 이벤트로 채워지지 않은 소싱처 보충) */}
                      {tickPriceSlice.map((item, i) => {
                        const diff = item.old_price > 0 ? Math.round((item.new_price - item.old_price) / item.old_price * 100) : 0
                        return (
                          <div key={`tp-${i}`} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginBottom: '0.15rem' }}>
                            {tickEndedAt && <span style={{ fontSize: '0.72rem', color: '#666', flexShrink: 0 }}>{fmtT(tickEndedAt)}</span>}
                            <span style={{ fontSize: '0.72rem', color: '#aaa', fontFamily: 'monospace' }}>{item.site_product_id || item.pid.slice(-8)}</span>
                            <span style={{ fontSize: '0.72rem', color: '#FFB347' }}>가격변동</span>
                            <span style={{ fontSize: '0.72rem', color: diff > 0 ? '#FF6B6B' : '#51CF66' }}>
                              ₩{fmtNum(item.old_price)}→₩{fmtNum(item.new_price)}{diff !== 0 ? ` (${diff > 0 ? '+' : ''}${diff}%)` : ''}
                            </span>
                          </div>
                        )
                      })}
                      {/* tick 재고변동 */}
                      {tickStockSlice.map((item, i) => (
                        <div key={`ts-${i}`} style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', marginBottom: '0.15rem' }}>
                          {tickEndedAt && <span style={{ fontSize: '0.72rem', color: '#666', flexShrink: 0 }}>{fmtT(tickEndedAt)}</span>}
                          <span style={{ fontSize: '0.72rem', color: '#aaa', fontFamily: 'monospace' }}>{item.site_product_id || item.pid.slice(-8)}</span>
                          <span style={{ fontSize: '0.72rem', color: '#A78BFA' }}>재고변동</span>
                          <span style={{ fontSize: '0.72rem', color: item.sale_status === 'sold_out' ? '#FF6B6B' : '#51CF66' }}>
                            {item.sale_status === 'sold_out' ? '품절' : item.sale_status ?? '변동'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            )}
            {/* 기타 이벤트 (scheduler_tick 외) */}
            {nonTickEvents.map((e, ei) => {
              const t = new Date(e.created_at)
              const timeStr = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}:${String(t.getSeconds()).padStart(2, '0')}`
              const d = e.detail as Record<string, unknown> | undefined
              const detailTags: { label: string; value: string; color: string }[] = []
              if (d) {
                if (d.old_price != null && d.new_price != null) {
                  const diff = d.diff_pct as number | undefined
                  const sign = diff && diff > 0 ? '+' : ''
                  detailTags.push({
                    label: '가격',
                    value: `₩${fmtNum(Number(d.old_price))} → ₩${fmtNum(Number(d.new_price))}${diff != null ? ` (${sign}${diff}%)` : ''}`,
                    color: (diff ?? 0) > 0 ? '#FF6B6B' : '#51CF66',
                  })
                }
                if (typeof d.refreshed === 'number' && d.refreshed > 0)
                  detailTags.push({ label: '갱신', value: `${fmtNum(d.refreshed)}건`, color: '#4C9AFF' })
                if (typeof d.changed === 'number' && d.changed > 0)
                  detailTags.push({ label: '변동', value: `${fmtNum(d.changed)}건`, color: '#FFD93D' })
                if (typeof d.sold_out === 'number' && d.sold_out > 0)
                  detailTags.push({ label: '품절', value: `${fmtNum(d.sold_out)}건`, color: '#FF6B6B' })
                if (typeof d.price_transmit === 'number' && d.price_transmit > 0)
                  detailTags.push({ label: '가격전송', value: `${fmtNum(d.price_transmit)}건`, color: '#FFB347' })
                if (typeof d.stock_transmit === 'number' && d.stock_transmit > 0)
                  detailTags.push({ label: '재고전송', value: `${fmtNum(d.stock_transmit)}건`, color: '#A78BFA' })
                if (typeof d.deleted === 'number' && d.deleted > 0)
                  detailTags.push({ label: '삭제', value: `${fmtNum(d.deleted)}건`, color: '#FF6B6B' })
                if (typeof d.no_pid === 'number' && d.no_pid > 0)
                  detailTags.push({ label: 'ID없음', value: `${fmtNum(d.no_pid)}건`, color: '#FFB347' })
                if (typeof d.blocked === 'number' && d.blocked > 0)
                  detailTags.push({ label: '차단', value: `${fmtNum(d.blocked)}건`, color: '#FF6B6B' })
                if (typeof d.timeouts === 'number' && d.timeouts > 0)
                  detailTags.push({ label: '타임아웃', value: `${fmtNum(d.timeouts)}건`, color: '#FFB347' })
                if (typeof d.other_errors === 'number' && d.other_errors > 0)
                  detailTags.push({ label: '기타에러', value: `${fmtNum(d.other_errors)}건`, color: '#888' })
                if (typeof d.count === 'number' && d.count > 0 && detailTags.length === 0)
                  detailTags.push({ label: '건수', value: `${fmtNum(d.count)}건`, color: '#4C9AFF' })
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
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: SEV_COLORS[e.severity] || '#666',
                      marginTop: '4px', flexShrink: 0,
                    }} />
                    <span style={{ fontSize: '0.9rem', color: '#666', minWidth: '3rem', flexShrink: 0 }}>{timeStr}</span>
                    <span style={{ fontSize: '0.96rem', color: '#E5E5E5', flex: 1 }}>
                      {e.summary}
                    </span>
                    {e.source_site && (
                      <span style={{
                        fontSize: '0.78rem', color: SITE_COLORS[e.source_site] || '#888',
                        padding: '0.1rem 0.3rem', borderRadius: '3px',
                        background: 'rgba(255,255,255,0.05)', flexShrink: 0,
                      }}>
                        {e.source_site}
                      </span>
                    )}
                  </div>
                  {detailTags.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', marginTop: '0.25rem', paddingLeft: '2.5rem' }}>
                      {detailTags.map((tag, i) => (
                        <span key={i} style={{
                          fontSize: '0.78rem',
                          padding: '0.1rem 0.4rem',
                          borderRadius: '3px',
                          background: `${tag.color}15`,
                          color: tag.color,
                          border: `1px solid ${tag.color}30`,
                        }}>
                          {tag.label}: {tag.value}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* A-2. 마켓별 스토어 현황 분석 */}
      {false && (() => {
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
                <span style={{ fontSize: '0.7rem', color: '#666' }}>{fmtNum(tabAccounts.length)}개 계정</span>
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
                            {fmtNum(acc.product_count ?? 0)}
                          </span>
                          <span style={{ fontSize: '0.68rem', color: '#888' }}>/ {fmtNum(acc.max_products)}</span>
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
            {fmtNum(product_stats.total)}
          </div>
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem', display: 'flex', gap: '0.5rem' }}>
            {Object.entries(product_stats.by_priority).map(([k, v]) => (
              <span key={k} style={{ color: PRIORITY_COLORS[k] || '#888' }}>
                {k} {v}
              </span>
            ))}
          </div>
        </div>

        {/* 등록상품 / 오토튠 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>등록상품 / 오토튠</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#4C9AFF' }}>
            {fmtNum(product_stats.registered ?? 0)}
          </div>
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem' }}>
            24h 갱신 {fmtNum(autotuneRefreshed)}건
          </div>
        </div>

        {/* 가격 변동 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>가격 변동</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: '#FFD93D' }}>
            {fmtNum(price_change_stats.changes_24h)}건
          </div>
          <div style={{ fontSize: '0.7rem', color: price_change_stats.avg_change_pct < 0 ? '#FF6B6B' : '#51CF66', marginTop: '0.25rem' }}>
            평균 {price_change_stats.avg_change_pct > 0 ? '+' : ''}{fmtNum(price_change_stats.avg_change_pct)}%
          </div>
        </div>

        {/* 에러 상품 */}
        <div style={card}>
          <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>에러 상품</div>
          <div style={{ fontSize: '1.75rem', fontWeight: 700, color: refresh_stats.error_products > 0 ? '#FF6B6B' : '#51CF66' }}>
            {fmtNum(refresh_stats.error_products)}
          </div>
          <div style={{ fontSize: '0.7rem', color: '#888', marginTop: '0.25rem' }}>
            연속실패
          </div>
        </div>
      </div>

      {/* C. 소싱처/마켓 헬스 */}
      <div style={{ display: 'none', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
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
                    {fmtNum(h.errors)}
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
                    ₩{fmtNum(c.old)}
                  </span>
                  <span style={{ color: '#888' }}>→</span>
                  <span style={{ color: '#E5E5E5', whiteSpace: 'nowrap' }}>
                    ₩{fmtNum(c.new)}
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
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{fmtNum(cnt)}</span>
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
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{fmtNum(cnt)}</span>
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
                  <span style={{ fontSize: '0.7rem', color: '#E5E5E5', minWidth: '2.5rem', textAlign: 'right' }}>{fmtNum(cnt)}</span>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* 소싱처/마켓 상태 대시보드 */}
      <div style={{ ...card, display: 'none', padding: '1.5rem' }}>
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

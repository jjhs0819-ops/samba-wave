'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { collectorApi } from '@/lib/samba/api'

interface BlockedSite {
  site: string
  error: string
}

const POLL_INTERVAL = 30_000

export default function SambaBlockAlert() {
  const [blockedSites, setBlockedSites] = useState<BlockedSite[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const checkProbe = useCallback(async () => {
    try {
      const data = await collectorApi.probeStatus()
      const sources = (data?.sources ?? data) as Record<string, Record<string, unknown>>
      const blocked: BlockedSite[] = []

      for (const [site, info] of Object.entries(sources)) {
        if (!info || typeof info !== 'object') continue
        const ok = info.ok as boolean | undefined
        const error = (info.error as string) || ''
        // ok === false 이고 에러 메시지에 차단/429/403 관련 내용이 있으면
        if (ok === false && (error.includes('차단') || error.includes('429') || error.includes('403'))) {
          blocked.push({ site, error })
        }
      }

      setBlockedSites(blocked)
    } catch {
      // API 실패 시 무시
    }
  }, [])

  useEffect(() => {
    checkProbe()
    timerRef.current = setInterval(checkProbe, POLL_INTERVAL)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [checkProbe])

  const handleDismiss = (site: string) => {
    setDismissed(prev => {
      const next = new Set(prev)
      next.add(site)
      return next
    })
  }

  // 닫지 않은 차단 사이트만 표시
  const visible = blockedSites.filter(b => !dismissed.has(b.site))

  // 차단 해제되면 dismissed에서도 제거
  useEffect(() => {
    const activeSites = new Set(blockedSites.map(b => b.site))
    setDismissed(prev => {
      const next = new Set<string>()
      prev.forEach(s => {
        if (activeSites.has(s)) next.add(s)
      })
      return next
    })
  }, [blockedSites])

  if (visible.length === 0) return null

  return (
    <div style={{
      position: 'sticky',
      top: 0,
      zIndex: 29,
      display: 'flex',
      flexDirection: 'column',
      gap: '0',
    }}>
      {visible.map(({ site, error }) => (
        <div
          key={site}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            padding: '0.625rem 2rem',
            background: 'rgba(255,107,107,0.12)',
            borderBottom: '1px solid rgba(255,107,107,0.3)',
          }}
        >
          {/* 경고 아이콘 */}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FF6B6B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>

          <span style={{ fontSize: '0.8125rem', color: '#FF6B6B', fontWeight: 600, flexShrink: 0 }}>
            접속 차단
          </span>
          <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
            <strong style={{ color: '#FFB84D' }}>{site}</strong> 소싱처가 접속 차단되었습니다 — {error}
          </span>

          <button
            onClick={() => handleDismiss(site)}
            style={{
              marginLeft: 'auto',
              background: 'transparent',
              border: 'none',
              color: '#888',
              cursor: 'pointer',
              padding: '0.25rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            title="닫기"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  )
}

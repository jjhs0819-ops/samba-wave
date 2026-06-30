'use client'

import { useRef, useEffect } from 'react'
import { fmtTextNumbers } from '@/lib/samba/styles'

import { btn } from '@/lib/samba/buttons'
import { useTheme } from '@/lib/samba/useTheme'

interface AiJobModalProps {
  open: boolean
  title: string
  logs: string[]
  done: boolean
  abortRef: React.MutableRefObject<boolean>
  onClose: () => void
}

// AI 작업 진행 모달
export default function AiJobModal({ open, title, logs, done, abortRef, onClose }: AiJobModalProps) {
  const c = useTheme()
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  if (!open) return null

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '12px', padding: '1.5rem', width: '500px', maxHeight: '70vh', display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: c.text }}>{title}</h3>
        <div ref={logRef} style={{ flex: 1, overflowY: 'auto', background: c.surfaceAlt, borderRadius: '8px', padding: '0.75rem', fontSize: '0.75rem', fontFamily: 'monospace', color: c.textSub, maxHeight: '50vh', lineHeight: 1.6 }}>
          {logs.map((msg, i) => {
            let color = c.textSub
            if (msg.includes('완료')) color = c.success
            if (/실패[\s:]*[1-9]/.test(msg) || /실패(?![\s:]*\d)/.test(msg) || msg.includes('오류')) color = c.danger
            if (msg.includes('시작')) color = c.link
            return <div key={i} style={{ color }}>{fmtTextNumbers(msg)}</div>
          })}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
          {!done && (
            <button onClick={() => { abortRef.current = true }} style={{ ...btn('danger'), flex: 1, padding: '0.5rem', borderRadius: '6px', fontSize: '0.8rem' }}>중단</button>
          )}
          {done && (
            <button onClick={onClose} style={{ ...btn('ghost'), flex: 1, padding: '0.5rem', borderRadius: '6px', fontSize: '0.8rem' }}>닫기</button>
          )}
        </div>
      </div>
    </div>
  )
}

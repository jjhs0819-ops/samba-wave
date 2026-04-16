'use client'

import { useRef, useEffect } from 'react'

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
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  if (!open) return null

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#1E1E1E', border: '1px solid #333', borderRadius: '12px', padding: '1.5rem', width: '500px', maxHeight: '70vh', display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: '#FF8C00' }}>{title}</h3>
        <div ref={logRef} style={{ flex: 1, overflowY: 'auto', background: '#111', borderRadius: '8px', padding: '0.75rem', fontSize: '0.75rem', fontFamily: 'monospace', color: '#CCC', maxHeight: '50vh', lineHeight: 1.6 }}>
          {logs.map((msg, i) => {
            let color = '#CCC'
            if (msg.includes('완료')) color = '#51CF66'
            if (msg.includes('실패') || msg.includes('오류')) color = '#FF6B6B'
            if (msg.includes('시작')) color = '#4C9AFF'
            return <div key={i} style={{ color }}>{msg}</div>
          })}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
          {!done && (
            <button onClick={() => { abortRef.current = true }} style={{ flex: 1, padding: '0.5rem', background: 'rgba(255,107,107,0.15)', border: '1px solid rgba(255,107,107,0.4)', borderRadius: '6px', color: '#FF6B6B', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>중단</button>
          )}
          {done && (
            <button onClick={onClose} style={{ flex: 1, padding: '0.5rem', background: '#333', border: '1px solid #555', borderRadius: '6px', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.8rem' }}>닫기</button>
          )}
        </div>
      </div>
    </div>
  )
}

'use client'

import { useRef, useEffect } from 'react'
import { fmtTextNumbers } from '@/lib/samba/styles'

interface DeleteJobModalProps {
  open: boolean
  logs: string[]
  done: boolean
  onClose: () => void
}

// 그룹 삭제 작업 진행 모달
export default function DeleteJobModal({ open, logs, done, onClose }: DeleteJobModalProps) {
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs])

  if (!open) return null

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#1E1E1E', border: '1px solid #333', borderRadius: '12px', padding: '1.5rem', width: '480px', maxHeight: '70vh', display: 'flex', flexDirection: 'column' }}>
        <h3 style={{ margin: '0 0 0.75rem', fontSize: '0.95rem', color: '#FF6B6B' }}>그룹 삭제 진행 중</h3>
        <div ref={logRef} style={{ flex: 1, overflowY: 'auto', background: '#111', borderRadius: '8px', padding: '0.75rem', fontSize: '0.75rem', fontFamily: 'monospace', color: '#CCC', maxHeight: '50vh', lineHeight: 1.6 }}>
          {logs.map((msg, i) => {
            let color = '#CCC'
            if (msg.includes('완료') || msg.includes('✅') || msg.includes('🎉')) color = '#51CF66'
            if (msg.includes('⚠️') || msg.includes('건너뜀')) color = '#FFD43B'
            if (msg.includes('시작') || msg.includes('🗑️')) color = '#4C9AFF'
            return <div key={i} style={{ color }}>{msg ? fmtTextNumbers(msg) : '\u00A0'}</div>
          })}
          {!done && <div style={{ color: '#888' }}>⏳ 처리 중...</div>}
        </div>
        <div style={{ marginTop: '0.75rem' }}>
          {done && (
            <button onClick={onClose} style={{ width: '100%', padding: '0.5rem', background: '#333', border: '1px solid #555', borderRadius: '6px', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.8rem' }}>닫기</button>
          )}
        </div>
      </div>
    </div>
  )
}

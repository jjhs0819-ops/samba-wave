'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

// ── 타입 ──

interface AlertState {
  type: 'alert'
  message: string
  variant?: 'info' | 'error' | 'success'
}

interface ConfirmState {
  type: 'confirm'
  message: string
  resolve: (result: boolean) => void
}

type ModalState = AlertState | ConfirmState | null

// ── 전역 상태 (간단한 이벤트 기반) ──

type Listener = (state: ModalState) => void
const listeners = new Set<Listener>()
let currentState: ModalState = null

function emit(state: ModalState) {
  currentState = state
  listeners.forEach(fn => fn(state))
}

/**
 * alert() 대체 - 커스텀 모달 알림
 */
export function showAlert(message: string, variant: 'info' | 'error' | 'success' = 'info') {
  emit({ type: 'alert', message, variant })
}

/**
 * confirm() 대체 - 커스텀 모달 확인
 * @returns Promise<boolean> - 확인 시 true, 취소 시 false
 */
export function showConfirm(message: string): Promise<boolean> {
  return new Promise(resolve => {
    emit({ type: 'confirm', message, resolve })
  })
}

// ── 컴포넌트 ──

export default function SambaModal() {
  const [state, setState] = useState<ModalState>(null)
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler: Listener = (s) => setState(s)
    listeners.add(handler)
    return () => { listeners.delete(handler) }
  }, [])

  const close = useCallback((result?: boolean) => {
    if (state?.type === 'confirm') {
      state.resolve(result ?? false)
    }
    emit(null)
  }, [state])

  // ESC 키로 닫기
  useEffect(() => {
    if (!state) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close(false)
      if (e.key === 'Enter' && state.type === 'alert') close()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [state, close])

  if (!state) return null

  const isError = state.type === 'alert' && state.variant === 'error'
  const isSuccess = state.type === 'alert' && state.variant === 'success'
  const accentColor = isError ? '#FF6B6B' : isSuccess ? '#51CF66' : '#FF8C00'

  return (
    <div
      ref={overlayRef}
      style={{
        position: 'fixed', inset: 0, zIndex: 99999,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={() => close(false)}
    >
      <div
        style={{
          background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '10px',
          width: 'min(400px, 90vw)', padding: '0',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 메시지 */}
        <div style={{ padding: '24px 24px 16px', fontSize: '0.85rem', color: '#E5E5E5', lineHeight: 1.6 }}>
          {state.message}
        </div>

        {/* 버튼 */}
        <div style={{
          display: 'flex', justifyContent: state.type === 'confirm' ? 'flex-end' : 'center',
          gap: '8px', padding: '12px 24px 20px',
        }}>
          {state.type === 'confirm' && (
            <button
              onClick={() => close(false)}
              style={{
                padding: '7px 20px', fontSize: '0.8rem', borderRadius: '6px',
                border: '1px solid #3D3D3D', background: '#2A2A2A', color: '#999',
                cursor: 'pointer',
              }}
            >취소</button>
          )}
          <button
            onClick={() => close(true)}
            autoFocus
            style={{
              padding: '7px 20px', fontSize: '0.8rem', borderRadius: '6px',
              border: 'none', background: accentColor, color: '#FFF',
              cursor: 'pointer', fontWeight: 600,
            }}
          >확인</button>
        </div>
      </div>
    </div>
  )
}

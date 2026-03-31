'use client'

import { useEffect, useState, useRef } from 'react'
import { inputStyle, fmtNum, parseNum } from '@/lib/samba/styles'

/** 숫자 입력 컴포넌트 (콤마 서식 + 스피너 제거) */
export default function NumInput({ value, onChange, style, placeholder, suffix }: {
  value: number
  onChange: (v: number) => void
  style?: React.CSSProperties
  placeholder?: string
  suffix?: string
}) {
  const [display, setDisplay] = useState(fmtNum(value))
  const ref = useRef<HTMLInputElement>(null)

  // 외부 value 변경 시 동기화 (포커스 중이 아닐 때만)
  useEffect(() => {
    if (document.activeElement !== ref.current) {
      setDisplay(fmtNum(value))
    }
  }, [value])

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.375rem' }}>
      <input
        ref={ref}
        type="text"
        inputMode="numeric"
        style={{ ...inputStyle, ...style }}
        value={display}
        placeholder={placeholder || '0'}
        onChange={(e) => {
          const raw = e.target.value.replace(/[^0-9.-]/g, '')
          setDisplay(raw)
        }}
        onBlur={(e) => {
          const n = parseNum(e.target.value)
          setDisplay(fmtNum(n))
          if (n !== value) onChange(n)
        }}
      />
      {suffix && <span style={{ color: '#888', fontSize: '0.8125rem' }}>{suffix}</span>}
    </span>
  )
}

/**
 * 문자열 기반 숫자 입력 컴포넌트
 * settings 페이지 등에서 value/onChange가 string인 경우 사용
 */
export function NumInputStr({ value, onChange, style, placeholder }: {
  value: string
  onChange: (v: string) => void
  style?: React.CSSProperties
  placeholder?: string
}) {
  const [display, setDisplay] = useState(() => {
    const n = parseNum(value)
    return n > 0 ? fmtNum(n) : ''
  })
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (document.activeElement !== ref.current) {
      const n = parseNum(value)
      setDisplay(n > 0 ? fmtNum(n) : '')
    }
  }, [value])

  return (
    <input
      ref={ref}
      type="text"
      inputMode="numeric"
      style={{ ...inputStyle, ...style }}
      value={display}
      placeholder={placeholder || '0'}
      onChange={(e) => {
        const raw = e.target.value.replace(/[^0-9]/g, '')
        setDisplay(raw)
      }}
      onBlur={(e) => {
        const n = parseNum(e.target.value)
        setDisplay(n > 0 ? fmtNum(n) : '')
        onChange(n > 0 ? String(n) : '')
      }}
    />
  )
}

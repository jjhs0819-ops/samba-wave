import type { CSSProperties } from 'react'
import { dark, type Palette } from '@/lib/samba/colors'
import { fmtDateTime } from '@/lib/samba/utils'

export interface License {
  id: string
  license_key: string
  buyer_name: string
  buyer_email: string
  is_active: boolean
  expires_at: string | null
  last_verified_at: string | null
  created_at: string
}

export interface LoginHistory {
  id: string
  email: string
  ip_address: string | null
  region: string | null
  created_at: string
}

export const STATUS_MAP: Record<string, { label: string; color: string }> = {
  active: { label: '활성', color: '#51CF66' },
  draft: { label: '대기', color: '#FFD93D' },
  inactive: { label: '비활성', color: '#888' },
  suspended: { label: '정지', color: '#FF6B6B' },
}

// IP 마스킹 (222.109.12.34 → 222.109.**)
export const maskIp = (ip: string | null) => {
  if (!ip) return '-'
  const parts = ip.split('.')
  if (parts.length === 4) return `${parts[0]}.${parts[1]}.**.**`
  return ip
}

// 년/월/일 select 헬퍼
export const years = () => {
  const cur = new Date().getFullYear()
  return Array.from({ length: 3 }, (_, i) => cur - i)
}
export const months = () => Array.from({ length: 12 }, (_, i) => i + 1)
export const daysInMonth = (y: number, m: number) => new Date(y, m, 0).getDate()
export const pad = (n: number) => String(n).padStart(2, '0')

// 테마 반응형 스타일 팩토리 — 다크는 기존 값과 픽셀 동일 유지(정확 토큰 없는 색은 다크 원값 분기)
export const makeSelectStyle = (c: Palette): CSSProperties => ({
  padding: '0.35rem 0.5rem', fontSize: '0.8rem', background: c.inputBg,
  border: `1px solid ${c === dark ? '#333' : c.border}`, color: c.text, borderRadius: '4px', cursor: 'pointer',
})
export const makeThStyle = (c: Palette): CSSProperties => ({
  padding: '0.6rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: c === dark ? '#888' : c.textSub,
})
export const makeTdStyle = (c: Palette): CSSProperties => ({
  padding: '0.5rem 1rem', textAlign: 'center', fontSize: '0.8rem', color: c === dark ? '#C5C5C5' : c.text,
})

// 로그인 일시 포맷: 2026-04-07 [08:44:50] — KST 명시적 변환
export const fmtLoginDate = (iso: string) => fmtDateTime(iso)

import type { CSSProperties } from 'react'
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

export const selectStyle: CSSProperties = {
  padding: '0.35rem 0.5rem', fontSize: '0.8rem', background: '#1A1A1A',
  border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', cursor: 'pointer',
}
export const thStyle: CSSProperties = {
  padding: '0.6rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888',
}
export const tdStyle: CSSProperties = {
  padding: '0.5rem 1rem', textAlign: 'center', fontSize: '0.8rem', color: '#C5C5C5',
}

// 로그인 일시 포맷: 2026-04-07 [08:44:50] — KST 명시적 변환
export const fmtLoginDate = (iso: string) => fmtDateTime(iso)

import type { CSSProperties } from 'react'
import { card, inputStyle } from '@/lib/samba/styles'
import { light as c } from '@/lib/samba/colors'
import { btn } from '@/lib/samba/buttons'

export type TabType = 'overview' | 'auto-posting' | 'posts' | 'products' | 'revenue' | 'settings'

export interface DashboardData {
  today_posts: number
  total_posts: number
  success_rate: number
  auto_status: 'running' | 'stopped'
}

export interface PostItem {
  id: string
  title: string
  category: string
  keyword: string
  status: 'published' | 'failed' | 'pending'
  published_at: string
}

export interface PostsResponse {
  items: PostItem[]
  total: number
  page: number
  pages: number
}

export interface WpSite {
  id: string
  site_url: string
  site_name: string
  status: string
  created_at: string
}

export interface KeywordGroup {
  id: string
  name: string
  category: string
  keywords: string[]
}

export interface SseLog {
  event: 'log' | 'success' | 'fail' | 'done' | 'error'
  message: string
  timestamp?: string
}

export interface WholesaleProduct {
  id: string
  name: string
  price: number
  image?: string
  source: string
}

export interface WholesaleSearchResult {
  items: WholesaleProduct[]
  total: number
}

export const TAB_LIST: { key: TabType; label: string }[] = [
  { key: 'overview', label: '종합현황' },
  { key: 'auto-posting', label: '자동 포스팅' },
  { key: 'posts', label: '게시물 관리' },
  { key: 'products', label: '상품 연동' },
  { key: 'revenue', label: '수익 대시보드' },
  { key: 'settings', label: '채널 설정' },
]

export const ISSUE_CATEGORIES = [
  { value: 'politics', label: '정치' },
  { value: 'economy', label: '경제' },
  { value: 'sports', label: '스포츠' },
  { value: 'tech', label: '기술' },
  { value: 'fashion', label: '패션' },
  { value: 'food', label: '음식' },
  { value: 'entertainment', label: '엔터테인먼트' },
  { value: 'health', label: '건강' },
]

export const cardPad = { ...card, padding: '20px' }

export function getStatusBadge(status: string) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    published: { bg: 'rgba(81,207,102,0.15)', color: c.success, label: '발행됨' },
    failed: { bg: 'rgba(255,107,107,0.15)', color: c.danger, label: '실패' },
    pending: { bg: 'rgba(138,149,176,0.15)', color: c.textMuted, label: '대기' },
    running: { bg: 'rgba(81,207,102,0.15)', color: c.success, label: '실행중' },
    stopped: { bg: 'rgba(255,107,107,0.15)', color: c.danger, label: '중지' },
    connected: { bg: 'rgba(81,207,102,0.15)', color: c.success, label: '연결됨' },
    disconnected: { bg: 'rgba(138,149,176,0.15)', color: c.textMuted, label: '미연결' },
  }
  const s = map[status] || map.pending
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: s.bg, color: s.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {s.label}
    </span>
  )
}

export const btnPrimary: CSSProperties = {
  ...btn('primary'),
  padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', whiteSpace: 'nowrap',
}

export const btnDanger: CSSProperties = {
  ...btn('danger'),
  padding: '4px 10px', fontSize: '0.72rem', borderRadius: '6px', whiteSpace: 'nowrap',
}

export const btnOutline: CSSProperties = {
  ...btn('accent'),
  padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', whiteSpace: 'nowrap',
}

export const thStyle: CSSProperties = {
  padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: c.textSub, fontWeight: 500,
}

export const tdStyle: CSSProperties = {
  padding: '10px', fontSize: '0.8rem', color: c.text,
}

export const sectionTitle: CSSProperties = {
  fontSize: '0.9rem', fontWeight: 600, color: c.text, margin: 0, marginBottom: '16px',
}

export const inputBox: CSSProperties = {
  ...inputStyle,
  background: c.inputBg,
  border: `1px solid ${c.border}`,
  borderRadius: '8px',
}

export const selectStyle: CSSProperties = {
  ...inputBox,
  appearance: 'none',
  cursor: 'pointer',
}

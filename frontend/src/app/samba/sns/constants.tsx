import type { CSSProperties } from 'react'
import { card, inputStyle } from '@/lib/samba/styles'

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
    published: { bg: 'rgba(81,207,102,0.15)', color: '#51CF66', label: '발행됨' },
    failed: { bg: 'rgba(255,107,107,0.15)', color: '#FF6B6B', label: '실패' },
    pending: { bg: 'rgba(138,149,176,0.15)', color: '#8A95B0', label: '대기' },
    running: { bg: 'rgba(81,207,102,0.15)', color: '#51CF66', label: '실행중' },
    stopped: { bg: 'rgba(255,107,107,0.15)', color: '#FF6B6B', label: '중지' },
    connected: { bg: 'rgba(81,207,102,0.15)', color: '#51CF66', label: '연결됨' },
    disconnected: { bg: 'rgba(138,149,176,0.15)', color: '#8A95B0', label: '미연결' },
  }
  const s = map[status] || map.pending
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: s.bg, color: s.color, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {s.label}
    </span>
  )
}

export const btnPrimary: CSSProperties = {
  padding: '6px 14px', fontSize: '0.78rem', background: '#FF8C00', color: '#000',
  border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
}

export const btnDanger: CSSProperties = {
  padding: '4px 10px', fontSize: '0.72rem', background: 'rgba(255,107,107,0.15)', color: '#FF6B6B',
  border: '1px solid rgba(255,107,107,0.3)', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
}

export const btnOutline: CSSProperties = {
  padding: '6px 14px', fontSize: '0.78rem', background: 'rgba(255,140,0,0.15)', color: '#FF8C00',
  border: '1px solid rgba(255,140,0,0.3)', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, whiteSpace: 'nowrap',
}

export const thStyle: CSSProperties = {
  padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500,
}

export const tdStyle: CSSProperties = {
  padding: '10px', fontSize: '0.8rem', color: '#E5E5E5',
}

export const sectionTitle: CSSProperties = {
  fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', margin: 0, marginBottom: '16px',
}

export const inputBox: CSSProperties = {
  ...inputStyle,
  background: 'rgba(255,255,255,0.05)',
  border: '1px solid #3D3D3D',
  borderRadius: '8px',
}

export const selectStyle: CSSProperties = {
  ...inputBox,
  appearance: 'none',
  cursor: 'pointer',
}

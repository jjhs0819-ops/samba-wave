import { light as c } from '@/lib/samba/colors'
import type { CSSProperties } from 'react'
import type { SambaMarketAccount } from '@/lib/samba/api/commerce'

export const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  requested: { label: '요청됨', bg: 'rgba(255,211,61,0.15)', text: c.warn },
  approved:  { label: '승인됨', bg: 'rgba(76,154,255,0.15)', text: c.link },
  rejected:  { label: '거절됨', bg: 'rgba(255,107,107,0.15)', text: c.danger },
  completed: { label: '완료됨', bg: 'rgba(81,207,102,0.15)', text: c.success },
  cancelled: { label: '취소됨', bg: 'rgba(100,100,100,0.2)', text: c.textMuted },
  collecting:    { label: '수거중', bg: 'rgba(255,165,0,0.15)', text: c.warn },
  collected:     { label: '수거완료', bg: 'rgba(81,207,102,0.15)', text: c.success },
  not_collected: { label: '미수거', bg: 'rgba(255,107,107,0.15)', text: c.danger },
}

export const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  return:   { label: '반품', color: c.danger },
  exchange: { label: '교환', color: c.link },
  cancel:   { label: '취소', color: c.textMuted },
}

// 구버전 반품사유 목록
export const RETURN_REASONS = [
  { value: '', label: '직접입력' },
  { value: '상품 불량/파손', label: '상품 불량/파손' },
  { value: '사이즈 불일치', label: '사이즈 불일치' },
  { value: '색상/디자인 불일치', label: '색상/디자인 불일치' },
  { value: '배송 중 파손', label: '배송 중 파손' },
  { value: '오배송 (다른 상품)', label: '오배송 (다른 상품)' },
  { value: '단순 변심', label: '단순 변심' },
  { value: '상품 설명과 다름', label: '상품 설명과 다름' },
  { value: '배송 지연', label: '배송 지연' },
  { value: '주문 실수', label: '주문 실수' },
  { value: '품질 불만족', label: '품질 불만족' },
]

// 날짜 → M/D 포맷
export const fmtMD = (d?: string | null) => {
  if (!d) return '-'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '-'
  return `${dt.getMonth() + 1}/${dt.getDate()}`
}

export const getAccountOptionLabel = (account: SambaMarketAccount) => (
  account.account_label?.trim()
  || account.seller_id?.trim()
  || account.business_name?.trim()
  || account.market_name
)

export const tdCenter: CSSProperties = {
  padding: '0.625rem', fontSize: '0.8125rem',
  whiteSpace: 'nowrap', textAlign: 'center', verticalAlign: 'middle',
}

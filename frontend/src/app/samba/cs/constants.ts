import { light as c } from '@/lib/samba/colors'

export const REPLY_STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: '미답변', bg: 'rgba(232,133,42,0.15)', text: c.warn },
  replied: { label: '답변완료', bg: 'rgba(56,154,56,0.15)', text: c.success },
}

export const INQUIRY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  general: { label: '주문문의', color: c.primary },
  product: { label: '주문문의', color: c.primary },
  qna: { label: '상품문의', color: c.link },
  call_center: { label: '주문문의', color: c.primary },
  delivery: { label: '주문문의', color: c.primary },
  exchange_return: { label: '주문문의', color: c.primary },
  exchange_request: { label: '교환요청', color: c.warn },
  cancel_request: { label: '취소요청', color: c.danger },
  product_question: { label: '상품문의', color: c.link },
}

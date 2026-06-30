export const REPLY_STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: '미답변', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  replied: { label: '답변완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
}

export const INQUIRY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  general: { label: '주문문의', color: '#FF8C00' },
  product: { label: '주문문의', color: '#FF8C00' },
  qna: { label: '상품문의', color: '#4C9AFF' },
  call_center: { label: '주문문의', color: '#FF8C00' },
  delivery: { label: '주문문의', color: '#FF8C00' },
  exchange_return: { label: '주문문의', color: '#FF8C00' },
  exchange_request: { label: '교환요청', color: '#FFB6C1' },
  cancel_request: { label: '취소요청', color: '#FF5050' },
  product_question: { label: '상품문의', color: '#4C9AFF' },
}

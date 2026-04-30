export const SOURCE_SITES = ['MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'REXMONDE', 'SSG', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

// 주문상태 목록 (배송중/배송완료는 가장 우측)
export const ORDER_STATUSES = [
  { key: 'pending', label: '주문접수' },
  { key: 'wait_ship', label: '배송대기중' },
  { key: 'preparing', label: '상품준비중' },
  { key: 'arrived', label: '사무실도착' },
  { key: 'ship_failed', label: '송장전송실패' },
  { key: 'cancelling', label: '취소중' },
  { key: 'returning', label: '반품중' },
  { key: 'exchanging', label: '교환중' },
  { key: 'exchange_requested', label: '교환요청' },
  { key: 'cancel_requested', label: '취소요청' },
  { key: 'return_requested', label: '반품요청' },
  { key: 'cancelled', label: '취소완료' },
  { key: 'returned', label: '반품완료' },
  { key: 'exchanged', label: '교환완료' },
  { key: 'shipping', label: '배송중' },
  { key: 'delivered', label: '배송완료' },
  { key: 'confirmed', label: '구매확정' },
]
// 기본 선택 상태
export const DEFAULT_STATUSES = ['pending', 'wait_ship', 'preparing', 'arrived', 'shipping', 'delivered', 'confirmed', 'exchanged', 'exchanging', 'exchange_requested']

export interface AnalyticsSearch {
  year: number
  month: number
  markets: string[]
  sites: string[]
  statuses: string[]
}

export interface MonthlyCell {
  sales: number
  orders: number
}

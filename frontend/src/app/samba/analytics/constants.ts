export const SOURCE_SITES = ['MUSINSA', 'KREAM', 'SNKRDUNK', 'BUNJANG', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'REXMONDE', 'SSG', 'LOTTEON', 'GSShop', 'ElandMall', 'SSF']

// 미등록상품(source_site 없음 또는 SOURCE_SITES 밖) — 소싱사이트 필터에서 토글 가능한 항목
export const UNREGISTERED_SITE = '미등록상품'
// 소싱사이트 필터 UI/전체선택 기준 목록 (실제 소싱처 + 미등록상품)
export const SITE_FILTER_OPTIONS = [...SOURCE_SITES, UNREGISTERED_SITE]

// 대소문자 변형(GSSHOP/ABCMART 등) → 정식 표기 정규화 테이블
const SITE_CANON: Record<string, string> = Object.fromEntries(SOURCE_SITES.map(s => [s.toUpperCase(), s]))

// 채널명("G마켓(계정)" 형태)에서 마켓명만 추출
export const channelToMarket = (name: string | undefined): string => {
  if (!name) return '기타'
  const idx = name.indexOf('(')
  return (idx > 0 ? name.substring(0, idx) : name).trim()
}

// 통계 행의 소싱처 분류 키
// - 크림 "판매" 주문은 source_site에 판매처명 'KREAM'이 저장돼 있음(주문화면 의존성 때문에 DB 수정 불가)
//   → 통계에서는 실제 소싱처인 스니덩크로 재해석해 판매처/소싱처 필터 간섭 제거
// - GSSHOP/ABCMART 같은 대소문자 변형은 정식 표기로 정규화 (미등록상품 오분류 방지)
export const aggregateSiteKey = (channelName: string | undefined, sourceSite: string | undefined): string => {
  const raw = channelToMarket(channelName) === 'KREAM' ? 'SNKRDUNK' : (sourceSite || '')
  return SITE_CANON[raw.toUpperCase()] || UNREGISTERED_SITE
}

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

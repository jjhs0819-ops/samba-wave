/**
 * SambaWave 공용 상수
 * SITE_COLORS, PERIOD_BUTTONS 등 여러 페이지에서 공유
 */

/** 소싱처별 테마 색상 */
export const SITE_COLORS: Record<string, string> = {
  MUSINSA: '#4C9AFF',
  KREAM: '#51CF66',
  DANAWA: '#FF922B',
  FashionPlus: '#CC5DE8',
  Nike: '#FF6B6B',
  Adidas: '#FFD93D',
  ABCmart: '#FF8C00',
  GrandStage: '#20C997',
  REXMONDE: '#F06595',
  SSG: '#FF5A2E',
  LOTTEON: '#E10044',
  GSShop: '#6B5CE7',
  ElandMall: '#4ECDC4',
  SSF: '#845EF7',
}

/** 기간 선택 버튼 (주문/CS/반품 공용) */
export const PERIOD_BUTTONS = [
  { key: 'lastmonth', label: '지난달' },
  { key: 'thismonth', label: '이번달' },
  { key: 'lastweek', label: '지난주' },
  { key: 'thisweek', label: '이번주' },
  { key: 'yesterday', label: '어제' },
  { key: 'today', label: '오늘' },
  { key: '1week', label: '일주일' },
  { key: '1month', label: '한달' },
  { key: 'thisyear', label: '올해' },
] as const

/** 소싱처 검색 URL (키워드 뒤에 붙여 사용) */
export const SOURCING_SEARCH_URLS: Record<string, string> = {
  MUSINSA: 'https://www.musinsa.com/search/musinsa/integration?q=',
  KREAM: 'https://kream.co.kr/search?keyword=',
  ABCmart: 'https://abcmart.a-rt.com/search?q=',
  LOTTEON: 'https://www.lotteon.com/search/search/search.ecn?render=search&platform=pc&q=',
}

/** 소싱처 상품 상세 URL (상품번호 뒤에 붙여 사용) */
export const SOURCING_PRODUCT_URLS: Record<string, string> = {
  MUSINSA: 'https://www.musinsa.com/products/',
  KREAM: 'https://kream.co.kr/products/',
  FashionPlus: 'https://www.fashionplus.co.kr/goods/detail/',
  ABCmart: 'https://www.a-rt.com/product?prdtNo=',
  Nike: 'https://www.nike.com/kr/t/',
  LOTTEON: 'https://www.lotteon.com/p/product/',
}

/** 소싱처 주문 상세 URL (주문번호 뒤에 붙여 사용) */
export const SOURCING_ORDER_URLS: Record<string, string> = {
  MUSINSA: 'https://www.musinsa.com/order/order-detail/',
  KREAM: 'https://kream.co.kr/my/purchasing/',
  FashionPlus: 'https://www.fashionplus.co.kr/mypage/order/detail/',
  ABCmart: 'https://www.a-rt.com/mypage/order-detail/',
  Nike: 'https://www.nike.com/kr/orders/',
}

/** 택배사별 배송 추적 URL (운송장번호 뒤에 붙여 사용) */
export const DELIVERY_TRACKING_URLS: Record<string, string> = {
  'CJ대한통운': 'https://trace.cjlogistics.com/next/tracking.html?wblNo=',
  '한진택배': 'https://www.hanjin.com/kor/CMS/DeliveryMgr/WaybillResult.do?mession=&searchType=General&wblnumText2=',
  '롯데택배': 'https://www.lotteglogis.com/home/reservation/tracking/link498?InvNo=',
  '로젠택배': 'https://www.ilogen.com/web/personal/trace/',
  '우체국택배': 'https://service.epost.go.kr/trace.RetrieveDomRi498.postal?sid1=',
  '경동택배': 'https://kdexp.com/deliverySearch?barcode=',
}

/** localStorage 키 상수 */
export const STORAGE_KEYS = {
  SAMBA_USER: 'samba_user',
  ANALYTICS_SEARCH: 'samba_analytics_search',
} as const

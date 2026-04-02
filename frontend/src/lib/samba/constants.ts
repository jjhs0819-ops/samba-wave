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
  OKmall: '#F06595',
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
  { key: 'thisyear', label: '올해' },
] as const

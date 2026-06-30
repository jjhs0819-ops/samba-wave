import { MARKET_KEYS } from './constants'
import { light as c } from '@/lib/samba/colors'

const marketColWidth = (mk: string) =>
  mk === 'coupang' || mk === 'ssg' || mk === 'ssg_std' || mk === 'gsshop' ? '360px' : '300px'

export const GRID_COLS = `80px 362px ${MARKET_KEYS.map(mk => marketColWidth(mk)).join(' ')} 40px`

// 가로 스크롤 시 사이트/소싱카테고리 컬럼 고정
export const stickyColA = { position: 'sticky' as const, left: 0, zIndex: 1 }
export const stickyColB = { position: 'sticky' as const, left: 80, zIndex: 1 }
export const stickyHeadA = {
  position: 'sticky' as const,
  left: 0,
  zIndex: 3,
  background: c.surface,
}
export const stickyHeadB = {
  position: 'sticky' as const,
  left: 80,
  zIndex: 3,
  background: c.surface,
}

export const colStyle = {
  flex: 1,
  minWidth: '140px',
  borderRight: `1px solid ${c.border}`,
  maxHeight: '280px',
  overflowY: 'auto' as const,
}

export const itemStyle = (isSelected: boolean) => ({
  padding: '0.5rem 0.75rem',
  fontSize: '0.8125rem',
  color: isSelected ? c.primary : c.text,
  cursor: 'pointer',
  background: isSelected ? 'rgba(37,99,235,0.08)' : 'transparent',
  transition: 'background 0.15s',
})

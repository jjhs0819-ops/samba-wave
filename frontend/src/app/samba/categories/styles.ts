import { dark, type Palette } from '@/lib/samba/colors'
import { MARKET_KEYS } from './constants'

const marketColWidth = (mk: string) =>
  mk === 'coupang' || mk === 'ssg' || mk === 'ssg_std' || mk === 'gsshop' ? '360px' : '300px'

export const GRID_COLS = `80px 362px ${MARKET_KEYS.map(mk => marketColWidth(mk)).join(' ')} 40px`

// 가로 스크롤 시 사이트/소싱카테고리 컬럼 고정
export const stickyColA = { position: 'sticky' as const, left: 0, zIndex: 1 }
export const stickyColB = { position: 'sticky' as const, left: 80, zIndex: 1 }
// 고정 헤더 배경 — 다크 기존값 #1F1F1F는 팔레트에 정확 대응 토큰이 없어 다크에선 그대로 유지,
// 라이트에선 헤더 행과 같은 표면색(c.surface)으로 맞춘다.
export const makeStickyHeadA = (c: Palette) => ({
  position: 'sticky' as const,
  left: 0,
  zIndex: 3,
  background: c === dark ? '#1F1F1F' : c.surface,
})
export const makeStickyHeadB = (c: Palette) => ({
  position: 'sticky' as const,
  left: 80,
  zIndex: 3,
  background: c === dark ? '#1F1F1F' : c.surface,
})

export const makeColStyle = (c: Palette) => ({
  flex: 1,
  minWidth: '140px',
  borderRight: `1px solid ${c.border}`,
  maxHeight: '280px',
  overflowY: 'auto' as const,
})

// 드릴다운 항목 — 선택 강조(주황)는 양 테마 공통 액센트로 유지,
// 비선택 글자는 다크 기존값 #C5C5C5 유지(정확 대응 토큰 없음) + 라이트는 보조 텍스트 토큰.
export const itemStyle = (isSelected: boolean, c: Palette) => ({
  padding: '0.5rem 0.75rem',
  fontSize: '0.8125rem',
  color: isSelected ? '#FF8C00' : c === dark ? '#C5C5C5' : c.textSub,
  cursor: 'pointer',
  background: isSelected ? 'rgba(255,140,0,0.08)' : 'transparent',
  transition: 'background 0.15s',
})

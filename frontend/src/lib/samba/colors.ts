/**
 * SambaWave 색상 토큰
 *
 * 기존 UI는 다크 hex(#0F0F0F·#2D2D2D·#E5E5E5 등)가 수백 곳 인라인으로 흩어져 있어
 * 테마 조정이 어려웠다. 화면별로 이 토큰을 점진 도입해 "의미 단위" 색 참조로 바꾼다.
 *
 * 사용 예) import { light as c } from '@/lib/samba/colors'
 *          style={{ background: c.surface, color: c.text, border: `1px solid ${c.border}` }}
 *
 * light = 더망고풍 밝은 테마(고밀도 테이블), dark = 기존 다크 테마 보존(향후 토글용).
 */

export interface Palette {
  pageBg: string       // 페이지 전체 배경
  surface: string      // 카드/테이블 표면
  surfaceAlt: string   // 교차행/옅은 면
  border: string       // 기본 테두리·구분선
  borderStrong: string // 강조 구분선
  text: string         // 본문 텍스트
  textSub: string      // 보조 텍스트
  textMuted: string    // 흐린 라벨
  headerBg: string     // 테이블 헤더 바 배경
  headerText: string   // 헤더 바 텍스트
  primary: string      // 브랜드 강조(주황)
  link: string         // 링크·파랑
  danger: string       // 빨강
  warn: string         // 주황·경고
  success: string      // 초록
  accentBg: string     // 옅은 강조 배경(노랑)
  btnBg: string        // 버튼 기본 배경
  btnBorder: string    // 버튼 테두리
  btnText: string      // 버튼 텍스트
  btnSolidBg: string   // 더망고풍 진한 솔리드 버튼 배경(주요 액션)
  btnSolidText: string // 솔리드 버튼 글씨
  inputBg: string      // 입력 배경
  gaugeTrack: string   // 게이지(용량바) 트랙(빈) 배경
  gaugeFill: string    // 게이지(용량바) 채움(중성 회색)
}

export const light: Palette = {
  pageBg: '#eef0f2',
  surface: '#ffffff',
  surfaceAlt: '#f4f5f6',
  border: '#c3c9cf',
  borderStrong: '#a3a9b0',
  text: '#14181f',
  textSub: '#3a434e',
  textMuted: '#5b646e',
  headerBg: '#2c3340',
  headerText: '#e8eaed',
  primary: '#2563eb',
  link: '#1c83e0',
  danger: '#d84444',
  warn: '#e8852a',
  success: '#389a38',
  accentBg: '#fcd8a8',
  btnBg: '#e9ecf1',
  btnBorder: '#c4cad1',
  btnText: '#404a59',
  btnSolidBg: '#15786a',
  btnSolidText: '#ffffff',
  inputBg: '#ffffff',
  gaugeTrack: '#e4e6e8',
  gaugeFill: '#525a64',
}

export const dark: Palette = {
  pageBg: '#0F0F0F',
  surface: 'rgba(30,30,30,0.5)',
  surfaceAlt: '#1A1A1A',
  border: '#2D2D2D',
  borderStrong: '#1C2333',
  text: '#E5E5E5',
  textSub: '#B0B0B0',
  textMuted: '#666666',
  headerBg: '#0D1117',
  headerText: '#94A3B8',
  primary: '#3b82f6',
  link: '#4C9AFF',
  danger: '#FF6B6B',
  warn: '#F59E0B',
  success: '#51CF66',
  accentBg: '#3A320F',
  btnBg: 'transparent',
  btnBorder: '#2D2D2D',
  btnText: '#B0B0B0',
  btnSolidBg: '#3a4150',
  btnSolidText: '#E5E5E5',
  inputBg: '#1A1A1A',
  gaugeTrack: '#232733',
  gaugeFill: '#6f7782',
}

/**
 * 라이트 입력칸 색 오버라이드.
 * 공용 inputStyle(styles.ts, 다크)은 여러 페이지가 공유하므로 직접 못 바꾼다.
 * 주문관리처럼 라이트인 화면에서만 `{ ...inputStyle, ...lightInput }` 로 색만 덮는다.
 */
export const lightInput = {
  background: light.inputBg,
  border: `1px solid ${light.border}`,
  color: light.text,
}

/**
 * 버튼 위계(variant) 헬퍼 — "차분하되 살아있게"
 *
 * 버튼이 인라인 style로 흩어져 위계가 없고, 상태칩·수치 색 옆에서 회색 버튼이 "죽어"
 * 보이는 문제를 정리한다. 보조 버튼은 옅은 회색 FILL로 또렷하게, 주요 액션은 차분한
 * 청록(틸)으로, 자주 쓰는 버튼은 색을 절제해 복원한다. 상태칩·수치 색은 유지한다.
 *
 * 색 값은 colors.ts의 버튼 토큰에서 온다(단일 출처). 헬퍼를 안 쓴 raw 인라인 버튼도
 * c.btnBg/c.btnBorder/c.btnSolidBg를 쓰면 동일하게 갱신된다.
 *   - btnBg #e9ecf1(보조 채움) · btnBorder #c4cad1 · btnText #404a59 · btnSolidBg #15786a(주요=틸)
 *
 * 사용법) 기존 인라인 style의 색/배경/테두리만 btn()으로 치환하고, 크기·레이아웃은 뒤에 유지.
 *   style={{ ...btn('secondary'), padding: '6px 14px', fontSize: '0.8rem' }}
 *
 * 변형 규칙:
 *   primary     화면/카드의 으뜸 액션(검색·전송·저장). 틸 솔리드. 화면당 1~2개.
 *   secondary   대다수 보조 액션. 옅은 회색 채움 → 또렷한 버튼감.
 *   accent      자주 쓰는 강조 버튼. 소프트 틸 틴트.
 *   send        발송류(SMS 등). 그린 솔리드.
 *   ghost       취소·닫기·초기화·복사·메뉴. 투명.
 *   danger      삭제·거부·중단 등 파괴적(평소 빨강 테두리로 절제).
 *   dangerSolid 삭제 확정·경보 모달 주액션 등 진짜 위험 확정에만.
 *   link        진짜 링크·drill-down. 텍스트+밑줄.
 *
 * 카카오 등 브랜드색, 토글 활성 의미색, 탭/페이지 선택 인디케이터, 상태 배지/수치 색은 손대지 않는다.
 */

import type { CSSProperties } from 'react'
import { dark, type Palette } from './colors'

export type BtnVariant = 'primary' | 'secondary' | 'accent' | 'send' | 'ghost' | 'danger' | 'dangerSolid' | 'link'

// 강조(메인색=틸의 옅은 틴트) — 토큰 외 전용 색
const ACC_BG = '#e3f4f0'
const ACC_BORDER = '#a9ddd2'
const ACC_TEXT = '#0f6a5b'

const BASE: CSSProperties = {
  borderRadius: '6px',
  fontWeight: 600,
  cursor: 'pointer',
  fontFamily: 'inherit',
  lineHeight: 1.2,
  whiteSpace: 'nowrap',
}

/** 버튼 변형의 색·배경·테두리 기본 스타일. 크기는 호출부에서 스프레드 뒤에 덮는다.
 *  palette 생략 시 라이트 팔레트 기본값. 테마 반응형이 필요하면 useTheme()의 c를 전달. */
export function btn(variant: BtnVariant, palette: Palette = dark): CSSProperties {
  const c = palette
  const variants: Record<BtnVariant, CSSProperties> = {
    primary: { background: c.btnSolidBg, color: c.btnSolidText, border: 'none', fontWeight: 700 },
    secondary: { background: c.btnBg, color: c.btnText, border: `1px solid ${c.btnBorder}` },
    accent: { background: ACC_BG, color: ACC_TEXT, border: `1px solid ${ACC_BORDER}` },
    send: { background: c.success, color: '#ffffff', border: 'none', fontWeight: 700 },
    ghost: { background: 'transparent', color: c.textMuted, border: 'none' },
    danger: { background: c.btnBg, color: c.danger, border: `1px solid ${c.danger}` },
    dangerSolid: { background: c.danger, color: '#ffffff', border: 'none', fontWeight: 700 },
    link: { background: 'none', color: c.link, border: 'none', textDecoration: 'underline', padding: 0 },
  }
  return { ...BASE, ...variants[variant] }
}

/** 비활성/로딩 시 덮어쓰는 오버레이: style={{ ...btn('primary'), ...(loading ? btnDisabled : null) }} */
export const btnDisabled: CSSProperties = {
  opacity: 0.55,
  cursor: 'not-allowed',
}

import type { CSSProperties } from 'react'
import type { SambaMarketAccount } from '@/lib/samba/api/commerce'
import type { Palette } from '@/lib/samba/colors'

export const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  requested: { label: '요청됨', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  approved:  { label: '승인됨', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  rejected:  { label: '거절됨', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  completed: { label: '완료됨', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelled: { label: '취소됨', bg: 'rgba(100,100,100,0.2)', text: '#888' },
  collecting:    { label: '수거중', bg: 'rgba(255,165,0,0.15)', text: '#FFA500' },
  collected:     { label: '수거완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  not_collected: { label: '미수거', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
}

export const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  return:   { label: '반품', color: '#FF6B6B' },
  exchange: { label: '교환', color: '#4C9AFF' },
  cancel:   { label: '취소', color: '#888' },
}

// 구버전 반품사유 목록
export const RETURN_REASONS = [
  { value: '', label: '직접입력' },
  { value: '상품 불량/파손', label: '상품 불량/파손' },
  { value: '사이즈 불일치', label: '사이즈 불일치' },
  { value: '색상/디자인 불일치', label: '색상/디자인 불일치' },
  { value: '배송 중 파손', label: '배송 중 파손' },
  { value: '오배송 (다른 상품)', label: '오배송 (다른 상품)' },
  { value: '단순 변심', label: '단순 변심' },
  { value: '상품 설명과 다름', label: '상품 설명과 다름' },
  { value: '배송 지연', label: '배송 지연' },
  { value: '주문 실수', label: '주문 실수' },
  { value: '품질 불만족', label: '품질 불만족' },
]

// 날짜 → M/D 포맷
export const fmtMD = (d?: string | null) => {
  if (!d) return '-'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '-'
  return `${dt.getMonth() + 1}/${dt.getDate()}`
}

export const getAccountOptionLabel = (account: SambaMarketAccount) => (
  account.account_label?.trim()
  || account.seller_id?.trim()
  || account.business_name?.trim()
  || account.market_name
)

// ── 반품교환탭 구획 분리 (T6·T9) ──
// 구획 키 — 급한 순서(사장님 확정): 취소요청 → 미수거 → 수거중·수거완료 → 반품완료 → 교환완료 → 기타
// (T9: 교환을 기타에서 분리해 6구획으로)
export type ReturnSectionKey = 'cancel_request' | 'not_collected' | 'collecting' | 'return_done' | 'exchange' | 'etc'

// 판정에 필요한 최소 필드만 구조적 타입으로 받는다 — SambaReturn 전체 타입 의존 회피
export interface ReturnSectionInput {
  type: string
  status: string
  market_order_status?: string
  completion_detail?: string
}

// 구획 판정 — 위에서부터 처음 맞는 구획에 배정(early return).
// 마지막 'etc' 가 나머지 전부를 무조건 받으므로, 어떤 행이든 정확히 한 구획에만
// 들어간다(빠지는 행 없음 = 구획별 건수 합계가 항상 전체 건수와 일치).
export const classifyReturnSection = (r: ReturnSectionInput): ReturnSectionKey => {
  // ★판정 순서 = '종결 여부' 먼저, 그다음 '진행 단계'.
  // 회수상태(status)를 먼저 보면 반품완료 건이 대부분 '수거완료'라 3번 구획으로 빨려들어가
  // 반품완료 구획이 텅 비고 수거 구획이 종결건으로 넘친다 (2026-09-03 수정).
  const detail = r.completion_detail || '진행중'
  // 1) 반품완료 — 완료내역이 '반품'이면 종결건이므로 진행 구획에 넣지 않는다
  if (detail === '반품') return 'return_done'
  // 2) 교환 건은 전용 구획으로 분리 (T9) — 회수·재출고 확인이 필요한 건이라 기타에 묻히면 안 됨
  if (r.type === 'exchange') return 'exchange'
  // 3) 그 밖의 종결건(취소완료·교환완료·거부) 은 '기타' — 더 볼 필요 없는 건
  if (detail === '취소' || detail === '교환' || detail === '거부') return 'etc'
  // 4) 진행중인 취소 클레임 — 승인 전 발주 여부를 확인해야 하는 건
  if (r.type === 'cancel' || (r.market_order_status || '').includes('취소요청')) return 'cancel_request'
  // 5) 회수 진행/완료
  if (r.status === 'collecting' || r.status === 'collected') return 'collecting'
  // 6) 나머지 진행중 = 아직 회수 안 된 건
  //    ★ status === 'not_collected' 로만 판정하면 안 된다 — 운영DB 실측(90일) 결과
  //    진행중 행의 status 는 대부분 requested/approved 라 '미수거' 구획이 0건이 된다.
  //    회수 어휘(collecting/collected)가 붙기 전 진행중 건은 전부 미수거로 본다.
  return 'not_collected'
}

export interface ReturnSectionDef {
  key: ReturnSectionKey
  label: string
  hint: string   // 중제목 오른쪽 흐린 안내문구
  fg: string     // 색 막대·구획명·건수 뱃지 색
  bg: string     // 중제목 행 배경 (옅은 색)
}

// 구획 정의(표시 순서 고정) — 색은 기존 STATUS_MAP/완료내역 색 계열을 팔레트(c)로 재사용
// (취소요청=빨강 danger · 미수거=주황 warn · 수거중=초록 success · 반품완료=핑크 · 교환완료=파랑 link · 기타=회색)
export const makeReturnSections = (c: Palette): ReturnSectionDef[] => [
  { key: 'cancel_request', label: '취소요청', hint: '취소 클레임 — 발주완료 건은 취소승인 금지', fg: c.danger, bg: 'rgba(255,107,107,0.10)' },
  { key: 'not_collected', label: '미수거', hint: '회수 대기 — 반송장 확인 필요', fg: c.warn, bg: 'rgba(255,165,0,0.10)' },
  { key: 'collecting', label: '수거중 · 수거완료', hint: '회수 진행/도착 건', fg: c.success, bg: 'rgba(81,207,102,0.10)' },
  { key: 'return_done', label: '반품완료', hint: '반품 처리 완료 건', fg: c.badgePinkFg, bg: c.badgePinkBg },
  { key: 'exchange', label: '교환완료', hint: '교환 건 — 회수·재출고 확인', fg: c.link, bg: 'rgba(76,154,255,0.10)' },
  { key: 'etc', label: '기타', hint: '취소완료·거부 등 — 기본 접힘', fg: c.textSub, bg: 'rgba(150,150,150,0.10)' },
]

// 백엔드 자동 기입 경고 메모("⚠️발주완료\n취소승인 금지") 판별 — 메모 셀 빨강 강조용
export const isOrderPlacedWarnMemo = (memo?: string | null): boolean => {
  const m = memo || ''
  return m.includes('발주완료') && m.includes('취소승인 금지')
}

export const tdCenter: CSSProperties = {
  padding: '0.625rem', fontSize: '0.8125rem',
  whiteSpace: 'nowrap', textAlign: 'center', verticalAlign: 'middle',
}

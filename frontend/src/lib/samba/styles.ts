/**
 * SambaWave 공용 스타일 상수
 * policies, settings 등 여러 페이지에서 공유
 */

export const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

export const inputStyle = {
  width: '100%',
  padding: '0.5rem 0.75rem',
  background: '#1A1A1A',
  border: '1px solid #2D2D2D',
  borderRadius: '6px',
  color: '#E5E5E5',
  fontSize: '0.875rem',
  outline: 'none',
  boxSizing: 'border-box' as const,
}

/** 숫자 포맷 (콤마 구분) */
export function fmtNum(v: number | string | null | undefined): string {
  const n = typeof v === 'number' ? v : Number(v ?? 0)
  if (!Number.isFinite(n)) return '0'
  return n.toLocaleString('ko-KR')
}

/** 콤마 포맷 문자열 → 숫자 파싱 */
export function fmtTextNumbers(text: string): string {
  const fmt = (value: string) => fmtNum(Number(value.replace(/,/g, '')))
  return text
    .replace(/\[(\d+)\/(\d+)\]/g, (_m, current: string, total: string) => `[${fmt(current)}/${fmt(total)}]`)
    .replace(/(^|[^\d,])(\d{4,})(?=(건|개|원|회|토큰|페이지))/g, (_m, prefix: string, value: string) => `${prefix}${fmt(value)}`)
    .replace(
      /((?:원가|판매가|정상가|계산가|성공|스킵|실패|상품|옵션|선택|총|전체|대기|완료|남은|중단|재고변동)\s*)(\d{4,})(?=(?:\D|$))/g,
      (_m, prefix: string, value: string) => `${prefix}${fmt(value)}`,
    )
}

export function parseNum(s: string): number {
  return Number(s.replace(/[^0-9.-]/g, '')) || 0
}

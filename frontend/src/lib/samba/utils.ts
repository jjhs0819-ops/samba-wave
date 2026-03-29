/**
 * SambaWave 공용 유틸 함수
 */

/**
 * ISO 날짜 문자열을 읽기 좋은 형식으로 변환
 * @param iso - ISO 날짜 문자열
 * @param sep - 연월일 구분자 (기본 '-')
 * @returns 'YYYY-MM-DD HH:mm' 또는 'YYYY.MM.DD HH:mm'
 */
export function fmtDate(iso: string | undefined | null, sep: string = '-'): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return typeof iso === 'string' ? iso.slice(0, 10) : '-'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}${sep}${m}${sep}${day} ${h}:${min}`
}

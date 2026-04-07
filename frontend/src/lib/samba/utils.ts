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
  // KST(Asia/Seoul, UTC+9) 기준으로 명시적 변환
  const kst = new Date(d.toLocaleString('en-US', { timeZone: 'Asia/Seoul' }))
  const y = kst.getFullYear()
  const m = String(kst.getMonth() + 1).padStart(2, '0')
  const day = String(kst.getDate()).padStart(2, '0')
  const h = String(kst.getHours()).padStart(2, '0')
  const min = String(kst.getMinutes()).padStart(2, '0')
  return `${y}${sep}${m}${sep}${day} ${h}:${min}`
}

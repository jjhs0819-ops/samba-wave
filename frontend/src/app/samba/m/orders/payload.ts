/**
 * 모바일 주문처리 — 소싱처 자동입력용 클립보드 페이로드.
 *
 * iOS 단축어가 `클립보드 가져오기` 로 읽어 파싱한다. 백엔드 엔드포인트나 장기토큰이
 * 필요 없고(단축어가 페이지 밖에서 클립보드를 읽으므로 CORS도 무관), 폰에서 바로 동작한다.
 * 마커(`SAMBA_ORDER|`)가 붙어 있어야 단축어가 우리 데이터로 인식한다.
 */

export const PAYLOAD_MARKER = 'SAMBA_ORDER|'

export interface AutofillPayload {
  /** 주문 id — 단축어 로그·중복 방지용 */
  orderId: string
  /** 수령인 이름 (마스킹 `*` 는 `o` 로 치환됨) */
  name: string
  /** 수령인 연락처 — 항상 사무실 전화 고정 (고객에게 소싱처 알림이 가지 않게) */
  phone: string
  /** 우편번호 */
  zip: string
  /** 도로명/지번 주소 */
  addr: string
  /** 상세주소 */
  detail: string
  /** 상품 옵션 (색상/사이즈) */
  option: string
  /** 수량 */
  qty: number
}

/** 마켓 주문 고객명은 개인정보 마스킹(`한*동`)이 섞여 있어 소싱처가 입력을 거부한다. */
export function cleanName(raw: string | null | undefined): string {
  return (raw || '').replace(/\*/g, 'o').trim()
}

export function buildPayloadText(p: AutofillPayload): string {
  return `${PAYLOAD_MARKER}${JSON.stringify(p)}`
}

/** 사람이 읽는 복사본 (C안 안전판 — 단축어가 안 먹을 때 손으로 붙여넣기) */
export function buildHumanText(p: AutofillPayload): string {
  return [
    p.name,
    p.phone,
    p.zip ? `[${p.zip}] ${p.addr}` : p.addr,
    p.detail,
  ]
    .filter(Boolean)
    .join('\n')
}

/** 클립보드 쓰기 — iOS 사파리는 사용자 제스처 안에서만 허용된다. */
export async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 구형 사파리 폴백
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}

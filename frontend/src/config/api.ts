/**
 * API 기본 URL 중앙 설정
 * 모든 API 클라이언트에서 이 값을 import하여 사용
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:28080'

/** API Gateway Key — 외부 앱 차단용 (캐주얼 접근 방지).
 * NEXT_PUBLIC_ 접두사로 브라우저에 노출되므로 보안 게이트가 아님.
 * 실제 API 보안은 JWT 인증이 담당한다. */
export const API_GATEWAY_KEY =
  process.env.NEXT_PUBLIC_API_GATEWAY_KEY || ''

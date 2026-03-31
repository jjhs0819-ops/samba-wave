/**
 * API 기본 URL 중앙 설정
 * 모든 API 클라이언트에서 이 값을 import하여 사용
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:28080'

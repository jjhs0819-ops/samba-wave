import { useEffect, useState } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'

// 프록시 서버 / 무신사 인증 상태를 관리하는 커스텀 훅
// - 마운트 시 두 엔드포인트를 호출해 상태 텍스트와 상태값을 갱신
// - setter들도 함께 반환하여 외부(예: CollectorStatusPanel)에서 재확인 가능
export type ProxyAuthStatus = 'checking' | 'ok' | 'error'

export default function useProxyAuth() {
  const [proxyStatus, setProxyStatus] = useState<ProxyAuthStatus>('checking')
  const [proxyText, setProxyText] = useState('프록시 서버 확인 중...')
  const [musinsaAuth, setMusinsaAuth] = useState<ProxyAuthStatus>('checking')
  const [musinsaAuthText, setMusinsaAuthText] = useState('인증 상태 확인 중...')

  // 프록시 서버 상태 확인
  const checkProxyStatus = () => {
    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/proxy-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === 'ok') {
          setProxyStatus('ok')
          setProxyText(data.message || '프록시 서버 정상 작동 중')
        } else {
          setProxyStatus('error')
          setProxyText(data.message || '프록시 서버 연결 실패')
        }
      })
      .catch(() => {
        setProxyStatus('error')
        setProxyText('백엔드 서버 연결 실패')
      })
  }

  // 무신사 인증 상태 확인
  const checkMusinsaAuth = () => {
    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === 'ok') {
          setMusinsaAuth('ok')
          setMusinsaAuthText(data.message || '무신사 인증 완료')
        } else {
          setMusinsaAuth('error')
          setMusinsaAuthText(data.message || '무신사 인증 필요')
        }
      })
      .catch(() => {
        setMusinsaAuth('error')
        setMusinsaAuthText('백엔드 서버 연결 실패')
      })
  }

  // 마운트 시 1회 체크 (기존 page.tsx 동작과 동일)
  useEffect(() => {
    checkProxyStatus()
    checkMusinsaAuth()
  }, [])

  return {
    proxyStatus,
    proxyText,
    musinsaAuth,
    musinsaAuthText,
    checkProxyStatus,
    checkMusinsaAuth,
    setProxyStatus,
    setProxyText,
    setMusinsaAuth,
    setMusinsaAuthText,
  }
}

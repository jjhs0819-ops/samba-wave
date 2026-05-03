import { useCallback, useEffect, useState } from 'react'
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

  // 프록시 서버 상태 확인 — 502/네트워크 오류 시 1회 재시도(1.5초 지연)
  // Caddy fail_duration 윈도우(5s) 내 단발성 502를 흡수하기 위함
  const checkProxyStatus = useCallback((retried = false) => {
    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/proxy-status`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
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
        if (!retried) {
          setTimeout(() => checkProxyStatus(true), 1500)
          return
        }
        setProxyStatus('error')
        setProxyText('백엔드 서버 연결 실패')
      })
  }, [])

  // 무신사 인증 상태 확인 — 동일하게 1회 재시도
  const checkMusinsaAuth = useCallback((retried = false) => {
    fetchWithAuth(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
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
        if (!retried) {
          setTimeout(() => checkMusinsaAuth(true), 1500)
          return
        }
        setMusinsaAuth('error')
        setMusinsaAuthText('백엔드 서버 연결 실패')
      })
  }, [])

  // 마운트 시 1회 체크 (기존 page.tsx 동작과 동일)
  useEffect(() => {
    const refreshAll = () => {
      checkProxyStatus()
      checkMusinsaAuth()
    }

    refreshAll()

    const intervalId = window.setInterval(refreshAll, 10000)
    const handleFocus = () => refreshAll()
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshAll()
    }

    window.addEventListener('focus', handleFocus)
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      window.clearInterval(intervalId)
      window.removeEventListener('focus', handleFocus)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [checkMusinsaAuth, checkProxyStatus])

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

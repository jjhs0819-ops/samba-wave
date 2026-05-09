'use client'

import { useState } from 'react'
import { SAMBA_PREFIX, fetchWithAuth } from '@/lib/samba/legacy'

export default function ExtensionLinkPage() {
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [message, setMessage] = useState('')

  async function issueKey() {
    setStatus('loading')
    try {
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/extension-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: `확장앱 ${new Date().toLocaleDateString('ko-KR')}` }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setMessage(err.detail || `오류 (HTTP ${res.status})`)
        setStatus('error')
        return
      }
      const data = await res.json()
      // 확장앱 content script 에 키 전달 (content-samba-deviceid.js 가 수신)
      window.postMessage(
        { source: 'samba-page', type: 'SAMBA_SET_API_KEY', apiKey: data.key },
        window.location.origin,
      )
      setMessage('✅ 확장앱 연결 완료! 이 탭을 닫아도 됩니다.')
      setStatus('done')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : '알 수 없는 오류')
      setStatus('error')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0F0F0F]">
      <div className="w-80 rounded-xl border border-[#2D2D2D] bg-[#1A1A1A] p-6 text-[#E5E5E5]">
        <h1 className="mb-1 text-lg font-bold text-[#FFB84D]">SAMBA-WAVE 확장앱 연결</h1>
        <p className="mb-5 text-xs text-[#888]">
          아래 버튼을 누르면 이 계정 전용 API 키를 발급해 확장앱에 자동 저장합니다.
        </p>

        {status !== 'done' && (
          <button
            onClick={issueKey}
            disabled={status === 'loading'}
            className="w-full rounded-md bg-[#FFB84D] py-2.5 text-sm font-bold text-black hover:bg-[#FFC870] disabled:opacity-50"
          >
            {status === 'loading' ? '발급 중...' : '🔑 API 키 발급 · 확장앱 연결'}
          </button>
        )}

        {message && (
          <p className={`mt-3 text-center text-sm ${status === 'error' ? 'text-red-400' : 'text-green-400'}`}>
            {message}
          </p>
        )}

        {status === 'idle' && (
          <p className="mt-4 text-center text-xs text-[#666]">
            로그인 상태여야 합니다. 미로그인 시{' '}
            <a href="/samba/login" className="text-[#FFB84D] underline">로그인</a>
            하세요.
          </p>
        )}
      </div>
    </div>
  )
}

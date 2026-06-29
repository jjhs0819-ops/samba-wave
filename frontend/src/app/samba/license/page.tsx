'use client'

import { useState } from 'react'

import { light as c } from '@/lib/samba/colors'
import { btn, btnDisabled } from '@/lib/samba/buttons'
import { verifyLicenseKey } from '@/lib/samba/api/license'
import { setLicenseKey } from '@/hooks/useLicenseCheck'

export default function LicensePage() {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async () => {
    const trimmed = key.trim().toUpperCase()
    if (!trimmed) return
    setLoading(true)
    setError('')
    try {
      const result = await verifyLicenseKey(trimmed)
      if (result.valid) {
        setLicenseKey(trimmed)
        window.location.href = '/samba'
      } else {
        setError(result.message)
      }
    } catch {
      setError('서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: c.pageBg }}>
      <div
        className="w-full max-w-md p-8 rounded-xl"
        style={{ background: c.surface, border: `1px solid ${c.border}` }}
      >
        <h1 className="text-2xl font-bold mb-2" style={{ color: c.text }}>
          라이선스 인증
        </h1>
        <p className="text-sm mb-8" style={{ color: c.textMuted }}>
          구매 시 발급받은 라이선스 키를 입력하세요.
        </p>
        <input
          type="text"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="SW-XXXX-XXXX-XXXX-XXXX"
          className="w-full rounded-lg px-4 py-3 text-sm font-mono mb-3 focus:outline-none"
          style={{
            background: c.inputBg,
            border: `1px solid ${c.border}`,
            color: c.text,
          }}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
        />
        {error && (
          <p className="text-sm mb-3" style={{ color: c.danger }}>
            {error}
          </p>
        )}
        <button
          onClick={handleSubmit}
          disabled={loading || !key.trim()}
          className="w-full font-semibold py-3 rounded-lg transition-colors"
          style={{
            ...btn('primary'),
            width: '100%',
            ...(loading || !key.trim() ? btnDisabled : null),
          }}
        >
          {loading ? '확인 중...' : '인증하기'}
        </button>
      </div>
    </div>
  )
}

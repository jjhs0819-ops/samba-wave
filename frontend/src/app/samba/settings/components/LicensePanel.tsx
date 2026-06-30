'use client'

import { useEffect, useState } from 'react'

import { verifyLicenseKey, type LicenseVerifyResult } from '@/lib/samba/api/license'
import { getLicenseKey, setLicenseKey } from '@/hooks/useLicenseCheck'
import { light as c } from '@/lib/samba/colors'
import { btn, btnDisabled } from '@/lib/samba/buttons'

export function LicensePanel() {
  const [currentKey, setCurrentKey] = useState<string | null>(null)
  const [newKey, setNewKey] = useState('')
  const [status, setStatus] = useState<LicenseVerifyResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    setCurrentKey(getLicenseKey())
  }, [])

  const maskKey = (key: string) => {
    const parts = key.split('-')
    if (parts.length === 5) return `${parts[0]}-${parts[1]}-****-****-${parts[4]}`
    return key
  }

  const handleVerify = async () => {
    const key = (editing ? newKey : currentKey)?.trim().toUpperCase()
    if (!key) return
    setLoading(true)
    try {
      const result = await verifyLicenseKey(key)
      setStatus(result)
      if (result.valid && editing) {
        setLicenseKey(key)
        setCurrentKey(key)
        setEditing(false)
        setNewKey('')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl p-6" style={{ background: c.surface, border: `1px solid ${c.border}` }}>
      <h2 className="font-semibold text-lg mb-4" style={{ color: c.text }}>
        라이선스
      </h2>

      {!editing && currentKey ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: c.textSub }}>
              라이선스 키
            </span>
            <span className="font-mono text-sm" style={{ color: c.text }}>
              {maskKey(currentKey)}
            </span>
          </div>
          {status && (
            <div className="text-sm" style={{ color: status.valid ? c.success : c.danger }}>
              {status.valid
                ? `유효 · ${status.expires_at ? `만료: ${status.expires_at.slice(0, 10)}` : '영구'}`
                : status.message}
            </div>
          )}
          <div className="flex gap-2 pt-2">
            <button
              onClick={handleVerify}
              disabled={loading}
              className="px-4 py-2 text-sm rounded-lg transition-colors"
              style={{ ...btn('secondary'), ...(loading ? btnDisabled : null) }}
            >
              {loading ? '확인 중...' : '재검증'}
            </button>
            <button
              onClick={() => setEditing(true)}
              className="px-4 py-2 text-sm rounded-lg"
              style={{ ...btn('ghost') }}
            >
              변경
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <input
            type="text"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="SW-XXXX-XXXX-XXXX-XXXX"
            className="w-full rounded-lg px-4 py-2.5 text-sm font-mono focus:outline-none"
            style={{ background: c.inputBg, border: `1px solid ${c.border}`, color: c.text }}
          />
          {status && !status.valid && (
            <p className="text-sm" style={{ color: c.danger }}>
              {status.message}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleVerify}
              disabled={loading || !newKey.trim()}
              className="px-4 py-2 text-sm rounded-lg transition-colors"
              style={{ ...btn('primary'), ...(loading || !newKey.trim() ? btnDisabled : null) }}
            >
              {loading ? '확인 중...' : '등록'}
            </button>
            {currentKey && (
              <button
                onClick={() => {
                  setEditing(false)
                  setNewKey('')
                  setStatus(null)
                }}
                className="px-4 py-2 text-sm rounded-lg"
                style={{ background: c.surfaceAlt, color: c.textSub }}
              >
                취소
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

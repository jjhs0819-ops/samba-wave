'use client'

import { useEffect, useState } from 'react'

import { verifyLicenseKey, type LicenseVerifyResult } from '@/lib/samba/api/license'
import { getLicenseKey, setLicenseKey } from '@/hooks/useLicenseCheck'

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
    <div className="rounded-xl p-6" style={{ background: '#1A1A1A', border: '1px solid #2A2A2A' }}>
      <h2 className="font-semibold text-lg mb-4" style={{ color: '#E5E5E5' }}>
        라이선스
      </h2>

      {!editing && currentKey ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm" style={{ color: '#888' }}>
              라이선스 키
            </span>
            <span className="font-mono text-sm" style={{ color: '#E5E5E5' }}>
              {maskKey(currentKey)}
            </span>
          </div>
          {status && (
            <div className="text-sm" style={{ color: status.valid ? '#4ADE80' : '#FF6B6B' }}>
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
              style={{ background: '#2A2A2A', color: '#E5E5E5', opacity: loading ? 0.5 : 1 }}
            >
              {loading ? '확인 중...' : '재검증'}
            </button>
            <button
              onClick={() => setEditing(true)}
              className="px-4 py-2 text-sm rounded-lg"
              style={{ background: '#2A2A2A', color: '#888' }}
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
            style={{ background: '#0F0F0F', border: '1px solid #3A3A3A', color: '#E5E5E5' }}
          />
          {status && !status.valid && (
            <p className="text-sm" style={{ color: '#FF6B6B' }}>
              {status.message}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleVerify}
              disabled={loading || !newKey.trim()}
              className="px-4 py-2 text-sm rounded-lg transition-colors"
              style={{
                background: loading || !newKey.trim() ? '#7A4A00' : '#FF8C00',
                color: '#fff',
                cursor: loading || !newKey.trim() ? 'not-allowed' : 'pointer',
              }}
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
                style={{ background: '#2A2A2A', color: '#888' }}
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

'use client'

import { useEffect, useState } from 'react'

import { fetchWithAuth, SAMBA_PREFIX } from '@/lib/samba/legacy'

interface License {
  id: string
  license_key: string
  buyer_name: string
  buyer_email: string
  is_active: boolean
  expires_at: string | null
  notes: string | null
  last_verified_at: string | null
  created_at: string
}

export default function LicenseAdminPage() {
  useEffect(() => {
    document.title = 'SAMBA-라이선스관리'
  }, [])

  const [licenses, setLicenses] = useState<License[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ buyer_name: '', buyer_email: '', expires_at: '', notes: '' })
  const [creating, setCreating] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses`)
      if (res.ok) setLicenses(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const create = async () => {
    setCreating(true)
    try {
      const body: Record<string, string | null> = {
        buyer_name: form.buyer_name,
        buyer_email: form.buyer_email,
        notes: form.notes || null,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
      }
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        setForm({ buyer_name: '', buyer_email: '', expires_at: '', notes: '' })
        await load()
      }
    } finally {
      setCreating(false)
    }
  }

  const toggle = async (id: string, isActive: boolean) => {
    await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: isActive }),
    })
    await load()
  }

  const remove = async (id: string) => {
    if (!confirm('삭제하시겠습니까?')) return
    await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses/${id}`, { method: 'DELETE' })
    await load()
  }

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-8" style={{ color: '#E5E5E5' }}>
        라이선스 관리
      </h1>

      {/* 신규 발급 폼 */}
      <div className="rounded-xl p-6 mb-8" style={{ background: '#1A1A1A', border: '1px solid #2A2A2A' }}>
        <h2 className="font-semibold mb-4" style={{ color: '#E5E5E5' }}>
          신규 라이선스 발급
        </h2>
        <div className="grid grid-cols-2 gap-4 mb-4">
          {[
            { placeholder: '구매자 이름', field: 'buyer_name' as const },
            { placeholder: '구매자 이메일', field: 'buyer_email' as const },
          ].map(({ placeholder, field }) => (
            <input
              key={field}
              placeholder={placeholder}
              value={form[field]}
              onChange={(e) => setForm({ ...form, [field]: e.target.value })}
              className="rounded-lg px-4 py-2.5 text-sm focus:outline-none"
              style={{ background: '#0F0F0F', border: '1px solid #3A3A3A', color: '#E5E5E5' }}
            />
          ))}
          <input
            type="date"
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            className="rounded-lg px-4 py-2.5 text-sm focus:outline-none"
            style={{ background: '#0F0F0F', border: '1px solid #3A3A3A', color: '#E5E5E5' }}
            title="만료일 (비워두면 영구)"
          />
          <input
            placeholder="메모 (선택)"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            className="rounded-lg px-4 py-2.5 text-sm focus:outline-none"
            style={{ background: '#0F0F0F', border: '1px solid #3A3A3A', color: '#E5E5E5' }}
          />
        </div>
        <button
          onClick={create}
          disabled={creating || !form.buyer_name || !form.buyer_email}
          className="px-6 py-2.5 text-sm font-semibold rounded-lg"
          style={{
            background: creating || !form.buyer_name || !form.buyer_email ? '#7A4A00' : '#FF8C00',
            color: '#fff',
            cursor: creating || !form.buyer_name || !form.buyer_email ? 'not-allowed' : 'pointer',
          }}
        >
          {creating ? '생성 중...' : '발급'}
        </button>
      </div>

      {/* 라이선스 목록 */}
      <div className="rounded-xl overflow-hidden" style={{ background: '#1A1A1A', border: '1px solid #2A2A2A' }}>
        <table className="w-full text-sm">
          <thead style={{ borderBottom: '1px solid #2A2A2A' }}>
            <tr style={{ color: '#888' }}>
              {['키', '구매자', '만료일', '마지막 검증', '상태', ''].map((h) => (
                <th key={h} className="text-left p-4">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="text-center py-8" style={{ color: '#555' }}>
                  불러오는 중...
                </td>
              </tr>
            ) : (
              licenses.map((lic) => (
                <tr key={lic.id} style={{ borderBottom: '1px solid #2A2A2A' }}>
                  <td className="p-4 font-mono text-xs" style={{ color: '#AAA' }}>
                    {lic.license_key}
                  </td>
                  <td className="p-4">
                    <div style={{ color: '#E5E5E5' }}>{lic.buyer_name}</div>
                    <div className="text-xs" style={{ color: '#666' }}>
                      {lic.buyer_email}
                    </div>
                  </td>
                  <td className="p-4" style={{ color: '#AAA' }}>
                    {lic.expires_at ? lic.expires_at.slice(0, 10) : '영구'}
                  </td>
                  <td className="p-4 text-xs" style={{ color: '#666' }}>
                    {lic.last_verified_at
                      ? lic.last_verified_at.slice(0, 16).replace('T', ' ')
                      : '-'}
                  </td>
                  <td className="p-4">
                    <span
                      className="px-2 py-1 rounded text-xs"
                      style={{
                        background: lic.is_active ? 'rgba(74,222,128,0.15)' : 'rgba(255,107,107,0.15)',
                        color: lic.is_active ? '#4ADE80' : '#FF6B6B',
                      }}
                    >
                      {lic.is_active ? '활성' : '비활성'}
                    </span>
                  </td>
                  <td className="p-4">
                    <div className="flex gap-2 justify-end">
                      <button
                        onClick={() => toggle(lic.id, !lic.is_active)}
                        className="px-3 py-1 text-xs rounded"
                        style={{ background: '#2A2A2A', color: '#AAA' }}
                      >
                        {lic.is_active ? '비활성화' : '활성화'}
                      </button>
                      <button
                        onClick={() => remove(lic.id)}
                        className="px-3 py-1 text-xs rounded"
                        style={{ background: 'rgba(255,107,107,0.15)', color: '#FF6B6B' }}
                      >
                        삭제
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

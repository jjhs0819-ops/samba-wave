'use client'

import { useState, useEffect } from 'react'
import { card, inputStyle } from '@/lib/samba/styles'
import { fetchWithAuth } from '@/lib/samba/api/shared'
import { showAlert } from '@/components/samba/Modal'

interface OfficeShipping {
  name: string
  phone: string
  address: string
  address_detail: string
}

export function OfficeShippingPanel() {
  const [form, setForm] = useState<OfficeShipping>({ name: '', phone: '', address: '', address_detail: '' })
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetchWithAuth('/api/v1/samba/proxy/config/office-shipping')
      .then(r => r.json())
      .then((d: OfficeShipping) => { setForm(d); setLoaded(true) })
      .catch(() => setLoaded(true))
  }, [])

  const handleSave = async () => {
    if (!form.name || !form.phone || !form.address) {
      showAlert('고객명, 번호, 주소는 필수 입력입니다', 'error')
      return
    }
    setSaving(true)
    try {
      const res = await fetchWithAuth('/api/v1/samba/proxy/config/office-shipping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (res.ok) {
        showAlert('사무실 배송정보 저장 완료')
      } else {
        showAlert('저장 실패', 'error')
      }
    } catch {
      showAlert('저장 실패', 'error')
    } finally {
      setSaving(false)
    }
  }

  if (!loaded) return null

  return (
    <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>사무실 배송정보 (주문처리용)</div>
      <div style={{ fontSize: '0.8rem', color: '#666', marginBottom: '1rem' }}>
        전화번호: 직배·까대기 모두 이 번호 사용 (판매자 기본 번호)<br />
        주소/이름: 까대기 주문 시 사용
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>고객명</label>
          <input
            style={inputStyle}
            value={form.name}
            onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
            placeholder="홍길동"
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>전화번호</label>
          <input
            style={inputStyle}
            value={form.phone}
            onChange={e => setForm(p => ({ ...p, phone: e.target.value }))}
            placeholder="010-0000-0000"
          />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>주소</label>
          <input
            style={inputStyle}
            value={form.address}
            onChange={e => setForm(p => ({ ...p, address: e.target.value }))}
            placeholder="서울시 강남구 테헤란로 123"
          />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>상세주소</label>
          <input
            style={inputStyle}
            value={form.address_detail}
            onChange={e => setForm(p => ({ ...p, address_detail: e.target.value }))}
            placeholder="101호"
          />
        </div>
      </div>
      <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{ padding: '0.5rem 1.25rem', background: '#1D4ED8', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.875rem', cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.6 : 1 }}
        >
          {saving ? '저장 중...' : '저장'}
        </button>
      </div>
    </div>
  )
}

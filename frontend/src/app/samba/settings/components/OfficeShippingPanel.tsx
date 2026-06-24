'use client'

import { useState, useEffect } from 'react'
import { card, inputStyle } from '@/lib/samba/styles'
import { fetchWithAuth, SAMBA_PREFIX } from '@/lib/samba/api/shared'
import { showAlert } from '@/components/samba/Modal'

interface OfficeShipping {
  name: string
  phone: string
  address: string
  address_detail: string
}

function splitPhone(phone: string): [string, string, string] {
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 11) return [digits.slice(0, 3), digits.slice(3, 7), digits.slice(7)]
  if (digits.length === 10) return [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6)]
  return [digits.slice(0, 3) || '', digits.slice(3, 7) || '', digits.slice(7) || '']
}

export function OfficeShippingPanel() {
  const [form, setForm] = useState<OfficeShipping>({ name: '', phone: '', address: '', address_detail: '' })
  const [ph, setPh] = useState<[string, string, string]>(['', '', ''])
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetchWithAuth(`${SAMBA_PREFIX}/proxy/config/office-shipping`)
      .then(r => r.json())
      .then((d: OfficeShipping) => {
        setForm(d)
        setPh(splitPhone(d.phone || ''))
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  const phoneStr = ph.join('-')

  const handleSave = async () => {
    if (!form.name || !phoneStr || !form.address) {
      showAlert('이름, 번호, 주소는 필수 입력입니다', 'error')
      return
    }
    setSaving(true)
    try {
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/proxy/config/office-shipping`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, phone: phoneStr }),
      })
      if (res.ok) {
        showAlert('사무실 배송정보 저장 완료')
      } else {
        const body = await res.text()
        showAlert(`저장 실패: ${body.slice(0, 80)}`, 'error')
      }
    } catch (e) {
      showAlert(`저장 실패: ${e instanceof Error ? e.message : String(e)}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  const phInput = (idx: 0 | 1 | 2, maxLen: number, placeholder: string) => (
    <input
      style={{ ...inputStyle, width: '100%', textAlign: 'center' }}
      value={ph[idx]}
      maxLength={maxLen}
      placeholder={placeholder}
      onChange={e => {
        const v = e.target.value.replace(/\D/g, '')
        const next: [string, string, string] = [...ph] as [string, string, string]
        next[idx] = v
        setPh(next)
      }}
    />
  )

  if (!loaded) return null

  return (
    <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>사무실 배송정보 (주문처리용)</div>
      <div style={{ fontSize: '0.8rem', color: '#666', marginBottom: '1rem' }}>
        전화번호: 직배·까대기 모두 이 번호 사용 (판매자 기본 번호)<br />
        이름/주소: 까대기 주문 시 사용
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>이름</label>
          <input
            style={inputStyle}
            value={form.name}
            onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
            placeholder="홍길동"
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>전화번호</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <div style={{ flex: '0 0 3rem' }}>{phInput(0, 3, '010')}</div>
            <span style={{ color: '#555' }}>-</span>
            <div style={{ flex: '0 0 4rem' }}>{phInput(1, 4, '0000')}</div>
            <span style={{ color: '#555' }}>-</span>
            <div style={{ flex: '0 0 4rem' }}>{phInput(2, 4, '0000')}</div>
          </div>
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={{ display: 'block', fontSize: '0.8rem', color: '#999', marginBottom: '0.25rem' }}>주소</label>
          <input
            style={inputStyle}
            value={form.address}
            onChange={e => setForm(p => ({ ...p, address: e.target.value }))}
            placeholder="도로명 주소 입력"
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

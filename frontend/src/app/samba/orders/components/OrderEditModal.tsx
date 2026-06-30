'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { inputStyle } from '@/lib/samba/styles'
import { lightInput } from '@/lib/samba/colors'
import { btn } from '@/lib/samba/buttons'
import { SHIPPING_COMPANIES } from '../constants'
import { useTheme } from '@/lib/samba/useTheme'

interface OrderForm {
  channel_id: string
  product_name: string
  customer_name: string
  customer_phone: string
  customer_address: string
  sale_price: number
  cost: number
  fee_rate: number
  shipping_company: string
  tracking_number: string
  notes: string
}

interface Props {
  open: boolean
  editingId: string | null
  form: OrderForm
  setForm: Dispatch<SetStateAction<OrderForm>>
  onClose: () => void
  onSubmit: () => void | Promise<void>
}

export default function OrderEditModal({ open, editingId, form, setForm, onClose, onSubmit }: Props) {
  const c = useTheme()
  if (!open) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '2rem', width: '640px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700 }}>{editingId ? '주문 수정' : '주문 추가'}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: c.textMuted, fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
          {[
            { key: 'product_name', label: '상품명', type: 'text' },
            { key: 'customer_name', label: '고객명', type: 'text' },
            { key: 'customer_phone', label: '전화번호', type: 'text' },
            { key: 'customer_address', label: '배송주소', type: 'text' },
            { key: 'sale_price', label: '판매가', type: 'number' },
            { key: 'cost', label: '원가', type: 'number' },
            { key: 'fee_rate', label: '수수료율(%)', type: 'number' },
            { key: 'tracking_number', label: '운송장번호', type: 'text' },
            { key: 'notes', label: '메모', type: 'text' },
          ].map(f => (
            <div key={f.key}>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>{f.label}</label>
              <input type={f.type} style={{ ...inputStyle, ...lightInput, width: '100%', padding: '0.5rem 0.75rem' }}
                value={String(form[f.key as keyof OrderForm])}
                onChange={e => setForm({ ...form, [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value })} />
            </div>
          ))}
          <div>
            <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>배송사</label>
            <select style={{ ...inputStyle, ...lightInput, width: '100%', padding: '0.5rem 0.75rem' }} value={form.shipping_company} onChange={e => setForm({ ...form, shipping_company: e.target.value })}>
              <option value="">선택</option>
              {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
            </select>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ ...btn('ghost'), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>취소</button>
          <button onClick={onSubmit} style={{ ...btn('primary'), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>저장</button>
        </div>
      </div>
    </div>
  )
}

'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { inputStyle } from '@/lib/samba/styles'

interface Props {
  open: boolean
  urlInput: string
  setUrlInput: Dispatch<SetStateAction<string>>
  imageInput: string
  setImageInput: Dispatch<SetStateAction<string>>
  saving: boolean
  onClose: () => void
  onSubmit: () => void | Promise<void>
}

export default function UrlInputModal({ open, urlInput, setUrlInput, imageInput, setImageInput, saving, onClose, onSubmit }: Props) {
  if (!open) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '520px', maxWidth: '90vw' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700 }}>상품 URL 등록</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>
        <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1rem' }}>
          소싱처 상품 URL과 이미지 URL을 입력하면 주문정보에 표시됩니다.
          <br />향후 동일 상품 주문에도 자동 적용됩니다.
        </p>
        <div style={{ marginBottom: '0.5rem' }}>
          <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.25rem', display: 'block' }}>상품 URL (원문링크)</label>
          <input
            type="text"
            placeholder="https://www.musinsa.com/app/goods/12345"
            style={{ ...inputStyle, width: '100%', padding: '0.625rem 0.75rem', fontSize: '0.875rem' }}
            value={urlInput}
            onChange={e => setUrlInput(e.target.value)}
            autoFocus
          />
        </div>
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.25rem', display: 'block' }}>이미지 URL</label>
          <input
            type="text"
            placeholder="https://image.musinsa.com/images/goods_img/..."
            style={{ ...inputStyle, width: '100%', padding: '0.625rem 0.75rem', fontSize: '0.875rem' }}
            value={imageInput}
            onChange={e => setImageInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onSubmit() }}
          />
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
          <button onClick={onSubmit} disabled={saving} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer' }}>
            {saving ? '저장중...' : '등록'}
          </button>
        </div>
      </div>
    </div>
  )
}

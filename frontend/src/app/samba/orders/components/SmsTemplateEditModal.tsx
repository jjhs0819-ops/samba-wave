'use client'

import React, { Dispatch, SetStateAction } from 'react'

interface SmsTemplate {
  id: string
  label: string
  msg: string
}

interface Props {
  template: SmsTemplate | null
  setTemplate: Dispatch<SetStateAction<SmsTemplate | null>>
  isNew: boolean
  onSave: () => void
}

export default function SmsTemplateEditModal({ template, setTemplate, isNew, onSave }: Props) {
  if (!template) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}>
      <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '1.5rem', width: '520px', maxWidth: '90vw' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>{isNew ? '새 템플릿 추가' : '템플릿 수정'}</h3>
          <button onClick={() => setTemplate(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>
        <div style={{ marginBottom: '0.75rem' }}>
          <label style={{ fontSize: '0.8125rem', color: '#888', display: 'block', marginBottom: '0.375rem' }}>템플릿 이름</label>
          <input
            type='text'
            value={template.label}
            onChange={e => setTemplate({ ...template, label: e.target.value })}
            placeholder='예: 주문취소안내'
            style={{ width: '100%', padding: '0.5rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem', outline: 'none', boxSizing: 'border-box' }}
          />
        </div>
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ fontSize: '0.8125rem', color: '#888', display: 'block', marginBottom: '0.375rem' }}>메시지 내용</label>
          <textarea
            value={template.msg}
            onChange={e => setTemplate({ ...template, msg: e.target.value })}
            rows={8}
            style={{ width: '100%', padding: '0.625rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.8125rem', outline: 'none', resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', boxSizing: 'border-box' }}
          />
          <div style={{ fontSize: '0.7rem', color: '#555', marginTop: '0.25rem' }}>
            사용 가능 변수: {'{{marketName}}'} {'{{goodsName}}'} {'{{rvcName}}'} {'{{sellerName}}'} {'{{OrderName}}'} {'{{rcvHPNo}}'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button onClick={() => setTemplate(null)} style={{ padding: '0.5rem 1rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
          <button
            onClick={onSave}
            disabled={!template.label.trim() || !template.msg.trim()}
            style={{ padding: '0.5rem 1rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer', opacity: (!template.label.trim() || !template.msg.trim()) ? 0.5 : 1 }}
          >저장</button>
        </div>
      </div>
    </div>
  )
}

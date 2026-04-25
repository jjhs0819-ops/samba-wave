'use client'

import React, { Dispatch, SetStateAction, RefObject } from 'react'
import { type SambaOrder, type MessageLog } from '@/lib/samba/api/commerce'

const MSG_VARIABLE_TAGS = [
  { tag: '{{sellerName}}', label: '판매자명' },
  { tag: '{{marketName}}', label: '판매마켓이름' },
  { tag: '{{OrderName}}', label: '주문번호' },
  { tag: '{{rvcName}}', label: '수취인명' },
  { tag: '{{rcvHPNo}}', label: '수취인휴대폰번호' },
  { tag: '{{goodsName}}', label: '상품명' },
]

interface SmsTemplate {
  id: string
  label: string
  msg: string
}

interface Props {
  msgModal: { type: 'sms' | 'kakao'; order: SambaOrder } | null
  setMsgModal: Dispatch<SetStateAction<{ type: 'sms' | 'kakao'; order: SambaOrder } | null>>
  msgText: string
  setMsgText: Dispatch<SetStateAction<string>>
  msgTextRef: RefObject<HTMLTextAreaElement | null>
  msgSending: boolean
  msgHistory: MessageLog[]
  smsTemplates: SmsTemplate[]
  insertMsgTag: (tag: string) => void
  openEditTemplate: (t: SmsTemplate) => void
  openNewTemplate: () => void
  deleteTemplate: (id: string) => void
  handleSendMsg: () => void | Promise<void>
}

export default function MessageModal(props: Props) {
  const {
    msgModal, setMsgModal,
    msgText, setMsgText,
    msgTextRef, msgSending, msgHistory,
    smsTemplates, insertMsgTag,
    openEditTemplate, openNewTemplate, deleteTemplate,
    handleSendMsg,
  } = props

  if (!msgModal) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '720px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>
            {msgModal.type === 'sms' ? 'SMS 발송' : '카카오톡 발송'}
          </h3>
          <button onClick={() => setMsgModal(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>

        {/* 주문 정보 */}
        <div style={{ background: '#111', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.8125rem' }}>
          <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '0.375rem' }}>
            <div><span style={{ color: '#666' }}>수신자: </span><span style={{ color: '#E5E5E5' }}>{msgModal.order.customer_name || '-'}</span></div>
            <div><span style={{ color: '#666' }}>전화번호: </span><span style={{ color: '#E5E5E5' }}>{msgModal.order.customer_phone}</span></div>
          </div>
          <div>
            <span style={{ color: '#666' }}>상품: </span>
            <span style={{ color: '#aaa' }}>{msgModal.order.product_name || '-'}</span>
          </div>
        </div>

        {/* 빠른 템플릿 카드 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '0.75rem' }}>
          {smsTemplates.map(t => (
            <div
              key={t.id}
              style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.625rem', transition: 'border-color 0.15s', position: 'relative' }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = '#FF8C00')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = '#2D2D2D')}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                <div
                  style={{ fontSize: '0.75rem', fontWeight: 600, color: '#E5E5E5', cursor: 'pointer', flex: 1 }}
                  onClick={() => setMsgText(t.msg)}
                >{t.label}</div>
                <div style={{ display: 'flex', gap: '0.25rem', flexShrink: 0 }}>
                  <button
                    onClick={e => { e.stopPropagation(); openEditTemplate(t) }}
                    style={{ background: 'none', border: 'none', color: '#888', fontSize: '0.65rem', cursor: 'pointer', padding: '0.1rem 0.25rem', lineHeight: 1 }}
                    title='수정'
                  >✏</button>
                  <button
                    onClick={e => { e.stopPropagation(); if (confirm(`"${t.label}" 템플릿을 삭제할까요?`)) deleteTemplate(t.id) }}
                    style={{ background: 'none', border: 'none', color: '#666', fontSize: '0.65rem', cursor: 'pointer', padding: '0.1rem 0.25rem', lineHeight: 1 }}
                    title='삭제'
                  >✕</button>
                </div>
              </div>
              <div
                style={{ fontSize: '0.625rem', color: '#777', lineHeight: '1.4', maxHeight: '3.5rem', overflow: 'hidden', whiteSpace: 'pre-wrap', wordBreak: 'break-word', cursor: 'pointer' }}
                onClick={() => setMsgText(t.msg)}
              >{t.msg.slice(0, 80)}...</div>
            </div>
          ))}
          {/* 새 템플릿 추가 카드 */}
          <div
            onClick={openNewTemplate}
            style={{ background: '#111', border: '1px dashed #3D3D3D', borderRadius: '8px', padding: '0.625rem', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.375rem', transition: 'border-color 0.15s', minHeight: '72px' }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#FF8C00')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = '#3D3D3D')}
          >
            <span style={{ fontSize: '1rem', color: '#555' }}>+</span>
            <span style={{ fontSize: '0.75rem', color: '#666' }}>새 템플릿</span>
          </div>
        </div>

        {/* 변수 태그 버튼 */}
        <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
          {MSG_VARIABLE_TAGS.map(v => (
            <button
              key={v.tag}
              type="button"
              onClick={() => insertMsgTag(v.tag)}
              style={{ padding: '0.2rem 0.5rem', fontSize: '0.6875rem', background: '#1A1A1A', border: '1px solid #444', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
            >{v.tag} <span style={{ color: '#888' }}>{v.label}</span></button>
          ))}
        </div>

        {/* 메시지 입력 */}
        <textarea
          ref={msgTextRef}
          value={msgText}
          onChange={e => setMsgText(e.target.value)}
          placeholder="메시지를 입력하세요"
          rows={5}
          style={{ width: '100%', padding: '0.625rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem', outline: 'none', resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.5rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.75rem', color: '#555' }}>
            {msgText.length > 0 ? `${new TextEncoder().encode(msgText).length}바이트` : ''}
            {msgText.length > 0 && new TextEncoder().encode(msgText).length > 90 ? ' (LMS)' : ''}
          </span>
        </div>

        {/* 이전 발송 기록 */}
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.5rem' }}>이전 발송 기록</div>
          <div style={{ maxHeight: '200px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
            {msgHistory.length === 0 ? (
              <div style={{ fontSize: '0.75rem', color: '#444', padding: '0.5rem', background: '#111', borderRadius: '6px' }}>이전 발송 기록 없음</div>
            ) : msgHistory.map(h => (
              <div key={h.id} style={{ background: '#111', border: `1px solid ${h.success ? '#2D3A2D' : '#3A2D2D'}`, borderRadius: '6px', padding: '0.5rem 0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.375rem', borderRadius: '3px', background: h.message_type === 'sms' ? '#1F3A24' : '#3A320F', color: h.message_type === 'sms' ? '#51CF66' : '#FFD93D', fontWeight: 600 }}>{h.message_type.toUpperCase()}</span>
                  <span style={{ fontSize: '0.65rem', color: '#666' }}>{h.sent_at ? new Date(h.sent_at).toLocaleString('ko-KR') : ''}</span>
                  <span style={{ fontSize: '0.65rem', color: h.success ? '#51CF66' : '#FF6B6B', marginLeft: 'auto' }}>{h.success ? '성공' : '실패'}</span>
                </div>
                <div style={{ fontSize: '0.7rem', color: '#B0B0B0', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: '1.4' }}>{h.rendered_message}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button onClick={() => setMsgModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
          <button
            onClick={handleSendMsg}
            disabled={msgSending}
            style={{
              padding: '0.625rem 1.25rem',
              background: msgModal.type === 'sms' ? '#51CF66' : '#FFD93D',
              border: 'none', borderRadius: '8px',
              color: msgModal.type === 'sms' ? '#fff' : '#1A1A1A',
              fontSize: '0.875rem', fontWeight: 600,
              cursor: msgSending ? 'not-allowed' : 'pointer',
              opacity: msgSending ? 0.6 : 1,
            }}
          >
            {msgSending ? '발송중...' : msgModal.type === 'sms' ? 'SMS 발송' : '카카오 발송'}
          </button>
        </div>
      </div>
    </div>
  )
}

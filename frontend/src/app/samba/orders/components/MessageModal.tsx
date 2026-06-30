'use client'

import React, { Dispatch, SetStateAction, RefObject } from 'react'
import { type SambaOrder, type MessageLog } from '@/lib/samba/api/commerce'
import { useTheme } from '@/lib/samba/useTheme'
import { btn, btnDisabled } from '@/lib/samba/buttons'

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
  msgPhone: string
  setMsgPhone: Dispatch<SetStateAction<string>>
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
  const c = useTheme()
  const {
    msgModal, setMsgModal,
    msgText, setMsgText,
    msgPhone, setMsgPhone,
    msgTextRef, msgSending, msgHistory,
    smsTemplates, insertMsgTag,
    openEditTemplate, openNewTemplate, deleteTemplate,
    handleSendMsg,
  } = props

  if (!msgModal) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '2rem', width: '720px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: c.text }}>
            {msgModal.type === 'sms' ? 'SMS 발송' : '카카오톡 발송'}
          </h3>
          <button onClick={() => setMsgModal(null)} style={{ background: 'none', border: 'none', color: c.textMuted, fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>

        {/* 주문 정보 */}
        <div style={{ background: c.surfaceAlt, borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.8125rem' }}>
          <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '0.375rem', alignItems: 'center' }}>
            <div><span style={{ color: c.textMuted }}>수신자: </span><span style={{ color: c.text }}>{msgModal.order.customer_name || '-'}</span></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <span style={{ color: c.textMuted }}>전화번호: </span>
              <input
                value={msgPhone}
                onChange={e => setMsgPhone(e.target.value)}
                placeholder="01012345678"
                style={{ width: '140px', padding: '0.25rem 0.5rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '6px', color: c.text, fontSize: '0.8125rem', outline: 'none' }}
              />
            </div>
          </div>
          <div>
            <span style={{ color: c.textMuted }}>상품: </span>
            <span style={{ color: c.textSub }}>{msgModal.order.product_name || '-'}</span>
          </div>
        </div>

        {/* 빠른 템플릿 카드 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '0.75rem' }}>
          {smsTemplates.map(t => (
            <div
              key={t.id}
              style={{ background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: '8px', padding: '0.625rem', transition: 'border-color 0.15s', position: 'relative' }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = '#a9ddd2')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = c.border)}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                <div
                  style={{ fontSize: '0.75rem', fontWeight: 600, color: c.text, cursor: 'pointer', flex: 1 }}
                  onClick={() => setMsgText(t.msg)}
                >{t.label}</div>
                <div style={{ display: 'flex', gap: '0.25rem', flexShrink: 0 }}>
                  <button
                    onClick={e => { e.stopPropagation(); openEditTemplate(t) }}
                    style={{ background: 'none', border: 'none', color: c.textMuted, fontSize: '0.65rem', cursor: 'pointer', padding: '0.1rem 0.25rem', lineHeight: 1 }}
                    title='수정'
                  >✏</button>
                  <button
                    onClick={e => { e.stopPropagation(); if (confirm(`"${t.label}" 템플릿을 삭제할까요?`)) deleteTemplate(t.id) }}
                    style={{ background: 'none', border: 'none', color: c.textMuted, fontSize: '0.65rem', cursor: 'pointer', padding: '0.1rem 0.25rem', lineHeight: 1 }}
                    title='삭제'
                  >✕</button>
                </div>
              </div>
              <div
                style={{ fontSize: '0.625rem', color: c.textMuted, lineHeight: '1.4', maxHeight: '3.5rem', overflow: 'hidden', whiteSpace: 'pre-wrap', wordBreak: 'break-word', cursor: 'pointer' }}
                onClick={() => setMsgText(t.msg)}
              >{t.msg.slice(0, 80)}...</div>
            </div>
          ))}
          {/* 새 템플릿 추가 카드 */}
          <div
            onClick={openNewTemplate}
            style={{ background: c.surfaceAlt, border: `1px dashed ${c.border}`, borderRadius: '8px', padding: '0.625rem', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.375rem', transition: 'border-color 0.15s', minHeight: '72px' }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = '#a9ddd2')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = c.border)}
          >
            <span style={{ fontSize: '1rem', color: c.textMuted }}>+</span>
            <span style={{ fontSize: '0.75rem', color: c.textMuted }}>새 템플릿</span>
          </div>
        </div>

        {/* 변수 태그 버튼 */}
        <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
          {MSG_VARIABLE_TAGS.map(v => (
            <button
              key={v.tag}
              type="button"
              onClick={() => insertMsgTag(v.tag)}
              style={{ padding: '0.2rem 0.5rem', fontSize: '0.6875rem', background: c.surface, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, cursor: 'pointer' }}
            >{v.tag} <span style={{ color: c.textMuted }}>{v.label}</span></button>
          ))}
        </div>

        {/* 메시지 입력 */}
        <textarea
          ref={msgTextRef}
          value={msgText}
          onChange={e => setMsgText(e.target.value)}
          placeholder="메시지를 입력하세요"
          rows={5}
          style={{ width: '100%', padding: '0.625rem 0.75rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '8px', color: c.text, fontSize: '0.875rem', outline: 'none', resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.5rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.75rem', color: c.textMuted }}>
            {msgText.length > 0 ? `${new TextEncoder().encode(msgText).length}바이트` : ''}
            {msgText.length > 0 && new TextEncoder().encode(msgText).length > 90 ? ' (LMS)' : ''}
          </span>
        </div>

        {/* 이전 발송 기록 */}
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', color: c.textMuted, marginBottom: '0.5rem' }}>이전 발송 기록</div>
          <div style={{ maxHeight: '200px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
            {msgHistory.length === 0 ? (
              <div style={{ fontSize: '0.75rem', color: c.textMuted, padding: '0.5rem', background: c.surfaceAlt, borderRadius: '6px' }}>이전 발송 기록 없음</div>
            ) : msgHistory.map(h => (
              <div key={h.id} style={{ background: c.surfaceAlt, border: `1px solid ${h.success ? c.success : c.danger}`, borderRadius: '6px', padding: '0.5rem 0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <span style={{ fontSize: '0.65rem', padding: '0.1rem 0.375rem', borderRadius: '3px', background: h.message_type === 'sms' ? c.surfaceAlt : c.accentBg, color: h.message_type === 'sms' ? c.success : c.warn, fontWeight: 600 }}>{h.message_type.toUpperCase()}</span>
                  <span style={{ fontSize: '0.65rem', color: c.textMuted }}>{h.sent_at ? new Date(h.sent_at).toLocaleString('ko-KR') : ''}</span>
                  <span style={{ fontSize: '0.65rem', color: h.success ? c.success : c.danger, marginLeft: 'auto' }}>{h.success ? '성공' : '실패'}</span>
                </div>
                <div style={{ fontSize: '0.7rem', color: c.textSub, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: '1.4' }}>{h.rendered_message}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
          <button onClick={() => setMsgModal(null)} style={{ ...btn('ghost'), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>취소</button>
          <button
            onClick={handleSendMsg}
            disabled={msgSending}
            style={{
              ...btn('send'),
              ...(msgSending ? btnDisabled : null),
              padding: '0.625rem 1.25rem',
              fontSize: '0.875rem',
            }}
          >
            {msgSending ? '발송중...' : msgModal.type === 'sms' ? 'SMS 발송' : '카카오 발송'}
          </button>
        </div>
      </div>
    </div>
  )
}

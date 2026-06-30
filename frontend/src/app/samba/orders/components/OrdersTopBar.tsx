'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'
import { formatDateInput, getKstTodayDate } from '@/lib/samba/utils'

import { btn } from '@/lib/samba/buttons'
import { light as c } from '@/lib/samba/colors'
import { useTheme } from '@/lib/samba/useTheme'

interface Notification {
  id: number
  message: string
  type: string
}

interface SmsRemain {
  SMS_CNT?: number
  LMS_CNT?: number
  MMS_CNT?: number
}

interface Props {
  notifications: Notification[]
  setNotifications: Dispatch<SetStateAction<Notification[]>>
  setStatusFilter: Dispatch<SetStateAction<string>>
  setMarketStatus: Dispatch<SetStateAction<string>>
  setCustomStart: Dispatch<SetStateAction<string>>
  setCustomEnd: Dispatch<SetStateAction<string>>
  setPeriod: Dispatch<SetStateAction<string>>
  isProductMode: boolean
  cpId: string | null
  cpName: string | null
  filteredOrdersCount: number
  pendingCount: number
  smsRemain: SmsRemain | null
  logMessages: string[]
  setLogMessages: (v: string[] | ((prev: string[]) => string[])) => void
}

function renderLogMessage(message: string) {
  const formatted = fmtTextNumbers(message)
  const savedLabel = '\uAC74 \uC2E0\uADDC \uC800\uC7A5'
  const parts = formatted.split(new RegExp(`(\\d[\\d,]*)(${savedLabel})`, 'g'))

  if (parts.length === 1) return formatted

  return parts.map((part, index) => {
    if (index % 3 === 1 && Number(part.replace(/,/g, '')) > 0) {
      return (
        <span key={`${part}-${index}`} style={{ color: c.text, fontWeight: 700 }}>
          {part}
        </span>
      )
    }
    return <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
  })
}

export default function OrdersTopBar(props: Props) {
  const c = useTheme()
  const {
    notifications, setNotifications, setStatusFilter, setMarketStatus,
    setCustomStart, setCustomEnd, setPeriod,
    isProductMode, cpId, cpName, filteredOrdersCount,
    pendingCount, smsRemain,
    logMessages, setLogMessages,
  } = props

  // 알림 메시지 안의 "N건"을 합산. notifications.length(알림 항목 수)는 항상 1이라
  // 9건이 1건으로 표시되던 버그(모달과 실제 필터 결과 불일치) 원인.
  const cancelAlertCount = notifications.reduce((sum, n) => {
    const m = n.message.match(/(\d[\d,]*)건/)
    if (!m) return sum
    const parsed = parseInt(m[1].replace(/,/g, ''), 10)
    return sum + (Number.isNaN(parsed) ? 0 : parsed)
  }, 0) || notifications.length

  return (
    <>
      {notifications.length > 0 && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: c.surface, border: `2px solid ${c.danger}`, borderRadius: '16px', padding: '2rem', maxWidth: '440px', width: '90%', boxShadow: '0 8px 32px rgba(255,68,68,0.3)', position: 'relative' }}>
            {/* X 닫기 (우측 상단) — 단순히 알람 닫기 */}
            <button
              aria-label='알람 닫기'
              title='닫기'
              onClick={() => setNotifications([])}
              style={{ position: 'absolute', top: '0.75rem', right: '0.75rem', width: '28px', height: '28px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: '6px', color: c.textSub, fontSize: '1.25rem', fontWeight: 700, cursor: 'pointer', lineHeight: 1 }}
              onMouseEnter={(e) => { e.currentTarget.style.color = c.danger; e.currentTarget.style.background = 'rgba(255,107,107,0.1)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = c.textSub; e.currentTarget.style.background = 'transparent' }}
            >
              &#10005;
            </button>
            <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>&#9888;</div>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: c.danger, marginBottom: '0.5rem' }}>마켓 취소 미반영 감지</h3>
              <p style={{ fontSize: '0.875rem', color: c.textSub, lineHeight: 1.5 }}>
                마켓에서 취소요청·취소완료된 주문이 <b style={{ color: c.danger }}>{fmtNum(cancelAlertCount)}건</b> 있지만 내부 상태가 아직 처리/배송 단계입니다. 발주·송장 등록 전에 확인해 주세요.
              </p>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                onClick={() => setNotifications([])}
                style={{ ...btn('ghost'), flex: 1, padding: '0.75rem', fontSize: '0.9375rem', fontWeight: 600 }}
              >
                나중에
              </button>
              <button
                onClick={() => {
                  setNotifications([])
                  setStatusFilter('')
                  setMarketStatus('cancel_requested')
                  setCustomStart('2020-01-01')
                  setCustomEnd(formatDateInput(getKstTodayDate()))
                  setPeriod('')
                }}
                style={{ ...btn('dangerSolid'), flex: 2, padding: '0.75rem', fontSize: '0.9375rem' }}
              >
                지금 확인하기
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        input[type=number]::-webkit-outer-spin-button,
        input[type=number]::-webkit-inner-spin-button {
          -webkit-appearance: none;
          margin: 0;
        }
        input[type=number] {
          -moz-appearance: textfield;
          appearance: textfield;
        }
      `}</style>

      {isProductMode && (
        <div style={{ background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.25)', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.85rem', color: c.text, fontWeight: 600 }}>상품별 매입대상</span>
            <span style={{ fontSize: '0.85rem', color: c.text, fontWeight: 500, maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {cpName || cpId}
            </span>
            <span style={{ fontSize: '0.75rem', color: c.textMuted }}>({fmtNum(filteredOrdersCount)}건)</span>
          </div>
          <a href='/samba/orders' style={{ fontSize: '0.75rem', color: c.link, textDecoration: 'none', padding: '4px 10px', border: `1px solid ${c.border}`, borderRadius: '5px', background: c.surfaceAlt, whiteSpace: 'nowrap' }}>전체 주문 보기</a>
        </div>
      )}

      <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>{isProductMode ? '상품 판매이력' : '주문 상황'}</h2>
          <p style={{ fontSize: '0.875rem', color: c.textMuted }}>
            미배송: <span style={{ color: c.danger, fontWeight: 700 }}>{fmtNum(pendingCount)}</span>건 / 전체: <span style={{ fontWeight: 700 }}>{fmtNum(filteredOrdersCount)}</span>건
          </p>
        </div>
        {smsRemain && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: '8px' }}>
            <span style={{ fontSize: '0.8125rem', color: c.textSub, fontWeight: 600 }}>SMS 잔여</span>
            <span style={{ fontSize: '0.8125rem', color: c.text }}>SMS <span style={{ color: c.success, fontWeight: 700 }}>{fmtNum(smsRemain.SMS_CNT)}</span>건</span>
            <span style={{ fontSize: '0.8125rem', color: c.text }}>LMS <span style={{ color: c.text, fontWeight: 700 }}>{fmtNum(smsRemain.LMS_CNT)}</span>건</span>
            <span style={{ fontSize: '0.8125rem', color: c.text }}>MMS <span style={{ color: c.text, fontWeight: 700 }}>{fmtNum(smsRemain.MMS_CNT)}</span>건</span>
          </div>
        )}
      </div>

      <div style={{ border: `1px solid ${c.borderStrong}`, borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: c.headerBg, borderBottom: `1px solid ${c.borderStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: c.headerText }}>주문 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ fontSize: '0.72rem', color: c.textMuted, background: 'transparent', border: `1px solid ${c.borderStrong}`, padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 로그가 초기화되었습니다.'])} style={{ fontSize: '0.72rem', color: c.textMuted, background: 'transparent', border: `1px solid ${c.borderStrong}`, padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={el => { if (el) el.scrollTop = el.scrollHeight }} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: c.textMuted, background: c.surfaceAlt, lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: c.textMuted, fontSize: 'inherit', margin: 0 }}>{renderLogMessage(msg)}</p>)}
        </div>
      </div>
    </>
  )
}

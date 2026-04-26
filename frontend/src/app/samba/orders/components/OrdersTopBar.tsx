'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'

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

export default function OrdersTopBar(props: Props) {
  const {
    notifications, setNotifications, setStatusFilter, setMarketStatus,
    setCustomStart, setCustomEnd, setPeriod,
    isProductMode, cpId, cpName, filteredOrdersCount,
    pendingCount, smsRemain,
    logMessages, setLogMessages,
  } = props

  return (
    <>
      {notifications.length > 0 && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: '#1A1A1A', border: '2px solid #FF4444', borderRadius: '16px', padding: '2rem', maxWidth: '420px', width: '90%', boxShadow: '0 8px 32px rgba(255,68,68,0.3)' }}>
            <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>&#9888;</div>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#FF6B6B', marginBottom: '0.5rem' }}>주문 취소요청 감지</h3>
            </div>
            {notifications.map(n => (
              <div key={n.id} style={{ background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '0.75rem', color: '#FF6B6B', fontSize: '0.9375rem', fontWeight: 600 }}>
                {n.message}
              </div>
            ))}
            <button
              onClick={() => {
                setNotifications([])
                setStatusFilter('')
                setMarketStatus('취소요청')
                setCustomStart('2020-01-01')
                setCustomEnd(new Date().toLocaleDateString('sv-SE'))
                setPeriod('')
              }}
              style={{ width: '100%', padding: '0.75rem', background: '#FF4444', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '1rem', fontWeight: 700, cursor: 'pointer', marginTop: '0.5rem' }}
            >
              취소요청 확인하기
            </button>
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
            <span style={{ fontSize: '0.85rem', color: '#FF8C00', fontWeight: 600 }}>상품별 판매이력</span>
            <span style={{ fontSize: '0.85rem', color: '#E5E5E5', fontWeight: 500, maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {cpName || cpId}
            </span>
            <span style={{ fontSize: '0.75rem', color: '#888' }}>({fmtNum(filteredOrdersCount)}건)</span>
          </div>
          <a href='/samba/orders' style={{ fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', padding: '4px 10px', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '5px', background: 'rgba(76,154,255,0.08)', whiteSpace: 'nowrap' }}>전체 주문 보기 →</a>
        </div>
      )}

      <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>{isProductMode ? '상품 판매이력' : '주문 상황'}</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>
            미배송: <span style={{ color: '#FF6B6B', fontWeight: 700 }}>{fmtNum(pendingCount)}</span>건 / 전체: <span style={{ fontWeight: 700 }}>{fmtNum(filteredOrdersCount)}</span>건
          </p>
        </div>
        {smsRemain && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(76,154,255,0.08)', border: '1px solid rgba(76,154,255,0.2)', borderRadius: '8px' }}>
            <span style={{ fontSize: '0.8125rem', color: '#4C9AFF', fontWeight: 600 }}>SMS 잔여</span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>SMS <span style={{ color: '#51CF66', fontWeight: 700 }}>{fmtNum(smsRemain.SMS_CNT)}</span>건</span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>LMS <span style={{ color: '#FFB84D', fontWeight: 700 }}>{fmtNum(smsRemain.LMS_CNT)}</span>건</span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>MMS <span style={{ color: '#CC5DE8', fontWeight: 700 }}>{fmtNum(smsRemain.MMS_CNT)}</span>건</span>
          </div>
        )}
      </div>

      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>주문 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 로그가 초기화되었습니다.'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={el => { if (el) el.scrollTop = el.scrollHeight }} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{fmtTextNumbers(msg)}</p>)}
        </div>
      </div>
    </>
  )
}

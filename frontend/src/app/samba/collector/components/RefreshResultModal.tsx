'use client'

import { type RefreshResult } from '@/lib/samba/api/commerce'
import { fmtNum } from '@/lib/samba/styles'

interface Props {
  open: boolean
  result: RefreshResult | null
  onClose: () => void
}

export default function RefreshResultModal({ open, result, onClose }: Props) {
  if (!open || !result) return null

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.6)', display: 'flex',
        alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#1A1A1A', border: '1px solid #2D2D2D',
          borderRadius: '12px', padding: '1.5rem', minWidth: '360px',
          maxWidth: '440px',
        }}
      >
        <h3 style={{
          fontSize: '1rem', fontWeight: 700, color: '#E5E5E5',
          marginBottom: '1rem', margin: 0, paddingBottom: '0.75rem',
          borderBottom: '1px solid #2D2D2D',
        }}>
          일괄 갱신 결과
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', marginTop: '1rem' }}>
          {[
            { label: '전체 대상', value: result.total, color: '#C5C5C5' },
            { label: '갱신 완료', value: result.refreshed, color: '#51CF66' },
            { label: '가격/재고 변동', value: result.changed, color: '#FFD93D' },
            { label: '품절 전환', value: result.sold_out, color: '#FF6B6B' },
            { label: '자동 재전송', value: result.retransmitted, color: '#4C9AFF' },
            { label: '확장앱 필요', value: result.needs_extension.length, color: '#CC5DE8' },
            { label: '오류', value: result.errors, color: '#FF6B6B' },
          ].map((item) => (
            <div key={item.label} style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', padding: '0.375rem 0',
            }}>
              <span style={{ fontSize: '0.85rem', color: '#999' }}>{item.label}</span>
              <span style={{ fontSize: '0.95rem', fontWeight: 700, color: item.color }}>
                {fmtNum(item.value)}건
              </span>
            </div>
          ))}
        </div>
        <button
          onClick={onClose}
          style={{
            width: '100%', marginTop: '1.25rem', padding: '0.625rem',
            background: 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)',
            color: '#FF8C00', borderRadius: '8px', fontSize: '0.85rem',
            fontWeight: 600, cursor: 'pointer',
          }}
        >
          확인
        </button>
      </div>
    </div>
  )
}

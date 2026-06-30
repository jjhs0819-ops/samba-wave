'use client'

import { type RefreshResult } from '@/lib/samba/api/commerce'
import { fmtNum } from '@/lib/samba/styles'

import { btn } from '@/lib/samba/buttons'
import { useTheme } from '@/lib/samba/useTheme'

interface Props {
  open: boolean
  result: RefreshResult | null
  onClose: () => void
}

export default function RefreshResultModal({ open, result, onClose }: Props) {
  const c = useTheme()
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
          background: c.surface, border: `1px solid ${c.border}`,
          borderRadius: '12px', padding: '1.5rem', minWidth: '360px',
          maxWidth: '440px',
        }}
      >
        <h3 style={{
          fontSize: '1rem', fontWeight: 700, color: c.text,
          marginBottom: '1rem', margin: 0, paddingBottom: '0.75rem',
          borderBottom: `1px solid ${c.border}`,
        }}>
          일괄 갱신 결과
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', marginTop: '1rem' }}>
          {[
            { label: '전체 대상', value: result.total, color: c.text },
            { label: '갱신 완료', value: result.refreshed, color: c.success },
            { label: '가격/재고 변동', value: result.changed, color: c.warn },
            { label: '품절 전환', value: result.sold_out, color: c.danger },
            { label: '자동 재전송', value: result.retransmitted, color: c.text },
            { label: '확장앱 필요', value: result.needs_extension.length, color: c.text },
            { label: '오류', value: result.errors, color: c.danger },
          ].map((item) => (
            <div key={item.label} style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', padding: '0.375rem 0',
            }}>
              <span style={{ fontSize: '0.85rem', color: c.textSub }}>{item.label}</span>
              <span style={{ fontSize: '0.95rem', fontWeight: 700, color: item.color }}>
                {fmtNum(item.value)}건
              </span>
            </div>
          ))}
        </div>
        <button
          onClick={onClose}
          style={{
            ...btn('primary'), width: '100%', marginTop: '1.25rem',
            padding: '0.625rem', borderRadius: '8px', fontSize: '0.85rem',
          }}
        >
          확인
        </button>
      </div>
    </div>
  )
}

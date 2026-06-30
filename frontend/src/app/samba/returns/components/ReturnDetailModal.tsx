'use client'

import type { SambaReturn } from '@/lib/samba/api/support'
import { fmtNum } from '@/lib/samba/styles'
import { STATUS_MAP, TYPE_LABELS } from '../constants'

interface Props {
  detailItem: SambaReturn | null
  onClose: () => void
}

export function ReturnDetailModal({ detailItem, onClose }: Props) {
  if (!detailItem) return null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '520px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>
            {TYPE_LABELS[detailItem.type]?.label || detailItem.type} 상세
          </h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
          {[
            { label: '주문 ID', value: detailItem.order_id },
            { label: '유형', value: TYPE_LABELS[detailItem.type]?.label || detailItem.type },
            { label: '수량', value: String(detailItem.quantity) },
            { label: '요청금액', value: detailItem.requested_amount ? `₩${fmtNum(detailItem.requested_amount)}` : '-' },
            { label: '상태', value: STATUS_MAP[detailItem.status]?.label || detailItem.status },
            { label: '등록일', value: detailItem.created_at?.slice(0, 10) || '-' },
          ].map(({ label, value }) => (
            <div key={label}>
              <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.25rem' }}>{label}</p>
              <p style={{ fontSize: '0.875rem', color: '#E5E5E5' }}>{value}</p>
            </div>
          ))}
          {detailItem.reason && (
            <div style={{ gridColumn: '1 / -1' }}>
              <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.25rem' }}>사유</p>
              <p style={{ fontSize: '0.875rem', color: '#E5E5E5' }}>{detailItem.reason}</p>
            </div>
          )}
        </div>

        {detailItem.timeline && detailItem.timeline.length > 0 && (
          <div>
            <h4 style={{ fontSize: '0.8125rem', color: '#888', fontWeight: 600, marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>처리 이력</h4>
            <div style={{ position: 'relative' }}>
              {detailItem.timeline.map((t, i) => {
                const st = STATUS_MAP[t.status]
                return (
                  <div key={i} style={{ display: 'flex', gap: '1rem', marginBottom: i < detailItem.timeline!.length - 1 ? '1rem' : 0 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
                      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: st?.text || '#555', flexShrink: 0 }} />
                      {i < detailItem.timeline!.length - 1 && (
                        <div style={{ width: '2px', flex: 1, background: '#2D2D2D', minHeight: '20px' }} />
                      )}
                    </div>
                    <div style={{ paddingBottom: i < detailItem.timeline!.length - 1 ? '0.5rem' : 0 }}>
                      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.25rem' }}>
                        <span style={{ fontSize: '0.8125rem', color: st?.text || '#888', fontWeight: 600 }}>{st?.label || t.status}</span>
                        <span style={{ fontSize: '0.75rem', color: '#555' }}>{t.date?.slice(0, 16) || ''}</span>
                      </div>
                      {t.message && <p style={{ fontSize: '0.8125rem', color: '#888' }}>{t.message}</p>}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

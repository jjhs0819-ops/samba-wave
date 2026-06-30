'use client'

import { useEffect, useState } from 'react'
import { orderApi, type SambaOrder, type TrackingInfo } from '@/lib/samba/api/commerce'
import { DELIVERY_TRACKING_URLS } from '@/lib/samba/constants'

interface Props {
  open: boolean
  order: SambaOrder | null
  onClose: () => void
}

const fmtTime = (iso: string | null): string => {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    return d.toLocaleString('ko-KR', {
      year: '2-digit', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
      hour12: false,
    })
  } catch {
    return iso
  }
}

// 진행 상태별 색상 (마지막 이벤트 강조용)
const statusColor = (code: string | null): string => {
  if (!code) return '#B0B0B0'
  if (code === 'delivered') return '#51CF66'
  if (code === 'out_for_delivery') return '#FF8C00'
  if (code === 'in_transit') return '#5EBAFF'
  if (code === 'at_pickup' || code === 'information_received') return '#FFD43B'
  return '#B0B0B0'
}

export default function TrackingModal({ open, order, onClose }: Props) {
  const [data, setData] = useState<TrackingInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !order) {
      setData(null)
      setError(null)
      return
    }
    const carrier = order.shipping_company || ''
    const invoice = order.tracking_number || ''
    if (!carrier || !invoice) {
      setError('택배사 또는 송장번호가 비어 있습니다')
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    orderApi.getTracking(carrier, invoice)
      .then(res => { if (!cancelled) setData(res) })
      .catch((e: unknown) => {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : '조회 실패'
        setError(msg)
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, order])

  if (!open || !order) return null

  const carrier = order.shipping_company || ''
  const invoice = order.tracking_number || ''
  const externalUrl = carrier && invoice ? `${DELIVERY_TRACKING_URLS[carrier] || ''}${invoice}` : ''

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', width: 'min(620px, 95vw)', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid #2D2D2D' }}>
          <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5' }}>택배 배송조회</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {externalUrl && (
              <a
                href={externalUrl}
                target="_blank"
                rel="noreferrer"
                style={{ fontSize: '0.7rem', padding: '0.2rem 0.55rem', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', textDecoration: 'none' }}
              >
                택배사 사이트
              </a>
            )}
            <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer' }}>✕</button>
          </div>
        </div>

        {/* 메타 정보 박스 */}
        <div style={{ padding: '12px 20px', borderBottom: '1px solid #2D2D2D', fontSize: '0.78rem', color: '#C5C5C5' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', rowGap: '6px', columnGap: '12px' }}>
            <span style={{ color: '#666' }}>주문번호</span>
            <span style={{ color: '#E5E5E5' }}>{order.order_number || '-'}</span>
            <span style={{ color: '#666' }}>상품명</span>
            <span style={{ color: '#E5E5E5', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{order.product_name || '-'}</span>
            <span style={{ color: '#666' }}>수령인</span>
            <span style={{ color: '#E5E5E5' }}>{order.customer_name || '-'}</span>
            <span style={{ color: '#666' }}>운송장번호</span>
            <span style={{ color: '#E5E5E5' }}>
              <span style={{ color: '#FF8C00', fontWeight: 600 }}>{carrier || '-'}</span>
              <span style={{ marginLeft: '8px' }}>({invoice || '-'})</span>
            </span>
            {data?.state && (
              <>
                <span style={{ color: '#666' }}>현재 상태</span>
                <span style={{ color: statusColor(data.events[data.events.length - 1]?.status_code || null), fontWeight: 600 }}>{data.state}</span>
              </>
            )}
          </div>
        </div>

        {/* 본문 */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '0' }}>
          {loading && (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: '#888', fontSize: '0.85rem' }}>
              조회 중...
            </div>
          )}
          {error && !loading && (
            <div style={{ padding: '24px 20px', color: '#FF6B6B', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>조회 실패: {error}</div>
              {externalUrl && (
                <a
                  href={externalUrl}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: '0.78rem', color: '#5EBAFF', textDecoration: 'underline' }}
                >
                  택배사 공식 페이지에서 직접 조회하기 →
                </a>
              )}
            </div>
          )}
          {!loading && !error && data && data.events.length === 0 && (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: '#888', fontSize: '0.85rem' }}>
              아직 배송 이력이 없습니다
            </div>
          )}
          {!loading && !error && data && data.events.length > 0 && (
            <div style={{ padding: '14px 20px' }}>
              {[...data.events].reverse().map((ev, i) => {
                const isLast = i === 0
                const dotColor = isLast ? statusColor(ev.status_code) : '#3A3A3A'
                const lineColor = '#2D2D2D'
                return (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '20px 1fr', columnGap: '12px', position: 'relative', paddingBottom: i === data.events.length - 1 ? '0' : '14px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                      <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: dotColor, marginTop: '4px', boxShadow: isLast ? `0 0 0 3px rgba(81,207,102,0.18)` : 'none' }} />
                      {i !== data.events.length - 1 && (
                        <div style={{ width: '2px', flex: 1, background: lineColor, marginTop: '2px', minHeight: '24px' }} />
                      )}
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '0.78rem', color: isLast ? '#E5E5E5' : '#C5C5C5', fontWeight: 600 }}>{ev.status || '-'}</span>
                        {ev.location && <span style={{ fontSize: '0.74rem', color: '#888' }}>· {ev.location}</span>}
                      </div>
                      {ev.description && (
                        <div style={{ fontSize: '0.74rem', color: '#777', marginTop: '2px', lineHeight: 1.45 }}>{ev.description}</div>
                      )}
                      <div style={{ fontSize: '0.7rem', color: '#555', marginTop: '3px' }}>{fmtTime(ev.time)}</div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

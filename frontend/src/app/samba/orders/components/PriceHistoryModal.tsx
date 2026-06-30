'use client'

import React from 'react'
import { fmtNum } from '@/lib/samba/styles'

interface Props {
  open: boolean
  product: { name: string; source_site: string }
  history: Record<string, unknown>[]
  onClose: () => void
}

export default function PriceHistoryModal({ open, product, history, onClose }: Props) {
  if (!open) return null

  const isKream = product.source_site === 'KREAM'
  const costPrices = history.map(h => Number(h.cost || h.sale_price || 0)).filter(Boolean)
  const currentPrice = costPrices[0] || 0
  const minPrice = costPrices.length ? Math.min(...costPrices) : 0
  const maxPrice = costPrices.length ? Math.max(...costPrices) : 0
  const minEntry = history.find(h => Number(h.cost || h.sale_price || 0) === minPrice)
  const maxEntry = history.find(h => Number(h.cost || h.sale_price || 0) === maxPrice)
  const kreamFastMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_fast_min as number || 0 : 0
  const kreamGeneralMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_general_min as number || 0 : 0
  const fmtHistDate = (d: string) => new Date(d).toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  const fmtShortDate = (d: string) => new Date(d).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

  if (history.length === 0) {
    return (
      <div style={{ position: 'fixed', inset: 0, zIndex: 99998, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.6)' }}
        onClick={onClose}>
        <div style={{ background: '#1A1A1A', borderRadius: '10px', padding: '2rem', color: '#888', fontSize: '0.85rem' }}>이력 로딩 중...</div>
      </div>
    )
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', width: 'min(700px, 95vw)', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}>
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid #2D2D2D' }}>
          <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5' }}>가격 / 재고 이력</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '0.75rem', color: '#666' }}>{fmtNum(history.length)}건 기록</span>
            <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer' }}>✕</button>
          </div>
        </div>
        {/* 상품 정보 + 요약 */}
        <div style={{ padding: '12px 20px', borderBottom: '1px solid #2D2D2D' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
            <span style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600 }}>{product.source_site}</span>
            <span style={{ fontSize: '0.75rem', color: '#999' }}>{product.name}</span>
          </div>
          {costPrices.length > 0 && (
            <div style={{ display: 'flex', gap: '20px', fontSize: '0.78rem', flexWrap: 'wrap' }}>
              {isKream && kreamFastMin > 0 && (
                <div><span style={{ color: '#666' }}>빠른배송 </span><span style={{ color: '#FF8C00', fontWeight: 600 }}>₩ {fmtNum(kreamFastMin)}</span></div>
              )}
              {isKream && kreamGeneralMin > 0 && (
                <div><span style={{ color: '#666' }}>일반배송 </span><span style={{ color: '#E5E5E5', fontWeight: 600 }}>₩ {fmtNum(kreamGeneralMin)}</span></div>
              )}
              {!isKream && (
                <div><span style={{ color: '#666' }}>현재가 </span><span style={{ color: '#E5E5E5', fontWeight: 600 }}>₩ {fmtNum(currentPrice)}</span></div>
              )}
              <div><span style={{ color: '#666' }}>최저가 </span><span style={{ color: '#51CF66', fontWeight: 600 }}>₩ {fmtNum(minPrice)}</span>{minEntry && <span style={{ color: '#555', fontSize: '0.68rem' }}> ({fmtShortDate(String(minEntry.date))})</span>}</div>
              <div><span style={{ color: '#666' }}>최고가 </span><span style={{ color: '#FF6B6B', fontWeight: 600 }}>₩ {fmtNum(maxPrice)}</span>{maxEntry && <span style={{ color: '#555', fontSize: '0.68rem' }}> ({fmtShortDate(String(maxEntry.date))})</span>}</div>
            </div>
          )}
        </div>
        {/* 이력 테이블 */}
        <div style={{ overflowY: 'auto', padding: '0' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ padding: '8px 16px', textAlign: 'left', color: '#888', fontWeight: 500 }}>날짜</th>
                {isKream ? (
                  <>
                    <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>빠른배송(₩)</th>
                    <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>일반배송(₩)</th>
                  </>
                ) : (
                  <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>원가(₩)</th>
                )}
                <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>재고(수량/O/X)</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => {
                const opts = (h.options || []) as Array<{ name?: string; price?: number; stock?: number; isSoldOut?: boolean }>
                return (
                  <React.Fragment key={i}>
                    <tr style={{ borderTop: i > 0 ? '1px solid #2D2D2D' : 'none', background: 'rgba(255,255,255,0.02)' }}>
                      <td style={{ padding: '8px 16px', color: '#C5C5C5', fontWeight: 600, fontSize: '0.78rem' }}>{fmtHistDate(String(h.date))}</td>
                      {isKream ? (
                        <>
                          <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FF8C00', fontWeight: 600 }}>
                            {(h as Record<string, unknown>).kream_fast_min ? `₩ ${fmtNum((h as Record<string, unknown>).kream_fast_min as number)}` : '-'}
                          </td>
                          <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                            {(h as Record<string, unknown>).kream_general_min ? `₩ ${fmtNum((h as Record<string, unknown>).kream_general_min as number)}` : '-'}
                          </td>
                        </>
                      ) : (
                        <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                          ₩ {fmtNum((h.cost || h.sale_price) as number)}
                        </td>
                      )}
                      <td style={{ padding: '8px 16px', textAlign: 'right', color: '#888' }}>
                        {opts.length > 0 ? `${fmtNum(opts.length)}개 옵션` : '-'}
                      </td>
                    </tr>
                    {opts.map((opt, oi) => {
                      const kOpt = opt as Record<string, unknown>
                      const soldOut = opt.isSoldOut || (opt.stock !== undefined && opt.stock <= 0)
                      const stockLabel = soldOut
                        ? '품절'
                        : opt.stock !== undefined
                          ? `${fmtNum(opt.stock)}개`
                          : 'O'
                      return (
                        <tr key={oi} style={{ borderTop: '1px solid #1A1A1A' }}>
                          <td style={{ padding: '4px 16px 4px 32px', color: '#666', fontSize: '0.73rem' }}>ㄴ {opt.name || `옵션${oi + 1}`}</td>
                          {isKream ? (
                            <>
                              <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                                {(kOpt.kreamFastPrice as number) > 0 ? `₩ ${fmtNum(kOpt.kreamFastPrice as number)}` : '-'}
                              </td>
                              <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                                {(kOpt.kreamGeneralPrice as number) > 0 ? `₩ ${fmtNum(kOpt.kreamGeneralPrice as number)}` : '-'}
                              </td>
                            </>
                          ) : (
                            <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                              ₩ {fmtNum((h.cost || h.sale_price) as number)}
                            </td>
                          )}
                          <td style={{ padding: '4px 16px', textAlign: 'right', fontSize: '0.73rem', fontWeight: 600, color: soldOut ? '#FF6B6B' : '#51CF66' }}>
                            {stockLabel}
                          </td>
                        </tr>
                      )
                    })}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

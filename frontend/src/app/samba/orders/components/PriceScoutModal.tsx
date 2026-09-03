'use client'

import React from 'react'
import { type SambaOrder, type SambaOrderPriceScan } from '@/lib/samba/api/commerce'
import { fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'
import { btn, btnDisabled } from '@/lib/samba/buttons'

// 소싱처 코드 → 한글 표기 (price_scout/service.py SCOUT_SITES 기준)
const SITE_LABELS: Record<string, string> = {
  MUSINSA: '무신사',
  ABCmart: 'ABC마트',
  LOTTEON: '롯데온',
  SSG: 'SSG',
  THEHYUNDAI: '더현대',
}

interface Props {
  open: boolean
  order: SambaOrder | null
  scan: SambaOrderPriceScan | null
  rescanning: boolean
  onRescan: () => void | Promise<void>
  onClose: () => void
}

/** 소싱처 최저가 탐색 결과 모달 — 사이트별 최저가·상품명·링크 + [다시 스캔] */
export default function PriceScoutModal({
  open, order, scan, rescanning, onRescan, onClose }: Props) {
  const c = useTheme()
  if (!open || !order) return null

  const results = scan?.results ?? []
  const orderCost = Number(order.cost ?? 0)
  const fmtScanDate = (d: string) => new Date(d).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '12px', width: 'min(700px, 95vw)', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        onClick={e => e.stopPropagation()}>
        {/* 헤더 */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: `1px solid ${c.border}` }}>
          <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: c.text }}>소싱처 최저가 탐색</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {scan?.scanned_at && (
              <span style={{ fontSize: '0.72rem', color: c.textMuted }}>스캔 {fmtScanDate(scan.scanned_at)}</span>
            )}
            <button
              onClick={onRescan}
              disabled={rescanning}
              title="24시간 캐시를 무시하고 소싱처 5곳을 다시 검색합니다"
              style={{ ...btn('primary', c), ...(rescanning ? btnDisabled : null), padding: '0.25rem 0.75rem', fontSize: '0.75rem' }}
            >{rescanning ? '스캔 중...' : '다시 스캔'}</button>
            <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: c.textMuted, fontSize: '1.2rem', cursor: 'pointer' }}>✕</button>
          </div>
        </div>

        {/* 주문 정보 + 요약 */}
        <div style={{ padding: '12px 20px', borderBottom: `1px solid ${c.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
            {scan?.model_code && (
              <span style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: c.accentBg, color: c.text, fontWeight: 600, fontFamily: 'monospace' }}>{scan.model_code}</span>
            )}
            <span style={{ fontSize: '0.75rem', color: c.textMuted }}>{order.product_name || '-'}</span>
          </div>
          <div style={{ display: 'flex', gap: '20px', fontSize: '0.78rem', flexWrap: 'wrap' }}>
            <div><span style={{ color: c.textMuted }}>내 원가 </span><span style={{ color: c.text, fontWeight: 600 }}>₩ {fmtNum(orderCost)}</span></div>
            {scan?.best_price != null && (
              <div>
                <span style={{ color: c.textMuted }}>전체 최저 </span>
                <span style={{ color: c.success, fontWeight: 600 }}>
                  {SITE_LABELS[scan.best_site || ''] || scan.best_site} ₩ {fmtNum(scan.best_price)}
                </span>
                {orderCost > 0 && scan.best_price < orderCost && (
                  <span style={{ color: c.danger, fontWeight: 600 }}> (-{fmtNum(orderCost - scan.best_price)})</span>
                )}
              </div>
            )}
            {scan?.suspect && (
              <div style={{ color: c.warn, fontWeight: 600 }}>⚠️ 오매칭 의심 — 원가 절반 미만. 링크로 실제 상품인지 확인하세요</div>
            )}
            {scan?.error && (
              <div style={{ color: c.danger }}>스캔 오류: {scan.error}</div>
            )}
          </div>
        </div>

        {/* 사이트별 결과 테이블 */}
        <div style={{ overflowY: 'auto', padding: '0' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${c.border}` }}>
                <th style={{ padding: '8px 16px', textAlign: 'left', color: c.textSub, fontWeight: 500 }}>소싱처</th>
                <th style={{ padding: '8px 16px', textAlign: 'right', color: c.textSub, fontWeight: 500 }}>최저가(₩)</th>
                <th style={{ padding: '8px 16px', textAlign: 'left', color: c.textSub, fontWeight: 500 }}>상품명</th>
                <th style={{ padding: '8px 16px', textAlign: 'center', color: c.textSub, fontWeight: 500 }}>링크</th>
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ padding: '24px 16px', textAlign: 'center', color: c.textMuted }}>
                    {scan ? '모델코드가 매칭된 소싱처 결과가 없습니다' : '아직 스캔 결과가 없습니다 — [다시 스캔]을 눌러주세요'}
                  </td>
                </tr>
              ) : [...results].sort((a, b) => a.price - b.price).map((r, i) => {
                const isBest = scan?.best_site === r.site && scan?.best_price === r.price
                const cheaper = orderCost > 0 && r.price < orderCost
                return (
                  <tr key={`${r.site}-${i}`} style={{ borderTop: i > 0 ? `1px solid ${c.border}` : 'none', background: isBest ? c.surfaceAlt : 'transparent' }}>
                    <td style={{ padding: '8px 16px', color: c.text, fontWeight: isBest ? 700 : 500 }}>
                      {isBest && '🔻 '}{SITE_LABELS[r.site] || r.site}
                    </td>
                    <td style={{ padding: '8px 16px', textAlign: 'right', color: cheaper ? c.danger : c.text, fontWeight: 600 }}>
                      ₩ {fmtNum(r.price)}
                      {cheaper && <span style={{ color: c.textMuted, fontSize: '0.68rem' }}> (-{fmtNum(orderCost - r.price)})</span>}
                    </td>
                    <td style={{ padding: '8px 16px', color: c.textSub, maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.name || ''}>
                      {r.name || '-'}
                    </td>
                    <td style={{ padding: '8px 16px', textAlign: 'center' }}>
                      {r.url ? (
                        <button
                          onClick={() => window.open(r.url as string, '_blank')}
                          style={{ ...btn('secondary', c), padding: '0.15rem 0.5rem', fontSize: '0.7rem' }}
                        >새 탭</button>
                      ) : (
                        <span style={{ color: c.textMuted, fontSize: '0.7rem' }}>-</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

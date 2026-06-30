'use client'

import { fmtNum } from '@/lib/samba/styles'

import { btn, btnDisabled } from '@/lib/samba/buttons'
import { useTheme } from '@/lib/samba/useTheme'

interface BrandSearchResult {
  brandCode: string
  brandName: string
}

interface MusinsaBrandModalProps {
  open: boolean
  brandSearchResults: BrandSearchResult[]
  pendingKeyword: string
  selectedBrandCodes: Set<string>
  setSelectedBrandCodes: React.Dispatch<React.SetStateAction<Set<string>>>
  onClose: () => void
  onConfirm: (codes: Set<string>) => void
}

// 무신사 브랜드 선택 모달
export default function MusinsaBrandModal({
  open,
  brandSearchResults,
  pendingKeyword,
  selectedBrandCodes,
  setSelectedBrandCodes,
  onClose,
  onConfirm,
}: MusinsaBrandModalProps) {
  const c = useTheme()
  if (!open || brandSearchResults.length === 0) return null

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '12px', padding: '24px 28px', minWidth: '360px', maxWidth: '500px' }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: c.text }}>브랜드 선택</h3>
        <p style={{ margin: '0 0 16px', fontSize: '0.78rem', color: c.textMuted }}>
          &quot;{pendingKeyword}&quot; 검색 결과 — 복수 선택 가능
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '50vh', overflowY: 'auto' }}>
          {brandSearchResults.map(b => {
            const checked = selectedBrandCodes.has(b.brandCode)
            return (
              <label key={b.brandCode}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 16px', background: checked ? '#e3f4f0' : c.surfaceAlt, border: `1px solid ${checked ? '#a9ddd2' : c.border}`, borderRadius: '8px', color: c.text, cursor: 'pointer', fontSize: '0.85rem', transition: 'border-color 0.15s' }}>
                <input type='checkbox' checked={checked}
                  onChange={() => setSelectedBrandCodes(prev => {
                    const next = new Set(prev)
                    if (next.has(b.brandCode)) next.delete(b.brandCode); else next.add(b.brandCode)
                    return next
                  })}
                  style={{ accentColor: c.primary, width: '15px', height: '15px', cursor: 'pointer' }} />
                <span style={{ fontWeight: 600, flex: 1 }}>{b.brandName}</span>
                <span style={{ color: c.textMuted, fontSize: '0.78rem' }}>{b.brandCode}</span>
              </label>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={() => onConfirm(selectedBrandCodes)}
            disabled={selectedBrandCodes.size === 0}
            style={{ ...btn('primary'), ...(selectedBrandCodes.size === 0 ? btnDisabled : null), flex: 1, padding: '10px', borderRadius: '8px', fontSize: '0.85rem' }}
          >
            선택 확인 ({fmtNum(selectedBrandCodes.size)}개)
          </button>
          <button
            onClick={() => onConfirm(new Set())}
            style={{ ...btn('secondary'), padding: '10px 16px', borderRadius: '8px', fontSize: '0.82rem' }}
          >
            전체 검색
          </button>
        </div>
      </div>
    </div>
  )
}

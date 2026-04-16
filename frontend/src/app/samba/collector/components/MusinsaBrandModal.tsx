'use client'

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
  if (!open || brandSearchResults.length === 0) return null

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '24px 28px', minWidth: '360px', maxWidth: '500px' }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: '#E5E5E5' }}>브랜드 선택</h3>
        <p style={{ margin: '0 0 16px', fontSize: '0.78rem', color: '#888' }}>
          &quot;{pendingKeyword}&quot; 검색 결과 — 복수 선택 가능
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '50vh', overflowY: 'auto' }}>
          {brandSearchResults.map(b => {
            const checked = selectedBrandCodes.has(b.brandCode)
            return (
              <label key={b.brandCode}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 16px', background: checked ? '#2A2000' : '#222', border: `1px solid ${checked ? '#FF8C00' : '#333'}`, borderRadius: '8px', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.85rem', transition: 'border-color 0.15s' }}>
                <input type='checkbox' checked={checked}
                  onChange={() => setSelectedBrandCodes(prev => {
                    const next = new Set(prev)
                    if (next.has(b.brandCode)) next.delete(b.brandCode); else next.add(b.brandCode)
                    return next
                  })}
                  style={{ accentColor: '#FF8C00', width: '15px', height: '15px', cursor: 'pointer' }} />
                <span style={{ fontWeight: 600, flex: 1 }}>{b.brandName}</span>
                <span style={{ color: '#888', fontSize: '0.78rem' }}>{b.brandCode}</span>
              </label>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={() => onConfirm(selectedBrandCodes)}
            disabled={selectedBrandCodes.size === 0}
            style={{ flex: 1, padding: '10px', background: selectedBrandCodes.size > 0 ? 'linear-gradient(135deg, #FF8C00, #FFB84D)' : '#333', border: 'none', borderRadius: '8px', color: '#fff', fontWeight: 600, fontSize: '0.85rem', cursor: selectedBrandCodes.size > 0 ? 'pointer' : 'not-allowed' }}
          >
            선택 확인 ({selectedBrandCodes.size}개)
          </button>
          <button
            onClick={() => onConfirm(new Set())}
            style={{ padding: '10px 16px', background: 'transparent', border: '1px dashed #555', borderRadius: '8px', color: '#888', cursor: 'pointer', fontSize: '0.82rem' }}
          >
            전체 검색
          </button>
        </div>
      </div>
    </div>
  )
}

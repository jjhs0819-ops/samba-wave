'use client'

import { collectorApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

interface BrandModalItem {
  name: string
  count: number
  id?: string
}

interface BrandModalParsed {
  brand: string
  keyword: string
  gf: string
}

interface LotteOnBrandModalProps {
  open: boolean
  brandModalList: BrandModalItem[]
  brandModalSelected: Set<string>
  brandModalKeyword: string
  brandModalParsed: BrandModalParsed | null
  selectedSite: string
  setBrandModalSelected: React.Dispatch<React.SetStateAction<Set<string>>>
  onClose: () => void
  onScanStart: () => void  // setBrandScanning(true) + setBrandCategories([]) + setBrandSelectedCats(new Set())
  onScanDone: (categories: { categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }[], total: number) => void
  addLog: (msg: string) => void
}

// 롯데ON / SSG / 패션플러스 브랜드 선택 모달
export default function LotteOnBrandModal({
  open,
  brandModalList,
  brandModalSelected,
  brandModalKeyword,
  brandModalParsed,
  selectedSite,
  setBrandModalSelected,
  onClose,
  onScanStart,
  onScanDone,
  addLog,
}: LotteOnBrandModalProps) {
  if (!open || brandModalList.length === 0) return null

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
          &quot;{brandModalKeyword}&quot; 검색 결과 — 복수 선택 가능
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '50vh', overflowY: 'auto' }}>
          {brandModalList.map(b => {
            const checked = brandModalSelected.has(b.name)
            return (
              <label key={b.name}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 16px', background: checked ? '#2A2000' : '#222', border: `1px solid ${checked ? '#FF8C00' : '#333'}`, borderRadius: '8px', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.85rem', transition: 'border-color 0.15s' }}>
                <input type='checkbox' checked={checked}
                  onChange={() => {
                    const next = new Set(brandModalSelected)
                    if (next.has(b.name)) next.delete(b.name); else next.add(b.name)
                    setBrandModalSelected(next)
                  }}
                  style={{ accentColor: '#FF8C00', width: '15px', height: '15px', cursor: 'pointer' }} />
                <span style={{ fontWeight: 600, flex: 1 }}>{b.name}</span>
                <span style={{ color: '#FF8C00', fontSize: '0.78rem', fontWeight: 600 }}>{fmtNum(b.count)}건</span>
              </label>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={async () => {
              if (brandModalSelected.size === 0) { showAlert('브랜드를 1개 이상 선택하세요'); return }
              onClose()
              onScanStart()
              const { brand, keyword, gf } = brandModalParsed || { brand: '', keyword: brandModalKeyword, gf: 'A' }
              const selectedBrands = Array.from(brandModalSelected)
              // 선택된 브랜드의 id 목록 및 총 상품수 계산 (SSG repBrandId 필터링용)
              const selectedBrandIds = brandModalList
                .filter(b => brandModalSelected.has(b.name) && b.id)
                .map(b => b.id as string)
              const selectedBrandTotal = brandModalList
                .filter(b => brandModalSelected.has(b.name))
                .reduce((sum, b) => sum + b.count, 0)
              const siteLabel = selectedSite === 'SSG' ? 'SSG' : selectedSite === 'FashionPlus' ? '패션플러스' : '롯데ON'
              addLog(`[카테고리스캔] ${siteLabel} "${keyword || brand}" 스캔 시작... (${fmtNum(selectedBrands.length)}개 브랜드)`)
              try {
                const res = await collectorApi.brandScan(brand, gf, keyword, selectedSite, selectedBrands, selectedBrandIds, selectedBrandTotal)
                onScanDone(res.categories, res.total)
                addLog(`[카테고리스캔] ${keyword || brand} (${fmtNum(selectedBrands.length)}개 브랜드): ${fmtNum(res.groupCount)}개 카테고리, 총 ${fmtNum(res.total)}건`)
              } catch (e) {
                addLog(`[카테고리스캔] ${siteLabel} 스캔 실패: ${e instanceof Error ? e.message : '오류'}`)
                showAlert(e instanceof Error ? e.message : '스캔 실패', 'error')
              }
            }}
            disabled={brandModalSelected.size === 0}
            style={{ flex: 1, padding: '10px', background: brandModalSelected.size === 0 ? '#333' : 'linear-gradient(135deg, #FF8C00, #FFB84D)', border: 'none', borderRadius: '8px', color: '#fff', fontWeight: 600, fontSize: '0.85rem', cursor: brandModalSelected.size === 0 ? 'not-allowed' : 'pointer' }}
          >
            카테고리 스캔 진행 ({brandModalSelected.size}개)
          </button>
          <button
            onClick={onClose}
            style={{ padding: '10px 16px', background: 'transparent', border: '1px dashed #555', borderRadius: '8px', color: '#888', cursor: 'pointer', fontSize: '0.82rem' }}
          >
            취소
          </button>
        </div>
      </div>
    </div>
  )
}

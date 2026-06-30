'use client'

import { collectorApi, categoryApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { MAPPING_MARKETS } from '../constants'
import MappingMarketRow from './MappingMarketRow'

interface MappingModalProps {
  open: boolean
  filter: SambaSearchFilter | null
  mappingData: Record<string, string>
  mappingLoading: boolean
  setMappingData: React.Dispatch<React.SetStateAction<Record<string, string>>>
  setMappingLoading: (v: boolean) => void
  onClose: () => void
  onSaved: () => void  // load + loadTree 호출
}

// 카테고리 매핑 모달
export default function MappingModal({
  open,
  filter,
  mappingData,
  mappingLoading,
  setMappingData,
  setMappingLoading,
  onClose,
  onSaved,
}: MappingModalProps) {
  if (!open || !filter) return null

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '28px 32px', minWidth: '500px', maxWidth: '700px', maxHeight: '80vh', overflowY: 'auto' }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: '#E5E5E5' }}>카테고리 매핑</h3>
        <p style={{ margin: '0 0 16px', fontSize: '0.75rem', color: '#888' }}>
          {filter.name} — 각 마켓별 카테고리를 지정하세요
        </p>

        <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
          <button
            disabled={mappingLoading}
            onClick={async () => {
              setMappingLoading(true)
              try {
                const products = await collectorApi.scrollProducts({ skip: 0, limit: 5, search_filter_id: filter.id })
                const rep = products.items[0]
                if (!rep) { showAlert('상품이 없습니다', 'error'); return }
                const res = await categoryApi.aiSuggest({
                  source_site: rep.source_site || filter.source_site,
                  source_category: [rep.category1, rep.category2, rep.category3, rep.category4].filter(Boolean).join(' > ') || rep.category || '',
                  sample_products: products.items.slice(0, 5).map(p => p.name || ''),
                  sample_tags: rep.tags?.filter((t: string) => !t.startsWith('__')) || [],
                  target_markets: MAPPING_MARKETS.map(m => m.id),
                })
                if (res) {
                  const newMapping: Record<string, string> = { ...mappingData }
                  for (const [market, cat] of Object.entries(res)) {
                    if (cat) newMapping[market] = cat as string
                  }
                  setMappingData(newMapping)
                  showAlert('AI 매핑 추천 완료', 'success')
                }
              } catch (e) { showAlert(e instanceof Error ? e.message : 'AI 매핑 실패', 'error') }
              finally { setMappingLoading(false) }
            }}
            style={{ padding: '7px 20px', fontSize: '0.82rem', borderRadius: '6px', cursor: mappingLoading ? 'not-allowed' : 'pointer', border: '1px solid rgba(255,140,0,0.5)', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600, opacity: mappingLoading ? 0.6 : 1 }}
          >{mappingLoading ? 'AI 분석중...' : 'AI 매핑'}</button>
          <button
            onClick={async () => {
              if (!await showConfirm('이 그룹의 카테고리 매핑을 모두 초기화하시겠습니까?')) return
              setMappingData({})
              try {
                await collectorApi.updateFilter(filter.id, { target_mappings: {} } as Partial<SambaSearchFilter>)
                showAlert('매핑 초기화 완료', 'success')
                onSaved()
              } catch (e) { showAlert(e instanceof Error ? e.message : '초기화 실패', 'error') }
            }}
            style={{ padding: '7px 20px', fontSize: '0.82rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(255,107,107,0.5)', background: 'rgba(255,107,107,0.1)', color: '#FF6B6B' }}
          >매핑 초기화</button>
        </div>

        {MAPPING_MARKETS.map(m => (
          <MappingMarketRow
            key={m.id}
            marketType={m.id}
            marketName={m.name}
            value={mappingData[m.id] || ''}
            onChange={val => setMappingData(prev => ({ ...prev, [m.id]: val }))}
            onClear={() => setMappingData(prev => { const n = { ...prev }; delete n[m.id]; return n })}
          />
        ))}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
          <button
            onClick={onClose}
            style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid #3D3D3D', background: 'transparent', color: '#888' }}
          >취소</button>
          <button
            onClick={async () => {
              try {
                const clean = Object.fromEntries(Object.entries(mappingData).filter(([, v]) => v))
                await collectorApi.updateFilter(filter.id, { target_mappings: clean } as Partial<SambaSearchFilter>)
                onClose()
                showAlert('매핑 저장 완료', 'success')
                onSaved()
              } catch (e) { showAlert(e instanceof Error ? e.message : '저장 실패', 'error') }
            }}
            style={{ padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px', cursor: 'pointer', border: '1px solid rgba(81,207,102,0.5)', background: 'rgba(81,207,102,0.15)', color: '#51CF66', fontWeight: 600 }}
          >
            저장 ({fmtNum(Object.values(mappingData).filter(Boolean).length)}개 마켓)
          </button>
        </div>
      </div>
    </div>
  )
}

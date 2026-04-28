'use client'

import type { Dispatch, SetStateAction } from 'react'
import {
  collectorApi,
  type SambaSearchFilter,
  type SambaPolicy,
} from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SOURCING_SEARCH_URLS } from '@/lib/samba/constants'
import { fmtDate as _fmtDate } from '@/lib/samba/utils'
import { fmtNum } from '@/lib/samba/styles'

const fmtDate = (iso: string | undefined | null) => _fmtDate(iso, '.')
const FIXED_REQUESTED_COUNT = 1000

export interface DrilldownGroupTableProps {
  filters: SambaSearchFilter[]; tree: SambaSearchFilter[]; policies: SambaPolicy[]
  drillSite: string | null; drillBrand: string | null; drillGroup: string | null; drillEntry: 'site' | 'brand' | null
  setDrillSite: Dispatch<SetStateAction<string | null>>; setDrillBrand: Dispatch<SetStateAction<string | null>>
  setDrillGroup: Dispatch<SetStateAction<string | null>>; setDrillEntry: Dispatch<SetStateAction<'site' | 'brand' | null>>
  collectFilter: string; marketRegFilter: string; tagRegFilter: string; policyRegFilter: string
  setCollectFilter: Dispatch<SetStateAction<string>>; setMarketRegFilter: Dispatch<SetStateAction<string>>
  setTagRegFilter: Dispatch<SetStateAction<string>>; setPolicyRegFilter: Dispatch<SetStateAction<string>>
  selectedIds: Set<string>; setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  setShowDuplicatesModal: Dispatch<SetStateAction<boolean>>; setShowMappingModal: Dispatch<SetStateAction<boolean>>
  setMappingFilter: Dispatch<SetStateAction<SambaSearchFilter | null>>
  setMappingData: Dispatch<SetStateAction<Record<string, string>>>
  tagPreviewLoading: boolean
  handleDeleteSelectedGroups: () => void | Promise<void>
  handleCollectGroups: () => void | Promise<void>
  handlePolicyApply: (filterId: string, policyId: string) => void | Promise<void>
  handleUpdateRequestedCount: (filterId: string, count: number) => void | Promise<void>
  handleGoToProducts: (f: SambaSearchFilter) => void
  handleBrandRefresh: () => void | Promise<void>
  handleAiTagPreview: () => void | Promise<void>
  handleClearAiTags: () => void | Promise<void>
  handleSyncRequestedCounts: () => void | Promise<void>
  parseGroupName: (name: string, site: string) => { brand: string; category: string }
  load: () => void | Promise<void>; loadTree: () => void | Promise<void>
}

export default function DrilldownGroupTable(props: DrilldownGroupTableProps) {
  const {
    filters, tree, policies,
    drillSite, drillBrand, drillGroup, drillEntry,
    setDrillSite, setDrillBrand, setDrillGroup, setDrillEntry,
    collectFilter, marketRegFilter, tagRegFilter, policyRegFilter,
    setCollectFilter, setMarketRegFilter, setTagRegFilter, setPolicyRegFilter,
    selectedIds, setSelectedIds,
    setShowDuplicatesModal, setShowMappingModal, setMappingFilter, setMappingData,
    tagPreviewLoading,
    handleDeleteSelectedGroups, handleCollectGroups,
    handlePolicyApply, handleUpdateRequestedCount, handleGoToProducts,
    handleBrandRefresh, handleAiTagPreview, handleClearAiTags, handleSyncRequestedCounts,
    parseGroupName, load, loadTree,
  } = props

  return (
    <>
      <div style={{ marginTop: '1rem' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: '0.75rem', flexWrap: 'wrap', gap: '8px',
        }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>검색그룹 목록</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <select value={collectFilter} onChange={e => setCollectFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: collectFilter ? '#F59E0B' : '#888', cursor: 'pointer' }}>
              <option value="">상품수집</option>
              <option value="collected">수집</option>
              <option value="uncollected">미수집</option>
            </select>
            <select value={marketRegFilter} onChange={e => setMarketRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: marketRegFilter ? '#4C9AFF' : '#888', cursor: 'pointer' }}>
              <option value="">마켓등록</option>
              <option value="registered">전체등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={tagRegFilter} onChange={e => setTagRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: tagRegFilter ? '#51CF66' : '#888', cursor: 'pointer' }}>
              <option value="">태그등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={policyRegFilter} onChange={e => setPolicyRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: policyRegFilter ? '#FF8C00' : '#888', cursor: 'pointer' }}>
              <option value="">정책등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <button
              onClick={() => setShowDuplicatesModal(true)}
              style={{
                background: 'rgba(255,165,0,0.1)', border: '1px solid rgba(255,165,0,0.3)',
                color: '#FFA500', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              중복 상품
            </button>
            <button
              onClick={handleDeleteSelectedGroups}
              style={{
                background: 'rgba(255,100,100,0.1)', border: '1px solid rgba(255,100,100,0.3)',
                color: '#FF6B6B', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              그룹 삭제
            </button>
            <button
              onClick={handleCollectGroups}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              상품수집
            </button>
            <button onClick={handleBrandRefresh} style={{ display: 'none' }}>추가수집</button>
            <button
              onClick={handleSyncRequestedCounts}
              title="선택된(없으면 전체) 그룹의 요청수를 현재 수집수로 일괄 맞춥니다"
              style={{
                background: 'rgba(100,200,255,0.1)', border: '1px solid rgba(100,200,255,0.3)',
                color: '#64C8FF', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              수집동기화
            </button>
            <button
              disabled={tagPreviewLoading}
              onClick={handleAiTagPreview}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem',
                cursor: tagPreviewLoading ? 'not-allowed' : 'pointer', opacity: tagPreviewLoading ? 0.6 : 1,
              }}
            >
              {tagPreviewLoading ? '태그 생성중...' : 'AI태그'}
            </button>
            <button onClick={handleClearAiTags} style={{
              background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)',
              color: '#FF6B6B', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem',
              cursor: 'pointer',
            }}>태그삭제</button>
          </div>
        </div>

        <div style={{
          marginBottom: '0.75rem', padding: '0.5rem 0.875rem', borderRadius: '8px',
          background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.2)',
          fontSize: '0.8rem', color: '#888',
        }}>
          ※ 정책 우선순위: <span style={{ color: '#FF8C00' }}>[상품별 개별정책]</span> → <span style={{ color: '#FF8C00' }}>[카테고리 정책]</span> 순으로 적용됩니다
          <span style={{ float: 'right', color: '#E5E5E5', fontWeight: 600 }}>
            수집 <span style={{ color: '#FF8C00' }}>{fmtNum(filters.reduce((s, f) => s + ((f as unknown as Record<string, number>).collected_count ?? 0), 0))}</span>
            <span style={{ color: '#555' }}> / </span>
            요청 <span style={{ color: '#FFB84D' }}>{fmtNum(filters.filter(f => !f.is_folder).reduce((s, f) => s + (f.requested_count ?? 0), 0))}</span>
          </span>
        </div>

        {(() => {
          const getAllLeaves = (node: SambaSearchFilter | undefined): SambaSearchFilter[] => {
            if (!node) return []
            const result: SambaSearchFilter[] = []
            const walk = (n: SambaSearchFilter) => {
              if (!n.is_folder) result.push(n)
              ;(n.children || []).forEach(walk)
            }
            ;(node.children || []).forEach(walk)
            return result
          }
          // 전체 사이트별 리프 + 브랜드/카테고리 파싱 (크로스 필터용)
          const allLeafInfosRaw = tree.flatMap(s =>
            getAllLeaves(s).map(l => {
              const parsed = parseGroupName(l.name, s.source_site || '')
              return { ...l, _siteId: s.id, _siteSite: s.source_site || '', _brand: parsed.brand, _category: parsed.category }
            })
          )
          // 상품수집 + 태그등록 + 정책등록 드롭박스 필터 적용
          let allLeafInfos = [...allLeafInfosRaw]
          if (collectFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const cnt = (l as unknown as Record<string, number>).collected_count ?? 0
              return collectFilter === 'collected' ? cnt > 0 : cnt === 0
            })
          }
          if (tagRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const r = l as unknown as Record<string, number>
              const cnt = r.ai_tagged_count ?? 0
              const total = r.collected_count ?? 0
              if (tagRegFilter === 'registered') return cnt > 0 && cnt >= total
              if (tagRegFilter === 'partial') return cnt > 0 && cnt < total
              if (tagRegFilter === 'unregistered') return cnt === 0
              return true
            })
          }
          if (policyRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const hasPolicy = !!(l as unknown as Record<string, string>).applied_policy_id
              if (policyRegFilter === 'registered') return hasPolicy
              if (policyRegFilter === 'unregistered') return !hasPolicy
              return true
            })
          }
          if (marketRegFilter) {
            allLeafInfos = allLeafInfos.filter(l => {
              const r = l as unknown as Record<string, number>
              const cnt = r.market_registered_count ?? 0
              const total = r.collected_count ?? 0
              if (marketRegFilter === 'registered') return cnt > 0 && cnt >= total
              if (marketRegFilter === 'partial') return cnt > 0 && cnt < total
              if (marketRegFilter === 'unregistered') return cnt === 0
              return true
            })
          }
          // 크로스 필터: 사이트 목록 (선택된 브랜드 기준 필터)
          const baseSites = collectFilter
            ? tree.filter(s => allLeafInfos.some(l => l._siteId === s.id))
            : tree
          const filteredSites = drillBrand
            ? baseSites.filter(s => allLeafInfos.some(l => l._siteId === s.id && l._brand === drillBrand))
            : baseSites
          // 크로스 필터: 브랜드 목록 (선택된 사이트 기준 필터)
          const brandLeaves = drillSite
            ? allLeafInfos.filter(l => l._siteId === drillSite)
            : allLeafInfos
          const brandMap = new Map<string, { count: number; collected: number }>()
          brandLeaves.forEach(l => {
            const prev = brandMap.get(l._brand) || { count: 0, collected: 0 }
            brandMap.set(l._brand, {
              count: prev.count + 1,
              collected: prev.collected + ((l as unknown as Record<string, number>).collected_count ?? 0)
            })
          })
          const brands = Array.from(brandMap.entries()).sort((a, b) => a[0].localeCompare(b[0], 'ko'))
          // 카테고리 그룹 (사이트+브랜드 교차 필터)
          let catLeaves = allLeafInfos
          if (drillSite) catLeaves = catLeaves.filter(l => l._siteId === drillSite)
          if (drillBrand) catLeaves = catLeaves.filter(l => l._brand === drillBrand)
          const catGroups = (drillSite && drillBrand) ? catLeaves.sort((a, b) => a._category.localeCompare(b._category, 'ko')) : []
          // 선택된 그룹 상세
          const selectedFilter = drillGroup ? filters.find(fl => fl.id === drillGroup) : null
          const selectedCount = selectedFilter ? ((selectedFilter as unknown as Record<string, number>).collected_count ?? 0) : 0

          const colW = ['12%', '13%', '22%', '15%', '10%', '8%', '6%', '11%', '3%']
          const colBase = { borderRight: '1px solid #2D2D2D', maxHeight: '320px', overflowY: 'auto' as const, boxSizing: 'border-box' as const, textAlign: 'left' as const }
          const colStyle = (i: number) => ({ ...colBase, width: colW[i], flexShrink: 0 })
          const detColStyle = (i: number) => ({ ...colBase, width: colW[i], flexShrink: 0, padding: '0.5rem 0.5rem' })
          const itemSt = (sel: boolean) => ({
            padding: '0.5rem 0.75rem', fontSize: '0.8125rem',
            color: sel ? '#FF8C00' : '#C5C5C5', cursor: 'pointer' as const,
            background: sel ? 'rgba(255,140,0,0.08)' : 'transparent',
            transition: 'background 0.15s',
            display: 'flex' as const, alignItems: 'center' as const, gap: '4px',
          })

          return (
            <div style={{
              background: 'rgba(30,30,30,0.5)', border: '1px solid #2D2D2D',
              borderRadius: '8px', overflow: 'hidden', marginBottom: '1rem',
            }}>
              {/* 헤더 */}
              <div style={{ display: 'flex', borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
                {['사이트', '브랜드', '카테고리', '링크', '정책', '수집', '요청', '생성일/최근수집', '매핑'].map((h, i) => (
                  <div key={h} style={{
                    width: colW[i], flexShrink: 0, boxSizing: 'border-box' as const,
                    padding: '0.5rem 0.5rem', textAlign: 'center' as const,
                    fontSize: '0.72rem', fontWeight: 600,
                    color: (i === 0 && (drillEntry === 'site' || drillSite)) || (i === 1 && (drillEntry === 'brand' || drillBrand)) || (i === 2 && drillGroup) ? '#FF8C00' : '#888',
                    borderRight: i < 8 ? '1px solid #2D2D2D' : 'none',
                    cursor: i < 3 ? 'pointer' : 'default',
                  }}
                  onClick={() => {
                    if (i === 0) { setDrillEntry('site'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 1) { setDrillEntry('brand'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 2) { setDrillGroup(null) }
                  }}
                  >{h}</div>
                ))}
              </div>

              <div style={{ display: 'flex' }}>
                <div style={colStyle(0)}>
                  {(drillEntry === 'site' || drillBrand) ? (
                    filteredSites.length === 0 ? (
                      <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>그룹 없음</div>
                    ) : filteredSites.map(s => (
                      <div key={s.id} style={itemSt(drillSite === s.id)}
                        onClick={() => { setDrillSite(drillSite === s.id ? null : s.id); setDrillGroup(null) }}
                        onMouseEnter={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'transparent' }}
                      >
                        {s.source_site || s.name}
                        <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: '#FF8C00', fontWeight: 600 }}>
                          {(() => {
                            const leaves = allLeafInfos.filter(l => l._siteId === s.id)
                            const collected = leaves.reduce((sum, l) => sum + ((l as unknown as Record<string, number>).collected_count ?? 0), 0)
                            return `${leaves.length}(${fmtNum(collected)})`
                          })()}
                        </span>
                      </div>
                    ))
                  ) : null}
                </div>
                <div style={colStyle(1)}>
                  {(drillEntry === 'brand' || drillSite) ? (
                    brands.length > 0 ? brands.map(([brand, info]) => (
                      <div key={brand} style={itemSt(drillBrand === brand)}
                        onClick={() => {
                          const toggling = drillBrand === brand
                          setDrillBrand(toggling ? null : brand)
                          setDrillGroup(null)
                          if (!toggling) {
                            // 브랜드 선택 시 해당 브랜드의 모든 카테고리 그룹 자동 선택
                            let leaves = allLeafInfos
                            if (drillSite) leaves = leaves.filter(l => l._siteId === drillSite)
                            leaves = leaves.filter(l => l._brand === brand)
                            setSelectedIds(new Set(leaves.map(l => l.id)))
                          } else {
                            setSelectedIds(new Set())
                          }
                        }}
                        onMouseEnter={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'transparent' }}
                      >
                        {brand}
                        <span style={{ marginLeft: 'auto', fontSize: '0.7rem', color: '#FF8C00', fontWeight: 600 }}>{fmtNum(info.count)}({fmtNum(info.collected)})</span>
                      </div>
                    )) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>브랜드 없음</div>
                  ) : null}
                </div>
                <div style={colStyle(2)}>
                  {(drillSite || drillBrand) ? (catGroups.length > 0 ? (<>
                    {catGroups.map(g => (
                      <div key={g.id} style={itemSt(drillGroup === g.id || selectedIds.has(g.id))}
                        onClick={(e) => {
                          // Ctrl(Win) / Meta(Mac) 누른 상태: 다중 선택 토글
                          if (e.ctrlKey || e.metaKey) {
                            setSelectedIds(prev => {
                              const next = new Set(prev)
                              if (next.has(g.id)) next.delete(g.id)
                              else next.add(g.id)
                              return next
                            })
                            setDrillGroup(g.id)
                            return
                          }
                          // 일반 클릭: 단일 선택
                          setDrillGroup(g.id)
                          setSelectedIds(new Set([g.id]))
                        }}
                        onMouseEnter={e => { if (drillGroup !== g.id && !selectedIds.has(g.id)) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillGroup !== g.id && !selectedIds.has(g.id)) e.currentTarget.style.background = 'transparent' }}
                      >
                        {g._category || g.name}
                        {(g as unknown as Record<string, number>).ai_tagged_count > 0 && (
                          <span style={{ fontSize: '0.55rem', padding: '0 3px', borderRadius: '3px', background: 'rgba(81,207,102,0.15)', color: '#51CF66', border: '1px solid rgba(81,207,102,0.3)' }}>T</span>
                        )}
                        <span style={{ marginLeft: 'auto', fontSize: '0.74rem', color: '#FF8C00', fontWeight: 600 }}>{fmtNum(g.collected_count ?? 0)}</span>
                      </div>
                    ))}
                  </>) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>항목 없음</div>
                  ) : null}
                </div>
                <div style={detColStyle(3)}>
                  {selectedFilter ? (() => {
                    // 소싱 URL 결정: category_filter(저장된 URL) > 사이트별 검색URL 생성
                    const storedUrl = (selectedFilter as unknown as Record<string, string>).category_filter || ''
                    const kw = selectedFilter.keyword || ''
                    const site = selectedFilter.source_site || ''
                    // keyword가 이미 URL이면 그대로 사용
                    const kwIsUrl = kw.startsWith('http://') || kw.startsWith('https://')
                    // storedUrl은 실제 URL인 경우만 사용 (카테고리 코드는 무시)
                    const validStoredUrl = storedUrl.startsWith('http') ? storedUrl : ''
                    const linkUrl = validStoredUrl || (kwIsUrl ? kw : (SOURCING_SEARCH_URLS[site] ? SOURCING_SEARCH_URLS[site] + encodeURIComponent(kw) : ''))
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {linkUrl ? (
                          <a href={linkUrl} target="_blank" rel="noopener noreferrer" style={{
                            color: '#7EB5D0', fontSize: '0.7rem', wordBreak: 'break-all',
                            textDecoration: 'underline', textUnderlineOffset: '2px', flex: 1,
                          }}>{(() => { try { return decodeURIComponent(linkUrl.replace(/https?:\/\/[^/]+/, '')).slice(0, 40) } catch { return linkUrl.replace(/https?:\/\/[^/]+/, '').slice(0, 40) } })()}...</a>
                        ) : <span style={{ color: '#555', fontSize: '0.75rem', flex: 1 }}>-</span>}
                        <button
                          onClick={async () => {
                            if (!await showConfirm(`"${selectedFilter.name}" 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`)) return
                            try {
                              const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: selectedFilter.id })
                              const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
                              if (registered.length > 0) {
                                showAlert(`마켓등록 상품이 ${fmtNum(registered.length)}건 있어서 삭제할 수 없습니다`, 'error')
                                return
                              }
                              const pIds = res.items.map(p => p.id)
                              if (pIds.length > 0) await collectorApi.bulkDeleteProducts(pIds)
                            } catch { /* 상품 없으면 무시 */ }
                            await collectorApi.deleteFilter(selectedFilter.id)
                            setDrillGroup(null)
                            load(); loadTree()
                          }}
                          style={{
                            background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)',
                            color: '#FF6B6B', fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px',
                            cursor: 'pointer', flexShrink: 0,
                          }}
                        >삭제</button>
                      </div>
                    )
                  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                <div style={detColStyle(4)}>
                  {selectedFilter ? (
                    <select
                      key={selectedFilter.id}
                      defaultValue={(selectedFilter as unknown as Record<string, string>).applied_policy_id || ''}
                      onChange={e => handlePolicyApply(selectedFilter.id, e.target.value)}
                      style={{
                        width: '100%', padding: '0.2rem 0.2rem', fontSize: '0.72rem',
                        background: 'rgba(22,22,22,0.95)', border: '1px solid #353535',
                        color: '#C5C5C5', borderRadius: '4px',
                      }}
                    >
                      <option value="">정책 선택</option>
                      {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : (drillBrand && catGroups.length > 0) ? (
                    <select onChange={async (e) => {
                      const policyId = e.target.value
                      if (!policyId) return
                      const policyName = policies.find(p => p.id === policyId)?.name || ''
                      if (!await showConfirm(`${drillBrand} 브랜드의 ${fmtNum(catGroups.length)}개 그룹에 "${policyName}" 정책을 일괄 적용하시겠습니까?`)) { e.target.value = ''; return }
                      try {
                        const res = await collectorApi.bulkApplyPolicy(catGroups.map(g => g.id), policyId)
                        showAlert(`${fmtNum(res.applied)}/${fmtNum(catGroups.length)}개 그룹에 정책 적용 완료`, 'success')
                      } catch (err) {
                        showAlert(`정책 적용 실패: ${err instanceof Error ? err.message : '오류'}`, 'error')
                      }
                      e.target.value = ''
                      load(); loadTree()
                    }} style={{
                      width: '100%', padding: '0.2rem 0.2rem', fontSize: '0.68rem',
                      background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.3)',
                      color: '#FF8C00', borderRadius: '4px', cursor: 'pointer', fontWeight: 600,
                    }}>
                      <option value="">일괄적용 ({fmtNum(catGroups.length)})</option>
                      {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                {/* 6. 수집 */}
                <div style={detColStyle(5)}>
                  {selectedFilter ? (
                    <span onClick={() => handleGoToProducts(selectedFilter)} style={{
                      color: selectedCount > 0 ? '#FF8C00' : '#555', fontWeight: 600, fontSize: '0.82rem',
                      cursor: selectedCount > 0 ? 'pointer' : 'default',
                      textDecoration: selectedCount > 0 ? 'underline' : 'none',
                    }}>{fmtNum(selectedCount)}</span>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 8. 요청 */}
                <div style={detColStyle(6)}>
                  {selectedFilter ? (
                    <input
                      key={selectedFilter.id}
                      type="text" inputMode="numeric" pattern="[0-9]*"
                      defaultValue={selectedFilter.requested_count ?? FIXED_REQUESTED_COUNT}
                      onBlur={e => {
                        const v = parseInt(e.target.value, 10)
                        if (!isNaN(v) && v > 0) handleUpdateRequestedCount(selectedFilter.id, v)
                      }}
                      style={{
                        width: '50px', textAlign: 'center', background: 'transparent',
                        border: '1px solid #3D3D3D', color: '#4C9AFF', fontSize: '0.78rem',
                        fontWeight: 600, padding: '0.1rem 0.2rem', borderRadius: '4px', outline: 'none',
                      }}
                      onFocus={e => { e.currentTarget.style.borderColor = '#4C9AFF' }}
                      onBlurCapture={e => { e.currentTarget.style.borderColor = '#3D3D3D' }}
                    />
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 9. 생성일/최근수집 */}
                <div style={detColStyle(7)}>
                  {selectedFilter ? (
                    <div style={{ fontSize: '0.68rem', color: '#888' }}>
                      {fmtDate(selectedFilter.created_at)}<br />{fmtDate(selectedFilter.last_collected_at)}
                    </div>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 10. 매핑 */}
                <div style={{ ...detColStyle(8), borderRight: 'none' }}>
                  {selectedFilter ? (() => {
                    const tm = (selectedFilter as SambaSearchFilter).target_mappings || {}
                    const mappedCount = Object.keys(tm).length
                    return (
                      <button
                        onClick={() => {
                          setMappingFilter(selectedFilter as SambaSearchFilter)
                          setMappingData({ ...tm })
                          setShowMappingModal(true)
                        }}
                        style={{
                          padding: '0.2rem 0.5rem', fontSize: '0.7rem', borderRadius: '4px', cursor: 'pointer',
                          background: mappedCount > 0 ? 'rgba(81,207,102,0.1)' : 'rgba(255,140,0,0.1)',
                          border: `1px solid ${mappedCount > 0 ? 'rgba(81,207,102,0.3)' : 'rgba(255,140,0,0.3)'}`,
                          color: mappedCount > 0 ? '#51CF66' : '#FF8C00',
                        }}
                      >{mappedCount > 0 ? fmtNum(mappedCount) : '+'}</button>
                    )
                  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
              </div>
            </div>
          )
        })()}
      </div>
    </>
  )
}

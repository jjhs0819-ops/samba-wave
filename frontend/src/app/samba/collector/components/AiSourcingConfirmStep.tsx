'use client'

import { Dispatch, SetStateAction } from 'react'
import { aiSourcingApi, type AISourcingResult } from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SITE_COLORS } from '@/lib/samba/constants'
import { fmtNum } from '@/lib/samba/styles'
import { SITES } from '../constants'

interface Props {
  aiResult: AISourcingResult
  aiSelectedCombos: Set<number>
  aiExcludedBrands: Set<string>
  aiMinCount: number
  aiCreating: boolean
  aiSourceSite: string
  setAiSelectedCombos: Dispatch<SetStateAction<Set<number>>>
  setAiExcludedBrands: Dispatch<SetStateAction<Set<string>>>
  setAiSourcingStep: (step: 'config' | 'analyzing' | 'confirm') => void
  setAiResult: (r: AISourcingResult | null) => void
  setAiCreating: (v: boolean) => void
  onClose: () => void
  onCreated: () => void
}

export default function AiSourcingConfirmStep(props: Props) {
  const {
    aiResult, aiSelectedCombos, aiExcludedBrands, aiMinCount, aiCreating, aiSourceSite,
    setAiSelectedCombos, setAiExcludedBrands, setAiSourcingStep, setAiResult, setAiCreating,
    onClose, onCreated,
  } = props

  return (
    <div style={{ padding: '20px' }}>
      {/* 요약 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '16px',
      }}>
        {[
          { label: '발견 브랜드', value: aiResult.summary.total_brands_found, color: '#4C9AFF' },
          { label: '발견 키워드쌍', value: aiResult.summary.total_pairs || 0, color: '#E5A0FF' },
          { label: 'IP안전', value: aiResult.summary.safe_brands, color: '#51CF66' },
          { label: '생성 그룹', value: aiResult.summary.total_combinations, color: '#FFB84D' },
          { label: '예상 상품', value: fmtNum(aiResult.summary.total_estimated_products), color: '#A29BFE' },
        ].map(s => (
          <div key={s.label} style={{
            background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px',
            padding: '10px', textAlign: 'center',
          }}>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: s.color }}>{s.value}</div>
            <div style={{ fontSize: '0.72rem', color: '#888' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* 선택된 소싱처 표시 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px',
        background: 'rgba(255,140,0,0.06)', border: '1px solid rgba(255,140,0,0.2)',
        borderRadius: '8px', padding: '8px 14px',
      }}>
        <span style={{ fontSize: '0.78rem', color: '#FF8C00', fontWeight: 600 }}>수집 소싱처: {SITES.find(s => s.id === aiSourceSite)?.label || aiSourceSite}</span>
        <span style={{ fontSize: '0.7rem', color: '#666' }}>그룹명: {aiSourceSite}_브랜드_키워드</span>
      </div>

      {/* 근거 데이터 */}
      {(() => {
        const sourceMap: Record<string, { brands: string[]; keywords: string[] }> = {}
        aiResult.brands.forEach(b => {
          const src = b.source || '기타'
          if (!sourceMap[src]) sourceMap[src] = { brands: [], keywords: [] }
          if (!sourceMap[src].brands.includes(b.brand)) sourceMap[src].brands.push(b.brand)
          ;[...(b.keywords || []), ...(b.categories || [])].forEach(kw => {
            if (kw && !sourceMap[src].keywords.includes(kw)) sourceMap[src].keywords.push(kw)
          })
        })
        const entries = Object.entries(sourceMap)
        if (entries.length === 0) return null
        return (
          <div style={{ marginBottom: '14px', padding: '12px 14px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', maxHeight: '300px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '8px', fontWeight: 600 }}>분석 근거 <span style={{ color: '#555', fontWeight: 400 }}>— 클릭하여 제외</span></div>
            {entries.map(([src, data]) => (
              <div key={src} style={{ marginBottom: '6px', fontSize: '0.78rem', lineHeight: 1.8, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '2px' }}>
                <span style={{ color: '#FFB84D', fontWeight: 600 }}>{src}</span>
                <span style={{ color: '#666' }}> : </span>
                {data.brands.map(brand => {
                  const excluded = aiExcludedBrands.has(brand)
                  return (
                    <span key={brand}
                      onClick={() => {
                        const next = new Set(aiExcludedBrands)
                        if (excluded) {
                          next.delete(brand)
                          const addIdxs = new Set(aiSelectedCombos)
                          aiResult.combinations.forEach((c, i) => {
                            if (c.brand === brand) addIdxs.add(i)
                          })
                          setAiSelectedCombos(addIdxs)
                        } else {
                          next.add(brand)
                          const removeIdxs = new Set(aiSelectedCombos)
                          aiResult.combinations.forEach((c, i) => {
                            if (c.brand === brand) removeIdxs.delete(i)
                          })
                          setAiSelectedCombos(removeIdxs)
                        }
                        setAiExcludedBrands(next)
                      }}
                      style={{
                        cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                        background: excluded ? 'rgba(255,107,107,0.1)' : 'rgba(255,255,255,0.05)',
                        color: excluded ? '#FF6B6B' : '#E5E5E5',
                        textDecoration: excluded ? 'line-through' : 'none',
                        opacity: excluded ? 0.5 : 1, transition: 'all 0.15s',
                      }}
                    >{brand}</span>
                  )
                })}
                {data.keywords.length > 0 && (
                  <>
                    <span style={{ color: '#666' }}> / </span>
                    {data.keywords.map(kw => {
                      const kwExcluded = aiExcludedBrands.has(`__kw__${kw}`)
                      return (
                        <span key={kw}
                          onClick={() => {
                            const kwKey = `__kw__${kw}`
                            const next = new Set(aiExcludedBrands)
                            if (kwExcluded) {
                              next.delete(kwKey)
                              const addIdxs = new Set(aiSelectedCombos)
                              aiResult.combinations.forEach((c, i) => {
                                if ((c.keyword || c.category) === kw) addIdxs.add(i)
                              })
                              setAiSelectedCombos(addIdxs)
                            } else {
                              next.add(kwKey)
                              const removeIdxs = new Set(aiSelectedCombos)
                              aiResult.combinations.forEach((c, i) => {
                                if ((c.keyword || c.category) === kw) removeIdxs.delete(i)
                              })
                              setAiSelectedCombos(removeIdxs)
                            }
                            setAiExcludedBrands(next)
                          }}
                          style={{
                            cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                            background: kwExcluded ? 'rgba(255,107,107,0.1)' : 'rgba(76,154,255,0.08)',
                            color: kwExcluded ? '#FF6B6B' : '#4C9AFF',
                            textDecoration: kwExcluded ? 'line-through' : 'none',
                            opacity: kwExcluded ? 0.5 : 1, transition: 'all 0.15s',
                          }}
                        >{kw}</span>
                      )
                    })}
                  </>
                )}
              </div>
            ))}
          </div>
        )
      })()}

      {/* IP위험 브랜드 */}
      {(() => {
        const unsafeBrands = aiResult.brands.filter(b => !b.is_safe)
        if (unsafeBrands.length === 0) return null
        return (
          <div style={{ marginBottom: '14px', padding: '12px 14px', background: 'rgba(255,107,107,0.04)', border: '1px solid rgba(255,107,107,0.15)', borderRadius: '8px' }}>
            <div style={{ fontSize: '0.75rem', color: '#FF6B6B', marginBottom: '8px', fontWeight: 600 }}>
              IP위험 브랜드 ({fmtNum(unsafeBrands.length)}개)
              {aiExcludedBrands.size > 0 && <span style={{ color: '#888', fontWeight: 400 }}> — {fmtNum(aiExcludedBrands.size)}개 제외</span>}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {unsafeBrands.map(b => {
                const excluded = aiExcludedBrands.has(b.brand)
                return (
                  <span key={b.brand}
                    onClick={() => {
                      const next = new Set(aiExcludedBrands)
                      if (excluded) {
                        next.delete(b.brand)
                        const addIdxs = new Set(aiSelectedCombos)
                        aiResult.combinations.forEach((c, i) => {
                          if (c.brand === b.brand) addIdxs.add(i)
                        })
                        setAiSelectedCombos(addIdxs)
                      } else {
                        next.add(b.brand)
                        const removeIdxs = new Set(aiSelectedCombos)
                        aiResult.combinations.forEach((c, i) => {
                          if (c.brand === b.brand) removeIdxs.delete(i)
                        })
                        setAiSelectedCombos(removeIdxs)
                      }
                      setAiExcludedBrands(next)
                    }}
                    title={b.safety_reason}
                    style={{
                      fontSize: '0.75rem', padding: '3px 10px', borderRadius: '12px', cursor: 'pointer',
                      background: excluded ? 'rgba(255,107,107,0.12)' : 'rgba(255,107,107,0.06)',
                      border: `1px solid rgba(255,107,107,${excluded ? '0.4' : '0.2'})`,
                      color: '#FF6B6B',
                      textDecoration: 'line-through',
                      opacity: excluded ? 0.5 : 1,
                      transition: 'all 0.15s',
                    }}
                  >
                    {b.brand}
                  </span>
                )
              })}
            </div>
            <div style={{ fontSize: '0.68rem', color: '#666', marginTop: '6px' }}>
              취소선 = IP위험 · 클릭하여 제외 (흐리게 처리됨)
            </div>
          </div>
        )
      })()}

      {/* 조합 테이블 */}
      <div style={{ maxHeight: '350px', overflowY: 'auto', marginBottom: '12px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #2D2D2D', position: 'sticky', top: 0, background: '#1A1A1A' }}>
              <th style={{ padding: '8px 6px', textAlign: 'left', width: '36px' }}>
                <input type='checkbox'
                  checked={(() => {
                    const selectable = aiResult.combinations.filter(c => !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                    const selectedSelectable = selectable.filter((c) => aiSelectedCombos.has(aiResult.combinations.indexOf(c)))
                    return selectable.length > 0 && selectedSelectable.length === selectable.length
                  })()}
                  onChange={e => {
                    if (e.target.checked) {
                      const all = new Set<number>()
                      aiResult.combinations.forEach((c, i) => {
                        if (!aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount) all.add(i)
                      })
                      setAiSelectedCombos(all)
                    } else {
                      setAiSelectedCombos(new Set())
                    }
                  }}
                  style={{ accentColor: '#FF8C00' }}
                />
              </th>
              <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>소싱처</th>
              <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>브랜드</th>
              <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>키워드</th>
              <th style={{ padding: '8px 6px', textAlign: 'right', color: '#888' }}>예상상품수</th>
              <th style={{ padding: '8px 6px', textAlign: 'center', color: '#888' }}>
                <span>IP안전</span>
                {aiResult.combinations.some(c => !c.is_safe && aiSelectedCombos.has(aiResult.combinations.indexOf(c))) && (
                  <button
                    onClick={() => {
                      const next = new Set(aiSelectedCombos)
                      aiResult.combinations.forEach((c, i) => {
                        if (!c.is_safe) next.delete(i)
                      })
                      setAiSelectedCombos(next)
                    }}
                    style={{
                      marginLeft: '4px', fontSize: '0.65rem', padding: '1px 6px', borderRadius: '3px',
                      background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                      color: '#FF6B6B', cursor: 'pointer',
                    }}
                  >위험 해제</button>
                )}
              </th>
            </tr>
          </thead>
          <tbody>
            {aiResult.combinations.map((combo, idx) => {
              const isExcluded = aiExcludedBrands.has(combo.brand) || aiExcludedBrands.has(`__kw__${combo.keyword || combo.category}`)
              if (combo.estimated_count < aiMinCount) return null
              return (
                <tr key={idx} style={{
                  borderBottom: '1px solid #1D1D1D',
                  background: isExcluded ? 'rgba(255,107,107,0.04)' : aiSelectedCombos.has(idx) ? 'rgba(108,92,231,0.06)' : 'transparent',
                  opacity: isExcluded ? 0.4 : 1,
                }}>
                  <td style={{ padding: '6px' }}>
                    <input type='checkbox'
                      checked={aiSelectedCombos.has(idx)}
                      disabled={isExcluded}
                      onChange={e => {
                        const next = new Set(aiSelectedCombos)
                        e.target.checked ? next.add(idx) : next.delete(idx)
                        setAiSelectedCombos(next)
                      }}
                      style={{ accentColor: '#FF8C00' }}
                    />
                  </td>
                  <td style={{ padding: '6px', color: SITE_COLORS[combo.source_site] || '#888' }}>
                    {combo.source_site}
                  </td>
                  <td style={{ padding: '6px', color: !combo.is_safe ? '#FF6B6B' : isExcluded ? '#888' : '#E5E5E5', fontWeight: 500, textDecoration: !combo.is_safe ? 'line-through' : 'none' }}>{combo.brand}</td>
                  <td style={{ padding: '6px', color: '#C5C5C5' }}>{combo.keyword || combo.category}</td>
                  <td style={{ padding: '6px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                    {fmtNum(combo.estimated_count)}
                  </td>
                  <td style={{ padding: '6px', textAlign: 'center' }}>
                    {combo.is_safe
                      ? <span style={{ color: '#51CF66', fontSize: '0.85rem' }}>안전</span>
                      : <span style={{ color: '#FF6B6B', fontSize: '0.85rem' }}>위험</span>
                    }
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 선택 요약 + 버튼 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.82rem', color: '#888' }}>
          {fmtNum(aiResult.combinations.filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`)).length)}개 선택 / 예상{' '}
          {aiResult.combinations
            .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`))
            .reduce((s, c) => s + c.estimated_count, 0)
            .toLocaleString()}개 상품
        </span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={() => {
            setAiSourcingStep('config')
            setAiResult(null)
          }} style={{
            padding: '8px 16px', borderRadius: '6px',
            background: 'transparent', border: '1px solid #3D3D3D',
            color: '#888', cursor: 'pointer',
          }}>다시 설정</button>
          <button
            onClick={async () => {
              const selected = aiResult.combinations
                .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                .map(c => ({ ...c, source_site: aiSourceSite }))
              if (selected.length === 0) return showAlert('조합을 선택해주세요', 'error')
              const totalEst = selected.reduce((s, c) => s + c.estimated_count, 0)
              const site = SITES.find(s => s.id === aiSourceSite)
              const ok = await showConfirm(
                `${fmtNum(selected.length)}개 검색그룹을 생성하시겠습니까?\n소싱처: ${site?.label || aiSourceSite}\n예상 상품수: ${fmtNum(totalEst)}개`
              )
              if (!ok) return
              setAiCreating(true)
              try {
                const res = await aiSourcingApi.createGroups(selected)
                showAlert(`${fmtNum(res.created)}개 검색그룹 생성 완료`, 'success')
                onClose()
                onCreated()
              } catch (err) {
                showAlert(`그룹 생성 실패: ${err instanceof Error ? err.message : '오류'}`, 'error')
              }
              setAiCreating(false)
            }}
            disabled={aiCreating || aiSelectedCombos.size === 0}
            style={{
              padding: '8px 20px', borderRadius: '6px',
              background: aiCreating ? 'rgba(108,92,231,0.1)' : 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
              color: '#fff', fontWeight: 700, fontSize: '0.85rem',
              border: 'none', cursor: aiCreating ? 'not-allowed' : 'pointer',
              opacity: aiSelectedCombos.size === 0 ? 0.5 : 1,
            }}
          >
            {aiCreating ? '생성중...' : `${fmtNum(aiSelectedCombos.size)}개 그룹 생성`}
          </button>
        </div>
      </div>
    </div>
  )
}

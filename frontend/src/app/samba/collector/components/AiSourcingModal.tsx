'use client'

import {
  aiSourcingApi,
  type AISourcingResult,
  type AISourcingCombination,
} from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { SITE_COLORS } from '@/lib/samba/constants'
import { fmtNum } from '@/lib/samba/styles'
import { SITES } from '../constants'

interface AiSourcingModalProps {
  open: boolean
  aiSourcingStep: 'config' | 'analyzing' | 'confirm'
  aiMonth: number
  aiMainCategory: string
  aiExcelFile: File | null
  aiTargetCount: number
  aiAnalyzing: boolean
  aiLogs: string[]
  aiResult: AISourcingResult | null
  aiSelectedCombos: Set<number>
  aiExcludedBrands: Set<string>
  aiExcludedKeywords: Set<string>
  aiMinCount: number
  aiCreating: boolean
  aiSourceSite: string
  setAiSourcingStep: (step: 'config' | 'analyzing' | 'confirm') => void
  setAiMonth: (v: number) => void
  setAiMainCategory: (v: string) => void
  setAiExcelFile: (f: File | null) => void
  setAiTargetCount: (v: number) => void
  setAiAnalyzing: (v: boolean) => void
  setAiLogs: React.Dispatch<React.SetStateAction<string[]>>
  setAiResult: (r: AISourcingResult | null) => void
  setAiSelectedCombos: React.Dispatch<React.SetStateAction<Set<number>>>
  setAiExcludedBrands: React.Dispatch<React.SetStateAction<Set<string>>>
  setAiExcludedKeywords: React.Dispatch<React.SetStateAction<Set<string>>>
  setAiMinCount: (v: number) => void
  setAiCreating: (v: boolean) => void
  setAiSourceSite: (v: string) => void
  onClose: () => void
  onCreated: () => void  // load + loadTree 호출
}

// AI 소싱기 모달
export default function AiSourcingModal({
  open,
  aiSourcingStep,
  aiMonth,
  aiMainCategory,
  aiExcelFile,
  aiTargetCount,
  aiAnalyzing,
  aiLogs,
  aiResult,
  aiSelectedCombos,
  aiExcludedBrands,
  aiMinCount,
  aiCreating,
  aiSourceSite,
  setAiSourcingStep,
  setAiMonth,
  setAiMainCategory,
  setAiExcelFile,
  setAiAnalyzing,
  setAiLogs,
  setAiResult,
  setAiSelectedCombos,
  setAiExcludedBrands,
  setAiMinCount,
  setAiCreating,
  setAiSourceSite,
  onClose,
  onCreated,
}: AiSourcingModalProps) {
  if (!open) return null

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={() => !aiAnalyzing && onClose()}>
      <div onClick={e => e.stopPropagation()} style={{
        background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px',
        width: aiSourcingStep === 'confirm' ? '900px' : '560px',
        maxHeight: '85vh', overflow: 'auto',
      }}>
        {/* 헤더 */}
        <div style={{
          padding: '16px 20px', borderBottom: '1px solid #2D2D2D',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.1rem' }}>🤖</span>
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>AI 소싱기</span>
            <span style={{ fontSize: '0.75rem', color: '#888', marginLeft: '4px' }}>
              {aiSourcingStep === 'config' ? '1/3 데이터소스 설정' :
               aiSourcingStep === 'analyzing' ? '2/3 분석 중' : '3/3 결과 확인'}
            </span>
          </div>
          {!aiAnalyzing && (
            <button onClick={onClose} style={{
              background: 'none', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer',
            }}>✕</button>
          )}
        </div>

        {/* STEP 1: 월 + 대카테고리 설정 */}
        {aiSourcingStep === 'config' && (
          <div style={{ padding: '20px' }}>
            {/* 월 + 대카테고리 (핵심 2개 입력) */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>분석 월 (작년)</label>
                <select value={aiMonth} onChange={e => setAiMonth(Number(e.target.value))} style={{
                  width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                  borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                }}>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                    <option key={m} value={m}>{m}월</option>
                  ))}
                </select>
                <span style={{ fontSize: '0.7rem', color: '#555', marginTop: '4px', display: 'block' }}>
                  {new Date().getFullYear() - 1}년 {aiMonth}월 데이터
                </span>
              </div>
              <div>
                <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>대 카테고리</label>
                <select value={aiMainCategory} onChange={e => setAiMainCategory(e.target.value)} style={{
                  width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                  borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                }}>
                  <option value='패션의류'>패션의류</option>
                  <option value='패션잡화'>패션잡화</option>
                  <option value='스포츠/레저'>스포츠/레저</option>
                  <option value='패션전체'>패션전체 (의류+잡화)</option>
                </select>
              </div>
            </div>

            {/* 수집 소싱처 선택 */}
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '8px' }}>수집 소싱처</label>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                {SITES.map(s => (
                  <button key={s.id} disabled={s.disabled} onClick={() => { if (!s.disabled) setAiSourceSite(s.id) }} style={{
                    padding: '6px 14px', borderRadius: '6px', fontSize: '0.78rem',
                    cursor: s.disabled ? 'not-allowed' : 'pointer',
                    fontWeight: aiSourceSite === s.id ? 700 : 400,
                    background: s.disabled ? 'transparent' : aiSourceSite === s.id ? 'rgba(255,140,0,0.15)' : '#111',
                    border: s.disabled ? '1px solid #2A2A2A' : aiSourceSite === s.id ? '1px solid #FF8C00' : '1px solid #2D2D2D',
                    color: s.disabled ? '#555' : aiSourceSite === s.id ? '#FF8C00' : '#888',
                    opacity: s.disabled ? 0.6 : 1,
                  }}>{s.label}{s.disabled ? ' (예정)' : ''}</button>
                ))}
              </div>
            </div>

            {/* 자동 조회 범위 */}
            <div style={{
              background: 'rgba(108,92,231,0.08)', border: '1px solid rgba(108,92,231,0.25)',
              borderRadius: '8px', padding: '12px 14px', marginBottom: '16px', fontSize: '0.78rem',
            }}>
              <div style={{ color: '#A29BFE', fontWeight: 600, marginBottom: '6px' }}>자동 조회 범위</div>
              <div style={{ color: '#999', lineHeight: 1.6 }}>
                <span style={{ color: '#4C9AFF' }}>무신사</span>:{' '}
                {aiMainCategory === '패션의류' ? '상의, 아우터, 바지, 원피스/스커트, 속옷/슬립웨어' :
                 aiMainCategory === '패션잡화' ? '가방, 신발, 시계/주얼리, 패션소품' :
                 aiMainCategory === '스포츠/레저' ? '스포츠/레저' : '전체 10개 카테고리'}
                <br />
                <span style={{ color: '#51CF66' }}>네이버 데이터랩</span>:{' '}
                {aiMainCategory === '패션전체' ? '패션의류 + 패션잡화' : aiMainCategory} 인기검색어 TOP 500
              </div>
            </div>

            {/* 엑셀 업로드 + 최소 상품수 */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px',
            }}>
              <div style={{
                background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>판매 엑셀 (선택)</span>
                  <span style={{ fontSize: '0.72rem', color: '#888' }}>정확도 향상</span>
                </div>
                <input type='file' accept='.xlsx,.xlsm,.xls,.csv'
                  onChange={e => setAiExcelFile(e.target.files?.[0] || null)}
                  style={{ fontSize: '0.8rem', color: '#888' }}
                />
                {aiExcelFile && (
                  <span style={{ fontSize: '0.75rem', color: '#FFB84D', display: 'block', marginTop: '4px' }}>
                    {aiExcelFile.name}
                  </span>
                )}
              </div>
              <div style={{
                background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>최소 상품수</span>
                  <span style={{ fontSize: '0.72rem', color: '#888' }}>미만 그룹 배제</span>
                </div>
                <input
                  type='text'
                  inputMode='numeric'
                  value={aiMinCount || ''}
                  onChange={e => setAiMinCount(Number(e.target.value.replace(/[^0-9]/g, '')) || 0)}
                  placeholder='0'
                  style={{
                    width: '100%', padding: '6px 10px', background: '#0A0A0A', border: '1px solid #3D3D3D',
                    borderRadius: '6px', color: '#FFB84D', fontSize: '0.9rem', fontWeight: 600,
                  }}
                />
              </div>
            </div>

            {/* 시작 버튼 */}
            <button
              onClick={async () => {
                setAiSourcingStep('analyzing')
                setAiAnalyzing(true)
                setAiLogs([`[시작] ${new Date().getFullYear() - 1}년 ${aiMonth}월 / ${aiMainCategory} 분석 시작...`])
                let gotResult = false
                try {
                  const resp = await aiSourcingApi.analyzeFull({
                    month: aiMonth,
                    main_category: aiMainCategory,
                    target_count: aiTargetCount,
                    file: aiExcelFile || undefined,
                  })
                  // HTTP 에러 체크
                  if (!resp.ok) {
                    const errText = await resp.text()
                    throw new Error(`서버 오류 (${resp.status}): ${errText.slice(0, 200)}`)
                  }
                  const reader = resp.body?.getReader()
                  if (!reader) throw new Error('스트리밍 응답 없음')
                  const decoder = new TextDecoder()
                  let buffer = ''
                  const processLine = (line: string) => {
                    if (line.startsWith('event: ')) return
                    if (!line.startsWith('data: ')) return
                    try {
                      const payload = JSON.parse(line.slice(6))
                      if (typeof payload === 'string') {
                        setAiLogs(prev => [...prev, payload])
                      } else if (payload.brands && payload.combinations) {
                        gotResult = true
                        const result = payload as AISourcingResult
                        setAiResult(result)
                        // IP위험 브랜드 표시만 (제외하지 않음 — 사용자가 판단)
                        setAiExcludedBrands(new Set())
                        setAiExcludedBrands(new Set())
                        // 전체 조합 기본 선택
                        const all = new Set<number>()
                        result.combinations.forEach((_c: AISourcingCombination, i: number) => {
                          all.add(i)
                        })
                        setAiSelectedCombos(all)
                      } else if (payload.step) {
                        setAiLogs(prev => [...prev, `[${payload.step}] ${fmtNum(payload.count)}개 처리`])
                      } else if (payload.message) {
                        setAiLogs(prev => [...prev, payload.message])
                      }
                    } catch { /* JSON 파싱 실패 무시 */ }
                  }
                  while (true) {
                    const { done, value } = await reader.read()
                    if (done) break
                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n')
                    buffer = lines.pop() || ''
                    for (const line of lines) processLine(line)
                  }
                  // 남은 버퍼 처리
                  if (buffer.trim()) processLine(buffer.trim())
                  // 결과가 있을 때만 confirm 단계로 전환
                  if (gotResult) {
                    setAiSourcingStep('confirm')
                  } else {
                    setAiLogs(prev => [...prev, '[오류] 분석 결과를 받지 못했습니다. 백엔드 로그를 확인해주세요.'])
                  }
                } catch (err) {
                  setAiLogs(prev => [...prev, `[오류] ${err instanceof Error ? err.message : '분석 실패'}`])
                }
                setAiAnalyzing(false)
              }}
              style={{
                width: '100%', padding: '10px', borderRadius: '8px',
                background: 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                color: '#fff', fontWeight: 700, fontSize: '0.9rem',
                border: 'none', cursor: 'pointer',
              }}
            >
              AI 분석 시작
            </button>
          </div>
        )}

        {/* STEP 2: 분석 중 */}
        {aiSourcingStep === 'analyzing' && (
          <div style={{ padding: '20px' }}>
            <div style={{
              background: '#080A10', borderRadius: '8px', padding: '14px',
              height: '300px', overflowY: 'auto', fontFamily: 'monospace',
              fontSize: '0.62rem', lineHeight: 1.5, color: '#8A95B0',
            }}>
              {aiLogs.map((line, i) => (
                <p key={i} style={{
                  margin: 0,
                  color: line.includes('완료') || line.includes('성공') ? '#51CF66'
                    : line.includes('오류') || line.includes('실패') ? '#FF6B6B'
                    : line.includes('시작') ? '#4C9AFF' : '#8A95B0',
                }}>{line}</p>
              ))}
            </div>
            {!aiAnalyzing && (
              <div style={{ marginTop: '12px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                {aiResult && (
                  <button onClick={() => setAiSourcingStep('confirm')} style={{
                    padding: '8px 20px', borderRadius: '6px',
                    background: 'rgba(81,207,102,0.2)', border: '1px solid rgba(81,207,102,0.5)',
                    color: '#51CF66', cursor: 'pointer', fontWeight: 600,
                  }}>결과 확인 →</button>
                )}
                <button onClick={onClose} style={{
                  padding: '8px 20px', borderRadius: '6px',
                  background: 'transparent', border: '1px solid #3D3D3D',
                  color: '#888', cursor: 'pointer',
                }}>닫기</button>
              </div>
            )}
          </div>
        )}

        {/* STEP 3: 결과 확인 + 컨펌 */}
        {aiSourcingStep === 'confirm' && aiResult && (
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
              // 소싱처별 브랜드 + 키워드 그룹핑
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
                            // 키워드 제외 시 해당 키워드를 가진 조합 체크 해제
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

            {/* IP위험 브랜드 — 취소선 표시, 클릭으로 제외/포함 전환 */}
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
        )}
      </div>
    </div>
  )
}

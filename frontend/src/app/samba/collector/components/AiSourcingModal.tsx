'use client'

import {
  aiSourcingApi,
  type AISourcingResult,
  type AISourcingCombination,
} from '@/lib/samba/api/operations'
import { showAlert } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { SITES } from '../constants'
import AiSourcingConfirmStep from './AiSourcingConfirmStep'

interface AiSourcingModalProps {
  open: boolean
  aiSourcingStep: 'config' | 'analyzing' | 'confirm'
  aiMonth: number; aiMainCategory: string; aiExcelFile: File | null; aiTargetCount: number
  aiAnalyzing: boolean; aiLogs: string[]; aiResult: AISourcingResult | null
  aiSelectedCombos: Set<number>; aiExcludedBrands: Set<string>; aiExcludedKeywords: Set<string>
  aiMinCount: number; aiCreating: boolean; aiSourceSite: string
  setAiSourcingStep: (step: 'config' | 'analyzing' | 'confirm') => void
  setAiMonth: (v: number) => void; setAiMainCategory: (v: string) => void
  setAiExcelFile: (f: File | null) => void; setAiTargetCount: (v: number) => void
  setAiAnalyzing: (v: boolean) => void; setAiLogs: React.Dispatch<React.SetStateAction<string[]>>
  setAiResult: (r: AISourcingResult | null) => void
  setAiSelectedCombos: React.Dispatch<React.SetStateAction<Set<number>>>
  setAiExcludedBrands: React.Dispatch<React.SetStateAction<Set<string>>>
  setAiExcludedKeywords: React.Dispatch<React.SetStateAction<Set<string>>>
  setAiMinCount: (v: number) => void; setAiCreating: (v: boolean) => void; setAiSourceSite: (v: string) => void
  onClose: () => void; onCreated: () => void
}

export default function AiSourcingModal({
  open, aiSourcingStep,
  aiMonth, aiMainCategory, aiExcelFile, aiTargetCount,
  aiAnalyzing, aiLogs, aiResult,
  aiSelectedCombos, aiExcludedBrands, aiMinCount, aiCreating, aiSourceSite,
  setAiSourcingStep, setAiMonth, setAiMainCategory, setAiExcelFile,
  setAiAnalyzing, setAiLogs, setAiResult,
  setAiSelectedCombos, setAiExcludedBrands,
  setAiMinCount, setAiCreating, setAiSourceSite,
  onClose, onCreated,
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
          <AiSourcingConfirmStep
            aiResult={aiResult}
            aiSelectedCombos={aiSelectedCombos}
            aiExcludedBrands={aiExcludedBrands}
            aiMinCount={aiMinCount}
            aiCreating={aiCreating}
            aiSourceSite={aiSourceSite}
            setAiSelectedCombos={setAiSelectedCombos}
            setAiExcludedBrands={setAiExcludedBrands}
            setAiSourcingStep={setAiSourcingStep}
            setAiResult={setAiResult}
            setAiCreating={setAiCreating}
            onClose={onClose}
            onCreated={onCreated}
          />
        )}
      </div>
    </div>
  )
}

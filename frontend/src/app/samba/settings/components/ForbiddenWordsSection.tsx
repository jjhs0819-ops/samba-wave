'use client'

import { Dispatch, SetStateAction } from 'react'
import { card, fmtNum } from '@/lib/samba/styles'
import { forbiddenApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'

interface Props {
  forbiddenText: string
  deletionText: string
  optionDeletionText: string
  wordsSaving: boolean
  setForbiddenText: (v: string) => void
  setDeletionText: (v: string) => void
  setOptionDeletionText: (v: string) => void
  setWordsSaving: (v: boolean) => void
  setInitialForbiddenText: (v: string) => void
  setInitialDeletionText: (v: string) => void
  setInitialOptionDeletionText: (v: string) => void
  tagBanned: { rejected: string[]; brands: string[]; source_sites: string[] }
  setTagBanned: Dispatch<SetStateAction<{ rejected: string[]; brands: string[]; source_sites: string[] }>>
}

export function ForbiddenWordsSection(props: Props) {
  const {
    forbiddenText, deletionText, optionDeletionText, wordsSaving,
    setForbiddenText, setDeletionText, setOptionDeletionText, setWordsSaving,
    setInitialForbiddenText, setInitialDeletionText, setInitialOptionDeletionText,
    tagBanned, setTagBanned,
  } = props

  return (
    <>
      {/* 금지어 / 삭제어 (전역) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5' }}>금지어 / 삭제어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>모든 그룹·상품에 공통 적용</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FF6B6B', fontWeight: 600 }}>
                금지어 (IP위험 브랜드 포함) — 세미콜론(;) 구분
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(forbiddenText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('forbidden', words)
                    const deduped = words.join('; ')
                    setForbiddenText(deduped)
                    setInitialForbiddenText(deduped)
                    showAlert(`금지어 ${fmtNum(words.length)}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                  color: '#FF6B6B', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={forbiddenText}
              onChange={e => setForbiddenText(e.target.value)}
              placeholder="구찌; 루이비통; 샤넬; 프라다"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {fmtNum(forbiddenText.split(';').filter(w => w.trim()).length)}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600 }}>
                삭제어 — 상품명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(deletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('deletion', words)
                    const deduped = words.join('; ')
                    setDeletionText(deduped)
                    setInitialDeletionText(deduped)
                    showAlert(`삭제어 ${fmtNum(words.length)}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,184,77,0.12)', border: '1px solid rgba(255,184,77,0.3)',
                  color: '#FFB84D', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={deletionText}
              onChange={e => setDeletionText(e.target.value)}
              placeholder="매장정품; 정품; 해외직구; 무료배송"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {fmtNum(deletionText.split(';').filter(w => w.trim()).length)}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#A29BFE', fontWeight: 600 }}>
                옵션삭제어 — 옵션명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(optionDeletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('option_deletion', words)
                    const deduped = words.join('; ')
                    setOptionDeletionText(deduped)
                    setInitialOptionDeletionText(deduped)
                    showAlert(`옵션삭제어 ${fmtNum(words.length)}개 저장 완료`, 'success')
                  } catch {
                    showAlert('저장 실패', 'error')
                  }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(162,155,254,0.12)', border: '1px solid rgba(162,155,254,0.3)',
                  color: '#A29BFE', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={optionDeletionText}
              onChange={e => setOptionDeletionText(e.target.value)}
              placeholder="01(; 02(; ); [품절]"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {fmtNum(optionDeletionText.split(';').filter(w => w.trim()).length)}개
            </div>
          </div>
        </div>
      </div>

      {/* 태그 금지어 (스마트스토어 등록불가 단어) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#C4736E' }}>태그 금지어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 스마트스토어 등록 시 자동 제외되는 단어 (API 거부 + 소싱처 + 브랜드)</span>
          <button onClick={() => forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})}
            style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>새로고침</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#C4736E', fontWeight: 600, marginBottom: '0.4rem' }}>
              API 거부 태그 ({fmtNum(tagBanned.rejected.length)}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>전송 실패 시 자동 누적 + 직접 추가 가능</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
              {tagBanned.rejected.length === 0 && <span style={{ fontSize: '0.75rem', color: '#555' }}>아직 없음</span>}
              {tagBanned.rejected.map((w, i) => (
                <span key={i} style={{
                  fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px',
                  background: 'rgba(196,115,110,0.12)', border: '1px solid rgba(196,115,110,0.3)', color: '#C4736E',
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                }}>
                  {w}
                  <span style={{ cursor: 'pointer', color: '#888', fontSize: '0.8rem', lineHeight: 1 }}
                    onClick={async () => {
                      const updated = tagBanned.rejected.filter((_, idx) => idx !== i)
                      await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                      setTagBanned(prev => ({ ...prev, rejected: updated }))
                    }}>×</span>
                </span>
              ))}
              <input
                type="text"
                placeholder="금지어 입력 후 Enter"
                style={{ fontSize: '0.7rem', padding: '2px 7px', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#C5C5C5', background: '#1A1A1A', outline: 'none', width: '140px' }}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') {
                    const val = e.currentTarget.value.trim().toLowerCase()
                    if (!val || tagBanned.rejected.includes(val)) return
                    const updated = [...tagBanned.rejected, val]
                    await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                    setTagBanned(prev => ({ ...prev, rejected: updated }))
                    e.currentTarget.value = ''
                  }
                }}
              />
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600, marginBottom: '0.4rem' }}>
              수집 브랜드 ({fmtNum(tagBanned.brands.length)}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>브랜드명 포함 태그 자동 제외</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', maxHeight: '80px', overflow: 'auto' }}>
              {tagBanned.brands.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(255,184,77,0.08)', border: '1px solid rgba(255,184,77,0.25)', color: '#FFB84D' }}>{w}</span>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#4C9AFF', fontWeight: 600, marginBottom: '0.4rem' }}>
              소싱처 ({fmtNum(tagBanned.source_sites.length)}개)
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {tagBanned.source_sites.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(76,154,255,0.08)', border: '1px solid rgba(76,154,255,0.25)', color: '#4C9AFF' }}>{w}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

'use client'

import { proxyApi } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'
import { btn } from '@/lib/samba/buttons'

export interface TagPreview {
  group_id: string
  group_name: string
  product_count: number
  rep_name: string
  tags: string[]
  seo_keywords: string[]
  coupang_search_tags?: string[]
}

export interface TagPreviewCost {
  api_calls: number
  input_tokens: number
  output_tokens: number
  cost_krw: number
}

interface TagPreviewModalProps {
  open: boolean
  tagPreviews: TagPreview[]
  tagPreviewCost: TagPreviewCost | null
  removedTags: string[]
  setTagPreviews: React.Dispatch<React.SetStateAction<TagPreview[]>>
  setRemovedTags: React.Dispatch<React.SetStateAction<string[]>>
  setLastAiUsage: (usage: { calls: number; tokens: number; cost: number; date: string }) => void
  setSelectedIds: React.Dispatch<React.SetStateAction<Set<string>>>
  setSelectAll: (v: boolean) => void
  onClose: () => void
  onApplied: () => void  // load + loadTree 호출
}

// AI 태그 미리보기 모달
export default function TagPreviewModal({
  open,
  tagPreviews,
  tagPreviewCost,
  removedTags,
  setTagPreviews,
  setRemovedTags,
  setLastAiUsage,
  setSelectedIds,
  setSelectAll,
  onClose,
  onApplied,
}: TagPreviewModalProps) {
  const c = useTheme()
  if (!open) return null

  const handleClose = () => {
    onClose()
    setRemovedTags([])
  }

  return (
    <div
      data-tag-preview-modal
      style={{ position: 'fixed', inset: 0, zIndex: 99999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={handleClose}
    >
      <div
        style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '12px', padding: '28px 32px', minWidth: '500px', maxWidth: '700px', maxHeight: '80vh', overflowY: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 600, color: c.text }}>AI 태그 미리보기</h3>
        <p style={{ margin: '0 0 20px', fontSize: '0.75rem', color: c.textMuted }}>
          태그사전에 미등록된 태그를 X로 제거한 후 적용하세요
        </p>
        {tagPreviews.map((preview) => (
          <div key={preview.group_id} style={{ marginBottom: '20px', padding: '16px', background: c.surfaceAlt, borderRadius: '8px', border: `1px solid ${c.border}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <div>
                <span style={{ fontSize: '0.82rem', color: c.text, fontWeight: 600 }}>{preview.group_name}</span>
                {preview.rep_name && preview.rep_name !== preview.group_name && (
                  <span style={{ fontSize: '0.7rem', color: c.textMuted, marginLeft: '6px' }}>({preview.rep_name})</span>
                )}
              </div>
              <span style={{ fontSize: '0.7rem', color: c.textMuted }}>{fmtNum(preview.product_count)}개 상품 | {fmtNum(preview.tags.length)}개 태그</span>
            </div>
            <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.72rem', color: c.textSub, fontWeight: 600, whiteSpace: 'nowrap' }}>SEO:</span>
              <input
                type='text'
                defaultValue={preview.seo_keywords.join(', ')}
                placeholder='SEO 키워드 (콤마 구분)'
                onBlur={(e) => {
                  const newKws = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                  setTagPreviews(prev => prev.map(p =>
                    p.group_id === preview.group_id ? { ...p, seo_keywords: newKws } : p
                  ))
                }}
                onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                style={{ flex: 1, fontSize: '0.72rem', padding: '3px 8px', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, outline: 'none' }}
              />
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {preview.tags.map((tag, ti) => (
                <span key={ti} style={{
                  fontSize: '0.78rem', padding: '4px 10px', borderRadius: '14px',
                  background: c.surface, border: `1px solid ${c.border}`, color: c.text,
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                }}>
                  {tag}
                  <span
                    style={{ cursor: 'pointer', color: c.textMuted, fontSize: '0.85rem', lineHeight: 1 }}
                    onClick={async () => {
                      setTagPreviews(prev => prev.map(p => ({
                        ...p, tags: p.tags.filter(t => t !== tag)
                      })))
                      const ban = await showConfirm(`"${tag}"을(를) 금지태그에 등록할까요?\n(등록하면 다음 AI태그 생성 시 자동 제외됩니다)`)
                      if (ban) {
                        setRemovedTags(prev => prev.includes(tag) ? prev : [...prev, tag])
                      }
                    }}
                  >&times;</span>
                </span>
              ))}
            </div>
            <input
              type='text'
              placeholder='추가 태그 입력 후 Enter (콤마 구분 가능)'
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  const input = (e.target as HTMLInputElement)
                  const newTags = input.value.split(',').map(t => t.trim()).filter(Boolean)
                  if (newTags.length === 0) return
                  setTagPreviews(prev => prev.map(p =>
                    p.group_id === preview.group_id
                      ? { ...p, tags: [...p.tags, ...newTags.filter(t => !p.tags.includes(t))] }
                      : p
                  ))
                  input.value = ''
                }
              }}
              style={{
                width: '100%', padding: '5px 10px', fontSize: '0.75rem',
                background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '6px',
                color: c.text, outline: 'none',
              }}
            />
            {/* 쿠팡 전용 검색어 (연관/자동완성/롱테일) — 최대 10개 */}
            <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: `1px dashed ${c.border}` }}>
              <div style={{ fontSize: '0.72rem', color: c.text, fontWeight: 600, marginBottom: '6px' }}>
                쿠팡 전용 검색어 (연관·자동완성·롱테일) — {fmtNum((preview.coupang_search_tags || []).length)}개
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
                {(preview.coupang_search_tags || []).map((tag, ti) => (
                  <span key={`c-${ti}`} style={{
                    fontSize: '0.78rem', padding: '4px 10px', borderRadius: '14px',
                    background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.25)', color: c.text,
                    display: 'inline-flex', alignItems: 'center', gap: '6px',
                  }}>
                    {tag}
                    <span
                      style={{ cursor: 'pointer', color: c.textMuted, fontSize: '0.85rem', lineHeight: 1 }}
                      onClick={() => {
                        setTagPreviews(prev => prev.map(p =>
                          p.group_id === preview.group_id
                            ? { ...p, coupang_search_tags: (p.coupang_search_tags || []).filter(t => t !== tag) }
                            : p
                        ))
                      }}
                    >&times;</span>
                  </span>
                ))}
              </div>
              <input
                type='text'
                placeholder='쿠팡 검색어 추가 후 Enter (콤마 구분 가능, 최대 10개)'
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    const input = (e.target as HTMLInputElement)
                    const adds = input.value.split(',').map(t => t.trim()).filter(Boolean)
                    if (adds.length === 0) return
                    setTagPreviews(prev => prev.map(p => {
                      if (p.group_id !== preview.group_id) return p
                      const cur = p.coupang_search_tags || []
                      const merged = [...cur, ...adds.filter(t => !cur.includes(t))].slice(0, 10)
                      return { ...p, coupang_search_tags: merged }
                    }))
                    input.value = ''
                  }
                }}
                style={{
                  width: '100%', padding: '5px 10px', fontSize: '0.75rem',
                  background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '6px',
                  color: c.text, outline: 'none',
                }}
              />
            </div>
          </div>
        ))}
        {removedTags.length > 0 && (
          <div style={{ marginBottom: '12px', padding: '10px 14px', background: 'rgba(255,107,107,0.06)', borderRadius: '6px', border: '1px solid rgba(255,107,107,0.15)' }}>
            <span style={{ fontSize: '0.72rem', color: c.danger, fontWeight: 600 }}>금지태그 등록 예정 ({fmtNum(removedTags.length)}개): </span>
            <span style={{ fontSize: '0.72rem', color: c.textMuted }}>{removedTags.join(', ')}</span>
          </div>
        )}
        {tagPreviewCost && (
          <p style={{ margin: '0 0 16px', fontSize: '0.72rem', color: c.textMuted, textAlign: 'right' }}>
            API {fmtNum(tagPreviewCost.api_calls)}회 | {fmtNum(tagPreviewCost.input_tokens + tagPreviewCost.output_tokens)} 토큰 | ~{fmtNum(tagPreviewCost.cost_krw)}원
          </p>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <button
            onClick={handleClose}
            style={{ ...btn('ghost'), padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px' }}
          >취소</button>
          <button
            onClick={async () => {
              const groups = tagPreviews.filter(p => p.tags.length > 0).map(p => ({ group_id: p.group_id, tags: p.tags, seo_keywords: p.seo_keywords, coupang_search_tags: p.coupang_search_tags || [] }))
              if (groups.length === 0) { showAlert('적용할 태그가 없습니다'); return }
              try {
                const res = await proxyApi.applyAiTags(groups, removedTags)
                if (res.success) {
                  showAlert(res.message, 'success')
                  if (tagPreviewCost) {
                    const now = new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' })
                    setLastAiUsage({
                      calls: tagPreviewCost.api_calls,
                      tokens: tagPreviewCost.input_tokens + tagPreviewCost.output_tokens,
                      cost: tagPreviewCost.cost_krw,
                      date: now,
                    })
                  }
                  onClose()
                  setSelectedIds(new Set()); setSelectAll(false)
                  onApplied()
                } else showAlert(res.message, 'error')
              } catch (e) {
                showAlert(`태그 적용 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
              }
            }}
            style={{ ...btn('primary'), padding: '7px 20px', fontSize: '0.85rem', borderRadius: '6px' }}
          >
            전체 그룹에 적용 ({fmtNum(tagPreviews.reduce((s, p) => s + p.tags.length, 0))}개 태그)
          </button>
        </div>
      </div>
    </div>
  )
}

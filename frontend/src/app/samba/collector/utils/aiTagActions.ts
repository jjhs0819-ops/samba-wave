'use client'

import { Dispatch, SetStateAction } from 'react'
import { proxyApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import type { TagPreview, TagPreviewCost } from '../components/TagPreviewModal'

interface AiTagPreviewArgs {
  selectAll: boolean
  selectedIds: Set<string>
  displayedFilters: SambaSearchFilter[]
  setTagPreviewLoading: Dispatch<SetStateAction<boolean>>
  addLog: (msg: string) => void
  setTagPreviews: Dispatch<SetStateAction<TagPreview[]>>
  setTagPreviewCost: Dispatch<SetStateAction<TagPreviewCost | null>>
  setRemovedTags: Dispatch<SetStateAction<string[]>>
  setShowTagPreview: Dispatch<SetStateAction<boolean>>
}

export async function performAiTagPreview(args: AiTagPreviewArgs) {
  const {
    selectAll, selectedIds, displayedFilters, setTagPreviewLoading, addLog,
    setTagPreviews, setTagPreviewCost, setRemovedTags, setShowTagPreview,
  } = args
  const checkedIds = selectAll ? displayedFilters.map(f => f.id) : [...selectedIds]
  const targetFilters = checkedIds.length > 0
    ? displayedFilters.filter(f => checkedIds.includes(f.id))
    : [...displayedFilters]
  if (targetFilters.length === 0) { showAlert('검색그룹이 없습니다'); return }
  const ok = await showConfirm(`${checkedIds.length > 0 ? '선택된' : '전체'} ${fmtNum(targetFilters.length)}개 그룹의 상품에 AI 태그를 생성하시겠습니까?\n(그룹별 대표 1개로 API 호출, 미리보기 후 확정)`)
  if (!ok) return
  setTagPreviewLoading(true)
  try {
    addLog(`[AI태그] ${fmtNum(targetFilters.length)}개 그룹 태그 생성 시작...`)
    const allPreviews: TagPreview[] = []
    let totalCalls = 0, totalInput = 0, totalOutput = 0, totalCost = 0
    for (let i = 0; i < targetFilters.length; i++) {
      const f = targetFilters[i]
      await new Promise(r => setTimeout(r, 50))
      try {
        const res = await proxyApi.previewAiTags([], [f.id])
        if (res.success && res.previews?.length > 0) {
          allPreviews.push(...(res.previews as TagPreview[]))
          totalCalls += res.api_calls || 0
          totalInput += res.input_tokens || 0
          totalOutput += res.output_tokens || 0
          totalCost += res.cost_krw || 0
          const firstPreview = res.previews[0] as TagPreview
          const tags = firstPreview?.tags || []
          const seo = firstPreview?.seo_keywords || []
          addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → SEO: ${seo.join(', ')} | 태그: ${fmtNum(tags.length)}개`)
        } else {
          addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → 태그 없음`)
        }
      } catch (e) {
        addLog(`[AI태그] [${fmtNum(i + 1)}/${fmtNum(targetFilters.length)}] ${f.name} → 실패: ${e instanceof Error ? e.message : '오류'}`)
      }
    }
    addLog(`[AI태그] 완료: ${fmtNum(allPreviews.length)}/${fmtNum(targetFilters.length)}개 그룹 | API ${fmtNum(totalCalls)}회 | ${fmtNum(Number(totalCost.toFixed(0)))}원`)
    if (allPreviews.length > 0) {
      setTagPreviews(allPreviews)
      setTagPreviewCost({ api_calls: totalCalls, input_tokens: totalInput, output_tokens: totalOutput, cost_krw: totalCost })
      setRemovedTags([])
      setShowTagPreview(true)
    } else {
      showAlert('생성된 태그가 없습니다', 'info')
    }
  } catch (e) {
    showAlert(`태그 생성 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
  } finally {
    setTagPreviewLoading(false)
  }
}

interface ClearAiTagsArgs {
  selectAll: boolean
  selectedIds: Set<string>
  displayedFilters: SambaSearchFilter[]
  addLog: (msg: string) => void
}

export async function performClearAiTags(args: ClearAiTagsArgs) {
  const { selectAll, selectedIds, displayedFilters, addLog } = args
  const checkedIds = selectAll ? displayedFilters.map(f => f.id) : [...selectedIds]
  const targetFilters = displayedFilters.filter(f => checkedIds.includes(f.id))
  if (targetFilters.length === 0) { showAlert('검색그룹을 선택해주세요'); return }
  const ok = await showConfirm(`${fmtNum(targetFilters.length)}개 그룹의 AI 태그를 전체 삭제하시겠습니까?`)
  if (!ok) return
  try {
    const groupIds = targetFilters.map(f => f.id)
    const res = await proxyApi.clearAiTags(groupIds)
    if (res.success) {
      showAlert(res.message, 'success')
      addLog(`[태그삭제] ${fmtNum(targetFilters.length)}개 그룹 AI 태그 삭제 완료`)
    } else showAlert(res.message, 'error')
  } catch (e) {
    showAlert(`태그 삭제 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
  }
}

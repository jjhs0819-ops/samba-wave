'use client'

import { Dispatch, SetStateAction } from 'react'
import { collectorApi, proxyApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

export interface DeleteGroupsArgs {
  displayedFilters: SambaSearchFilter[]
  selectedIds: Set<string>
  drillBrand: string | null
  filters: SambaSearchFilter[]
  siteFilter: string
  setDeleteJobLogs: Dispatch<SetStateAction<string[]>>
  setDeleteJobDone: Dispatch<SetStateAction<boolean>>
  setDeleteJobModal: Dispatch<SetStateAction<boolean>>
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  setSelectAll: Dispatch<SetStateAction<boolean>>
  load: () => void | Promise<void>
  loadTree: () => void | Promise<void>
}

export async function performDeleteSelectedGroups(args: DeleteGroupsArgs) {
  const {
    displayedFilters, selectedIds, drillBrand, filters, siteFilter,
    setDeleteJobLogs, setDeleteJobDone, setDeleteJobModal,
    setSelectedIds, setSelectAll, load, loadTree,
  } = args
  const displayedIds = new Set(displayedFilters.map(f => f.id))
  const baseIds = selectedIds.size > 0
    ? new Set([...selectedIds].filter(id => displayedIds.has(id)))
    : displayedIds
  if (baseIds.size === 0) {
    showAlert(`삭제 대상이 없습니다. (selectedIds=${fmtNum(selectedIds.size)}, displayed=${fmtNum(displayedFilters.length)}, drillBrand=${drillBrand || '없음'})`)
    return
  }

  const allIds = new Set(baseIds)
  const findChildren = (parentId: string) => {
    for (const f of filters) {
      if (f.parent_id === parentId && !allIds.has(f.id)) {
        if (siteFilter && f.source_site && f.source_site !== siteFilter) continue
        allIds.add(f.id)
        findChildren(f.id)
      }
    }
  }
  for (const id of baseIds) findChildren(id)

  const childCount = allIds.size - baseIds.size
  const label = selectedIds.size > 0 ? '선택된' : '표시된'
  const msg = childCount > 0
    ? `${label} ${fmtNum(baseIds.size)}개 + 하위 ${fmtNum(childCount)}개 (총 ${fmtNum(allIds.size)}개) 그룹과 상품을 모두 삭제하시겠습니까?`
    : `${label} ${fmtNum(baseIds.size)}개 그룹과 그룹 내 상품을 모두 삭제하시겠습니까?`
  if (!await showConfirm(msg)) return

  const allIdsArr = [...allIds]
  const nameMap = new Map(filters.map(f => [f.id, f.name]))
  setDeleteJobLogs([`🗑️ 총 ${fmtNum(allIdsArr.length)}개 그룹 삭제 시작...`])
  setDeleteJobDone(false)
  setDeleteJobModal(true)

  let doneCount = 0
  let skipCount = 0
  for (const id of allIdsArr) {
    const groupName = nameMap.get(id) || id
    setDeleteJobLogs(prev => [...prev, `[${fmtNum(doneCount + skipCount + 1)}/${fmtNum(allIdsArr.length)}] "${groupName}" 처리 중...`])
    try {
      const res = await collectorApi.scrollProducts({ skip: 0, limit: 10000, search_filter_id: id })
      const registered = res.items.filter(p => p.market_product_nos && Object.keys(p.market_product_nos).length > 0)
      if (registered.length > 0) {
        setDeleteJobLogs(prev => [...prev, `  ⚠️ 마켓등록 상품 ${fmtNum(registered.length)}건 — 삭제 건너뜀`])
        skipCount++
        continue
      }
      const productIds = res.items.map(p => p.id)
      if (productIds.length > 0) {
        setDeleteJobLogs(prev => [...prev, `  상품 ${fmtNum(productIds.length)}건 삭제 중...`])
        await collectorApi.bulkDeleteProducts(productIds)
      }
    } catch { /* 상품 없으면 무시 */ }
    await collectorApi.deleteFilter(id).catch(() => {})
    doneCount++
    setDeleteJobLogs(prev => [...prev, `  ✅ 삭제 완료`])
  }

  setDeleteJobLogs(prev => [...prev, ``, `🎉 완료 — ${fmtNum(doneCount)}개 삭제${skipCount > 0 ? `, ${fmtNum(skipCount)}개 건너뜀` : ''}`])
  setDeleteJobDone(true)
  setSelectedIds(new Set())
  setSelectAll(false)
  load(); loadTree()
}

interface AiTagPreviewArgs {
  selectAll: boolean
  selectedIds: Set<string>
  displayedFilters: SambaSearchFilter[]
  setTagPreviewLoading: Dispatch<SetStateAction<boolean>>
  addLog: (msg: string) => void
  setTagPreviews: Dispatch<SetStateAction<Array<Record<string, unknown>>>>
  setTagPreviewCost: Dispatch<SetStateAction<{ api_calls: number; input_tokens: number; output_tokens: number; cost_krw: number }>>
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
    const allPreviews: Array<Record<string, unknown>> = []
    let totalCalls = 0, totalInput = 0, totalOutput = 0, totalCost = 0
    for (let i = 0; i < targetFilters.length; i++) {
      const f = targetFilters[i]
      await new Promise(r => setTimeout(r, 50))
      try {
        const res = await proxyApi.previewAiTags([], [f.id])
        if (res.success && res.previews?.length > 0) {
          allPreviews.push(...(res.previews as Array<Record<string, unknown>>))
          totalCalls += res.api_calls || 0
          totalInput += res.input_tokens || 0
          totalOutput += res.output_tokens || 0
          totalCost += res.cost_krw || 0
          const firstPreview = res.previews[0] as Record<string, unknown>
          const tags = (firstPreview?.tags as unknown[]) || []
          const seo = (firstPreview?.seo_keywords as string[]) || []
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

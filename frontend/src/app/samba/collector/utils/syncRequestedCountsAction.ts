'use client'

import { collectorApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

interface SyncRequestedCountsArgs {
  selectedIds: Set<string>
  displayedFilters: SambaSearchFilter[]
  load: () => void | Promise<void>
  loadTree: () => void | Promise<void>
}

// 선택된(없으면 전체) 그룹의 requested_count 를 collected_count 로 일괄 동기화
export async function performSyncRequestedCounts(args: SyncRequestedCountsArgs) {
  const { selectedIds, displayedFilters, load, loadTree } = args
  const targets = selectedIds.size > 0
    ? displayedFilters.filter(f => selectedIds.has(f.id))
    : displayedFilters
  if (targets.length === 0) { showAlert('동기화할 그룹이 없습니다'); return }
  const mismatch = targets.filter(f => (f.requested_count || 0) !== ((f as unknown as Record<string, number>).collected_count || 0))
  if (mismatch.length === 0) { showAlert('모든 그룹이 이미 동기화되어 있습니다', 'info'); return }
  if (!await showConfirm(`${fmtNum(mismatch.length)}개 그룹의 요청수를 수집수로 동기화하시겠습니까?`)) return
  let synced = 0
  for (const f of mismatch) {
    try {
      const collected = (f as unknown as Record<string, number>).collected_count || 0
      await collectorApi.updateFilter(f.id, { requested_count: collected })
      synced++
    } catch { /* 개별 실패는 스킵 */ }
  }
  showAlert(`${fmtNum(synced)}개 그룹 동기화 완료`, 'success')
  load(); loadTree()
}

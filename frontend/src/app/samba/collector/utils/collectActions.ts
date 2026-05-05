'use client'

import { MutableRefObject, Dispatch, SetStateAction } from 'react'
import { type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'
import { showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

export interface CollectGroupsArgs {
  drillGroup: string | null
  displayedFilters: SambaSearchFilter[]
  selectedIds: Set<string>
  filters: SambaSearchFilter[]
  checkedOptions: Record<string, boolean>
  collectAbortRef: MutableRefObject<AbortController | null>
  manualCollectRef: MutableRefObject<boolean>
  setCollecting: Dispatch<SetStateAction<boolean>>
  addLog: (msg: string) => void
  load: () => void | Promise<void>
  loadTree: () => void | Promise<void>
}

export async function performCollectGroups(args: CollectGroupsArgs) {
  const {
    drillGroup, displayedFilters, selectedIds, filters, checkedOptions,
    collectAbortRef, manualCollectRef, setCollecting, addLog, load, loadTree,
  } = args
  const targetFilters = drillGroup
    ? displayedFilters.filter(f => f.id === drillGroup)
    : selectedIds.size > 0
      ? displayedFilters.filter(f => selectedIds.has(f.id))
      : displayedFilters
  const sortedTargetFilters = [...targetFilters].sort((a, b) => {
    const remB = (b.requested_count || 0) - ((b as unknown as Record<string, number>).collected_count || 0)
    const remA = (a.requested_count || 0) - ((a as unknown as Record<string, number>).collected_count || 0)
    if (remB !== remA) return remB - remA
    return (b.requested_count || 0) - (a.requested_count || 0)
  })
  const targetIds = sortedTargetFilters.map(f => f.id)
  if (targetIds.length === 0) {
    addLog("수집할 그룹이 없습니다.")
    return
  }
  const totalReq = targetFilters.reduce((s, f) => s + (f.requested_count || 0), 0)
  const label = selectedIds.size > 0 ? '선택된' : drillGroup ? '선택된' : '표시된'
  const _allMusinsa = sortedTargetFilters.every(f => f.source_site === 'MUSINSA')
  const _allABCmart = sortedTargetFilters.every(f => f.source_site === 'ABCmart')
  const _allSSG = sortedTargetFilters.every(f => f.source_site === 'SSG')
  const _allGS = sortedTargetFilters.every(f => f.source_site === 'GSShop')
  const _getBrandKey = (f: SambaSearchFilter) => {
    try {
      const p = new URL(f.keyword || '')
      if (f.source_site === 'MUSINSA') return p.searchParams.get('brand') || ''
      if (f.source_site === 'ABCmart') return p.searchParams.get('searchWord') || ''
      if (f.source_site === 'SSG') return p.searchParams.get('query') || ''
      if (f.source_site === 'GSShop') return p.searchParams.get('tq') || ''
      return ''
    } catch { return '' }
  }
  const _musinsaBrand = _allMusinsa && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
  const _abcBrand = _allABCmart && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
  const _ssgBrand = _allSSG && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
  const _gsBrand = _allGS && sortedTargetFilters.length > 0 ? _getBrandKey(sortedTargetFilters[0]) : ''
  const _brandValue = _musinsaBrand || _abcBrand || _ssgBrand || _gsBrand
  const _brandSite = _allMusinsa ? 'MUSINSA' : _allABCmart ? 'ABCmart' : _allSSG ? 'SSG' : _allGS ? 'GSShop' : ''
  const _totalMusinsaBrandCount = _musinsaBrand ? filters.filter(f => f.source_site === 'MUSINSA' && _getBrandKey(f) === _musinsaBrand).length : 0
  const _totalAbcBrandCount = _abcBrand ? filters.filter(f => f.source_site === 'ABCmart' && _getBrandKey(f) === _abcBrand).length : 0
  const _totalSsgBrandCount = _ssgBrand ? filters.filter(f => f.source_site === 'SSG' && _getBrandKey(f) === _ssgBrand).length : 0
  const _totalGsBrandCount = _gsBrand ? filters.filter(f => f.source_site === 'GSShop' && _getBrandKey(f) === _gsBrand).length : 0
  const _sameBrand = (
    (_musinsaBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalMusinsaBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _musinsaBrand)) ||
    (_abcBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalAbcBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _abcBrand)) ||
    (_ssgBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalSsgBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _ssgBrand)) ||
    (_gsBrand && sortedTargetFilters.length >= 2 && sortedTargetFilters.length === _totalGsBrandCount && sortedTargetFilters.every(f => _getBrandKey(f) === _gsBrand))
  )

  const ok = await showConfirm(
    _sameBrand
      ? `${label} ${fmtNum(targetIds.length)}개 그룹 브랜드 전체수집을 시작하시겠습니까?`
      : `${label} ${fmtNum(targetIds.length)}개 그룹 상품수집을 시작하시겠습니까?\n(요청 ${fmtNum(totalReq)}건, 중복 상품은 자동 스킵)`
  )
  if (!ok) return
  const abort = new AbortController()
  collectAbortRef.current = abort
  manualCollectRef.current = true
  setCollecting(true)

  if (_sameBrand && _brandSite) {
    const _searchKeyword = (() => {
      try {
        const p = new URL(sortedTargetFilters[0].keyword || '')
        if (_brandSite === 'MUSINSA') return p.searchParams.get('keyword') || _brandValue
        if (_brandSite === 'SSG') return p.searchParams.get('query') || _brandValue
        if (_brandSite === 'GSShop') return p.searchParams.get('tq') || _brandValue
        return p.searchParams.get('searchWord') || _brandValue
      } catch { return _brandValue }
    })()
    addLog(`[브랜드전체수집] '${_searchKeyword}' ${fmtNum(targetIds.length)}개 그룹 단일 Job 시작...`)
    try {
      const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/brand-collect-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abort.signal,
        body: JSON.stringify({
          filter_ids: targetIds,
          source_site: _brandSite,
          keyword: _searchKeyword,
          brand: _musinsaBrand,
          gf: (() => { try { return new URL(sortedTargetFilters[0].keyword || '').searchParams.get('gf') || 'A' } catch { return 'A' } })(),
          exclude_preorder: checkedOptions.excludePreorder ?? true,
          exclude_boutique: checkedOptions.excludeBoutique ?? true,
          use_max_discount: checkedOptions.maxDiscount ?? false,
          include_sold_out: checkedOptions.includeSoldOut ?? false,
        }),
      })
      if (!r.ok) {
        addLog(`[브랜드전체수집] 시작 실패: HTTP ${r.status}`)
      } else {
        const { job_id } = await r.json() as { job_id: string }
        addLog(`[브랜드전체수집] Job 생성 완료 — 백그라운드 실행 중 (페이지 이탈해도 계속 수집됩니다)`)
        let _pendingLoggedAt = 0
        let _pollFailCount = 0
        while (!abort.signal.aborted) {
          await new Promise(resolve => setTimeout(resolve, 2000))
          if (abort.signal.aborted) break
          try {
            const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
            if (!jr.ok) break
            _pollFailCount = 0
            const jobData = await jr.json() as { status: string; result?: Record<string, number>; error?: string }
            if (jobData.status === 'pending') {
              const now = Date.now()
              if (now - _pendingLoggedAt > 10000) {
                addLog(`[브랜드전체수집] 대기 중 — 다른 브랜드수집 완료 후 자동 시작...`)
                _pendingLoggedAt = now
              }
              continue
            }
            if (jobData.status === 'completed') {
              addLog(`[브랜드전체수집] 완료 — 저장 ${fmtNum(jobData.result?.saved ?? 0)}건`)
              await load(); await loadTree()
              break
            }
            if (jobData.status === 'failed') {
              addLog(`[브랜드전체수집] 실패: ${jobData.error || '오류'}`)
              await load(); await loadTree()
              break
            }
          } catch {
            _pollFailCount++
            if (_pollFailCount >= 5) {
              addLog(`[브랜드전체수집] 연결이 끊겼습니다. 수집은 백그라운드에서 계속 진행 중이며 새로고침으로 결과를 확인할 수 있습니다.`)
              break
            }
          }
        }
      }
    } catch (e) { addLog(`[브랜드전체수집] 시작 실패: ${(e as Error).message}`) }
  } else {
    addLog(`${fmtNum(targetIds.length)}개 그룹 상품수집 시작...`)
    for (let gi = 0; gi < targetIds.length; gi++) {
      const id = targetIds[gi]
      if (abort.signal.aborted) break
      const f = filters.find((x) => x.id === id)
      if (!f) continue
      const gp = `[${fmtNum(gi + 1)}/${fmtNum(targetIds.length)}]`
      await new Promise(r => setTimeout(r, 100))
      try {
        const res = await fetchWithAuth(
          `${API_BASE}/api/v1/samba/collector/collect-filter/${id}?group_index=${gi + 1}&group_total=${targetIds.length}`,
          { method: 'POST', signal: abort.signal }
        )
        if (!res.ok) {
          const errData = await res.json().catch(() => null)
          addLog(`[${f.name}] 수집 실패: ${errData?.detail || `HTTP ${res.status}`}`)
          continue
        }
        const { job_id } = await res.json() as { job_id: string }
        let lastCurrent = 0
        while (!abort.signal.aborted) {
          await new Promise(r => setTimeout(r, 1000))
          if (abort.signal.aborted) break
          try {
            const jobRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
            if (!jobRes.ok) break
            const job = await jobRes.json() as {
              status: string; current: number; total: number
              progress: number; result?: { saved?: number; skipped?: number; policy?: string; in_stock_count?: number; sold_out_count?: number }
              error?: string
            }
            if (job.current > lastCurrent) { lastCurrent = job.current; load() }
            if (job.status === 'completed') {
              const saved = job.result?.saved ?? 0
              const skipped = job.result?.skipped ?? 0
              const policy = job.result?.policy || ''
              const inStock = job.result?.in_stock_count ?? 0
              const soldOut = job.result?.sold_out_count ?? 0
              const parts = [`신규 ${fmtNum(saved)}건`]
              if (inStock > 0 || soldOut > 0) parts.push(`재고 ${fmtNum(inStock)}건 | 품절 ${fmtNum(soldOut)}건`)
              if (skipped > 0) parts.push(`중복/스킵 ${fmtNum(skipped)}건`)
              if (policy) parts.push(policy)
              break
            }
            if (job.status === 'failed') { addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '알 수 없는 오류'}`); break }
          } catch { /* 재시도 */ }
        }
      } catch (e) { addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`) }
    }
  }

  manualCollectRef.current = false
  setCollecting(false)
  collectAbortRef.current = null
  load(); loadTree()
}

interface StopCollectArgs {
  collectAbortRef: MutableRefObject<AbortController | null>
  addLog: (msg: string) => void
  setCollecting: Dispatch<SetStateAction<boolean>>
}

export async function performStopCollect({ collectAbortRef, addLog, setCollecting }: StopCollectArgs) {
  collectAbortRef.current?.abort()
  addLog('수집 중단 요청...')
  setCollecting(false)
  try {
    await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/cancel-collect`, { method: 'POST' })
  } catch { /* 취소 실패는 무시 */ }
}

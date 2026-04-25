'use client'

import { MutableRefObject, Dispatch, SetStateAction } from 'react'
import { collectorApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

export interface BrandRefreshArgs {
  displayedFilters: SambaSearchFilter[]
  drillBrand: string | null
  drillGroup: string | null
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

export async function performBrandRefresh(args: BrandRefreshArgs) {
  const {
    displayedFilters, drillBrand, drillGroup, selectedIds, filters, checkedOptions,
    collectAbortRef, manualCollectRef, setCollecting, addLog, load, loadTree,
  } = args
  const sampleFilter = displayedFilters[0]
  if (!sampleFilter) { showAlert('표시된 그룹이 없습니다'); return }
  const sourceSite = sampleFilter.source_site || 'MUSINSA'
  const parsed = (() => { try { return new URL(sampleFilter.keyword || '') } catch { return null } })()
  const gf = parsed?.searchParams.get('gf') || 'A'
  let brand = ''
  if (sourceSite === 'MUSINSA') {
    brand = parsed?.searchParams.get('brand') || ''
  } else if (sourceSite === 'Nike') {
    brand = parsed?.searchParams.get('q') || ''
  } else if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') {
    brand = parsed?.searchParams.get('searchWord') || ''
  } else if (sourceSite === 'GSShop') {
    brand = parsed?.searchParams.get('tq') || ''
  } else if (sourceSite === 'LOTTEON') {
    brand = parsed?.searchParams.get('q') || ''
  } else {
    brand = parsed?.searchParams.get('q') || parsed?.searchParams.get('brand') || parsed?.searchParams.get('searchWord') || parsed?.searchParams.get('tq') || ''
  }
  if (!brand) { showAlert(`${sourceSite}에서 브랜드 정보를 찾을 수 없습니다`); return }

  if (!drillBrand) {
    const mixedSite = displayedFilters.some(f => f.source_site !== sourceSite)
    if (mixedSite) {
      showAlert('여러 소싱처가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'error')
      return
    }
    const extractB = (f: SambaSearchFilter) => {
      const p = (() => { try { return new URL(f.keyword || '') } catch { return null } })()
      if (sourceSite === 'MUSINSA') return p?.searchParams.get('brand') || ''
      if (sourceSite === 'Nike') return p?.searchParams.get('q') || ''
      if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') return p?.searchParams.get('searchWord') || ''
      if (sourceSite === 'GSShop') return p?.searchParams.get('tq') || ''
      if (sourceSite === 'LOTTEON') return p?.searchParams.get('q') || ''
      return p?.searchParams.get('q') || p?.searchParams.get('brand') || p?.searchParams.get('searchWord') || p?.searchParams.get('tq') || ''
    }
    const mixedBrand = displayedFilters.some(f => extractB(f) !== brand)
    if (mixedBrand) {
      showAlert('여러 브랜드가 혼재합니다.\n특정 브랜드 행을 클릭(드릴다운)한 후 추가수집을 실행해주세요.', 'error')
      return
    }
  }

  const brandName = drillBrand || brand
  const selectedCategories: string[] = []
  if (drillGroup) {
    const sf = filters.find(f => f.id === drillGroup)
    if (sf) {
      if (sourceSite === 'MUSINSA') {
        const catParam = (() => { try { return new URL(sf.keyword || '').searchParams.get('category') } catch { return null } })()
        if (catParam) selectedCategories.push(catParam)
      } else {
        const cf = (sf as unknown as Record<string, string>).category_filter
        if (cf) selectedCategories.push(cf)
      }
    }
  } else if (selectedIds.size > 0 && selectedIds.size < displayedFilters.length) {
    for (const sf of displayedFilters.filter(f => selectedIds.has(f.id))) {
      if (sourceSite === 'MUSINSA') {
        const catParam = (() => { try { return new URL(sf.keyword || '').searchParams.get('category') } catch { return null } })()
        if (catParam) selectedCategories.push(catParam)
      } else {
        const cf = (sf as unknown as Record<string, string>).category_filter
        if (cf) selectedCategories.push(cf)
      }
    }
  }
  const scopeText = selectedCategories.length > 0
    ? `\n\n대상: 선택 카테고리 ${fmtNum(selectedCategories.length)}개`
    : '\n\n대상: 전체 카테고리'
  const ok = await showConfirm(`${brandName} 추가수집을 실행하시겠습니까?\n\n• 신규 카테고리 → 그룹 자동 생성\n• 기존 카테고리 → 요청수 갱신 후 수집${scopeText}`)
  if (!ok) return
  addLog(`[추가수집] ${brandName} 카테고리 스캔 중...${selectedCategories.length > 0 ? ` (선택 ${fmtNum(selectedCategories.length)}개)` : ''}`)
  try {
    const res = await collectorApi.brandRefresh({ brand, brand_name: brandName, gf, options: checkedOptions, source_site: sourceSite, categories: selectedCategories.length > 0 ? selectedCategories : undefined })
    addLog(`[추가수집] ${res.message}`)
    await load(); await loadTree()
    let updatedFilters: SambaSearchFilter[]
    if (drillGroup) {
      const refreshed = (await collectorApi.listFilters()).find(f => f.id === drillGroup)
      updatedFilters = refreshed ? [refreshed] : []
    } else if (res.filter_ids && res.filter_ids.length > 0) {
      const idSet = new Set(res.filter_ids)
      const allFilters = await collectorApi.listFilters()
      updatedFilters = allFilters.filter(f => idSet.has(f.id))
    } else if (selectedCategories.length > 0) {
      const catSet = new Set(selectedCategories)
      updatedFilters = (await collectorApi.listFilters()).filter(f => {
        if (f.source_site !== sourceSite) return false
        let fCat = ''
        if (sourceSite === 'MUSINSA') {
          try { fCat = new URL(f.keyword || '').searchParams.get('category') || '' } catch { /* */ }
        } else {
          fCat = (f as unknown as Record<string, string>).category_filter || ''
        }
        return fCat !== '' && catSet.has(fCat)
      })
    } else {
      updatedFilters = (await collectorApi.listFilters()).filter(f => {
        if (f.source_site !== sourceSite) return false
        const p = (() => { try { return new URL(f.keyword || '') } catch { return null } })()
        if (sourceSite === 'MUSINSA') return p?.searchParams.get('brand') === brand
        if (sourceSite === 'Nike') return p?.searchParams.get('q') === brand
        if (sourceSite === 'ABCmart' || sourceSite === 'GrandStage') return p?.searchParams.get('searchWord') === brand
        if (sourceSite === 'GSShop') return p?.searchParams.get('tq') === brand
        if (sourceSite === 'LOTTEON') return p?.searchParams.get('q') === brand
        return p?.searchParams.get('q') === brand || p?.searchParams.get('brand') === brand
      })
    }
    if (updatedFilters.length > 0) {
      const collectOk = await showConfirm(`${res.message}\n\n${fmtNum(updatedFilters.length)}개 그룹 상품수집을 시작하시겠습니까?`)
      if (collectOk) {
        const abort = new AbortController()
        collectAbortRef.current = abort
        manualCollectRef.current = true
        setCollecting(true)

        if (sourceSite === 'MUSINSA' || sourceSite === 'ABCmart' || sourceSite === 'SSG' || sourceSite === 'GSShop') {
          let _searchKeyword = brand
          if (updatedFilters.length > 0) {
            try {
              const _p = new URL(updatedFilters[0].keyword || '')
              if (sourceSite === 'MUSINSA') _searchKeyword = _p.searchParams.get('keyword') || brand
              else if (sourceSite === 'SSG') _searchKeyword = _p.searchParams.get('query') || brand
              else if (sourceSite === 'GSShop') _searchKeyword = _p.searchParams.get('tq') || brand
              else _searchKeyword = _p.searchParams.get('searchWord') || brand
            } catch { /* fallback */ }
          }
          addLog(`[브랜드전체수집] '${_searchKeyword}' ${fmtNum(updatedFilters.length)}개 그룹 단일 Job 시작...`)
          try {
            const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/brand-collect-all`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                filter_ids: updatedFilters.map(f => f.id),
                source_site: sourceSite,
                keyword: _searchKeyword,
                brand: brand,
                gf: gf,
                exclude_preorder: checkedOptions.excludePreorder ?? true,
                exclude_boutique: checkedOptions.excludeBoutique ?? true,
                use_max_discount: checkedOptions.maxDiscount ?? false,
                include_sold_out: checkedOptions.includeSoldOut ?? false,
              }),
            })
            if (!r.ok) {
              addLog(`[브랜드전체수집] 시작 실패: HTTP ${r.status}`)
            } else {
              const { job_id } = await r.json()
              addLog(`[브랜드전체수집] Job 생성 완료 — 백그라운드 실행 중 (페이지 이탈해도 계속 수집됩니다)`)
              let _pollFailCount = 0
              while (!abort.signal.aborted) {
                await new Promise(resolve => setTimeout(resolve, 2000))
                if (abort.signal.aborted) break
                try {
                  const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                  if (!jr.ok) break
                  _pollFailCount = 0
                  const jobData = await jr.json() as { status: string; current: number; total: number; result?: Record<string, number>; error?: string }
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
                  if (_pollFailCount >= 3) {
                    addLog('[브랜드전체수집] 서버 응답 없음 — 백그라운드 수집은 계속됩니다')
                    break
                  }
                }
              }
            }
          } catch (e) { addLog(`[브랜드전체수집] 오류: ${(e as Error).message}`) }
        } else {
          updatedFilters = [...updatedFilters].sort((a, b) => {
            const remB = (b.requested_count || 0) - ((b as unknown as Record<string, number>).collected_count || 0)
            const remA = (a.requested_count || 0) - ((a as unknown as Record<string, number>).collected_count || 0)
            if (remB !== remA) return remB - remA
            return (b.requested_count || 0) - (a.requested_count || 0)
          })
          addLog(`${fmtNum(updatedFilters.length)}개 그룹 상품수집 시작...`)
          for (let gi = 0; gi < updatedFilters.length; gi++) {
            const f = updatedFilters[gi]
            if (abort.signal.aborted) break
            const gp = `[${fmtNum(gi + 1)}/${fmtNum(updatedFilters.length)}]`
            try {
              const r = await fetchWithAuth(`${API_BASE}/api/v1/samba/collector/collect-filter/${f.id}?group_index=${gi + 1}&group_total=${updatedFilters.length}`, { method: 'POST' })
              if (!r.ok) { addLog(`[${f.name}] 수집 실패: HTTP ${r.status}`); continue }
              const { job_id } = await r.json()
              while (!abort.signal.aborted) {
                await new Promise(r => setTimeout(r, 1000))
                if (abort.signal.aborted) break
                const jr = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/${job_id}`)
                if (!jr.ok) break
                const job = await jr.json()
                if (job.status === 'completed') break
                if (job.status === 'failed') { addLog(`${gp} [${f.name}] 수집 실패: ${job.error || '오류'}`); break }
              }
            } catch (e) { addLog(`${gp} [${f.name}] 수집 오류: ${(e as Error).message}`) }
          }
        }

        manualCollectRef.current = false
        setCollecting(false)
        load(); loadTree()
      }
    }
  } catch (e) { showAlert(e instanceof Error ? e.message : '수집 실패', 'error') }
}

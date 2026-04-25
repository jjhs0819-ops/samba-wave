'use client'

import { useMemo } from 'react'
import { type SambaSearchFilter } from '@/lib/samba/api/commerce'

// 그룹명에서 브랜드/카테고리 파싱: "MUSINSA_나이키_운동화" → {brand:"나이키", category:"운동화"}
export function parseGroupName(name: string, site: string) {
  let rest = name
  const prefixes = [site + '_', site.toLowerCase() + '_', '무신사_']
  for (const p of prefixes) {
    if (rest.toLowerCase().startsWith(p.toLowerCase())) {
      rest = rest.slice(p.length)
      break
    }
  }
  const singleBrandMap: Record<string, string> = { Nike: '나이키' }
  if (singleBrandMap[site]) {
    return { brand: singleBrandMap[site], category: rest }
  }
  const parts = rest.split('_')
  if (parts.length >= 2) return { brand: parts[0], category: parts.slice(1).join('_') }
  const spaceParts = rest.split(' ')
  if (spaceParts.length >= 2) return { brand: spaceParts[0], category: spaceParts.slice(1).join(' ') }
  return { brand: rest, category: '' }
}

interface Args {
  filters: SambaSearchFilter[]
  tree: SambaSearchFilter[]
  siteFilter: string
  drillSite: string | null
  drillBrand: string | null
  aiFilter: string
  collectFilter: string
  marketRegFilter: string
  tagRegFilter: string
  policyRegFilter: string
  sortBy: string
}

export function useDisplayedFilters(args: Args) {
  const { filters, tree, siteFilter, drillSite, drillBrand, aiFilter, collectFilter, marketRegFilter, tagRegFilter, policyRegFilter, sortBy } = args

  return useMemo(() => {
    let result = [...filters]
    if (siteFilter) result = result.filter((f) => f.source_site === siteFilter)
    if (drillSite) {
      const drillSiteName = tree.find(s => s.id === drillSite)?.source_site
      if (drillSiteName) result = result.filter(f => f.source_site === drillSiteName)
    }
    if (drillBrand) {
      result = result.filter(f => {
        const parsed = parseGroupName(f.name, f.source_site || '')
        return parsed.brand === drillBrand
      })
    }
    if (aiFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const aiTagCount = r.ai_tagged_count ?? 0
        const aiImgCount = r.ai_image_count ?? 0
        switch (aiFilter) {
          case 'ai_tag_yes': return aiTagCount > 0
          case 'ai_tag_no': return aiTagCount === 0
          case 'ai_img_yes': return aiImgCount > 0
          case 'ai_img_no': return aiImgCount === 0
          default: return true
        }
      })
    }
    if (collectFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.collected_count ?? 0
        if (collectFilter === 'collected') return cnt > 0
        if (collectFilter === 'uncollected') return cnt === 0
        return true
      })
    }
    if (marketRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.market_registered_count ?? 0
        const total = r.collected_count ?? 0
        if (marketRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (marketRegFilter === 'partial') return cnt > 0 && cnt < total
        if (marketRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    if (tagRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.ai_tagged_count ?? 0
        const total = r.collected_count ?? 0
        if (tagRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (tagRegFilter === 'partial') return cnt > 0 && cnt < total
        if (tagRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    if (policyRegFilter) {
      result = result.filter((f) => {
        const r = f as unknown as Record<string, number>
        const cnt = r.policy_applied_count ?? 0
        const total = r.collected_count ?? 0
        if (policyRegFilter === 'registered') return cnt > 0 && cnt >= total
        if (policyRegFilter === 'partial') return cnt > 0 && cnt < total
        if (policyRegFilter === 'unregistered') return cnt === 0
        return true
      })
    }
    const [sortField, sortDir] = sortBy.split('_')
    result.sort((a, b) => {
      const va = sortField === 'lastCollectedAt' ? (a.last_collected_at || '') : (a.created_at || '')
      const vb = sortField === 'lastCollectedAt' ? (b.last_collected_at || '') : (b.created_at || '')
      return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
    })
    return result
  }, [filters, siteFilter, drillSite, tree, drillBrand, aiFilter, collectFilter, marketRegFilter, tagRegFilter, policyRegFilter, sortBy])
}

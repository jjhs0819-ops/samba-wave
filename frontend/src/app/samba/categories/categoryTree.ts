import type { CatLevel } from './types'

// API 응답 → 카테고리 트리 + 사이트 목록
export function buildCategoryTree(
  rows: { source_site: string; category: string; count: number }[],
): { tree: Record<string, CatLevel>; sites: string[] } {
  const tree: Record<string, CatLevel> = {}
  const siteSet = new Set<string>()

  rows.forEach(({ source_site, category }) => {
    const site = source_site || '기타'
    siteSet.add(site)
    if (!tree[site]) tree[site] = { name: site, children: {}, products: [] }

    const cats = category ? category.split('>').map(c => c.trim()).filter(Boolean) : []
    let current = tree[site]
    cats.forEach(cat => {
      if (!current.children[cat]) {
        current.children[cat] = { name: cat, children: {}, products: [] }
      }
      current = current.children[cat]
    })
  })

  return { tree, sites: Array.from(siteSet).sort() }
}

// 카테고리 단계별 자식 목록 조회
export function getCatList(
  tree: Record<string, CatLevel>,
  site: string | null,
  cat1: string | null,
  cat2: string | null,
  cat3: string | null,
  level: 1 | 2 | 3 | 4,
): string[] {
  if (!site || !tree[site]) return []
  if (level === 1) return Object.keys(tree[site].children).sort()

  if (!cat1 || !tree[site].children[cat1]) return []
  if (level === 2) return Object.keys(tree[site].children[cat1].children).sort()

  if (!cat2 || !tree[site].children[cat1].children[cat2]) return []
  if (level === 3) return Object.keys(tree[site].children[cat1].children[cat2].children).sort()

  if (!cat3 || !tree[site].children[cat1].children[cat2].children[cat3]) return []
  return Object.keys(tree[site].children[cat1].children[cat2].children[cat3].children).sort()
}

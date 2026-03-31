'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { collectorApi, categoryApi, accountApi, type SambaCollectedProduct } from '@/lib/samba/api'
import { MARKET_LABELS } from '@/lib/samba/markets'
import { showAlert } from '@/components/samba/Modal'
import { card } from '@/lib/samba/styles'

// 카테고리 계층 구조 타입
interface CatLevel {
  name: string
  children: Record<string, CatLevel>
  products: SambaCollectedProduct[]
}

// 매핑 현황 행 타입
interface MappingRow {
  id: string
  source_site: string
  source_category: string
  target_mappings: Record<string, string>
}

// MARKET_LABELS는 @/lib/samba/markets에서 import

// AI 매핑 비용 추정 근거:
// Claude Sonnet 4 ($3/M input, $15/M output, 환율 ₩1,450)
// 1회 호출: ~1,500 input tokens × $3/M = $0.0045 = ₩6.5
//         + ~300 output tokens × $15/M = $0.0045 = ₩6.5
// 합계: ~₩13, 여유분 포함 ₩15
const COST_PER_CALL_KRW = 15
const COST_BASIS = 'Sonnet4 $3/M in + $15/M out × ₩1,450'

export default function CategoriesPage() {
  useEffect(() => { document.title = 'SAMBA-카테고리' }, [])
  const router = useRouter()
  const [products, setProducts] = useState<SambaCollectedProduct[]>([])
  const [loading, setLoading] = useState(true)

  // 사이트 목록
  const [sites, setSites] = useState<string[]>([])
  // 카테고리 트리 (사이트별)
  const [catTree, setCatTree] = useState<Record<string, CatLevel>>({})

  // 5단 드릴다운 선택 상태
  const [selectedSite, setSelectedSite] = useState<string | null>(null)
  const [selectedCat1, setSelectedCat1] = useState<string | null>(null)
  const [selectedCat2, setSelectedCat2] = useState<string | null>(null)
  const [selectedCat3, setSelectedCat3] = useState<string | null>(null)
  const [selectedCat4, setSelectedCat4] = useState<string | null>(null)
  const [catEntry, setCatEntry] = useState<number>(0) // 진입점 레벨 (0=사이트, 1=대분류, ...)

  // 선택된 카테고리의 상품들
  const [selectedProducts, setSelectedProducts] = useState<SambaCollectedProduct[]>([])
  const [selectedPath, setSelectedPath] = useState('')

  // AI 매핑 모달 상태
  const [aiModalOpen, setAiModalOpen] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiResult, setAiResult] = useState<Record<string, string>>({})
  const [aiEdits, setAiEdits] = useState<Record<string, string>>({})
  // 벌크 매핑 결과
  const [bulkResult, setBulkResult] = useState<{ mapped: number; updated: number; skipped: number; errors: string[] } | null>(null)

  // 매핑 현황
  const [mappings, setMappings] = useState<MappingRow[]>([])
  // 인라인 편집 상태: { mappingId, market }
  const [editingCell, setEditingCell] = useState<{ id: string; market: string } | null>(null)
  const [editingValue, setEditingValue] = useState('')
  // 카테고리 검색 드롭다운
  const [suggestions, setSuggestions] = useState<string[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 마켓별 카테고리 수
  const [marketCatCounts, setMarketCatCounts] = useState<Record<string, number>>({})
  // 마켓별 AI 리매핑 로딩 상태
  const [marketAiLoading, setMarketAiLoading] = useState<string | null>(null)
  // 마켓별 AI 진행 모달
  const [marketAiProgress, setMarketAiProgress] = useState<{ market: string; current: number; total: number; success: number; fail: number } | null>(null)
  // 카테고리 동기화
  const [seedLoading, setSeedLoading] = useState(false)
  const [syncModalOpen, setSyncModalOpen] = useState(false)
  const [syncSelected, setSyncSelected] = useState<Record<string, boolean>>({})
  const [syncProgress, setSyncProgress] = useState<Record<string, { status: string; count?: number; error?: string }>>({})
  // 최근 AI 사용량 기록
  const [lastAiUsage, setLastAiUsage] = useState<{ calls: number; tokens: number; cost: number; date: string } | null>(null)
  // 활성 계정 마켓 목록 (벌크 매핑 마켓 선택용)
  const [activeMarketTypes, setActiveMarketTypes] = useState<string[]>([])
  // 벌크 매핑 마켓 선택
  const [bulkSelectedMarkets, setBulkSelectedMarkets] = useState<Record<string, boolean>>({})
  // 수동 매핑 자동저장 디바운스
  const autoSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const all = await collectorApi.listProducts(0, 100000)
      if (Array.isArray(all) && all.length > 0) {
        setProducts(all)
        buildTree(all)
      } else {
        setProducts([])
        setSites([])
      }
    } catch (e) {
      console.error('[카테고리] 상품 로드 실패:', e)
    }
    // 매핑 현황 로드
    try {
      const list = await categoryApi.listMappings()
      setMappings(Array.isArray(list) ? (list as MappingRow[]) : [])
    } catch (e) {
      console.error('[카테고리] 매핑 로드 실패:', e)
    }
    // 활성 계정 마켓 로드
    try {
      const accounts = await accountApi.listActive()
      if (Array.isArray(accounts)) {
        const types = [...new Set(accounts.map(a => a.market_type))]
        setActiveMarketTypes(types)
        const initial: Record<string, boolean> = {}
        types.forEach(t => { initial[t] = true })
        setBulkSelectedMarkets(initial)
      }
    } catch (e) {
      console.error('[카테고리] 활성 계정 로드 실패:', e)
    }
    // 마켓별 카테고리 수 로드
    try {
      const counts = await categoryApi.getMarketCategoryCounts()
      setMarketCatCounts(counts)
    } catch { /* 무시 */ }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const buildTree = (prods: SambaCollectedProduct[]) => {
    const tree: Record<string, CatLevel> = {}
    const siteSet = new Set<string>()

    prods.forEach(p => {
      const site = p.source_site || '기타'
      siteSet.add(site)

      if (!tree[site]) tree[site] = { name: site, children: {}, products: [] }

      const cats = [p.category1, p.category2, p.category3, p.category4].filter(Boolean) as string[]
      if (cats.length === 0 && p.category) {
        cats.push(...p.category.split('>').map(c => c.trim()).filter(Boolean))
      }

      let current = tree[site]
      cats.forEach((cat, idx) => {
        if (!current.children[cat]) {
          current.children[cat] = { name: cat, children: {}, products: [] }
        }
        if (idx === cats.length - 1) {
          current.children[cat].products.push(p)
        }
        current = current.children[cat]
      })

      // 카테고리 없는 상품은 사이트 루트에
      if (cats.length === 0) {
        tree[site].products.push(p)
      }
    })

    setCatTree(tree)
    setSites(Array.from(siteSet).sort())
  }

  const handleSiteClick = (site: string) => {
    setSelectedSite(selectedSite === site ? null : site)
    // 하위 선택 초기화
    setSelectedCat1(null); setSelectedCat2(null); setSelectedCat3(null); setSelectedCat4(null)
    setSelectedProducts([]); setSelectedPath('')
  }

  const handleCat1Click = (cat: string) => {
    setSelectedCat1(selectedCat1 === cat ? null : cat)
    // 하위 선택 초기화
    setSelectedCat2(null); setSelectedCat3(null); setSelectedCat4(null)
    setSelectedProducts([]); setSelectedPath('')
  }

  const handleCat2Click = (cat: string) => {
    setSelectedCat2(selectedCat2 === cat ? null : cat)
    // 하위 선택 초기화
    setSelectedCat3(null); setSelectedCat4(null)
    setSelectedProducts([]); setSelectedPath('')
  }

  const handleCat3Click = (cat: string) => {
    setSelectedCat3(selectedCat3 === cat ? null : cat)
    // 하위 선택 초기화
    setSelectedCat4(null)
    setSelectedProducts([]); setSelectedPath('')
  }

  const handleCat4Click = (cat: string) => {
    setSelectedCat4(selectedCat4 === cat ? null : cat)
    setSelectedProducts([]); setSelectedPath('')
  }

  // 크로스 필터: 지정 레벨 제외한 나머지 필터 적용
  const getCrossFiltered = useCallback((excludeLevel: string) => {
    let filtered = products
    if (excludeLevel !== 'site' && selectedSite) filtered = filtered.filter(p => (p.source_site || '기타') === selectedSite)
    if (excludeLevel !== 'cat1' && selectedCat1) filtered = filtered.filter(p => p.category1 === selectedCat1)
    if (excludeLevel !== 'cat2' && selectedCat2) filtered = filtered.filter(p => p.category2 === selectedCat2)
    if (excludeLevel !== 'cat3' && selectedCat3) filtered = filtered.filter(p => p.category3 === selectedCat3)
    if (excludeLevel !== 'cat4' && selectedCat4) filtered = filtered.filter(p => p.category4 === selectedCat4)
    return filtered
  }, [products, selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4])

  // 선택 변경 시 상품 목록 자동 업데이트
  useEffect(() => {
    if (!selectedSite && !selectedCat1 && !selectedCat2 && !selectedCat3 && !selectedCat4) {
      setSelectedProducts([]); setSelectedPath('')
      return
    }
    const filtered = getCrossFiltered('none')
    const path = [selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4].filter(Boolean)
    setSelectedProducts(filtered)
    setSelectedPath(path.join(' > '))
  }, [selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4, getCrossFiltered])

  // ── AI 카테고리 매핑 ──

  const getSourceCategory = () => {
    const parts = [selectedCat1, selectedCat2, selectedCat3, selectedCat4].filter(Boolean)
    return parts.join(' > ')
  }

  // AI 매핑 — 마켓 선택 단계
  const [aiMarketSelectOpen, setAiMarketSelectOpen] = useState(false)
  const [aiSelectedMarkets, setAiSelectedMarkets] = useState<Record<string, boolean>>({})

  // 수동 매핑
  const [manualModalOpen, setManualModalOpen] = useState(false)
  const [manualEdits, setManualEdits] = useState<Record<string, string>>({})

  // 인라인 카테고리 검색 자동완성
  const [inlineFocusedMarket, setInlineFocusedMarket] = useState<string | null>(null)
  const [inlineSuggestions, setInlineSuggestions] = useState<string[]>([])
  const inlineDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const handleOpenAiMarketSelect = () => {
    if (!selectedSite || !selectedCat1) {
      // 벌크 모드 — 계정 연결된 마켓 선택 단계
      if (activeMarketTypes.length === 0) {
        showAlert('활성 마켓 계정이 없습니다. 마켓계정 페이지에서 계정을 등록해주세요.', 'info')
        return
      }
      const initial: Record<string, boolean> = {}
      activeMarketTypes.forEach(t => { initial[t] = true })
      setBulkSelectedMarkets(initial)
      setAiMarketSelectOpen(true)
      return
    }
    // 단건 모드 — 마켓 선택 단계
    const initial: Record<string, boolean> = {}
    marketKeys.forEach(mk => { initial[mk] = true })
    setAiSelectedMarkets(initial)
    setAiMarketSelectOpen(true)
  }

  const handleAiMarketSelectAll = (checked: boolean) => {
    const updated: Record<string, boolean> = {}
    marketKeys.forEach(mk => { updated[mk] = checked })
    setAiSelectedMarkets(updated)
  }

  const handleAiMarketConfirm = () => {
    if (!selectedSite || !selectedCat1) {
      // 벌크 모드
      const selected = activeMarketTypes.filter(t => bulkSelectedMarkets[t])
      if (selected.length === 0) {
        showAlert('최소 1개 마켓을 선택해주세요', 'info')
        return
      }
      setAiMarketSelectOpen(false)
      handleAiMapping(selected)
    } else {
      // 단건 모드
      const selected = marketKeys.filter(mk => aiSelectedMarkets[mk])
      if (selected.length === 0) {
        showAlert('최소 1개 마켓을 선택해주세요', 'info')
        return
      }
      setAiMarketSelectOpen(false)
      handleAiMapping(selected)
    }
  }

  const handleAiMapping = async (targetMarkets?: string[]) => {
    setAiLoading(true)
    setAiModalOpen(true)
    setAiResult({})
    setAiEdits({})
    setBulkResult(null)

    if (selectedSite && selectedCat1) {
      // 선택된 사이트+카테고리 범위의 하위 전체를 벌크 매핑 (1회 API 호출)
      const categoryPrefix = getSourceCategory()
      try {
        const result = await categoryApi.aiSuggestBulk(targetMarkets, selectedSite, categoryPrefix)
        setBulkResult(result)
        const totalCalls = result.mapped + result.updated
        setLastAiUsage({ calls: totalCalls, tokens: totalCalls * 1800, cost: totalCalls * COST_PER_CALL_KRW, date: new Date().toLocaleTimeString() })
        // 매핑 현황 새로고침
        if (totalCalls > 0) {
          const refreshed = await categoryApi.listMappings() as MappingRow[]
          setMappings(refreshed)
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : '알 수 없는 오류'
        showAlert(`AI 매핑 실패: ${msg}`, 'error')
        setAiModalOpen(false)
      } finally {
        setAiLoading(false)
      }
    } else {
      // 벌크 모드: 선택된 마켓만 미매핑 자동 매핑
      try {
        const result = await categoryApi.aiSuggestBulk(targetMarkets)
        setBulkResult(result)
        const totalCalls = result.mapped + result.updated
        setLastAiUsage({ calls: totalCalls, tokens: totalCalls * 1800, cost: totalCalls * COST_PER_CALL_KRW, date: new Date().toLocaleTimeString() })
      } catch (e) {
        const msg = e instanceof Error ? e.message : '알 수 없는 오류'
        showAlert(`벌크 매핑 실패: ${msg}`, 'error')
        setAiModalOpen(false)
      } finally {
        setAiLoading(false)
      }
    }
  }

  // ── 수동 매핑 ──

  const handleOpenManualMapping = () => {
    if (!selectedSite || !selectedCat1) {
      showAlert('사이트와 카테고리를 먼저 선택해주세요', 'info')
      return
    }
    setManualEdits({})
    setManualModalOpen(true)
  }

  const handleManualSave = async () => {
    if (!selectedSite) return
    const sourceCategory = getSourceCategory()
    const targetMappings: Record<string, string> = {}
    Object.entries(manualEdits).forEach(([market, cat]) => {
      if (cat.trim()) targetMappings[market] = cat.trim()
    })
    if (Object.keys(targetMappings).length === 0) {
      showAlert('최소 1개 마켓의 카테고리를 입력해주세요', 'info')
      return
    }
    try {
      await categoryApi.createMapping({
        source_site: selectedSite,
        source_category: sourceCategory,
        target_mappings: targetMappings,
      })
      showAlert(`${Object.keys(targetMappings).length}개 마켓에 카테고리 매핑 저장 완료`, 'success')
      setManualModalOpen(false)
      load()
    } catch (e) {
      const msg = e instanceof Error ? e.message : '저장 실패'
      showAlert(`매핑 저장 실패: ${msg}`, 'error')
    }
  }

  const handleAiSave = async () => {
    if (!selectedSite) return

    const sourceCategory = getSourceCategory()
    // 빈 값 제거
    const targetMappings: Record<string, string> = {}
    Object.entries(aiEdits).forEach(([market, cat]) => {
      if (cat) targetMappings[market] = cat
    })

    if (Object.keys(targetMappings).length === 0) {
      showAlert('매핑할 카테고리가 없습니다', 'info')
      return
    }

    try {
      await categoryApi.createMapping({
        source_site: selectedSite,
        source_category: sourceCategory,
        target_mappings: targetMappings,
      })
      showAlert(`${Object.keys(targetMappings).length}개 마켓에 카테고리 매핑 저장 완료`, 'success')
      setAiModalOpen(false)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '저장 실패'
      showAlert(`매핑 저장 실패: ${msg}`, 'error')
    }
  }

  // 5단 드릴다운 데이터 (크로스 필터: 각 레벨은 자신을 제외한 필터 적용)
  const getCrossSites = () => [...new Set(getCrossFiltered('site').map(p => p.source_site || '기타'))].sort()
  const getCat1List = () => [...new Set(getCrossFiltered('cat1').map(p => p.category1).filter(Boolean) as string[])].sort()
  const getCat2List = () => [...new Set(getCrossFiltered('cat2').map(p => p.category2).filter(Boolean) as string[])].sort()
  const getCat3List = () => [...new Set(getCrossFiltered('cat3').map(p => p.category3).filter(Boolean) as string[])].sort()
  const getCat4List = () => [...new Set(getCrossFiltered('cat4').map(p => p.category4).filter(Boolean) as string[])].sort()

  // ── 최하단 카테고리 감지 (하위 자식이 없는 노드) ──

  const isLeafCategory = useMemo(() => {
    if (!selectedCat1) return false
    if (selectedCat4) return true
    if (selectedCat3 && getCat4List().length === 0) return true
    if (selectedCat2 && getCat3List().length === 0) return true
    if (selectedCat1 && getCat2List().length === 0) return true
    return false
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4, catTree, products])

  // 최하단 선택 시 기존 매핑값으로 manualEdits 초기화
  useEffect(() => {
    if (!isLeafCategory || !selectedSite) return
    const sourceCategory = [selectedCat1, selectedCat2, selectedCat3, selectedCat4].filter(Boolean).join(' > ')
    const existing = mappings.find(m => m.source_site === selectedSite && m.source_category === sourceCategory)
    if (existing) {
      setManualEdits({ ...existing.target_mappings })
    } else {
      setManualEdits({})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLeafCategory, selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4])

  // 수동 매핑 자동저장: manualEdits 변경 시 1.5초 디바운스
  useEffect(() => {
    if (!isLeafCategory || !selectedSite || !selectedCat1) return
    const hasValues = Object.values(manualEdits).some(v => v.trim())
    if (!hasValues) return

    if (autoSaveRef.current) clearTimeout(autoSaveRef.current)
    autoSaveRef.current = setTimeout(async () => {
      const sourceCategory = [selectedCat1, selectedCat2, selectedCat3, selectedCat4].filter(Boolean).join(' > ')
      const targetMappings: Record<string, string> = {}
      Object.entries(manualEdits).forEach(([market, cat]) => {
        if (cat.trim()) targetMappings[market] = cat.trim()
      })
      if (Object.keys(targetMappings).length === 0) return

      try {
        const existing = mappings.find(m => m.source_site === selectedSite && m.source_category === sourceCategory)
        if (existing) {
          await categoryApi.updateMapping(existing.id, { target_mappings: targetMappings })
          setMappings(prev => prev.map(m => m.id === existing.id ? { ...m, target_mappings: targetMappings } : m))
        } else {
          await categoryApi.createMapping({
            source_site: selectedSite,
            source_category: sourceCategory,
            target_mappings: targetMappings,
          })
          load()
        }
      } catch (e) {
        console.error('[카테고리] 자동 저장 실패:', e)
      }
    }, 1500)

    return () => {
      if (autoSaveRef.current) clearTimeout(autoSaveRef.current)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manualEdits])

  // ── 미매핑 카테고리 수 + 비용 추정 ──

  const unmappedCount = useMemo(() => {
    const uniqueCats = new Set<string>()
    products.forEach(p => {
      const site = p.source_site || ''
      if (!site) return
      const cats = [p.category1, p.category2, p.category3, p.category4].filter(Boolean) as string[]
      if (cats.length === 0 && p.category) {
        cats.push(...p.category.split('>').map(c => c.trim()).filter(Boolean))
      }
      if (cats.length > 0) uniqueCats.add(`${site}::${cats.join(' > ')}`)
    })
    const mappedKeys = new Set(mappings.map(m => `${m.source_site}::${m.source_category}`))
    let count = 0
    uniqueCats.forEach(k => { if (!mappedKeys.has(k)) count++ })
    return count
  }, [products, mappings])

  const costEstimate = useMemo(() => {
    if (selectedSite && selectedCat1) {
      return { calls: 1, tokens: '~1,500 in + ~300 out', cost: COST_PER_CALL_KRW }
    }
    const calls = Math.max(unmappedCount, 1)
    return { calls, tokens: `~${(calls * 1500).toLocaleString()} in + ~${(calls * 300).toLocaleString()} out`, cost: calls * COST_PER_CALL_KRW }
  }, [selectedSite, selectedCat1, unmappedCount])

  // ── 매핑 현황 필터링 (드릴다운 선택에 연동) ──

  const filteredMappings = useMemo(() => {
    // 수집 상품에서 고유 (site, leaf_category) 추출
    const productCats = new Map<string, { site: string; category: string }>()
    products.forEach(p => {
      const site = p.source_site || ''
      if (!site) return
      // DB의 category 컬럼을 직접 사용 (category1~4 조합과 불일치 방지)
      const leafPath = p.category?.trim()
        || [p.category1, p.category2, p.category3, p.category4].filter(Boolean).join(' > ')
      if (!leafPath) return
      const key = `${site}::${leafPath}`
      if (!productCats.has(key)) {
        productCats.set(key, { site, category: leafPath })
      }
    })

    // DB 매핑을 키 맵으로 변환
    const mappingMap = new Map<string, MappingRow>()
    mappings.forEach(m => {
      mappingMap.set(`${m.source_site}::${m.source_category}`, m)
    })

    // 수집 상품 카테고리 + DB 매핑 병합
    const merged: MappingRow[] = []
    const seen = new Set<string>()

    // 수집 상품 카테고리 기준으로 먼저 추가 (매핑 유무 관계없이)
    productCats.forEach(({ site, category }, key) => {
      seen.add(key)
      const existing = mappingMap.get(key)
      if (existing) {
        merged.push(existing)
      } else {
        // 미매핑 카테고리 — 빈 행으로 추가
        merged.push({
          id: `unmapped_${key}`,
          source_site: site,
          source_category: category,
          target_mappings: {},
        })
      }
    })

    // DB에만 있고 상품이 없는 매핑도 추가 (과거 상품 삭제된 경우)
    mappings.forEach(m => {
      const key = `${m.source_site}::${m.source_category}`
      if (!seen.has(key)) {
        seen.add(key)
        merged.push(m)
      }
    })

    // 필터 적용
    let result = merged
    if (selectedSite) {
      result = result.filter(m => m.source_site === selectedSite)
    }
    const catPath = [selectedCat1, selectedCat2, selectedCat3, selectedCat4].filter(Boolean).join(' > ')
    if (catPath) {
      result = result.filter(m => m.source_category.startsWith(catPath))
    }
    return result.slice().sort((a, b) =>
      a.source_site.localeCompare(b.source_site) || a.source_category.localeCompare(b.source_category)
    )
  }, [mappings, products, selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4])

  // ── 매핑 현황 핸들러 ──

  const handleDeleteMapping = async (id: string) => {
    try {
      await categoryApi.deleteMapping(id)
      setMappings(prev => prev.filter(m => m.id !== id))
      showAlert('매핑이 삭제되었습니다', 'success')
    } catch (e) {
      const msg = e instanceof Error ? e.message : '삭제 실패'
      showAlert(`매핑 삭제 실패: ${msg}`, 'error')
    }
  }

  // 드롭다운 위치 (fixed 포지셔닝용)
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null)

  const handleStartEdit = (id: string, market: string, currentValue: string) => {
    setEditingCell({ id, market })
    setEditingValue(currentValue || '')
    setSuggestions([])
  }

  const updateDropdownPos = (input: HTMLInputElement) => {
    const rect = input.getBoundingClientRect()
    setDropdownPos({ top: rect.bottom + 2, left: rect.left, width: rect.width })
  }

  const handleSuggestSearch = (value: string, market: string, inputEl?: HTMLInputElement) => {
    setEditingValue(value)
    if (inputEl) updateDropdownPos(inputEl)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!value.trim()) { setSuggestions([]); return }
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await categoryApi.suggest(value, market)
        setSuggestions(Array.isArray(results) ? results : [])
      } catch {
        setSuggestions([])
      }
    }, 300)
  }

  // 미매핑 행에서 편집된 매핑 찾기 (unmapped_ ID → filteredMappings에서 조회)
  const findMappingRow = (id: string): MappingRow | undefined => {
    if (id.startsWith('unmapped_')) {
      return filteredMappings.find(m => m.id === id)
    }
    return mappings.find(m => m.id === id)
  }

  // 미매핑 행 → 새 매핑 생성
  const createMappingForUnmapped = async (row: MappingRow, market: string, value: string) => {
    const targets = { [market]: value }
    try {
      const created = await categoryApi.createMapping({
        source_site: row.source_site,
        source_category: row.source_category,
        target_mappings: targets,
      })
      if (created && typeof created === 'object' && 'id' in created) {
        setMappings(prev => [...prev, created as MappingRow])
      } else {
        await load()
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '생성 실패'
      showAlert(`매핑 생성 실패: ${msg}`, 'error')
    }
  }

  const handleSelectSuggestion = async (cat: string) => {
    if (!editingCell) return
    const { id, market } = editingCell
    const row = findMappingRow(id)
    if (!row) return

    if (id.startsWith('unmapped_')) {
      await createMappingForUnmapped(row, market, cat)
    } else {
      const updatedTargets = { ...row.target_mappings, [market]: cat }
      try {
        await categoryApi.updateMapping(id, { target_mappings: updatedTargets })
        setMappings(prev => prev.map(m => m.id === id ? { ...m, target_mappings: updatedTargets } : m))
      } catch (e) {
        const msg = e instanceof Error ? e.message : '수정 실패'
        showAlert(`매핑 수정 실패: ${msg}`, 'error')
      }
    }
    setEditingCell(null)
    setEditingValue('')
    setSuggestions([])
  }

  const handleSaveEdit = async () => {
    if (!editingCell) return
    const { id, market } = editingCell
    const row = findMappingRow(id)
    if (!row) return

    if (id.startsWith('unmapped_')) {
      if (editingValue.trim()) {
        await createMappingForUnmapped(row, market, editingValue.trim())
      }
    } else {
      const updatedTargets = { ...row.target_mappings }
      if (editingValue.trim()) {
        updatedTargets[market] = editingValue.trim()
      } else {
        delete updatedTargets[market]
      }
      try {
        await categoryApi.updateMapping(id, { target_mappings: updatedTargets })
        setMappings(prev => prev.map(m => m.id === id ? { ...m, target_mappings: updatedTargets } : m))
      } catch (e) {
        const msg = e instanceof Error ? e.message : '수정 실패'
        showAlert(`매핑 수정 실패: ${msg}`, 'error')
      }
    }
    setEditingCell(null)
    setEditingValue('')
    setSuggestions([])
  }

  const handleEditKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSaveEdit()
    if (e.key === 'Escape') { setEditingCell(null); setEditingValue(''); setSuggestions([]) }
  }

  // ── 매핑 일괄 삭제 ──

  const handleBulkDelete = async () => {
    if (filteredMappings.length === 0) {
      showAlert('삭제할 매핑이 없습니다', 'info')
      return
    }
    const ids = filteredMappings.map(m => m.id)
    try {
      // 등록 상품이 없는 매핑만 필터
      const check = await categoryApi.checkRegisteredPerMapping(ids)
      const deletableIds = ids.filter(id => !check.registered_ids?.includes(id))
      const blockedCount = ids.length - deletableIds.length

      if (deletableIds.length === 0) {
        showAlert(`전체 ${ids.length}건 모두 등록 상품이 있어 삭제할 수 없습니다`, 'error')
        return
      }

      // 등록 상품 없는 것만 삭제
      const result = await categoryApi.bulkDeleteMappings(deletableIds)
      setMappings(prev => prev.filter(m => !deletableIds.includes(m.id)))
      const msg = blockedCount > 0
        ? `${result.deleted}건 삭제 완료 (등록 상품 있는 ${blockedCount}건은 유지)`
        : `${result.deleted}건 매핑 삭제 완료`
      showAlert(msg, 'success')
    } catch (e) {
      const msg = e instanceof Error ? e.message : '삭제 실패'
      showAlert(`매핑 삭제 실패: ${msg}`, 'error')
    }
  }

  // ── 마켓 컬럼 삭제 (해당 마켓의 카테고리만 제거) ──

  const handleMarketColumnDelete = async (market: string) => {
    if (filteredMappings.length === 0) {
      showAlert('삭제할 매핑이 없습니다', 'info')
      return
    }
    const ids = filteredMappings.map(m => m.id)
    try {
      // 해당 마켓에 등록된 상품 확인
      const res = await categoryApi.checkMarketRegistered(market, ids)
      if (res.registered_count > 0) {
        showAlert(`${MARKET_LABELS[market]}에 등록된 상품이 ${res.registered_count}건 있어 삭제할 수 없습니다`, 'error')
        return
      }
      const result = await categoryApi.clearMarketColumn(market, ids)
      // 로컬 state 갱신
      setMappings(prev => prev.map(m => {
        if (ids.includes(m.id) && m.target_mappings?.[market]) {
          const updated = { ...m.target_mappings }
          delete updated[market]
          return { ...m, target_mappings: updated }
        }
        return m
      }))
      showAlert(`${MARKET_LABELS[market]} 카테고리 ${result.cleared}건 삭제 완료`, 'success')
    } catch (e) {
      const msg = e instanceof Error ? e.message : '삭제 실패'
      showAlert(`매핑 삭제 실패: ${msg}`, 'error')
    }
  }

  // ── 마켓별 AI 리매핑 (현재 보이는 매핑만 대상) ──

  const handleMarketAiRemap = async (market: string) => {
    if (filteredMappings.length === 0) {
      showAlert('리매핑할 매핑 데이터가 없습니다', 'info')
      return
    }
    // 이미 해당 마켓 매핑이 있는 행은 제외
    const needMapping = filteredMappings.filter(row => {
      const existing = row.target_mappings?.[market]
      return !existing || existing === ''
    })
    if (needMapping.length === 0) {
      showAlert(`${MARKET_LABELS[market]} 매핑이 모두 완료되어 있습니다`, 'info')
      return
    }
    const skippedCount = filteredMappings.length - needMapping.length
    setMarketAiLoading(market)
    const total = needMapping.length
    setMarketAiProgress({ market, current: 0, total, success: 0, fail: 0 })

    let successCount = 0
    let errorCount = 0
    const updatedMappings = [...mappings]

    for (let i = 0; i < needMapping.length; i++) {
      const row = needMapping[i]
      setMarketAiProgress({ market, current: i + 1, total, success: successCount, fail: errorCount })

      const rowProducts = products.filter(p =>
        p.source_site === row.source_site &&
        [p.category1, p.category2, p.category3, p.category4]
          .filter(Boolean).join(' > ') === row.source_category
      )
      const sampleNames = rowProducts.slice(0, 5).map(p => p.name)
      const sampleTags = (rowProducts[0]?.tags || []).filter((t: string) => !t.startsWith('__')).slice(0, 10)

      try {
        const result = await categoryApi.aiSuggest({
          source_site: row.source_site,
          source_category: row.source_category,
          sample_products: sampleNames,
          sample_tags: sampleTags,
          target_markets: [market],
        })
        const newCat = result[market]
        if (newCat) {
          if (row.id.startsWith('unmapped_')) {
            const created = await categoryApi.createMapping({
              source_site: row.source_site,
              source_category: row.source_category,
              target_mappings: { [market]: newCat },
            })
            if (created && typeof created === 'object' && 'id' in created) {
              const idx = updatedMappings.findIndex(m => m.id === row.id)
              if (idx >= 0) updatedMappings[idx] = created as typeof row
              else updatedMappings.push(created as typeof row)
            }
          } else {
            const updatedTargets = { ...row.target_mappings, [market]: newCat }
            await categoryApi.updateMapping(row.id, { target_mappings: updatedTargets })
            const idx = updatedMappings.findIndex(m => m.id === row.id)
            if (idx >= 0) updatedMappings[idx] = { ...updatedMappings[idx], target_mappings: updatedTargets }
          }
          successCount++
        }
      } catch {
        errorCount++
      }
    }

    setMappings(updatedMappings)
    setMarketAiLoading(null)
    setLastAiUsage({ calls: successCount, tokens: successCount * 1800, cost: successCount * COST_PER_CALL_KRW, date: new Date().toLocaleTimeString() })
    setMarketAiProgress({ market, current: total, total, success: successCount, fail: errorCount })
    if (skippedCount > 0) showAlert(`${skippedCount}건은 이미 매핑되어 건너뜀`, 'info')
  }

  // ESM 크로스매핑 복사 (지마켓→옥션)
  const [esmCopyLoading, setEsmCopyLoading] = useState(false)

  const handleEsmCrossCopy = async (fromMarket: string, toMarket: string) => {
    const ids = filteredMappings.map(m => m.id).filter(id => !id.startsWith('unmapped_'))
    if (ids.length === 0) {
      showAlert('복사할 매핑 데이터가 없습니다', 'info')
      return
    }
    setEsmCopyLoading(true)
    try {
      const result = await categoryApi.copyEsmMapping(fromMarket, toMarket, ids)
      const label = fromMarket === 'gmarket' ? 'G마켓→옥션' : '옥션→G마켓'
      showAlert(`${label} 크로스매핑: ${result.copied}건 복사, ${result.skipped}건 스킵, ${result.failed}건 실패`, 'success')
      if (result.copied > 0) {
        const refreshed = await categoryApi.listMappings() as MappingRow[]
        setMappings(refreshed)
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '복사 실패'
      showAlert(`크로스매핑 실패: ${msg}`, 'error')
    } finally {
      setEsmCopyLoading(false)
    }
  }

  // 마켓 키 목록
  const marketKeys = Object.keys(MARKET_LABELS)

  const colStyle = {
    flex: 1,
    minWidth: '140px',
    borderRight: '1px solid #2D2D2D',
    maxHeight: '280px',
    overflowY: 'auto' as const,
  }

  const itemStyle = (isSelected: boolean) => ({
    padding: '0.5rem 0.75rem',
    fontSize: '0.8125rem',
    color: isSelected ? '#FF8C00' : '#C5C5C5',
    cursor: 'pointer',
    background: isSelected ? 'rgba(255,140,0,0.08)' : 'transparent',
    transition: 'background 0.15s',
  })

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 단계 연결 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.25rem' }}>
        <a href="/samba/policies" style={{ fontSize: '0.75rem', color: '#888', textDecoration: 'none' }}>← 정책관리</a>
        <a href="/samba/shipments" style={{ fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none' }}>상품전송 →</a>
      </div>
      {/* 헤더 + 카테고리 동기화 */}
      <div style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>카테고리 매핑</h2>
        <button
          onClick={() => {
            const initial: Record<string, boolean> = {}
            Object.keys(MARKET_LABELS).forEach(mk => { initial[mk] = true })
            setSyncSelected(initial)
            setSyncProgress({})
            setSyncModalOpen(true)
          }}
          disabled={seedLoading}
          style={{
            padding: '0.375rem 0.875rem',
            fontSize: '0.8125rem',
            fontWeight: 600,
            background: seedLoading ? '#333' : 'rgba(81,207,102,0.12)',
            border: `1px solid ${seedLoading ? '#444' : 'rgba(81,207,102,0.35)'}`,
            borderRadius: '6px',
            color: seedLoading ? '#666' : '#51CF66',
            cursor: seedLoading ? 'not-allowed' : 'pointer',
          }}
        >{seedLoading ? '동기화 중...' : '마켓 카테고리 동기화'}</button>
      </div>

      {/* AI 사용량 (SMS 잔여량 스타일 — 항상 표시) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 비용</span>
        <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
          예상 <span style={{ color: '#FFB84D', fontWeight: 700 }}>₩{costEstimate.cost.toLocaleString()}</span>
          <span style={{ color: '#888' }}> ({costEstimate.calls}회)</span>
        </span>
        {lastAiUsage && (
          <>
            <span style={{ color: '#2D2D2D' }}>|</span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
              최근 <span style={{ color: '#51CF66', fontWeight: 700 }}>₩{lastAiUsage.cost.toLocaleString()}</span>
              <span style={{ color: '#888' }}> ({lastAiUsage.calls}회 / ~{lastAiUsage.tokens.toLocaleString()}토큰)</span>
            </span>
            <span style={{ fontSize: '0.6875rem', color: '#555' }}>{lastAiUsage.date}</span>
          </>
        )}
        <span style={{ fontSize: '0.625rem', color: '#555', marginLeft: 'auto', cursor: 'help' }} title={`산정 근거: ${COST_BASIS}\n1회: ~1,500 in + ~300 out = ~₩15`}>근거</span>
      </div>

      {/* AI 안내 + 버튼 */}
      <div style={{ background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.25)', borderRadius: '8px', padding: '0.875rem 1.25rem', marginBottom: '1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
        <span style={{ fontSize: '0.8125rem', color: '#888', flex: 1 }}>
          {selectedPath
            ? `선택: ${selectedPath} (${selectedProducts.length}개) — AI가 마켓별 카테고리를 추천합니다`
            : '카테고리 선택 시 단건 매핑, 미선택 시 전체 미매핑 자동 처리'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
          <button
            onClick={handleOpenAiMarketSelect}
            style={{
              padding: '0.5rem 1rem',
              background: 'rgba(255,140,0,0.12)',
              border: '1px solid rgba(255,140,0,0.35)',
              borderRadius: '8px',
              color: '#FF8C00',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
            }}
          >{selectedSite && selectedCat1 ? 'AI 매핑' : 'AI 전체 자동 매핑'}</button>
          <button
            onClick={handleBulkDelete}
            disabled={filteredMappings.length === 0}
            style={{
              padding: '0.5rem 1rem',
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: '8px',
              color: filteredMappings.length === 0 ? '#555' : '#EF4444',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: filteredMappings.length === 0 ? 'not-allowed' : 'pointer',
              whiteSpace: 'nowrap',
            }}
          >매핑 일괄 삭제 ({filteredMappings.length})</button>
        </div>
      </div>

      {/* 5단 드릴다운 테이블 (사이트 포함) */}
      <div style={{ ...card, overflow: 'hidden', marginBottom: '1.25rem' }}>
        {/* 헤더 */}
        <div style={{ display: 'flex', borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
          {['사이트', '대분류', '중분류', '소분류', '세분류'].map((h, i) => {
            const selections = [selectedSite, selectedCat1, selectedCat2, selectedCat3, selectedCat4]
            return (
              <div key={h} style={{
                flex: 1, minWidth: '140px', padding: '0.625rem 0.75rem',
                fontSize: '0.75rem', fontWeight: 600,
                color: catEntry === i || selections[i] ? '#FF8C00' : '#888',
                borderRight: i < 4 ? '1px solid #2D2D2D' : 'none',
                cursor: 'pointer',
              }}
              onClick={() => {
                // 진입점 전환: 모든 선택 초기화, 해당 레벨을 진입점으로
                setCatEntry(i)
                setSelectedSite(null); setSelectedCat1(null); setSelectedCat2(null)
                setSelectedCat3(null); setSelectedCat4(null)
                setSelectedProducts([]); setSelectedPath('')
              }}
              >{h}</div>
            )
          })}
        </div>

        {loading ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>카테고리 트리를 로딩 중...</div>
        ) : (
          <div style={{ display: 'flex' }}>
            {/* 사이트: 항상 표시 */}
            <div style={colStyle}>
              {getCrossSites().length === 0 ? (
                <div style={{ padding: '1rem', color: '#555', fontSize: '0.8125rem' }}>수집 상품이 없습니다</div>
              ) : getCrossSites().map(site => (
                <div key={site} style={itemStyle(selectedSite === site)} onClick={() => handleSiteClick(site)}
                  onMouseEnter={e => { if (selectedSite !== site) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedSite !== site) e.currentTarget.style.background = 'transparent' }}
                >{site}</div>
              ))}
            </div>
            {/* 대분류: 사이트 선택 후 표시 */}
            <div style={colStyle}>
              {selectedSite ? (
                getCat1List().map(cat => (
                  <div key={cat} style={itemStyle(selectedCat1 === cat)} onClick={() => handleCat1Click(cat)}
                    onMouseEnter={e => { if (selectedCat1 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                    onMouseLeave={e => { if (selectedCat1 !== cat) e.currentTarget.style.background = 'transparent' }}
                  >{cat}</div>
                ))
              ) : null}
            </div>
            {/* 중분류: 대분류 선택 후 표시 */}
            <div style={colStyle}>
              {selectedCat1 ? (
                getCat2List().map(cat => (
                  <div key={cat} style={itemStyle(selectedCat2 === cat)} onClick={() => handleCat2Click(cat)}
                    onMouseEnter={e => { if (selectedCat2 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                    onMouseLeave={e => { if (selectedCat2 !== cat) e.currentTarget.style.background = 'transparent' }}
                  >{cat}</div>
                ))
              ) : null}
            </div>
            {/* 소분류: 중분류 선택 후 표시 */}
            <div style={colStyle}>
              {selectedCat2 ? (
                getCat3List().map(cat => (
                  <div key={cat} style={itemStyle(selectedCat3 === cat)} onClick={() => handleCat3Click(cat)}
                    onMouseEnter={e => { if (selectedCat3 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                    onMouseLeave={e => { if (selectedCat3 !== cat) e.currentTarget.style.background = 'transparent' }}
                  >{cat}</div>
                ))
              ) : null}
            </div>
            {/* 세분류: 소분류 선택 후 표시 */}
            <div style={{ ...colStyle, borderRight: 'none' }}>
              {selectedCat3 ? (
                getCat4List().map(cat => (
                  <div key={cat} style={itemStyle(selectedCat4 === cat)} onClick={() => handleCat4Click(cat)}
                    onMouseEnter={e => { if (selectedCat4 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                    onMouseLeave={e => { if (selectedCat4 !== cat) e.currentTarget.style.background = 'transparent' }}
                  >{cat}</div>
                ))
              ) : null}
            </div>
          </div>
        )}
      </div>

      {/* 매핑 현황 테이블 — 드릴다운 선택에 동적 반응 */}
      {(mappings.length > 0 || isLeafCategory) && (
        <div style={{ marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '1.125rem', fontWeight: 700, marginBottom: '0.75rem' }}>
            매핑 현황{' '}
            <span style={{ fontSize: '0.875rem', fontWeight: 400, color: '#888' }}>
              ({filteredMappings.length === mappings.length
                ? `총 ${mappings.length}건`
                : `${filteredMappings.length}건 / 전체 ${mappings.length}건`})
            </span>
          </h3>
          <div style={{ ...card, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
                  <th style={{ padding: '0.625rem 0.75rem', textAlign: 'left', color: '#888', fontWeight: 600, whiteSpace: 'nowrap' }}>사이트</th>
                  <th style={{ padding: '0.625rem 0.75rem', textAlign: 'left', color: '#888', fontWeight: 600, whiteSpace: 'nowrap' }}>소싱 카테고리</th>
                  {marketKeys.map(mk => (
                    <th key={mk} style={{ padding: '0.625rem 0.5rem', textAlign: 'left', color: '#888', fontWeight: 600, whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span>{MARKET_LABELS[mk]}</span>
                        {/* ESM 크로스매핑 버튼: 옥션은 G→A, 지마켓은 A→G */}
                        {mk === 'auction' && (
                          <button
                            onClick={() => handleEsmCrossCopy('gmarket', 'auction')}
                            disabled={esmCopyLoading || filteredMappings.length === 0}
                            style={{
                              background: 'none',
                              border: '1px solid transparent',
                              borderRadius: '3px',
                              color: esmCopyLoading ? '#4C9AFF' : '#555',
                              fontSize: '0.5625rem',
                              cursor: esmCopyLoading ? 'not-allowed' : 'pointer',
                              padding: '1px 3px',
                              lineHeight: 1,
                              fontWeight: 700,
                            }}
                            onMouseEnter={e => { if (!esmCopyLoading) { e.currentTarget.style.color = '#4C9AFF'; e.currentTarget.style.borderColor = 'rgba(76,154,255,0.3)' } }}
                            onMouseLeave={e => { if (!esmCopyLoading) { e.currentTarget.style.color = '#555'; e.currentTarget.style.borderColor = 'transparent' } }}
                            title="G마켓 매핑을 옥션으로 크로스매핑 복사"
                          >{esmCopyLoading ? '...' : 'G→A'}</button>
                        )}
                        {mk === 'gmarket' && (
                          <button
                            onClick={() => handleEsmCrossCopy('auction', 'gmarket')}
                            disabled={esmCopyLoading || filteredMappings.length === 0}
                            style={{
                              background: 'none',
                              border: '1px solid transparent',
                              borderRadius: '3px',
                              color: esmCopyLoading ? '#4C9AFF' : '#555',
                              fontSize: '0.5625rem',
                              cursor: esmCopyLoading ? 'not-allowed' : 'pointer',
                              padding: '1px 3px',
                              lineHeight: 1,
                              fontWeight: 700,
                            }}
                            onMouseEnter={e => { if (!esmCopyLoading) { e.currentTarget.style.color = '#4C9AFF'; e.currentTarget.style.borderColor = 'rgba(76,154,255,0.3)' } }}
                            onMouseLeave={e => { if (!esmCopyLoading) { e.currentTarget.style.color = '#555'; e.currentTarget.style.borderColor = 'transparent' } }}
                            title="옥션 매핑을 G마켓으로 크로스매핑 복사"
                          >{esmCopyLoading ? '...' : 'A→G'}</button>
                        )}
                        <button
                          onClick={() => handleMarketAiRemap(mk)}
                          disabled={marketAiLoading !== null || filteredMappings.length === 0}
                          style={{
                            background: 'none',
                            border: '1px solid transparent',
                            borderRadius: '3px',
                            color: marketAiLoading === mk ? '#FF8C00' : '#555',
                            fontSize: '0.625rem',
                            cursor: marketAiLoading !== null ? 'not-allowed' : 'pointer',
                            padding: '1px 3px',
                            lineHeight: 1,
                            opacity: marketAiLoading !== null && marketAiLoading !== mk ? 0.3 : 1,
                          }}
                          onMouseEnter={e => {
                            if (!marketAiLoading) {
                              e.currentTarget.style.color = '#FF8C00'
                              e.currentTarget.style.borderColor = 'rgba(255,140,0,0.3)'
                            }
                          }}
                          onMouseLeave={e => {
                            if (marketAiLoading !== mk) {
                              e.currentTarget.style.color = '#555'
                              e.currentTarget.style.borderColor = 'transparent'
                            }
                          }}
                          title={`${MARKET_LABELS[mk]} AI 리매핑 (${filteredMappings.length}건)`}
                        >{marketAiLoading === mk ? '...' : 'AI'}</button>
                        <button
                          onClick={() => handleMarketColumnDelete(mk)}
                          disabled={filteredMappings.length === 0}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: '#444',
                            fontSize: '0.625rem',
                            cursor: filteredMappings.length === 0 ? 'not-allowed' : 'pointer',
                            padding: '1px 2px',
                            lineHeight: 1,
                          }}
                          onMouseEnter={e => { e.currentTarget.style.color = '#EF4444' }}
                          onMouseLeave={e => { e.currentTarget.style.color = '#444' }}
                          title={`${MARKET_LABELS[mk]} 카테고리 일괄 삭제 (${filteredMappings.length}건)`}
                        >✕</button>
                      </div>
                      <span style={{ fontSize: '0.625rem', color: (marketCatCounts[mk] || 0) >= 1000 ? '#51CF66' : '#FF6B6B' }}>
                        {(marketCatCounts[mk] || 0).toLocaleString()}개
                      </span>
                      </div>
                    </th>
                  ))}
                  <th style={{ padding: '0.625rem 0.75rem', width: '40px' }} />
                </tr>
              </thead>
              <tbody>
                {filteredMappings.length === 0 && !isLeafCategory ? (
                  <tr>
                    <td colSpan={marketKeys.length + 3} style={{ padding: '1.5rem', textAlign: 'center', color: '#555' }}>
                      {selectedSite ? `${selectedSite}에 매핑된 카테고리가 없습니다` : '매핑 데이터가 없습니다'}
                    </td>
                  </tr>
                ) : null}
                {/* 최하단 카테고리 선택 + 매핑 없음 → 신규 편집 행 */}
                {isLeafCategory && filteredMappings.length === 0 && (
                  <tr style={{ borderBottom: '1px solid #2D2D2D', background: 'rgba(255,140,0,0.04)' }}>
                    <td style={{ padding: '0.5rem 0.75rem', color: '#FFB84D', fontWeight: 600, whiteSpace: 'nowrap' }}>{selectedSite}</td>
                    <td style={{ padding: '0.5rem 0.75rem', color: '#E5E5E5', whiteSpace: 'nowrap' }}>{getSourceCategory()}</td>
                    {marketKeys.map(mk => {
                      const isEditing = inlineFocusedMarket === mk || editingCell?.id === '__new__' && editingCell?.market === mk
                      return (
                        <td key={mk} style={{ padding: '0.25rem 0.5rem', minWidth: '140px' }}>
                          <div>
                            <input
                              value={manualEdits[mk] || ''}
                              onChange={e => {
                                const val = e.target.value
                                setManualEdits(prev => ({ ...prev, [mk]: val }))
                                setInlineFocusedMarket(mk)
                                updateDropdownPos(e.target)
                                if (inlineDebounceRef.current) clearTimeout(inlineDebounceRef.current)
                                if (!val.trim()) { setInlineSuggestions([]); return }
                                inlineDebounceRef.current = setTimeout(async () => {
                                  try {
                                    const results = await categoryApi.suggest(val, mk)
                                    setInlineSuggestions(Array.isArray(results) ? results : [])
                                  } catch { setInlineSuggestions([]) }
                                }, 300)
                              }}
                              onFocus={e => { setInlineFocusedMarket(mk); setInlineSuggestions([]); updateDropdownPos(e.target) }}
                              onBlur={() => { setTimeout(() => { if (inlineFocusedMarket === mk) { setInlineFocusedMarket(null); setInlineSuggestions([]); setDropdownPos(null) } }, 250) }}
                              placeholder="검색..."
                              style={{
                                width: '100%', padding: '0.375rem 0.5rem', background: '#1A1A1A',
                                border: `1px solid ${isEditing ? '#FF8C00' : manualEdits[mk]?.trim() ? 'rgba(255,140,0,0.3)' : '#2D2D2D'}`,
                                borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', outline: 'none',
                              }}
                            />
                          </div>
                        </td>
                      )
                    })}
                    <td style={{ padding: '0.5rem 0.5rem', textAlign: 'center' }}>
                      <button
                        onClick={handleManualSave}
                        disabled={Object.values(manualEdits).filter(v => v.trim()).length === 0}
                        style={{
                          background: 'none', border: 'none', fontSize: '0.875rem', cursor: 'pointer', padding: '0.25rem',
                          color: Object.values(manualEdits).filter(v => v.trim()).length > 0 ? '#22C55E' : '#444',
                        }}
                        title="매핑 저장"
                      >✓</button>
                    </td>
                  </tr>
                )}
                {filteredMappings.map(row => (
                    <tr key={row.id} style={{ borderBottom: '1px solid #2D2D2D' }}>
                      <td style={{ padding: '0.5rem 0.75rem', color: '#FFB84D', fontWeight: 600, whiteSpace: 'nowrap' }}>{row.source_site}</td>
                      <td style={{ padding: '0.5rem 0.75rem', color: '#E5E5E5', whiteSpace: 'nowrap' }}>{row.source_category}</td>
                      {marketKeys.map(mk => {
                        const val = row.target_mappings?.[mk] || ''
                        const isEditing = editingCell?.id === row.id && editingCell?.market === mk
                        return (
                          <td key={mk} style={{ padding: '0.25rem 0.5rem', minWidth: '140px', position: 'relative' }}>
                            {isEditing ? (
                              <div style={{ position: 'relative' }}>
                                <input
                                  autoFocus
                                  value={editingValue}
                                  onChange={e => handleSuggestSearch(e.target.value, mk, e.target)}
                                  onFocus={e => updateDropdownPos(e.target)}
                                  onBlur={() => {
                                    setTimeout(() => {
                                      if (editingCell?.id === row.id && editingCell?.market === mk) {
                                        handleSaveEdit()
                                      }
                                    }, 250)
                                  }}
                                  onKeyDown={handleEditKeyDown}
                                  placeholder="카테고리 검색..."
                                  style={{
                                    width: '100%',
                                    padding: '0.375rem 0.5rem',
                                    background: '#1A1A1A',
                                    border: '1px solid #FF8C00',
                                    borderRadius: '4px',
                                    color: '#E5E5E5',
                                    fontSize: '0.75rem',
                                    outline: 'none',
                                  }}
                                />
                              </div>
                            ) : (
                              <div
                                onClick={() => handleStartEdit(row.id, mk, val)}
                                style={{
                                  padding: '0.375rem 0.5rem',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                  color: val ? '#C5C5C5' : '#555',
                                  fontSize: '0.75rem',
                                  transition: 'background 0.15s',
                                }}
                                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)' }}
                                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                                title={val || '클릭하여 매핑 추가'}
                              >
                                {val || '─'}
                              </div>
                            )}
                          </td>
                        )
                      })}
                      <td style={{ padding: '0.5rem 0.5rem', textAlign: 'center' }}>
                        {row.id.startsWith('unmapped_') ? (
                          <span style={{ color: '#555', fontSize: '0.7rem' }}>미매핑</span>
                        ) : (
                          <button
                            onClick={() => handleDeleteMapping(row.id)}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: '#666',
                              fontSize: '0.875rem',
                              cursor: 'pointer',
                              padding: '0.25rem',
                              lineHeight: 1,
                            }}
                            onMouseEnter={e => { e.currentTarget.style.color = '#EF4444' }}
                            onMouseLeave={e => { e.currentTarget.style.color = '#666' }}
                            title="매핑 삭제"
                          >✕</button>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 카테고리 검색 드롭다운 (fixed — overflow 영향 안 받음) */}
      {(suggestions.length > 0 || (inlineFocusedMarket && inlineSuggestions.length > 0)) && dropdownPos && (
        <div style={{
          position: 'fixed',
          top: dropdownPos.top,
          left: dropdownPos.left,
          width: dropdownPos.width,
          zIndex: 99999,
          background: '#1E1E1E',
          border: '1px solid #3D3D3D',
          borderRadius: '6px',
          maxHeight: '200px',
          overflowY: 'auto',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
        }}>
          {(suggestions.length > 0 ? suggestions : inlineSuggestions).map((s, i) => (
            <div
              key={i}
              onMouseDown={e => {
                e.preventDefault()
                if (suggestions.length > 0) {
                  handleSelectSuggestion(s)
                } else if (inlineFocusedMarket) {
                  setManualEdits(prev => ({ ...prev, [inlineFocusedMarket]: s }))
                  setInlineFocusedMarket(null)
                  setInlineSuggestions([])
                }
                setDropdownPos(null)
              }}
              style={{
                padding: '0.5rem 0.75rem',
                fontSize: '0.75rem',
                color: '#C5C5C5',
                cursor: 'pointer',
                borderBottom: i < (suggestions.length > 0 ? suggestions : inlineSuggestions).length - 1 ? '1px solid #2D2D2D' : 'none',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,140,0,0.1)'; e.currentTarget.style.color = '#FF8C00' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#C5C5C5' }}
            >{s}</div>
          ))}
        </div>
      )}

      {/* 선택 카테고리 + 상품 썸네일 */}
      {selectedPath && (
        <div>
          <div style={{ marginBottom: '1rem', fontSize: '0.875rem' }}>
            <span style={{ color: '#888' }}>[선택카테고리]</span>{' '}
            <span style={{ color: '#FF8C00', fontWeight: 600 }}>{selectedPath}</span>{' '}
            <span style={{ color: '#888' }}>상품 {selectedProducts.length}개</span>
          </div>

          {selectedProducts.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '1rem' }}>
              {selectedProducts.slice(0, 100).map(p => (
                <div key={p.id} style={{ ...card, overflow: 'hidden', cursor: 'pointer' }}
                  onClick={() => router.push(`/samba/products?highlight=${p.id}`)}
                >
                  {/* 이미지 */}
                  <div style={{ width: '100%', aspectRatio: '1', background: '#1A1A1A', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                    {p.images && p.images.length > 0 ? (
                      <img src={p.images[0]} alt={p.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                    ) : (
                      <span style={{ color: '#555', fontSize: '2rem' }}>🖼</span>
                    )}
                  </div>
                  <div style={{ padding: '0.75rem' }}>
                    <p style={{ fontSize: '0.8125rem', color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: '0.25rem' }}>{p.name}</p>
                    <p style={{ fontSize: '0.875rem', fontWeight: 600, color: '#FF8C00' }}>₩{(p.sale_price || 0).toLocaleString()}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* AI 매핑 결과 모달 */}
      {aiModalOpen && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 99998,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => { if (!aiLoading) setAiModalOpen(false) }}
        >
          <div
            style={{
              background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '12px',
              width: 'min(560px, 92vw)', maxHeight: '80vh', overflow: 'auto',
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* 모달 헤더 */}
            <div style={{
              padding: '1.25rem 1.5rem',
              borderBottom: '1px solid #2D2D2D',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div>
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>
                  {selectedSite && selectedCat1 ? 'AI 카테고리 매핑' : 'AI 전체 자동 매핑'}
                </h3>
                <p style={{ fontSize: '0.75rem', color: '#888' }}>
                  {selectedSite && selectedCat1 ? selectedPath : '미매핑 카테고리 일괄 처리 + 누락 마켓 보충'}
                </p>
              </div>
              {!aiLoading && (
                <button
                  onClick={() => setAiModalOpen(false)}
                  style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}
                >✕</button>
              )}
            </div>

            {/* 모달 본문 */}
            <div style={{ padding: '1.25rem 1.5rem' }}>
              {aiLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem 0', color: '#888' }}>
                  <div style={{ fontSize: '1.5rem', marginBottom: '0.75rem' }}>🤖</div>
                  <p style={{ fontSize: '0.875rem' }}>
                    {bulkResult === null && !selectedSite
                      ? 'Claude가 미매핑 카테고리를 일괄 분석하고 있어요...'
                      : 'Claude가 카테고리를 분석하고 있어요...'}
                  </p>
                </div>
              ) : bulkResult ? (
                /* 벌크 모드 결과 */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  {/* 요약 카드 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
                    <div style={{ padding: '1rem', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#22C55E' }}>{bulkResult.mapped}</div>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginTop: '0.25rem' }}>신규 매핑</div>
                    </div>
                    <div style={{ padding: '1rem', background: 'rgba(59,130,246,0.08)', border: '1px solid rgba(59,130,246,0.25)', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#3B82F6' }}>{bulkResult.updated}</div>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginTop: '0.25rem' }}>마켓 보충</div>
                    </div>
                    <div style={{ padding: '1rem', background: 'rgba(255,255,255,0.03)', border: '1px solid #2D2D2D', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#888' }}>{bulkResult.skipped}</div>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginTop: '0.25rem' }}>건너뜀</div>
                    </div>
                  </div>
                  {/* 에러 목록 */}
                  {bulkResult.errors.length > 0 && (
                    <div style={{ padding: '0.75rem 1rem', background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px' }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#EF4444', marginBottom: '0.5rem' }}>오류 {bulkResult.errors.length}건</div>
                      <div style={{ maxHeight: '120px', overflowY: 'auto' }}>
                        {bulkResult.errors.map((err, i) => (
                          <div key={i} style={{ fontSize: '0.75rem', color: '#999', padding: '0.125rem 0' }}>{err}</div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* 단건 모드 결과 */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {Object.keys(aiResult).length === 0 ? (
                    <p style={{ color: '#888', textAlign: 'center', padding: '1rem' }}>
                      추천 결과가 없습니다
                    </p>
                  ) : (
                    Object.entries(aiEdits).map(([market, cat]) => (
                      <div key={market} style={{
                        display: 'flex', alignItems: 'center', gap: '0.75rem',
                        padding: '0.75rem',
                        background: 'rgba(255,255,255,0.02)',
                        borderRadius: '8px',
                        border: '1px solid #2D2D2D',
                      }}>
                        <div style={{
                          minWidth: '100px',
                          fontSize: '0.8125rem',
                          fontWeight: 600,
                          color: '#FFB84D',
                        }}>
                          {MARKET_LABELS[market] || market}
                        </div>
                        <input
                          value={cat}
                          onChange={e => setAiEdits(prev => ({ ...prev, [market]: e.target.value }))}
                          style={{
                            flex: 1,
                            padding: '0.5rem 0.75rem',
                            background: '#1A1A1A',
                            border: '1px solid #2D2D2D',
                            borderRadius: '6px',
                            color: cat ? '#E5E5E5' : '#555',
                            fontSize: '0.8125rem',
                            outline: 'none',
                          }}
                          placeholder="(매핑 없음)"
                        />
                        <span style={{ fontSize: '0.875rem' }}>
                          {cat ? '✅' : '➖'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>

            {/* 모달 하단 버튼 */}
            {!aiLoading && (bulkResult || Object.keys(aiResult).length > 0) && (
              <div style={{
                padding: '1rem 1.5rem',
                borderTop: '1px solid #2D2D2D',
                display: 'flex', justifyContent: 'flex-end', gap: '0.5rem',
              }}>
                {bulkResult ? (
                  <button
                    onClick={() => { setAiModalOpen(false); load() }}
                    style={{
                      padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px',
                      border: 'none', background: '#FF8C00', color: '#FFF', cursor: 'pointer', fontWeight: 600,
                    }}
                  >확인</button>
                ) : (
                  <>
                    <button
                      onClick={() => setAiModalOpen(false)}
                      style={{
                        padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px',
                        border: '1px solid #3D3D3D', background: '#2A2A2A', color: '#999', cursor: 'pointer',
                      }}
                    >취소</button>
                    <button
                      onClick={handleAiSave}
                      style={{
                        padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px',
                        border: 'none', background: '#FF8C00', color: '#FFF', cursor: 'pointer', fontWeight: 600,
                      }}
                    >매핑 저장</button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 마켓별 AI 리매핑 진행 모달 */}
      {marketAiProgress && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 99998,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => {
            if (marketAiProgress.current >= marketAiProgress.total) {
              setMarketAiProgress(null)
              load()
            }
          }}
        >
          <div
            style={{
              background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '12px',
              width: 'min(420px, 90vw)', overflow: 'hidden',
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* 헤더 */}
            <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid #2D2D2D' }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>
                {MARKET_LABELS[marketAiProgress.market]} AI 카테고리 매핑
              </h3>
              <p style={{ fontSize: '0.75rem', color: '#888' }}>
                {marketAiProgress.current >= marketAiProgress.total
                  ? '매핑 완료'
                  : `${marketAiProgress.current} / ${marketAiProgress.total}건 처리 중...`}
              </p>
            </div>

            {/* 본문 */}
            <div style={{ padding: '1.5rem' }}>
              {/* 진행바 */}
              <div style={{ background: '#2D2D2D', borderRadius: '4px', height: '8px', overflow: 'hidden', marginBottom: '1rem' }}>
                <div style={{
                  width: `${Math.round((marketAiProgress.current / marketAiProgress.total) * 100)}%`,
                  height: '100%',
                  background: marketAiProgress.current >= marketAiProgress.total ? '#22C55E' : '#FF8C00',
                  borderRadius: '4px',
                  transition: 'width 0.3s',
                }} />
              </div>

              {/* 결과 카드 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
                <div style={{ padding: '0.75rem', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.25)', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#22C55E' }}>{marketAiProgress.success}</div>
                  <div style={{ fontSize: '0.6875rem', color: '#888' }}>성공</div>
                </div>
                <div style={{ padding: '0.75rem', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#EF4444' }}>{marketAiProgress.fail}</div>
                  <div style={{ fontSize: '0.6875rem', color: '#888' }}>실패</div>
                </div>
                <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.03)', border: '1px solid #2D2D2D', borderRadius: '8px', textAlign: 'center' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#888' }}>{marketAiProgress.total - marketAiProgress.current}</div>
                  <div style={{ fontSize: '0.6875rem', color: '#888' }}>대기</div>
                </div>
              </div>

              {/* 진행 중 안내 or 완료 버튼 */}
              {marketAiProgress.current < marketAiProgress.total ? (
                <div style={{ textAlign: 'center', marginTop: '1rem', color: '#888', fontSize: '0.8125rem' }}>
                  🤖 Claude가 카테고리를 분석하고 있어요...
                </div>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
                  <button
                    onClick={() => { setMarketAiProgress(null); load() }}
                    style={{
                      padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px',
                      border: 'none', background: '#FF8C00', color: '#FFF', cursor: 'pointer', fontWeight: 600,
                    }}
                  >확인</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {/* AI 마켓 선택 모달 */}
      {aiMarketSelectOpen && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 99998,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setAiMarketSelectOpen(false)}
        >
          <div
            style={{
              background: '#1E1E1E', border: '1px solid #3D3D3D', borderRadius: '12px',
              width: 'min(480px, 92vw)', maxHeight: '80vh', overflow: 'auto',
            }}
            onClick={e => e.stopPropagation()}
          >
            {(!selectedSite || !selectedCat1) ? (
              /* 벌크 모드: 계정 연결된 마켓만 표시 */
              <>
                <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid #2D2D2D' }}>
                  <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>AI 전체 자동 매핑 — 마켓 선택</h3>
                  <p style={{ fontSize: '0.75rem', color: '#888' }}>
                    계정 연결된 마켓만 표시됩니다 · 미매핑 카테고리를 선택된 마켓으로 일괄 매핑
                  </p>
                </div>
                <div style={{ padding: '1.25rem 1.5rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={activeMarketTypes.every(t => bulkSelectedMarkets[t])}
                      onChange={e => {
                        const updated: Record<string, boolean> = {}
                        activeMarketTypes.forEach(t => { updated[t] = e.target.checked })
                        setBulkSelectedMarkets(updated)
                      }}
                      style={{ accentColor: '#FF8C00' }}
                    />
                    <span style={{ fontSize: '0.8125rem', color: '#E5E5E5', fontWeight: 600 }}>전체 선택</span>
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
                    {activeMarketTypes.map(t => (
                      <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0.625rem', background: bulkSelectedMarkets[t] ? 'rgba(255,140,0,0.08)' : 'transparent', border: `1px solid ${bulkSelectedMarkets[t] ? 'rgba(255,140,0,0.3)' : '#2D2D2D'}`, borderRadius: '6px', cursor: 'pointer', transition: 'all 0.15s' }}>
                        <input
                          type="checkbox"
                          checked={!!bulkSelectedMarkets[t]}
                          onChange={e => setBulkSelectedMarkets(prev => ({ ...prev, [t]: e.target.checked }))}
                          style={{ accentColor: '#FF8C00' }}
                        />
                        <span style={{ fontSize: '0.8125rem', color: bulkSelectedMarkets[t] ? '#FF8C00' : '#999' }}>{MARKET_LABELS[t] || t}</span>
                      </label>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.75rem' }}>
                    선택: {activeMarketTypes.filter(t => bulkSelectedMarkets[t]).length}개 마켓
                  </div>
                </div>
              </>
            ) : (
              /* 단건 모드: 전체 마켓 표시 */
              <>
                <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid #2D2D2D' }}>
                  <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>AI 매핑 — 마켓 선택</h3>
                  <p style={{ fontSize: '0.75rem', color: '#888' }}>
                    {selectedPath} — AI가 선택된 마켓의 카테고리를 추천합니다
                  </p>
                </div>
                <div style={{ padding: '1.25rem 1.5rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={marketKeys.every(mk => aiSelectedMarkets[mk])}
                      onChange={e => handleAiMarketSelectAll(e.target.checked)}
                      style={{ accentColor: '#FF8C00' }}
                    />
                    <span style={{ fontSize: '0.8125rem', color: '#E5E5E5', fontWeight: 600 }}>전체 선택</span>
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
                    {marketKeys.map(mk => (
                      <label key={mk} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0.625rem', background: aiSelectedMarkets[mk] ? 'rgba(255,140,0,0.08)' : 'transparent', border: `1px solid ${aiSelectedMarkets[mk] ? 'rgba(255,140,0,0.3)' : '#2D2D2D'}`, borderRadius: '6px', cursor: 'pointer', transition: 'all 0.15s' }}>
                        <input
                          type="checkbox"
                          checked={!!aiSelectedMarkets[mk]}
                          onChange={e => setAiSelectedMarkets(prev => ({ ...prev, [mk]: e.target.checked }))}
                          style={{ accentColor: '#FF8C00' }}
                        />
                        <span style={{ fontSize: '0.8125rem', color: aiSelectedMarkets[mk] ? '#FF8C00' : '#999' }}>{MARKET_LABELS[mk]}</span>
                      </label>
                    ))}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.75rem' }}>
                    선택: {marketKeys.filter(mk => aiSelectedMarkets[mk]).length}개 마켓 · 예상 비용 ₩{COST_PER_CALL_KRW}
                  </div>
                </div>
              </>
            )}
            <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid #2D2D2D', display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button
                onClick={() => setAiMarketSelectOpen(false)}
                style={{ padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px', border: '1px solid #3D3D3D', background: '#2A2A2A', color: '#999', cursor: 'pointer' }}
              >취소</button>
              <button
                onClick={handleAiMarketConfirm}
                style={{ padding: '0.5rem 1.25rem', fontSize: '0.8125rem', borderRadius: '6px', border: 'none', background: '#FF8C00', color: '#FFF', cursor: 'pointer', fontWeight: 600 }}
              >AI 매핑 시작</button>
            </div>
          </div>
        </div>
      )}

      {/* 카테고리 동기화 마켓 선택 모달 */}
      {syncModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '480px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>마켓 카테고리 동기화</h3>
            <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1rem' }}>동기화할 마켓을 선택하세요. API 계정이 등록된 마켓만 동기화됩니다.</p>

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              <button
                onClick={() => {
                  const all: Record<string, boolean> = {}
                  Object.keys(MARKET_LABELS).forEach(mk => { all[mk] = true })
                  setSyncSelected(all)
                }}
                style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: 'transparent', border: '1px solid #3D3D3D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}
              >전체선택</button>
              <button
                onClick={() => setSyncSelected({})}
                style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem', background: 'transparent', border: '1px solid #3D3D3D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}
              >전체해제</button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '1.25rem' }}>
              {Object.entries(MARKET_LABELS).map(([mk, label]) => (
                <label key={mk} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', cursor: 'pointer', padding: '0.375rem 0.5rem', background: syncSelected[mk] ? 'rgba(81,207,102,0.1)' : 'rgba(30,30,30,0.5)', border: `1px solid ${syncSelected[mk] ? 'rgba(81,207,102,0.3)' : '#2D2D2D'}`, borderRadius: '6px' }}>
                  <input
                    type="checkbox"
                    checked={!!syncSelected[mk]}
                    onChange={e => setSyncSelected(prev => ({ ...prev, [mk]: e.target.checked }))}
                    style={{ accentColor: '#51CF66', width: '14px', height: '14px' }}
                  />
                  <span style={{ fontSize: '0.8125rem', color: syncSelected[mk] ? '#E5E5E5' : '#666' }}>{label}</span>
                  <span style={{ fontSize: '0.625rem', color: (marketCatCounts[mk] || 0) >= 1000 ? '#51CF66' : '#FF6B6B', marginLeft: 'auto' }}>{(marketCatCounts[mk] || 0).toLocaleString()}</span>
                  {syncProgress[mk] && (() => {
                    const p = syncProgress[mk]
                    if (p.status === 'loading') return <span style={{ fontSize: '0.625rem', color: '#FF8C00' }}>...</span>
                    if (p.status === 'ok') return <span style={{ fontSize: '0.625rem', color: '#51CF66' }}>{p.count?.toLocaleString()}</span>
                    return <span style={{ fontSize: '0.625rem', color: '#FF6B6B' }}>X</span>
                  })()}
                </label>
              ))}
            </div>

            {/* 동기화 결과 */}
            {Object.values(syncProgress).some(p => p.status !== 'loading') && (
              <div style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem', marginBottom: '1rem', maxHeight: '200px', overflowY: 'auto' }}>
                <p style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem', fontWeight: 600 }}>동기화 결과</p>
                {Object.entries(syncProgress)
                  .filter(([, p]) => p.status !== 'loading')
                  .map(([mk, p]) => (
                    <div key={mk} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.25rem 0', borderBottom: '1px solid #1C1C1C' }}>
                      <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>{MARKET_LABELS[mk] || mk}</span>
                      {p.status === 'ok' ? (
                        <span style={{ fontSize: '0.8125rem', color: '#51CF66', fontWeight: 600 }}>{p.count?.toLocaleString()}개</span>
                      ) : (
                        <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>{p.error || '실패'}</span>
                      )}
                    </div>
                  ))}
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setSyncModalOpen(false)}
                disabled={seedLoading}
                style={{ padding: '0.5rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}
              >닫기</button>
              <button
                onClick={async () => {
                  const selected = Object.keys(syncSelected).filter(mk => syncSelected[mk])
                  if (selected.length === 0) { showAlert('마켓을 선택하세요', 'info'); return }
                  setSeedLoading(true)
                  let okCount = 0
                  let failCount = 0
                  for (const mk of selected) {
                    setSyncProgress(prev => ({ ...prev, [mk]: { status: 'loading' } }))
                    try {
                      const res = await categoryApi.syncMarket(mk)
                      if (res.ok) {
                        setSyncProgress(prev => ({ ...prev, [mk]: { status: 'ok', count: res.count } }))
                        setMarketCatCounts(prev => ({ ...prev, [mk]: res.count }))
                        okCount++
                      } else {
                        setSyncProgress(prev => ({ ...prev, [mk]: { status: 'fail', error: '응답 오류' } }))
                        failCount++
                      }
                    } catch (err) {
                      setSyncProgress(prev => ({ ...prev, [mk]: { status: 'fail', error: err instanceof Error ? err.message : '실패' } }))
                      failCount++
                    }
                  }
                  setSeedLoading(false)
                }}
                disabled={seedLoading}
                style={{ padding: '0.5rem 1.25rem', background: seedLoading ? '#333' : '#51CF66', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: seedLoading ? 'not-allowed' : 'pointer' }}
              >{seedLoading ? '동기화 중...' : '동기화 시작'}</button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

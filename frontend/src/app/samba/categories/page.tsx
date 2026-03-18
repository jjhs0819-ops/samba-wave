'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { collectorApi, type SambaCollectedProduct } from '@/lib/samba/api'
import { showAlert } from '@/components/samba/Modal'

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

// 카테고리 계층 구조 타입
interface CatLevel {
  name: string
  children: Record<string, CatLevel>
  products: SambaCollectedProduct[]
}

export default function CategoriesPage() {
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

  // 선택된 카테고리의 상품들
  const [selectedProducts, setSelectedProducts] = useState<SambaCollectedProduct[]>([])
  const [selectedPath, setSelectedPath] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const all = await collectorApi.listProducts(0, 9999)
      console.log('[카테고리] 상품 로드:', all?.length || 0, '건')
      if (Array.isArray(all) && all.length > 0) {
        setProducts(all)
        buildTree(all)
      } else {
        console.warn('[카테고리] 상품 데이터 비어있음')
        setProducts([])
        setSites([])
      }
    } catch (e) {
      console.error('[카테고리] 상품 로드 실패:', e)
    }
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
    setSelectedSite(site)
    setSelectedCat1(null); setSelectedCat2(null); setSelectedCat3(null); setSelectedCat4(null)
    setSelectedProducts([]); setSelectedPath('')
  }

  const handleCat1Click = (cat: string) => {
    setSelectedCat1(cat); setSelectedCat2(null); setSelectedCat3(null); setSelectedCat4(null)
    updateSelectedProducts(cat, null, null, null)
  }

  const handleCat2Click = (cat: string) => {
    setSelectedCat2(cat); setSelectedCat3(null); setSelectedCat4(null)
    updateSelectedProducts(selectedCat1!, cat, null, null)
  }

  const handleCat3Click = (cat: string) => {
    setSelectedCat3(cat); setSelectedCat4(null)
    updateSelectedProducts(selectedCat1!, selectedCat2!, cat, null)
  }

  const handleCat4Click = (cat: string) => {
    setSelectedCat4(cat)
    updateSelectedProducts(selectedCat1!, selectedCat2!, selectedCat3!, cat)
  }

  const updateSelectedProducts = (c1: string, c2: string | null, c3: string | null, c4: string | null) => {
    if (!selectedSite) return
    let node = catTree[selectedSite]
    const path = [selectedSite]

    if (c1 && node.children[c1]) { node = node.children[c1]; path.push(c1) }
    if (c2 && node.children[c2]) { node = node.children[c2]; path.push(c2) }
    if (c3 && node.children[c3]) { node = node.children[c3]; path.push(c3) }
    if (c4 && node.children[c4]) { node = node.children[c4]; path.push(c4) }

    // 해당 노드 + 하위의 모든 상품 수집
    const collectProducts = (n: CatLevel): SambaCollectedProduct[] => {
      let result = [...n.products]
      Object.values(n.children).forEach(child => { result = result.concat(collectProducts(child)) })
      return result
    }

    const prods = collectProducts(node)
    setSelectedProducts(prods)
    setSelectedPath(path.join(' > '))
  }

  // 5단 드릴다운 데이터
  const getCat1List = () => selectedSite && catTree[selectedSite] ? Object.keys(catTree[selectedSite].children) : []
  const getCat2List = () => selectedSite && selectedCat1 && catTree[selectedSite]?.children[selectedCat1] ? Object.keys(catTree[selectedSite].children[selectedCat1].children) : []
  const getCat3List = () => selectedSite && selectedCat1 && selectedCat2 && catTree[selectedSite]?.children[selectedCat1]?.children[selectedCat2] ? Object.keys(catTree[selectedSite].children[selectedCat1].children[selectedCat2].children) : []
  const getCat4List = () => selectedSite && selectedCat1 && selectedCat2 && selectedCat3 && catTree[selectedSite]?.children[selectedCat1]?.children[selectedCat2]?.children[selectedCat3] ? Object.keys(catTree[selectedSite].children[selectedCat1].children[selectedCat2].children[selectedCat3].children) : []

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
      {/* 헤더 */}
      <div style={{ marginBottom: '1.25rem' }}>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>카테고리 매핑</h2>
      </div>

      {/* AI 안내 */}
      <div style={{ background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.25)', borderRadius: '8px', padding: '0.875rem 1.25rem', marginBottom: '1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.8125rem', color: '#888' }}>AI가 최하단 카테고리 기준으로 등록 마켓 카테고리를 선택합니다.</span>
        <button onClick={() => showAlert('AI 카테고리 매핑은 Claude API 연동 후 사용 가능합니다', 'info')}
          style={{ padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.12)', border: '1px solid rgba(255,140,0,0.35)', borderRadius: '8px', color: '#FF8C00', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}
        >AI 카테고리 매핑</button>
      </div>

      {/* 5단 드릴다운 테이블 (사이트 포함) */}
      <div style={{ ...card, overflow: 'hidden', marginBottom: '1.25rem' }}>
        {/* 헤더 */}
        <div style={{ display: 'flex', borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
          {['사이트', '대분류', '중분류', '소분류', '세분류'].map((h, i) => (
            <div key={h} style={{ flex: 1, minWidth: '140px', padding: '0.625rem 0.75rem', fontSize: '0.75rem', fontWeight: 600, color: '#888', borderRight: i < 4 ? '1px solid #2D2D2D' : 'none' }}>{h}</div>
          ))}
        </div>

        {loading ? (
          <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>카테고리 트리를 로딩 중...</div>
        ) : (
          <div style={{ display: 'flex' }}>
            {/* 사이트 */}
            <div style={colStyle}>
              {sites.length === 0 ? (
                <div style={{ padding: '1rem', color: '#555', fontSize: '0.8125rem' }}>수집 상품이 없습니다</div>
              ) : sites.map(site => (
                <div key={site} style={itemStyle(selectedSite === site)} onClick={() => handleSiteClick(site)}
                  onMouseEnter={e => { if (selectedSite !== site) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedSite !== site) e.currentTarget.style.background = 'transparent' }}
                >{site}</div>
              ))}
            </div>
            {/* 대분류 */}
            <div style={colStyle}>
              {getCat1List().map(cat => (
                <div key={cat} style={itemStyle(selectedCat1 === cat)} onClick={() => handleCat1Click(cat)}
                  onMouseEnter={e => { if (selectedCat1 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedCat1 !== cat) e.currentTarget.style.background = 'transparent' }}
                >{cat}</div>
              ))}
            </div>
            {/* 중분류 */}
            <div style={colStyle}>
              {getCat2List().map(cat => (
                <div key={cat} style={itemStyle(selectedCat2 === cat)} onClick={() => handleCat2Click(cat)}
                  onMouseEnter={e => { if (selectedCat2 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedCat2 !== cat) e.currentTarget.style.background = 'transparent' }}
                >{cat}</div>
              ))}
            </div>
            {/* 소분류 */}
            <div style={colStyle}>
              {getCat3List().length > 0 ? getCat3List().map(cat => (
                <div key={cat} style={itemStyle(selectedCat3 === cat)} onClick={() => handleCat3Click(cat)}
                  onMouseEnter={e => { if (selectedCat3 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedCat3 !== cat) e.currentTarget.style.background = 'transparent' }}
                >{cat}</div>
              )) : selectedCat2 && <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8125rem' }}>항목 없음</div>}
            </div>
            {/* 세분류 */}
            <div style={{ ...colStyle, borderRight: 'none' }}>
              {getCat4List().length > 0 ? getCat4List().map(cat => (
                <div key={cat} style={itemStyle(selectedCat4 === cat)} onClick={() => handleCat4Click(cat)}
                  onMouseEnter={e => { if (selectedCat4 !== cat) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                  onMouseLeave={e => { if (selectedCat4 !== cat) e.currentTarget.style.background = 'transparent' }}
                >{cat}</div>
              )) : selectedCat3 && <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8125rem' }}>소분류 선택</div>}
            </div>
          </div>
        )}
      </div>

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
    </div>
  )
}

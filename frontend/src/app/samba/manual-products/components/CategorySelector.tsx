'use client'

import { useState } from 'react'
import { categoryApi } from '@/lib/samba/legacy'

import { btn, btnDisabled } from '@/lib/samba/buttons'
import { useTheme } from '@/lib/samba/useTheme'

interface Account {
  id: string
  market_type: string
  account_name: string
}

interface Props {
  accounts: Account[]
  savedCategories: Record<string, string>
  onSave: (categories: Record<string, string>) => void
  marketProductNos?: Record<string, string>
  onDeleteFromMarket?: (accountId: string) => void
  deletingAccountId?: string
}

function getMarketProductUrl(
  marketType: string,
  productNo: string,
  extras?: { pid?: string; vid?: string }
): string | null {
  switch (marketType) {
    case 'coupang': {
      const pid = extras?.pid
      const vid = extras?.vid
      if (pid) {
        return vid
          ? `https://www.coupang.com/vp/products/${pid}?vendorItemId=${vid}`
          : `https://www.coupang.com/vp/products/${pid}`
      }
      return `https://www.coupang.com/vp/products/${productNo}`
    }
    case '11st': return `https://www.11st.co.kr/products/${productNo}`
    case 'ssg': return `https://www.ssg.com/item/itemView.ssg?itemId=${productNo}`
    case 'gsshop': return `https://www.gsshop.com/prd/prd.gs?prdid=${productNo}`
    default: return null
  }
}

export default function CategorySelector({
  accounts,
  savedCategories,
  onSave,
  marketProductNos,
  onDeleteFromMarket,
  deletingAccountId,
}: Props) {
  const c = useTheme()
  const [cats, setCats] = useState<Record<string, string>>(savedCategories)
  const [queries, setQueries] = useState<Record<string, string>>({})
  const [suggestions, setSuggestions] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState<Record<string, boolean>>({})

  // 판매처(market_type)별로 계정 묶기
  const groups = accounts.reduce<Record<string, Account[]>>((acc, a) => {
    if (!acc[a.market_type]) acc[a.market_type] = []
    acc[a.market_type].push(a)
    return acc
  }, {})

  const search = async (marketType: string, q: string) => {
    setQueries(prev => ({ ...prev, [marketType]: q }))
    if (!q.trim()) {
      setSuggestions(prev => ({ ...prev, [marketType]: [] }))
      return
    }
    setLoading(prev => ({ ...prev, [marketType]: true }))
    try {
      const result = await categoryApi.suggest(q, marketType)
      const list = Array.isArray(result) ? (result as string[]) : []
      setSuggestions(prev => ({ ...prev, [marketType]: list }))
    } catch {
      setSuggestions(prev => ({ ...prev, [marketType]: [] }))
    } finally {
      setLoading(prev => ({ ...prev, [marketType]: false }))
    }
  }

  const select = (marketType: string, cat: string) => {
    const updated = { ...cats, [marketType]: cat }
    setCats(updated)
    setSuggestions(prev => ({ ...prev, [marketType]: [] }))
    setQueries(prev => ({ ...prev, [marketType]: cat }))
    onSave(updated)
  }

  if (accounts.length === 0) {
    return <p style={{ fontSize: 12, color: c.textMuted, padding: '8px 0' }}>등록된 판매처 계정이 없습니다.</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(groups).map(([marketType, accs]) => {
        return (
          <div
            key={marketType}
            style={{ background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: 6, padding: 8 }}
          >
            {/* 헤더: 판매처명 */}
            <p style={{ fontSize: 11, color: c.textSub, margin: '0 0 6px 0' }}>{marketType}</p>

            {/* 카테고리 검색 (판매처 단위) */}
            <div style={{ position: 'relative' }}>
              <input
                value={queries[marketType] ?? cats[marketType] ?? ''}
                onChange={e => search(marketType, e.target.value)}
                placeholder='카테고리 검색...'
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  background: c.inputBg,
                  border: `1px solid ${c.border}`,
                  borderRadius: 4,
                  fontSize: 13,
                  color: c.text,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
              />
              {loading[marketType] && (
                <span style={{ position: 'absolute', right: 8, top: 8, fontSize: 11, color: c.textSub }}>
                  검색 중
                </span>
              )}
              {(suggestions[marketType] ?? []).length > 0 && (
                <ul
                  style={{
                    position: 'absolute',
                    zIndex: 50,
                    width: '100%',
                    background: c.surface,
                    border: `1px solid ${c.border}`,
                    borderRadius: 4,
                    maxHeight: 160,
                    overflowY: 'auto',
                    fontSize: 13,
                    listStyle: 'none',
                    padding: 0,
                    margin: 0,
                    marginTop: 4,
                    boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
                  }}
                >
                  {suggestions[marketType].map((cat, i) => (
                    <li
                      key={i}
                      onClick={() => select(marketType, cat)}
                      style={{ padding: '7px 12px', color: c.text, cursor: 'pointer' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLLIElement).style.background = c.surfaceAlt }}
                      onMouseLeave={e => { (e.currentTarget as HTMLLIElement).style.background = 'transparent' }}
                    >
                      {cat}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {cats[marketType] && (
              <p style={{ fontSize: 11, color: c.textSub, marginTop: 4 }}>선택됨: {cats[marketType]}</p>
            )}

            {/* 계정별 등록상품 버튼 */}
            {marketProductNos && accs.some(a => !!marketProductNos[a.id]) && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
                {accs.map(acc => {
                  const productNo = marketProductNos[acc.id]
                  if (!productNo) return null
                  const marketUrl = getMarketProductUrl(acc.market_type, productNo, {
                    pid: marketProductNos[`${acc.id}_pid`],
                    vid: marketProductNos[`${acc.id}_vid`],
                  })
                  const isDeleting = deletingAccountId === acc.id
                  return (
                    <div key={acc.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontSize: 11, color: c.textSub, flex: 1 }}>{acc.account_name}</span>
                      {marketUrl && (
                        <button
                          onClick={() => window.open(marketUrl, '_blank')}
                          style={{ ...btn('secondary'), padding: '2px 8px', fontSize: 11, whiteSpace: 'nowrap' }}
                        >
                          구매페이지
                        </button>
                      )}
                      {onDeleteFromMarket && (
                        <button
                          onClick={() => !isDeleting && onDeleteFromMarket(acc.id)}
                          disabled={isDeleting}
                          style={{ ...btn('danger'), padding: '2px 8px', fontSize: 11, whiteSpace: 'nowrap', ...(isDeleting ? btnDisabled : null) }}
                        >
                          {isDeleting ? '삭제 중...' : '마켓삭제'}
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

'use client'

import { useState } from 'react'
import { categoryApi } from '@/lib/samba/legacy'

interface Account {
  id: string
  market_type: string
  account_name: string
}

interface Props {
  accounts: Account[]
  savedCategories: Record<string, string>
  onSave: (categories: Record<string, string>) => void
}

export default function CategorySelector({ accounts, savedCategories, onSave }: Props) {
  const [cats, setCats] = useState<Record<string, string>>(savedCategories)
  const [queries, setQueries] = useState<Record<string, string>>({})
  const [suggestions, setSuggestions] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState<Record<string, boolean>>({})

  const search = async (accountId: string, marketType: string, q: string) => {
    setQueries(prev => ({ ...prev, [accountId]: q }))
    if (!q.trim()) {
      setSuggestions(prev => ({ ...prev, [accountId]: [] }))
      return
    }
    setLoading(prev => ({ ...prev, [accountId]: true }))
    try {
      const result = await categoryApi.suggest(q, marketType)
      const list = Array.isArray(result) ? (result as string[]) : []
      setSuggestions(prev => ({ ...prev, [accountId]: list }))
    } catch {
      setSuggestions(prev => ({ ...prev, [accountId]: [] }))
    } finally {
      setLoading(prev => ({ ...prev, [accountId]: false }))
    }
  }

  const select = (accountId: string, cat: string) => {
    const updated = { ...cats, [accountId]: cat }
    setCats(updated)
    setSuggestions(prev => ({ ...prev, [accountId]: [] }))
    setQueries(prev => ({ ...prev, [accountId]: cat }))
    onSave(updated)
  }

  if (accounts.length === 0) {
    return <p style={{ fontSize: 12, color: '#444', padding: '8px 0' }}>등록된 판매처 계정이 없습니다.</p>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {accounts.map(acc => (
        <div
          key={acc.id}
          style={{ background: '#0A0A0A', border: '1px solid #1A1A1A', borderRadius: 6, padding: 8 }}
        >
          <p style={{ fontSize: 11, color: '#666', marginBottom: 4 }}>
            {acc.market_type} · {acc.account_name}
          </p>
          <div style={{ position: 'relative' }}>
            <input
              value={queries[acc.id] ?? cats[acc.id] ?? ''}
              onChange={e => search(acc.id, acc.market_type, e.target.value)}
              placeholder='카테고리 검색...'
              style={{
                width: '100%',
                padding: '6px 10px',
                background: '#0A0A0A',
                border: '1px solid #2D2D2D',
                borderRadius: 4,
                fontSize: 13,
                color: '#E5E5E5',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            {loading[acc.id] && (
              <span style={{ position: 'absolute', right: 8, top: 8, fontSize: 11, color: '#666' }}>
                검색 중
              </span>
            )}
            {(suggestions[acc.id] ?? []).length > 0 && (
              <ul
                style={{
                  position: 'absolute',
                  zIndex: 50,
                  width: '100%',
                  background: '#111',
                  border: '1px solid #2D2D2D',
                  borderRadius: 4,
                  marginTop: 2,
                  maxHeight: 160,
                  overflowY: 'auto',
                  fontSize: 13,
                  listStyle: 'none',
                  padding: 0,
                  margin: 0,
                  marginTop: 4,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                }}
              >
                {suggestions[acc.id].map((cat, i) => (
                  <li
                    key={i}
                    onClick={() => select(acc.id, cat)}
                    style={{ padding: '7px 12px', color: '#E5E5E5', cursor: 'pointer' }}
                    onMouseEnter={e => { (e.currentTarget as HTMLLIElement).style.background = '#1A1A1A' }}
                    onMouseLeave={e => { (e.currentTarget as HTMLLIElement).style.background = 'transparent' }}
                  >
                    {cat}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {cats[acc.id] && (
            <p style={{ fontSize: 11, color: '#FF8C00', marginTop: 4 }}>선택됨: {cats[acc.id]}</p>
          )}
        </div>
      ))}
    </div>
  )
}

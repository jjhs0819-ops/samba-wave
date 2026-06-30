'use client'

import { useState } from 'react'
import { categoryApi } from '@/lib/samba/api/commerce'

interface MappingMarketRowProps {
  marketType: string
  marketName: string
  value: string
  onChange: (v: string) => void
  onClear: () => void
}

// 매핑 모달 — 마켓별 카테고리 입력 + 자동완성
export default function MappingMarketRow({ marketType, marketName, value, onChange, onClear }: MappingMarketRowProps) {
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSugg, setShowSugg] = useState(false)
  return (
    <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px', position: 'relative' }}>
      <span style={{ fontSize: '0.8rem', color: '#888', minWidth: '100px' }}>{marketName}</span>
      <div style={{ flex: 1, position: 'relative' }}>
        <input
          type='text'
          value={value}
          onChange={async e => {
            const val = e.target.value
            onChange(val)
            if (val.length >= 2) {
              try {
                const res = await categoryApi.suggest(val, marketType)
                setSuggestions(Array.isArray(res) ? res.slice(0, 8) : [])
                setShowSugg(true)
              } catch { setSuggestions([]) }
            } else { setSuggestions([]); setShowSugg(false) }
          }}
          onFocus={() => { if (suggestions.length > 0) setShowSugg(true) }}
          onBlur={() => setTimeout(() => setShowSugg(false), 200)}
          placeholder='카테고리 검색 (2자 이상 입력)'
          style={{ width: '100%', fontSize: '0.78rem', padding: '5px 10px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', outline: 'none' }}
        />
        {showSugg && suggestions.length > 0 && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10, background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', maxHeight: '200px', overflowY: 'auto', marginTop: '2px' }}>
            {suggestions.map((s, i) => (
              <div key={i}
                onMouseDown={() => { onChange(s); setShowSugg(false) }}
                style={{ padding: '6px 10px', fontSize: '0.72rem', color: '#C5C5C5', cursor: 'pointer', borderBottom: i < suggestions.length - 1 ? '1px solid #2D2D2D' : 'none' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,140,0,0.1)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              >{s}</div>
            ))}
          </div>
        )}
      </div>
      {value && (
        <button onClick={onClear}
          style={{ color: '#666', cursor: 'pointer', background: 'none', border: 'none', fontSize: '1rem' }}>&times;</button>
      )}
    </div>
  )
}

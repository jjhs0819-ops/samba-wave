'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { fmtNum } from '@/lib/samba/styles'

interface Props {
  totalCount: number
  pageSize: number
  currentPage: number
  setCurrentPage: Dispatch<SetStateAction<number>>
}

export default function OrdersPagination({ totalCount, pageSize, currentPage, setCurrentPage }: Props) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const pages: (number | string)[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    pages.push(1)
    if (currentPage > 3) pages.push('...')
    for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) pages.push(i)
    if (currentPage < totalPages - 2) pages.push('...')
    pages.push(totalPages)
  }
  const pgBtn = (active: boolean) => ({
    background: active ? '#FF8C00' : 'rgba(30,30,30,0.9)',
    color: active ? '#fff' : '#aaa',
    border: active ? 'none' : '1px solid #333',
    borderRadius: '6px',
    padding: '0.3rem 0.6rem',
    fontSize: '0.75rem',
    cursor: 'pointer' as const,
    minWidth: '32px',
    fontWeight: active ? 600 : 400,
  })

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 0.5rem', borderTop: '1px solid #232323', marginTop: '0.5rem' }}>
      <span style={{ fontSize: '0.75rem', color: '#888', whiteSpace: 'nowrap' }}>
        총 <span style={{ color: '#FF8C00', fontWeight: 600 }}>{fmtNum(totalCount)}</span>건
        {totalCount > pageSize && <> · {fmtNum(currentPage)}/{fmtNum(totalPages)}페이지</>}
      </span>
      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <button style={pgBtn(false)} disabled={currentPage === 1} onClick={() => setCurrentPage(1)}>«</button>
          <button style={pgBtn(false)} disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>‹</button>
          {pages.map((p, i) =>
            typeof p === 'string'
              ? <span key={`dot-${i}`} style={{ color: '#555', padding: '0 4px' }}>…</span>
              : <button key={p} style={pgBtn(p === currentPage)} onClick={() => setCurrentPage(p as number)}>{p}</button>
          )}
          <button style={pgBtn(false)} disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>›</button>
          <button style={pgBtn(false)} disabled={currentPage === totalPages} onClick={() => setCurrentPage(totalPages)}>»</button>
        </div>
      )}
      <div />
    </div>
  )
}

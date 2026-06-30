'use client'

import React, { useState } from 'react'

import { API_BASE_URL } from '@/config/api'

/** 상품 이미지 컴포넌트 — 로드 실패 시 이름 첫 글자 표시. */
const API_BASE = API_BASE_URL

// /static/ 상대 경로를 백엔드 절대 URL로 변환
function resolveImageUrl(url?: string): string | undefined {
  if (!url) return undefined
  if (url.startsWith('/static/')) return `${API_BASE}${url}`
  return url
}

const ProductImage = React.memo(function ProductImage({ src, name, size = 110 }: { src?: string; name: string; size?: number }) {
  const [error, setError] = useState(false)
  const firstChar = (name || '?')[0]
  const resolvedSrc = resolveImageUrl(src)

  if (!resolvedSrc || error) {
    return (
      <div style={{
        width: size, height: size, minWidth: size, borderRadius: '8px',
        border: '1px dashed #3D3D3D', display: 'flex', alignItems: 'center',
        justifyContent: 'center', background: '#1A1A1A',
      }}>
        <span style={{ fontSize: size * 0.45, color: '#FF8C00', fontFamily: 'sans-serif' }}>{firstChar}</span>
      </div>
    )
  }

  return (
    <img
      src={resolvedSrc}
      alt={name}
      loading="lazy"
      onError={() => setError(true)}
      style={{
        width: size, height: size, minWidth: size, objectFit: 'cover',
        borderRadius: '8px', border: '1px solid #2D2D2D',
      }}
    />
  )
})

export default ProductImage

'use client'

import React from 'react'
import { showAlert } from '@/components/samba/Modal'

export const copyableTextStyle: React.CSSProperties = {
  color: '#E5E5E5',
  cursor: 'copy',
  textDecoration: 'underline',
  textDecorationColor: 'rgba(229, 229, 229, 0.35)',
  textUnderlineOffset: '2px',
}

export const handleCopyText = async (value: string | null | undefined) => {
  let text = (value || '').trim()
  text = text.replace(/\([^)]*\)/g, '').trim()
  if (!text) {
    showAlert('복사할 내용이 없습니다', 'info')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    showAlert('복사에 실패했습니다', 'error')
  }
}

export const renderCopyableText = (
  value: string | null | undefined,
  _label?: string,
  style?: React.CSSProperties,
): React.ReactNode => {
  const text = value || '-'
  return (
    <span
      role="button"
      tabIndex={0}
      title="Copy"
      onClick={() => handleCopyText(value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handleCopyText(value)
        }
      }}
      style={{ ...copyableTextStyle, ...style }}
    >
      {text}
    </span>
  )
}

// 우선순위:
//  1) 백엔드가 분리 저장한 detail 컬럼 그대로 사용 (롯데ON/스마트스토어/쿠팡/11번가 신규 데이터)
//  2) 기존 누적 데이터(공백 join 단일 문자열)는 휴리스틱으로 fallback 분리
//     - 첫 번째 `)` 가 우편번호 닫는 괄호일 수 있어 마지막 `)` 우선
//     - 콤마 있으면 콤마 기준
//     - 동/호/층/호실 패턴 fallback
export const splitCustomerAddress = (
  address: string | null | undefined,
  detailColumn?: string | null,
) => {
  const normalized = (address || '').trim().replace(/\s+/g, ' ')
  const detailFromDb = (detailColumn || '').trim().replace(/\s+/g, ' ')

  if (!normalized && !detailFromDb) return { base: '', detail: '' }

  // 1) 백엔드 분리 저장 컬럼 우선
  if (detailFromDb) {
    return { base: normalized, detail: detailFromDb }
  }

  if (!normalized) return { base: '', detail: '' }

  // 2-a) 콤마 구분자 (도로명주소 표준)
  const commaIdx = normalized.indexOf(',')
  if (commaIdx > 0 && commaIdx < normalized.length - 1) {
    return {
      base: normalized.slice(0, commaIdx).trim(),
      detail: normalized.slice(commaIdx + 1).trim(),
    }
  }

  // 2-b) 마지막 `)` 기준 (법정동/건물명 괄호 뒤에 상세주소가 오는 패턴)
  const lastParenIdx = normalized.lastIndexOf(')')
  if (lastParenIdx > 0 && lastParenIdx < normalized.length - 1) {
    return {
      base: normalized.slice(0, lastParenIdx + 1).trim(),
      detail: normalized.slice(lastParenIdx + 1).trim(),
    }
  }

  // 2-c) 동/호/층/호실 패턴
  const detailMatch = normalized.match(/^(.+?)\s+((?:\d+\s*동\s*)?\d+\s*(?:호|층|호실)\b.*)$/)
  if (detailMatch) {
    return { base: detailMatch[1].trim(), detail: detailMatch[2].trim() }
  }

  return { base: normalized, detail: '' }
}

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

export const splitCustomerAddress = (address: string | null | undefined) => {
  const normalized = (address || '').trim().replace(/\s+/g, ' ')
  if (!normalized) return { base: '', detail: '' }

  const parenEndIndex = normalized.indexOf(')')
  if (parenEndIndex >= 0 && parenEndIndex < normalized.length - 1) {
    return {
      base: normalized.slice(0, parenEndIndex + 1).trim(),
      detail: normalized.slice(parenEndIndex + 1).trim(),
    }
  }

  const detailMatch = normalized.match(/^(.+?)\s+((?:\d+\s*동\s*)?\d+\s*(?:호|층|호실)\b.*)$/)
  if (detailMatch) {
    return { base: detailMatch[1].trim(), detail: detailMatch[2].trim() }
  }

  return { base: normalized, detail: '' }
}

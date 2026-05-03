'use client'
import { useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisBrandBlock } from '@/lib/samba/api/tetris'

// ─── 타입 ─────────────────────────────────────────────────────────────────────

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  block: TetrisBrandBlock
  accountId: string
  blockHeight: number
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onRemove: (assignmentId: string, brandName: string) => void
  policies: Policy[]
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
}

// ─── BrandBlock 컴포넌트 ──────────────────────────────────────────────────────

export default function BrandBlock({
  block,
  accountId,
  blockHeight,
  onDragStart,
  onRemove,
  policies,
  onPolicyChange,
}: Props) {
  const [showPolicies, setShowPolicies] = useState(false)
  const color = block.policy_color || '#6B7280'
  const isLegacy = block.is_legacy

  return (
    <div
      draggable
      onDragStart={() => onDragStart(block, accountId)}
      style={{
        height: blockHeight,
        background: isLegacy ? 'rgba(60,60,60,0.6)' : 'rgba(40,40,40,0.8)',
        border: `1px solid ${color}40`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        padding: '4px 6px',
        cursor: 'grab',
        position: 'relative',
        overflow: 'visible',
        marginBottom: 2,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        userSelect: 'none',
      }}
      onClick={() => {
        if (!isLegacy && block.id) setShowPolicies(v => !v)
      }}
    >
      {/* 상단: 소싱처 + 브랜드명 */}
      <div style={{
        fontSize: 11,
        color: '#ccc',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        textOverflow: 'ellipsis',
      }}>
        <span style={{ color: '#888', marginRight: 4 }}>
          {block.source_site.toLowerCase()}
        </span>
        <span style={{ color: '#eee', fontWeight: 600 }}>
          {block.brand_name}
        </span>
        {isLegacy && (
          <span style={{ color: '#888', fontSize: 10, marginLeft: 4 }}>
            (기존 등록)
          </span>
        )}
      </div>

      {/* 하단: 등록/수집 수치 */}
      <div style={{ fontSize: 10, color: '#999' }}>
        등록 {fmtNum(block.registered_count)} / 수집 {fmtNum(block.collected_count)}
      </div>

      {/* X 제거 버튼 (id가 있고 legacy가 아닌 경우만) */}
      {block.id && !isLegacy && (
        <button
          onClick={e => {
            e.stopPropagation()
            onRemove(block.id!, block.brand_name)
          }}
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            background: 'transparent',
            border: 'none',
            color: '#888',
            cursor: 'pointer',
            fontSize: 12,
            padding: '0 2px',
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}

      {/* 정책 선택 드롭다운 */}
      {showPolicies && block.id && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 200,
            background: '#1a1a1a',
            border: '1px solid #333',
            borderRadius: 4,
            boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          }}
          onClick={e => e.stopPropagation()}
        >
          {/* 정책 없음 선택지 */}
          <div
            onClick={() => {
              onPolicyChange(block.id!, null, accountId)
              setShowPolicies(false)
            }}
            style={{
              padding: '6px 8px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              background: block.policy_id === null ? 'rgba(255,140,0,0.1)' : 'transparent',
            }}
          >
            <span style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: '#6B7280',
              display: 'inline-block',
            }} />
            <span style={{ fontSize: 12, color: '#999' }}>정책 없음</span>
          </div>
          {policies.map(p => (
            <div
              key={p.id}
              onClick={() => {
                onPolicyChange(block.id!, p.id, accountId)
                setShowPolicies(false)
              }}
              style={{
                padding: '6px 8px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                background: p.id === block.policy_id ? 'rgba(255,140,0,0.1)' : 'transparent',
              }}
            >
              <span style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: p.color,
                display: 'inline-block',
                flexShrink: 0,
              }} />
              <span style={{ fontSize: 12, color: '#ccc' }}>{p.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

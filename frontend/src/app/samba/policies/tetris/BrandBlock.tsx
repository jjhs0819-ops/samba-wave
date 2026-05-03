'use client'
import { useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisBrandBlock } from '@/lib/samba/api/tetris'

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
  const isCompact = blockHeight <= 44

  // 등록 비율 (0~1) — 해당 계정 기준
  const fillRatio = block.collected_count > 0
    ? Math.min(1, block.registered_count / block.collected_count)
    : 0

  return (
    <div
      draggable
      onDragStart={() => onDragStart(block, accountId)}
      onClick={() => { if (!isLegacy && block.id) setShowPolicies(v => !v) }}
      style={{
        height: blockHeight,
        minHeight: blockHeight,
        background: isLegacy ? 'rgba(50,50,50,0.7)' : 'rgba(28,28,28,0.9)',
        border: `1px solid ${color}50`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        marginBottom: 2,
        cursor: 'grab',
        position: 'relative',
        overflow: 'hidden',
        userSelect: 'none',
        boxSizing: 'border-box',
        flexShrink: 0,
      }}
    >
      {/* 등록 채움 표시 — 하단부터 fillRatio 비율만큼 */}
      {fillRatio > 0 && (
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: `${fillRatio * 100}%`,
          background: `${color}28`,
          pointerEvents: 'none',
        }} />
      )}

      {/* 텍스트 레이어 */}
      <div style={{
        position: 'relative',
        height: '100%',
        padding: isCompact ? '3px 20px 3px 6px' : '4px 20px 4px 6px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}>
        {/* 브랜드명 */}
        <div style={{
          fontSize: 11,
          color: '#ddd',
          fontWeight: 600,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
        }}>
          {block.brand_name}
          {isLegacy && <span style={{ color: '#666', fontSize: 9, marginLeft: 4 }}>기존</span>}
        </div>

        {/* 등록/수집 카운트 */}
        <div style={{ fontSize: isCompact ? 9 : 10, lineHeight: 1.1 }}>
          <span style={{ color: fillRatio >= 1 ? '#22C55E' : fillRatio > 0 ? '#F59E0B' : '#666' }}>
            {fmtNum(block.registered_count)}
          </span>
          <span style={{ color: '#444' }}>/</span>
          <span style={{ color: '#888' }}>{fmtNum(block.collected_count)}</span>
        </div>
      </div>

      {/* 소싱처 라벨 (우측 하단) */}
      {!isCompact && (
        <div style={{
          position: 'absolute',
          bottom: 2,
          right: block.id && !isLegacy ? 18 : 4,
          fontSize: 9,
          color: '#444',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
        }}>
          {block.source_site}
        </div>
      )}

      {/* 제거 버튼 */}
      {block.id && !isLegacy && (
        <button
          onClick={e => { e.stopPropagation(); onRemove(block.id!, block.brand_name) }}
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            background: 'transparent',
            border: 'none',
            color: '#666',
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
          <div
            onClick={() => { onPolicyChange(block.id!, null, accountId); setShowPolicies(false) }}
            style={{ padding: '6px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, background: block.policy_id === null ? 'rgba(255,140,0,0.1)' : 'transparent' }}
          >
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#6B7280', display: 'inline-block' }} />
            <span style={{ fontSize: 12, color: '#999' }}>정책 없음</span>
          </div>
          {policies.map(p => (
            <div
              key={p.id}
              onClick={() => { onPolicyChange(block.id!, p.id, accountId); setShowPolicies(false) }}
              style={{ padding: '6px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, background: p.id === block.policy_id ? 'rgba(255,140,0,0.1)' : 'transparent' }}
            >
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: p.color, display: 'inline-block', flexShrink: 0 }} />
              <span style={{ fontSize: 12, color: '#ccc' }}>{p.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

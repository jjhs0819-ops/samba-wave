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
  onRemove: (assignmentId: string, brandName: string, sourceSite: string) => void
  onDeleteBrandScope: (sourceSite: string, brandName: string) => Promise<void>
  policies: Policy[]
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
}

export default function BrandBlock({
  block,
  accountId,
  blockHeight,
  onDragStart,
  onRemove,
  onDeleteBrandScope,
  policies,
  onPolicyChange,
}: Props) {
  const [showPolicies, setShowPolicies] = useState(false)
  const color = block.policy_color || '#6B7280'
  const isLegacy = block.is_legacy
  const brandColor = block.ai_tagged_count > 0 ? '#ddd' : '#EF4444'

  const fillRatio = block.collected_count > 0
    ? Math.min(1, block.registered_count / block.collected_count)
    : 0

  return (
    <div
      draggable
      onDragStart={e => { e.stopPropagation(); onDragStart(block, accountId) }}
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
      {fillRatio > 0 && (
        <div
          style={{
            position: 'absolute',
            bottom: 0,
            left: 0,
            right: 0,
            height: `${fillRatio * 100}%`,
            background: `${color}28`,
            pointerEvents: 'none',
          }}
        />
      )}

      <div
        style={{
          position: 'relative',
          height: '100%',
          padding: '2px 18px 2px 6px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          gap: 1,
        }}
      >
        {/* 상단: 브랜드명 + 등록/수집 수 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            minWidth: 0,
            lineHeight: 1.05,
          }}
        >
          <div
            style={{
              minWidth: 0,
              flex: '1 1 auto',
              fontSize: 10,
              color: brandColor,
              fontWeight: 600,
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              textOverflow: 'ellipsis',
            }}
          >
            {block.brand_name}
            {isLegacy && <span style={{ color: '#666', fontSize: 9, marginLeft: 4 }}>legacy</span>}
          </div>
          <div style={{ flexShrink: 0, fontSize: 9, whiteSpace: 'nowrap' }}>
            <span style={{ color: fillRatio >= 1 ? '#22C55E' : fillRatio > 0 ? '#F59E0B' : '#666' }}>
              {fmtNum(block.registered_count)}
            </span>
            <span style={{ color: '#444' }}>/</span>
            <span style={{ color: '#888' }}>{fmtNum(block.collected_count)}</span>
          </div>
        </div>
        {/* 하단: 소싱처명 우측 정렬 */}
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'flex-end',
        }}>
          <span style={{
            fontSize: 9,
            color: '#fff',
            fontWeight: 500,
            whiteSpace: 'nowrap',
            opacity: 0.7,
          }}>
            {block.source_site}
          </span>
        </div>
      </div>

      {(
        <button
          onClick={async e => {
            e.stopPropagation()
            if (block.id) {
              onRemove(block.id, block.brand_name, block.source_site)
              return
            }
            await onDeleteBrandScope(block.source_site, block.brand_name)
          }}
          title="이 계정에서 삭제"
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            width: 16,
            height: 16,
            borderRadius: 4,
            background: 'rgba(239,68,68,0.16)',
            border: '1px solid rgba(239,68,68,0.35)',
            color: '#FCA5A5',
            cursor: 'pointer',
            fontSize: 11,
            fontWeight: 700,
            padding: 0,
            lineHeight: '14px',
          }}
        >
          x
        </button>
      )}

      {showPolicies && block.id && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 200,
            background: '#1a1a1a',
            border: '1px solid #333',
            borderRadius: 6,
            padding: '6px 8px',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.6)',
            whiteSpace: 'nowrap',
          }}
          onClick={e => e.stopPropagation()}
        >
          <div
            onClick={() => { onPolicyChange(block.id!, null, accountId); setShowPolicies(false) }}
            title="clear policy"
            style={{
              width: 16,
              height: 16,
              borderRadius: '50%',
              background: '#6B7280',
              cursor: 'pointer',
              border: block.policy_id === null ? '2px solid #fff' : '2px solid transparent',
              flexShrink: 0,
            }}
          />
          {policies.map(p => (
            <div
              key={p.id}
              onClick={() => { onPolicyChange(block.id!, p.id, accountId); setShowPolicies(false) }}
              title={p.name}
              style={{
                width: 16,
                height: 16,
                borderRadius: '50%',
                background: p.color,
                cursor: 'pointer',
                border: p.id === block.policy_id ? '2px solid #fff' : '2px solid transparent',
                flexShrink: 0,
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

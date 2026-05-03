'use client'
import { useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import BrandBlock from './BrandBlock'
import type { TetrisAccountBlock, TetrisBrandBlock } from '@/lib/samba/api/tetris'

// ─── 타입 ─────────────────────────────────────────────────────────────────────

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  account: TetrisAccountBlock
  blockHeight: number
  policies: Policy[]
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onRemove: (assignmentId: string, brandName: string) => void
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
  isDragging: boolean
}

// ─── AccountBlock 컴포넌트 ────────────────────────────────────────────────────

export default function AccountBlock({
  account,
  blockHeight,
  policies,
  onDragStart,
  onDrop,
  onRemove,
  onPolicyChange,
  isDragging,
}: Props) {
  const [isOver, setIsOver] = useState(false)

  // 등록 비율로 진행바 색상 결정
  const ratio = account.max_count > 0
    ? account.total_registered / account.max_count
    : 0
  const progressColor = ratio >= 1
    ? '#EF4444'   // 초과: 빨강
    : ratio >= 0.8
    ? '#F59E0B'   // 여유 적음: 주황
    : '#22C55E'   // 여유: 초록

  // 계정 내부 목록 높이: 블럭 수 × (블럭높이 + 마진) + 최소 높이
  const listMinHeight = Math.max(
    (account.max_count > 0 ? account.max_count : 4) * (blockHeight + 2),
    80,
  )

  return (
    <div
      style={{
        background: isOver && isDragging
          ? 'rgba(255,140,0,0.08)'
          : 'rgba(25,25,25,0.6)',
        border: isOver && isDragging
          ? '1px dashed #FF8C00'
          : '1px solid #2a2a2a',
        borderRadius: 6,
        marginBottom: 8,
        transition: 'background 0.15s, border 0.15s',
      }}
      onDragOver={e => {
        e.preventDefault()
        setIsOver(true)
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={async () => {
        setIsOver(false)
        await onDrop(account.account_id)
      }}
    >
      {/* 헤더 */}
      <div style={{
        padding: '6px 8px',
        borderBottom: '1px solid #2a2a2a',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8,
      }}>
        <span style={{ fontSize: 12, color: '#ccc', fontWeight: 600, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
          {account.account_label}
        </span>
        <span style={{ fontSize: 10, color: '#888', whiteSpace: 'nowrap', flexShrink: 0 }}>
          <span style={{ color: progressColor }}>{fmtNum(account.total_registered)}</span>
          {account.max_count > 0 && (
            <span>/{fmtNum(account.max_count)}</span>
          )}
          {' '}수집 {fmtNum(account.total_collected)}
        </span>
      </div>

      {/* 진행바 */}
      {account.max_count > 0 && (
        <div style={{ height: 2, background: '#2a2a2a' }}>
          <div style={{
            height: '100%',
            width: `${Math.min(ratio * 100, 100)}%`,
            background: progressColor,
            transition: 'width 0.3s',
          }} />
        </div>
      )}

      {/* 블럭 목록 */}
      <div style={{
        padding: '4px 6px',
        minHeight: listMinHeight,
        overflowY: 'auto',
      }}>
        {account.assignments.map((block, idx) => (
          <BrandBlock
            key={block.id ?? `legacy-${idx}`}
            block={block}
            accountId={account.account_id}
            blockHeight={blockHeight}
            onDragStart={onDragStart}
            onRemove={onRemove}
            policies={policies}
            onPolicyChange={onPolicyChange}
          />
        ))}
        {account.assignments.length === 0 && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: 60,
            color: '#444',
            fontSize: 11,
          }}>
            {isDragging ? '여기에 드롭하세요' : '배치된 브랜드 없음'}
          </div>
        )}
      </div>
    </div>
  )
}

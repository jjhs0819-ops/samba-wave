'use client'
import AccountBlock from './AccountBlock'
import type { TetrisMarketGroup, TetrisBrandBlock } from '@/lib/samba/api/tetris'
import type { DragState } from './useTetris'

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  market: TetrisMarketGroup
  pixelsPerUnit: number
  globalMax: number
  policies: Policy[]
  dragState: DragState
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onReorder: (draggedId: string, newIndex: number, allAssignments: TetrisBrandBlock[]) => Promise<void>
  onRemove: (assignmentId: string, brandName: string) => void
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
}

const MIN_ACCOUNT_HEIGHT = 120

export default function MarketColumn({
  market,
  pixelsPerUnit,
  globalMax,
  policies,
  dragState,
  onDragStart,
  onDrop,
  onReorder,
  onRemove,
  onPolicyChange,
}: Props) {
  return (
    <div style={{ minWidth: 220, width: 240, flexShrink: 0 }}>
      {/* 계정 목록 */}
      <div style={{
        background: 'rgba(20,20,20,0.5)',
        border: '1px solid #333',
        borderRadius: 6,
        padding: '8px 6px',
      }}>
        {market.accounts.map(account => {
          const capacityHeight = account.max_count > 0
            ? Math.max(MIN_ACCOUNT_HEIGHT, Math.round(account.max_count * pixelsPerUnit))
            : Math.max(MIN_ACCOUNT_HEIGHT, Math.round(globalMax * pixelsPerUnit * 0.15))

          return (
            <AccountBlock
              key={account.account_id}
              account={account}
              capacityHeight={capacityHeight}
              pixelsPerUnit={pixelsPerUnit}
              policies={policies}
              dragState={dragState}
              onDragStart={onDragStart}
              onDrop={onDrop}
              onReorder={onReorder}
              onRemove={onRemove}
              onPolicyChange={onPolicyChange}
              isDragging={dragState !== null}
            />
          )
        })}
        {market.accounts.length === 0 && (
          <div style={{ color: '#444', fontSize: 11, padding: '12px 0', textAlign: 'center' }}>계정 없음</div>
        )}
      </div>
    </div>
  )
}

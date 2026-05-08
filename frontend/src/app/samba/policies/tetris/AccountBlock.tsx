'use client'
import { useMemo, useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import BrandBlock from './BrandBlock'
import type { TetrisAccountBlock, TetrisBrandBlock } from '@/lib/samba/api/tetris'
import type { DragState } from './useTetris'

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  account: TetrisAccountBlock
  capacityHeight: number
  pixelsPerUnit: number
  policies: Policy[]
  dragState: DragState
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onReorder: (draggedId: string, newIndex: number, allAssignments: TetrisBrandBlock[]) => Promise<void>
  onRemove: (assignmentId: string, brandName: string, sourceSite: string) => void
  onDeleteBrandScope: (sourceSite: string, brandName: string) => Promise<void>
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
  isDragging: boolean
  isAccountDragging: boolean
  onAccountDragStart: (accountId: string) => void
  onAccountDragEnd: () => void
}

function SlotZone({
  active,
  onEnter,
  onLeave,
  onDrop,
}: {
  active: boolean
  onEnter: () => void
  onLeave: () => void
  onDrop: () => void
}) {
  return (
    <div
      style={{
        height: active ? 6 : 2,
        background: active ? '#FF8C00' : 'rgba(255,140,0,0.15)',
        borderRadius: 2,
        margin: '1px 0',
        flexShrink: 0,
        transition: 'height 0.1s, background 0.1s',
      }}
      onDragOver={e => { e.preventDefault(); e.stopPropagation(); onEnter() }}
      onDragLeave={onLeave}
      onDrop={e => { e.stopPropagation(); onDrop() }}
    />
  )
}

const MIN_BLOCK_PX = 24

export default function AccountBlock({
  account,
  capacityHeight,
  pixelsPerUnit,
  policies,
  dragState,
  onDragStart,
  onDrop,
  onReorder,
  onRemove,
  onDeleteBrandScope,
  onPolicyChange,
  isDragging,
  isAccountDragging,
  onAccountDragStart,
  onAccountDragEnd,
}: Props) {
  const [isOver, setIsOver] = useState(false)
  const [dropSlot, setDropSlot] = useState<number | null>(null)
  const [isThisBeingDragged, setIsThisBeingDragged] = useState(false)

  const isSameAccountDrag =
    dragState !== null &&
    dragState.fromAccountId === account.account_id

  const ratio = account.total_collected > 0
    ? account.total_registered / account.total_collected
    : 0
  const progressColor = ratio >= 1 ? '#EF4444' : ratio >= 0.8 ? '#F59E0B' : '#22C55E'

  const blocksWithHeight = useMemo(() => {
    const items = account.assignments.map(block => ({
      block,
      height: block.collected_count > 0
        ? Math.max(MIN_BLOCK_PX, Math.round(block.collected_count * pixelsPerUnit))
        : MIN_BLOCK_PX,
    }))
    return { items }
  }, [account.assignments, pixelsPerUnit])

  const handleSlotDrop = async (slotIndex: number) => {
    setDropSlot(null)
    if (!dragState?.assignmentId) return
    await onReorder(dragState.assignmentId, slotIndex, account.assignments)
  }

  return (
    <div
      draggable
      onDragStart={e => {
        e.stopPropagation()
        setIsThisBeingDragged(true)
        onAccountDragStart(account.account_id)
      }}
      onDragEnd={() => {
        setIsThisBeingDragged(false)
        onAccountDragEnd()
      }}
      style={{
        position: 'relative',
        height: capacityHeight,
        minHeight: capacityHeight,
        background: isOver && isDragging && !isSameAccountDrag ? 'rgba(255,140,0,0.08)' : 'rgba(25,25,25,0.6)',
        borderRadius: 6,
        transition: 'background 0.15s, opacity 0.15s',
        overflow: 'hidden',
        boxSizing: 'border-box',
        opacity: isThisBeingDragged ? 0.4 : 1,
        cursor: isThisBeingDragged ? 'grabbing' : 'grab',
      }}
      onDragOver={e => { if (isAccountDragging || isSameAccountDrag) return; e.preventDefault(); setIsOver(true) }}
      onDragLeave={() => setIsOver(false)}
      onDrop={async () => { if (isAccountDragging || isSameAccountDrag) return; setIsOver(false); await onDrop(account.account_id) }}
    >
      {isOver && isDragging && !isAccountDragging && !isSameAccountDrag && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            border: '1px dashed #FF8C00',
            borderRadius: 6,
            pointerEvents: 'none',
            boxSizing: 'border-box',
          }}
        />
      )}

      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: `${Math.min(ratio * 100, 100)}%`,
          height: 2,
          background: progressColor,
          transition: 'width 0.3s',
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          zIndex: 2,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 2,
          pointerEvents: 'none',
        }}
      >
        <div style={{ fontSize: 12, color: '#eee', fontWeight: 600, maxWidth: 190, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
          {account.account_label}
        </div>
        <div style={{ fontSize: 10, color: '#888', whiteSpace: 'nowrap' }}>
          <span style={{ color: progressColor }}>{fmtNum(account.total_registered)}</span>
          <span>/{fmtNum(account.total_collected)}</span>
        </div>
      </div>


      <div
        style={{
          height: '100%',
          background: 'rgba(16,16,16,0.8)',
          padding: '8px 6px 6px',
          display: 'flex',
          flexDirection: 'column',
          boxSizing: 'border-box',
        }}
      >
        {account.assignments.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#444', fontSize: 11 }}>
            {isDragging && !isSameAccountDrag && !isAccountDragging ? 'Drop a brand here' : 'No assigned brands'}
          </div>
        ) : (
          <>
            <div style={{ flex: 1 }} />
            {isSameAccountDrag && !isAccountDragging && (
              <SlotZone
                active={dropSlot === 0}
                onEnter={() => setDropSlot(0)}
                onLeave={() => setDropSlot(null)}
                onDrop={() => handleSlotDrop(0)}
              />
            )}
            {[...blocksWithHeight.items]
              .sort((a, b) => a.block.collected_count - b.block.collected_count)
              .map((item, idx) => (
                <div key={item.block.id ?? `legacy-${idx}`}>
                  <BrandBlock
                    block={item.block}
                    accountId={account.account_id}
                    blockHeight={item.height}
                    onDragStart={onDragStart}
                    onRemove={onRemove}
                    onDeleteBrandScope={onDeleteBrandScope}
                    policies={policies}
                    onPolicyChange={onPolicyChange}
                  />
                  {isSameAccountDrag && !isAccountDragging && !item.block.is_legacy && item.block.id && (
                    <SlotZone
                      active={dropSlot === idx + 1}
                      onEnter={() => setDropSlot(idx + 1)}
                      onLeave={() => setDropSlot(null)}
                      onDrop={() => handleSlotDrop(idx + 1)}
                    />
                  )}
                </div>
              ))}
          </>
        )}
      </div>
    </div>
  )
}

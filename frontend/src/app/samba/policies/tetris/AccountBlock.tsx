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
  capacityHeight: number     // 계정 블록 영역 전체 높이 (px)
  pixelsPerUnit: number      // 수량 1개 당 픽셀 (블록 높이 계산용)
  policies: Policy[]
  dragState: DragState
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onReorder: (draggedId: string, newIndex: number, allAssignments: TetrisBrandBlock[]) => Promise<void>
  onRemove: (assignmentId: string, brandName: string) => void
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
  isDragging: boolean
}

// ─── 슬롯 드롭존 ──────────────────────────────────────────────────────────────

function SlotZone({ active, onEnter, onLeave, onDrop }: {
  active: boolean
  onEnter: () => void
  onLeave: () => void
  onDrop: () => void
}) {
  return (
    <div
      style={{
        height: active ? 8 : 4,
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

// ─── AccountBlock ─────────────────────────────────────────────────────────────

const MIN_BLOCK_PX = 28  // 블록 최소 픽셀 높이

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
  onPolicyChange,
  isDragging,
}: Props) {
  const [isOver, setIsOver] = useState(false)
  const [dropSlot, setDropSlot] = useState<number | null>(null)

  const isSameAccountDrag =
    dragState !== null &&
    dragState.fromAccountId === account.account_id &&
    dragState.assignmentId !== null

  const validAssignments = useMemo(
    () => account.assignments.filter(b => !b.is_legacy && b.id),
    [account.assignments]
  )

  const ratio = account.max_count > 0 ? account.total_registered / account.max_count : 0
  const progressColor = ratio >= 1 ? '#EF4444' : ratio >= 0.8 ? '#F59E0B' : '#22C55E'

  // 각 브랜드 블록의 픽셀 높이 = collected_count × pixelsPerUnit (최소 MIN_BLOCK_PX)
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
      style={{
        background: isOver && isDragging && !isSameAccountDrag ? 'rgba(255,140,0,0.08)' : 'rgba(25,25,25,0.6)',
        border: isOver && isDragging && !isSameAccountDrag ? '1px dashed #FF8C00' : '1px solid #2a2a2a',
        borderRadius: 6,
        marginBottom: 8,
        transition: 'background 0.15s, border 0.15s',
      }}
      onDragOver={e => { if (isSameAccountDrag) return; e.preventDefault(); setIsOver(true) }}
      onDragLeave={() => setIsOver(false)}
      onDrop={async () => { if (isSameAccountDrag) return; setIsOver(false); await onDrop(account.account_id) }}
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
          {account.max_count > 0 && <span>/{fmtNum(account.max_count)}</span>}
          {' '}수집 {fmtNum(account.total_collected)}
        </span>
      </div>

      {/* 진행바 */}
      {account.max_count > 0 && (
        <div style={{ height: 2, background: '#2a2a2a' }}>
          <div style={{ height: '100%', width: `${Math.min(ratio * 100, 100)}%`, background: progressColor, transition: 'width 0.3s' }} />
        </div>
      )}

      {/* 블록 영역 */}
      <div style={{ padding: '6px' }}>
        <div style={{
          height: capacityHeight,
          minHeight: capacityHeight,
          background: 'rgba(16,16,16,0.8)',
          border: '1px solid #1f1f1f',
          borderRadius: 4,
          padding: 6,
          display: 'flex',
          flexDirection: 'column',
          overflowY: 'auto',
          boxSizing: 'border-box',
        }}>
          {account.assignments.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#444', fontSize: 11 }}>
              {isDragging && !isSameAccountDrag ? '여기에 드롭하세요' : '배치된 브랜드 없음'}
            </div>
          ) : (
            <>
              {/* spacer: 블록을 하단으로 밀어내는 빈 공간 */}
              <div style={{ flex: 1 }} />

              {/* 드래그 중 최상단 슬롯 */}
              {isSameAccountDrag && (
                <SlotZone
                  active={dropSlot === 0}
                  onEnter={() => setDropSlot(0)}
                  onLeave={() => setDropSlot(null)}
                  onDrop={() => handleSlotDrop(0)}
                />
              )}
              {/* 등록수 오름차순 정렬 → 많이 등록된 브랜드가 하단에 */}
              {[...blocksWithHeight.items]
                .sort((a, b) => a.block.registered_count - b.block.registered_count)
                .map((item, idx) => (
                  <div key={item.block.id ?? `legacy-${idx}`}>
                    <BrandBlock
                      block={item.block}
                      accountId={account.account_id}
                      blockHeight={item.height}
                      onDragStart={onDragStart}
                      onRemove={onRemove}
                      policies={policies}
                      onPolicyChange={onPolicyChange}
                    />
                    {isSameAccountDrag && !item.block.is_legacy && item.block.id && (
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
    </div>
  )
}

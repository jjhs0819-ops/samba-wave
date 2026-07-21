'use client'
import { useMemo, useState } from 'react'
import AccountBlock from './AccountBlock'
import type { TetrisAccountBlock, TetrisMarketGroup, TetrisBrandBlock } from '@/lib/samba/api/tetris'
import type { DragState } from './useTetris'
import { useTheme } from '@/lib/samba/useTheme'

interface Policy {
  id: string
  name: string
  color: string
}

// 계정 박스 실제 픽셀 높이 — AccountBlock 의 블록 높이 계산(MIN_BLOCK_PX=24 + marginBottom 2)과
// 동일 기준. TetrisBoard 가 보드 전체 높이(가장 긴 컬럼)를 구할 때도 이 함수를 써야
// 컬럼별 바닥선이 어긋나지 않는다 (블록 최소 24px 보장 때문에 눈금 높이와 픽셀 높이가 다름)
const MIN_BLOCK_PX = 24
export function accountPixelHeight(account: TetrisAccountBlock, pixelsPerUnit: number): number {
  const scaledCapacityHeight = account.max_count > 0
    ? Math.max(1, Math.round(account.max_count * pixelsPerUnit))
    : 0
  const baseCapacity = scaledCapacityHeight > 0
    ? scaledCapacityHeight
    : account.total_collected > 0
      ? Math.max(1, Math.round(account.total_collected * pixelsPerUnit))
      : 60
  const blocksTotalHeight = account.assignments.reduce((sum, b) =>
    sum + (b.collected_count > 0
      ? Math.max(MIN_BLOCK_PX, Math.round(b.collected_count * pixelsPerUnit))
      : MIN_BLOCK_PX) + 2, 0)
  return Math.max(baseCapacity, blocksTotalHeight + 16)
}

export function columnPixelHeight(accounts: TetrisAccountBlock[], pixelsPerUnit: number): number {
  return accounts.reduce((sum, a) => sum + accountPixelHeight(a, pixelsPerUnit), 0)
}

interface Props {
  market: TetrisMarketGroup
  pixelsPerUnit: number
  boardHeight: number
  policies: Policy[]
  dragState: DragState
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onReorder: (draggedId: string, newIndex: number, allAssignments: TetrisBrandBlock[]) => Promise<void>
  onAccountReorder: (accounts: TetrisAccountBlock[]) => Promise<void>
  onRemove: (assignmentId: string, brandName: string, sourceSite: string) => void
  onDeleteBrandScope: (sourceSite: string, brandName: string) => Promise<void>
  onRemoveLegacyFromAccount: (sourceSite: string, brandName: string, accountId: string) => Promise<void>
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
  onToggleExcluded: (block: TetrisBrandBlock, accountId: string) => Promise<void>
  onToggleAccountExcluded: (accountId: string, currentExcluded: boolean) => Promise<void>
}

function AccountSlot({
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
  const c = useTheme()
  return (
    <div
      style={{
        height: active ? 10 : 4,
        background: active ? c.primary : c.accentBg,
        borderRadius: 3,
        margin: '2px 0',
        transition: 'height 0.1s, background 0.1s',
        flexShrink: 0,
      }}
      onDragOver={e => { e.preventDefault(); e.stopPropagation(); onEnter() }}
      onDragLeave={onLeave}
      onDrop={e => { e.preventDefault(); e.stopPropagation(); onDrop() }}
    />
  )
}

export default function MarketColumn({
  market,
  pixelsPerUnit,
  boardHeight,
  policies,
  dragState,
  onDragStart,
  onDrop,
  onReorder,
  onAccountReorder,
  onRemove,
  onDeleteBrandScope,
  onRemoveLegacyFromAccount,
  onPolicyChange,
  onToggleExcluded,
  onToggleAccountExcluded,
}: Props) {
  const c = useTheme()
  const [draggedAccountId, setDraggedAccountId] = useState<string | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)

  const orderedAccounts = useMemo(() => {
    return [...market.accounts].sort((a, b) => {
      // 수집상품수 오름차순 — 수집 많은 계정이 하단에 배치
      if (a.total_collected !== b.total_collected) {
        return a.total_collected - b.total_collected
      }
      return a.account_label.localeCompare(b.account_label)
    })
  }, [market.accounts])

  // 보드 전체 공통 높이(가장 긴 컬럼 픽셀 기준) — 모든 컬럼 바닥선을 하나로 맞춘다
  const columnHeight = Math.max(60, boardHeight)
  const isAccountDragging = draggedAccountId !== null

  const handleAccountDrop = async (targetIndex: number) => {
    if (!draggedAccountId) return
    const reordered = [...orderedAccounts]
    const fromIndex = reordered.findIndex(account => account.account_id === draggedAccountId)
    if (fromIndex === -1) {
      setDraggedAccountId(null)
      setDropIndex(null)
      return
    }

    const [moved] = reordered.splice(fromIndex, 1)
    reordered.splice(targetIndex, 0, moved)

    setDraggedAccountId(null)
    setDropIndex(null)
    await onAccountReorder(reordered)
  }

  return (
    <div style={{ minWidth: 211, width: 227, flexShrink: 0 }}>
      <div style={{
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderRadius: 6,
        padding: '0 6px',
      }}>
        <div style={{
          // 테트리스 바닥 쌓기 — 0점(바닥)부터 블록이 쌓이도록 아래정렬.
          // globalMax가 컬럼 합산 기준이라 내용이 눈금을 넘지 않고,
          // 혹시 넘치면 minHeight라 박스가 늘어나 잘림 없음 (고정 height 금지)
          minHeight: columnHeight,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
        }}>
          {isAccountDragging && (
            <AccountSlot
              active={dropIndex === 0}
              onEnter={() => setDropIndex(0)}
              onLeave={() => setDropIndex(null)}
              onDrop={() => handleAccountDrop(0)}
            />
          )}
          {orderedAccounts.map((account, index) => {
            // 블록 합이 박스(max_count 기준)보다 크면 overflow:hidden 으로 잘리므로
            // 박스 높이를 블록 합 이상으로 보장 — 계산은 accountPixelHeight 공용 함수
            const capacityHeight = accountPixelHeight(account, pixelsPerUnit)

            return (
              <div key={account.account_id}>
                <AccountBlock
                  account={account}
                  capacityHeight={capacityHeight}
                  pixelsPerUnit={pixelsPerUnit}
                  policies={policies}
                  dragState={dragState}
                  onDragStart={onDragStart}
                  onDrop={onDrop}
                  onReorder={onReorder}
                  onRemove={onRemove}
                  onDeleteBrandScope={onDeleteBrandScope}
                  onRemoveLegacyFromAccount={onRemoveLegacyFromAccount}
                  onPolicyChange={onPolicyChange}
                  onToggleExcluded={onToggleExcluded}
                  onToggleAccountExcluded={onToggleAccountExcluded}
                  isDragging={dragState !== null}
                  isAccountDragging={isAccountDragging}
                  onAccountDragStart={accountId => setDraggedAccountId(accountId)}
                  onAccountDragEnd={() => {
                    setDraggedAccountId(null)
                    setDropIndex(null)
                  }}
                />
                {isAccountDragging && (
                  <AccountSlot
                    active={dropIndex === index + 1}
                    onEnter={() => setDropIndex(index + 1)}
                    onLeave={() => setDropIndex(null)}
                    onDrop={() => handleAccountDrop(index + 1)}
                  />
                )}
              </div>
            )
          })}
          {orderedAccounts.length === 0 && (
            <div style={{ color: c.textMuted, fontSize: 11, padding: '12px 0', textAlign: 'center' }}>No accounts</div>
          )}
        </div>
      </div>
    </div>
  )
}

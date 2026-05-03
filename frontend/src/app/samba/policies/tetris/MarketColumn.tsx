'use client'
import { fmtNum } from '@/lib/samba/styles'
import AccountBlock from './AccountBlock'
import type { TetrisMarketGroup, TetrisBrandBlock } from '@/lib/samba/api/tetris'
import type { DragState } from './useTetris'

// ─── 타입 ─────────────────────────────────────────────────────────────────────

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  market: TetrisMarketGroup
  blockHeight: number
  policies: Policy[]
  dragState: DragState
  onDragStart: (block: TetrisBrandBlock, accountId: string) => void
  onDrop: (toAccountId: string) => Promise<void>
  onRemove: (assignmentId: string, brandName: string) => void
  onPolicyChange: (assignmentId: string, policyId: string | null, accountId: string) => Promise<void>
}

// ─── MarketColumn 컴포넌트 ────────────────────────────────────────────────────

export default function MarketColumn({
  market,
  blockHeight,
  policies,
  dragState,
  onDragStart,
  onDrop,
  onRemove,
  onPolicyChange,
}: Props) {
  // 마켓 전체 합산 수치
  const totalRegistered = market.accounts.reduce((s, a) => s + a.total_registered, 0)
  const totalCollected = market.accounts.reduce((s, a) => s + a.total_collected, 0)

  return (
    <div style={{
      minWidth: 200,
      width: 220,
      flexShrink: 0,
    }}>
      {/* 마켓 컬럼 헤더 */}
      <div style={{
        padding: '8px 10px',
        background: 'rgba(35,35,35,0.8)',
        border: '1px solid #333',
        borderRadius: '6px 6px 0 0',
        borderBottom: 'none',
      }}>
        <div style={{ fontSize: 13, color: '#eee', fontWeight: 700, marginBottom: 2 }}>
          {market.market_name}
        </div>
        <div style={{ fontSize: 10, color: '#666' }}>
          등록 {fmtNum(totalRegistered)} · 수집 {fmtNum(totalCollected)}
        </div>
      </div>

      {/* 계정 목록 */}
      <div style={{
        background: 'rgba(20,20,20,0.5)',
        border: '1px solid #333',
        borderTop: 'none',
        borderRadius: '0 0 6px 6px',
        padding: '8px 6px',
      }}>
        {market.accounts.map(account => (
          <AccountBlock
            key={account.account_id}
            account={account}
            blockHeight={blockHeight}
            policies={policies}
            onDragStart={onDragStart}
            onDrop={onDrop}
            onRemove={onRemove}
            onPolicyChange={onPolicyChange}
            isDragging={dragState !== null}
          />
        ))}
        {market.accounts.length === 0 && (
          <div style={{ color: '#444', fontSize: 11, padding: '12px 0', textAlign: 'center' }}>
            계정 없음
          </div>
        )}
      </div>
    </div>
  )
}

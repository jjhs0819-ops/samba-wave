'use client'
import { useMemo } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import { useTetris } from './useTetris'
import MarketColumn from './MarketColumn'
import UnassignedPool from './UnassignedPool'
import type { TetrisBrandBlock } from '@/lib/samba/api/tetris'

// ─── TetrisBoard 컴포넌트 ─────────────────────────────────────────────────────

export default function TetrisBoard() {
  const {
    board,
    loading,
    blockHeight,
    setBlockHeight,
    dragState,
    setDragState,
    handleDrop,
    handleRemove,
    handlePolicyChange,
    refresh,
  } = useTetris()

  // board에서 unique 정책 목록 추출
  const policies = useMemo(() => {
    const pMap = new Map<string, { id: string; name: string; color: string }>()
    board?.markets.forEach(m =>
      m.accounts.forEach(a =>
        a.assignments.forEach(b => {
          if (b.policy_id && b.policy_name) {
            pMap.set(b.policy_id, {
              id: b.policy_id,
              name: b.policy_name,
              color: b.policy_color,
            })
          }
        })
      )
    )
    return Array.from(pMap.values())
  }, [board])

  // 드래그 시작 핸들러 (배치된 블럭)
  const handleDragStart = (block: TetrisBrandBlock, accountId: string) => {
    setDragState({
      block,
      fromAccountId: accountId,
      assignmentId: block.id,
    })
  }

  // 드래그 시작 핸들러 (미배치 풀)
  const handleUnassignedDragStart = (block: TetrisBrandBlock) => {
    setDragState({
      block,
      fromAccountId: null,
      assignmentId: null,
    })
  }

  if (loading) {
    return (
      <div style={{ color: '#888', padding: 24, fontSize: 13 }}>
        불러오는 중...
      </div>
    )
  }

  if (!board) return null

  return (
    <div>
      {/* 컨트롤 바 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 16,
        padding: '8px 0',
        borderBottom: '1px solid #2a2a2a',
      }}>
        <span style={{ fontSize: 12, color: '#666' }}>블럭 높이</span>
        <button
          onClick={() => setBlockHeight(h => Math.max(30, h - 10))}
          style={{
            padding: '2px 10px',
            background: '#2a2a2a',
            border: '1px solid #444',
            color: '#ccc',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 14,
            lineHeight: 1,
          }}
        >
          −
        </button>
        <span style={{ color: '#888', fontSize: 12, minWidth: 50, textAlign: 'center' }}>
          {blockHeight}px
        </span>
        <button
          onClick={() => setBlockHeight(h => Math.min(120, h + 10))}
          style={{
            padding: '2px 10px',
            background: '#2a2a2a',
            border: '1px solid #444',
            color: '#ccc',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 14,
            lineHeight: 1,
          }}
        >
          +
        </button>

        <button
          onClick={refresh}
          style={{
            marginLeft: 'auto',
            padding: '4px 14px',
            background: '#2a2a2a',
            border: '1px solid #444',
            color: '#ccc',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          새로고침
        </button>
      </div>

      {/* 테트리스 보드 (가로 스크롤) */}
      <div style={{
        overflowX: 'auto',
        display: 'flex',
        gap: 12,
        alignItems: 'flex-start',
        paddingBottom: 8,
        minHeight: 200,
      }}>
        {board.markets.map(market => (
          <MarketColumn
            key={market.market_type}
            market={market}
            blockHeight={blockHeight}
            policies={policies}
            dragState={dragState}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
            onRemove={handleRemove}
            onPolicyChange={handlePolicyChange}
          />
        ))}
        {board.markets.length === 0 && (
          <div style={{ color: '#444', fontSize: 12, padding: '32px 0' }}>
            등록된 마켓 계정이 없습니다.
          </div>
        )}
      </div>

      {/* 미배치 풀 */}
      {board.unassigned.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{
            color: '#888',
            fontSize: 12,
            marginBottom: 10,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span>미배치 소싱처-브랜드</span>
            <span style={{
              background: 'rgba(255,140,0,0.15)',
              color: '#FF8C00',
              padding: '1px 8px',
              borderRadius: 10,
              fontSize: 11,
            }}>
              {fmtNum(board.unassigned.length)}개
            </span>
          </div>
          <UnassignedPool
            unassigned={board.unassigned}
            blockHeight={blockHeight}
            onDragStart={handleUnassignedDragStart}
          />
        </div>
      )}
    </div>
  )
}

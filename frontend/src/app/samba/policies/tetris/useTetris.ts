'use client'
import { useState, useCallback, useEffect } from 'react'
import { tetrisApi } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import type {
  TetrisBoardResponse,
  TetrisBrandBlock,
} from '@/lib/samba/api/tetris'

// ─── 드래그 상태 타입 ─────────────────────────────────────────────────────────

export type DragState = {
  block: TetrisBrandBlock
  fromAccountId: string | null  // null = 미배치 풀
  assignmentId: string | null
} | null

// ─── useTetris 훅 ─────────────────────────────────────────────────────────────

export function useTetris() {
  const [board, setBoard] = useState<TetrisBoardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // pixelsPerUnit: 등록 수량 1개 당 픽셀 수 (기본 0.01 = 100개당 1px, 70,000max → 700px)
  const [pixelsPerUnit, setPixelsPerUnit] = useState(0.01)
  const [dragState, setDragState] = useState<DragState>(null)

  // 보드 데이터 새로고침
  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Request timeout (15s)')), 15000)
      )
      const data = await Promise.race([
        tetrisApi.getBoard(),
        timeoutPromise,
      ])
      setBoard(data as TetrisBoardResponse)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      console.error('[테트리스] getBoard 실패:', msg)
      setError(msg)
      setBoard(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 계정에 블럭 드롭
  const handleDrop = useCallback(async (
    toAccountId: string,
  ) => {
    if (!dragState) return

    const block = dragState.block

    // 같은 계정에 드롭하면 무시 (레거시 블럭 포함)
    if (dragState.fromAccountId === toAccountId) {
      setDragState(null)
      return
    }

    const message = dragState.fromAccountId
      ? `"${block.brand_name}" 블럭을 다른 계정으로 이동합니다.\n기존 계정의 등록 상품이 삭제되고 새 계정에 재등록됩니다.`
      : `"${block.brand_name}" 블럭을 배치합니다. 상품 등록이 시작됩니다.`

    const confirmed = await showConfirm(message)
    if (!confirmed) {
      setDragState(null)
      return
    }

    try {
      if (dragState.assignmentId && dragState.fromAccountId !== toAccountId) {
        // 다른 계정으로 이동
        await tetrisApi.move(dragState.assignmentId, {
          market_account_id: toAccountId,
          policy_id: block.policy_id,
          position_order: 0,
        })
      } else if (!dragState.assignmentId) {
        // 미배치 풀 → 계정으로 신규 배치
        await tetrisApi.assign({
          source_site: block.source_site,
          brand_name: block.brand_name,
          market_account_id: toAccountId,
          policy_id: null,
          position_order: 0,
        })
      }
      await refresh()
    } catch (e) {
      showAlert('오류가 발생했습니다: ' + String(e))
    }

    setDragState(null)
  }, [dragState, refresh])

  // 계정 내 순서 변경 (move API 불필요 — reorder 전용)
  const handleReorder = useCallback(async (
    draggedId: string,
    newIndex: number,
    allAssignments: TetrisBrandBlock[],
  ) => {
    const mutable = allAssignments.filter(b => !b.is_legacy && b.id !== null)
    const fromIndex = mutable.findIndex(b => b.id === draggedId)
    if (fromIndex === -1) return

    const [moved] = mutable.splice(fromIndex, 1)
    mutable.splice(newIndex, 0, moved)

    const updates = mutable
      .map((block, idx) => ({ id: block.id!, oldPos: block.position_order, newPos: idx }))
      .filter(u => u.oldPos !== u.newPos)

    try {
      for (const { id, newPos } of updates) {
        await tetrisApi.reorder(id, { position_order: newPos })
      }
      await refresh()
    } catch (e) {
      showAlert('순서 변경 중 오류가 발생했습니다: ' + String(e))
    }
  }, [refresh])

  // 블럭 제거
  const handleRemove = useCallback(async (assignmentId: string, brandName: string) => {
    const confirmed = await showConfirm(
      `"${brandName}" 블럭을 제거합니다. 마켓 등록 상품이 삭제됩니다.`
    )
    if (!confirmed) return

    try {
      await tetrisApi.remove(assignmentId)
      await refresh()
    } catch (e) {
      showAlert('제거 중 오류가 발생했습니다: ' + String(e))
    }
  }, [refresh])

  // 정책 변경 (move API 재활용 — 동일 계정, policy_id만 교체)
  const handlePolicyChange = useCallback(async (
    assignmentId: string,
    policyId: string | null,
    accountId: string,
  ) => {
    try {
      await tetrisApi.move(assignmentId, {
        market_account_id: accountId,
        policy_id: policyId,
        position_order: 0,
      })
      await refresh()
    } catch (e) {
      showAlert('정책 변경 중 오류가 발생했습니다: ' + String(e))
    }
  }, [refresh])

  // 소싱처 브랜드 풀에서 정책 일괄 변경 — 해당 브랜드의 모든 배치 블럭에 동일 정책 적용
  const handleBrandPolicyChangeAll = useCallback(async (
    sourceSite: string,
    brandName: string,
    policyId: string | null,
  ) => {
    if (!board) return
    const targets: { assignmentId: string; accountId: string }[] = []
    board.markets.forEach(m =>
      m.accounts.forEach(a =>
        a.assignments.forEach(b => {
          if (b.source_site === sourceSite && b.brand_name === brandName && b.id && !b.is_legacy) {
            targets.push({ assignmentId: b.id, accountId: a.account_id })
          }
        })
      )
    )
    if (targets.length === 0) return
    try {
      for (const { assignmentId, accountId } of targets) {
        await tetrisApi.move(assignmentId, { market_account_id: accountId, policy_id: policyId, position_order: 0 })
      }
      await refresh()
    } catch (e) {
      showAlert('정책 변경 중 오류가 발생했습니다: ' + String(e))
    }
  }, [board, refresh])

  return {
    board,
    loading,
    error,
    pixelsPerUnit,
    setPixelsPerUnit,
    dragState,
    setDragState,
    handleDrop,
    handleRemove,
    handleReorder,
    handlePolicyChange,
    handleBrandPolicyChangeAll,
    refresh,
  }
}

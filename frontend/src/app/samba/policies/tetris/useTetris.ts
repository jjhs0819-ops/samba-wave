'use client'
import { useState, useCallback, useEffect } from 'react'
import { collectorApi, tetrisApi } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisBoardResponse, TetrisBrandBlock } from '@/lib/samba/api/tetris'

export type DragState = {
  block: TetrisBrandBlock
  fromAccountId: string | null
  assignmentId: string | null
} | null

export function useTetris() {
  const [board, setBoard] = useState<TetrisBoardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pixelsPerUnit, setPixelsPerUnit] = useState(0.01)
  const [dragState, setDragState] = useState<DragState>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Request timeout (15s)')), 15000)
      )
      const data = await Promise.race([tetrisApi.getBoard(), timeoutPromise])
      setBoard(data as TetrisBoardResponse)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      console.error('[Tetris] getBoard failed:', msg)
      setError(msg)
      setBoard(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleDrop = useCallback(async (toAccountId: string) => {
    if (!dragState) return

    const block = dragState.block
    if (dragState.fromAccountId === toAccountId) {
      setDragState(null)
      return
    }

    const message = dragState.fromAccountId
      ? `"${block.brand_name}" 브랜드가 다른 계정으로 이동됩니다.\n기존 마켓 등록 상품이 삭제되고 재등록됩니다.`
      : `"${block.brand_name}" 브랜드가 이 계정에 배치됩니다.\n상품 등록이 시작됩니다.`

    const confirmed = await showConfirm(message)
    if (!confirmed) {
      setDragState(null)
      return
    }

    try {
      if (dragState.assignmentId && dragState.fromAccountId !== toAccountId) {
        await tetrisApi.move(dragState.assignmentId, {
          market_account_id: toAccountId,
          policy_id: block.policy_id,
          position_order: 0,
        })
        await refresh()
      } else if (!dragState.assignmentId) {
        const result = await tetrisApi.assign({
          source_site: block.source_site,
          brand_name: block.brand_name,
          market_account_id: toAccountId,
          policy_id: null,
          position_order: 0,
        })
        // 옵티미스틱 업데이트: 보드 재조회 없이 즉시 블록 추가
        setBoard(prev => {
          if (!prev) return prev
          const newBlock: TetrisBrandBlock = {
            id: result.id,
            source_site: block.source_site,
            brand_name: block.brand_name,
            policy_id: null,
            policy_name: null,
            policy_color: '#3B82F6',
            registered_count: 0,
            collected_count: block.collected_count,
            ai_tagged_count: block.ai_tagged_count,
            position_order: 0,
            is_legacy: false,
          }
          return {
            ...prev,
            markets: prev.markets.map(m => ({
              ...m,
              accounts: m.accounts.map(a =>
                a.account_id === toAccountId
                  ? {
                      ...a,
                      assignments: [newBlock, ...a.assignments],
                      total_collected: a.total_collected + block.collected_count,
                    }
                  : a
              ),
            })),
          }
        })
      }
    } catch (e) {
      showAlert('An error occurred: ' + String(e))
    }

    setDragState(null)
  }, [dragState, refresh])

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
      showAlert('Reorder failed: ' + String(e))
    }
  }, [refresh])

  const handleRemove = useCallback(async (assignmentId: string, brandName: string) => {
    const confirmed = await showConfirm(
      `"${brandName}" brand will be removed from this account.\nMarket products will be deleted.`
    )
    if (!confirmed) return

    try {
      await tetrisApi.remove(assignmentId)
      await refresh()
    } catch (e) {
      showAlert('Deletion failed: ' + String(e))
    }
  }, [refresh])

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
      showAlert('Policy update failed: ' + String(e))
    }
  }, [refresh])

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
        await tetrisApi.move(assignmentId, {
          market_account_id: accountId,
          policy_id: policyId,
          position_order: 0,
        })
      }
      await refresh()
    } catch (e) {
      showAlert('Policy update failed: ' + String(e))
    }
  }, [board, refresh])

  const handleDeleteBrandScope = useCallback(async (sourceSite: string, brandName: string) => {
    const confirmed = await showConfirm(
      `"${brandName}" 브랜드의 상품과 그룹이 모두 삭제됩니다.\n이 작업은 되돌릴 수 없습니다.`
    )
    if (!confirmed) return

    try {
      const res = await collectorApi.deleteBrandScope(sourceSite, brandName)
      showAlert(`삭제 완료: 상품 ${fmtNum(res.deleted_products)}건, 그룹 ${fmtNum(res.deleted_filters)}개`)
      await refresh()
    } catch (e) {
      showAlert('브랜드 삭제 실패: ' + String(e))
    }
  }, [refresh])

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
    handleDeleteBrandScope,
    refresh,
  }
}

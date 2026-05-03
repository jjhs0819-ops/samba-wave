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

export function useTetris(tetrisEnabled: boolean = false) {
  const [board, setBoard] = useState<TetrisBoardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [blockHeight, setBlockHeight] = useState(60)  // px
  const [dragState, setDragState] = useState<DragState>(null)

  // 보드 데이터 새로고침
  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await tetrisApi.getBoard()
      setBoard(data)
    } catch {
      // 네트워크 오류는 무시 (빈 화면 유지)
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
    if (!tetrisEnabled) {
      showAlert('테트리스 매칭이 비활성화되어 있습니다')
      setDragState(null)
      return
    }

    if (!dragState) return

    const block = dragState.block

    // 같은 계정에 드롭하면 무시
    if (dragState.fromAccountId === toAccountId && dragState.assignmentId) {
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
  }, [dragState, refresh, tetrisEnabled])

  // 블럭 제거
  const handleRemove = useCallback(async (assignmentId: string, brandName: string) => {
    if (!tetrisEnabled) {
      showAlert('테트리스 매칭이 비활성화되어 있습니다')
      return
    }

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
  }, [refresh, tetrisEnabled])

  // 정책 변경 (move API 재활용 — 동일 계정, policy_id만 교체)
  const handlePolicyChange = useCallback(async (
    assignmentId: string,
    policyId: string | null,
    accountId: string,
  ) => {
    if (!tetrisEnabled) {
      showAlert('테트리스 매칭이 비활성화되어 있습니다')
      return
    }

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
  }, [refresh, tetrisEnabled])

  return {
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
  }
}

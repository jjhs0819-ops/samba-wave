'use client'
import { useMemo, useRef, useCallback, useState } from 'react'
import { accountApi } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { useTetris } from './useTetris'
import MarketColumn from './MarketColumn'
import UnassignedPool from './UnassignedPool'
import type { TetrisAccountBlock, TetrisBrandBlock } from '@/lib/samba/api/tetris'
import type { BrandAssignment } from './UnassignedPool'

function computeScaleStep(pixelsPerUnit: number, targetPx = 20): number {
  const rawStep = targetPx / pixelsPerUnit
  const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)))
  const norm = rawStep / magnitude
  const nice = norm <= 1.5 ? 1 : norm <= 3.5 ? 2 : norm <= 7 ? 5 : 10
  return nice * magnitude
}

function ScaleRuler({
  globalMax,
  pixelsPerUnit,
}: {
  globalMax: number
  pixelsPerUnit: number
}) {
  const totalHeight = Math.max(globalMax * pixelsPerUnit, 60)
  const scaleStep = computeScaleStep(pixelsPerUnit)

  const marks: number[] = []
  for (let v = 0; v <= globalMax; v += scaleStep) marks.push(v)
  if (marks[marks.length - 1] < globalMax) marks.push(globalMax)

  return (
    <div style={{ width: 56, flexShrink: 0, position: 'relative' }}>
      <div style={{ position: 'relative', height: totalHeight }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, right: 0, width: 1, background: '#2a2a2a' }} />
        {marks.map(v => {
          const fromBottom = v * pixelsPerUnit
          const top = totalHeight - fromBottom
          const isTop = v === globalMax
          const isZero = v === 0
          return (
            <div
              key={v}
              style={{
                position: 'absolute',
                top,
                left: 0,
                right: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 4,
                transform: isZero ? 'translateY(0%)' : isTop ? 'translateY(-100%)' : 'translateY(-50%)',
              }}
            >
              <span style={{ fontSize: 9, color: '#555', userSelect: 'none', whiteSpace: 'nowrap' }}>
                {fmtNum(v)}
              </span>
              <span style={{ width: 8, borderTop: '1px solid #333', display: 'inline-block' }} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

interface DeleteScopeModal {
  assignmentId: string
  brandName: string
  sourceSite: string
}

const SCALE_RULER_WIDTH = 56
const COLUMN_WIDTH = 280
const COLUMN_GAP = 12

export default function TetrisBoard() {
  const {
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
  } = useTetris()

  const [deleteModal, setDeleteModal] = useState<DeleteScopeModal | null>(null)

  // horizontal scroll sync between the sticky header row and the market columns
  const contentScrollRef = useRef<HTMLDivElement>(null)
  const headerScrollRef = useRef<HTMLDivElement>(null)

  const onContentScroll = useCallback(() => {
    if (headerScrollRef.current && contentScrollRef.current) {
      headerScrollRef.current.scrollLeft = contentScrollRef.current.scrollLeft
    }
  }, [])

  const sortedMarkets = useMemo(() => {
    if (!board) return []
    return [...board.markets].sort((a, b) => {
      const aR = a.accounts.reduce((s, ac) => s + ac.total_registered, 0)
      const bR = b.accounts.reduce((s, ac) => s + ac.total_registered, 0)
      if (bR !== aR) return bR - aR
      const aC = a.accounts.reduce((s, ac) => s + ac.max_count, 0)
      const bC = b.accounts.reduce((s, ac) => s + ac.max_count, 0)
      if (bC !== aC) return bC - aC
      return a.market_name.localeCompare(b.market_name)
    })
  }, [board])

  // 단일 계정 기준 최대값 (합산 아님 — 스케일이 실제 데이터에 맞도록)
  const globalMax = useMemo(() => {
    if (!board) return 70000
    const allAccounts = board.markets.flatMap(m => m.accounts)
    return Math.max(1000, ...allAccounts.map(a => Math.max(a.max_count, a.total_collected)))
  }, [board])

  // 미배치 브랜드별 배치 현황 맵 (sourceSite::brandName → BrandAssignment[])
  const assignmentsByBrand = useMemo(() => {
    const map = new Map<string, BrandAssignment[]>()
    if (!board) return map
    board.markets.forEach(m => {
      m.accounts.forEach(a => {
        a.assignments.forEach(b => {
          const key = `${b.source_site}::${b.brand_name}`
          if (!map.has(key)) map.set(key, [])
          map.get(key)!.push({
            marketType: m.market_type,
            marketName: m.market_name,
            accountLabel: a.account_label,
          })
        })
      })
    })
    return map
  }, [board])

  // 브랜드별 현재 정책 색상 맵 (첫 번째 배치 기준)
  const policyByBrand = useMemo(() => {
    const map = new Map<string, { policyId: string | null; policyColor: string }>()
    if (!board) return map
    board.markets.forEach(m =>
      m.accounts.forEach(a =>
        a.assignments.forEach(b => {
          const key = `${b.source_site}::${b.brand_name}`
          if (!map.has(key)) {
            map.set(key, { policyId: b.policy_id, policyColor: b.policy_color })
          }
        })
      )
    )
    return map
  }, [board])

  // 정책 목록 (색상 포함)
  const policies = useMemo(() => {
    const pMap = new Map<string, { id: string; name: string; color: string }>()
    board?.markets.forEach(m =>
      m.accounts.forEach(a =>
        a.assignments.forEach(b => {
          if (b.policy_id && b.policy_name) {
            pMap.set(b.policy_id, { id: b.policy_id, name: b.policy_name, color: b.policy_color })
          }
        })
      )
    )
    return Array.from(pMap.values())
  }, [board])

  const currentStep = useMemo(() => computeScaleStep(pixelsPerUnit), [pixelsPerUnit])

  const handleDragStart = (block: TetrisBrandBlock, accountId: string) => {
    setDragState({ block, fromAccountId: accountId, assignmentId: block.id })
  }
  const handleUnassignedDragStart = (block: TetrisBrandBlock) => {
    setDragState({ block, fromAccountId: null, assignmentId: null })
  }

  const handleAccountReorder = useCallback(async (accounts: TetrisAccountBlock[]) => {
    try {
      for (const [index, account] of accounts.entries()) {
        await accountApi.update(account.account_id, {
          additional_fields: {
            tetrisAccountOrder: index,
          },
        })
      }
      await refresh()
    } catch (error) {
      showAlert('계정 순서 저장에 실패했습니다: ' + String(error))
    }
  }, [refresh])

  // 삭제 버튼 클릭 — 삭제 범위 모달 표시
  const handleRemoveWithScope = useCallback((assignmentId: string, brandName: string, sourceSite: string) => {
    setDeleteModal({ assignmentId, brandName, sourceSite })
  }, [])

  // 삭제 범위 모달 — 이 계정만 삭제
  const handleDeleteThisOnly = useCallback(async () => {
    if (!deleteModal) return
    setDeleteModal(null)
    const confirmed = await showConfirm(`"${deleteModal.brandName}" 블럭을 이 계정에서만 제거합니다.\n마켓 등록 상품이 삭제됩니다.`)
    if (!confirmed) return
    try {
      const { tetrisApi } = await import('@/lib/samba/api')
      await tetrisApi.remove(deleteModal.assignmentId)
      await refresh()
    } catch (e) {
      showAlert('제거 중 오류가 발생했습니다: ' + String(e))
    }
  }, [deleteModal, refresh])

  // 삭제 범위 모달 — 전체 계정 삭제
  const handleDeleteAll = useCallback(async () => {
    if (!deleteModal) return
    const { sourceSite, brandName } = deleteModal
    setDeleteModal(null)
    const confirmed = await showConfirm(`"${brandName}" 블럭을 모든 계정에서 제거합니다.\n관련 마켓 등록 상품이 모두 삭제됩니다.`)
    if (!confirmed) return
    try {
      if (!board) return
      const { tetrisApi } = await import('@/lib/samba/api')
      const targets: string[] = []
      board.markets.forEach(m =>
        m.accounts.forEach(a =>
          a.assignments.forEach(b => {
            if (b.source_site === sourceSite && b.brand_name === brandName && b.id && !b.is_legacy) {
              targets.push(b.id)
            }
          })
        )
      )
      for (const id of targets) {
        await tetrisApi.remove(id)
      }
      await refresh()
    } catch (e) {
      showAlert('전체 제거 중 오류가 발생했습니다: ' + String(e))
    }
  }, [deleteModal, board, refresh])

  // 뷰포트 중심 기준 줌 (스크롤 위치 보정)
  const zoomFromCenter = useCallback((factor: number) => {
    const oldPpu = pixelsPerUnit
    const newPpu = Math.min(0.5, Math.max(0.001, oldPpu * factor))
    if (newPpu === oldPpu) return

    const viewportH = window.innerHeight
    const scrollY = window.scrollY
    const centerY = scrollY + viewportH / 2

    setPixelsPerUnit(newPpu)

    requestAnimationFrame(() => {
      const scale = newPpu / oldPpu
      const newCenterY = centerY * scale
      window.scrollTo({ top: newCenterY - viewportH / 2, behavior: 'instant' })
    })
  }, [pixelsPerUnit, setPixelsPerUnit])

  if (loading) return <div style={{ color: '#888', padding: 24, fontSize: 13 }}>데이터 로딩 중...</div>
  if (error) return (
    <div style={{ color: '#EF4444', padding: 24, fontSize: 13, background: 'rgba(239,68,68,0.08)', borderRadius: 6, border: '1px solid rgba(239,68,68,0.2)', marginTop: 16 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>보드 로딩 실패</div>
      <div style={{ color: '#888', fontSize: 12 }}>{error}</div>
      <button onClick={refresh} style={{ marginTop: 10, padding: '4px 12px', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>재시도</button>
    </div>
  )
  if (!board) return null

  return (
    <div>
      {/* 상단 툴바 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 16,
        padding: '8px 0',
        borderBottom: '1px solid #2a2a2a',
      }}>
        <span style={{ color: '#555', fontSize: 11 }}>최대 {fmtNum(globalMax)}개</span>
        <button
          onClick={refresh}
          style={{ marginLeft: 'auto', padding: '4px 14px', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
        >
          새로고침
        </button>
      </div>

      {/* 스케일 +/- 고정 패널 — 화면 좌측 중앙 */}
      <div style={{
        position: 'fixed',
        left: 8,
        top: '50%',
        transform: 'translateY(-50%)',
        zIndex: 50,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 6,
        background: 'rgba(20,20,20,0.9)',
        border: '1px solid #333',
        borderRadius: 6,
        padding: '8px 6px',
      }}>
        <button
          onClick={() => zoomFromCenter(2)}
          style={{ width: 28, height: 28, background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 16, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          +
        </button>
        <span style={{ color: '#555', fontSize: 9, textAlign: 'center', lineHeight: 1.3 }}>
          {fmtNum(currentStep)}
        </span>
        <button
          onClick={() => zoomFromCenter(0.5)}
          style={{ width: 28, height: 28, background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 16, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          -
        </button>
      </div>

      {/* Sticky 마켓명 헤더 row */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        background: 'rgba(12,12,12,0.97)',
        backdropFilter: 'blur(6px)',
        borderBottom: '1px solid #222',
        display: 'flex',
      }}>
        {/* 스케일 눈금 자리 */}
        <div style={{ width: SCALE_RULER_WIDTH, flexShrink: 0 }} />
        {/* 마켓명 헤더 (스크롤 연동) */}
        <div
          ref={headerScrollRef}
          className="tetris-scroll-x"
          style={{ display: 'flex', gap: COLUMN_GAP, overflow: 'hidden', flex: 1 }}
        >
          {sortedMarkets.map(market => {
            const totalRegistered = market.accounts.reduce((s, a) => s + a.total_registered, 0)
            const totalCollected  = market.accounts.reduce((s, a) => s + a.total_collected, 0)
            return (
              <div
                key={market.market_type}
                style={{ minWidth: COLUMN_WIDTH, width: COLUMN_WIDTH, flexShrink: 0, padding: '8px 10px' }}
              >
                <div style={{ fontSize: 13, color: '#eee', fontWeight: 700, marginBottom: 2 }}>
                  {market.market_name}
                </div>
                <div style={{ fontSize: 10, color: '#666' }}>
                  등록 {fmtNum(totalRegistered)} / 수집 {fmtNum(totalCollected)}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 눈금자 + 마켓 컬럼 (가로 스크롤) */}
      <div style={{ display: 'flex', gap: 0, alignItems: 'flex-start' }}>
        <ScaleRuler
          globalMax={globalMax}
          pixelsPerUnit={pixelsPerUnit}
        />
        <div
          ref={contentScrollRef}
          className="tetris-scroll-x"
          onScroll={onContentScroll}
          style={{ overflowX: 'auto', overflowY: 'hidden', flex: 1, display: 'flex', gap: COLUMN_GAP, alignItems: 'flex-start' }}
        >
          {sortedMarkets.map(market => (
            <MarketColumn
              key={market.market_type}
              market={market}
              pixelsPerUnit={pixelsPerUnit}
              globalMax={globalMax}
              policies={policies}
              dragState={dragState}
              onDragStart={handleDragStart}
              onDrop={handleDrop}
              onReorder={handleReorder}
              onAccountReorder={handleAccountReorder}
              onRemove={handleRemoveWithScope}
              onPolicyChange={handlePolicyChange}
            />
          ))}
          {sortedMarkets.length === 0 && (
            <div style={{ color: '#444', fontSize: 12, padding: '32px 0' }}>
              등록된 마켓 계정이 없습니다.
            </div>
          )}
        </div>
      </div>

      {/* 소싱처 브랜드 풀 — 항상 표시 */}
      <div style={{ marginTop: 28 }}>
        <div style={{ color: '#888', fontSize: 12, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>소싱처 브랜드</span>
          <span style={{ background: 'rgba(255,140,0,0.15)', color: '#FF8C00', padding: '1px 8px', borderRadius: 10, fontSize: 11 }}>
            {fmtNum(board.unassigned.length)}개
          </span>
        </div>
        <UnassignedPool
          unassigned={board.unassigned}
          pixelsPerUnit={pixelsPerUnit}
          onDragStart={handleUnassignedDragStart}
          assignmentsByBrand={assignmentsByBrand}
          policies={policies}
          policyByBrand={policyByBrand}
          onBrandPolicyChange={handleBrandPolicyChangeAll}
        />
      </div>

      {/* 삭제 범위 선택 모달 */}
      {deleteModal && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          onClick={() => setDeleteModal(null)}
        >
          <div
            style={{
              background: '#1a1a1a', border: '1px solid #333', borderRadius: 8,
              padding: '20px 24px', minWidth: 300, maxWidth: 400,
              boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ fontSize: 14, color: '#eee', fontWeight: 700, marginBottom: 6 }}>
              "{deleteModal.brandName}" 삭제 범위
            </div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 20 }}>
              이 계정에서만 삭제할지, 모든 계정에서 삭제할지 선택하세요.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button
                onClick={handleDeleteThisOnly}
                style={{ padding: '9px 0', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
              >
                이 계정에서만 삭제
              </button>
              <button
                onClick={handleDeleteAll}
                style={{ padding: '9px 0', background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)', color: '#EF4444', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
              >
                모든 계정에서 삭제
              </button>
              <button
                onClick={() => setDeleteModal(null)}
                style={{ padding: '7px 0', background: 'transparent', border: '1px solid #333', color: '#666', borderRadius: 4, cursor: 'pointer', fontSize: 11 }}
              >
                취소
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

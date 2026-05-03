'use client'
import { useMemo, useRef, useCallback } from 'react'
import { accountApi } from '@/lib/samba/api'
import { showAlert } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { useTetris } from './useTetris'
import MarketColumn from './MarketColumn'
import UnassignedPool from './UnassignedPool'
import type { TetrisAccountBlock, TetrisBrandBlock } from '@/lib/samba/api/tetris'

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

const SCALE_RULER_WIDTH = 56
const COLUMN_WIDTH = 280
const COLUMN_GAP = 12

export default function TetrisBoard() {
  const {
    board,
    loading,
    pixelsPerUnit,
    setPixelsPerUnit,
    dragState,
    setDragState,
    handleDrop,
    handleRemove,
    handleReorder,
    handlePolicyChange,
    refresh,
  } = useTetris()

  // horizontal scroll sync between the sticky header row and the market columns
  const contentScrollRef = useRef<HTMLDivElement>(null)
  const headerScrollRef = useRef<HTMLDivElement>(null)

  const onContentScroll = useCallback(() => {
    if (headerScrollRef.current && contentScrollRef.current) {
      headerScrollRef.current.scrollLeft = contentScrollRef.current.scrollLeft
    }
  }, [])

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

  // ???? ?? max_count ??? ? ???? ?? ??? ???? ??
  const globalMax = useMemo(() => {
    if (!board) return 70000
    const marketCapacities = board.markets.map(market =>
      market.accounts.reduce((sum, account) => sum + account.max_count, 0)
    )
    return Math.max(1000, ...marketCapacities)
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

  if (loading) return <div style={{ color: '#888', padding: 24, fontSize: 13 }}>遺덈윭?ㅻ뒗 以?..</div>
  if (!board) return null

  return (
    <div>
      {/* 而⑦듃濡?諛?*/}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        marginBottom: 16,
        padding: '8px 0',
        borderBottom: '1px solid #2a2a2a',
      }}>
        <span style={{ fontSize: 12, color: '#666' }}>스케일</span>
        <button
          onClick={() => setPixelsPerUnit(p => Math.max(0.001, p / 2))}
          style={{ padding: '2px 10px', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
        >
          -
        </button>
        <span style={{ color: '#888', fontSize: 12, minWidth: 80, textAlign: 'center' }}>
          {fmtNum(currentStep)}단위
        </span>
        <button
          onClick={() => setPixelsPerUnit(p => Math.min(0.5, p * 2))}
          style={{ padding: '2px 10px', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 14, lineHeight: 1 }}
        >
          +
        </button>
        <span style={{ color: '#555', fontSize: 11 }}>
          (최대 {fmtNum(globalMax)}개)
        </span>
        <button
          onClick={refresh}
          style={{ marginLeft: 'auto', padding: '4px 14px', background: '#2a2a2a', border: '1px solid #444', color: '#ccc', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
        >
          새로고침
        </button>
      </div>

      {/* ?? Sticky 留덉폆 ?ㅻ뜑 row (overflow 而⑦뀒?대꼫 諛뽰뿉 ?꾩튂 ??viewport 湲곗? sticky ?숈옉) ?? */}
      <div style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        background: 'rgba(12,12,12,0.97)',
        backdropFilter: 'blur(6px)',
        borderBottom: '1px solid #222',
        display: 'flex',
      }}>
        {/* ?ㅼ????덇툑 ?먮━ */}
        <div style={{ width: SCALE_RULER_WIDTH, flexShrink: 0 }} />
        {/* 留덉폆 ?ㅻ뜑 (?섑룊 ?ㅽ겕濡??깊겕) */}
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
                  ?깅줉 {fmtNum(totalRegistered)} / ?섏쭛 {fmtNum(totalCollected)}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ?ㅼ???+ 留덉폆 而щ읆 (?섑룊 ?ㅽ겕濡? */}
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
              onRemove={handleRemove}
              onPolicyChange={handlePolicyChange}
            />
          ))}
          {sortedMarkets.length === 0 && (
            <div style={{ color: '#444', fontSize: 12, padding: '32px 0' }}>
              ?깅줉??留덉폆 怨꾩젙???놁뒿?덈떎.
            </div>
          )}
        </div>
      </div>

      {/* 誘몃같移?? */}
      {board.unassigned.length > 0 && (
        <div style={{ marginTop: 28 }}>
          <div style={{ color: '#888', fontSize: 12, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>미배치 소싱처 브랜드</span>
            <span style={{ background: 'rgba(255,140,0,0.15)', color: '#FF8C00', padding: '1px 8px', borderRadius: 10, fontSize: 11 }}>
              {fmtNum(board.unassigned.length)}개
            </span>
          </div>
          <UnassignedPool
            unassigned={board.unassigned}
            pixelsPerUnit={pixelsPerUnit}
            onDragStart={handleUnassignedDragStart}
          />
        </div>
      )}
    </div>
  )
}

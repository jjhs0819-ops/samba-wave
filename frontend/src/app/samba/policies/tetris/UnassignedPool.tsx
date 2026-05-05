'use client'
import { useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisUnassigned, TetrisBrandBlock } from '@/lib/samba/api/tetris'

const FIXED_BLOCK_PX = 56

const MARKET_COLORS: Record<string, string> = {
  coupang: '#F5A623',    // 주황
  smartstore: '#03C75A', // 초록
  '11st': '#E8002D',     // 빨강
  gmarket: '#0065D5',    // 파랑
  auction: '#A855F7',    // 보라 (기존 하늘과 구분)
  lotteon: '#E2E8F0',    // 흰색
  gsshop: '#FACC15',     // 노랑 (쿠팡 주황과 구분)
  ssg: '#6B21A8',        // 진보라 (auction 보라와 구분)
  lottehome: '#DB2777',  // 핑크-마젠타
  homeand: '#06B6D4',    // 청록
  hmall: '#3B82F6',      // 파랑 (gmarket 진파랑과 구분)
  toss: '#1D4ED8',       // 진파랑
  ktalpha: '#10B981',    // 에메랄드
}

function getMarketColor(marketType: string): string {
  return MARKET_COLORS[marketType.toLowerCase()] ?? '#6B7280'
}

export interface BrandAssignment {
  marketType: string
  marketName: string
  accountLabel: string
}

interface Props {
  unassigned: TetrisUnassigned[]
  blockHeight?: number
  pixelsPerUnit: number
  onDragStart: (block: TetrisBrandBlock) => void
  assignmentsByBrand: Map<string, BrandAssignment[]>
  onBrandClick: (sourceSite: string, brandName: string) => void
}

function UnassignedItem({
  item,
  itemHeight,
  onDragStart,
  assignments,
  onClick,
}: {
  item: TetrisUnassigned
  itemHeight: number
  onDragStart: (block: TetrisBrandBlock) => void
  assignments: BrandAssignment[]
  onClick: () => void
}) {
  const block: TetrisBrandBlock = {
    id: null,
    source_site: item.source_site,
    brand_name: item.brand_name,
    policy_id: null,
    policy_name: null,
    policy_color: '#6B7280',
    registered_count: item.registered_count,
    collected_count: item.collected_count,
    position_order: 0,
    is_legacy: false,
  }

  // 등록된 마켓 타입별 색상 점 (중복 제거)
  const uniqueMarkets = Array.from(
    new Map(assignments.map(a => [a.marketType, a])).values()
  )

  return (
    <div
      draggable
      onDragStart={() => onDragStart(block)}
      onClick={assignments.length > 0 ? onClick : undefined}
      style={{
        height: itemHeight,
        minHeight: itemHeight,
        background: 'rgba(28,28,28,0.9)',
        border: '1px solid #3a3a3a50',
        borderLeft: '3px solid #6B7280',
        borderRadius: 4,
        marginBottom: 2,
        cursor: assignments.length > 0 ? 'pointer' : 'grab',
        position: 'relative',
        overflow: 'hidden',
        userSelect: 'none',
        boxSizing: 'border-box',
        flexShrink: 0,
      }}
    >
      <div style={{
        position: 'relative',
        height: '100%',
        padding: '4px 6px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}>
        <div style={{
          fontSize: 11,
          color: '#ddd',
          fontWeight: 600,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
          paddingRight: 36,
        }}>
          {item.brand_name}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 10, color: '#666' }}>
            <span style={{ color: '#22C55E' }}>{fmtNum(item.registered_count)}</span>
            <span style={{ color: '#444' }}>/</span>
            <span style={{ color: '#888' }}>{fmtNum(item.collected_count)}</span>
          </div>
          {/* 등록 마켓 색상 점 */}
          {uniqueMarkets.length > 0 && (
            <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
              {uniqueMarkets.map(a => (
                <div
                  key={a.marketType}
                  title={a.marketName}
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 1,
                    background: getMarketColor(a.marketType),
                    flexShrink: 0,
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
      <div style={{
        position: 'absolute',
        top: 3,
        right: 4,
        fontSize: 9,
        color: '#444',
        whiteSpace: 'nowrap',
        pointerEvents: 'none',
      }}>
        {item.source_site}
      </div>
    </div>
  )
}

export default function UnassignedPool({
  unassigned,
  pixelsPerUnit: _pixelsPerUnit,
  onDragStart,
  assignmentsByBrand,
  onBrandClick,
}: Props) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)

  const grouped = unassigned.reduce<Record<string, TetrisUnassigned[]>>((acc, item) => {
    const key = item.source_site
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  return (
    <div
      style={{
        background: 'rgba(20,20,20,0.5)',
        border: '1px solid #2a2a2a',
        borderRadius: 6,
        padding: '10px 12px',
      }}
    >
      {Object.entries(grouped).map(([site, items]) => (
        <div key={site} style={{ marginBottom: 16 }}>
          <div
            style={{
              fontSize: 11,
              color: '#888',
              marginBottom: 6,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            {site}
            <span style={{ color: '#555', marginLeft: 6 }}>({fmtNum(items.length)})</span>
          </div>
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 8,
              alignItems: 'flex-end',
            }}
          >
            {items.map((item, idx) => {
              const key = `${item.source_site}::${item.brand_name}`
              const assignments = assignmentsByBrand.get(key) ?? []
              return (
                <div
                  key={`${item.source_site}-${item.brand_name}-${idx}`}
                  style={{
                    width: 160,
                    opacity: hoveredKey === key ? 0.8 : 1,
                    transition: 'opacity 0.1s',
                  }}
                  onMouseEnter={() => assignments.length > 0 && setHoveredKey(key)}
                  onMouseLeave={() => setHoveredKey(null)}
                >
                  <UnassignedItem
                    item={item}
                    itemHeight={FIXED_BLOCK_PX}
                    onDragStart={onDragStart}
                    assignments={assignments}
                    onClick={() => onBrandClick(item.source_site, item.brand_name)}
                  />
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

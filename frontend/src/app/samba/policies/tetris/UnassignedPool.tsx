'use client'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisUnassigned, TetrisBrandBlock } from '@/lib/samba/api/tetris'

const FIXED_BLOCK_PX = 56

interface Props {
  unassigned: TetrisUnassigned[]
  blockHeight?: number  // unused — kept for backward-compat
  pixelsPerUnit: number
  onDragStart: (block: TetrisBrandBlock) => void
}

function UnassignedItem({
  item,
  itemHeight,
  onDragStart,
}: {
  item: TetrisUnassigned
  itemHeight: number
  onDragStart: (block: TetrisBrandBlock) => void
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

  return (
    <div
      draggable
      onDragStart={() => onDragStart(block)}
      style={{
        height: itemHeight,
        minHeight: itemHeight,
        background: 'rgba(28,28,28,0.9)',
        border: '1px solid #3a3a3a50',
        borderLeft: '3px solid #6B7280',
        borderRadius: 4,
        marginBottom: 2,
        cursor: 'grab',
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
        }}>
          {item.brand_name}
        </div>
        <div style={{ fontSize: 10, color: '#666' }}>
          <span style={{ color: '#22C55E' }}>{fmtNum(item.registered_count)}</span>
          <span style={{ color: '#444' }}>/</span>
          <span style={{ color: '#888' }}>{fmtNum(item.collected_count)}</span>
        </div>
      </div>
      <div style={{
        position: 'absolute',
        bottom: 2,
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

export default function UnassignedPool({ unassigned, pixelsPerUnit, onDragStart }: Props) {
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
              return (
                <div key={`${item.source_site}-${item.brand_name}-${idx}`} style={{ width: 160 }}>
                  <UnassignedItem
                    item={item}
                    itemHeight={FIXED_BLOCK_PX}
                    onDragStart={onDragStart}
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

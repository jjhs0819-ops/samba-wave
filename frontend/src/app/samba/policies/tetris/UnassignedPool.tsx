'use client'
import { fmtNum } from '@/lib/samba/styles'
import type { TetrisUnassigned, TetrisBrandBlock } from '@/lib/samba/api/tetris'

// ─── 타입 ─────────────────────────────────────────────────────────────────────

interface Props {
  unassigned: TetrisUnassigned[]
  blockHeight: number
  onDragStart: (block: TetrisBrandBlock) => void
}

// ─── 미배치 풀 블럭 (단일 아이템) ────────────────────────────────────────────

function UnassignedItem({
  item,
  blockHeight,
  onDragStart,
}: {
  item: TetrisUnassigned
  blockHeight: number
  onDragStart: (block: TetrisBrandBlock) => void
}) {
  // TetrisUnassigned → TetrisBrandBlock 형태로 변환 (id/policy 없음)
  const block: TetrisBrandBlock = {
    id: null,
    source_site: item.source_site,
    brand_name: item.brand_name,
    policy_id: null,
    policy_name: null,
    policy_color: '#6B7280',
    registered_count: 0,
    collected_count: item.collected_count,
    position_order: 0,
    is_legacy: false,
  }

  return (
    <div
      draggable
      onDragStart={() => onDragStart(block)}
      style={{
        height: blockHeight,
        background: 'rgba(40,40,40,0.7)',
        border: '1px solid #3a3a3a',
        borderLeft: '3px solid #6B7280',
        borderRadius: 4,
        padding: '4px 6px',
        cursor: 'grab',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        userSelect: 'none',
        overflow: 'hidden',
      }}
    >
      {/* 소싱처 + 브랜드명 */}
      <div style={{
        fontSize: 11,
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        textOverflow: 'ellipsis',
      }}>
        <span style={{ color: '#666', marginRight: 4 }}>
          {item.source_site.toLowerCase()}
        </span>
        <span style={{ color: '#ccc', fontWeight: 600 }}>
          {item.brand_name}
        </span>
      </div>
      {/* 수집 수 */}
      <div style={{ fontSize: 10, color: '#666' }}>
        수집 {fmtNum(item.collected_count)}
      </div>
    </div>
  )
}

// ─── UnassignedPool 컴포넌트 ──────────────────────────────────────────────────

export default function UnassignedPool({ unassigned, blockHeight, onDragStart }: Props) {
  // 소싱처별 그룹화
  const grouped = unassigned.reduce<Record<string, TetrisUnassigned[]>>((acc, item) => {
    const key = item.source_site
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  return (
    <div style={{
      background: 'rgba(20,20,20,0.5)',
      border: '1px solid #2a2a2a',
      borderRadius: 6,
      padding: '10px 12px',
    }}>
      {Object.entries(grouped).map(([site, items]) => (
        <div key={site} style={{ marginBottom: 16 }}>
          {/* 소싱처 레이블 */}
          <div style={{
            fontSize: 11,
            color: '#888',
            marginBottom: 6,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            {site}
            <span style={{ color: '#555', marginLeft: 6 }}>({fmtNum(items.length)})</span>
          </div>
          {/* 블럭 그리드 */}
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 4,
          }}>
            {items.map((item, idx) => (
              <div key={`${item.source_site}-${item.brand_name}-${idx}`} style={{ width: 180 }}>
                <UnassignedItem
                  item={item}
                  blockHeight={blockHeight}
                  onDragStart={onDragStart}
                />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

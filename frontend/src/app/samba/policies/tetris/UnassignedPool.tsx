'use client'
import { useState } from 'react'
import { fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'
import type { TetrisUnassigned, TetrisBrandBlock } from '@/lib/samba/api/tetris'

const FIXED_BLOCK_PX = 56

const MARKET_COLORS: Record<string, string> = {
  coupang: '#F59E0B',    // 호박(amber)
  smartstore: '#22C55E', // 네이버 초록
  '11st': '#EF4444',     // 빨강
  gmarket: '#3B82F6',    // 파랑
  auction: '#A855F7',    // 보라
  lotteon: '#FFFFFF',    // 흰색
  gsshop: '#EC4899',     // 핫핑크
  ssg: '#7C3AED',        // 남보라
  lottehome: '#EAB308',  // 노랑
  homeand: '#0EA5E9',    // 하늘
  hmall: '#6366F1',      // 인디고 (기존 파랑→파란보라로 분리)
  toss: '#84CC16',       // 라임 (기존 파랑→연두로 분리)
  ktalpha: '#10B981',    // 에메랄드
  playauto: '#6B7280',   // 회색
}

function getMarketColor(marketType: string): string {
  return MARKET_COLORS[marketType.toLowerCase()] ?? '#6B7280'
}

function normTetrisKey(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/g, '').toLowerCase()
}

function normSiteKey(value: string | null | undefined): string {
  const key = normTetrisKey(value)
  const siteAliases: Record<string, string> = {
    gsshop: 'gsshop',
    abcmart: 'abcmart',
    grandstage: 'abcmart',
    lotteon: 'lotteon',
    musinsa: 'musinsa',
    ssg: 'ssg',
  }
  return siteAliases[key] ?? key
}

function brandScopeKey(sourceSite: string | null | undefined, brandName: string | null | undefined): string {
  return `${normSiteKey(sourceSite)}::${normTetrisKey(brandName)}`
}


export interface BrandAssignment {
  marketType: string
  marketName: string
  accountLabel: string
}

interface Policy {
  id: string
  name: string
  color: string
}

interface Props {
  unassigned: TetrisUnassigned[]
  blockHeight?: number
  pixelsPerUnit: number
  onDragStart: (block: TetrisBrandBlock) => void
  assignmentsByBrand: Map<string, BrandAssignment[]>
  policies: Policy[]
  policyByBrand: Map<string, { policyId: string | null; policyColor: string }>
  onBrandPolicyChange: (sourceSite: string, brandName: string, policyId: string | null) => Promise<void>
  onDeleteBrandScope: (sourceSite: string, brandName: string) => Promise<void>
}

function UnassignedItem({
  item,
  itemHeight,
  onDragStart,
  assignments,
  policies,
  currentPolicyId,
  currentPolicyColor,
  onPolicyChange,
  onDeleteBrandScope,
}: {
  item: TetrisUnassigned
  itemHeight: number
  onDragStart: (block: TetrisBrandBlock) => void
  assignments: BrandAssignment[]
  policies: Policy[]
  currentPolicyId: string | null
  currentPolicyColor: string
  onPolicyChange: (policyId: string | null) => Promise<void>
  onDeleteBrandScope: (sourceSite: string, brandName: string) => Promise<void>
}) {
  const c = useTheme()
  const [showPalette, setShowPalette] = useState(false)
  const brandColor = item.ai_tagged_count > 0 ? c.text : c.danger
  const uniqueMarkets = Array.from(
    new Map(assignments.map(a => [a.marketType, a])).values()
  )

  const block: TetrisBrandBlock = {
    id: null,
    source_site: item.source_site,
    brand_name: item.brand_name,
    policy_id: item.policy_id,
    policy_name: item.policy_name,
    policy_color: item.policy_color ?? '#6B7280',
    registered_count: item.registered_count,
    collected_count: item.collected_count,
    ai_tagged_count: item.ai_tagged_count,
    position_order: 0,
    is_legacy: false,
  }

  const borderColor = currentPolicyId ? currentPolicyColor : c.border

  return (
    <div
      draggable
      onDragStart={() => { setShowPalette(false); onDragStart(block) }}
      onClick={() => setShowPalette(v => !v)}
      style={{
        height: itemHeight,
        minHeight: itemHeight,
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderLeft: `3px solid ${borderColor}`,
        borderRadius: 4,
        marginBottom: 2,
        cursor: 'pointer',
        position: 'relative',
        overflow: 'visible',
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
        gap: 2,
        overflow: 'hidden',
      }}>
        {/* 상단: 브랜드명 (삭제 버튼 공간 확보) */}
        <div style={{
          fontSize: 11,
          color: brandColor,
          fontWeight: 600,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
          textOverflow: 'ellipsis',
          paddingRight: 22,
        }}>
          {item.brand_name}
        </div>
        {/* 중단: 판매처 컬러 스퀘어 (배치된 마켓) */}
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
        {/* 하단: 등록/수집수(좌) + 소싱처명(우) */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 10, color: c.textMuted }}>
            <span style={{ color: c.success }}>{fmtNum(item.registered_count)}</span>
            <span style={{ color: c.textMuted }}>/</span>
            <span style={{ color: c.text }}>{fmtNum(item.collected_count)}</span>
          </div>
          <span style={{ fontSize: 9, color: c.text, whiteSpace: 'nowrap', fontWeight: 500 }}>
            {item.source_site}
          </span>
        </div>
      </div>

      <button
        type="button"
        title="브랜드 전체 삭제"
        onClick={async e => {
          e.stopPropagation()
          setShowPalette(false)
          await onDeleteBrandScope(item.source_site, item.brand_name)
        }}
        style={{
          position: 'absolute',
          top: 2,
          right: 2,
          width: 16,
          height: 16,
          borderRadius: 4,
          border: '1px solid rgba(239,68,68,0.35)',
          background: 'rgba(239,68,68,0.16)',
          color: c.danger,
          fontSize: 11,
          fontWeight: 700,
          lineHeight: '14px',
          cursor: 'pointer',
          padding: 0,
        }}
      >
        x
      </button>

      {/* 정책 색상 팔레트 */}
      {showPalette && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 300,
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: 6,
            padding: '6px 8px',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
            whiteSpace: 'nowrap',
          }}
          onClick={e => e.stopPropagation()}
        >
          <div
            onClick={() => { onPolicyChange(null); setShowPalette(false) }}
            title="정책 없음"
            style={{
              width: 16, height: 16, borderRadius: '50%',
              background: '#6B7280',
              cursor: 'pointer',
              border: currentPolicyId === null ? `2px solid ${c.text}` : '2px solid transparent',
              flexShrink: 0,
            }}
          />
          {policies.map(p => (
            <div
              key={p.id}
              onClick={() => { onPolicyChange(p.id); setShowPalette(false) }}
              title={p.name}
              style={{
                width: 16, height: 16, borderRadius: '50%',
                background: p.color,
                cursor: 'pointer',
                border: p.id === currentPolicyId ? `2px solid ${c.text}` : '2px solid transparent',
                flexShrink: 0,
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function UnassignedPool({
  unassigned,
  pixelsPerUnit: _pixelsPerUnit,
  onDragStart,
  assignmentsByBrand,
  policies,
  policyByBrand,
  onBrandPolicyChange,
  onDeleteBrandScope,
}: Props) {
  const c = useTheme()
  const grouped = unassigned.reduce<Record<string, TetrisUnassigned[]>>((acc, item) => {
    const key = item.source_site
    if (!acc[key]) acc[key] = []
    acc[key].push(item)
    return acc
  }, {})

  // 소싱처별로 브랜드명 가나다순 정렬
  Object.values(grouped).forEach(items => {
    items.sort((a, b) => (a.brand_name ?? '').localeCompare(b.brand_name ?? '', 'ko'))
  })

  return (
    <div
      style={{
        background: c.surfaceAlt,
        border: `1px solid ${c.border}`,
        borderRadius: 6,
        padding: '10px 12px',
      }}
    >
      {Object.entries(grouped).sort(([, a], [, b]) => b.length - a.length).map(([site, items]) => (
        <div key={site} style={{ marginBottom: 16 }}>
          <div
            style={{
              fontSize: 11,
              color: c.textSub,
              marginBottom: 6,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            {site}
            <span style={{ color: c.textMuted, marginLeft: 6 }}>({fmtNum(items.length)})</span>
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
              const key = brandScopeKey(item.source_site, item.brand_name)
              const assignments = assignmentsByBrand.get(key) ?? []
              const policyInfo = policyByBrand.get(key)
              return (
                <div
                  key={`${item.source_site}-${item.brand_name}-${idx}`}
                  style={{ width: 160 }}
                >
                  <UnassignedItem
                    item={item}
                    itemHeight={FIXED_BLOCK_PX}
                    onDragStart={onDragStart}
                    assignments={assignments}
                    policies={policies}
                    currentPolicyId={policyInfo?.policyId ?? item.policy_id ?? null}
                    currentPolicyColor={policyInfo?.policyColor ?? item.policy_color ?? '#6B7280'}
                    onPolicyChange={(policyId) => onBrandPolicyChange(item.source_site, item.brand_name, policyId)}
                    onDeleteBrandScope={onDeleteBrandScope}
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

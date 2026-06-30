'use client'

import { useState, useEffect, useRef } from 'react'
import { collectorApi, shipmentApi } from '@/lib/samba/api/commerce'
import { showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

type DuplicateItem = {
  id: string
  name: string
  source_site: string
  brand: string | null
  sale_price: number
  images: string[]
  registered_accounts: unknown
  status: string
}

type DeleteLogEntry = {
  time: string
  brand: string
  name: string
  productId: string
  status: 'processing' | 'done' | 'failed' | 'skipped'
}

type DuplicateGroup = {
  name: string
  total: number
  registered: DuplicateItem[]
  duplicates: DuplicateItem[]
}

interface DuplicatesModalProps {
  open: boolean
  sourceSite?: string
  filterIds?: string[]
  onClose: () => void
  onDeleted: () => void
}

export default function DuplicatesModal({ open, sourceSite, filterIds, onClose, onDeleted }: DuplicatesModalProps) {
  const [groups, setGroups] = useState<DuplicateGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [deleteLog, setDeleteLog] = useState<DeleteLogEntry[]>([])
  const logEndRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await collectorApi.getDuplicates(sourceSite, filterIds)
      setGroups(res.groups)
      setChecked(new Set(res.groups.flatMap(g => g.duplicates.map(d => d.id))))
      setLoaded(true)
    } finally {
      setLoading(false)
    }
  }

  // 모달 열릴 때 또는 sourceSite/filterIds 변경 시 자동 조회
  useEffect(() => {
    if (open) {
      setLoaded(false)
      load()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sourceSite, filterIds?.join(',')])

  useEffect(() => {
    if (deleting) logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [deleteLog, deleting])

  if (!open) return null

  const toggleItem = (id: string) => {
    setChecked(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleGroup = (group: DuplicateGroup, select: boolean) => {
    setChecked(prev => {
      const next = new Set(prev)
      for (const d of group.duplicates) {
        if (select) next.add(d.id)
        else next.delete(d.id)
      }
      return next
    })
  }

  const nowStr = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

  const updateLogStatus = (id: string, status: DeleteLogEntry['status']) => {
    setDeleteLog(prev => prev.map(e => e.productId === id ? { ...e, status } : e))
  }

  const handleDelete = async () => {
    if (checked.size === 0) return
    const ids = Array.from(checked)

    // 선택된 중복 상품들의 registered_accounts 수집
    const allDuplicates = groups.flatMap(g => g.duplicates)
    const selected = allDuplicates.filter(d => checked.has(d.id))
    const registeredIds = selected.filter(d => {
      const ra = d.registered_accounts
      return ra && Array.isArray(ra) && ra.length > 0
    })
    const hasMarketRegistered = registeredIds.length > 0

    const confirmMsg = hasMarketRegistered
      ? `선택한 중복 상품 ${fmtNum(ids.length)}개를 삭제합니다.\n마켓에 등록된 ${fmtNum(registeredIds.length)}개는 마켓에서도 삭제됩니다.\n계속하시겠습니까?`
      : `선택한 중복 상품 ${fmtNum(ids.length)}개를 삭제하시겠습니까?`
    const ok = await showConfirm(confirmMsg)
    if (!ok) return

    // 로그 초기화
    setDeleteLog(selected.map(d => ({
      time: nowStr(),
      brand: d.brand ?? '-',
      name: d.name,
      productId: d.id,
      status: 'processing',
    })))

    setDeleting(true)
    try {
      let safeToDeleteIds = ids
      const failedIds = new Set<string>()

      // 마켓 등록 상품은 마켓에서 먼저 삭제
      if (hasMarketRegistered) {
        const marketIds = registeredIds.map(d => d.id)
        const accountIds: string[] = Array.from(
          new Set(registeredIds.flatMap(d => Array.isArray(d.registered_accounts) ? d.registered_accounts as string[] : []))
        )
        const res = await shipmentApi.marketDelete(marketIds, accountIds)

        // 마켓삭제 실패한 상품은 DB 삭제 제외 (고아 상품 방지)
        ;(res.results ?? [])
          .filter(r => r.success_count === 0)
          .forEach(r => failedIds.add(r.product_id))

        if (failedIds.size > 0) {
          safeToDeleteIds = ids.filter(id => !failedIds.has(id))
          failedIds.forEach(id => updateLogStatus(id, 'failed'))
          alert(`마켓삭제 실패 ${fmtNum(failedIds.size)}건 — 해당 상품은 DB 삭제 건너뜀. 재시도하세요.`)
        }
      }

      if (safeToDeleteIds.length > 0) {
        await collectorApi.bulkDeleteProducts(safeToDeleteIds)
        setDeleteLog(prev => prev.map(e =>
          safeToDeleteIds.includes(e.productId) ? { ...e, status: 'done', time: nowStr() } : e
        ))
      }

      // skipped 처리 (마켓삭제 실패가 아닌 나머지 미삭제 항목)
      setDeleteLog(prev => prev.map(e =>
        e.status === 'processing' ? { ...e, status: 'skipped' } : e
      ))

      await load()
      onDeleted()
    } finally {
      setDeleting(false)
    }
  }

  const SITE_COLORS: Record<string, string> = {
    MUSINSA: '#4ECDC4', KREAM: '#FF6B6B', LOTTEON: '#FF8C00',
    SSG: '#FF4081', ABCmart: '#66BB6A', Nike: '#E040FB',
    GSShop: '#29B6F6', FASHIONPLUS: '#FFA726',
  }

  const siteColor = (site: string) => SITE_COLORS[site] ?? '#888'

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#1A1A1A', border: '1px solid #333', borderRadius: '12px', width: '720px', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* 헤더 */}
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid #2A2A2A', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <span style={{ fontSize: '0.95rem', fontWeight: 700, color: '#E5E5E5' }}>중복 상품 조회</span>
            {loaded && (
              <span style={{ marginLeft: '0.75rem', fontSize: '0.78rem', color: '#888' }}>
                {fmtNum(groups.length)}개 그룹 / 중복 {fmtNum(groups.reduce((s, g) => s + g.duplicates.length, 0))}건
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={() => setChecked(new Set(groups.flatMap(g => g.duplicates.map(d => d.id))))}
              disabled={!loaded || groups.length === 0}
              style={{ fontSize: '0.75rem', padding: '0.3rem 0.75rem', background: 'rgba(80,80,80,0.2)', border: '1px solid #333', color: '#AAA', borderRadius: '6px', cursor: 'pointer' }}
            >전체선택</button>
            <button
              onClick={() => setChecked(new Set())}
              disabled={!loaded || checked.size === 0}
              style={{ fontSize: '0.75rem', padding: '0.3rem 0.75rem', background: 'rgba(80,80,80,0.2)', border: '1px solid #333', color: '#AAA', borderRadius: '6px', cursor: 'pointer' }}
            >전체해제</button>
            <button
              onClick={load}
              disabled={loading}
              style={{ fontSize: '0.75rem', padding: '0.3rem 0.75rem', background: 'rgba(100,200,255,0.1)', border: '1px solid rgba(100,200,255,0.3)', color: '#64C8FF', borderRadius: '6px', cursor: loading ? 'not-allowed' : 'pointer' }}
            >
              {loading ? '조회중...' : '새로고침'}
            </button>
            <button
              onClick={handleDelete}
              disabled={deleting || checked.size === 0}
              style={{ fontSize: '0.75rem', padding: '0.3rem 0.75rem', background: checked.size > 0 ? 'rgba(255,100,100,0.15)' : 'rgba(80,80,80,0.2)', border: `1px solid ${checked.size > 0 ? 'rgba(255,100,100,0.35)' : '#333'}`, color: checked.size > 0 ? '#FF6B6B' : '#555', borderRadius: '6px', cursor: checked.size > 0 ? 'pointer' : 'not-allowed' }}
            >
              {deleting ? '삭제중...' : `선택 삭제 (${fmtNum(checked.size)})`}
            </button>
            <button onClick={onClose} style={{ fontSize: '0.85rem', color: '#888', background: 'none', border: 'none', cursor: 'pointer', padding: '0.2rem 0.4rem' }}>✕</button>
          </div>
        </div>

        {/* 본문 */}
        <div style={{ overflowY: 'auto', flex: 1, padding: '0.75rem 1.25rem' }}>
          {/* 삭제 진행 로그 */}
          {deleting && deleteLog.length > 0 && (
            <div style={{ marginBottom: '1rem', background: '#0D0D0D', border: '1px solid #2A2A2A', borderRadius: '8px', overflow: 'hidden' }}>
              <div style={{ padding: '0.5rem 0.875rem', background: '#161616', borderBottom: '1px solid #222', fontSize: '0.78rem', color: '#AAA', fontWeight: 600 }}>
                삭제 진행 중 ({fmtNum(deleteLog.filter(e => e.status === 'done').length)} / {fmtNum(deleteLog.length)})
              </div>
              <div style={{ maxHeight: '220px', overflowY: 'auto', padding: '0.25rem 0' }}>
                {deleteLog.map((entry, i) => {
                  const statusColor = entry.status === 'done' ? '#6DD68A' : entry.status === 'failed' ? '#FF6B6B' : entry.status === 'skipped' ? '#888' : '#FFA726'
                  const statusLabel = entry.status === 'done' ? '완료' : entry.status === 'failed' ? '실패' : entry.status === 'skipped' ? '건너뜀' : '처리중'
                  return (
                    <div key={i} style={{ padding: '0.35rem 0.875rem', display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid #1A1A1A', fontSize: '0.75rem' }}>
                      <span style={{ color: '#555', flexShrink: 0, fontFamily: 'monospace' }}>{entry.time}</span>
                      <span style={{ color: '#888', flexShrink: 0, maxWidth: '80px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.brand}</span>
                      <span style={{ color: '#CCC', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.name}</span>
                      <span style={{ color: '#555', flexShrink: 0, fontFamily: 'monospace', fontSize: '0.7rem' }}>{entry.productId}</span>
                      <span style={{ color: statusColor, flexShrink: 0, fontWeight: 600, minWidth: '40px', textAlign: 'right' }}>{statusLabel}</span>
                    </div>
                  )
                })}
                <div ref={logEndRef} />
              </div>
            </div>
          )}

          {loading && (
            <div style={{ textAlign: 'center', color: '#888', padding: '2rem', fontSize: '0.85rem' }}>조회 중...</div>
          )}
          {!loading && loaded && groups.length === 0 && (
            <div style={{ textAlign: 'center', color: '#666', padding: '2rem', fontSize: '0.85rem' }}>중복 상품이 없습니다.</div>
          )}
          {!loading && groups.map(group => (
            <div key={group.name} style={{ marginBottom: '1rem', background: '#111', borderRadius: '8px', overflow: 'hidden', border: '1px solid #2A2A2A' }}>
              {/* 그룹 헤더 */}
              <div style={{ padding: '0.6rem 0.875rem', background: '#161616', borderBottom: '1px solid #222', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '0.82rem', color: '#DDD', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '480px' }}>{group.name}</span>
                <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                  <button onClick={() => toggleGroup(group, true)} style={{ fontSize: '0.7rem', padding: '0.15rem 0.5rem', background: 'rgba(255,100,100,0.1)', border: '1px solid rgba(255,100,100,0.25)', color: '#FF8888', borderRadius: '4px', cursor: 'pointer' }}>전체선택</button>
                  <button onClick={() => toggleGroup(group, false)} style={{ fontSize: '0.7rem', padding: '0.15rem 0.5rem', background: 'rgba(80,80,80,0.2)', border: '1px solid #333', color: '#888', borderRadius: '4px', cursor: 'pointer' }}>선택해제</button>
                </div>
              </div>

              {/* 등록된 상품 */}
              {group.registered.map(item => (
                <div key={item.id} style={{ padding: '0.5rem 0.875rem', display: 'flex', alignItems: 'center', gap: '10px', borderBottom: '1px solid #1E1E1E', opacity: 0.7 }}>
                  <div style={{ width: '36px', height: '36px', flexShrink: 0, borderRadius: '4px', overflow: 'hidden', background: '#222' }}>
                    {item.images[0] && <img src={item.images[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.78rem', color: '#CCC', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</div>
                    <div style={{ display: 'flex', gap: '6px', marginTop: '2px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.68rem', color: siteColor(item.source_site), fontWeight: 600 }}>{item.source_site}</span>
                      {item.brand && <span style={{ fontSize: '0.68rem', color: '#666' }}>{item.brand}</span>}
                      <span style={{ fontSize: '0.68rem', color: '#888' }}>{fmtNum(item.sale_price)}원</span>
                    </div>
                  </div>
                  <span style={{ fontSize: '0.68rem', background: 'rgba(100,200,100,0.15)', border: '1px solid rgba(100,200,100,0.3)', color: '#6DD68A', padding: '0.15rem 0.5rem', borderRadius: '4px', flexShrink: 0 }}>마켓등록</span>
                </div>
              ))}

              {/* 중복 상품 */}
              {group.duplicates.map(item => (
                <div
                  key={item.id}
                  onClick={() => toggleItem(item.id)}
                  style={{ padding: '0.5rem 0.875rem', display: 'flex', alignItems: 'center', gap: '10px', borderBottom: '1px solid #1E1E1E', cursor: 'pointer', background: checked.has(item.id) ? 'rgba(255,100,100,0.05)' : 'transparent' }}
                >
                  <input
                    type='checkbox'
                    checked={checked.has(item.id)}
                    onChange={() => toggleItem(item.id)}
                    onClick={e => e.stopPropagation()}
                    style={{ flexShrink: 0, accentColor: '#FF6B6B' }}
                  />
                  <div style={{ width: '36px', height: '36px', flexShrink: 0, borderRadius: '4px', overflow: 'hidden', background: '#222' }}>
                    {item.images[0] && <img src={item.images[0]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.78rem', color: '#DDD', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</div>
                    <div style={{ display: 'flex', gap: '6px', marginTop: '2px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.68rem', color: siteColor(item.source_site), fontWeight: 600 }}>{item.source_site}</span>
                      {item.brand && <span style={{ fontSize: '0.68rem', color: '#666' }}>{item.brand}</span>}
                      <span style={{ fontSize: '0.68rem', color: '#888' }}>{fmtNum(item.sale_price)}원</span>
                    </div>
                  </div>
                  <span style={{ fontSize: '0.68rem', background: 'rgba(255,100,100,0.1)', border: '1px solid rgba(255,100,100,0.25)', color: '#FF8888', padding: '0.15rem 0.5rem', borderRadius: '4px', flexShrink: 0 }}>중복</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

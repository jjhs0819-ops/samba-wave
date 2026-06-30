'use client'

import { useMemo, useRef, useState } from 'react'
import { manualProductApi, shipmentApi } from '@/lib/samba/legacy'
import CategorySelector from './CategorySelector'
import ImageManagerModal from './ImageManagerModal'
import type { SambaCollectedProduct } from '@/lib/samba/legacy'
import { fmtNum } from '@/lib/samba/styles'
import { buildMarketPriceList } from '@/lib/samba/marketPrice'
import { light as c } from '@/lib/samba/colors'
import { btn, btnDisabled } from '@/lib/samba/buttons'

interface Policy { id: string; name: string; market_policies?: Record<string, unknown>; pricing?: Record<string, unknown> }

function policyAccountIds(policy: Policy | undefined, accounts: Account[]): Account[] {
  if (!policy?.market_policies) return []
  const ids = Object.values(policy.market_policies).flatMap(mp => {
    const m = mp as Record<string, unknown>
    if (Array.isArray(m.accountIds) && m.accountIds.length > 0) return m.accountIds as string[]
    if (typeof m.accountId === 'string') return [m.accountId]
    return []
  })
  return accounts.filter(a => ids.includes(a.id))
}
interface Account { id: string; market_type: string; account_name: string; additional_fields?: Record<string, unknown> }

interface LogEntry {
  id: number
  time: string
  type: 'transmit' | 'delete'
  message: string
  ok: boolean
}

interface Props {
  product: SambaCollectedProduct
  policies: Policy[]
  accounts: Account[]
  onDeleted: () => void
  onUpdated: (p: SambaCollectedProduct) => void
  onRefresh: () => void
}

const SELECT = `w-full px-2.5 py-1.5 bg-[${c.inputBg}] border border-[${c.border}] rounded text-sm text-[${c.text}] focus:outline-none focus:border-[${c.primary}]`
const INPUT = `w-full px-2.5 py-1.5 bg-[${c.inputBg}] border border-[${c.border}] rounded text-sm text-[${c.text}] placeholder-[${c.textMuted}] focus:outline-none focus:border-[${c.primary}]`
const LABEL = `text-xs text-[${c.textSub}] mb-1 block`

// 수정 폼 옵션 행 (UI 전용 id 포함) — 옵션별 가격 미사용(판매가는 정책 기반)
interface EditOption { id: string; name: string; stock: number }

// 상품 옵션 배열을 수정 폼용으로 정규화 (런타임 형태가 제각각이라 안전 변환)
function toEditOptions(raw: unknown[] | undefined): EditOption[] {
  if (!Array.isArray(raw)) return []
  return raw.map(o => {
    const m = (o ?? {}) as Record<string, unknown>
    return {
      id: crypto.randomUUID(),
      name: typeof m.name === 'string' ? m.name : '',
      stock: Number(m.stock ?? 0) || 0,
    }
  })
}

export default function ManualProductCard({ product, policies, accounts, onDeleted, onUpdated, onRefresh }: Props) {
  const [showCategories, setShowCategories] = useState(false)
  const [showPrices, setShowPrices] = useState(false)
  const [showImageModal, setShowImageModal] = useState(false)
  const [transmitting, setTransmitting] = useState(false)
  const [result, setResult] = useState('')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [deletingAccountId, setDeletingAccountId] = useState<string | null>(null)
  const logSeq = useRef(0)

  // 상품 기본정보 수정 상태
  const [editing, setEditing] = useState(false)
  const [savingEdit, setSavingEdit] = useState(false)
  const [editErr, setEditErr] = useState('')
  const [edit, setEdit] = useState({
    name: '', brand: '', original_price: '', sale_price: '', cost: '',
    manufacturer: '', style_code: '', origin: '', sex: '남녀공용', season: '사계절',
    color: '', material: '', tags: '',
  })
  const [editOptions, setEditOptions] = useState<EditOption[]>([])

  const startEdit = () => {
    setEditErr('')
    setEdit({
      name: product.name ?? '',
      brand: product.brand ?? '',
      original_price: product.original_price != null ? String(product.original_price) : '',
      sale_price: product.sale_price != null ? String(product.sale_price) : '',
      cost: product.cost != null ? String(product.cost) : '',
      manufacturer: product.manufacturer ?? '',
      style_code: product.style_code ?? '',
      origin: product.origin ?? '',
      sex: product.sex || '남녀공용',
      season: product.season || '사계절',
      color: product.color ?? '',
      material: product.material ?? '',
      tags: (product.tags ?? []).join(', '),
    })
    setEditOptions(toEditOptions(product.options))
    setEditing(true)
  }

  const setEditField = (key: keyof typeof edit, val: string) =>
    setEdit(prev => ({ ...prev, [key]: val }))

  const addEditOption = () =>
    setEditOptions(prev => [...prev, { id: crypto.randomUUID(), name: '', stock: 0 }])
  const removeEditOption = (id: string) =>
    setEditOptions(prev => prev.filter(o => o.id !== id))
  const updateEditOption = (id: string, key: 'name' | 'stock', val: string | number) =>
    setEditOptions(prev => prev.map(o => o.id === id ? { ...o, [key]: val } : o))

  const saveEdit = async () => {
    if (!edit.name.trim()) { setEditErr('상품명은 필수입니다'); return }
    setSavingEdit(true)
    setEditErr('')
    try {
      const updated = await manualProductApi.update(product.id, {
        name: edit.name.trim(),
        brand: edit.brand.trim() || undefined,
        original_price: edit.original_price ? Number(edit.original_price) : 0,
        sale_price: edit.sale_price ? Number(edit.sale_price) : 0,
        cost: edit.cost ? Number(edit.cost) : undefined,
        manufacturer: edit.manufacturer.trim() || undefined,
        style_code: edit.style_code.trim() || undefined,
        origin: edit.origin.trim() || undefined,
        sex: edit.sex || undefined,
        season: edit.season || undefined,
        color: edit.color.trim() || undefined,
        material: edit.material.trim() || undefined,
        tags: edit.tags.split(',').map(t => t.trim()).filter(Boolean),
        options: editOptions
          .filter(o => o.name.trim())
          .map(o => ({ name: o.name.trim(), price: 0, stock: o.stock })),
      })
      onUpdated(updated)
      setEditing(false)
    } catch (e) {
      setEditErr('저장 실패: ' + String(e))
    } finally {
      setSavingEdit(false)
    }
  }

  const extraData = (product.extra_data as Record<string, unknown>) ?? {}
  const savedCats = (extraData.manual_market_categories as Record<string, string>) ?? {}

  const addLog = (type: LogEntry['type'], message: string, ok: boolean) => {
    setLogs(prev => [
      ...prev,
      {
        id: logSeq.current++,
        time: new Date().toLocaleTimeString('ko-KR'),
        type,
        message,
        ok,
      },
    ])
  }

  const applyPolicy = async (policyId: string) => {
    const updated = await manualProductApi.update(product.id, { applied_policy_id: policyId })
    onUpdated(updated)
  }

  const saveCategories = async (cats: Record<string, string>) => {
    const updated = await manualProductApi.update(product.id, {
      extra_data: { ...(product.extra_data ?? {}), manual_market_categories: cats },
    })
    onUpdated(updated)
  }

  const saveImages = async (newImages: string[], newDetailImages: string[]) => {
    const updated = await manualProductApi.update(product.id, {
      images: newImages,
      detail_images: newDetailImages,
    })
    onUpdated(updated)
  }

  const transmit = async () => {
    if (!product.applied_policy_id) { setResult('정책을 선택하세요'); return }
    const policy = policies.find(p => p.id === product.applied_policy_id)
    const targetIds = policyAccountIds(policy, accounts).map(a => a.id)
    if (targetIds.length === 0) { setResult('정책에 전송 계정이 없습니다'); return }
    setTransmitting(true)
    setResult('')
    try {
      await shipmentApi.start(
        [product.id],
        ['price', 'stock', 'image', 'description'],
        targetIds,
        false,
      )
      setResult('전송 요청 완료')
      addLog('transmit', `전송 완료 (${fmtNum(targetIds.length)}개 계정)`, true)
    } catch (e) {
      const msg = '전송 실패: ' + String(e)
      setResult(msg)
      addLog('transmit', msg, false)
    } finally {
      setTransmitting(false)
    }
  }

  const deleteFromMarket = async (accountId: string) => {
    const acc = accounts.find(a => a.id === accountId)
    const label = acc ? `${acc.market_type}/${acc.account_name}` : accountId
    setDeletingAccountId(accountId)
    try {
      const res = await shipmentApi.marketDelete([product.id], [accountId])
      const r = res.results?.[0]
      const status = r?.delete_results?.[accountId] ?? 'unknown'
      const ok = status === 'success'
      addLog('delete', `마켓 삭제 [${label}]: ${ok ? '완료' : status}`, ok)
      if (ok) onRefresh()
    } catch (e) {
      addLog('delete', `마켓 삭제 실패 [${label}]: ${String(e)}`, false)
    } finally {
      setDeletingAccountId(null)
    }
  }

  const deleteProduct = async () => {
    if (!confirm('상품을 삭제하시겠습니까?')) return
    await manualProductApi.delete(product.id)
    onDeleted()
  }

  const thumb = product.images?.[0]
  const catCount = Object.keys(savedCats).length
  const marketProductNos = (product.market_product_nos as Record<string, string> | undefined) ?? {}

  // 판매처별 판매가 (정책 기반 — 상품관리 카드와 동일 계산식)
  const appliedPolicy = policies.find(p => p.id === product.applied_policy_id)
  const priceCost = product.cost || product.sale_price || product.original_price || 0
  const marketPriceList = useMemo(() => {
    if (!appliedPolicy?.pricing) return []
    return buildMarketPriceList({
      pricing: appliedPolicy.pricing,
      marketPolicies: appliedPolicy.market_policies ?? {},
      accounts,
      cost: priceCost,
      sourceSite: product.source_site || '',
      isPointRestricted: (product as { is_point_restricted?: boolean | null }).is_point_restricted,
    })
  }, [appliedPolicy, accounts, priceCost, product])

  return (
    <div className={`bg-[${c.surface}] border border-[${c.border}] rounded-lg p-4 space-y-3`}>
      {/* 상품 기본 정보 */}
      <div className='flex gap-3'>
        <div
          onClick={() => setShowImageModal(true)}
          className={`w-16 h-16 rounded border border-[${c.border}] shrink-0 cursor-pointer overflow-hidden bg-[${c.surfaceAlt}] flex items-center justify-center hover:border-[#a9ddd2] transition-colors`}
          title='이미지 관리'
        >
          {thumb ? (
            <img src={thumb} alt='' className='w-full h-full object-cover' />
          ) : (
            <span className={`text-[${c.textMuted}] text-xs`}>이미지</span>
          )}
        </div>
        <div className='flex-1 min-w-0'>
          <p className={`font-medium text-sm text-[${c.text}] truncate`}>{product.name}</p>
          {product.brand && <p className={`text-xs text-[${c.textMuted}] mt-0.5`}>{product.brand}</p>}
          <div className={`flex gap-3 mt-1 text-xs text-[${c.textMuted}]`}>
            <span>원가 {fmtNum(product.cost ?? 0)}원</span>
            <span>판매가 {fmtNum(product.sale_price ?? 0)}원</span>
          </div>
        </div>
        <div className='flex flex-col gap-1.5 self-start shrink-0 items-end'>
          {!editing && (
            <button onClick={startEdit} className={`text-[${c.textSub}] text-xs hover:underline`}>수정</button>
          )}
          <button onClick={deleteProduct} className={`text-[${c.danger}] text-xs hover:underline`}>삭제</button>
        </div>
      </div>

      {/* 기본정보 수정 폼 */}
      {editing && (
        <div className={`space-y-2 border border-[${c.border}] rounded-lg p-3 bg-[${c.surfaceAlt}]`}>
          <input className={INPUT} value={edit.name} onChange={e => setEditField('name', e.target.value)} placeholder='상품명 *' />
          <input className={INPUT} value={edit.brand} onChange={e => setEditField('brand', e.target.value)} placeholder='브랜드' />
          <div className='grid grid-cols-3 gap-2'>
            <div>
              <label className={LABEL}>정상가</label>
              <input type='number' className={INPUT} value={edit.original_price} onChange={e => setEditField('original_price', e.target.value)} placeholder='0' />
            </div>
            <div>
              <label className={LABEL}>할인가</label>
              <input type='number' className={INPUT} value={edit.sale_price} onChange={e => setEditField('sale_price', e.target.value)} placeholder='0' />
            </div>
            <div>
              <label className={LABEL}>원가</label>
              <input type='number' className={INPUT} value={edit.cost} onChange={e => setEditField('cost', e.target.value)} placeholder='0' />
            </div>
          </div>
          <div className='grid grid-cols-2 gap-2'>
            <input className={INPUT} value={edit.manufacturer} onChange={e => setEditField('manufacturer', e.target.value)} placeholder='제조사' />
            <input className={INPUT} value={edit.style_code} onChange={e => setEditField('style_code', e.target.value)} placeholder='품번' />
            <input className={INPUT} value={edit.origin} onChange={e => setEditField('origin', e.target.value)} placeholder='제조국' />
            <input className={INPUT} value={edit.color} onChange={e => setEditField('color', e.target.value)} placeholder='색상' />
            <select className={SELECT} value={edit.sex} onChange={e => setEditField('sex', e.target.value)}>
              <option>남녀공용</option><option>남성</option><option>여성</option><option>키즈</option>
            </select>
            <select className={SELECT} value={edit.season} onChange={e => setEditField('season', e.target.value)}>
              <option>사계절</option><option>봄/여름</option><option>가을/겨울</option><option>봄</option><option>여름</option><option>가을</option><option>겨울</option>
            </select>
            <input className={`col-span-2 px-2.5 py-1.5 bg-[${c.inputBg}] border border-[${c.border}] rounded text-sm text-[${c.text}] placeholder-[${c.textMuted}] focus:outline-none focus:border-[${c.primary}]`} value={edit.material} onChange={e => setEditField('material', e.target.value)} placeholder='재질 (예: 면 100%)' />
          </div>

          {/* 태그 (쉼표 구분) */}
          <div>
            <label className={LABEL}>태그 (쉼표로 구분)</label>
            <input className={INPUT} value={edit.tags} onChange={e => setEditField('tags', e.target.value)} placeholder='예: 봄신상, 캐주얼, 데일리' />
          </div>

          {/* 옵션 */}
          <div>
            <div className='flex justify-between items-center mb-1'>
              <label className={LABEL}>옵션</label>
              <button onClick={addEditOption} className={`text-xs text-[${c.textSub}] hover:text-[${c.text}]`}>+ 추가</button>
            </div>
            <div className={`grid grid-cols-[1fr_90px_24px] gap-2 text-xs text-[${c.textSub}] px-0.5 mb-1`}>
              <span>옵션명</span><span>재고</span><span />
            </div>
            <div className='space-y-1.5'>
              {editOptions.map(opt => (
                <div key={opt.id} className='grid grid-cols-[1fr_90px_24px] gap-2'>
                  <input className={INPUT} value={opt.name} onChange={e => updateEditOption(opt.id, 'name', e.target.value)} placeholder='옵션명 (예: 블랙/L)' />
                  <input type='number' className={INPUT} value={opt.stock} onChange={e => updateEditOption(opt.id, 'stock', Number(e.target.value))} placeholder='0' />
                  <button onClick={() => removeEditOption(opt.id)} className={`text-[${c.danger}] text-sm`}>×</button>
                </div>
              ))}
              {editOptions.length === 0 && (
                <p className={`text-xs text-[${c.textMuted}]`}>옵션 없음 (추가하면 단일/다중 옵션 등록)</p>
              )}
            </div>
          </div>

          {editErr && <p className={`text-[${c.danger}] text-xs`}>{editErr}</p>}

          <div className='flex gap-2 justify-end pt-1'>
            <button onClick={() => setEditing(false)} disabled={savingEdit} style={{ ...btn('ghost'), ...(savingEdit ? btnDisabled : null) }} className='px-3 py-1.5 text-sm rounded'>취소</button>
            <button onClick={saveEdit} disabled={savingEdit} style={{ ...btn('primary'), ...(savingEdit ? btnDisabled : null) }} className='px-4 py-1.5 text-sm'>{savingEdit ? '저장 중...' : '저장'}</button>
          </div>
        </div>
      )}

      {/* 정책 */}
      <div>
        <label className={`text-xs text-[${c.textSub}] block mb-1`}>정책</label>
        <select className={SELECT} value={product.applied_policy_id ?? ''} onChange={e => applyPolicy(e.target.value)}>
          <option value=''>정책 없음</option>
          {policies.map(p => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* 판매처별 판매가 — 정책 기반 계산 (상품관리와 동일) */}
      {marketPriceList.length > 0 && (
        <div>
          <button
            onClick={() => setShowPrices(v => !v)}
            className={`text-xs text-[${c.textSub}] hover:text-[${c.text}]`}
          >
            {showPrices ? '판매처별 판매가 접기 ▲' : `판매처별 판매가 보기 ▼ (${fmtNum(marketPriceList.length)}개)`}
          </button>
          {showPrices && (
            <div className='flex flex-col gap-1.5 mt-1'>
              {marketPriceList.map(m => (
                <div key={m.marketName} className={`bg-[${c.surfaceAlt}] border border-[${c.border}] rounded px-2.5 py-1.5`}>
                  <div className='flex items-center justify-between'>
                    <span className={`text-xs text-[${c.textSub}]`}>{m.marketName === '신세계몰(전시)' ? '신세계몰' : m.marketName}</span>
                    <span className={`text-sm font-semibold text-[${c.text}]`}>{m.calcStr.split(' = ')[0]}</span>
                  </div>
                  <div className={`text-[0.68rem] text-[${c.textMuted}] mt-0.5`}>{m.calcStr.split(' = ')[1]}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 카테고리 — 정책 연결 시에만 표시 */}
      {product.applied_policy_id && (() => {
        const policy = policies.find(p => p.id === product.applied_policy_id)
        const linked = policyAccountIds(policy, accounts)
        if (linked.length === 0) return null
        return (
          <div>
            <button
              onClick={() => setShowCategories(v => !v)}
              className={`text-xs text-[${c.textSub}] hover:text-[${c.text}]`}
            >
              {showCategories ? '카테고리 접기 ▲' : `마켓별 카테고리 ▼${catCount > 0 ? ` (${fmtNum(catCount)}개 설정됨)` : ''}`}
            </button>
            {showCategories && (
              <div className='mt-2'>
                <CategorySelector
                  accounts={linked}
                  savedCategories={savedCats}
                  onSave={saveCategories}
                  marketProductNos={marketProductNos}
                  onDeleteFromMarket={deleteFromMarket}
                  deletingAccountId={deletingAccountId ?? undefined}
                />
              </div>
            )}
          </div>
        )
      })()}

      {/* 전송 */}
      <div className='pt-1 space-y-2'>
        <div className='flex items-center gap-2'>
          <button
            onClick={transmit}
            disabled={transmitting}
            style={{ ...btn('primary'), ...(transmitting ? btnDisabled : null) }}
            className='px-4 py-1.5 text-sm'
          >
            {transmitting ? '전송 중...' : '마켓 전송'}
          </button>
          {result && (
            <span className={`text-xs ${result.includes('실패') || result.includes('선택') ? `text-[${c.danger}]` : `text-[${c.success}]`}`}>
              {result}
            </span>
          )}
        </div>

        {/* 로그창 */}
        {logs.length > 0 && (
          <div
            style={{
              maxHeight: 120,
              overflowY: 'auto',
              background: c.surfaceAlt,
              border: `1px solid ${c.border}`,
              borderRadius: 6,
              padding: '6px 8px',
            }}
          >
            {logs.map(log => (
              <div
                key={log.id}
                style={{
                  display: 'flex',
                  gap: 6,
                  fontSize: 11,
                  lineHeight: '18px',
                  color: log.ok ? c.success : c.danger,
                }}
              >
                <span style={{ color: c.textMuted, flexShrink: 0 }}>{log.time}</span>
                <span style={{ color: c.textMuted, flexShrink: 0 }}>{log.type === 'transmit' ? '전송' : '삭제'}</span>
                <span style={{ wordBreak: 'break-all' }}>{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {showImageModal && (
        <ImageManagerModal
          images={product.images ?? []}
          detailImages={(product.detail_images as string[] | undefined) ?? []}
          onSave={saveImages}
          onClose={() => setShowImageModal(false)}
        />
      )}
    </div>
  )
}

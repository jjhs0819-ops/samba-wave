'use client'

import { useState } from 'react'
import { manualProductApi } from '@/lib/samba/legacy'
import ImageManagerModal from './ImageManagerModal'
import CategorySelector from './CategorySelector'

interface Account {
  id: string
  market_type: string
  account_name: string
}

interface Policy {
  id: string
  name: string
  market_policies?: Record<string, unknown>
}

interface Props {
  accounts: Account[]
  policies: Policy[]
  onCreated: () => void
}

interface OptionRow {
  id: string
  name: string
  price: number
  stock: number
}

const INPUT = 'w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] placeholder-[#444] focus:outline-none focus:border-[#FF8C00]'
const LABEL = 'text-xs text-[#666] mb-1 block'

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

export default function NewProductCard({ accounts, policies, onCreated }: Props) {
  const [name, setName] = useState('')
  const [nameEn, setNameEn] = useState('')
  const [nameJa, setNameJa] = useState('')
  const [brand, setBrand] = useState('')
  const [originalPrice, setOriginalPrice] = useState('')
  const [salePrice, setSalePrice] = useState('')
  const [cost, setCost] = useState('')
  const [manufacturer, setManufacturer] = useState('')
  const [styleCode, setStyleCode] = useState('')
  const [origin, setOrigin] = useState('')
  const [sex, setSex] = useState('남녀공용')
  const [season, setSeason] = useState('사계절')
  const [color, setColor] = useState('')
  const [material, setMaterial] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [detailImages, setDetailImages] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [options, setOptions] = useState<OptionRow[]>([
    { id: crypto.randomUUID(), name: '', price: 0, stock: 0 },
  ])
  const [selectedPolicyId, setSelectedPolicyId] = useState('')
  const [pendingCategories, setPendingCategories] = useState<Record<string, string>>({})
  const [showImageModal, setShowImageModal] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const addTag = () => {
    const t = tagInput.trim()
    if (t && !tags.includes(t)) setTags(prev => [...prev, t])
    setTagInput('')
  }
  const removeTag = (t: string) => setTags(prev => prev.filter(v => v !== t))

  const addOption = () =>
    setOptions(prev => [...prev, { id: crypto.randomUUID(), name: '', price: 0, stock: 0 }])
  const removeOption = (id: string) =>
    setOptions(prev => prev.filter(o => o.id !== id))
  const updateOption = (id: string, key: 'name' | 'price' | 'stock', val: string | number) =>
    setOptions(prev => prev.map(o => o.id === id ? { ...o, [key]: val } : o))

  const reset = () => {
    setName(''); setNameEn(''); setNameJa(''); setBrand('')
    setOriginalPrice(''); setSalePrice(''); setCost('')
    setManufacturer(''); setStyleCode(''); setOrigin('')
    setSex('남녀공용'); setSeason('사계절'); setColor(''); setMaterial('')
    setImages([]); setDetailImages([]); setTags([])
    setOptions([{ id: crypto.randomUUID(), name: '', price: 0, stock: 0 }])
    setSelectedPolicyId('')
    setPendingCategories({})
    setError('')
  }

  const handleSubmit = async () => {
    if (!name.trim()) { setError('상품명은 필수입니다'); return }
    setSaving(true)
    setError('')
    try {
      const created = await manualProductApi.create({
        name: name.trim(),
        name_en: nameEn.trim() || undefined,
        name_ja: nameJa.trim() || undefined,
        brand: brand.trim() || undefined,
        original_price: originalPrice ? Number(originalPrice) : undefined,
        sale_price: salePrice ? Number(salePrice) : undefined,
        cost: cost ? Number(cost) : (originalPrice ? Number(originalPrice) : undefined),
        images: images.filter(Boolean),
        detail_images: detailImages.filter(Boolean),
        options: options.filter(o => o.name.trim()).map(({ id: _id, ...rest }) => rest),
        manufacturer: manufacturer.trim() || undefined,
        style_code: styleCode.trim() || undefined,
        origin: origin.trim() || undefined,
        sex: sex || undefined,
        season: season || undefined,
        color: color.trim() || undefined,
        material: material.trim() || undefined,
        tags: tags.length > 0 ? tags : undefined,
      })
      const updates: Record<string, unknown> = {}
      if (selectedPolicyId) updates.applied_policy_id = selectedPolicyId
      if (Object.keys(pendingCategories).length > 0) updates.extra_data = { manual_market_categories: pendingCategories }
      if (Object.keys(updates).length > 0) {
        await manualProductApi.update(created.id, updates)
      }
      reset()
      onCreated()
    } catch (e) {
      setError('등록 실패: ' + String(e))
    } finally {
      setSaving(false)
    }
  }

  const thumb = images[0]

  return (
    <>
      <div className='bg-[#111] border border-[#1A1A1A] rounded-lg p-4 mb-6 space-y-4'>
        <p className='text-sm font-semibold text-[#FF8C00]'>새 상품 등록</p>

        {/* 이미지 + 기본정보 */}
        <div className='flex gap-4'>
          <div
            onClick={() => setShowImageModal(true)}
            className='w-20 h-20 rounded border border-[#2D2D2D] shrink-0 cursor-pointer overflow-hidden bg-[#0A0A0A] flex flex-col items-center justify-center hover:border-[#FF8C00] transition-colors'
            title='이미지 추가/관리'
          >
            {thumb ? (
              <img src={thumb} alt='' className='w-full h-full object-cover' />
            ) : (
              <>
                <span className='text-[#444] text-lg'>+</span>
                <span className='text-[#444] text-xs'>이미지</span>
              </>
            )}
          </div>

          <div className='flex-1 space-y-2'>
            <input className={INPUT} value={name} onChange={e => setName(e.target.value)} placeholder='상품명 *' />
            <div className='grid grid-cols-2 gap-2'>
              <input className={INPUT} value={nameEn} onChange={e => setNameEn(e.target.value)} placeholder='영문 상품명' />
              <input className={INPUT} value={nameJa} onChange={e => setNameJa(e.target.value)} placeholder='일문 상품명' />
            </div>
            <input className={INPUT} value={brand} onChange={e => setBrand(e.target.value)} placeholder='브랜드' />
          </div>
        </div>

        {/* 가격 */}
        <div className='grid grid-cols-3 gap-2'>
          <div>
            <label className={LABEL}>정상가</label>
            <input type='number' className={INPUT} value={originalPrice} onChange={e => setOriginalPrice(e.target.value)} placeholder='0' />
          </div>
          <div>
            <label className={LABEL}>할인가</label>
            <input type='number' className={INPUT} value={salePrice} onChange={e => setSalePrice(e.target.value)} placeholder='0' />
          </div>
          <div>
            <label className={LABEL}>원가</label>
            <input type='number' className={INPUT} value={cost} onChange={e => setCost(e.target.value)} placeholder='0' />
          </div>
        </div>

        {/* 상품정보 */}
        <div>
          <label className={LABEL}>상품정보</label>
          <div className='grid grid-cols-4 gap-2'>
            <input className={INPUT} value={manufacturer} onChange={e => setManufacturer(e.target.value)} placeholder='제조사' />
            <input className={INPUT} value={styleCode} onChange={e => setStyleCode(e.target.value)} placeholder='품번' />
            <input className={INPUT} value={origin} onChange={e => setOrigin(e.target.value)} placeholder='제조국' />
            <input className={INPUT} value={color} onChange={e => setColor(e.target.value)} placeholder='색상' />
            <select className={INPUT} value={sex} onChange={e => setSex(e.target.value)}>
              <option>남녀공용</option><option>남성</option><option>여성</option><option>키즈</option>
            </select>
            <select className={INPUT} value={season} onChange={e => setSeason(e.target.value)}>
              <option>사계절</option><option>봄/여름</option><option>가을/겨울</option><option>봄</option><option>여름</option><option>가을</option><option>겨울</option>
            </select>
            <input className='col-span-2 px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] placeholder-[#444] focus:outline-none focus:border-[#FF8C00]' value={material} onChange={e => setMaterial(e.target.value)} placeholder='재질 (예: 면 100%)' />
          </div>
        </div>

        {/* 정책 */}
        <div>
          <label className={LABEL}>정책</label>
          <select
            className={INPUT}
            value={selectedPolicyId}
            onChange={e => { setSelectedPolicyId(e.target.value); setPendingCategories({}) }}
          >
            <option value=''>정책 없음</option>
            {policies.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* 판매처별 카테고리 — 정책 선택 시에만 표시 */}
        {selectedPolicyId && (() => {
          const policy = policies.find(p => p.id === selectedPolicyId)
          const linked = policyAccountIds(policy, accounts)
          return linked.length > 0 ? (
            <div>
              <label className={LABEL}>판매처별 카테고리</label>
              <CategorySelector accounts={linked} savedCategories={pendingCategories} onSave={setPendingCategories} />
            </div>
          ) : (
            <p className='text-xs text-[#666]'>이 정책에 연결된 판매처 계정이 없습니다.</p>
          )
        })()}

        {/* 태그 */}
        <div>
          <label className={LABEL}>태그</label>
          <div className='flex gap-2 mb-2'>
            <input
              className={INPUT}
              value={tagInput}
              onChange={e => setTagInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
              placeholder='태그 입력 후 Enter'
            />
            <button onClick={addTag} className='px-3 py-1.5 bg-[#1A1A1A] text-[#999] text-sm rounded hover:text-[#E5E5E5]'>추가</button>
          </div>
          {tags.length > 0 && (
            <div className='flex flex-wrap gap-1'>
              {tags.map(t => (
                <span key={t} className='inline-flex items-center gap-1 bg-[#1A1A1A] text-[#999] text-xs px-2 py-0.5 rounded'>
                  {t}
                  <button onClick={() => removeTag(t)} className='text-[#666] hover:text-[#FF6B6B]'>×</button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 옵션 */}
        <div>
          <div className='flex justify-between items-center mb-1'>
            <label className={LABEL}>옵션</label>
            <button onClick={addOption} className='text-xs text-[#FF8C00] hover:text-[#E07B00]'>+ 추가</button>
          </div>
          <div className='grid grid-cols-[1fr_100px_100px_24px] gap-2 text-xs text-[#666] px-0.5 mb-1'>
            <span>옵션명</span><span>가격</span><span>재고</span><span />
          </div>
          <div className='space-y-1.5'>
            {options.map(opt => (
              <div key={opt.id} className='grid grid-cols-[1fr_100px_100px_24px] gap-2'>
                <input className={INPUT} value={opt.name} onChange={e => updateOption(opt.id, 'name', e.target.value)} placeholder='옵션명 (예: 블랙/L)' />
                <input type='number' className={INPUT} value={opt.price} onChange={e => updateOption(opt.id, 'price', Number(e.target.value))} placeholder='0' />
                <input type='number' className={INPUT} value={opt.stock} onChange={e => updateOption(opt.id, 'stock', Number(e.target.value))} placeholder='0' />
                {options.length > 1 ? (
                  <button onClick={() => removeOption(opt.id)} className='text-[#FF6B6B] text-sm'>×</button>
                ) : <span />}
              </div>
            ))}
          </div>
        </div>

        {error && <p className='text-[#FF6B6B] text-xs'>{error}</p>}

        <div className='flex justify-end'>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className='px-5 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00] disabled:opacity-50'
          >
            {saving ? '등록 중...' : '등록'}
          </button>
        </div>
      </div>

      {showImageModal && (
        <ImageManagerModal
          images={images}
          detailImages={detailImages}
          onSave={(imgs, dets) => { setImages(imgs); setDetailImages(dets) }}
          onClose={() => setShowImageModal(false)}
        />
      )}
    </>
  )
}

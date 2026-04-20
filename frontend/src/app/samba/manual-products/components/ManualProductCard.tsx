'use client'

import { useState } from 'react'
import { manualProductApi, shipmentApi } from '@/lib/samba/legacy'
import CategorySelector from './CategorySelector'
import ImageManagerModal from './ImageManagerModal'
import type { SambaCollectedProduct } from '@/lib/samba/legacy'
import { fmtNum } from '@/lib/samba/styles'

interface Policy { id: string; name: string }
interface Account { id: string; market_type: string; account_name: string }

interface Props {
  product: SambaCollectedProduct
  policies: Policy[]
  accounts: Account[]
  onDeleted: () => void
  onUpdated: (p: SambaCollectedProduct) => void
}

const SELECT = 'w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] focus:outline-none focus:border-[#FF8C00]'

export default function ManualProductCard({ product, policies, accounts, onDeleted, onUpdated }: Props) {
  const [showCategories, setShowCategories] = useState(false)
  const [showImageModal, setShowImageModal] = useState(false)
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([])
  const [transmitting, setTransmitting] = useState(false)
  const [result, setResult] = useState('')

  const extraData = (product.extra_data as Record<string, unknown>) ?? {}
  const savedCats = (extraData.manual_market_categories as Record<string, string>) ?? {}

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
    if (selectedAccounts.length === 0) { setResult('전송할 계정을 선택하세요'); return }
    setTransmitting(true)
    setResult('')
    try {
      await shipmentApi.start(
        [product.id],
        ['price', 'stock', 'image', 'description'],
        selectedAccounts,
        false,
      )
      setResult('전송 요청 완료')
    } catch (e) {
      setResult('전송 실패: ' + String(e))
    } finally {
      setTransmitting(false)
    }
  }

  const deleteProduct = async () => {
    if (!confirm('상품을 삭제하시겠습니까?')) return
    await manualProductApi.delete(product.id)
    onDeleted()
  }

  const thumb = product.images?.[0]
  const catCount = Object.keys(savedCats).length

  return (
    <div className='bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3'>
      {/* 상품 기본 정보 */}
      <div className='flex gap-3'>
        <div
          onClick={() => setShowImageModal(true)}
          className='w-16 h-16 rounded border border-[#2D2D2D] shrink-0 cursor-pointer overflow-hidden bg-[#0A0A0A] flex items-center justify-center hover:border-[#FF8C00] transition-colors'
          title='이미지 관리'
        >
          {thumb ? (
            <img src={thumb} alt='' className='w-full h-full object-cover' />
          ) : (
            <span className='text-[#444] text-xs'>이미지</span>
          )}
        </div>
        <div className='flex-1 min-w-0'>
          <p className='font-medium text-sm text-[#E5E5E5] truncate'>{product.name}</p>
          {product.brand && <p className='text-xs text-[#666] mt-0.5'>{product.brand}</p>}
          <div className='flex gap-3 mt-1 text-xs text-[#888]'>
            <span>원가 {fmtNum(product.cost ?? 0)}원</span>
            <span>판매가 {fmtNum(product.sale_price ?? 0)}원</span>
          </div>
        </div>
        <button onClick={deleteProduct} className='text-[#FF6B6B] text-xs self-start shrink-0 hover:underline'>삭제</button>
      </div>

      {/* 정책 */}
      <div>
        <label className='text-xs text-[#666] block mb-1'>정책</label>
        <select className={SELECT} value={product.applied_policy_id ?? ''} onChange={e => applyPolicy(e.target.value)}>
          <option value=''>정책 없음</option>
          {policies.map(p => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* 전송 계정 */}
      <div>
        <label className='text-xs text-[#666] block mb-1'>전송 계정</label>
        <div className='flex flex-wrap gap-1'>
          {accounts.map(acc => (
            <label key={acc.id} className='flex items-center gap-1.5 text-xs bg-[#0A0A0A] border border-[#1A1A1A] rounded px-2 py-1 cursor-pointer select-none hover:border-[#2D2D2D]'>
              <input
                type='checkbox'
                checked={selectedAccounts.includes(acc.id)}
                onChange={e =>
                  setSelectedAccounts(prev =>
                    e.target.checked ? [...prev, acc.id] : prev.filter(id => id !== acc.id)
                  )
                }
                className='accent-[#FF8C00]'
              />
              <span className='text-[#999]'>{acc.market_type}</span>
              <span className='text-[#666]'>{acc.account_name}</span>
            </label>
          ))}
        </div>
      </div>

      {/* 카테고리 */}
      <div>
        <button
          onClick={() => setShowCategories(v => !v)}
          className='text-xs text-[#FF8C00] hover:text-[#E07B00]'
        >
          {showCategories ? '카테고리 접기 ▲' : `마켓별 카테고리 ▼${catCount > 0 ? ` (${fmtNum(catCount)}개 설정됨)` : ''}`}
        </button>
        {showCategories && (
          <div className='mt-2'>
            <CategorySelector
              accounts={selectedAccounts.length > 0
                ? accounts.filter(a => selectedAccounts.includes(a.id))
                : accounts}
              savedCategories={savedCats}
              onSave={saveCategories}
            />
          </div>
        )}
      </div>

      {/* 전송 */}
      <div className='flex items-center gap-2 pt-1'>
        <button
          onClick={transmit}
          disabled={transmitting}
          className='px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00] disabled:opacity-50'
        >
          {transmitting ? '전송 중...' : '마켓 전송'}
        </button>
        {result && (
          <span className={`text-xs ${result.includes('실패') || result.includes('선택') ? 'text-[#FF6B6B]' : 'text-green-400'}`}>
            {result}
          </span>
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

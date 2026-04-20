'use client'

import { useCallback, useEffect, useState } from 'react'
import { manualProductApi, policyApi, accountApi } from '@/lib/samba/legacy'
import type { SambaCollectedProduct, SambaPolicy, SambaMarketAccount } from '@/lib/samba/legacy'
import NewProductCard from './components/NewProductCard'
import ManualProductCard from './components/ManualProductCard'

interface Policy { id: string; name: string }
interface Account { id: string; market_type: string; account_name: string }

export default function ManualProductsPage() {
  const [products, setProducts] = useState<SambaCollectedProduct[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [prods, pols, accs] = await Promise.all([
        manualProductApi.list(),
        policyApi.list(),
        accountApi.list(),
      ])
      setProducts(prods)
      setPolicies((pols as SambaPolicy[]).map(p => ({ id: p.id, name: p.name })))
      setAccounts(
        (accs as SambaMarketAccount[]).map(a => ({
          id: a.id,
          market_type: a.market_type,
          account_name: a.account_label,
        }))
      )
    } catch (e) {
      console.error('상품/정책/계정 로드 실패', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDeleted = (id: string) =>
    setProducts(prev => prev.filter(p => p.id !== id))

  const handleUpdated = (updated: SambaCollectedProduct) =>
    setProducts(prev => prev.map(p => p.id === updated.id ? updated : p))

  return (
    <div className='p-6 max-w-4xl mx-auto'>
      <h1 className='text-xl font-bold text-[#E5E5E5] mb-6'>수동 상품 등록</h1>

      <NewProductCard accounts={accounts} onCreated={load} />

      {loading ? (
        <p className='text-sm text-[#666]'>불러오는 중...</p>
      ) : products.length > 0 ? (
        <div className='grid grid-cols-1 md:grid-cols-2 gap-4'>
          {products.map(p => (
            <ManualProductCard
              key={p.id}
              product={p}
              policies={policies}
              accounts={accounts}
              onDeleted={() => handleDeleted(p.id)}
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      ) : (
        <p className='text-center py-10 text-[#444] text-sm'>등록된 상품이 없습니다.</p>
      )}
    </div>
  )
}

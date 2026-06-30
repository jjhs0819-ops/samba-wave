'use client'

import { useCallback, useEffect, useState } from 'react'
import { manualProductApi, policyApi, accountApi } from '@/lib/samba/legacy'
import type { SambaCollectedProduct, SambaPolicy, SambaMarketAccount } from '@/lib/samba/legacy'
import NewProductCard from './components/NewProductCard'
import ManualProductCard from './components/ManualProductCard'
import { light as c } from '@/lib/samba/colors'

interface Policy { id: string; name: string; market_policies?: Record<string, unknown>; pricing?: Record<string, unknown> }
interface Account { id: string; market_type: string; account_name: string; additional_fields?: Record<string, unknown> }

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
      setPolicies((pols as SambaPolicy[]).map(p => ({ id: p.id, name: p.name, market_policies: p.market_policies, pricing: p.pricing })))
      setAccounts(
        (accs as SambaMarketAccount[]).map(a => ({
          id: a.id,
          market_type: a.market_type,
          account_name: a.account_label,
          additional_fields: a.additional_fields,
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
      <h1 className='text-xl font-bold mb-6' style={{ color: c.text }}>수동 상품 등록</h1>

      <NewProductCard accounts={accounts} policies={policies} onCreated={load} />

      {loading ? (
        <p className='text-sm' style={{ color: c.textMuted }}>불러오는 중...</p>
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
              onRefresh={load}
            />
          ))}
        </div>
      ) : (
        <p className='text-center py-10 text-sm' style={{ color: c.textMuted }}>등록된 상품이 없습니다.</p>
      )}
    </div>
  )
}

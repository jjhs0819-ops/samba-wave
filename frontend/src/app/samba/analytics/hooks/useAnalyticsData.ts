'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  accountApi, collectorApi, orderApi,
  type SambaMarketAccount, type SambaOrder,
} from '@/lib/samba/api/commerce'
import {
  analyticsApi,
  type SourcingRoi, type ProductPerformance, type BrandSales,
} from '@/lib/samba/api/operations'
import { SOURCE_SITES } from '../constants'

interface Args {
  searchYear: number
  searchMonth: number
  setSelectedSites: (v: string[]) => void
  setSelectedMarkets: (v: string[]) => void
}

export function useAnalyticsData({ searchYear, searchMonth, setSelectedSites, setSelectedMarkets }: Args) {
  const [loading, setLoading] = useState(true)
  const [marketAccounts, setMarketAccounts] = useState<SambaMarketAccount[]>([])
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [, setChannelData] = useState<{ channel_name: string; sales: number; orders: number; profit: number }[]>([])
  const [dailyData, setDailyData] = useState<{ date: string; sales: number; orders: number; profit: number }[]>([])
  const [sourcingRoi, setSourcingRoi] = useState<SourcingRoi[]>([])
  const [bestSellers, setBestSellers] = useState<ProductPerformance[]>([])
  const [brandData, setBrandData] = useState<BrandSales[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const start = searchMonth > 0
        ? `${searchYear}-${String(searchMonth).padStart(2, '0')}-01`
        : `${searchYear}-01-01`
      const end = searchMonth > 0
        ? `${searchYear}-${String(searchMonth).padStart(2, '0')}-${new Date(searchYear, searchMonth, 0).getDate()}`
        : `${searchYear}-12-31`
      const allOrders = await orderApi.listByDateRange(start, end).catch(() => [])
      setOrders(allOrders)

      const [ch, daily, roi, best, brands] = await Promise.all([
        analyticsApi.channels().catch(() => []),
        analyticsApi.daily(30).catch(() => []),
        analyticsApi.sourcingRoi(start, end).catch(() => []),
        analyticsApi.bestSellers(10, 30).catch(() => []),
        analyticsApi.brands(start, end).catch(() => []),
      ])
      setChannelData(ch)
      setDailyData(daily)
      setSourcingRoi(roi)
      setBestSellers(best)
      setBrandData(brands)
    } catch {}
    setLoading(false)
  }, [searchYear, searchMonth])

  useEffect(() => { load() }, [load])

  // 마켓 계정 목록 + 소싱사이트 기본값
  useEffect(() => {
    const init = async () => {
      const accounts = await accountApi.listActive().catch(() => [] as SambaMarketAccount[])
      setMarketAccounts(accounts)
      const allData = await collectorApi.scrollProducts({ limit: 1 }).catch(() => null)
      if (allData) {
        const collectedSites = (allData.sites || []).filter((s: string) => SOURCE_SITES.includes(s))
        if (collectedSites.length > 0) setSelectedSites(collectedSites)
      }
    }
    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 마켓 기본값: 주문 데이터에서 마켓 추출
  const initialMarketSet = useRef(false)
  useEffect(() => {
    if (!initialMarketSet.current && orders.length > 0) {
      initialMarketSet.current = true
      const orderMarkets = new Set<string>()
      for (const o of orders) {
        if (o.channel_name) {
          const name = o.channel_name
          const idx = name.indexOf('(')
          orderMarkets.add(idx > 0 ? name.substring(0, idx) : name)
        }
      }
      if (orderMarkets.size > 0) setSelectedMarkets([...orderMarkets])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orders])

  return {
    loading, marketAccounts, orders,
    dailyData, sourcingRoi, bestSellers, brandData,
    load,
  }
}

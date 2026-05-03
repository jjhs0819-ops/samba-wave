'use client'

import { useMemo } from 'react'
import { type SambaOrder, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { parseActionTags } from '../utils/actionTag'

interface Args {
  orders: SambaOrder[]
  accounts: SambaMarketAccount[]
  isProductMode: boolean
  customStart: string
  customEnd: string
  marketFilter: string
  siteFilter: string
  accountFilter: string
  marketStatus: string
  statusFilter: string
  inputFilter: string
  searchText: string
  searchCategory: string
  sortBy: string
  activeActions: Record<string, string | null>
}

export function useFilteredOrders(args: Args) {
  const {
    orders, accounts, isProductMode,
    customStart, customEnd, marketFilter, siteFilter, accountFilter,
    marketStatus, statusFilter, inputFilter, searchText, searchCategory,
    sortBy, activeActions,
  } = args

  return useMemo(() => orders.filter(o => {
    if (!isProductMode) {
      const orderDate = new Date(o.paid_at || o.created_at)
      if (customStart) {
        const start = new Date(customStart)
        start.setHours(0, 0, 0, 0)
        if (orderDate < start) return false
      }
      if (customEnd) {
        const end = new Date(customEnd)
        end.setHours(23, 59, 59, 999)
        if (orderDate > end) return false
      }
    }
    if (marketFilter) {
      if (marketFilter.startsWith('acc:')) {
        if (o.channel_id !== marketFilter.slice(4)) return false
      } else if (marketFilter.startsWith('type:')) {
        const mtype = marketFilter.slice(5)
        const acc = accounts.find(a => a.id === o.channel_id)
        if (acc) {
          if (acc.market_type !== mtype) return false
        } else {
          const marketName = accounts.find(a => a.market_type === mtype)?.market_name || mtype
          if (!o.channel_name?.includes(marketName)) return false
        }
      }
    }
    if (siteFilter) {
      if (o.source_site !== siteFilter) return false
    }
    if (accountFilter) {
      if (o.sourcing_account_id !== accountFilter) return false
    }
    if (marketStatus) {
      if (o.shipping_status !== marketStatus) return false
    }
    if (statusFilter) {
      if (statusFilter === 'active') {
        if (!['new_order', 'invoice_printed', 'pending', 'preparing', 'wait_ship', 'arrived'].includes(o.status)) return false
        const ss = o.shipping_status || ''
        if (['취소중', '취소요청', '취소완료', '취소처리중', '반품요청', '반품완료', '교환요청', '교환완료'].includes(ss)) return false
      } else if (statusFilter === 'cancel_return_excluded') {
        if (['cancel_requested', 'cancelled', 'return_requested', 'returned', 'exchange_requested', 'exchange_pending', 'exchange_done', 'ship_failed', 'undeliverable'].includes(o.status)) return false
      } else if (statusFilter === 'pending') {
        if (!['pending', 'preparing', 'new_order', 'invoice_printed'].includes(o.status)) return false
      } else if (o.status !== statusFilter) return false
    }
    if (inputFilter) {
      const actionTags = parseActionTags(activeActions[o.id] ?? o.action_tag ?? null)
      switch (inputFilter) {
        case 'has_order': if (!o.sourcing_order_number) return false; break
        case 'no_order': if (o.sourcing_order_number) return false; break
        case 'has_invoice': if (!o.tracking_number) return false; break
        case 'no_invoice': if (o.tracking_number) return false; break
        case 'registered': if (!o.collected_product_id && !o.source_url && !o.product_image) return false; break
        case 'unregistered': if (o.collected_product_id || o.source_url || o.product_image) return false; break
        case 'direct': if (!actionTags.includes('direct')) return false; break
        case 'kkadaegi': if (!actionTags.includes('kkadaegi')) return false; break
        case 'gift': if (!actionTags.includes('gift')) return false; break
        case 'staff_a': if (!actionTags.includes('staff_a')) return false; break
        case 'staff_b': if (!actionTags.includes('staff_b')) return false; break
      }
    }
    if (searchText) {
      const q = searchText.toLowerCase()
      if (searchCategory === 'customer' && !o.customer_name?.toLowerCase().includes(q)) return false
      if (searchCategory === 'product' && !o.product_name?.toLowerCase().includes(q)) return false
      if (searchCategory === 'product_id' && !o.product_id?.toLowerCase().includes(q)) return false
      if (searchCategory === 'order_number' && !o.order_number?.toLowerCase().includes(q)) return false
    }
    return true
  }).sort((a, b) => {
    const getTime = (o: SambaOrder) => o.paid_at ? new Date(o.paid_at).getTime() : new Date(o.created_at).getTime()
    switch (sortBy) {
      case 'date_asc':    return getTime(a) - getTime(b)
      case 'profit_desc': return (b.profit || 0) - (a.profit || 0)
      case 'profit_asc':  return (a.profit || 0) - (b.profit || 0)
      case 'price_desc':  return (b.sale_price || 0) - (a.sale_price || 0)
      case 'price_asc':   return (a.sale_price || 0) - (b.sale_price || 0)
      default:            return getTime(b) - getTime(a)
    }
  }), [orders, customStart, customEnd, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, inputFilter, activeActions, searchText, searchCategory, accounts, sortBy, isProductMode])
}

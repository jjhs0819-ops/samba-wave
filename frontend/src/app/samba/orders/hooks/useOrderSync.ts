'use client'

import { useState, Dispatch, SetStateAction } from 'react'
import { orderApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { fmtNum } from '@/lib/samba/styles'
import { fmtTime } from '@/lib/samba/utils'

interface UseOrderSyncArgs {
  accounts: SambaMarketAccount[]
  period: string
  setLogMessages: Dispatch<SetStateAction<string[]>>
  showNotification: (message: string, type?: string) => void
  loadOrders: () => void | Promise<void>
}

export function useOrderSync({ accounts, period, setLogMessages, showNotification, loadOrders }: UseOrderSyncArgs) {
  const [syncing, setSyncing] = useState(false)
  const [syncAccountId, setSyncAccountId] = useState('')

  const handleFetch = async () => {
    setSyncing(true)
    const ts = () => fmtTime()
    const daysMap: Record<string, number> = {
      yesterday: 1, today: 1, thisweek: 7, lastweek: 14, '5days': 5, '1week': 7, '15days': 15,
      thismonth: 31, lastmonth: 60, '1month': 30, '3months': 90, '6months': 180,
      thisyear: Math.ceil((Date.now() - new Date(new Date().getFullYear(), 0, 1).getTime()) / 86400000) + 1, all: 365,
    }
    const days = daysMap[period] || 7

    // 마켓타입 선택 시 해당 마켓 계정들만 순회 동기화
    if (syncAccountId.startsWith('type:')) {
      const marketType = syncAccountId.replace('type:', '')
      const marketAccs = accounts.filter(a => a.market_type === marketType)
      const marketName = marketAccs[0]?.market_name || marketType
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 전체 계정 주문수집 시작 (${fmtNum(marketAccs.length)}개 계정, 최근 ${days}일)...`])
      let totalSynced = 0
      let totalCancelRequested = 0
      for (const acc of marketAccs) {
        const label = `${acc.market_name}(${acc.seller_id || '-'})`
        try {
          const res = await orderApi.syncFromMarkets(days, acc.id)
          for (const r of res.results) {
            if (r.status === 'success') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${fmtNum(r.fetched)}건 조회, ${fmtNum(r.synced)}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${fmtNum((r as Record<string, unknown>).confirmed as number)}건 발주확인` : ''}`])
            } else if (r.status === 'skip') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
            } else {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
            }
            totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
          }
          totalSynced += res.total_synced
        } catch (e) {
          setLogMessages(prev => [...prev, `[${ts()}] ${label} 오류: ${e}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 주문수집 완료 — 총 ${fmtNum(totalSynced)}건 신규 저장`])
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${fmtNum(totalCancelRequested)}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
      setSyncing(false)
      return
    }

    // 전체마켓: Caddy response_header_timeout(120s) 회피 위해 계정별 개별 호출로 분할
    const isAll = !syncAccountId
    if (isAll) {
      setLogMessages(prev => [...prev, `[${ts()}] 전체마켓 주문수집 시작 (${fmtNum(accounts.length)}개 계정, 최근 ${days}일)...`])
      let totalSynced = 0
      let totalCancelRequested = 0
      for (const acc of accounts) {
        const label = `${acc.market_name}(${acc.seller_id || '-'})`
        try {
          const res = await orderApi.syncFromMarkets(days, acc.id)
          for (const r of res.results) {
            if (r.status === 'success') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${fmtNum(r.fetched)}건 조회, ${fmtNum(r.synced)}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${fmtNum((r as Record<string, unknown>).confirmed as number)}건 발주확인` : ''}`])
            } else if (r.status === 'skip') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
            } else {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
            }
            totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
          }
          totalSynced += res.total_synced
        } catch (e) {
          setLogMessages(prev => [...prev, `[${ts()}] ${label} 오류: ${e}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 전체마켓 주문수집 완료 — 총 ${fmtNum(totalSynced)}건 신규 저장`])
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${fmtNum(totalCancelRequested)}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
      setSyncing(false)
      return
    }

    // 개별 계정 동기화
    const acc = accounts.find(a => a.id === syncAccountId)
    const label = acc ? `${acc.market_name}(${acc.seller_id || '-'})` : syncAccountId
    setLogMessages(prev => [...prev, `[${ts()}] ${label} 주문수집 시작 (최근 ${days}일)...`])
    try {
      const res = await orderApi.syncFromMarkets(days, syncAccountId)
      for (const r of res.results) {
        if (r.status === 'success') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${fmtNum(r.fetched)}건 조회, ${fmtNum(r.synced)}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${fmtNum((r as Record<string, unknown>).confirmed as number)}건 발주확인` : ''}`])
        } else if (r.status === 'skip') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
        } else {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 주문수집 완료 — 총 ${fmtNum(res.total_synced)}건 신규 저장`])
      let totalCancelRequested = 0
      for (const r of res.results) {
        totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
      }
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${fmtNum(totalCancelRequested)}건이 감지되었습니다. 확인이 필요합니다.`)
      }
    } catch (e) {
      setLogMessages(prev => [...prev, `[${ts()}] 오류: ${e}`])
    } finally {
      await loadOrders()
      setSyncing(false)
    }
  }

  return {
    syncing,
    syncAccountId, setSyncAccountId,
    handleFetch,
  }
}

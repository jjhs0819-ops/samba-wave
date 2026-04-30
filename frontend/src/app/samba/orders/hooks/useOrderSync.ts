'use client'

import { useState, Dispatch, SetStateAction } from 'react'
import { orderApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { jobApi } from '@/lib/samba/api/operations'
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
  // 백그라운드 모드: 백엔드 잡 큐로 위임 + 진행률 폴링 (페이지 이탈해도 계속)
  const [backgroundMode, setBackgroundMode] = useState(false)

  const handleFetch = async () => {
    setSyncing(true)
    const ts = () => fmtTime()
    const daysMap: Record<string, number> = {
      yesterday: 1, today: 1, thisweek: 7, lastweek: 14, '5days': 5, '1week': 7, '15days': 15,
      thismonth: 31, lastmonth: 60, '1month': 30, '3months': 90, '6months': 180,
      thisyear: Math.ceil((Date.now() - new Date(new Date().getFullYear(), 0, 1).getTime()) / 86400000) + 1, all: 365,
    }
    const days = daysMap[period] || 7

    // 백그라운드 모드 — 전체마켓에서만 활성화 (개별 계정/마켓타입은 짧아서 불필요)
    if (backgroundMode && !syncAccountId) {
      try {
        const created = await jobApi.create({ job_type: 'order_sync', payload: { days } })
        const jobId = created.id
        const reused = created.duplicate
        setLogMessages(prev => [...prev, `[${ts()}] 백그라운드 잡 ${reused ? '재사용' : '시작'} (${jobId.slice(0, 12)}...)`])
        // 폴링 — 잡 끝날 때까지. 페이지 이탈/새로고침해도 백엔드 잡은 계속 돌아감
        let logSince = 0
        let done = false
        while (!done) {
          await new Promise(r => setTimeout(r, 2000))
          try {
            const logsRes = await jobApi.jobLogs(jobId, logSince)
            if (logsRes.logs && logsRes.logs.length > 0) {
              setLogMessages(prev => [...prev, ...logsRes.logs])
              logSince += logsRes.logs.length
            }
            const job = await jobApi.get(jobId)
            const status = (job as unknown as { status?: string }).status
            if (status === 'completed' || status === 'failed' || status === 'cancelled') {
              setLogMessages(prev => [...prev, `[${ts()}] 잡 ${status === 'completed' ? '완료' : status === 'failed' ? '실패' : '취소'}`])
              done = true
            }
          } catch (e) {
            setLogMessages(prev => [...prev, `[${ts()}] 폴링 오류: ${e}`])
          }
        }
      } catch (e) {
        setLogMessages(prev => [...prev, `[${ts()}] 백그라운드 잡 생성 실패: ${e}`])
      } finally {
        await loadOrders()
        setSyncing(false)
      }
      return
    }

    // 마켓타입 선택 시 해당 마켓 계정들만 병렬 동기화
    if (syncAccountId.startsWith('type:')) {
      const marketType = syncAccountId.replace('type:', '')
      const marketAccs = accounts.filter(a => a.market_type === marketType)
      const marketName = marketAccs[0]?.market_name || marketType
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 전체 계정 주문수집 시작 (${fmtNum(marketAccs.length)}개 계정, 최근 ${days}일)...`])
      const settled = await Promise.allSettled(marketAccs.map(acc => orderApi.syncFromMarkets(days, acc.id)))
      let totalSynced = 0
      let totalCancelRequested = 0
      for (const outcome of settled) {
        if (outcome.status === 'rejected') {
          setLogMessages(prev => [...prev, `[${ts()}] 오류: ${outcome.reason}`])
          continue
        }
        const res = outcome.value
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
      }
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 주문수집 완료 — 총 ${fmtNum(totalSynced)}건 신규 저장`])
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${fmtNum(totalCancelRequested)}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
      setSyncing(false)
      return
    }

    // 전체마켓: 계정별 개별 호출로 분할 + 병렬 실행 (Caddy 120s 타임아웃은 계정 단위 요청이라 문제없음)
    const isAll = !syncAccountId
    if (isAll) {
      setLogMessages(prev => [...prev, `[${ts()}] 전체마켓 주문수집 시작 (${fmtNum(accounts.length)}개 계정, 최근 ${days}일)...`])
      const settled = await Promise.allSettled(accounts.map(acc => orderApi.syncFromMarkets(days, acc.id)))
      let totalSynced = 0
      let totalCancelRequested = 0
      for (const outcome of settled) {
        if (outcome.status === 'rejected') {
          setLogMessages(prev => [...prev, `[${ts()}] 오류: ${outcome.reason}`])
          continue
        }
        const res = outcome.value
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
    backgroundMode, setBackgroundMode,
    handleFetch,
  }
}

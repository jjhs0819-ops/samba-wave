'use client'

import { useEffect, useRef, MutableRefObject, Dispatch, SetStateAction } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'

interface Args {
  collecting: boolean
  brandScanning: boolean
  setCollecting: Dispatch<SetStateAction<boolean>>
  setCollectLog: Dispatch<SetStateAction<string[]>>
  load: () => void | Promise<void>
  logRef: MutableRefObject<HTMLDivElement | null>
  manualCollectRef: MutableRefObject<boolean>
}

export function useCollectLogPolling(args: Args) {
  const { collecting, brandScanning, setCollecting, setCollectLog, load, logRef, manualCollectRef } = args
  const collectLogSinceRef = useRef(0)
  const collectLogPollingRef = useRef(false)

  // 수집 로그 링 버퍼 폴링 (서버 로그 — collecting 또는 brandScanning 시 폴링)
  useEffect(() => {
    if (!collecting && !brandScanning) return
    collectLogPollingRef.current = true
    let checkCount = 0

    const doPoll = async () => {
      if (!collectLogPollingRef.current) return
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-logs?since_idx=${collectLogSinceRef.current}`)
        if (!res.ok) return
        const data = await res.json() as { logs: string[]; current_idx: number }
        if (data.current_idx < collectLogSinceRef.current) {
          collectLogSinceRef.current = 0
          return
        }
        if (data.logs.length > 0) {
          setCollectLog(prev => [...prev, ...data.logs].slice(-30))
          setTimeout(() => {
            if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
          }, 50)
        }
        collectLogSinceRef.current = data.current_idx

        checkCount++
        if (checkCount % 10 === 0 && !manualCollectRef.current) {
          const jRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=running&limit=5`)
          if (jRes.ok) {
            const jobs = await jRes.json() as Array<{ job_type: string; status: string }>
            const stillRunning = jobs.some(j => j.job_type === 'collect')
            if (!stillRunning) {
              const pRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=pending&limit=5`)
              const pJobs = pRes.ok ? await pRes.json() as Array<{ job_type: string }> : []
              const stillPending = pJobs.some(j => j.job_type === 'collect')
              if (!stillPending) {
                setCollecting(false)
                load()
              }
            }
          }
        }
      } catch { /* 네트워크 오류 무시 */ }
    }

    doPoll()
    const timer = setInterval(doPoll, 500)
    return () => { clearInterval(timer); collectLogPollingRef.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collecting, brandScanning])

  // 페이지 로드 시 진행 중인 수집 Job 자동 감지 + 로그 복원
  useEffect(() => {
    const detectRunningCollect = async () => {
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=running&limit=5`)
        if (!res.ok) return
        const jobs = await res.json() as Array<{ job_type: string; status: string }>
        const hasCollect = jobs.some(j => j.job_type === 'collect' && (j.status === 'running' || j.status === 'pending'))
        if (!hasCollect) {
          const pRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs?status=pending&limit=5`)
          if (pRes.ok) {
            const pJobs = await pRes.json() as Array<{ job_type: string; status: string }>
            const hasPending = pJobs.some(j => j.job_type === 'collect')
            if (!hasPending) return
          } else return
        }
        const logRes = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-logs?since_idx=0`)
        if (logRes.ok) {
          const logData = await logRes.json() as { logs: string[]; current_idx: number }
          if (logData.logs.length > 0) {
            setCollectLog(logData.logs.slice(-30))
          }
          collectLogSinceRef.current = logData.current_idx
        }
        setCollecting(true)
      } catch { /* 무시 */ }
    }
    detectRunningCollect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { collectLogSinceRef }
}

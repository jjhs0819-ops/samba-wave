'use client'

import { useEffect, useRef, useState } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'

export interface CollectQueueItem {
  id: string
  filter_name: string
  source_site: string
  started_at: string | null
  current: number
  total: number
}

interface QueueStatus {
  running: CollectQueueItem[]
  pending: CollectQueueItem[]
}

export function useCollectQueuePolling() {
  const [collectQueueStatus, setCollectQueueStatus] = useState<QueueStatus>({ running: [], pending: [] })
  const collectQueuePollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-queue-status`)
        if (res.ok) {
          const data = await res.json() as QueueStatus
          setCollectQueueStatus(data)
        }
      } catch { /* 무시 */ }
    }
    fetchStatus()
    collectQueuePollRef.current = setInterval(fetchStatus, 3000)
    return () => { if (collectQueuePollRef.current) clearInterval(collectQueuePollRef.current) }
  }, [])

  return collectQueueStatus
}

'use client'

import { useEffect, useRef, useState } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'

interface QueueStatus {
  running: Array<{ filter_name: string; source_site: string }>
  pending: Array<{ filter_name: string; source_site: string }>
}

export function useCollectQueuePolling(collecting: boolean) {
  const [collectQueueStatus, setCollectQueueStatus] = useState<QueueStatus>({ running: [], pending: [] })
  const collectQueuePollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!collecting) {
      setCollectQueueStatus({ running: [], pending: [] })
      return
    }
    const fetchStatus = async () => {
      try {
        const res = await fetchWithAuth(`${API_BASE}/api/v1/samba/jobs/collect-queue-status`)
        if (res.ok) {
          const data = await res.json() as QueueStatus
          setCollectQueueStatus(data)
        }
      } catch { /* 무시 */ }
    }
    const delay = setTimeout(() => {
      fetchStatus()
      collectQueuePollRef.current = setInterval(fetchStatus, 5000)
    }, 1000)
    return () => { clearTimeout(delay); if (collectQueuePollRef.current) clearInterval(collectQueuePollRef.current) }
  }, [collecting])

  return collectQueueStatus
}

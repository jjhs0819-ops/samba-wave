'use client'

import { useEffect, useState } from 'react'

import { verifyLicenseKey } from '@/lib/samba/api/license'

const STORAGE_KEY = 'samba_license_key'
const CACHE_KEY = 'samba_license_cache'
const CACHE_TTL_MS = 24 * 60 * 60 * 1000

interface LicenseCache {
  valid: boolean
  checkedAt: number
  expiresAt: string | null
  buyerName: string | null
}

export type LicenseStatus = 'loading' | 'valid' | 'invalid' | 'not_configured'

export function getLicenseKey(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(STORAGE_KEY)
}

export function setLicenseKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key)
  localStorage.removeItem(CACHE_KEY)
}

export function clearLicenseKey(): void {
  localStorage.removeItem(STORAGE_KEY)
  localStorage.removeItem(CACHE_KEY)
}

function getCache(): LicenseCache | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const cache: LicenseCache = JSON.parse(raw)
    if (Date.now() - cache.checkedAt > CACHE_TTL_MS) return null
    return cache
  } catch {
    return null
  }
}

function setCache(data: LicenseCache): void {
  localStorage.setItem(CACHE_KEY, JSON.stringify(data))
}

export function useLicenseCheck() {
  const [status, setStatus] = useState<LicenseStatus>('loading')
  const [message, setMessage] = useState('')

  const check = async (forceRefresh = false) => {
    const key = getLicenseKey()
    if (!key) {
      setStatus('not_configured')
      return
    }
    if (!forceRefresh) {
      const cache = getCache()
      if (cache) {
        setStatus(cache.valid ? 'valid' : 'invalid')
        return
      }
    }
    try {
      const result = await verifyLicenseKey(key)
      setCache({
        valid: result.valid,
        checkedAt: Date.now(),
        expiresAt: result.expires_at,
        buyerName: result.buyer_name,
      })
      setStatus(result.valid ? 'valid' : 'invalid')
      if (!result.valid) setMessage(result.message)
    } catch {
      const cache = getCache()
      setStatus(cache ? (cache.valid ? 'valid' : 'invalid') : 'invalid')
      setMessage('라이선스 서버에 연결할 수 없습니다.')
    }
  }

  useEffect(() => {
    check()
    const timer = setInterval(() => check(true), CACHE_TTL_MS)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { status, message, recheck: () => check(true) }
}

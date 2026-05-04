'use client'

const STORAGE_KEY = 'samba_license_key'

export function getLicenseKey(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(STORAGE_KEY)
}

export function setLicenseKey(key: string): void {
  localStorage.setItem(STORAGE_KEY, key)
}

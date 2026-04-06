'use client'

import { useState, useEffect } from 'react'

/**
 * localStorage에 상태를 자동 저장/복원하는 커스텀 훅
 * SSR 환경에서는 defaultValue를 반환한다.
 */
export function useLocalStorageState<T>(
  key: string,
  defaultValue: T
): [T, (value: T | ((prev: T) => T)) => void] {
  const [state, setState] = useState<T>(() => {
    if (typeof window === 'undefined') return defaultValue
    try {
      const stored = localStorage.getItem(key)
      return stored ? JSON.parse(stored) : defaultValue
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state))
    } catch {
      // localStorage 접근 실패 무시
    }
  }, [key, state])

  return [state, setState]
}

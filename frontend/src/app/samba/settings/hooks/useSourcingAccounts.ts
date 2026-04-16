'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  sourcingAccountApi,
  type SambaSourcingAccount,
  type ChromeProfile,
} from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'

export interface SourcingAccountsState {
  sourcingAccounts: SambaSourcingAccount[]
  sourcingSites: { id: string; name: string; group: string }[]
  chromeProfiles: ChromeProfile[]
  chromeProfilesSyncing: boolean
  sourcingTab: string
  sourcingFormOpen: boolean
  sourcingEditId: string | null
  sourcingForm: {
    site_name: string
    account_label: string
    username: string
    password: string
    chrome_profile: string
    memo: string
  }
  balanceLoading: Record<string, boolean>
  normalizedChromeProfiles: ChromeProfile[]
}

export interface SourcingAccountsActions {
  loadSourcingAccounts: () => Promise<void>
  handleSyncChromeProfiles: () => Promise<void>
  handleSourcingSave: () => Promise<void>
  handleSourcingDelete: (id: string) => Promise<void>
  handleSourcingEdit: (a: SambaSourcingAccount) => void
  handleFetchBalance: (id: string) => Promise<void>
  handleFetchAllBalances: () => Promise<void>
  setSourcingTab: (tab: string) => void
  setSourcingFormOpen: (open: boolean) => void
  setSourcingEditId: (id: string | null) => void
  setSourcingForm: React.Dispatch<React.SetStateAction<SourcingAccountsState['sourcingForm']>>
}

export function useSourcingAccounts(): SourcingAccountsState & SourcingAccountsActions {
  const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
  const [sourcingSites, setSourcingSites] = useState<{ id: string; name: string; group: string }[]>([])
  const [chromeProfiles, setChromeProfiles] = useState<ChromeProfile[]>([])
  const [chromeProfilesSyncing, setChromeProfilesSyncing] = useState(false)
  const [sourcingTab, setSourcingTab] = useState('MUSINSA')
  const [sourcingFormOpen, setSourcingFormOpen] = useState(false)
  const [sourcingEditId, setSourcingEditId] = useState<string | null>(null)
  const [sourcingForm, setSourcingForm] = useState({
    site_name: 'MUSINSA',
    account_label: '',
    username: '',
    password: '',
    chrome_profile: '',
    memo: '',
  })
  const [balanceLoading, setBalanceLoading] = useState<Record<string, boolean>>({})

  // 중복 제거된 크롬 프로필 목록
  const normalizedChromeProfiles = useMemo(() => {
    const seen = new Set<string>()
    return chromeProfiles.filter(profile => {
      const key = (profile.email || profile.directory || '').trim().toLowerCase()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [chromeProfiles])

  // 소싱처 계정 목록 로드
  const loadSourcingAccounts = useCallback(async () => {
    try {
      const [accounts, sites, profiles] = await Promise.all([
        sourcingAccountApi.list(),
        sourcingAccountApi.getSites(),
        sourcingAccountApi.getChromeProfiles(),
      ])
      setSourcingAccounts(accounts)
      setSourcingSites(sites)
      setChromeProfiles(profiles)
    } catch { /* ignore */ }
  }, [])

  // 크롬 프로필 동기화
  const handleSyncChromeProfiles = async () => {
    setChromeProfilesSyncing(true)
    try {
      await sourcingAccountApi.requestChromeProfileSync()

      let profiles: ChromeProfile[] = []
      for (let i = 0; i < 12; i++) {
        await new Promise(resolve => setTimeout(resolve, 2500))
        profiles = await sourcingAccountApi.getChromeProfiles()
        setChromeProfiles(profiles)
        if (profiles.length > 0) break
      }

      if (profiles.length > 0) {
        showAlert(`크롬 프로필 ${profiles.length}개를 동기화했습니다.`, 'success')
      } else {
        showAlert('동기화 요청은 보냈지만 프로필이 아직 없습니다. 확장앱 로그인 상태를 확인하세요.', 'error')
      }
    } catch (err) {
      showAlert(err instanceof Error ? err.message : '크롬 프로필 동기화 실패', 'error')
    }
    setChromeProfilesSyncing(false)
  }

  // 소싱처 계정 저장
  const handleSourcingSave = async () => {
    if (!sourcingForm.account_label || !sourcingForm.username || !sourcingForm.password) {
      showAlert('별칭, 아이디, 비밀번호는 필수입니다', 'error')
      return
    }
    try {
      if (sourcingEditId) {
        await sourcingAccountApi.update(sourcingEditId, sourcingForm)
      } else {
        await sourcingAccountApi.create({ ...sourcingForm, site_name: sourcingTab })
      }
      setSourcingEditId(null)
      setSourcingForm({ site_name: sourcingTab, account_label: '', username: '', password: '', chrome_profile: '', memo: '' })
      loadSourcingAccounts()
    } catch (err) { showAlert(err instanceof Error ? err.message : '저장 실패', 'error') }
  }

  // 소싱처 계정 삭제
  const handleSourcingDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    await sourcingAccountApi.delete(id)
    loadSourcingAccounts()
  }

  // 소싱처 계정 수정 모드
  const handleSourcingEdit = (a: SambaSourcingAccount) => {
    setSourcingEditId(a.id)
    setSourcingForm({
      site_name: a.site_name,
      account_label: a.account_label,
      username: a.username,
      password: a.password,
      chrome_profile: a.chrome_profile || '',
      memo: a.memo || '',
    })
  }

  // 단일 계정 잔액 새로고침
  const handleFetchBalance = async (id: string) => {
    setBalanceLoading(prev => ({ ...prev, [id]: true }))
    try {
      await loadSourcingAccounts()
      showAlert('잔액 갱신 완료 (확장앱에서 수집된 데이터)', 'success')
    } catch (err) { showAlert(err instanceof Error ? err.message : '잔액 조회 실패', 'error') }
    setBalanceLoading(prev => ({ ...prev, [id]: false }))
  }

  // 전체 잔액 새로고침 요청
  const handleFetchAllBalances = async () => {
    try {
      await sourcingAccountApi.requestBalanceCheck()
      showAlert('잔액 체크 요청 완료 — 확장앱이 30초 내 자동 수집합니다', 'success')
      // 15초 후 자동 새로고침
      setTimeout(() => loadSourcingAccounts(), 15000)
    } catch (err) { showAlert(err instanceof Error ? err.message : '잔액 체크 요청 실패', 'error') }
  }

  return {
    sourcingAccounts,
    sourcingSites,
    chromeProfiles,
    chromeProfilesSyncing,
    sourcingTab,
    sourcingFormOpen,
    sourcingEditId,
    sourcingForm,
    balanceLoading,
    normalizedChromeProfiles,
    loadSourcingAccounts,
    handleSyncChromeProfiles,
    handleSourcingSave,
    handleSourcingDelete,
    handleSourcingEdit,
    handleFetchBalance,
    handleFetchAllBalances,
    setSourcingTab,
    setSourcingFormOpen,
    setSourcingEditId,
    setSourcingForm,
  }
}

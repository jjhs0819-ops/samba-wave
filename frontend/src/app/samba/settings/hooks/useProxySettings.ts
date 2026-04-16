'use client'

import { useState, useCallback } from 'react'
import {
  proxyConfigApi,
  type ProxyConfigItem,
  type ProxyPurpose,
} from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { parseProxyUrl, buildProxyUrl } from '../utils/proxy'

export interface ProxySettingsState {
  proxies: ProxyConfigItem[]
  proxyModalOpen: boolean
  proxyEditIdx: number | null
  proxyForm: ProxyConfigItem
  proxyFields: { username: string; password: string; ip: string; port: string }
  proxyTesting: number | null
  proxySaving: boolean
}

export interface ProxySettingsActions {
  loadProxies: () => Promise<void>
  saveProxies: (items: ProxyConfigItem[], silent?: boolean) => Promise<void>
  testProxy: (idx: number) => Promise<void>
  openProxyAdd: () => void
  openProxyEdit: (idx: number) => void
  handleProxySave: () => Promise<void>
  handleProxyDelete: (idx: number) => Promise<void>
  handleProxyToggle: (idx: number) => Promise<void>
  toggleProxyPurpose: (purpose: ProxyConfigItem['purposes'][number]) => void
  setProxyModalOpen: (open: boolean) => void
  setProxyForm: React.Dispatch<React.SetStateAction<ProxyConfigItem>>
  setProxyFields: React.Dispatch<React.SetStateAction<{ username: string; password: string; ip: string; port: string }>>
}

export function useProxySettings(): ProxySettingsState & ProxySettingsActions {
  const [proxies, setProxies] = useState<ProxyConfigItem[]>([])
  const [proxyModalOpen, setProxyModalOpen] = useState(false)
  const [proxyEditIdx, setProxyEditIdx] = useState<number | null>(null)
  const [proxyForm, setProxyForm] = useState<ProxyConfigItem>({ name: '', url: '', purposes: [], enabled: true })
  const [proxyFields, setProxyFields] = useState({ username: '', password: '', ip: '', port: '' })
  const [proxyTesting, setProxyTesting] = useState<number | null>(null)
  const [proxySaving, setProxySaving] = useState(false)

  // 프록시 목록 로드
  const loadProxies = useCallback(async () => {
    try {
      const data = await proxyConfigApi.list()
      if (Array.isArray(data)) setProxies(data)
    } catch { /* ignore */ }
  }, [])

  // 프록시 저장
  const saveProxies = async (items: ProxyConfigItem[], silent?: boolean) => {
    setProxySaving(true)
    try {
      await proxyConfigApi.save(items)
      setProxies(items)
      if (!silent) showAlert('프록시 설정이 저장되었습니다.', 'success')
    } catch {
      if (!silent) showAlert('프록시 저장 실패', 'error')
    }
    setProxySaving(false)
  }

  // 프록시 연결 테스트
  const testProxy = async (idx: number) => {
    const p = proxies[idx]
    if (!p.url) {
      // 메인 IP는 httpbin으로 직접 테스트
      setProxyTesting(idx)
      try {
        const res = await fetch('https://httpbin.org/ip').then(r => r.json())
        showAlert(`메인 IP 확인: ${res.origin}`, 'success')
      } catch { showAlert('메인 IP 테스트 실패', 'error') }
      setProxyTesting(null)
      return
    }
    setProxyTesting(idx)
    try {
      const res = await proxyConfigApi.test(p.url)
      if (res.success) {
        showAlert(`연결 성공 — 외부 IP: ${res.ip}`, 'success')
      } else {
        showAlert(`연결 실패: ${res.message}`, 'error')
      }
    } catch (e) {
      showAlert(`테스트 오류: ${e instanceof Error ? e.message : '오류'}`, 'error')
    }
    setProxyTesting(null)
  }

  // 프록시 추가 모달 열기
  const openProxyAdd = () => {
    setProxyEditIdx(null)
    setProxyForm({ name: '', url: '', purposes: [], enabled: true })
    setProxyFields({ username: '', password: '', ip: '', port: '' })
    setProxyModalOpen(true)
  }

  // 프록시 수정 모달 열기
  const openProxyEdit = (idx: number) => {
    setProxyEditIdx(idx)
    setProxyForm({ ...proxies[idx], purposes: [...proxies[idx].purposes] })
    setProxyFields(parseProxyUrl(proxies[idx].url))
    setProxyModalOpen(true)
  }

  // 프록시 폼 저장
  const handleProxySave = async () => {
    if (!proxyForm.name.trim()) {
      showAlert('이름을 입력하세요.', 'error')
      return
    }
    if (proxyForm.purposes.length === 0) {
      showAlert('용도를 1개 이상 선택하세요.', 'error')
      return
    }
    // 필드에서 URL 조합 (메인 IP는 빈값)
    const assembledUrl = buildProxyUrl(proxyFields)
    const formWithUrl = { ...proxyForm, url: assembledUrl }
    const updated = [...proxies]
    if (proxyEditIdx !== null) {
      updated[proxyEditIdx] = formWithUrl
    } else {
      updated.push(formWithUrl)
    }
    await saveProxies(updated)
    setProxyModalOpen(false)
  }

  // 프록시 삭제
  const handleProxyDelete = async (idx: number) => {
    if (!await showConfirm(`"${proxies[idx].name}" 프록시를 삭제하시겠습니까?`)) return
    const updated = proxies.filter((_, i) => i !== idx)
    await saveProxies(updated)
  }

  // 프록시 활성화 토글
  const handleProxyToggle = async (idx: number) => {
    const updated = [...proxies]
    updated[idx] = { ...updated[idx], enabled: !updated[idx].enabled }
    await saveProxies(updated)
  }

  // 프록시 용도 토글
  const toggleProxyPurpose = (purpose: ProxyPurpose) => {
    setProxyForm(prev => ({
      ...prev,
      purposes: prev.purposes.includes(purpose)
        ? prev.purposes.filter(p => p !== purpose)
        : [...prev.purposes, purpose],
    }))
  }

  return {
    proxies,
    proxyModalOpen,
    proxyEditIdx,
    proxyForm,
    proxyFields,
    proxyTesting,
    proxySaving,
    loadProxies,
    saveProxies,
    testProxy,
    openProxyAdd,
    openProxyEdit,
    handleProxySave,
    handleProxyDelete,
    handleProxyToggle,
    toggleProxyPurpose,
    setProxyModalOpen,
    setProxyForm,
    setProxyFields,
  }
}

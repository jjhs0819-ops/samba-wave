'use client'

import { useState, useCallback, useEffect } from 'react'
import {
  accountApi,
  forbiddenApi,
  proxyApi,
  type SambaMarketAccount,
} from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { STORE_MARKETS, SAFE_SELECT_DEFAULTS } from '../config'

export interface StoreSettingsState {
  accounts: SambaMarketAccount[]
  accountLoading: boolean
  storeTab: string
  visiblePasswords: Set<string>
  storeData: Record<string, Record<string, string>>
  savedStoreData: Record<string, Record<string, string>>
  storeStatus: Record<string, string>
  editingAccountId: string | null
  ssgShippingOptions: { value: string; label: string; divCd: number }[]
  ssgAddrOptions: { value: string; label: string }[]
  esmPlaceOptions: Record<string, { value: string; label: string }[]>
  esmDispatchOptions: Record<string, { value: string; label: string }[]>
  lotteonDeliveryPolicyOptions: { value: string; label: string }[]
  lotteonWarehouseOptions: { departure: { value: string; label: string }[]; return_: { value: string; label: string }[] }
  networkIps: { web: string; local: string }
  networkIpStatus: string
  coupangOutboundList: Array<{ code: string; name: string; address: string }>
  coupangInboundList: Array<{ code: string; name: string; address: string; address_detail: string; zipcode: string; phone: string }>
}

export interface StoreSettingsActions {
  loadAccounts: () => Promise<void>
  loadStoreSettings: () => Promise<void>
  updateStoreField: (marketKey: string, fieldName: string, value: string) => void
  saveStoreSettings: (marketKey: string) => Promise<void>
  testStoreAuth: (marketKey: string) => Promise<void>
  handleAccountToggle: (id: string) => Promise<void>
  handleAccountDelete: (id: string) => Promise<void>
  togglePasswordVisibility: (key: string) => void
  setStoreTab: (tab: string) => void
  setStoreData: React.Dispatch<React.SetStateAction<Record<string, Record<string, string>>>>
  setSsgShippingOptions: React.Dispatch<React.SetStateAction<{ value: string; label: string; divCd: number }[]>>
  setSsgAddrOptions: React.Dispatch<React.SetStateAction<{ value: string; label: string }[]>>
  setEsmPlaceOptions: React.Dispatch<React.SetStateAction<Record<string, { value: string; label: string }[]>>>
  setEsmDispatchOptions: React.Dispatch<React.SetStateAction<Record<string, { value: string; label: string }[]>>>
  setLotteonDeliveryPolicyOptions: React.Dispatch<React.SetStateAction<{ value: string; label: string }[]>>
  setLotteonWarehouseOptions: React.Dispatch<React.SetStateAction<{ departure: { value: string; label: string }[]; return_: { value: string; label: string }[] }>>
  setCoupangOutboundList: React.Dispatch<React.SetStateAction<Array<{ code: string; name: string; address: string }>>>
  setCoupangInboundList: React.Dispatch<React.SetStateAction<Array<{ code: string; name: string; address: string; address_detail: string; zipcode: string; phone: string }>>>
  loadCoupangShippingPlaces: (accountId?: string) => Promise<void>
  setEditingAccountId: (id: string | null) => void
  setVisiblePasswords: React.Dispatch<React.SetStateAction<Set<string>>>
  setNetworkIps: React.Dispatch<React.SetStateAction<{ web: string; local: string }>>
  saveNetworkIps: () => Promise<void>
}

export function useStoreSettings(): StoreSettingsState & StoreSettingsActions {
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [accountLoading, setAccountLoading] = useState(true)
  const [storeTab, setStoreTab] = useState('smartstore')
  const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set())
  const [storeData, setStoreData] = useState<Record<string, Record<string, string>>>({})
  const [savedStoreData, setSavedStoreData] = useState<Record<string, Record<string, string>>>({})
  const [storeStatus, setStoreStatus] = useState<Record<string, string>>({})
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null)
  const [ssgShippingOptions, setSsgShippingOptions] = useState<{ value: string; label: string; divCd: number }[]>([])
  const [ssgAddrOptions, setSsgAddrOptions] = useState<{ value: string; label: string }[]>([])
  const [esmPlaceOptions, setEsmPlaceOptions] = useState<Record<string, { value: string; label: string }[]>>({})
  const [esmDispatchOptions, setEsmDispatchOptions] = useState<Record<string, { value: string; label: string }[]>>({})
  const [lotteonDeliveryPolicyOptions, setLotteonDeliveryPolicyOptions] = useState<{ value: string; label: string }[]>([])
  const [lotteonWarehouseOptions, setLotteonWarehouseOptions] = useState<{ departure: { value: string; label: string }[]; return_: { value: string; label: string }[] }>({ departure: [], return_: [] })
  const [networkIps, setNetworkIps] = useState({ web: '', local: '' })
  const [networkIpStatus, setNetworkIpStatus] = useState('')
  const [coupangOutboundList, setCoupangOutboundList] = useState<Array<{ code: string; name: string; address: string }>>([])
  const [coupangInboundList, setCoupangInboundList] = useState<Array<{ code: string; name: string; address: string; address_detail: string; zipcode: string; phone: string }>>([])

  const loadAccounts = useCallback(async () => {
    setAccountLoading(true)
    try { setAccounts(await accountApi.list()) } catch { /* ignore */ }
    setAccountLoading(false)
  }, [])

  // ※ 과거 버그: savedStoreData만 세팅하고 storeData는 빈 상태였음 → select UI는 첫 옵션이 시각적으로 보이지만 state는 ''라서
  //    저장 시 merge 로직이 select 필드값을 누락해 DB에 합배송 key 자체가 들어가지 않음 → 백엔드가 기본값 "Y"로 등록 (합배송 불가 UI와 불일치)
  //    → storeData도 함께 세팅 + 안전한 기본값이 명시된 select 필드(SAFE_SELECT_DEFAULTS)에 한해 초기값 주입해 일관성 확보
  const loadStoreSettings = useCallback(async () => {
    const loaded: Record<string, Record<string, string>> = {}
    const statuses: Record<string, string> = {}
    for (const market of STORE_MARKETS) {
      try {
        const data = await forbiddenApi.getSetting(`store_${market.key}`).catch(() => null) as Record<string, string> | null
        if (data && Object.keys(data).length > 0) {
          loaded[market.key] = data
          statuses[market.key] = '연결됨'
        }
      } catch { /* ignore */ }
    }
    // 안전한 기본값을 가진 select 필드에만 초기값 주입
    try {
      const network = await forbiddenApi.getSetting('store_network_ips').catch(() => null) as Record<string, string> | null
      setNetworkIps({
        web: String(network?.web || ''),
        local: String(network?.local || ''),
      })
      setNetworkIpStatus(network && (network.web || network.local) ? '저장됨' : '')
    } catch {
      setNetworkIpStatus('')
    }
    const withDefaults: Record<string, Record<string, string>> = {}
    for (const market of STORE_MARKETS) {
      const base = { ...(loaded[market.key] || {}) }
      for (const field of market.fields) {
        if (field.type === 'select' && field.name in SAFE_SELECT_DEFAULTS && !(field.name in base)) {
          base[field.name] = SAFE_SELECT_DEFAULTS[field.name]
        }
      }
      withDefaults[market.key] = base
    }
    setSavedStoreData(withDefaults)
    setStoreData(withDefaults)
    setStoreStatus(statuses)
  }, [])

  const updateStoreField = (marketKey: string, fieldName: string, value: string) => {
    setStoreData(prev => ({
      ...prev,
      [marketKey]: { ...(prev[marketKey] || {}), [fieldName]: value }
    }))
  }

  const saveNetworkIps = async () => {
    try {
      const payload = {
        web: networkIps.web.trim(),
        local: networkIps.local.trim(),
      }
      await forbiddenApi.saveSetting('store_network_ips', payload)
      setNetworkIps(payload)
      setNetworkIpStatus('저장됨')
      showAlert('웹/로컬 IP를 저장했습니다.', 'success')
    } catch {
      setNetworkIpStatus('저장 실패')
      showAlert('웹/로컬 IP 저장 실패', 'error')
    }
  }

  const saveStoreSettings = async (marketKey: string) => {
    try {
      // 기존 저장 데이터와 현재 입력 데이터 병합
      // select 필드에서 ''(설정안함)을 선택한 경우 해당 키 삭제
      const current = storeData[marketKey] || {}
      const marketCfgForMerge = STORE_MARKETS.find(m => m.key === marketKey)
      const selectFields = new Set(
        (marketCfgForMerge?.fields ?? []).filter(f => f.type === 'select').map(f => f.name)
      )
      const clearKeys = Object.entries(current)
        .filter(([k, v]) => v === '' && selectFields.has(k))
        .map(([k]) => k)
      const filtered = Object.fromEntries(Object.entries(current).filter(([, v]) => v !== ''))
      // 완전 분리: savedStoreData(Settings 공통) 병합 제거 — account.additional_fields 기반으로만 저장
      const merged = { ...filtered }
      // select "설정안함" 선택 시 해당 키 삭제
      for (const k of clearKeys) delete merged[k]
      const data = merged
      await forbiddenApi.saveSetting(`store_${marketKey}`, data)
      const marketCfg = STORE_MARKETS.find(m => m.key === marketKey)
      const label = marketCfg?.label || marketKey

      // 계정 자동 생성/업데이트
      const sellerId = data.storeId || data.account || data.email || data.userId || data.vendorId || data.apiKey || ''
      const businessName = data.businessName || ''
      if (sellerId || businessName) {
        // API 인증정보를 additional_fields에 저장 (계정별 독립 인증)
        // businessName, storeId, maxCount은 additional_fields에서 제외
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { businessName: _bn, storeId: _si, maxCount: _mc, ...apiFields } = data
        const accountData: Partial<SambaMarketAccount> = {
          market_type: marketKey,
          market_name: label,
          account_label: `${businessName}${sellerId ? '-' + (sellerId.length > 16 ? sellerId.slice(0, 8) + '...' : sellerId) : ''}`.replace(/^-|-$/g, '') || marketKey,
          seller_id: sellerId,
          business_name: businessName,
          is_active: true,
          additional_fields: apiFields, // clientId, clientSecret 등 API 인증정보
        }

        if (editingAccountId) {
          // 수정 모드: 해당 계정 업데이트
          await accountApi.update(editingAccountId, accountData)
          setEditingAccountId(null)
        } else {
          // 신규: 동일 seller_id 계정이 있으면 업데이트, 없으면 생성
          const existing = accounts.find(a => a.market_type === marketKey && a.seller_id === sellerId)
          if (existing) {
            await accountApi.update(existing.id, accountData)
          } else {
            await accountApi.create(accountData)
          }
        }
        await loadAccounts()
      }
      // 저장 후 savedStoreData 갱신 + 폼에 저장된 값 유지
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
      setStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
      setStoreStatus(prev => ({ ...prev, [marketKey]: '연결됨' }))
      setEditingAccountId(null)

      showAlert(`${label} 설정이 저장되었습니다.`, 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  const testStoreAuth = async (marketKey: string) => {
    const data = storeData[marketKey] || {}
    const hasKey = Object.values(data).some(v => v && v.length > 0)
    if (!hasKey) {
      setStoreStatus(prev => ({ ...prev, [marketKey]: '필드를 입력해주세요' }))
      return
    }
    setStoreStatus(prev => ({ ...prev, [marketKey]: '인증 확인 중...' }))
    try {
      // password 필드가 비어있으면 editingAccount.additional_fields에서 복원 (완전 분리)
      const marketCfg = STORE_MARKETS.find(m => m.key === marketKey)
      const pwdFields = new Set(
        (marketCfg?.fields ?? []).filter(f => f.type === 'password').map(f => f.name)
      )
      const safeData = { ...data }
      for (const field of pwdFields) {
        if (!safeData[field] || safeData[field]?.startsWith('****')) {
          const editingAcc = accounts.find(a => a.id === editingAccountId)
          const origVal = (editingAcc?.additional_fields as Record<string, string> | null)?.[field]
          if (origVal) safeData[field] = origVal
        }
      }
      // 먼저 설정 저장
      await forbiddenApi.saveSetting(`store_${marketKey}`, safeData)
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...safeData } }))
      // 마켓별 인증 테스트
      let result: { success: boolean; message: string }
      if (marketKey === 'smartstore') {
        result = await proxyApi.smartstoreAuthTest()
      } else if (marketKey === '11st') {
        result = await proxyApi.elevenstAuthTest()
      } else if (marketKey === 'coupang') {
        result = await proxyApi.coupangAuthTest()
      } else if (marketKey === 'lotteon') {
        const lotteonResult = await proxyApi.lotteonAuthTest()
        result = lotteonResult
        // 인증 성공 시 배송비정책/출고지/회수지 목록 자동 로드
        if (lotteonResult.success) {
          const [polRes, whRes] = await Promise.all([
            proxyApi.lotteonDeliveryPolicies(),
            proxyApi.lotteonWarehouses(),
          ])
          if (polRes.success) setLotteonDeliveryPolicyOptions(polRes.policies)
          if (whRes.success) setLotteonWarehouseOptions({ departure: whRes.departure, return_: whRes.return_ })
        }
      } else if (marketKey === 'ssg') {
        result = await proxyApi.ssgAuthTest()
      } else if (marketKey === 'gsshop') {
        result = await proxyApi.gsshopAuthTest()
      } else {
        result = await proxyApi.marketAuthTest(marketKey)
      }
      if (result.success) {
        setStoreStatus(prev => ({ ...prev, [marketKey]: `✓ ${result.message}` }))
        showAlert(result.message, 'success')
      } else {
        setStoreStatus(prev => ({ ...prev, [marketKey]: `✗ ${result.message}` }))
        showAlert(result.message, 'error')
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '알 수 없는 오류'
      const displayMsg = msg === 'Failed to fetch'
        ? '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.'
        : `인증 테스트 실패: ${msg}`
      setStoreStatus(prev => ({ ...prev, [marketKey]: '연결 실패' }))
      showAlert(displayMsg, 'error')
    }
  }

  // 쿠팡 출고지/반품지 목록 조회
  const loadCoupangShippingPlaces = useCallback(async (accountId?: string) => {
    try {
      // 인증정보 먼저 저장
      await saveStoreSettings('coupang')
      const res = await proxyApi.coupangShippingPlaces(accountId)
      if (res.success && res.data) {
        setCoupangOutboundList(res.data.outboundList || [])
        setCoupangInboundList(res.data.inboundList || [])
        showAlert('출고지/반품지 목록을 가져왔습니다.', 'success')
      } else {
        showAlert(res.message || '출고지/반품지 조회 실패', 'error')
      }
    } catch {
      showAlert('출고지/반품지 조회 실패', 'error')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveStoreSettings])

  // SSG 탭 진입 시 배송비/주소 옵션 자동 로드
  useEffect(() => {
    if (storeTab !== 'ssg') return
    if (ssgShippingOptions.length > 0 || ssgAddrOptions.length > 0) return
    const ssgData = savedStoreData['ssg'] || storeData['ssg'] || {}
    if (!ssgData.apiKey) return
    proxyApi.ssgShippingPolicies().then(res => {
      if (!res.success || !res.policies?.length) return
      const opts = res.policies.map((p: { shppcstId: string; feeAmt: number; prpayCodDivNm: string; shppcstAplUnitNm: string; divCd: number }) => {
        const fee = p.feeAmt ? `${fmtNum(Number(p.feeAmt))}원` : '무료'
        const parts = [p.shppcstId, fee]
        if (p.prpayCodDivNm) parts.push(p.prpayCodDivNm)
        if (p.shppcstAplUnitNm) parts.push(p.shppcstAplUnitNm)
        return { value: p.shppcstId, label: parts.join(' / '), divCd: p.divCd }
      })
      setSsgShippingOptions(opts)
    }).catch(() => {})
    proxyApi.ssgAddresses().then(res => {
      if (!res.success || !res.addresses?.length) return
      setSsgAddrOptions(res.addresses.map((a: { grpAddrId: string; doroAddrId?: string; addrNm: string; bascAddr: string }) => ({
        value: a.doroAddrId || a.grpAddrId,
        label: `${a.addrNm}${a.bascAddr ? ` (${a.bascAddr})` : ''}`,
      })))
    }).catch(() => {})
  }, [storeTab, savedStoreData, storeData, ssgShippingOptions.length, ssgAddrOptions.length])

  // 롯데ON 탭 진입 시 배송비정책/출고지/회수지 자동 로드
  useEffect(() => {
    if (storeTab !== 'lotteon') return
    if (lotteonDeliveryPolicyOptions.length > 0 || lotteonWarehouseOptions.departure.length > 0) return
    const d = savedStoreData['lotteon'] || storeData['lotteon'] || {}
    if (!d.apiKey) return
    Promise.all([proxyApi.lotteonDeliveryPolicies(), proxyApi.lotteonWarehouses()])
      .then(([polRes, whRes]) => {
        if (polRes.success) setLotteonDeliveryPolicyOptions(polRes.policies)
        if (whRes.success) setLotteonWarehouseOptions({ departure: whRes.departure, return_: whRes.return_ })
      }).catch(() => {})
  }, [storeTab, savedStoreData, storeData, lotteonDeliveryPolicyOptions.length, lotteonWarehouseOptions.departure.length])

  const handleAccountToggle = async (id: string) => { await accountApi.toggle(id); loadAccounts() }
  const handleAccountDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    await accountApi.delete(id); loadAccounts()
  }

  const togglePasswordVisibility = (key: string) => {
    setVisiblePasswords(prev => {
      const n = new Set(prev)
      if (n.has(key)) { n.delete(key) } else { n.add(key) }
      return n
    })
  }

  return {
    accounts,
    accountLoading,
    storeTab,
    visiblePasswords,
    storeData,
    savedStoreData,
    storeStatus,
    editingAccountId,
    ssgShippingOptions,
    ssgAddrOptions,
    esmPlaceOptions,
    esmDispatchOptions,
    lotteonDeliveryPolicyOptions,
    lotteonWarehouseOptions,
    networkIps,
    networkIpStatus,
    coupangOutboundList,
    coupangInboundList,
    loadAccounts,
    loadStoreSettings,
    updateStoreField,
    saveNetworkIps,
    saveStoreSettings,
    testStoreAuth,
    handleAccountToggle,
    handleAccountDelete,
    togglePasswordVisibility,
    setStoreTab,
    setStoreData,
    setSsgShippingOptions,
    setSsgAddrOptions,
    setEsmPlaceOptions,
    setEsmDispatchOptions,
    setLotteonDeliveryPolicyOptions,
    setLotteonWarehouseOptions,
    setCoupangOutboundList,
    setCoupangInboundList,
    loadCoupangShippingPlaces,
    setEditingAccountId,
    setVisiblePasswords,
    setNetworkIps,
  }
}

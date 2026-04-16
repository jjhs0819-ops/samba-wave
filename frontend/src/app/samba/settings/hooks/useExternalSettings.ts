'use client'

import { useState, useCallback, useEffect } from 'react'
import {
  forbiddenApi,
  proxyApi,
  collectorApi,
} from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'
import {
  EXCHANGE_CURRENCY_ORDER,
  EMPTY_EXCHANGE_RATES,
  getExchangeDisplayMultiplier,
  type ExchangeCurrencyCode,
  type ExchangeRateResponse,
} from '../config'
import { parseNum } from '@/lib/samba/styles'

export interface ExternalSettingsState {
  // SMS
  smsUserId: string
  smsApiKey: string
  smsSender: string
  smsStatus: string
  // 카카오 알림톡
  kakaoUserId: string
  kakaoApiKey: string
  kakaoSenderKey: string
  kakaoSender: string
  kakaoStatus: string
  // Claude AI
  claudeApiKey: string
  claudeModel: string
  claudeStatus: string
  aiFeatures: Record<string, boolean>
  // Gemini AI
  geminiApiKey: string
  geminiModel: string
  geminiStatus: string
  // Cloudflare R2
  r2AccountId: string
  r2AccessKey: string
  r2SecretKey: string
  r2BucketName: string
  r2PublicUrl: string
  r2Status: string
  // 모델 프리셋
  presets: { key: string; label: string; desc: string; image: string | null }[]
  editingPreset: string | null
  editingDesc: string
  editingLabel: string
  regenerating: string | null
  presetZoom: string | null
  // 금지어/삭제어
  forbiddenText: string
  deletionText: string
  initialForbiddenText: string
  initialDeletionText: string
  optionDeletionText: string
  initialOptionDeletionText: string
  wordsSaving: boolean
  // 태그 금지어
  tagBanned: { rejected: string[]; brands: string[]; source_sites: string[] }
  // 환율
  exchangeRates: ExchangeRateResponse
  exchangeStatus: string
  exchangeSaving: boolean
  // Probe
  probeData: Record<string, Record<string, Record<string, unknown>>>
  probeLoading: boolean
}

export interface ExternalSettingsActions {
  loadExternalSettings: () => Promise<void>
  loadExchangeRates: (forceRefresh?: boolean) => Promise<void>
  saveExchangeSettings: () => Promise<void>
  updateExchangeField: (code: ExchangeCurrencyCode, field: 'adjustment' | 'fixedRate', value: string) => void
  saveSmsSettings: () => Promise<void>
  testSmsKey: () => Promise<void>
  saveKakaoSettings: () => Promise<void>
  testKakaoKey: () => Promise<void>
  saveClaudeSettings: () => Promise<void>
  testClaudeApi: () => Promise<void>
  toggleAiFeature: (key: string) => void
  testGeminiApi: () => Promise<void>
  saveGeminiSettings: () => Promise<void>
  loadPresets: () => Promise<void>
  handleSavePreset: (key: string, label: string, desc: string) => Promise<void>
  handleRegeneratePreset: (key: string, desc?: string, label?: string) => Promise<void>
  saveR2Settings: () => Promise<void>
  testR2: () => Promise<void>
  loadProbeStatus: () => Promise<void>
  runProbe: () => Promise<void>
  setSmsUserId: (v: string) => void
  setSmsApiKey: (v: string) => void
  setSmsSender: (v: string) => void
  setKakaoUserId: (v: string) => void
  setKakaoApiKey: (v: string) => void
  setKakaoSenderKey: (v: string) => void
  setKakaoSender: (v: string) => void
  setClaudeApiKey: (v: string) => void
  setClaudeModel: (v: string) => void
  setGeminiApiKey: (v: string) => void
  setGeminiModel: (v: string) => void
  setR2AccountId: (v: string) => void
  setR2AccessKey: (v: string) => void
  setR2SecretKey: (v: string) => void
  setR2BucketName: (v: string) => void
  setR2PublicUrl: (v: string) => void
  setEditingPreset: (key: string | null) => void
  setEditingDesc: (v: string) => void
  setEditingLabel: (v: string) => void
  setRegenerating: (key: string | null) => void
  setPresetZoom: (url: string | null) => void
  setForbiddenText: (v: string) => void
  setDeletionText: (v: string) => void
  setOptionDeletionText: (v: string) => void
  setTagBanned: React.Dispatch<React.SetStateAction<ExternalSettingsState['tagBanned']>>
  setWordsSaving: (v: boolean) => void
  setInitialForbiddenText: (v: string) => void
  setInitialDeletionText: (v: string) => void
  setInitialOptionDeletionText: (v: string) => void
}

export function useExternalSettings(): ExternalSettingsState & ExternalSettingsActions {
  // SMS
  const [smsUserId, setSmsUserId] = useState('')
  const [smsApiKey, setSmsApiKey] = useState('')
  const [smsSender, setSmsSender] = useState('')
  const [smsStatus, setSmsStatus] = useState('')
  // 카카오 알림톡
  const [kakaoUserId, setKakaoUserId] = useState('')
  const [kakaoApiKey, setKakaoApiKey] = useState('')
  const [kakaoSenderKey, setKakaoSenderKey] = useState('')
  const [kakaoSender, setKakaoSender] = useState('')
  const [kakaoStatus, setKakaoStatus] = useState('')
  // Claude AI
  const [claudeApiKey, setClaudeApiKey] = useState('')
  const [claudeModel, setClaudeModel] = useState('claude-sonnet-4-6')
  const [claudeStatus, setClaudeStatus] = useState('')
  const [aiFeatures, setAiFeatures] = useState<Record<string, boolean>>({ productName: true })
  // Gemini AI
  const [geminiApiKey, setGeminiApiKey] = useState('')
  const [geminiModel, setGeminiModel] = useState('gemini-2.5-flash')
  const [geminiStatus, setGeminiStatus] = useState('')
  // Cloudflare R2
  const [r2AccountId, setR2AccountId] = useState('')
  const [r2AccessKey, setR2AccessKey] = useState('')
  const [r2SecretKey, setR2SecretKey] = useState('')
  const [r2BucketName, setR2BucketName] = useState('')
  const [r2PublicUrl, setR2PublicUrl] = useState('')
  const [r2Status, setR2Status] = useState('')
  // 모델 프리셋
  const [presets, setPresets] = useState<{ key: string; label: string; desc: string; image: string | null }[]>([])
  const [editingPreset, setEditingPreset] = useState<string | null>(null)
  const [editingDesc, setEditingDesc] = useState('')
  const [editingLabel, setEditingLabel] = useState('')
  const [regenerating, setRegenerating] = useState<string | null>(null)
  const [presetZoom, setPresetZoom] = useState<string | null>(null)
  // 금지어/삭제어
  const [forbiddenText, setForbiddenText] = useState('')
  const [deletionText, setDeletionText] = useState('')
  const [initialForbiddenText, setInitialForbiddenText] = useState('')
  const [initialDeletionText, setInitialDeletionText] = useState('')
  const [optionDeletionText, setOptionDeletionText] = useState('')
  const [initialOptionDeletionText, setInitialOptionDeletionText] = useState('')
  const [wordsSaving, setWordsSaving] = useState(false)
  // 태그 금지어
  const [tagBanned, setTagBanned] = useState<{ rejected: string[]; brands: string[]; source_sites: string[] }>({ rejected: [], brands: [], source_sites: [] })
  // 환율
  const [exchangeRates, setExchangeRates] = useState<ExchangeRateResponse>(EMPTY_EXCHANGE_RATES)
  const [exchangeStatus, setExchangeStatus] = useState('')
  const [exchangeSaving, setExchangeSaving] = useState(false)
  // Probe
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // 환율 로드
  const loadExchangeRates = useCallback(async (forceRefresh = false) => {
    try {
      const data = await forbiddenApi.getExchangeRates(forceRefresh)
      setExchangeRates(data as ExchangeRateResponse)
      if (forceRefresh) setExchangeStatus('최신 환율을 불러왔습니다.')
    } catch {
      setExchangeRates(prev => prev || EMPTY_EXCHANGE_RATES)
      setExchangeStatus('환율 정보를 불러오지 못했습니다. 저장된 고정/조정 환율만 입력할 수 있습니다.')
      if (forceRefresh) showAlert('환율 정보를 불러오지 못했습니다.', 'error')
    }
  }, [])

  // 환율 필드 업데이트
  const updateExchangeField = (
    code: ExchangeCurrencyCode,
    field: 'adjustment' | 'fixedRate',
    value: string,
  ) => {
    setExchangeRates(prev => {
      const multiplier = getExchangeDisplayMultiplier(code)
      const numericValue = (parseNum(value) || 0) / multiplier
      const current = prev.currencies[code]
      const nextAdjustment = field === 'adjustment' ? numericValue : current.adjustment
      const nextFixedRate = field === 'fixedRate' ? numericValue : current.fixedRate
      const useFixed = nextFixedRate > 0
      return {
        ...prev,
        currencies: {
          ...prev.currencies,
          [code]: {
            ...current,
            [field]: numericValue,
            adjustment: nextAdjustment,
            fixedRate: nextFixedRate,
            effectiveRate: useFixed
              ? nextFixedRate
              : Math.max(current.baseRate + nextAdjustment, 0),
            useFixed,
          },
        },
      }
    })
  }

  // 환율 저장
  const saveExchangeSettings = async () => {
    setExchangeSaving(true)
    try {
      const payload = {
        currencies: Object.fromEntries(
          EXCHANGE_CURRENCY_ORDER.map((code) => [
            code,
            {
              adjustment: exchangeRates.currencies[code].adjustment || 0,
              fixedRate: exchangeRates.currencies[code].fixedRate || 0,
            },
          ]),
        ),
      }
      await forbiddenApi.saveSetting('exchange_rates', payload)
      setExchangeStatus('환율 설정이 저장되었습니다.')
      await loadExchangeRates(true)
      showAlert('환율 설정이 저장되었습니다.', 'success')
    } catch {
      setExchangeStatus('환율 설정 저장에 실패했습니다.')
      showAlert('환율 설정 저장에 실패했습니다.', 'error')
    } finally {
      setExchangeSaving(false)
    }
  }

  // 외부 설정 로드 (SMS/카카오/Claude/Gemini/R2)
  const loadExternalSettings = useCallback(async () => {
    try {
      const sms = await forbiddenApi.getSetting('aligo_sms').catch(() => null) as Record<string, string> | null
      if (sms) {
        setSmsUserId(sms.userId || '')
        setSmsApiKey(sms.apiKey || '')
        setSmsSender(sms.sender || '')
        if (sms.apiKey) setSmsStatus('저장됨')
      }
    } catch { /* ignore */ }
    try {
      const kakao = await forbiddenApi.getSetting('aligo_kakao').catch(() => null) as Record<string, string> | null
      if (kakao) {
        setKakaoUserId(kakao.userId || '')
        setKakaoApiKey(kakao.apiKey || '')
        setKakaoSenderKey(kakao.senderKey || '')
        setKakaoSender(kakao.sender || '')
        if (kakao.apiKey) setKakaoStatus('저장됨')
      }
    } catch { /* ignore */ }
    try {
      const claude = await forbiddenApi.getSetting('claude').catch(() => null) as Record<string, unknown> | null
      if (claude) {
        setClaudeApiKey(String(claude.apiKey || ''))
        setClaudeModel(String(claude.model || 'claude-sonnet-4-6'))
        if (claude.apiKey) setClaudeStatus('저장됨')
        if (claude.aiFeatures && typeof claude.aiFeatures === 'object') {
          setAiFeatures(claude.aiFeatures as Record<string, boolean>)
        }
      }
    } catch { /* ignore */ }
    try {
      const gm = await forbiddenApi.getSetting('gemini').catch(() => null) as Record<string, unknown> | null
      if (gm) {
        setGeminiApiKey(String(gm.apiKey || ''))
        setGeminiModel(String(gm.model || 'gemini-2.5-flash'))
        if (gm.apiKey) setGeminiStatus('저장됨')
      }
    } catch { /* ignore */ }
    try {
      const r2 = await forbiddenApi.getSetting('cloudflare_r2').catch(() => null) as Record<string, unknown> | null
      if (r2) {
        setR2AccountId(String(r2.accountId || ''))
        setR2AccessKey(String(r2.accessKey || ''))
        setR2SecretKey(String(r2.secretKey || ''))
        setR2BucketName(String(r2.bucketName || ''))
        setR2PublicUrl(String(r2.publicUrl || ''))
        if (r2.accessKey) setR2Status('저장됨')
      }
    } catch { /* ignore */ }
  }, [])

  // SMS 설정 저장
  const saveSmsSettings = async () => {
    try {
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      setSmsStatus('저장됨')
      showAlert('SMS 설정이 저장되었습니다.', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // SMS 테스트
  const testSmsKey = async () => {
    if (!smsUserId || !smsApiKey) {
      showAlert('Identifier와 API Key를 먼저 입력하세요.', 'error')
      return
    }
    setSmsStatus('확인 중...')
    try {
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      const result = await proxyApi.aligoRemain()
      if (result.success) {
        setSmsStatus(`인증 완료 (SMS: ${result.SMS_CNT}건, LMS: ${result.LMS_CNT}건, MMS: ${result.MMS_CNT}건)`)
        showAlert(`인증 완료 — SMS: ${result.SMS_CNT}건, LMS: ${result.LMS_CNT}건, MMS: ${result.MMS_CNT}건`, 'success')
      } else {
        setSmsStatus('인증 실패')
        showAlert(result.message || '알리고 API 인증 실패', 'error')
      }
    } catch (e) {
      setSmsStatus('연결 실패')
      showAlert(`알리고 API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // 카카오 알림톡 저장
  const saveKakaoSettings = async () => {
    try {
      await forbiddenApi.saveSetting('aligo_kakao', { userId: kakaoUserId, apiKey: kakaoApiKey, senderKey: kakaoSenderKey, sender: kakaoSender })
      setKakaoStatus('저장됨')
      showAlert('카카오 알림톡 설정이 저장되었습니다.', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // 카카오 테스트
  const testKakaoKey = async () => {
    if (!kakaoUserId || !kakaoApiKey) {
      showAlert('Identifier와 API Key를 먼저 입력하세요.', 'error')
      return
    }
    setKakaoStatus('확인 중...')
    if (kakaoApiKey.length > 5) {
      setKakaoStatus('Key 형식 유효')
      showAlert('API Key 형식이 유효합니다. 실제 연결은 알림톡 발송 시 확인됩니다.', 'success')
    } else {
      setKakaoStatus('Key 형식 오류')
      showAlert('API Key가 너무 짧습니다.', 'error')
    }
  }

  // Claude API 저장
  const saveClaudeSettings = async () => {
    if (!claudeApiKey) {
      showAlert('API Key를 입력해주세요', 'error')
      return
    }
    try {
      await forbiddenApi.saveSetting('claude', { apiKey: claudeApiKey, model: claudeModel, aiFeatures, updatedAt: new Date().toISOString() })
      setClaudeStatus(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Claude API 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // Claude API 테스트
  const testClaudeApi = async () => {
    if (!claudeApiKey) {
      showAlert('API Key를 먼저 입력해주세요', 'error')
      return
    }
    if (!claudeApiKey.startsWith('sk-ant-')) {
      setClaudeStatus('유효하지 않은 API Key 형식 (sk-ant- 로 시작해야 합니다)')
      return
    }
    setClaudeStatus('API 연결 확인 중...')
    try {
      await forbiddenApi.saveSetting('claude', { apiKey: claudeApiKey, model: claudeModel, aiFeatures, updatedAt: new Date().toISOString() })
      const result = await proxyApi.claudeTest()
      if (result.success) {
        setClaudeStatus(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setClaudeStatus(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setClaudeStatus('연결 실패')
      showAlert(`Claude API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // AI 기능 토글
  const toggleAiFeature = (key: string) => {
    setAiFeatures(prev => ({ ...prev, [key]: !prev[key] }))
  }

  // Gemini API 테스트
  const testGeminiApi = async () => {
    if (!geminiApiKey) { showAlert('API Key를 먼저 입력해주세요', 'error'); return }
    setGeminiStatus('API 연결 확인 중...')
    try {
      await forbiddenApi.saveSetting('gemini', { apiKey: geminiApiKey, model: geminiModel, updatedAt: new Date().toISOString() })
      const result = await proxyApi.geminiTest()
      if (result.success) {
        setGeminiStatus(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setGeminiStatus(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setGeminiStatus('연결 실패')
      showAlert(`Gemini API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // Gemini AI 저장
  const saveGeminiSettings = async () => {
    if (!geminiApiKey) { showAlert('API Key를 입력해주세요', 'error'); return }
    try {
      await forbiddenApi.saveSetting('gemini', { apiKey: geminiApiKey, model: geminiModel, updatedAt: new Date().toISOString() })
      setGeminiStatus(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Gemini 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // 프리셋 로드
  const loadPresets = useCallback(async () => {
    try {
      const res = await proxyApi.listPresets()
      if (res.success) setPresets(res.presets)
    } catch { /* ignore */ }
  }, [])

  // 프리셋 텍스트만 저장
  const handleSavePreset = async (key: string, label: string, desc: string) => {
    try {
      const res = await proxyApi.regeneratePreset(key, desc, label, true)
      if (res.success) {
        showAlert('프리셋 저장 완료', 'success')
        setEditingPreset(null)
        await loadPresets()
      } else showAlert(res.message, 'error')
    } catch (e) {
      showAlert(`저장 실패: ${e instanceof Error ? e.message : ''}`, 'error')
    }
  }

  // 프리셋 재생성
  const handleRegeneratePreset = async (key: string, desc?: string, label?: string) => {
    setRegenerating(key)
    try {
      const res = await proxyApi.regeneratePreset(key, desc, label)
      if (res.success) {
        showAlert(res.message, 'success')
        setEditingPreset(null)
        await loadPresets()
      } else showAlert(res.message, 'error')
    } catch (e) {
      showAlert(`재생성 실패: ${e instanceof Error ? e.message : ''}`, 'error')
    } finally { setRegenerating(null) }
  }

  // Cloudflare R2 저장
  const saveR2Settings = async () => {
    try {
      await forbiddenApi.saveSetting('cloudflare_r2', {
        accountId: r2AccountId, accessKey: r2AccessKey, secretKey: r2SecretKey,
        bucketName: r2BucketName, publicUrl: r2PublicUrl, updatedAt: new Date().toISOString(),
      })
      setR2Status(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Cloudflare R2 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // Cloudflare R2 테스트
  const testR2 = async () => {
    if (!r2AccessKey || !r2SecretKey || !r2BucketName) {
      showAlert('Access Key, Secret Key, Bucket Name을 입력해주세요', 'error')
      return
    }
    setR2Status('연결 확인 중...')
    try {
      await forbiddenApi.saveSetting('cloudflare_r2', {
        accountId: r2AccountId, accessKey: r2AccessKey, secretKey: r2SecretKey,
        bucketName: r2BucketName, publicUrl: r2PublicUrl, updatedAt: new Date().toISOString(),
      })
      const result = await proxyApi.r2Test()
      if (result.success) {
        setR2Status(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setR2Status(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setR2Status('연결 실패')
      showAlert(`R2 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // Probe 상태 로드
  const loadProbeStatus = useCallback(async () => {
    try {
      const data = await collectorApi.probeStatus() as Record<string, Record<string, Record<string, unknown>>>
      if (data) setProbeData(data)
    } catch { /* ignore */ }
  }, [])

  // Probe 헬스체크 실행
  const runProbe = async () => {
    setProbeLoading(true)
    try {
      const data = await collectorApi.probeRun() as Record<string, Record<string, Record<string, unknown>>>
      if (data) setProbeData(data)
      showAlert('헬스체크 완료', 'success')
    } catch (e) {
      showAlert(`헬스체크 실패: ${e instanceof Error ? e.message : '오류'}`, 'error')
    }
    setProbeLoading(false)
  }

  // 금지어/삭제어 + 태그 금지어 초기 로드
  useEffect(() => {
    forbiddenApi.listWords().then((words: { id: string; word: string; type: string }[]) => {
      const dedupe = (arr: string[]) => [...new Set(arr.map(w => w.trim()).filter(Boolean))]
      const ft = dedupe(words.filter(w => w.type === 'forbidden').map(w => w.word)).join('; ')
      const dt = dedupe(words.filter(w => w.type === 'deletion').map(w => w.word)).join('; ')
      const ot = dedupe(words.filter(w => w.type === 'option_deletion').map(w => w.word)).join('; ')
      setForbiddenText(ft)
      setDeletionText(dt)
      setOptionDeletionText(ot)
      setInitialForbiddenText(ft)
      setInitialDeletionText(dt)
      setInitialOptionDeletionText(ot)
    }).catch(() => {})
    forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})
  }, [])

  // 프리셋 초기 로드
  useEffect(() => { loadPresets() }, [loadPresets])

  return {
    smsUserId, smsApiKey, smsSender, smsStatus,
    kakaoUserId, kakaoApiKey, kakaoSenderKey, kakaoSender, kakaoStatus,
    claudeApiKey, claudeModel, claudeStatus, aiFeatures,
    geminiApiKey, geminiModel, geminiStatus,
    r2AccountId, r2AccessKey, r2SecretKey, r2BucketName, r2PublicUrl, r2Status,
    presets, editingPreset, editingDesc, editingLabel, regenerating, presetZoom,
    forbiddenText, deletionText, initialForbiddenText, initialDeletionText,
    optionDeletionText, initialOptionDeletionText, wordsSaving,
    tagBanned,
    exchangeRates, exchangeStatus, exchangeSaving,
    probeData, probeLoading,
    loadExternalSettings,
    loadExchangeRates,
    saveExchangeSettings,
    updateExchangeField,
    saveSmsSettings,
    testSmsKey,
    saveKakaoSettings,
    testKakaoKey,
    saveClaudeSettings,
    testClaudeApi,
    toggleAiFeature,
    testGeminiApi,
    saveGeminiSettings,
    loadPresets,
    handleSavePreset,
    handleRegeneratePreset,
    saveR2Settings,
    testR2,
    loadProbeStatus,
    runProbe,
    setSmsUserId,
    setSmsApiKey,
    setSmsSender,
    setKakaoUserId,
    setKakaoApiKey,
    setKakaoSenderKey,
    setKakaoSender,
    setClaudeApiKey,
    setClaudeModel,
    setGeminiApiKey,
    setGeminiModel,
    setR2AccountId,
    setR2AccessKey,
    setR2SecretKey,
    setR2BucketName,
    setR2PublicUrl,
    setEditingPreset,
    setEditingDesc,
    setEditingLabel,
    setRegenerating,
    setPresetZoom,
    setForbiddenText,
    setDeletionText,
    setOptionDeletionText,
    setTagBanned,
    setInitialForbiddenText,
    setInitialDeletionText,
    setInitialOptionDeletionText,
    setWordsSaving,
  } as ExternalSettingsState & ExternalSettingsActions
}

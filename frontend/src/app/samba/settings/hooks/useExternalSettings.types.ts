import type {
  ExchangeCurrencyCode,
  ExchangeRateResponse,
} from '../config'

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

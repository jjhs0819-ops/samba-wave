'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { accountApi, collectorApi, forbiddenApi, proxyApi, type SambaMarketAccount } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { card, inputStyle, fmtNum, parseNum } from '@/lib/samba/styles'

const MARKET_TYPES = [
  { value: 'smartstore', label: '스마트스토어' },
  { value: 'coupang', label: '쿠팡' },
  { value: 'gmarket', label: 'G마켓' },
  { value: 'auction', label: '옥션' },
  { value: '11st', label: '11번가' },
  { value: 'lotteon', label: '롯데ON' },
  { value: 'ssg', label: '신세계몰' },
  { value: 'kream', label: 'KREAM' },
  { value: 'musinsa', label: '무신사' },
  { value: 'ebay', label: 'eBay' },
  { value: 'lazada', label: 'Lazada' },
  { value: 'qoo10', label: 'Qoo10' },
  { value: 'shopee', label: 'Shopee' },
  { value: 'shopify', label: 'Shopify' },
  { value: 'zoom', label: 'Zum(줌)' },
]

const CLAUDE_MODELS = [
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (권장)' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6 (고성능)' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (빠름/저렴)' },
]

const AI_FEATURES = [
  { key: 'productName', label: '상품명 가공' },
  { key: 'description', label: '상세설명 생성' },
  { key: 'csReply', label: 'CS 자동 답변' },
  { key: 'autoTag', label: '태그 자동 생성' },
  { key: 'imageProcess', label: '이미지 가공' },
]


// 숫자 입력 컴포넌트 (콤마 서식 + 스피너 제거)
function NumInput({ value, onChange, style, placeholder }: {
  value: string
  onChange: (v: string) => void
  style?: React.CSSProperties
  placeholder?: string
}) {
  const [display, setDisplay] = useState(() => {
    const n = parseNum(value)
    return n > 0 ? fmtNum(n) : ''
  })
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (document.activeElement !== ref.current) {
      const n = parseNum(value)
      setDisplay(n > 0 ? fmtNum(n) : '')
    }
  }, [value])

  return (
    <input
      ref={ref}
      type="text"
      inputMode="numeric"
      style={{ ...inputStyle, ...style }}
      value={display}
      placeholder={placeholder || '0'}
      onChange={(e) => {
        const raw = e.target.value.replace(/[^0-9]/g, '')
        setDisplay(raw)
      }}
      onBlur={(e) => {
        const n = parseNum(e.target.value)
        setDisplay(n > 0 ? fmtNum(n) : '')
        onChange(n > 0 ? String(n) : '')
      }}
    />
  )
}

// 마켓별 스토어 연결 필드 정의
interface MarketConfig {
  key: string
  label: string
  authField?: string
  guideUrl?: string // API 가이드 링크
  fields: { name: string; label: string; type: string; placeholder?: string; options?: { value: string; label: string }[] }[]
}

const STORE_MARKETS: MarketConfig[] = [
  { key: 'smartstore', label: '스마트스토어', authField: 'clientSecret', guideUrl: 'https://apicenter.commerce.naver.com/ko/member/home', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'clientId', label: 'Client ID', type: 'text' },
    { name: 'clientSecret', label: 'Client Secret', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'gmarket', label: '지마켓', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'auction', label: '옥션', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'coupang', label: '쿠팡', authField: 'secretKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'vendorId', label: 'Vendor 업체코드', type: 'text', placeholder: 'Wing 판매자 업체코드' },
    { name: 'accessKey', label: 'Access key', type: 'text' },
    { name: 'secretKey', label: 'Secret key', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'lotteon', label: '롯데ON', authField: 'apiKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: '롯데ON API key', type: 'text' },
    { name: 'dvCstPolNo', label: '배송정책번호', type: 'text', placeholder: '예: 3757145' },
    { name: 'owhpNo', label: '출고지번호', type: 'text', placeholder: '예: PLO3293317' },
    { name: 'rtrpNo', label: '회수지번호', type: 'text', placeholder: '예: PLO3293317' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: '11st', label: '11번가', authField: 'apiKey', guideUrl: 'https://openapi.11st.co.kr/openapi/OpenApiServiceRegister.tmall', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '상품전송 ID', type: 'text', placeholder: '11번가 셀러 ID' },
    { name: 'apiKey', label: 'Open API Key', type: 'text', placeholder: '32자리 Open API Key' },
    { name: 'sellerType', label: '판매자 형태', type: 'select', options: [
      { value: 'domestic', label: '국내판매자(국내사업자)' },
      { value: 'global', label: '글로벌판매자(국내사업자)' },
      { value: 'overseas', label: '국내판매자(해외사업자)' },
    ]},
    { name: 'taxType', label: '과세구분', type: 'select', options: [
      { value: '01', label: '과세' },
      { value: '02', label: '면세' },
    ]},
    { name: 'deliveryType', label: '배송비 유형', type: 'select', options: [
      { value: 'DV_FREE', label: '무료배송' },
      { value: 'DV_FIX', label: '유료배송(고정)' },
      { value: 'DV_COND', label: '조건부 무료' },
    ]},
    { name: 'deliveryFee', label: '배송비', type: 'number', placeholder: '0' },
    { name: 'jejuFee', label: '제주 추가배송비', type: 'number', placeholder: '4000' },
    { name: 'islandFee', label: '도서지역 추가배송비', type: 'number', placeholder: '5000' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '4000' },
    { name: 'exchangeFee', label: '반품배송비(왕복)', type: 'number', placeholder: '8000' },
    { name: 'shipFromAddress', label: '출고지 주소', type: 'text', placeholder: '출고지 주소 입력' },
    { name: 'returnAddress', label: '반품지 주소', type: 'text', placeholder: '반품지 주소 입력' },
    { name: 'origin', label: '원산지', type: 'text', placeholder: '기타' },
    { name: 'asMessage', label: 'A/S안내', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'returnExchangeGuide', label: '반품/교환 안내', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'minorRestrict', label: '청소년구매불가', type: 'select', options: [
      { value: 'N', label: '아니오' },
      { value: 'Y', label: '예' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'ssg', label: 'SSG', authField: 'apiKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiId', label: 'API ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'gsshop', label: 'GSSHOP', authField: 'apiKeyProd', guideUrl: 'https://partners.gsshop.com/api/apiMain', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKeyDev', label: '개발 AES256 인증키', type: 'password' },
    { name: 'apiKeyProd', label: '운영 AES256 인증키', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'lottehome', label: '롯데홈쇼핑', authField: 'password', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '로그인 ID', type: 'text', placeholder: '롯데홈쇼핑 로그인 ID' },
    { name: 'agncNo', label: '업체번호', type: 'text', placeholder: '예: 037800LT' },
    { name: 'password', label: '비밀번호', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'homeand', label: '홈앤쇼핑', authField: 'apiKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiId', label: 'API ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'hmall', label: 'HMALL', authField: 'apiKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiId', label: 'API ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'kream', label: 'KREAM', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'saleType', label: '판매유형', type: 'select', options: [
      { value: 'general', label: '일반판매' }, { value: 'storage', label: '보관판매' }, { value: 'grade95', label: '95점판매' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'ebay', label: 'eBay', authField: 'oauthToken', guideUrl: 'https://developer.ebay.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'eBay Seller ID', type: 'text' },
    { name: 'clientId', label: 'App ID (Client ID)', type: 'text' },
    { name: 'clientSecret', label: 'Cert ID (Client Secret)', type: 'password' },
    { name: 'oauthToken', label: 'OAuth Refresh Token', type: 'password' },
    { name: 'siteId', label: 'Site ID', type: 'select', options: [
      { value: '0', label: 'US (0)' }, { value: '3', label: 'UK (3)' }, { value: '77', label: 'DE (77)' }, { value: '15', label: 'AU (15)' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'lazada', label: 'Lazada', authField: 'accessToken', guideUrl: 'https://open.lazada.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Seller ID', type: 'text' },
    { name: 'appKey', label: 'App Key', type: 'text' },
    { name: 'appSecret', label: 'App Secret', type: 'password' },
    { name: 'accessToken', label: 'Access Token', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'sg', label: 'Singapore' }, { value: 'my', label: 'Malaysia' }, { value: 'th', label: 'Thailand' },
      { value: 'ph', label: 'Philippines' }, { value: 'id', label: 'Indonesia' }, { value: 'vn', label: 'Vietnam' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'qoo10', label: 'Qoo10', authField: 'apiKey', guideUrl: 'https://qsm.qoo10.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Seller ID', type: 'text' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'userKey', label: 'User Key', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'jp', label: 'Japan' }, { value: 'sg', label: 'Singapore' }, { value: 'global', label: 'Global' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'shopee', label: 'Shopee', authField: 'accessToken', guideUrl: 'https://open.shopee.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Shop ID', type: 'text' },
    { name: 'partnerId', label: 'Partner ID', type: 'text' },
    { name: 'partnerKey', label: 'Partner Key', type: 'password' },
    { name: 'accessToken', label: 'Access Token', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'sg', label: 'Singapore' }, { value: 'my', label: 'Malaysia' }, { value: 'th', label: 'Thailand' },
      { value: 'ph', label: 'Philippines' }, { value: 'id', label: 'Indonesia' }, { value: 'vn', label: 'Vietnam' },
      { value: 'tw', label: 'Taiwan' }, { value: 'br', label: 'Brazil' },
    ]},
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'shopify', label: 'Shopify', authField: 'accessToken', guideUrl: 'https://shopify.dev/docs/api', fields: [
    { name: 'businessName', label: '스토어명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 도메인', type: 'text', placeholder: 'mystore.myshopify.com' },
    { name: 'accessToken', label: 'Admin API Access Token', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'zoom', label: 'Zum(줌)', authField: 'apiKey', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'apiSecret', label: 'API Secret', type: 'password' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
]

export default function SettingsPage() {
  // Accounts state
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [accountLoading, setAccountLoading] = useState(true)

  // 스토어 연결
  const [storeTab, setStoreTab] = useState('smartstore')
  const [storeData, setStoreData] = useState<Record<string, Record<string, string>>>({})
  const [savedStoreData, setSavedStoreData] = useState<Record<string, Record<string, string>>>({})
  const [storeStatus, setStoreStatus] = useState<Record<string, string>>({})
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null) // 수정 중인 계정 ID

  // 알리고 SMS 설정
  const [smsUserId, setSmsUserId] = useState('')
  const [smsApiKey, setSmsApiKey] = useState('')
  const [smsSender, setSmsSender] = useState('')
  const [smsStatus, setSmsStatus] = useState('')

  // 카카오 알림톡 설정
  const [kakaoUserId, setKakaoUserId] = useState('')
  const [kakaoApiKey, setKakaoApiKey] = useState('')
  const [kakaoSenderKey, setKakaoSenderKey] = useState('')
  const [kakaoSender, setKakaoSender] = useState('')
  const [kakaoStatus, setKakaoStatus] = useState('')

  // Probe 상태
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // Claude AI API 설정
  const [claudeApiKey, setClaudeApiKey] = useState('')
  const [claudeModel, setClaudeModel] = useState('claude-sonnet-4-6')
  const [claudeStatus, setClaudeStatus] = useState('')
  const [aiFeatures, setAiFeatures] = useState<Record<string, boolean>>({ productName: true })

  const loadAccounts = useCallback(async () => {
    setAccountLoading(true)
    try { setAccounts(await accountApi.list()) } catch { /* ignore */ }
    setAccountLoading(false)
  }, [])

  // 스토어 연결 설정 로드 (폼은 비워두고 savedStoreData에만 저장)
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
    setSavedStoreData(loaded)
    setStoreStatus(statuses)
  }, [])

  const updateStoreField = (marketKey: string, fieldName: string, value: string) => {
    setStoreData(prev => ({
      ...prev,
      [marketKey]: { ...(prev[marketKey] || {}), [fieldName]: value }
    }))
  }

  const saveStoreSettings = async (marketKey: string) => {
    try {
      const data = storeData[marketKey] || {}
      await forbiddenApi.saveSetting(`store_${marketKey}`, data)
      const marketCfg = STORE_MARKETS.find(m => m.key === marketKey)
      const label = marketCfg?.label || marketKey

      // 계정 자동 생성/업데이트
      const sellerId = data.storeId || data.account || data.email || data.userId || data.vendorId || data.apiKey || ''
      const businessName = data.businessName || ''
      if (sellerId || businessName) {
        // API 인증정보를 additional_fields에 저장 (계정별 독립 인증)
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
      // 저장 후 savedStoreData 갱신 + 폼 비우기
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
      setStoreData(prev => { const next = { ...prev }; delete next[marketKey]; return next })
      setStoreStatus(prev => ({ ...prev, [marketKey]: '연결됨' }))

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
      // 먼저 설정 저장
      await forbiddenApi.saveSetting(`store_${marketKey}`, data)
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
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
        // 인증 성공 시 배송인프라 값을 폼에 자동 반영
        if (lotteonResult.success && lotteonResult.data) {
          const infra = lotteonResult.data
          const updated = { ...data }
          if (infra.dvCstPolNo && !data.dvCstPolNo) updated.dvCstPolNo = infra.dvCstPolNo
          if (infra.owhpNo && !data.owhpNo) updated.owhpNo = infra.owhpNo
          if (infra.rtrpNo && !data.rtrpNo) updated.rtrpNo = infra.rtrpNo
          setStoreData(prev => ({ ...prev, [marketKey]: updated }))
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

  // 설정 로드 (SMS/카카오/Claude)
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
  }, [])

  useEffect(() => { loadAccounts() }, [loadAccounts])

  const loadProbeStatus = useCallback(async () => {
    try {
      const data = await collectorApi.probeStatus() as Record<string, Record<string, Record<string, unknown>>>
      if (data) setProbeData(data)
    } catch { /* ignore */ }
  }, [])

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

  useEffect(() => { loadExternalSettings(); loadStoreSettings(); loadProbeStatus() }, [loadExternalSettings, loadStoreSettings, loadProbeStatus])

  const handleAccountToggle = async (id: string) => { await accountApi.toggle(id); loadAccounts() }
  const handleAccountDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    await accountApi.delete(id); loadAccounts()
  }

  // SMS 설정 저장
  const saveSmsSettings = async () => {
    try {
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      setSmsStatus('저장됨')
      showAlert('SMS 설정이 저장되었습니다.', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // SMS Key 테스트 - 설정 저장 후 알리고 API로 잔여건수 조회
  const testSmsKey = async () => {
    if (!smsUserId || !smsApiKey) {
      showAlert('Identifier와 API Key를 먼저 입력하세요.', 'error')
      return
    }
    setSmsStatus('확인 중...')
    try {
      // 먼저 설정 저장
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      // 알리고 잔여건수 조회
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

  // 카카오 Key 테스트
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

  // Claude API 테스트 — 실제 API 호출로 검증
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
      // 먼저 설정 저장
      await forbiddenApi.saveSetting('claude', { apiKey: claudeApiKey, model: claudeModel, aiFeatures, updatedAt: new Date().toISOString() })
      // 실제 API 호출 테스트
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

  const toggleAiFeature = (key: string) => {
    setAiFeatures(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 마켓 계정 */}
          {/* 스토어 연결 */}
          <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>스토어 연결</div>
            <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1.25rem' }}>API 연결 및 계정 설정을 관리합니다</p>

            {/* 마켓 탭바 */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 0, borderBottom: '1px solid #2D2D2D', marginBottom: '1.5rem' }}>
              {STORE_MARKETS.map(m => (
                <button
                  key={m.key}
                  onClick={() => setStoreTab(m.key)}
                  style={{
                    padding: '0.5rem 1rem', background: 'none', border: 'none',
                    borderBottom: storeTab === m.key ? '2px solid #FF8C00' : '2px solid transparent',
                    color: storeTab === m.key ? '#FF8C00' : '#666',
                    fontSize: '0.8125rem', fontWeight: storeTab === m.key ? 600 : 400,
                    cursor: 'pointer', marginBottom: '-1px', whiteSpace: 'nowrap',
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* 마켓별 설정 폼 */}
            {STORE_MARKETS.filter(m => m.key === storeTab).map(market => (
              <div key={market.key} style={{ maxWidth: '560px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                  <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5' }}>{market.label} 설정</span>
                  {editingAccountId && (
                    <>
                      <span style={{ fontSize: '0.75rem', color: '#FF8C00', fontWeight: 600 }}>
                        ({accounts.find(a => a.id === editingAccountId)?.account_label} 수정중)
                      </span>
                      <button
                        onClick={() => {
                          setEditingAccountId(null)
                          setStoreData(prev => { const next = { ...prev }; delete next[market.key]; return next })
                        }}
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer' }}
                      >취소</button>
                    </>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {market.fields.map(field => (
                    <div key={field.name} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '180px', flexShrink: 0 }}>{field.label}</label>
                      {field.type === 'select' ? (
                        <select
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                        >
                          {field.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      ) : field.type === 'number' ? (
                        <NumInput
                          style={{ flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(v) => updateStoreField(market.key, field.name, v)}
                          placeholder={field.placeholder || '0'}
                        />
                      ) : (
                        <input
                          type={field.type}
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                          placeholder={field.placeholder || ''}
                        />
                      )}
                      {/* API 인증 필드 우측에 인증 테스트 버튼 */}
                      {market.authField === field.name && (
                        <>
                          <button
                            onClick={() => testStoreAuth(market.key)}
                            style={{ padding: '0.375rem 0.875rem', background: '#FF8C00', color: '#000', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                          >인증 테스트</button>
                          {market.guideUrl && (
                            <a href={market.guideUrl} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '0.375rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0 }}
                            >API 발급</a>
                          )}
                        </>
                      )}
                      {/* 11번가 출고지정보 가져오기 버튼 */}
                      {market.key === '11st' && field.name === 'shipFromAddress' && (
                        <button
                          onClick={async () => {
                            try {
                              // 현재 입력된 API Key로 먼저 설정 저장
                              const data = storeData['11st'] || {}
                              if (data.apiKey) {
                                await forbiddenApi.saveSetting('store_11st', data)
                              }
                              const res = await proxyApi.elevenstSellerInfo()
                              if (res.success && res.data) {
                                const d = res.data
                                if (d.shipFromAddress) updateStoreField('11st', 'shipFromAddress', d.shipFromAddress)
                                if (d.returnAddress) updateStoreField('11st', 'returnAddress', d.returnAddress)
                                if (d.returnFee) updateStoreField('11st', 'returnFee', d.returnFee)
                                if (d.exchangeFee) updateStoreField('11st', 'exchangeFee', d.exchangeFee)
                                showAlert('출고지/반품지 정보를 가져왔습니다.', 'success')
                              } else {
                                showAlert(res.message || '정보를 가져올 수 없습니다.', 'error')
                              }
                            } catch {
                              showAlert('출고지 정보 조회 실패', 'error')
                            }
                          }}
                          style={{ padding: '0.375rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                        >출고지정보 가져오기</button>
                      )}
                    </div>
                  ))}
                  {storeStatus[market.key] && (
                    <div style={{ fontSize: '0.8125rem', color: storeStatus[market.key]?.includes('연결') || storeStatus[market.key]?.includes('저장') || storeStatus[market.key]?.includes('✓') ? '#51CF66' : storeStatus[market.key]?.includes('중...') ? '#FFD93D' : '#FF6B6B' }}>
                      {storeStatus[market.key]}
                    </div>
                  )}
                </div>

                {/* 설정 저장 */}
                <div style={{ marginTop: '1.5rem' }}>
                  <button
                    onClick={() => saveStoreSettings(market.key)}
                    style={{ padding: '0.625rem 1.75rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 700, fontSize: '0.875rem', cursor: 'pointer' }}
                  >설정 저장</button>
                </div>
              </div>
            ))}
          </div>

          {/* 마켓별 계정 현황 */}
          <div style={{ marginBottom: '1rem' }}>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>마켓별 계정 현황</div>
          </div>

          {accountLoading ? (
            <div style={{ ...card, padding: '2rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
          ) : accounts.length === 0 ? (
            <div style={{ ...card, padding: '2rem', textAlign: 'center', color: '#555' }}>마켓 계정이 없습니다</div>
          ) : (() => {
            // 마켓별 그룹핑
            const grouped: Record<string, SambaMarketAccount[]> = {}
            accounts.forEach(a => {
              if (!grouped[a.market_type]) grouped[a.market_type] = []
              grouped[a.market_type].push(a)
            })
            const marketColors: Record<string, string> = {
              smartstore: '#03C75A', coupang: '#E4422B', gmarket: '#6DB33F', auction: '#E74C3C',
              '11st': '#FF0000', lotteon: '#E10044', ssg: '#FF5A00', gsshop: '#6B5CE7',
              lottehome: '#E10044', homeand: '#FF6600', hmall: '#2D2D8A', kream: '#222', musinsa: '#1A1A1A',
            }
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', maxWidth: '480px' }}>
                {Object.entries(grouped).map(([marketType, accs]) => {
                  const marketLabel = STORE_MARKETS.find(m => m.key === marketType)?.label
                    || MARKET_TYPES.find(m => m.value === marketType)?.label || marketType
                  const color = marketColors[marketType] || '#FF8C00'
                  return (
                    <div key={marketType} style={{ ...card, padding: '0.75rem 1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <span style={{
                          width: '24px', height: '24px', borderRadius: '5px', display: 'flex',
                          alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem',
                          fontWeight: 700, color: '#fff', background: color,
                        }}>
                          {marketLabel.charAt(0)}
                        </span>
                        <span style={{ fontWeight: 700, color: '#E5E5E5', fontSize: '0.85rem' }}>
                          {marketLabel}
                        </span>
                        <span style={{ fontSize: '0.7rem', color: '#888' }}>({accs.length}개)</span>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                        {accs.map(a => (
                          <div key={a.id} style={{
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            padding: '0.3rem 0.5rem', background: 'rgba(255,255,255,0.02)',
                            borderRadius: '5px', border: '1px solid rgba(45,45,45,0.5)',
                          }}>
                            <div style={{ flex: 1, minWidth: 0, fontSize: '0.8rem', color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {a.account_label}
                            </div>
                            <button
                              onClick={() => {
                                setStoreTab(marketType)
                                setEditingAccountId(a.id)
                                // 해당 계정의 데이터를 폼에 채우기
                                const accFields = (a.additional_fields || {}) as Record<string, string>
                                const formData: Record<string, string> = {
                                  businessName: a.business_name || '',
                                  storeId: a.seller_id || '',
                                  ...accFields,
                                }
                                setStoreData(prev => ({ ...prev, [marketType]: formData }))
                              }}
                              style={{
                                padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                                background: editingAccountId === a.id ? 'rgba(255,140,0,0.15)' : 'rgba(60,60,60,0.8)',
                                color: editingAccountId === a.id ? '#FF8C00' : '#C5C5C5',
                                border: editingAccountId === a.id ? '1px solid #FF8C00' : '1px solid #3D3D3D',
                                cursor: 'pointer', whiteSpace: 'nowrap',
                              }}
                            >
                              {editingAccountId === a.id ? '수정중' : '수정'}
                            </button>
                            <button
                              onClick={() => handleAccountDelete(a.id)}
                              style={{
                                padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                                background: 'rgba(255,80,80,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,80,80,0.3)',
                                cursor: 'pointer', whiteSpace: 'nowrap',
                              }}
                            >
                              삭제
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          })()}
      {/* SMS / 카카오 알림톡 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.5rem' }}>

        {/* SMS 설정 */}
        <div style={{ paddingBottom: '1.5rem', marginBottom: '1.5rem', borderBottom: '1px solid #2D2D2D' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#4C9AFF' }}>SMS 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 문자메세지 설정을 할 수 있습니다.</span>
            {smsStatus && <span style={{ fontSize: '0.8rem', color: smsStatus === '저장됨' || smsStatus.includes('유효') ? '#51CF66' : smsStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{smsStatus === '저장됨' ? '✓ 저장됨' : smsStatus}</span>}
            <button onClick={saveSmsSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>SMS API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={smsUserId} onChange={(e) => setSmsUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={smsApiKey} onChange={(e) => setSmsApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testSmsKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>SMS 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={smsSender} onChange={(e) => setSmsSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>

        {/* 카카오 알림톡 설정 */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FFB84D' }}>카카오 알림톡 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 카카오 알림톡 설정을 할 수 있습니다.</span>
            {kakaoStatus && <span style={{ fontSize: '0.8rem', color: kakaoStatus === '저장됨' || kakaoStatus.includes('유효') ? '#51CF66' : kakaoStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{kakaoStatus === '저장됨' ? '✓ 저장됨' : kakaoStatus}</span>}
            <button onClick={saveKakaoSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>알림톡 API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={kakaoUserId} onChange={(e) => setKakaoUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={kakaoApiKey} onChange={(e) => setKakaoApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testKakaoKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 SenderKey</label>
              <input style={{ ...inputStyle, flex: 1 }} value={kakaoSenderKey} onChange={(e) => setKakaoSenderKey(e.target.value)} placeholder='Senderkey를 입력하세요.' />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={kakaoSender} onChange={(e) => setKakaoSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>
      </div>

      {/* Claude AI API 연동 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#A78BFA' }}>Claude AI API 연동</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** Anthropic Claude API를 연결하면 상품명 가공, CS 자동 답변 등 AI 기능을 사용할 수 있습니다.</span>
          <button onClick={saveClaudeSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>API Key</label>
            <input
              type='password'
              style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }}
              value={claudeApiKey}
              onChange={(e) => setClaudeApiKey(e.target.value)}
              placeholder='sk-ant-api03-...'
            />
            <button onClick={testClaudeApi} style={{ background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.35)', color: '#A78BFA', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>모델 선택</label>
            <select style={{ ...inputStyle, width: '260px' }} value={claudeModel} onChange={(e) => setClaudeModel(e.target.value)}>
              {CLAUDE_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          {claudeStatus && (
            <div style={{ fontSize: '0.8125rem', color: claudeStatus.includes('저장') ? '#51CF66' : claudeStatus.includes('유효') ? '#FFB84D' : '#FF6B6B', padding: '0.4rem 0' }}>
              {claudeStatus.includes('저장') ? '✓ ' : claudeStatus.includes('유효') ? '⚠ ' : '✗ '}{claudeStatus}
            </div>
          )}
        </div>
      </div>

    </div>
  )
}

'use client'

import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  orderApi,
  channelApi,
  accountApi,
  proxyApi,
  collectorApi,
  forbiddenApi,
  type SambaOrder,
  type SambaChannel,
  type SambaMarketAccount,
} from '@/lib/samba/api/commerce'
import { fetchWithAuth } from '@/lib/samba/api/shared'
import { sourcingAccountApi, type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { PERIOD_BUTTONS, DELIVERY_TRACKING_URLS } from '@/lib/samba/constants'
import { inputStyle, fmtNum } from '@/lib/samba/styles'
import { fmtDate } from '@/lib/samba/utils'

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending:    { label: '주문접수', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  wait_ship:  { label: '배송대기중', bg: 'rgba(100,149,237,0.15)', text: '#6495ED' },
  arrived:    { label: '사무실도착', bg: 'rgba(72,209,204,0.15)', text: '#48D1CC' },
  ship_failed: { label: '송장전송실패', bg: 'rgba(255,50,50,0.2)', text: '#FF3232' },
  shipping:   { label: '국내배송중', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  delivered:  { label: '배송완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelling: { label: '취소중', bg: 'rgba(255,165,0,0.15)', text: '#FFA500' },
  returning:  { label: '반품중', bg: 'rgba(200,100,200,0.15)', text: '#CC5DE8' },
  exchanging: { label: '교환중', bg: 'rgba(255,182,193,0.15)', text: '#FFB6C1' },
  cancel_requested: { label: '취소요청', bg: 'rgba(255,80,80,0.2)', text: '#FF5050' },
  return_requested: { label: '반품요청', bg: 'rgba(200,100,200,0.2)', text: '#CC5DE8' },
  cancelled:  { label: '취소완료', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  returned:   { label: '반품완료', bg: 'rgba(180,80,180,0.15)', text: '#B44EB4' },
  exchanged:  { label: '교환완료', bg: 'rgba(144,238,144,0.15)', text: '#90EE90' },
}

const SHIPPING_COMPANIES = ['CJ대한통운', '한진택배', '롯데택배', '로젠택배', '우체국택배', '경동택배', '대신택배', '일양로지스', '편의점택배', 'DHL', '직접배송', '기타']

const MARKET_STATUS_OPTIONS = [
  '발주미확인', '발송대기', '결제완료', '주문접수', '배송대기중',
  '배송중', '배송완료', '구매확정', '송장출력', '송장입력', '출고', '정산완료',
  '취소요청', '취소처리중', '취소완료', '취소거부', '취소중',
  '반품요청', '수거중', '수거완료', '반품완료', '반품거부',
  '교환요청', '교환처리중', '교환완료', '교환거부',
  '보류', '송장전송완료',
]

const TRACKING_URLS = DELIVERY_TRACKING_URLS

interface OrderForm {
  channel_id: string; product_name: string; customer_name: string; customer_phone: string
  customer_address: string; sale_price: number; cost: number; fee_rate: number
  shipping_company: string; tracking_number: string; notes: string
}

const emptyForm: OrderForm = {
  channel_id: '', product_name: '', customer_name: '', customer_phone: '',
  customer_address: '', sale_price: 0, cost: 0, fee_rate: 0,
  shipping_company: '', tracking_number: '', notes: '',
}

// 직배/까대기/선물 버튼 색상
const ACTION_BUTTONS = [
  { key: 'no_price', label: '가격X', activeColor: '#DC2626' },
  { key: 'no_stock', label: '재고X', activeColor: '#CA8A04' },
  { key: 'direct', label: '직배', activeColor: '#2563EB' },
  { key: 'kkadaegi', label: '까대기', activeColor: '#D97706' },
  { key: 'gift', label: '선물', activeColor: '#059669' },
] as const

export default function OrdersPage() {
  useEffect(() => { document.title = 'SAMBA-주문관리' }, [])
  const searchParams = useSearchParams()
  // 상품별 주문이력 조회 모드
  const cpId = searchParams.get('cpId')
  const cpName = searchParams.get('cpName')
  const isProductMode = !!cpId
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [channels, setChannels] = useState<SambaChannel[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('1month')
  const [marketFilter, setMarketFilter] = useState('')
  const [marketStatus, setMarketStatus] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState('')
  const [inputFilter, setInputFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [searchText, setSearchText] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkStatus, setBulkStatus] = useState('')
  const [bulkUpdating, setBulkUpdating] = useState(false)
  const [sortBy, setSortBy] = useState('date_desc')
  const [logMessages, _setLogMessagesRaw] = useState<string[]>(['[대기] 주문 가져오기 결과가 여기에 표시됩니다...'])
  const setLogMessages: typeof _setLogMessagesRaw = (v) => _setLogMessagesRaw(prev => {
    const next = typeof v === 'function' ? v(prev) : v
    return next.slice(-30)
  })
  const [smsRemain, setSmsRemain] = useState<{ SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncAccountId, setSyncAccountId] = useState('')
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })
  // 인라인 원가/배송비/송장 수정용 상태
  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingTrackings, setEditingTrackings] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  const [editingOrderNumbers, setEditingOrderNumbers] = useState<Record<string, string>>({})
  // 직배/까대기/선물 토글 상태
  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  // 우측상단 알람
  const [notifications, setNotifications] = useState<{id: number, message: string, type: string}[]>([])

  const showNotification = (message: string, type: string = 'warning') => {
    const id = Date.now()
    setNotifications(prev => [...prev, { id, message, type }])
  }

  // 주문별 업데이트 로그 (주문 ID → 마지막 갱신 결과)
  const [refreshLog, setRefreshLog] = useState<Record<string, string>>({})

  // 가격이력 모달
  const [priceHistoryModal, setPriceHistoryModal] = useState(false)
  const [priceHistoryData, setPriceHistoryData] = useState<Record<string, unknown>[]>([])
  const [priceHistoryProduct, setPriceHistoryProduct] = useState<{ name: string; source_site: string }>({ name: '', source_site: '' })

  const [showUrlModal, setShowUrlModal] = useState(false)
  const [urlModalOrderId, setUrlModalOrderId] = useState('')
  const [urlModalInput, setUrlModalInput] = useState('')
  const [urlModalImageInput, setUrlModalImageInput] = useState('')
  const [urlModalSaving, setUrlModalSaving] = useState(false)
  // SMS/카카오 발송 모달
  const [msgModal, setMsgModal] = useState<{ type: 'sms' | 'kakao'; order: SambaOrder } | null>(null)
  const [msgText, setMsgText] = useState('')
  const [msgSending, setMsgSending] = useState(false)
  const msgTextRef = useRef<HTMLTextAreaElement>(null)
  // 취소 알림 설정 (URL 파라미터 alarm=1이면 자동 오픈)
  const [showAlarmSetting, setShowAlarmSetting] = useState(searchParams.get('alarm') === '1')
  const [alarmHour, setAlarmHour] = useState('1')
  const [alarmMin, setAlarmMin] = useState('0')
  const [sleepStart, setSleepStart] = useState('23:00')
  const [sleepEnd, setSleepEnd] = useState('07:00')

  const MSG_VARIABLE_TAGS = [
    { tag: '{{sellerName}}', label: '판매자명' },
    { tag: '{{marketName}}', label: '판매마켓이름' },
    { tag: '{{OrderName}}', label: '주문번호' },
    { tag: '{{rvcName}}', label: '수취인명' },
    { tag: '{{rcvHPNo}}', label: '수취인휴대폰번호' },
    { tag: '{{goodsName}}', label: '상품명' },
  ]

  const insertMsgTag = (tag: string) => {
    const el = msgTextRef.current
    if (!el) { setMsgText(prev => prev + tag); return }
    const start = el.selectionStart
    const end = el.selectionEnd
    const newVal = msgText.slice(0, start) + tag + msgText.slice(end)
    setMsgText(newVal)
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + tag.length; el.focus() })
  }
  // 검색 카테고리
  const [searchCategory, setSearchCategory] = useState('customer')
  // 일자 고정
  const [dateLocked, setDateLocked] = useState(false)
  const [customStart, setCustomStart] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 29)
    return d.toLocaleDateString('sv-SE')
  })
  const [startLocked, setStartLocked] = useState(false)
  const [customEnd, setCustomEnd] = useState(new Date().toLocaleDateString('sv-SE'))

  const loadOrders = useCallback(async () => {
    setLoading(true)
    try {
      const data = isProductMode
        ? await orderApi.listByCollectedProduct(cpId!)
        : await orderApi.listByDateRange(customStart, customEnd)
      setOrders(data)
      setCurrentPage(1)
      setEditingTrackings({})
      // 서버에서 받은 action_tag로 activeActions 초기화
      const actions: Record<string, string | null> = {}
      for (const o of data) {
        if (o.action_tag) actions[o.id] = o.action_tag
      }
      setActiveActions(actions)
    } catch (e) {
      console.error('주문 로딩 실패:', e)
      setLogMessages(prev => [...prev, `[에러] 주문 데이터 로딩 실패: ${e instanceof Error ? e.message : '서버 오류'}`])
    }
    setLoading(false)
  }, [isProductMode, cpId, customStart, customEnd])

  // 플레이오토 마켓번호 별칭 매핑
  const [siteAliasMap, setSiteAliasMap] = useState<Record<string, string>>({})
  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => { channelApi.list().then(setChannels).catch(() => {}) }, [])
  useEffect(() => { accountApi.listActive().then(setAccounts).catch(() => {}) }, [])
  useEffect(() => { sourcingAccountApi.list().then(accs => setSourcingAccounts(accs.filter(a => a.is_active))).catch(() => {}) }, [])
  useEffect(() => {
    proxyApi.aligoRemain().then(r => { if (r.success) setSmsRemain(r) }).catch(() => {})
  }, [])
  useEffect(() => {
    forbiddenApi.getSetting('store_playauto').then(data => {
      const d = data as Record<string, string> | null
      if (!d) return
      const map: Record<string, string> = {}
      for (const k of ['alias1', 'alias2', 'alias3']) {
        const v = d[k] || ''
        if (v.includes('-')) {
          const [code, ...rest] = v.split('-')
          map[code.trim()] = rest.join('-').trim()
        }
      }
      setSiteAliasMap(map)
    }).catch(() => {})
  }, [])

  const handleFetch = async () => {
    setSyncing(true)
    const ts = () => new Date().toLocaleTimeString()
    const daysMap: Record<string, number> = {
      yesterday: 1, today: 1, thisweek: 7, lastweek: 14, '1week': 7, '15days': 15,
      thismonth: 31, lastmonth: 60, '1month': 30, '3months': 90, '6months': 180,
      thisyear: Math.ceil((Date.now() - new Date(new Date().getFullYear(), 0, 1).getTime()) / 86400000) + 1, all: 365,
    }
    const days = daysMap[period] || 7

    // 마켓타입 선택 시 해당 마켓 계정들만 순회 동기화
    if (syncAccountId.startsWith('type:')) {
      const marketType = syncAccountId.replace('type:', '')
      const marketAccs = accounts.filter(a => a.market_type === marketType)
      const marketName = marketAccs[0]?.market_name || marketType
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 전체 계정 주문 동기화 시작 (${marketAccs.length}개 계정, 최근 ${days}일)...`])
      let totalSynced = 0
      let totalCancelRequested = 0
      for (const acc of marketAccs) {
        const label = `${acc.market_name}(${acc.seller_id || '-'})`
        try {
          const res = await orderApi.syncFromMarkets(days, acc.id)
          for (const r of res.results) {
            if (r.status === 'success') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.fetched?.toLocaleString()}건 조회, ${r.synced?.toLocaleString()}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${(r as Record<string, unknown>).confirmed}건 발주확인` : ''}`])
            } else if (r.status === 'skip') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
            } else {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
            }
            totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
          }
          totalSynced += res.total_synced
        } catch (e) {
          setLogMessages(prev => [...prev, `[${ts()}] ${label} 오류: ${e}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 동기화 완료 — 총 ${totalSynced.toLocaleString()}건 신규 저장`])
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${totalCancelRequested.toLocaleString()}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
      setSyncing(false)
      return
    }

    // 전체마켓 또는 개별 계정 동기화
    const isAll = !syncAccountId
    const acc = isAll ? null : accounts.find(a => a.id === syncAccountId)
    const label = isAll ? '전체마켓' : (acc ? `${acc.market_name}(${acc.seller_id || '-'})` : syncAccountId)
    setLogMessages(prev => [...prev, `[${ts()}] ${label} 주문 동기화 시작 (최근 ${days}일)...`])
    try {
      const res = await orderApi.syncFromMarkets(days, isAll ? undefined : syncAccountId)
      for (const r of res.results) {
        if (r.status === 'success') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.fetched?.toLocaleString()}건 조회, ${r.synced?.toLocaleString()}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${(r as Record<string, unknown>).confirmed}건 발주확인` : ''}`])
        } else if (r.status === 'skip') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
        } else {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 동기화 완료 — 총 ${res.total_synced.toLocaleString()}건 신규 저장`])
      let totalCancelRequested = 0
      for (const r of res.results) {
        totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
      }
      if (totalCancelRequested > 0) {
        showNotification(`주문 취소요청 ${totalCancelRequested.toLocaleString()}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${ts()}] 오류: ${e}`])
    }
    setSyncing(false)
  }

  const openEdit = (o: SambaOrder) => {
    setEditingId(o.id)
    setForm({
      channel_id: o.channel_id || '', product_name: o.product_name || '',
      customer_name: o.customer_name || '', customer_phone: o.customer_phone || '',
      customer_address: o.customer_address || '', sale_price: o.sale_price, cost: o.cost,
      fee_rate: o.fee_rate, shipping_company: o.shipping_company || '',
      tracking_number: o.tracking_number || '', notes: o.notes || '',
    })
    setShowForm(true)
  }

  const handleSubmit = async () => {
    try {
      const ch = channels.find(c => c.id === form.channel_id)
      const payload = { ...form, channel_name: ch?.name, fee_rate: form.fee_rate || ch?.fee_rate || 0 }
      if (editingId) await orderApi.update(editingId, payload)
      else await orderApi.create(payload)
      setShowForm(false); setEditingId(null); setForm({ ...emptyForm }); loadOrders()
    } catch (e) { showAlert(e instanceof Error ? e.message : '저장 실패', 'error') }
  }

  // SMS/카카오 발송
  const openMsgModal = (type: 'sms' | 'kakao', order: SambaOrder) => {
    if (!order.customer_phone) {
      showAlert('고객 전화번호가 없습니다', 'error')
      return
    }
    setMsgModal({ type, order })
    setMsgText('')
  }

  const handleSendMsg = async () => {
    if (!msgModal || !msgText.trim()) {
      showAlert('메시지를 입력해주세요', 'error')
      return
    }
    setMsgSending(true)
    try {
      const phone = msgModal.order.customer_phone || ''
      let res: { success: boolean; message: string }
      if (msgModal.type === 'sms') {
        res = await proxyApi.sendSms(phone, msgText)
      } else {
        res = await proxyApi.sendKakao(phone, msgText)
      }
      if (res.success) {
        showAlert(res.message, 'success')
        setMsgModal(null)
        setMsgText('')
      } else {
        showAlert(res.message, 'error')
      }
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '발송 실패', 'error')
    }
    setMsgSending(false)
  }

  const handleStatusChange = async (id: string, status: string) => {
    try { await orderApi.updateStatus(id, status); loadOrders() }
    catch (e) { showAlert(e instanceof Error ? e.message : '상태 변경 실패', 'error') }
  }

  const handleDelete = async (id: string) => {
    if (!await showConfirm('주문삭제하시겠습니까?')) return
    try { await orderApi.delete(id); loadOrders() }
    catch (e) { showAlert(e instanceof Error ? e.message : '삭제 실패', 'error') }
  }

  // 원가 인라인 저장
  const handleCostSave = async (id: string) => {
    const val = editingCosts[id]
    if (val === undefined) return
    try {
      await orderApi.update(id, { cost: Number(val) || 0 })
      setEditingCosts(prev => { const n = { ...prev }; delete n[id]; return n })
      loadOrders()
    } catch (e) { showAlert(e instanceof Error ? e.message : '원가 저장 실패', 'error') }
  }

  // 배송비 인라인 저장
  const handleShipFeeSave = async (id: string) => {
    const val = editingShipFees[id]
    if (val === undefined) return
    try {
      await orderApi.update(id, { shipping_fee: Number(val) || 0 })
      setEditingShipFees(prev => { const n = { ...prev }; delete n[id]; return n })
      loadOrders()
    } catch (e) { showAlert(e instanceof Error ? e.message : '배송비 저장 실패', 'error') }
  }

  // 실수익 실시간 계산 (정산 - 원가 - 배송비)
  const calcProfit = (o: SambaOrder) => {
    const costVal = editingCosts[o.id] !== undefined ? Number(editingCosts[o.id]) || 0 : o.cost
    const shipFeeVal = editingShipFees[o.id] !== undefined ? Number(editingShipFees[o.id]) || 0 : o.shipping_fee
    return o.revenue - costVal - shipFeeVal
  }

  const calcProfitRate = (o: SambaOrder) => {
    const profit = calcProfit(o)
    return o.revenue > 0 ? ((profit / o.revenue) * 100).toFixed(1) : '0'
  }

  // 버튼 핸들러
  const handleCopyOrderNumber = (orderNumber: string) => {
    navigator.clipboard.writeText(orderNumber)
    showAlert('주문번호가 복사되었습니다', 'success')
  }
  const handleDanawa = (productName: string) => {
    window.open(`https://search.danawa.com/dsearch.php?query=${encodeURIComponent(productName || '')}`, '_blank')
  }
  const handleNaver = (productName: string) => {
    window.open(`https://search.shopping.naver.com/search/all?query=${encodeURIComponent(productName || '')}`, '_blank')
  }
  const handleTracking = (shippingCompany: string, trackingNumber: string) => {
    if (!trackingNumber) {
      showAlert('송장번호가 없습니다', 'error')
      return
    }
    const baseUrl = TRACKING_URLS[shippingCompany] || TRACKING_URLS['CJ대한통운']
    window.open(`${baseUrl}${trackingNumber}`, '_blank')
  }
  const handleSourceLink = async (o: SambaOrder) => {
    // 1. 미등록 입력으로 등록한 source_url 우선
    if (o.source_url) {
      window.open(o.source_url, '_blank')
      return
    }
    // 2. product_id가 URL이면 직접 열기
    if (o.product_id && o.product_id.startsWith('http')) {
      window.open(o.product_id, '_blank')
      return
    }
    // 3. 마켓 상품번호로 수집상품 역추적
    if (o.product_id) {
      try {
        const res = await collectorApi.lookupByMarketNo(o.product_id)
        if (res.found && res.original_link) {
          window.open(res.original_link, '_blank')
          return
        }
      } catch { /* ignore */ }
    }
    // 4. 상품명에서 소싱처 상품번호 추출 → URL 구성
    const sourcingUrls: Record<string, string> = {
      MUSINSA: 'https://www.musinsa.com/products/',
      KREAM: 'https://kream.co.kr/products/',
      FashionPlus: 'https://www.fashionplus.co.kr/goods/detail/',
      ABCmart: 'https://www.a-rt.com/product?prdtNo=',
      Nike: 'https://www.nike.com/kr/t/',
    }
    const name = o.product_name || ''
    // 상품명 끝에 숫자가 있으면 소싱처 상품번호로 추정
    const idMatch = name.match(/\b(\d{6,})\s*$/)
    if (idMatch && o.source_site && sourcingUrls[o.source_site]) {
      window.open(sourcingUrls[o.source_site] + idMatch[1], '_blank')
      return
    }
    // source_site 없어도 상품명 패턴으로 소싱처 추론
    if (idMatch) {
      const id = idMatch[1]
      if (name.includes('운동화') || name.includes('나이키') || name.includes('아디다스')) {
        window.open('https://www.fashionplus.co.kr/goods/detail/' + id, '_blank')
        return
      }
      window.open('https://www.musinsa.com/products/' + id, '_blank')
      return
    }
    showAlert('소싱처 원문링크 정보가 없습니다', 'info')
  }
  const handleMarketLink = (o: SambaOrder) => {
    const acc = accounts.find(a => a.id === o.channel_id)
    const marketType = acc?.market_type || ''
    const sellerId = acc?.seller_id || ''
    const storeSlug = (acc?.additional_fields as Record<string, string> | undefined)?.storeSlug || ''
    const productNo = o.product_id || ''

    // 마켓 상품번호 → 구매페이지 직접 이동
    const urlMap: Record<string, string> = {
      smartstore: `https://smartstore.naver.com/${storeSlug || sellerId}/products/${productNo}`,
      coupang: `https://www.coupang.com/vp/products/${productNo}`,
      '11st': `https://www.11st.co.kr/products/${productNo}`,
      gmarket: `https://item.gmarket.co.kr/Item?goodscode=${productNo}`,
      auction: `https://itempage3.auction.co.kr/DetailView.aspx?ItemNo=${productNo}`,
      ssg: `https://www.ssg.com/item/itemView.ssg?itemId=${productNo}`,
      lotteon: `https://www.lotteon.com/p/product/${productNo}`,
      kream: `https://kream.co.kr/products/${productNo}`,
      ebay: `https://www.ebay.com/itm/${productNo}`,
    }

    if (productNo) {
      // 플레이오토: source_site에서 실제 판매처 추출 → 해당 마켓 URL 사용
      if (marketType === 'playauto' && o.source_site) {
        const site = o.source_site.split('(')[0]
        const siteUrlMap: Record<string, (no: string) => string> = {
          'GS이숍': (no) => `https://www.gsshop.com/prd/prd.gs?prdid=${no}`,
          'G마켓': (no) => `https://item.gmarket.co.kr/Item?goodscode=${no}`,
          '옥션': (no) => `https://itempage3.auction.co.kr/DetailView.aspx?ItemNo=${no}`,
          '11번가': (no) => `https://www.11st.co.kr/products/${no}`,
          '스마트스토어': (no) => `https://smartstore.naver.com/search?q=${encodeURIComponent(no)}`,
          '쿠팡': (no) => `https://www.coupang.com/vp/products/${no}`,
          'SSG': (no) => `https://www.ssg.com/item/itemView.ssg?itemId=${no}`,
          '롯데ON': (no) => `https://www.lotteon.com/p/product/${no}`,
          '롯데온': (no) => `https://www.lotteon.com/p/product/${no}`,
          '롯데홈쇼핑': (no) => `https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=${no}`,
          '롯데아이몰': (no) => `https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=${no}`,
          '홈앤쇼핑': (no) => `https://www.hmall.com/p/pda/itemPtc.do?slitmCd=${no}`,
          'HMALL': (no) => `https://www.hmall.com/p/pda/itemPtc.do?slitmCd=${no}`,
        }
        const builder = siteUrlMap[site]
        if (builder) {
          // GS이숍만 ProdCode에 사이트코드(3자리) 포함 → 뒤 3자리 제거, 나머지는 전체번호 유지
          const cleanNo = site === 'GS이숍' && productNo.length > 3
            ? productNo.slice(0, -3)
            : productNo
          window.open(builder(cleanNo), '_blank'); return
        }
      }

      const url = urlMap[marketType]
      if (url) { window.open(url, '_blank'); return }
    }

    // fallback: 상품명으로 검색
    const searchMap: Record<string, string> = {
      smartstore: `https://search.shopping.naver.com/search/all?query=`,
      coupang: `https://www.coupang.com/np/search?q=`,
      '11st': `https://search.11st.co.kr/Search.tmall?kwd=`,
      ssg: `https://www.ssg.com/search.ssg?query=`,
    }
    const searchBase = searchMap[marketType]
    if (searchBase) {
      window.open(searchBase + encodeURIComponent(o.product_name || ''), '_blank')
    } else if (o.product_name) {
      window.open(`https://search.shopping.naver.com/search/all?query=${encodeURIComponent(o.product_name)}`, '_blank')
    } else {
      showAlert('판매마켓 링크를 생성할 수 없습니다', 'error')
    }
  }

  // 미등록 입력 모달 열기
  const openUrlModal = (orderId: string) => {
    const target = orders.find(o => o.id === orderId)
    setUrlModalOrderId(orderId)
    setUrlModalInput(target?.source_url || '')
    setUrlModalImageInput(target?.product_image || '')
    setShowUrlModal(true)
  }

  // 미등록 입력 URL 저장
  const handleUrlSubmit = async () => {
    if (!urlModalInput.trim() && !urlModalImageInput.trim()) {
      showAlert('URL을 입력해주세요', 'error')
      return
    }
    setUrlModalSaving(true)
    try {
      const url = urlModalInput.trim()
      const imgUrl = urlModalImageInput.trim()
      await orderApi.update(urlModalOrderId, {
        ...(url ? { source_url: url } : {}),
        ...(imgUrl ? { product_image: imgUrl } : {}),
      })
      setShowUrlModal(false)
      setUrlModalInput('')
      setUrlModalImageInput('')
      loadOrders()
      showAlert('미등록 상품 정보가 등록되었습니다', 'success')
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '저장 실패', 'error')
    }
    setUrlModalSaving(false)
  }

  // 이미지 클릭 → 마켓 상품 페이지 또는 이미지 URL로 이동
  const handleImageClick = (o: SambaOrder) => {
    // product_id가 URL이면 해당 페이지로 이동
    if (o.product_id && o.product_id.startsWith('http')) {
      window.open(o.product_id, '_blank')
      return
    }
    // 마켓 상품번호가 있으면 마켓 상품 페이지로 이동
    if (o.product_id && o.channel_id) {
      handleMarketLink(o)
      return
    }
    // 이미지 URL이 있으면 이미지 열기
    if (o.product_image && o.product_image.startsWith('http')) {
      window.open(o.product_image, '_blank')
    }
  }

  // 가격X/재고X/직배/까대기/선물 토글 (서버 저장)
  const toggleAction = async (orderId: string, actionKey: string) => {
    const newVal = activeActions[orderId] === actionKey ? null : actionKey
    setActiveActions(prev => ({ ...prev, [orderId]: newVal }))
    try {
      await orderApi.update(orderId, { action_tag: newVal || '' })
    } catch { /* ignore */ }
  }

  // 기간 필터 계산
  const getPeriodStart = (key: string): Date | null => {
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    switch (key) {
      case 'today': return now
      case 'yesterday': { const d = new Date(now); d.setDate(d.getDate() - 1); return d }
      case 'thisweek': { const d = new Date(now); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d }
      case 'lastweek': { const d = new Date(now); d.setDate(d.getDate() - ((d.getDay() + 6) % 7) - 7); return d }
      case '1week': { const d = new Date(now); d.setDate(d.getDate() - 6); return d }
      case '1month': { const d = new Date(now); d.setDate(d.getDate() - 29); return d }
      case 'thismonth': return new Date(now.getFullYear(), now.getMonth(), 1)
      case 'lastmonth': return new Date(now.getFullYear(), now.getMonth() - 1, 1)
      case 'thisyear': return new Date(now.getFullYear(), 0, 1)
      default: return null
    }
  }

  // 기간 종료일 계산 (지난주/지난달/어제는 해당 기간 마지막 날)
  const getPeriodEnd = (key: string): Date => {
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    switch (key) {
      case 'yesterday': { const d = new Date(now); d.setDate(d.getDate() - 1); return d }
      case 'lastweek': { const d = new Date(now); d.setDate(d.getDate() - ((d.getDay() + 6) % 7) - 1); return d }
      case 'lastmonth': return new Date(now.getFullYear(), now.getMonth(), 0)
      default: return now
    }
  }

  // 필터링된 주문 목록
  const filteredOrders = useMemo(() => orders.filter(o => {
    // 상품별 모드에서는 날짜 필터 건너뜀 (전체 이력 표시)
    if (!isProductMode) {
      const orderDate = new Date(o.paid_at || o.created_at)
      // 시작일 필터 — API 호출과 동일하게 customStart 기준
      if (customStart) {
        const start = new Date(customStart)
        start.setHours(0, 0, 0, 0)
        if (orderDate < start) return false
      }
      // 종료일 필터
      if (customEnd) {
        const end = new Date(customEnd)
        end.setHours(23, 59, 59, 999)
        if (orderDate > end) return false
      }
    }
    if (marketFilter) {
      if (marketFilter.startsWith('acc:')) {
        // 개별 계정 필터
        if (o.channel_id !== marketFilter.slice(4)) return false
      } else if (marketFilter.startsWith('type:')) {
        // 마켓 유형 필터
        const mtype = marketFilter.slice(5)
        const acc = accounts.find(a => a.id === o.channel_id)
        if (acc) {
          if (acc.market_type !== mtype) return false
        } else {
          const marketName = accounts.find(a => a.market_type === mtype)?.market_name || mtype
          if (!o.channel_name?.includes(marketName)) return false
        }
      }
    }
    if (siteFilter) {
      if (o.source_site !== siteFilter) return false
    }
    if (accountFilter) {
      if (o.sourcing_account_id !== accountFilter) return false
    }
    if (marketStatus) {
      if (o.shipping_status !== marketStatus) return false
    }
    if (statusFilter) {
      if (statusFilter === 'active') {
        if (!['new_order', 'invoice_printed', 'pending', 'wait_ship', 'arrived'].includes(o.status)) return false
        const ss = o.shipping_status || ''
        if (['취소중', '취소요청', '취소완료', '취소처리중', '반품요청', '반품완료', '교환요청', '교환완료'].includes(ss)) return false
      } else if (statusFilter === 'pending') {
        if (!['pending', 'new_order', 'invoice_printed'].includes(o.status)) return false
      } else if (o.status !== statusFilter) return false
    }
    if (inputFilter) {
      const action = activeActions[o.id]
      switch (inputFilter) {
        case 'has_order': if (!o.order_number) return false; break
        case 'no_order': if (o.order_number) return false; break
        case 'direct': if (action !== 'direct') return false; break
        case 'kkadaegi': if (action !== 'kkadaegi') return false; break
        case 'gift': if (action !== 'gift') return false; break
      }
    }
    if (searchText) {
      const q = searchText.toLowerCase()
      if (searchCategory === 'customer' && !o.customer_name?.toLowerCase().includes(q)) return false
      if (searchCategory === 'product' && !o.product_name?.toLowerCase().includes(q)) return false
      if (searchCategory === 'product_id' && !o.product_id?.toLowerCase().includes(q)) return false
      if (searchCategory === 'order_number' && !o.order_number?.toLowerCase().includes(q)) return false
    }
    return true
  }).sort((a, b) => {
    const getTime = (o: SambaOrder) => o.paid_at ? new Date(o.paid_at).getTime() : new Date(o.created_at).getTime()
    switch (sortBy) {
      case 'date_asc':    return getTime(a) - getTime(b)
      case 'profit_desc': return (b.profit || 0) - (a.profit || 0)
      case 'profit_asc':  return (a.profit || 0) - (b.profit || 0)
      case 'price_desc':  return (b.sale_price || 0) - (a.sale_price || 0)
      case 'price_asc':   return (a.sale_price || 0) - (b.sale_price || 0)
      default:            return getTime(b) - getTime(a) // date_desc
    }
  }), [orders, customStart, customEnd, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, inputFilter, activeActions, searchText, searchCategory, accounts, sortBy, isProductMode])

  // 현재 페이지 주문 ID 목록
  const currentPageIds = useMemo(() =>
    filteredOrders.slice((currentPage - 1) * pageSize, currentPage * pageSize).map(o => o.id),
    [filteredOrders, currentPage, pageSize])

  // 전체 선택/해제
  const toggleSelectAll = () => {
    if (currentPageIds.every(id => selectedIds.has(id))) {
      setSelectedIds(prev => { const next = new Set(prev); currentPageIds.forEach(id => next.delete(id)); return next })
    } else {
      setSelectedIds(prev => { const next = new Set(prev); currentPageIds.forEach(id => next.add(id)); return next })
    }
  }

  // 일괄 처리 (상태변경 / 발주확인 / 취소승인 / 삭제)
  const handleBulkAction = async () => {
    if (!bulkStatus || selectedIds.size === 0) return
    if (bulkStatus === 'delete') {
      const confirmed = await showConfirm(`선택된 ${fmtNum(selectedIds.size)}건을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)
      if (!confirmed) return
    }
    setBulkUpdating(true)
    let ok = 0
    for (const id of selectedIds) {
      try {
        if (bulkStatus === 'delete') {
          await orderApi.delete(id)
        } else if (bulkStatus === 'confirm') {
          await orderApi.confirmOrder(id)
        } else if (bulkStatus === 'approve_cancel') {
          await orderApi.approveCancel(id)
        } else {
          await orderApi.update(id, { status: bulkStatus })
        }
        ok++
      } catch { /* ignore */ }
    }
    const actionLabel =
      bulkStatus === 'delete'         ? '삭제' :
      bulkStatus === 'confirm'        ? '발주확인' :
      bulkStatus === 'approve_cancel' ? '취소승인' :
      `상태변경→${bulkStatus}`
    setLogMessages(prev => [...prev, `[완료] 일괄 ${actionLabel}: ${fmtNum(ok)}/${fmtNum(selectedIds.size)}건`])
    setSelectedIds(new Set())
    setBulkStatus('')
    setBulkUpdating(false)
    await loadOrders()
  }

  // 문자열 입력 → 숫자 콤마 포맷 (편집 중 입력값용)
  const fmtNumStr = (v: string) => {
    const num = v.replace(/[^\d]/g, '')
    return num ? Number(num).toLocaleString() : ''
  }

  const pendingCount = filteredOrders.filter(o => o.status === 'pending').length

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 취소/반품/교환 요청 경고 — 클릭 전 사라지지 않는 모달 */}
      {notifications.length > 0 && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: '#1A1A1A', border: '2px solid #FF4444', borderRadius: '16px', padding: '2rem', maxWidth: '420px', width: '90%', boxShadow: '0 8px 32px rgba(255,68,68,0.3)' }}>
            <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
              <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>&#9888;</div>
              <h3 style={{ fontSize: '1.25rem', fontWeight: 700, color: '#FF6B6B', marginBottom: '0.5rem' }}>주문 취소요청 감지</h3>
            </div>
            {notifications.map(n => (
              <div key={n.id} style={{ background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '0.75rem', color: '#FF6B6B', fontSize: '0.9375rem', fontWeight: 600 }}>
                {n.message}
              </div>
            ))}
            <button
              onClick={() => {
                setNotifications([])
                setStatusFilter('')
                setMarketStatus('취소요청')
                setCustomStart('2020-01-01')
                setCustomEnd(new Date().toLocaleDateString('sv-SE'))
                setPeriod('')
              }}
              style={{ width: '100%', padding: '0.75rem', background: '#FF4444', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '1rem', fontWeight: 700, cursor: 'pointer', marginTop: '0.5rem' }}
            >
              취소요청 확인하기
            </button>
          </div>
        </div>
      )}

      {/* 스피너 제거 CSS */}
      <style>{`
        input[type=number]::-webkit-outer-spin-button,
        input[type=number]::-webkit-inner-spin-button {
          -webkit-appearance: none;
          margin: 0;
        }
        input[type=number] {
          -moz-appearance: textfield;
          appearance: textfield;
        }
      `}</style>

      {/* 관련 페이지 연결 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.25rem' }}>
        <a href="/samba/returns" style={{ fontSize: '0.75rem', color: '#FF8C00', textDecoration: 'none' }}>반품교환 →</a>
        <a href="/samba/cs" style={{ fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none' }}>CS →</a>
      </div>
      {/* 상품별 주문이력 모드 배너 */}
      {isProductMode && (
        <div style={{
          background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.25)',
          borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '0.75rem',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.85rem', color: '#FF8C00', fontWeight: 600 }}>상품별 판매이력</span>
            <span style={{ fontSize: '0.85rem', color: '#E5E5E5', fontWeight: 500, maxWidth: '400px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {cpName || cpId}
            </span>
            <span style={{ fontSize: '0.75rem', color: '#888' }}>({fmtNum(filteredOrders.length)}건)</span>
          </div>
          <a href='/samba/orders' style={{
            fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none',
            padding: '4px 10px', border: '1px solid rgba(76,154,255,0.3)',
            borderRadius: '5px', background: 'rgba(76,154,255,0.08)', whiteSpace: 'nowrap',
          }}>전체 주문 보기 →</a>
        </div>
      )}
      {/* 헤더 */}
      <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>{isProductMode ? '상품 판매이력' : '주문 상황'}</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>
            미배송: <span style={{ color: '#FF6B6B', fontWeight: 700 }}>{fmtNum(pendingCount)}</span>건 / 전체: <span style={{ fontWeight: 700 }}>{fmtNum(filteredOrders.length)}</span>건
          </p>
        </div>
        {smsRemain && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(76,154,255,0.08)', border: '1px solid rgba(76,154,255,0.2)', borderRadius: '8px' }}>
            <span style={{ fontSize: '0.8125rem', color: '#4C9AFF', fontWeight: 600 }}>SMS 잔여</span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
              SMS <span style={{ color: '#51CF66', fontWeight: 700 }}>{smsRemain.SMS_CNT?.toLocaleString()}</span>건
            </span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
              LMS <span style={{ color: '#FFB84D', fontWeight: 700 }}>{smsRemain.LMS_CNT?.toLocaleString()}</span>건
            </span>
            <span style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>
              MMS <span style={{ color: '#CC5DE8', fontWeight: 700 }}>{smsRemain.MMS_CNT?.toLocaleString()}</span>건
            </span>
          </div>
        )}
      </div>

      {/* 주문 로그 */}
      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>주문 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 로그가 초기화되었습니다.'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={el => { if (el) el.scrollTop = el.scrollHeight }} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{msg}</p>)}
        </div>
      </div>

      {/* 기간 필터 바 — 상품별 모드에서는 숨김 */}
      {!isProductMode && <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap', alignItems: 'center' }}>
          {PERIOD_BUTTONS.map(pb => (
            <button key={pb.key} onClick={() => {
              if (dateLocked) return
              setPeriod(pb.key)
              if (!startLocked) {
                const start = getPeriodStart(pb.key)
                setCustomStart(start ? start.toLocaleDateString('sv-SE') : '')
              }
              setCustomEnd(getPeriodEnd(pb.key).toLocaleDateString('sv-SE'))
            }}
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? 'rgba(80,80,80,0.8)' : 'rgba(50,50,50,0.8)', border: period === pb.key ? '1px solid #666' : '1px solid #3D3D3D', color: period === pb.key ? '#fff' : '#C5C5C5', cursor: dateLocked ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', opacity: dateLocked && period !== pb.key ? 0.5 : 1 }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 4px' }} />
          <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)}
            style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: '#C0392B', color: '#FF8C00' } : {}) }} />
          <button
            onClick={() => setStartLocked(prev => !prev)}
            style={{
              padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap',
              background: startLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)',
              border: startLocked ? '1px solid #C0392B' : '1px solid #3D3D3D',
              color: startLocked ? '#fff' : '#C5C5C5',
            }}
          >고정</button>
          <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
          <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)}
            style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <button
            onClick={() => setDateLocked(prev => !prev)}
            style={{
              padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap',
              background: dateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)',
              border: dateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D',
              color: dateLocked ? '#fff' : '#C5C5C5',
            }}
          >고정</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '200px' }}>
            <option value="">전체마켓보기</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
              const items: { value: string; label: string; isGroup: boolean }[] = []
              marketTypes.forEach(([type, name]) => {
                items.push({ value: `type:${type}`, label: name, isGroup: true })
                accounts.filter(a => a.market_type === type).forEach(a => {
                  const label = `  ${name} ${a.business_name || ''} ${a.seller_id || ''}`.trim()
                  items.push({ value: a.id, label, isGroup: false })
                })
              })
              return items.map(item => (
                <option key={item.value} value={item.value} style={{ fontWeight: item.isGroup ? 600 : 400 }}>{item.label}</option>
              ))
            })()}
          </select>
          <button onClick={handleFetch} disabled={syncing} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: syncing ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{syncing ? '동기화 중...' : '가져오기'}</button>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '110px' }}>
            <option value="">일괄 작업 선택</option>
            <optgroup label="상태 변경">
              <option value="pending">→ 주문접수</option>
              <option value="wait_ship">→ 배송대기</option>
              <option value="arrived">→ 사무실도착</option>
              <option value="shipped">→ 출고완료</option>
              <option value="delivered">→ 배송완료</option>
              <option value="cancelled">→ 취소완료</option>
            </optgroup>
            <optgroup label="주문 처리">
              <option value="confirm">발주확인</option>
              <option value="approve_cancel">취소승인</option>
              <option value="delete">삭제 ⚠️</option>
            </optgroup>
          </select>
          <button onClick={handleBulkAction} disabled={bulkUpdating || !bulkStatus || selectedIds.size === 0} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: selectedIds.size > 0 && bulkStatus ? (bulkStatus === 'delete' ? '#7B2D00' : '#C0392B') : 'rgba(50,50,50,0.9)', border: `1px solid ${selectedIds.size > 0 && bulkStatus === 'delete' ? '#A83200' : '#3D3D3D'}`, color: selectedIds.size > 0 && bulkStatus ? '#fff' : '#666', borderRadius: '4px', cursor: bulkUpdating || !bulkStatus || selectedIds.size === 0 ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{bulkUpdating ? '처리 중...' : `실행 (${fmtNum(selectedIds.size)}건)`}</button>
        </div>
      </div>}

      {/* 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <span style={{ fontSize: '0.72rem', color: '#aaa', whiteSpace: 'nowrap', marginRight: '4px' }}>
          <span style={{ color: '#FF8C00', fontWeight: 600 }}>{filteredOrders.length.toLocaleString()}</span>건 / ₩<span style={{ color: '#FF8C00', fontWeight: 600 }}>{filteredOrders.reduce((s, o) => s + (o.sale_price || 0), 0).toLocaleString()}</span>
        </span>
        <select style={{ ...inputStyle, width: '80px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">상품</option>
          <option value="customer">고객</option>
          <option value="product_id">상품번호</option>
          <option value="order_number">주문번호</option>
        </select>
        <input style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadOrders() }} />
        <button style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체마켓보기</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
              const items: { value: string; label: string; isGroup: boolean }[] = []
              marketTypes.forEach(([type, name]) => {
                items.push({ value: `type:${type}`, label: name, isGroup: true })
                accounts.filter(a => a.market_type === type).forEach(a => {
                  const label = `${name} ${a.business_name || ''} ${a.seller_id || ''}`.trim()
                  items.push({ value: `acc:${a.id}`, label: `  ${label}`, isGroup: false })
                })
              })
              return items.map(item => (
                <option key={item.value} value={item.value} style={{ fontWeight: item.isGroup ? 600 : 400 }}>{item.label}</option>
              ))
            })()}
          </select>
          <select style={{ ...inputStyle, width: '110px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}><option value="">전체사이트보기</option>{['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','REXMONDE','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}</select>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
            <option value="">주문계정</option>
            {(() => {
              const allSites = [...new Set(sourcingAccounts.map(sa => sa.site_name))]
              return allSites.sort().map(site => (
                <optgroup key={site} label={site}>
                  {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                    <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                  ))}
                </optgroup>
              ))
            })()}
          </select>
          <select style={{ ...inputStyle, width: '112px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">마켓상태 보기</option>
            {MARKET_STATUS_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '118px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="">입력값</option>
            <option value="has_order">주문번호입력</option>
            <option value="no_order">주문번호 미입력</option>
            <option value="direct">직배</option>
            <option value="kkadaegi">까대기</option>
            <option value="gift">선물</option>
          </select>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="active">접수/대기/사무실</option>
            <option value="">전체 주문상태</option>
            {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k} style={k === 'ship_failed' ? { color: '#FF3232' } : {}}>{v.label}</option>)}
          </select>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }}>
            <option value="date_desc">주문일자↓</option>
            <option value="date_asc">주문일자↑</option>
            <option value="profit_desc">수익↓</option>
            <option value="profit_asc">수익↑</option>
            <option value="price_desc">판매가↓</option>
            <option value="price_asc">판매가↑</option>
          </select>
          <select style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={20}>20개 보기</option><option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
          </select>
        </div>
      </div>

      {/* 주문 테이블 */}
      <div style={{ border: '1px solid #2D2D2D', borderRadius: '8px', overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: '1100px', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#0D1117', borderBottom: '2px solid #1C2333' }}>
              <th style={{ width: '36px', padding: '0.5rem', textAlign: 'center', borderRight: '1px solid #1C2333' }}>
                <input type="checkbox" checked={currentPageIds.length > 0 && currentPageIds.every(id => selectedIds.has(id))} onChange={toggleSelectAll} style={{ accentColor: '#F59E0B', width: '13px', height: '13px', cursor: 'pointer' }} />
              </th>
              <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: '#94A3B8', borderRight: '1px solid #1C2333' }}>주문정보</th>
              <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: '#94A3B8', borderRight: '1px solid #1C2333', width: '143px' }}>금액</th>
              <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: '#94A3B8', width: '460px' }}>주문상태</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</td></tr>
            ) : filteredOrders.length === 0 ? (
              <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>주문이 없습니다</td></tr>
            ) : filteredOrders.slice((currentPage - 1) * pageSize, currentPage * pageSize).map((o, index) => {
              const costDisplay = editingCosts[o.id] !== undefined ? fmtNumStr(editingCosts[o.id]) : (o.cost ? o.cost.toLocaleString() : '')
              const shipFeeDisplay = editingShipFees[o.id] !== undefined ? fmtNumStr(editingShipFees[o.id]) : (o.shipping_fee ? o.shipping_fee.toLocaleString() : '')
              const liveProfit = calcProfit(o)
              const liveProfitRate = calcProfitRate(o)
              const activeAction = activeActions[o.id] || null

              return (
                <tr key={o.id} style={{ borderBottom: '1px solid #1C2333', verticalAlign: 'top' }}>
                  {/* 체크박스 */}
                  <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', borderRight: '1px solid #1C2333' }}>
                    <div style={{ fontSize: '0.65rem', color: '#FFFFFF', fontWeight: 'bold', marginBottom: '2px' }}>{(currentPage - 1) * pageSize + index + 1}</div>
                    <input type="checkbox" checked={selectedIds.has(o.id)} onChange={() => setSelectedIds(prev => { const next = new Set(prev); next.has(o.id) ? next.delete(o.id) : next.add(o.id); return next })} style={{ accentColor: '#F59E0B', cursor: 'pointer' }} />
                  </td>
                  {/* 주문정보 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8125rem', position: 'relative' }}>
                    {/* 우측 상단: 주문일 + 수량 + 삭제 */}
                    <div style={{ position: 'absolute', top: '0.75rem', right: '0.75rem', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.25rem' }}>
                      {o.paid_at && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{ fontSize: '0.72rem', color: '#fff', fontWeight: 700 }}>{fmtDate(o.paid_at, '.')}</span>
                        </div>
                      )}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontSize: '0.72rem', color: '#555' }}>{fmtDate(o.created_at, '.')}</span>
                        <button onClick={() => handleDelete(o.id)} style={{ padding: '0.125rem 0.5rem', fontSize: '0.7rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}>삭제</button>
                      </div>
                      <span style={{ fontSize: o.quantity > 1 ? '2.25rem' : '0.95rem', fontWeight: 700, color: o.quantity > 1 ? '#F5A623' : '#888' }}>수량: <span style={{ color: o.quantity > 1 ? '#F5A623' : '#E5E5E5' }}>{o.quantity.toLocaleString()}</span></span>
                    </div>

                    {/* 상품 이미지 (100x100) + 마켓/주문번호 */}
                    <div style={{ display: 'flex', gap: '0.625rem', marginBottom: '0.5rem' }}>
                      {o.product_image ? (
                        <img
                          src={o.product_image}
                          alt=""
                          onClick={() => handleImageClick(o)}
                          style={{ width: '100px', height: '100px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', flexShrink: 0, cursor: 'pointer' }}
                        />
                      ) : (
                        <div
                          onClick={() => handleImageClick(o)}
                          style={{ width: '100px', height: '100px', background: '#1A1A1A', borderRadius: '6px', border: '1px solid #2D2D2D', display: 'flex', alignItems: 'center', justifyContent: 'center', color: o.product_id?.startsWith('http') ? '#4C9AFF' : '#444', fontSize: '0.75rem', flexShrink: 0, cursor: o.product_id?.startsWith('http') ? 'pointer' : 'default', textDecoration: o.product_id?.startsWith('http') ? 'underline' : 'none' }}
                        >{o.product_id?.startsWith('http') ? '링크이동' : 'No IMG'}</div>
                      )}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', flexWrap: 'wrap' }}>
                          <span style={{ fontSize: '0.75rem', color: '#B0B0B0', background: '#1A1A1A', padding: '0.125rem 0.5rem', borderRadius: '4px' }}>{o.channel_name || '마켓'}</span>
                          {o.source_site && <span style={{ fontSize: '0.75rem', color: '#B0B0B0', background: '#1A1A1A', padding: '0.125rem 0.5rem', borderRadius: '4px', border: '1px solid #2D2D2D' }}>{(() => {
                            const m = o.source_site.match(/^(.+)\(([^)]+)\)$/)
                            if (m && siteAliasMap[m[2]]) return `${m[1]}(${siteAliasMap[m[2]]})`
                            return o.source_site
                          })()}</span>}
                          <button onClick={() => handleCopyOrderNumber(o.order_number)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>주문번호복사</button>
                          <button onClick={() => openMsgModal('sms', o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>SMS</button>
                          <button onClick={() => openMsgModal('kakao', o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>KAKAO</button>
                        </div>
                        {/* 상품주문번호 + 주문번호 같은 행 */}
                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.25rem', fontSize: '0.75rem' }}>
                          <div><span style={{ color: '#666' }}>상품주문번호 </span><span style={{ fontFamily: 'monospace', color: '#E5E5E5' }}>{o.order_number}</span></div>
                          {o.shipment_id && (
                            <div><span style={{ color: '#666' }}>주문번호 </span><span style={{ fontFamily: 'monospace', color: '#B0B0B0' }}>{o.shipment_id}</span></div>
                          )}
                        </div>
                        {/* 상품명 + 옵션 */}
                        <div style={{ minWidth: 0 }}>
                          <span style={{ color: '#C5C5C5', fontSize: '0.8125rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}>{o.product_name || '-'}</span>
                          {o.product_option && (
                            <span style={{ color: '#B0B0B0', fontSize: '0.75rem', display: 'block', marginTop: '0.125rem' }}>[옵션] {o.product_option}</span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* 쿠팡노출 */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginBottom: '0.375rem' }}>
                      <span style={{ color: '#666', fontSize: '0.7rem', whiteSpace: 'nowrap' }}>쿠팡노출</span>
                      <input
                        type="text"
                        placeholder="쿠팡노출상품명"
                        defaultValue={o.coupang_display_name || ''}
                        onBlur={async (e) => {
                          const val = e.target.value.trim()
                          if (val === (o.coupang_display_name ?? '')) return
                          try {
                            await orderApi.update(o.id, { coupang_display_name: val || undefined })
                            loadOrders()
                          } catch (err) { showAlert(err instanceof Error ? err.message : '저장 실패', 'error') }
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        style={{ flex: 1, fontSize: '0.75rem', padding: '0.125rem 0.375rem', background: '#1A1A1A', border: '1px solid #444', color: '#E5E5E5', borderRadius: '4px', minWidth: 0 }}
                      />
                    </div>

                    {/* 업데이트 로그 */}
                    {refreshLog[o.id] && (
                      <div style={{ fontSize: '0.72rem', color: '#8A95B0', padding: '0.25rem 0', marginBottom: '0.25rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {refreshLog[o.id]}
                      </div>
                    )}
                    {/* 버튼 */}
                    <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                      <button onClick={() => handleDanawa(o.product_name || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>다나와</button>
                      <button onClick={() => handleNaver(o.product_name || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>네이버</button>
                      <button onClick={async () => {
                        // 1순위: collected_product_id 직접 참조 (근본적 해결)
                        if (o.collected_product_id) {
                          window.open(`/samba/products?search=${encodeURIComponent(o.collected_product_id)}&search_type=id&highlight=${o.collected_product_id}`, '_blank')
                          return
                        }
                        // 2순위: 마켓 상품번호로 lookup (+ 지연 채움)
                        const _openAndLink = (cpId: string) => {
                          window.open(`/samba/products?search=${encodeURIComponent(cpId)}&search_type=id&highlight=${cpId}`, '_blank')
                          orderApi.linkProduct(o.id, cpId).catch(() => {})
                        }
                        if (o.product_id) {
                          try {
                            const res = await collectorApi.lookupByMarketNo(o.product_id)
                            if (res.found && res.id) { _openAndLink(res.id); return }
                          } catch { /* ignore */ }
                        }
                        // 3순위: 상품명 끝 숫자(소싱 상품번호)
                        const _spidMatch = (o.product_name || '').match(/\b(\d{6,})\s*$/)
                        if (_spidMatch) {
                          try {
                            const res = await collectorApi.lookupByMarketNo(_spidMatch[1])
                            if (res.found && res.id) { _openAndLink(res.id); return }
                          } catch { /* ignore */ }
                        }
                        // 4순위: 영문+숫자 조합 상품코드 (IQ2245 068 → IQ2245068)
                        const _codeMatch = (o.product_name || '').match(/\b([A-Za-z]{1,5}\d{2,})[\s-]+(\d{2,4})\s*$/)
                        if (_codeMatch) {
                          try {
                            const res = await collectorApi.lookupByMarketNo(`${_codeMatch[1]}${_codeMatch[2]}`)
                            if (res.found && res.id) { _openAndLink(res.id); return }
                          } catch { /* ignore */ }
                        }
                        // 5순위: 상품명으로 수집상품 검색 (market_names 포함)
                        if (o.product_name) {
                          try {
                            const _scrollRes = await collectorApi.scrollProducts({ search: o.product_name, search_type: 'name', limit: 1 })
                            if (_scrollRes.items?.length > 0 && _scrollRes.total === 1) { _openAndLink(_scrollRes.items[0].id); return }
                          } catch { /* ignore */ }
                          window.open(`/samba/products?search=${encodeURIComponent(o.product_name)}`, '_blank')
                        } else {
                          showAlert('상품 정보가 없습니다', 'info')
                        }
                      }} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>상품정보</button>
                      <button onClick={async () => {
                        if (!o.product_id) { showAlert('상품 정보가 없습니다', 'info'); return }
                        try {
                          const lookup = await collectorApi.lookupByMarketNo(o.product_id)
                          if (!lookup.found || !lookup.id) { showAlert('수집상품을 찾을 수 없습니다', 'info'); return }
                          setPriceHistoryProduct({ name: o.product_name || '', source_site: o.source_site || '' })
                          setPriceHistoryData([])
                          setPriceHistoryModal(true)
                          const history = await collectorApi.getPriceHistory(lookup.id)
                          setPriceHistoryData(history || [])
                        } catch { showAlert('가격이력 조회 실패', 'error') }
                      }} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>가격변경이력</button>
                      <button onClick={() => handleSourceLink(o)} style={{ fontSize: '0.6875rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>원문링크</button>
                      <button onClick={() => handleMarketLink(o)} style={{ fontSize: '0.6875rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>판매링크</button>
                      <button onClick={() => openUrlModal(o.id)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>미등록 입력</button>
                      <button onClick={() => handleTracking(o.shipping_company || '', o.tracking_number || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>배송조회</button>
                      <button onClick={async () => {
                        const ts = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                        setRefreshLog(prev => ({ ...prev, [o.id]: `[${ts}] 가격재고 갱신 중...` }))
                        // 마켓상품번호 → 수집상품 ID 역추적
                        let cpId = ''
                        if (o.collected_product_id) {
                          cpId = o.collected_product_id
                        } else if (o.product_id) {
                          try {
                            const lookup = await collectorApi.lookupByMarketNo(o.product_id)
                            if (lookup.found && lookup.id) cpId = lookup.id
                          } catch { /* ignore */ }
                        }
                        if (!cpId) {
                          const idMatch = (o.product_name || '').match(/\b(\d{6,})\s*$/)
                          if (idMatch) {
                            try {
                              const lookup = await collectorApi.lookupByMarketNo(idMatch[1])
                              if (lookup.found && lookup.id) cpId = lookup.id
                            } catch { /* ignore */ }
                          }
                        }
                        if (!cpId) {
                          setRefreshLog(prev => ({ ...prev, [o.id]: `[${ts}] 수집상품을 찾을 수 없습니다` }))
                          return
                        }
                        try {
                          const res = await collectorApi.refresh([cpId])
                          const detail = res.details?.[0]
                          const logMsg = detail
                            ? `${detail.name?.slice(0, 25)} → ${detail.detail}`
                            : res.changed > 0 ? '변동 감지' : '변동 없음'
                          const ts2 = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                          setRefreshLog(prev => ({ ...prev, [o.id]: `[${ts2}] ${logMsg}` }))
                        } catch (e) {
                          setRefreshLog(prev => ({ ...prev, [o.id]: `[${ts}] 갱신 실패: ${e instanceof Error ? e.message : ''}` }))
                        }
                      }} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>업데이트</button>
                      <button onClick={() => showAlert('마켓상품삭제 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>마켓상품삭제</button>
                      <button onClick={() => {
                        if (o.ext_order_number) { window.open(o.ext_order_number, '_blank'); return }
                        const srcNo = o.sourcing_order_number || ''
                        if (!srcNo) { showAlert('소싱 주문번호가 없습니다', 'info'); return }
                        const orderUrlMap: Record<string, string> = {
                          MUSINSA: `https://www.musinsa.com/order/order-detail/${srcNo}`,
                          KREAM: `https://kream.co.kr/my/purchasing/${srcNo}`,
                          FashionPlus: `https://www.fashionplus.co.kr/mypage/order/detail/${srcNo}`,
                          ABCmart: `https://www.a-rt.com/mypage/order-detail/${srcNo}`,
                          Nike: `https://www.nike.com/kr/orders/${srcNo}`,
                        }
                        const url = orderUrlMap[o.source_site || '']
                        if (!url) { showAlert(`${o.source_site || '알수없는'} 소싱처는 원주문링크를 지원하지 않습니다`, 'info'); return }
                        window.open(url, '_blank')
                      }} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#B0B0B0', cursor: 'pointer' }}>원주문링크</button>
                    </div>

                    {/* 주문자/수령인/연락처/주소 한 줄 */}
                    <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.8rem', flexWrap: 'wrap' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666' }}>주문자</span>
                        <span style={{ color: '#E5E5E5' }}>{o.customer_name || '-'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666' }}>수령인</span>
                        <span style={{ color: '#E5E5E5' }}>{o.customer_name || '-'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666' }}>연락처</span>
                        <span style={{ color: '#888' }}>{o.customer_phone || '-'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666' }}>주소</span>
                        <span style={{ color: '#888' }}>{o.customer_address || '-'}</span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
                      <span style={{ color: '#666', whiteSpace: 'nowrap' }}>타마켓주문링크</span>
                      <input
                        type="text"
                        placeholder="타마켓 주문링크 URL"
                        defaultValue={o.ext_order_number || ''}
                        onBlur={async (e) => {
                          const val = e.target.value.trim()
                          if (val === (o.ext_order_number ?? '')) return
                          try {
                            await orderApi.update(o.id, { ext_order_number: val || undefined })
                            loadOrders()
                          } catch (err) { showAlert(err instanceof Error ? err.message : '저장 실패', 'error') }
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        style={{ flex: 1, fontSize: '0.75rem', padding: '0.125rem 0.375rem', background: '#1A1A1A', border: '1px solid #444', color: '#E5E5E5', borderRadius: '4px', fontFamily: 'monospace', minWidth: 0 }}
                      />
                    </div>
                  </td>
                  {/* 금액 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>결제</span><span>{o.sale_price.toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>정산</span><span>{Math.round(o.revenue).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>실수익</span><span>{liveProfit >= 0 ? '+' : ''}{Math.round(liveProfit).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>수익률</span><span style={{ color: '#888' }}>{liveProfitRate}%</span></div>
                    </div>
                    {/* 주문취소 + 가격X/재고X/직배/까대기/선물 */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginTop: '0.375rem', borderTop: '1px solid #1C2333', paddingTop: '0.375rem' }}>
                      <button
                        onClick={async () => {
                          const isPlayauto = (o.source === 'playauto' || o.channel_name?.toLowerCase().includes('플레이오토'))
                          const confirmMsg = isPlayauto ? '주문확인 처리하시겠습니까?' : '주문을 취소하시겠습니까?'
                          const yes = await showConfirm(confirmMsg)
                          if (!yes) return
                          try {
                            const res = await orderApi.sellerCancel(o.id, 'SOLD_OUT')
                            showAlert(res.message || '처리 완료', 'success')
                            loadOrders()
                          } catch (err) {
                            showAlert(err instanceof Error ? err.message : '처리 실패', 'error')
                          }
                        }}
                        style={{
                          fontSize: '0.68rem', padding: '0.125rem 0',
                          background: 'rgba(220,38,38,0.8)',
                          color: '#fff', border: '1px solid #DC2626',
                          borderRadius: '4px', cursor: 'pointer', textAlign: 'center',
                          fontWeight: 600,
                        }}
                      >주문취소</button>
                      {ACTION_BUTTONS.map(btn => {
                        const isActive = activeAction === btn.key
                        return (
                          <button
                            key={btn.key}
                            onClick={() => toggleAction(o.id, btn.key)}
                            style={{
                              fontSize: '0.68rem', padding: '0.125rem 0',
                              background: isActive ? btn.activeColor : 'rgba(80,80,80,0.5)',
                              color: '#fff', border: isActive ? `1px solid ${btn.activeColor}` : '1px solid #555',
                              borderRadius: '4px', cursor: 'pointer', textAlign: 'center',
                            }}
                          >{btn.label}</button>
                        )
                      })}
                    </div>
                  </td>
                  {/* 주문상태 */}
                  <td style={{ padding: '0.625rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                      {/* 1행: 상태 드롭박스 + 주문번호 인풋 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                        <select value={o.status} onChange={e => handleStatusChange(o.id, e.target.value)}
                          style={{
                            ...inputStyle,
                            flex: 1,
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                            color: o.status === 'ship_failed' ? '#FF3232' : inputStyle.color,
                          }}
                        >
                          {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k} style={k === 'ship_failed' ? { color: '#FF3232' } : {}}>{v.label}</option>)}
                        </select>
                        <input
                          type="text"
                          placeholder="소싱주문번호"
                          value={editingOrderNumbers[o.id] ?? o.sourcing_order_number ?? ''}
                          onChange={e => setEditingOrderNumbers(prev => ({ ...prev, [o.id]: e.target.value }))}
                          onBlur={async (e) => {
                            const val = e.target.value.trim()
                            setEditingOrderNumbers(prev => { const n = { ...prev }; delete n[o.id]; return n })
                            if (val === (o.sourcing_order_number ?? '')) return
                            try {
                              await orderApi.update(o.id, { sourcing_order_number: val })
                              loadOrders()
                            } catch (err) { showAlert(err instanceof Error ? err.message : '소싱주문번호 저장 실패', 'error') }
                          }}
                          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.75rem' }}
                        />
                      </div>

                      {/* 2행: 주문계정 + 마켓상태 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                        <select
                          value={o.sourcing_account_id || ''}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await orderApi.update(o.id, { sourcing_account_id: val || undefined } as Partial<SambaOrder>)
                              loadOrders()
                            } catch { /* ignore */ }
                          }}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}
                        >
                          <option value="">주문계정</option>
                          {(() => {
                            const allSites = [...new Set(sourcingAccounts.map(sa => sa.site_name))]
                            const siteOrder: Record<string, number> = { MUSINSA: 0, LOTTEON: 1, SSG: 2 }
                            const sites = allSites.sort((a, b) => (siteOrder[a] ?? 99) - (siteOrder[b] ?? 99) || a.localeCompare(b))
                            return sites.map(site => (
                              <optgroup key={site} label={site}>
                                {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                                  <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                                ))}
                              </optgroup>
                            ))
                          })()}
                        </select>
                        <div style={{
                          flex: 1, padding: '0.25rem 0.375rem',
                          background: 'rgba(30,30,30,0.6)', border: '1px solid #2D2D2D', borderRadius: '6px',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                        }}>
                          <span style={{ fontSize: '0.75rem', color: '#4C9AFF', fontWeight: 600 }}>{o.shipping_status || '-'}</span>
                        </div>
                      </div>

                      {/* 3행: 원가 + 배송비 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                        <input
                          type="text"
                          style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', textAlign: 'right' }}
                          value={costDisplay}
                          placeholder="실구매가"
                          onChange={e => {
                            const raw = e.target.value.replace(/[^\d]/g, '')
                            setEditingCosts(prev => ({ ...prev, [o.id]: raw }))
                          }}
                          onBlur={() => handleCostSave(o.id)}
                          onKeyDown={e => { if (e.key === 'Enter') handleCostSave(o.id) }}
                        />
                        <input
                          type="text"
                          style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', textAlign: 'right' }}
                          value={shipFeeDisplay}
                          placeholder="배송비"
                          onChange={e => {
                            const raw = e.target.value.replace(/[^\d]/g, '')
                            setEditingShipFees(prev => ({ ...prev, [o.id]: raw }))
                          }}
                          onBlur={() => handleShipFeeSave(o.id)}
                          onKeyDown={e => { if (e.key === 'Enter') handleShipFeeSave(o.id) }}
                        />
                      </div>

                      {/* 택배사 + 송장번호 + 전송 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                        <select
                          key={`${o.id}-${o.shipping_company}-${o.status}`}
                          id={`ship-co-${o.id}`}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                          defaultValue={o.shipping_company || ''}
                          onChange={async e => {
                            const co = e.target.value
                            const tn = (document.getElementById(`ship-tn-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                            const alreadyShipped = o.shipping_status === '송장전송완료'
                            if (co && tn && alreadyShipped) {
                              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                              try { await orderApi.update(o.id, { shipping_company: co, tracking_number: tn }) } catch { /* ignore */ }
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 수정 저장완료 (${co} ${tn}) — 스마트스토어는 송장수정 API를 지원하지 않습니다. 판매자센터에서 직접 수정해주세요.`])
                              loadOrders()
                            } else if (co && tn) {
                              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 중... (${co} ${tn})`])
                              try {
                                const res = await orderApi.shipOrder(o.id, co, tn)
                                if (!res.market_sent) {
                                  await orderApi.updateStatus(o.id, 'ship_failed')
                                  setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                                } else {
                                  setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                                }
                                loadOrders()
                              } catch (err) {
                                await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 실패`])
                                loadOrders()
                              }
                            } else if (co) {
                              try { await orderApi.update(o.id, { shipping_company: co }) } catch { /* ignore */ }
                            }
                          }}
                        >
                          <option value="">택배사</option>
                          {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
                        </select>
                        <input
                          id={`ship-tn-${o.id}`}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                          value={editingTrackings[o.id] ?? o.tracking_number ?? ''}
                          placeholder="송장번호"
                          onChange={e => setEditingTrackings(prev => ({ ...prev, [o.id]: e.target.value }))}
                          onBlur={async e => {
                            const tn = e.target.value.trim()
                            const co = (document.getElementById(`ship-co-${o.id}`) as HTMLSelectElement)?.value || ''
                            const changed = tn !== (o.tracking_number || '')
                            const retry = o.status === 'ship_failed'
                            const alreadyShipped = o.shipping_status === '송장전송완료'
                            if (co && tn && changed && alreadyShipped) {
                              // 이미 발송된 주문 — DB만 저장, 마켓 수정은 판매자센터에서
                              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                              try { await orderApi.update(o.id, { shipping_company: co, tracking_number: tn }) } catch { /* ignore */ }
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 수정 저장완료 (${co} ${tn}) — 스마트스토어는 송장수정 API를 지원하지 않습니다. 판매자센터에서 직접 수정해주세요.`])
                              loadOrders()
                            } else if (co && tn && (changed || retry)) {
                              const ts = () => new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 중... (${co} ${tn})`])
                              try {
                                const res = await orderApi.shipOrder(o.id, co, tn)
                                if (!res.market_sent) {
                                  await orderApi.updateStatus(o.id, 'ship_failed')
                                  setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                                } else {
                                  setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                                }
                                loadOrders()
                              } catch (err) {
                                await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 실패`])
                                loadOrders()
                              }
                            } else if (tn && tn !== (o.tracking_number || '')) {
                              try { await orderApi.update(o.id, { tracking_number: tn }) } catch { /* ignore */ }
                            }
                          }}
                          onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        />
                      </div>

                      {/* 간단메모 */}
                      <textarea
                        style={{ ...inputStyle, fontSize: '0.72rem', resize: 'none', height: '5.38rem', lineHeight: '1.4' }}
                        placeholder="간단메모"
                        defaultValue={o.notes || ''}
                        onBlur={async e => {
                          const val = e.target.value.trim()
                          if (val !== (o.notes || '')) {
                            try { await orderApi.update(o.id, { notes: val }) } catch { /* ignore */ }
                          }
                        }}
                      />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 페이지네이션 */}
      {(() => {
        const totalPages = Math.max(1, Math.ceil(filteredOrders.length / pageSize))
        const pages: (number | string)[] = []
        if (totalPages <= 7) {
          for (let i = 1; i <= totalPages; i++) pages.push(i)
        } else {
          pages.push(1)
          if (currentPage > 3) pages.push('...')
          for (let i = Math.max(2, currentPage - 1); i <= Math.min(totalPages - 1, currentPage + 1); i++) pages.push(i)
          if (currentPage < totalPages - 2) pages.push('...')
          pages.push(totalPages)
        }
        const pgBtn = (active: boolean) => ({
          background: active ? '#FF8C00' : 'rgba(30,30,30,0.9)',
          color: active ? '#fff' : '#aaa',
          border: active ? 'none' : '1px solid #333',
          borderRadius: '6px',
          padding: '0.3rem 0.6rem',
          fontSize: '0.75rem',
          cursor: 'pointer' as const,
          minWidth: '32px',
          fontWeight: active ? 600 : 400,
        })
        return (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 0.5rem', borderTop: '1px solid #232323', marginTop: '0.5rem' }}>
            {/* 좌측: 건수 정보 */}
            <span style={{ fontSize: '0.75rem', color: '#888', whiteSpace: 'nowrap' }}>
              총 <span style={{ color: '#FF8C00', fontWeight: 600 }}>{fmtNum(filteredOrders.length)}</span>건
              {filteredOrders.length > pageSize && <> · {fmtNum(currentPage)}/{fmtNum(totalPages)}페이지</>}
            </span>
            {/* 중앙: 페이지 버튼 */}
            {totalPages > 1 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <button style={pgBtn(false)} disabled={currentPage === 1} onClick={() => setCurrentPage(1)}>«</button>
                <button style={pgBtn(false)} disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>‹</button>
                {pages.map((p, i) =>
                  typeof p === 'string'
                    ? <span key={`dot-${i}`} style={{ color: '#555', padding: '0 4px' }}>…</span>
                    : <button key={p} style={pgBtn(p === currentPage)} onClick={() => setCurrentPage(p as number)}>{p}</button>
                )}
                <button style={pgBtn(false)} disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>›</button>
                <button style={pgBtn(false)} disabled={currentPage === totalPages} onClick={() => setCurrentPage(totalPages)}>»</button>
              </div>
            )}
            <div />
          </div>
        )
      })()}

      {/* 주문 수정 모달 */}
      {showForm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '640px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700 }}>{editingId ? '주문 수정' : '주문 추가'}</h3>
              <button onClick={() => { setShowForm(false); setEditingId(null) }} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
              {[
                { key: 'product_name', label: '상품명', type: 'text' },
                { key: 'customer_name', label: '고객명', type: 'text' },
                { key: 'customer_phone', label: '전화번호', type: 'text' },
                { key: 'customer_address', label: '배송주소', type: 'text' },
                { key: 'sale_price', label: '판매가', type: 'number' },
                { key: 'cost', label: '원가', type: 'number' },
                { key: 'fee_rate', label: '수수료율(%)', type: 'number' },
                { key: 'tracking_number', label: '운송장번호', type: 'text' },
                { key: 'notes', label: '메모', type: 'text' },
              ].map(f => (
                <div key={f.key}>
                  <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>{f.label}</label>
                  <input type={f.type} style={{ ...inputStyle, width: '100%', padding: '0.5rem 0.75rem' }}
                    value={String(form[f.key as keyof OrderForm])}
                    onChange={e => setForm({ ...form, [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value })} />
                </div>
              ))}
              <div>
                <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>배송사</label>
                <select style={{ ...inputStyle, width: '100%', padding: '0.5rem 0.75rem' }} value={form.shipping_company} onChange={e => setForm({ ...form, shipping_company: e.target.value })}>
                  <option value="">선택</option>
                  {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => { setShowForm(false); setEditingId(null) }} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleSubmit} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>저장</button>
            </div>
          </div>
        </div>
      )}

      {/* 미등록 입력 URL 모달 */}
      {showUrlModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '520px', maxWidth: '90vw' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700 }}>상품 URL 등록</h3>
              <button onClick={() => setShowUrlModal(false)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>
            <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1rem' }}>
              소싱처 상품 URL과 이미지 URL을 입력하면 주문정보에 표시됩니다.
              <br />향후 동일 상품 주문에도 자동 적용됩니다.
            </p>
            <div style={{ marginBottom: '0.5rem' }}>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.25rem', display: 'block' }}>상품 URL (원문링크)</label>
              <input
                type="text"
                placeholder="https://www.musinsa.com/app/goods/12345"
                style={{ ...inputStyle, width: '100%', padding: '0.625rem 0.75rem', fontSize: '0.875rem' }}
                value={urlModalInput}
                onChange={e => setUrlModalInput(e.target.value)}
                autoFocus
              />
            </div>
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.25rem', display: 'block' }}>이미지 URL</label>
              <input
                type="text"
                placeholder="https://image.musinsa.com/images/goods_img/..."
                style={{ ...inputStyle, width: '100%', padding: '0.625rem 0.75rem', fontSize: '0.875rem' }}
                value={urlModalImageInput}
                onChange={e => setUrlModalImageInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleUrlSubmit() }}
              />
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowUrlModal(false)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleUrlSubmit} disabled={urlModalSaving} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: urlModalSaving ? 'not-allowed' : 'pointer' }}>
                {urlModalSaving ? '저장중...' : '등록'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 가격/재고 이력 모달 — 상품관리 ProductCard와 100% 동일 */}
      {priceHistoryModal && (() => {
        const history = priceHistoryData
        const isKream = priceHistoryProduct.source_site === 'KREAM'
        const costPrices = history.map(h => Number(h.cost || h.sale_price || 0)).filter(Boolean)
        const currentPrice = costPrices[0] || 0
        const minPrice = costPrices.length ? Math.min(...costPrices) : 0
        const maxPrice = costPrices.length ? Math.max(...costPrices) : 0
        const minEntry = history.find(h => Number(h.cost || h.sale_price || 0) === minPrice)
        const maxEntry = history.find(h => Number(h.cost || h.sale_price || 0) === maxPrice)
        const kreamFastMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_fast_min as number || 0 : 0
        const kreamGeneralMin = isKream && history[0] ? (history[0] as Record<string, unknown>).kream_general_min as number || 0 : 0
        const fmtHistDate = (d: string) => new Date(d).toLocaleString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        const fmtShortDate = (d: string) => new Date(d).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })

        if (history.length === 0 && priceHistoryModal) {
          return (
            <div style={{ position: 'fixed', inset: 0, zIndex: 99998, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.6)' }}
              onClick={() => setPriceHistoryModal(false)}>
              <div style={{ background: '#1A1A1A', borderRadius: '10px', padding: '2rem', color: '#888', fontSize: '0.85rem' }}>이력 로딩 중...</div>
            </div>
          )
        }

        return (
          <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => setPriceHistoryModal(false)}>
            <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', width: 'min(700px, 95vw)', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
              onClick={e => e.stopPropagation()}>
              {/* 헤더 */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px', borderBottom: '1px solid #2D2D2D' }}>
                <h3 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5' }}>가격 / 재고 이력</h3>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontSize: '0.75rem', color: '#666' }}>{history.length}건 기록</span>
                  <button onClick={() => setPriceHistoryModal(false)} style={{ background: 'transparent', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer' }}>✕</button>
                </div>
              </div>
              {/* 상품 정보 + 요약 */}
              <div style={{ padding: '12px 20px', borderBottom: '1px solid #2D2D2D' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                  <span style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: '3px', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', fontWeight: 600 }}>{priceHistoryProduct.source_site}</span>
                  <span style={{ fontSize: '0.75rem', color: '#999' }}>{priceHistoryProduct.name}</span>
                </div>
                {costPrices.length > 0 && (
                  <div style={{ display: 'flex', gap: '20px', fontSize: '0.78rem', flexWrap: 'wrap' }}>
                    {isKream && kreamFastMin > 0 && (
                      <div><span style={{ color: '#666' }}>빠른배송 </span><span style={{ color: '#FF8C00', fontWeight: 600 }}>₩ {kreamFastMin.toLocaleString()}</span></div>
                    )}
                    {isKream && kreamGeneralMin > 0 && (
                      <div><span style={{ color: '#666' }}>일반배송 </span><span style={{ color: '#E5E5E5', fontWeight: 600 }}>₩ {kreamGeneralMin.toLocaleString()}</span></div>
                    )}
                    {!isKream && (
                      <div><span style={{ color: '#666' }}>현재가 </span><span style={{ color: '#E5E5E5', fontWeight: 600 }}>₩ {currentPrice.toLocaleString()}</span></div>
                    )}
                    <div><span style={{ color: '#666' }}>최저가 </span><span style={{ color: '#51CF66', fontWeight: 600 }}>₩ {minPrice.toLocaleString()}</span>{minEntry && <span style={{ color: '#555', fontSize: '0.68rem' }}> ({fmtShortDate(String(minEntry.date))})</span>}</div>
                    <div><span style={{ color: '#666' }}>최고가 </span><span style={{ color: '#FF6B6B', fontWeight: 600 }}>₩ {maxPrice.toLocaleString()}</span>{maxEntry && <span style={{ color: '#555', fontSize: '0.68rem' }}> ({fmtShortDate(String(maxEntry.date))})</span>}</div>
                  </div>
                )}
              </div>
              {/* 이력 테이블 */}
              <div style={{ overflowY: 'auto', padding: '0' }}>
                {history.length === 0 ? (
                  <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
                    가격 변동 이력 없음<br />
                    <span style={{ fontSize: '0.75rem', color: '#444' }}>업데이트 시 이력이 기록됩니다</span>
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                        <th style={{ padding: '8px 16px', textAlign: 'left', color: '#888', fontWeight: 500 }}>날짜</th>
                        {isKream ? (
                          <>
                            <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>빠른배송(₩)</th>
                            <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>일반배송(₩)</th>
                          </>
                        ) : (
                          <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>원가(₩)</th>
                        )}
                        <th style={{ padding: '8px 16px', textAlign: 'right', color: '#888', fontWeight: 500 }}>재고(수량/O/X)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h, i) => {
                        const opts = (h.options || []) as Array<{ name?: string; price?: number; stock?: number; isSoldOut?: boolean }>
                        return (
                          <React.Fragment key={i}>
                            <tr style={{ borderTop: i > 0 ? '1px solid #2D2D2D' : 'none', background: 'rgba(255,255,255,0.02)' }}>
                              <td style={{ padding: '8px 16px', color: '#C5C5C5', fontWeight: 600, fontSize: '0.78rem' }}>{fmtHistDate(String(h.date))}</td>
                              {isKream ? (
                                <>
                                  <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FF8C00', fontWeight: 600 }}>
                                    {(h as Record<string, unknown>).kream_fast_min ? `₩ ${((h as Record<string, unknown>).kream_fast_min as number).toLocaleString()}` : '-'}
                                  </td>
                                  <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                                    {(h as Record<string, unknown>).kream_general_min ? `₩ ${((h as Record<string, unknown>).kream_general_min as number).toLocaleString()}` : '-'}
                                  </td>
                                </>
                              ) : (
                                <td style={{ padding: '8px 16px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                                  ₩ {((h.cost || h.sale_price) as number)?.toLocaleString() || '-'}
                                </td>
                              )}
                              <td style={{ padding: '8px 16px', textAlign: 'right', color: '#888' }}>
                                {opts.length > 0 ? `${opts.length}개 옵션` : '-'}
                              </td>
                            </tr>
                            {opts.map((opt, oi) => {
                              const kOpt = opt as Record<string, unknown>
                              const soldOut = opt.isSoldOut || (opt.stock !== undefined && opt.stock <= 0)
                              const stockLabel = soldOut ? '품절' : opt.stock !== undefined ? `${opt.stock.toLocaleString()}개` : 'O'
                              return (
                                <tr key={oi} style={{ borderTop: '1px solid #1A1A1A' }}>
                                  <td style={{ padding: '4px 16px 4px 32px', color: '#666', fontSize: '0.73rem' }}>ㄴ {opt.name || `옵션${oi + 1}`}</td>
                                  {isKream ? (
                                    <>
                                      <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                                        {(kOpt.kreamFastPrice as number) > 0 ? `₩ ${(kOpt.kreamFastPrice as number).toLocaleString()}` : '-'}
                                      </td>
                                      <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                                        {(kOpt.kreamGeneralPrice as number) > 0 ? `₩ ${(kOpt.kreamGeneralPrice as number).toLocaleString()}` : '-'}
                                      </td>
                                    </>
                                  ) : (
                                    <td style={{ padding: '4px 16px', textAlign: 'right', color: '#888', fontSize: '0.73rem' }}>
                                      ₩ {((h.cost || h.sale_price) as number)?.toLocaleString()}
                                    </td>
                                  )}
                                  <td style={{ padding: '4px 16px', textAlign: 'right', fontSize: '0.73rem', fontWeight: 600, color: soldOut ? '#FF6B6B' : '#51CF66' }}>
                                    {stockLabel}
                                  </td>
                                </tr>
                              )
                            })}
                          </React.Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {/* SMS/카카오 발송 모달 */}
      {msgModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '720px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>
                {msgModal.type === 'sms' ? 'SMS 발송' : '카카오톡 발송'}
              </h3>
              <button onClick={() => setMsgModal(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>

            {/* 주문 정보 */}
            <div style={{ background: '#111', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.8125rem' }}>
              <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '0.375rem' }}>
                <div><span style={{ color: '#666' }}>수신자: </span><span style={{ color: '#E5E5E5' }}>{msgModal.order.customer_name || '-'}</span></div>
                <div><span style={{ color: '#666' }}>전화번호: </span><span style={{ color: '#E5E5E5' }}>{msgModal.order.customer_phone}</span></div>
              </div>
              <div>
                <span style={{ color: '#666' }}>상품: </span>
                <span style={{ color: '#aaa' }}>{msgModal.order.product_name || '-'}</span>
              </div>
            </div>

            {/* 빠른 템플릿 카드 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '0.75rem' }}>
              {[
                { label: '주문취소안내', msg: '{{marketName}} 주문취소안내\n주문상품 : {{goodsName}}\n\n안녕하세요, {{rvcName}} 고객님.\n\n해당 상품이 일시적으로 시스템 오류로 노출되어 주문이 접수된 것으로 확인되었습니다.\n\n불편을 드려 정말 죄송합니다.\n\n빠른 환불 처리를 위해 "단순취소" 사유로 주문취소 해주시면 확인 후 바로 환불도와드리겠습니다.\n\n불편을 드려 진심으로 죄송하며, 더 나은 서비스로 보답드리겠습니다. 감사합니다.' },
                { label: '가격변동 취소', msg: '{{marketName}} 가격변동 안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님\n\n해당 제품 공급처에서 가격을 변동하여 안내드립니다.\n취소 후 재주문 부탁드립니다.' },
                { label: '국내상품 발주안내', msg: '{{marketName}} 주문상품 발주 완료\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님^^ 발주 완료되었습니다. 배송완료까지 영업일기준 2~3일정도 소요됩니다.' },
                { label: '반품비', msg: '{{marketName}} 반품비 안내\n상품명 : {{goodsName}}\n\n반품비 안내드립니다.\n교환비용 8,000원 발생(고객변심)하므로 따로 개별 문자 안내드리겠습니다.' },
                { label: '반품안내문자', msg: '{{marketName}} 반품 안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님\n반품신청으로 무자안내드립니다.\n교환 접수시 회수기사님 방문2-3일내 이루어지며 회수된 상품 해당부서로 이동하여 검수진행과정 진행됩니다.' },
                { label: '발주 후 품절', msg: '{{marketName}} 품절안내\n주문상품 : {{goodsName}}\n\n안녕하세요 {{rvcName}} 고객님. 저희가 해당 제품 발주를 넣었는데 공급처에서 품절이라고 연락이 왔습니다.\n취소 처리 도와드리겠습니다.' },
              ].map(t => (
                <div
                  key={t.label}
                  onClick={() => setMsgText(t.msg)}
                  style={{ background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.625rem', cursor: 'pointer', transition: 'border-color 0.15s' }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = '#FF8C00')}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = '#2D2D2D')}
                >
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '0.375rem' }}>{t.label}</div>
                  <div style={{ fontSize: '0.625rem', color: '#777', lineHeight: '1.4', maxHeight: '3.5rem', overflow: 'hidden', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{t.msg.slice(0, 80)}...</div>
                </div>
              ))}
            </div>

            {/* 변수 태그 버튼 */}
            <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
              {MSG_VARIABLE_TAGS.map(v => (
                <button
                  key={v.tag}
                  type="button"
                  onClick={() => insertMsgTag(v.tag)}
                  style={{ padding: '0.2rem 0.5rem', fontSize: '0.6875rem', background: '#1A1A1A', border: '1px solid #444', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
                >{v.tag} <span style={{ color: '#888' }}>{v.label}</span></button>
              ))}
            </div>

            {/* 메시지 입력 */}
            <textarea
              ref={msgTextRef}
              value={msgText}
              onChange={e => setMsgText(e.target.value)}
              placeholder="메시지를 입력하세요"
              rows={5}
              style={{ width: '100%', padding: '0.625rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem', outline: 'none', resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', boxSizing: 'border-box' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.5rem', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.75rem', color: '#555' }}>
                {msgText.length > 0 ? `${new TextEncoder().encode(msgText).length}바이트` : ''}
                {msgText.length > 0 && new TextEncoder().encode(msgText).length > 90 ? ' (LMS)' : ''}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setMsgModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button
                onClick={handleSendMsg}
                disabled={msgSending}
                style={{
                  padding: '0.625rem 1.25rem',
                  background: msgModal.type === 'sms' ? '#51CF66' : '#FFD93D',
                  border: 'none', borderRadius: '8px',
                  color: msgModal.type === 'sms' ? '#fff' : '#1A1A1A',
                  fontSize: '0.875rem', fontWeight: 600,
                  cursor: msgSending ? 'not-allowed' : 'pointer',
                  opacity: msgSending ? 0.6 : 1,
                }}
              >
                {msgSending ? '발송중...' : msgModal.type === 'sms' ? 'SMS 발송' : '카카오 발송'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 취소 알림 설정 모달 */}
      {showAlarmSetting && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '400px', maxWidth: '90vw' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>취소 알림 설정</h3>
              <button onClick={() => setShowAlarmSetting(false)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>

            {/* 수집 주기 */}
            <div style={{ marginBottom: '1.25rem' }}>
              <label style={{ fontSize: '0.8125rem', color: '#888', display: 'block', marginBottom: '0.5rem' }}>취소주문 수집 주기</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="number" min="0" max="23"
                  value={alarmHour}
                  onChange={e => setAlarmHour(e.target.value)}
                  style={{ width: '60px', padding: '0.4rem 0.5rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', fontSize: '0.875rem', textAlign: 'center', outline: 'none' }}
                />
                <span style={{ color: '#888', fontSize: '0.8125rem' }}>시간</span>
                <input
                  type="number" min="0" max="59"
                  value={alarmMin}
                  onChange={e => setAlarmMin(e.target.value)}
                  style={{ width: '60px', padding: '0.4rem 0.5rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', fontSize: '0.875rem', textAlign: 'center', outline: 'none' }}
                />
                <span style={{ color: '#888', fontSize: '0.8125rem' }}>분</span>
              </div>
            </div>

            {/* 수면타임 */}
            <div style={{ marginBottom: '1.5rem' }}>
              <label style={{ fontSize: '0.8125rem', color: '#888', display: 'block', marginBottom: '0.5rem' }}>수면타임</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#666', fontSize: '0.8125rem' }}>시작</span>
                <input
                  type="time"
                  value={sleepStart}
                  onChange={e => setSleepStart(e.target.value)}
                  style={{ padding: '0.4rem 0.5rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', fontSize: '0.875rem', outline: 'none' }}
                />
                <span style={{ color: '#555', fontSize: '0.875rem' }}>~</span>
                <span style={{ color: '#666', fontSize: '0.8125rem' }}>종료</span>
                <input
                  type="time"
                  value={sleepEnd}
                  onChange={e => setSleepEnd(e.target.value)}
                  style={{ padding: '0.4rem 0.5rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '6px', color: '#E5E5E5', fontSize: '0.875rem', outline: 'none' }}
                />
              </div>
              <p style={{ fontSize: '0.72rem', color: '#555', marginTop: '0.375rem' }}>수면타임 동안은 취소주문 수집을 하지 않습니다</p>
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowAlarmSetting(false)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button
                onClick={() => {
                  showAlert(`수집 주기: ${alarmHour}시간 ${alarmMin}분 / 수면타임: ${sleepStart} ~ ${sleepEnd} 저장완료`, 'success')
                  setShowAlarmSetting(false)
                }}
                style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
              >저장</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

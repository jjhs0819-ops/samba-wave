'use client'

import { useEffect, useState, useCallback } from 'react'
import { orderApi, channelApi, accountApi, proxyApi, type SambaOrder, type SambaChannel, type SambaMarketAccount } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending:    { label: '주문접수', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  wait_ship:  { label: '배송대기중', bg: 'rgba(100,149,237,0.15)', text: '#6495ED' },
  arrived:    { label: '사무실도착', bg: 'rgba(72,209,204,0.15)', text: '#48D1CC' },
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

const SHIPPING_COMPANIES = ['CJ대한통운', '한진택배', '롯데택배', '로젠택배', '우체국택배', '경동택배', '합동택배', '기타']

const PERIOD_BUTTONS = [
  { key: 'today', label: '오늘' },
  { key: '1week', label: '1주일' },
  { key: '15days', label: '15일' },
  { key: '1month', label: '1개월' },
  { key: '3months', label: '3개월' },
  { key: '6months', label: '6개월' },
  { key: 'thisyear', label: '올해' },
  { key: 'all', label: '전체' },
]

const MARKET_STATUS_OPTIONS = ['일반', '송장전송완료', '송장전송실패', '교환요청', '취소요청', '반품요청', '배송완료']

// 택배사별 배송조회 URL
const TRACKING_URLS: Record<string, string> = {
  'CJ대한통운': 'https://trace.cjlogistics.com/next/tracking.html?wblNo=',
  '한진택배': 'https://www.hanjin.com/kor/CMS/DeliveryMgr/WaybillResult.do?mession=&searchType=General&wblnumText2=',
  '롯데택배': 'https://www.lotteglogis.com/home/reservation/tracking/link498?InvNo=',
  '로젠택배': 'https://www.ilogen.com/web/personal/trace/',
  '우체국택배': 'https://service.epost.go.kr/trace.RetrieveDomRi498.postal?sid1=',
  '경동택배': 'https://kdexp.com/deliverySearch?barcode=',
}

const inputStyle = {
  padding: '0.28rem 0.4rem',
  fontSize: '0.8125rem',
  background: '#1E1E1E',
  border: '1px solid #3D3D3D',
  borderRadius: '4px',
  color: '#C5C5C5',
  outline: 'none',
  boxSizing: 'border-box' as const,
}

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
  { key: 'direct', label: '직배', activeColor: '#2563EB' },
  { key: 'kkadaegi', label: '까대기', activeColor: '#D97706' },
  { key: 'gift', label: '선물', activeColor: '#059669' },
] as const

export default function OrdersPage() {
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [channels, setChannels] = useState<SambaChannel[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('thisyear')
  const [marketFilter, setMarketFilter] = useState('')
  const [marketStatus, setMarketStatus] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [inputFilter, setInputFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [searchText, setSearchText] = useState('')
  const [pageSize, setPageSize] = useState(50)
  const [logMessages, setLogMessages] = useState<string[]>(['[대기] 주문 가져오기 결과가 여기에 표시됩니다...'])
  const [smsRemain, setSmsRemain] = useState<{ SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncAccountId, setSyncAccountId] = useState('')
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })
  // 인라인 원가/배송비 수정용 상태
  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  // 직배/까대기/선물 토글 상태
  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  // 미등록 입력 모달
  // 우측상단 알람
  const [notifications, setNotifications] = useState<{id: number, message: string, type: string}[]>([])

  const showNotification = (message: string, type: string = 'warning') => {
    const id = Date.now()
    setNotifications(prev => [...prev, { id, message, type }])
  }

  const [showUrlModal, setShowUrlModal] = useState(false)
  const [urlModalOrderId, setUrlModalOrderId] = useState('')
  const [urlModalInput, setUrlModalInput] = useState('')
  const [urlModalSaving, setUrlModalSaving] = useState(false)
  // SMS/카카오 발송 모달
  const [msgModal, setMsgModal] = useState<{ type: 'sms' | 'kakao'; order: SambaOrder } | null>(null)
  const [msgText, setMsgText] = useState('')
  const [msgSending, setMsgSending] = useState(false)
  // 검색 카테고리
  const [searchCategory, setSearchCategory] = useState('customer')
  // 일자 고정
  const [dateLocked, setDateLocked] = useState(false)
  const [customStart, setCustomStart] = useState('')
  const [startLocked, setStartLocked] = useState(false)
  const [customEnd, setCustomEnd] = useState('')

  const loadOrders = useCallback(async () => {
    setLoading(true)
    try {
      setOrders(await orderApi.list(0, pageSize))
    } catch { /* ignore */ }
    setLoading(false)
  }, [pageSize])

  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => { channelApi.list().then(setChannels).catch(() => {}) }, [])
  useEffect(() => { accountApi.listActive().then(setAccounts).catch(() => {}) }, [])
  useEffect(() => {
    proxyApi.aligoRemain().then(r => { if (r.success) setSmsRemain(r) }).catch(() => {})
  }, [])

  const handleFetch = async () => {
    if (!syncAccountId) {
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 주문 목록 새로고침...`])
      await loadOrders()
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 완료`])
      return
    }
    setSyncing(true)
    const ts = () => new Date().toLocaleTimeString()
    const acc = accounts.find(a => a.id === syncAccountId)
    const label = acc ? `${acc.market_name}(${acc.seller_id || '-'})` : syncAccountId
    const daysMap: Record<string, number> = {
      today: 1, '1week': 7, '15days': 15, '1month': 30,
      '3months': 90, '6months': 180, thisyear: 365, all: 365,
    }
    const days = daysMap[period] || 7
    setLogMessages(prev => [...prev, `[${ts()}] ${label} 주문 가져오기 시작 (최근 ${days}일)...`])
    try {
      const res = await orderApi.syncFromMarkets(days, syncAccountId)
      for (const r of res.results) {
        if (r.status === 'success') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.fetched}건 조회, ${r.synced}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${(r as Record<string, unknown>).confirmed}건 발주확인` : ''}`])
        } else if (r.status === 'skip') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
        } else {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 완료 — ${res.total_synced}건 신규 저장`])
      // 취소요청 알람
      let totalCancelRequested = 0
      for (const r of res.results) {
        totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
      }
      if (totalCancelRequested > 0) {
        showNotification(`취소/반품/교환 요청 ${totalCancelRequested}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${ts()}] 오류: ${e}`])
    }
    setSyncing(false)
  }

  const handleSyncFromMarkets = async () => {
    setSyncing(true)
    const ts = () => new Date().toLocaleTimeString()
    const daysMap: Record<string, number> = {
      today: 1, '1week': 7, '15days': 15, '1month': 30,
      '3months': 90, '6months': 180, thisyear: 365, all: 365,
    }
    const days = daysMap[period] || 7
    setLogMessages(prev => [...prev, `[${ts()}] 전체마켓 주문 동기화 시작 (최근 ${days}일)...`])

    try {
      const res = await orderApi.syncFromMarkets(days)
      for (const r of res.results) {
        if (r.status === 'success') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.fetched}건 조회, ${r.synced}건 신규 저장${(r as Record<string, unknown>).confirmed ? `, ${(r as Record<string, unknown>).confirmed}건 발주확인` : ''}`])
        } else if (r.status === 'skip') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${r.message}`])
        } else {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 동기화 완료 — 총 ${res.total_synced}건 신규 저장`])
      // 취소요청 알람
      let totalCancelRequested = 0
      for (const r of res.results) {
        totalCancelRequested += ((r as Record<string, unknown>).cancel_requested as number) || 0
      }
      if (totalCancelRequested > 0) {
        showNotification(`취소/반품/교환 요청 ${totalCancelRequested}건이 감지되었습니다. 확인이 필요합니다.`)
      }
      await loadOrders()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${ts()}] 동기화 오류: ${e}`])
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
  const handleSourceLink = (o: SambaOrder) => {
    if (!o.source_site || !o.product_id) {
      showAlert('소싱처 정보가 없습니다', 'error')
      return
    }
    const siteUrls: Record<string, string> = {
      MUSINSA: `https://www.musinsa.com/app/goods/${o.product_id}`,
      Nike: `https://www.nike.com/kr/t/${o.product_id}`,
      ABCmart: `https://abcmart.a-rt.com/product/detail?goodsId=${o.product_id}`,
    }
    const url = siteUrls[o.source_site]
    if (url) window.open(url, '_blank')
    else showAlert(`${o.source_site} 원문링크 미지원`, 'error')
  }
  const handleMarketLink = (o: SambaOrder) => {
    const acc = accounts.find(a => a.id === o.channel_id)
    const marketType = acc?.market_type || ''
    const sellerId = acc?.seller_id || ''
    const storeSlug = (acc?.additional_fields as Record<string, string> | undefined)?.storeSlug || ''
    const productNo = o.product_id || ''

    // 마켓 상품번호가 있으면 구매페이지 직접 이동
    if (productNo) {
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
    setUrlModalOrderId(orderId)
    setUrlModalInput('')
    setShowUrlModal(true)
  }

  // 미등록 입력 URL 저장 + 이미지 자동 수집
  const handleUrlSubmit = async () => {
    if (!urlModalInput.trim()) {
      showAlert('URL을 입력해주세요', 'error')
      return
    }
    setUrlModalSaving(true)
    try {
      const url = urlModalInput.trim()
      // 이미지 추출 시도
      let imageUrl: string | undefined
      try {
        const res = await orderApi.fetchProductImage(url)
        imageUrl = res.image_url
      } catch {
        // 이미지 추출 실패 시 URL만 저장
      }
      await orderApi.update(urlModalOrderId, {
        product_id: url,
        ...(imageUrl ? { product_image: imageUrl } : {}),
      })
      setShowUrlModal(false)
      setUrlModalInput('')
      loadOrders()
      if (imageUrl) {
        showAlert('상품 URL과 이미지가 등록되었습니다', 'success')
      } else {
        showAlert('상품 URL이 등록되었습니다 (이미지 추출 실패)', 'info')
      }
    } catch (e) {
      showAlert(e instanceof Error ? e.message : 'URL 저장 실패', 'error')
    }
    setUrlModalSaving(false)
  }

  // 이미지 클릭 → product_id URL 또는 product_image URL로 이동
  const handleImageClick = (o: SambaOrder) => {
    // product_id가 URL이면 해당 페이지로 이동 (미등록 입력으로 등록된 경우)
    if (o.product_id && o.product_id.startsWith('http')) {
      window.open(o.product_id, '_blank')
    } else if (o.product_image && o.product_image.startsWith('http')) {
      window.open(o.product_image, '_blank')
    }
  }

  // 직배/까대기/선물 토글
  const toggleAction = (orderId: string, actionKey: string) => {
    setActiveActions(prev => ({
      ...prev,
      [orderId]: prev[orderId] === actionKey ? null : actionKey,
    }))
  }

  // 기간 필터 계산
  const getPeriodStart = (key: string): Date | null => {
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    switch (key) {
      case 'today': return now
      case '1week': { const d = new Date(now); d.setDate(d.getDate() - 7); return d }
      case '15days': { const d = new Date(now); d.setDate(d.getDate() - 15); return d }
      case '1month': { const d = new Date(now); d.setMonth(d.getMonth() - 1); return d }
      case '3months': { const d = new Date(now); d.setMonth(d.getMonth() - 3); return d }
      case '6months': { const d = new Date(now); d.setMonth(d.getMonth() - 6); return d }
      case 'thisyear': return new Date(now.getFullYear(), 0, 1)
      default: return null
    }
  }

  // 필터링된 주문 목록
  const filteredOrders = orders.filter(o => {
    const orderDate = new Date(o.created_at)
    // 시작일 고정이면 customStart 우선
    if (startLocked && customStart) {
      const start = new Date(customStart)
      start.setHours(0, 0, 0, 0)
      if (orderDate < start) return false
    } else {
      const periodStart = getPeriodStart(period)
      if (periodStart && orderDate < periodStart) return false
    }
    // 종료일 필터
    if (customEnd) {
      const end = new Date(customEnd)
      end.setHours(23, 59, 59, 999)
      if (orderDate > end) return false
    }
    if (marketFilter) {
      // channel_id(계정 ID)로 계정 조회 → market_type 비교
      const acc = accounts.find(a => a.id === o.channel_id)
      if (acc) {
        if (acc.market_type !== marketFilter) return false
      } else {
        // 계정 매칭 실패 시 channel_name에 마켓명 포함 여부로 판단
        const marketName = accounts.find(a => a.market_type === marketFilter)?.market_name || marketFilter
        if (!o.channel_name?.includes(marketName)) return false
      }
    }
    if (siteFilter) {
      if (o.source_site !== siteFilter) return false
    }
    if (marketStatus) {
      if (o.shipping_status !== marketStatus) return false
    }
    if (statusFilter) {
      if (o.status !== statusFilter) return false
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
  })

  // 숫자 콤마 포맷 헬퍼
  const fmtNum = (v: string) => {
    const num = v.replace(/[^\d]/g, '')
    return num ? Number(num).toLocaleString() : ''
  }

  const pendingCount = filteredOrders.filter(o => o.status === 'pending').length

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 우측상단 알람 */}
      {notifications.length > 0 && (
        <div style={{ position: 'fixed', top: '1rem', right: '1rem', zIndex: 9999, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {notifications.map(n => (
            <div key={n.id} style={{
              background: 'rgba(255, 80, 80, 0.95)',
              border: '1px solid #FF4444',
              borderRadius: '8px',
              padding: '0.75rem 1rem',
              color: '#FFF',
              fontSize: '0.875rem',
              fontWeight: 600,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              maxWidth: '320px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem',
            }}>
              <span>{n.message}</span>
              <button onClick={() => setNotifications(prev => prev.filter(x => x.id !== n.id))}
                style={{ background: 'none', border: 'none', color: '#FFF', cursor: 'pointer', fontSize: '1rem', padding: '0 0.25rem', flexShrink: 0 }}>✕</button>
            </div>
          ))}
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

      {/* 헤더 */}
      <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>주문 상황</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>
            미배송: <span style={{ color: '#FF6B6B', fontWeight: 700 }}>{pendingCount}</span>건 / 전체: <span style={{ fontWeight: 700 }}>{filteredOrders.length}</span>건
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
        <div style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{msg}</p>)}
        </div>
      </div>

      {/* 기간 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap', alignItems: 'center' }}>
          {PERIOD_BUTTONS.map(pb => (
            <button key={pb.key} onClick={() => {
              if (dateLocked) return
              setPeriod(pb.key)
              // 프리셋 선택 시 시작일이 고정 상태가 아니면 자동 계산
              if (!startLocked) {
                const start = getPeriodStart(pb.key)
                setCustomStart(start ? start.toISOString().slice(0, 10) : '')
              }
              setCustomEnd(new Date().toISOString().slice(0, 10))
            }}
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: period === pb.key ? '1px solid #C0392B' : '1px solid #3D3D3D', color: period === pb.key ? '#fff' : '#C5C5C5', cursor: dateLocked ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', opacity: dateLocked && period !== pb.key ? 0.5 : 1 }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 4px' }} />
          <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', minWidth: '140px' }}>
            <option value="">전체 계정</option>
            {accounts.map(a => <option key={a.id} value={a.id}>{a.market_name}({a.seller_id || a.account_label || '-'})</option>)}
          </select>
          <button onClick={handleFetch} disabled={syncing} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: syncing ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{syncing ? '동기화 중...' : '가져오기'}</button>
          <button onClick={handleSyncFromMarkets} disabled={syncing}
            style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: syncing ? '#333' : '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: syncing ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{syncing ? '동기화 중...' : '전체마켓 가져오기'}</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
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
          >{startLocked ? '고정' : '고정'}</button>
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
          >{dateLocked ? '고정' : '고정'}</button>
        </div>
      </div>

      {/* 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <select style={{ ...inputStyle, width: '80px', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">상품</option>
          <option value="customer">고객</option>
          <option value="product_id">상품번호</option>
          <option value="order_number">주문번호</option>
        </select>
        <input style={{ ...inputStyle, width: '140px' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadOrders() }} />
        <button style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '118px' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체마켓보기</option>
            {[...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()].map(([type, name]) => (
              <option key={type} value={type}>{name}</option>
            ))}
          </select>
          <select style={{ ...inputStyle, width: '110px' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}><option value="">전체사이트보기</option>{['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','GrandStage','OKmall','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}</select>
          <select style={{ ...inputStyle, width: '112px' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">마켓상태 보기</option>
            {MARKET_STATUS_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '118px' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="">입력값</option>
            <option value="has_order">주문번호입력</option>
            <option value="no_order">주문번호 미입력</option>
            <option value="direct">직배</option>
            <option value="kkadaegi">까대기</option>
            <option value="gift">선물</option>
          </select>
          <select style={{ ...inputStyle, width: '112px' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">주문상태</option>
            {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select style={{ ...inputStyle, width: '88px' }}><option>-- 정렬 --</option><option>주문일자▲</option><option>주문일자▼</option></select>
          <select style={{ ...inputStyle, width: '92px' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
          </select>
        </div>
      </div>

      {/* 주문 테이블 */}
      <div style={{ border: '1px solid #2D2D2D', borderRadius: '8px', overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: '1100px', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#0D1117', borderBottom: '2px solid #1C2333' }}>
              <th style={{ width: '36px', padding: '0.5rem', textAlign: 'center', borderRight: '1px solid #1C2333' }}>
                <input type="checkbox" style={{ accentColor: '#F59E0B', width: '13px', height: '13px' }} />
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
            ) : filteredOrders.map(o => {
              const costDisplay = editingCosts[o.id] !== undefined ? fmtNum(editingCosts[o.id]) : (o.cost ? o.cost.toLocaleString() : '')
              const shipFeeDisplay = editingShipFees[o.id] !== undefined ? fmtNum(editingShipFees[o.id]) : (o.shipping_fee ? o.shipping_fee.toLocaleString() : '')
              const liveProfit = calcProfit(o)
              const liveProfitRate = calcProfitRate(o)
              const activeAction = activeActions[o.id] || null

              return (
                <tr key={o.id} style={{ borderBottom: '1px solid #1C2333', verticalAlign: 'top' }}>
                  {/* 체크박스 */}
                  <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', borderRight: '1px solid #1C2333' }}>
                    <input type="checkbox" style={{ accentColor: '#F59E0B' }} />
                  </td>
                  {/* 주문정보 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8125rem', position: 'relative' }}>
                    {/* 우측 상단: 주문일시 + 삭제 */}
                    <div style={{ position: 'absolute', top: '0.75rem', right: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontSize: '0.72rem', color: '#555' }}>{new Date(o.created_at).toLocaleString('ko-KR')}</span>
                      <button onClick={() => handleDelete(o.id)} style={{ padding: '0.125rem 0.5rem', fontSize: '0.7rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}>삭제</button>
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
                          <span style={{ fontSize: '0.75rem', color: '#888', background: '#1A1A1A', padding: '0.125rem 0.5rem', borderRadius: '4px' }}>{o.channel_name || '마켓'}</span>
                          <button onClick={() => handleCopyOrderNumber(o.order_number)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '4px', color: '#4C9AFF', cursor: 'pointer' }}>주문번호복사</button>
                          <button onClick={() => openMsgModal('sms', o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(81,207,102,0.1)', border: '1px solid rgba(81,207,102,0.3)', borderRadius: '4px', color: '#51CF66', cursor: 'pointer' }}>SMS</button>
                          <button onClick={() => openMsgModal('kakao', o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(255,211,61,0.1)', border: '1px solid rgba(255,211,61,0.3)', borderRadius: '4px', color: '#FFD93D', cursor: 'pointer' }}>KAKAO</button>
                        </div>
                        {/* 상품주문번호 + 주문번호 같은 행 */}
                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.25rem', fontSize: '0.75rem' }}>
                          <div><span style={{ color: '#666' }}>상품주문번호 </span><span style={{ fontFamily: 'monospace', color: '#E5E5E5' }}>{o.order_number}</span></div>
                          {o.shipment_id && (
                            <div><span style={{ color: '#666' }}>주문번호 </span><span style={{ fontFamily: 'monospace', color: '#B0B0B0' }}>{o.shipment_id}</span></div>
                          )}
                        </div>
                        {/* 상품명 + 수량 */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{ color: '#C5C5C5', fontSize: '0.8125rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>{o.product_name || '-'}</span>
                          <span style={{ fontSize: '2.25rem', fontWeight: 700, color: '#888', flexShrink: 0 }}>수량: <span style={{ color: '#E5E5E5' }}>{o.quantity}</span></span>
                        </div>
                      </div>
                    </div>

                    {/* 버튼 */}
                    <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                      <button onClick={() => handleDanawa(o.product_name || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'rgba(255,140,0,0.12)', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}>다나와</button>
                      <button onClick={() => handleNaver(o.product_name || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'rgba(81,207,102,0.12)', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#51CF66', cursor: 'pointer' }}>네이버</button>
                      <button onClick={() => showAlert('상품정보 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>상품정보</button>
                      <button onClick={() => showAlert('가격변경이력 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>가격변경이력</button>
                      <button onClick={() => handleSourceLink(o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>원문링크</button>
                      <button onClick={() => handleMarketLink(o)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>판매마켓링크</button>
                      <button onClick={() => openUrlModal(o.id)} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>미등록 입력</button>
                      <button onClick={() => handleTracking(o.shipping_company || '', o.tracking_number || '')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>배송조회</button>
                      <button onClick={() => showAlert('업데이트 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>업데이트</button>
                      <button onClick={() => showAlert('마켓상품삭제 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>마켓상품삭제</button>
                      <button onClick={() => showAlert('원주문취소 기능 준비중입니다', 'info')} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer' }}>원주문취소</button>
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
                  </td>
                  {/* 금액 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>결제</span><span>{o.sale_price.toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>정산</span><span>{Math.round(o.revenue).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>실수익</span><span style={{ color: liveProfit >= 0 ? '#51CF66' : '#FF6B6B' }}>{liveProfit >= 0 ? '+' : ''}{Math.round(liveProfit).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>수익률</span><span style={{ color: '#888' }}>{liveProfitRate}%</span></div>
                    </div>
                  </td>
                  {/* 주문상태 */}
                  <td style={{ padding: '0.625rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                      {/* 1행: 상태 드롭박스 + 마켓상태 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                        <select value={o.status} onChange={e => handleStatusChange(o.id, e.target.value)}
                          style={{
                            ...inputStyle,
                            flex: 1,
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                        </select>
                        <div style={{
                          flex: 1,
                          padding: '0.25rem 0.375rem',
                          background: 'rgba(30,30,30,0.6)',
                          border: '1px solid #2D2D2D',
                          borderRadius: '6px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}>
                          <span style={{ fontSize: '0.75rem', color: '#4C9AFF', fontWeight: 600 }}>{o.shipping_status || '-'}</span>
                        </div>
                      </div>

                      {/* 2행: 가격X/재고X/직배/까대기/선물 + 취소승인 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                        <div style={{ flex: 1, display: 'flex', gap: '0.25rem', alignItems: 'center', minWidth: 0 }}>
                          <button onClick={() => showAlert('가격X 기능 준비중입니다', 'info')} style={{ flex: 1, fontSize: '0.68rem', padding: '0.125rem 0', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', textAlign: 'center' }}>가격X</button>
                          <button onClick={() => showAlert('재고X 기능 준비중입니다', 'info')} style={{ flex: 1, fontSize: '0.68rem', padding: '0.125rem 0', background: 'rgba(255,211,61,0.1)', border: '1px solid rgba(255,211,61,0.3)', color: '#FFD93D', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', textAlign: 'center' }}>재고X</button>
                          {ACTION_BUTTONS.map(btn => {
                            const isActive = activeAction === btn.key
                            return (
                              <button
                                key={btn.key}
                                onClick={() => toggleAction(o.id, btn.key)}
                                style={{
                                  flex: 1,
                                  padding: '0.125rem 0',
                                  fontSize: '0.68rem',
                                  background: isActive ? btn.activeColor : 'rgba(80,80,80,0.5)',
                                  color: '#fff',
                                  border: isActive ? `1px solid ${btn.activeColor}` : '1px solid #555',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                  whiteSpace: 'nowrap',
                                  textAlign: 'center',
                                }}
                              >{btn.label}</button>
                            )
                          })}
                        </div>
                        <button onClick={async () => {
                          if (!await showConfirm(`${o.order_number} 주문의 취소요청을 승인하시겠습니까?`)) return
                          try {
                            const res = await orderApi.approveCancel(o.id)
                            showAlert(res.message || '취소승인 완료', 'success')
                            loadOrders()
                          } catch (e) { showAlert(e instanceof Error ? e.message : '취소승인 실패', 'error') }
                        }} style={{ flex: 1, fontSize: '0.68rem', padding: '0.25rem 0', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', textAlign: 'center' }}>취소승인</button>
                      </div>

                      {/* 3행: 배송비 + 원가 */}
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
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
                        <input
                          type="text"
                          style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', textAlign: 'right' }}
                          value={costDisplay}
                          placeholder="원가"
                          onChange={e => {
                            const raw = e.target.value.replace(/[^\d]/g, '')
                            setEditingCosts(prev => ({ ...prev, [o.id]: raw }))
                          }}
                          onBlur={() => handleCostSave(o.id)}
                          onKeyDown={e => { if (e.key === 'Enter') handleCostSave(o.id) }}
                        />
                      </div>

                      {/* 택배사 + 송장번호 */}
                      <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center' }}>
                        <select style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }} defaultValue={o.shipping_company || ''}>
                          <option value="">택배사</option>
                          {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
                        </select>
                        <input style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }} value={o.tracking_number || ''} readOnly placeholder="송장번호" />
                      </div>

                      {/* 간단메모 */}
                      <textarea style={{ ...inputStyle, fontSize: '0.72rem', resize: 'none', height: '3rem', lineHeight: '1.4' }} placeholder="간단메모" defaultValue={o.notes || ''} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

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
              소싱처 상품 URL을 입력하면 대표이미지가 주문정보에 표시됩니다.
              <br />향후 동일 상품 주문에도 자동 적용됩니다.
            </p>
            <input
              type="text"
              placeholder="https://www.musinsa.com/app/goods/12345"
              style={{ ...inputStyle, width: '100%', padding: '0.625rem 0.75rem', fontSize: '0.875rem', marginBottom: '1rem' }}
              value={urlModalInput}
              onChange={e => setUrlModalInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleUrlSubmit() }}
              autoFocus
            />
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowUrlModal(false)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleUrlSubmit} disabled={urlModalSaving} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: urlModalSaving ? 'not-allowed' : 'pointer' }}>
                {urlModalSaving ? '저장중...' : '등록'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SMS/카카오 발송 모달 */}
      {msgModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '480px', maxWidth: '90vw' }}>
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

            {/* 빠른 템플릿 */}
            <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
              {[
                { label: '배송안내', msg: '안녕하세요 고객님, 주문하신 상품이 발송되었습니다. 배송 완료까지 2~3일 소요될 수 있습니다.' },
                { label: '배송지연', msg: '안녕하세요 고객님, 현재 물량이 많아 배송이 다소 지연되고 있습니다. 양해 부탁드립니다.' },
                { label: '품절안내', msg: '안녕하세요 고객님, 주문하신 상품이 품절되어 안내드립니다. 취소 처리 도와드리겠습니다.' },
                { label: '취소완료', msg: '안녕하세요 고객님, 요청하신 주문건 취소 완료되었습니다.' },
              ].map(t => (
                <button
                  key={t.label}
                  onClick={() => setMsgText(t.msg)}
                  style={{ fontSize: '0.6875rem', padding: '0.25rem 0.5rem', background: '#222', border: '1px solid #333', borderRadius: '4px', color: '#aaa', cursor: 'pointer' }}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* 메시지 입력 */}
            <textarea
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
    </div>
  )
}

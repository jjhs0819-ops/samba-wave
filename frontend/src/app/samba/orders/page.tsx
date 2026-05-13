'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
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
import { sourcingAccountApi, type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { fmtTime, formatDateInput, getKstTodayDate } from '@/lib/samba/utils'
import { fmtNum } from '@/lib/samba/styles'
import OrdersTable from './components/OrdersTable'
import { useSmsMessage } from './hooks/useSmsMessage'
import { useOrderSync } from './hooks/useOrderSync'
import { useOrderLinks } from './hooks/useOrderLinks'
import { useOrderActions } from './hooks/useOrderActions'
import { useUrlModal } from './hooks/useUrlModal'
import { renderCopyableText, splitCustomerAddress } from './utils/copyHelpers'
import { formatSourceSiteLabel, normalizeSourceSiteName } from './utils/siteAlias'
import { parsePlayautoAliasEntry } from '@/lib/samba/playautoAlias'
import OrdersFilterBar from './components/OrdersFilterBar'
import OrdersTopBar from './components/OrdersTopBar'
import OrdersPagination from './components/OrdersPagination'
import PriceHistoryModal from './components/PriceHistoryModal'
import MessageModal from './components/MessageModal'
import OrderEditModal from './components/OrderEditModal'
import UrlInputModal from './components/UrlInputModal'
import SmsTemplateEditModal from './components/SmsTemplateEditModal'
import AlarmSettingModal from './components/AlarmSettingModal'
import TrackingModal from './components/TrackingModal'
import { showConfirm } from '@/components/samba/Modal'

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

export default function OrdersPage() {
  useEffect(() => { document.title = 'SAMBA-주문관리' }, [])
  const searchParams = useSearchParams()
  const cpId = searchParams.get('cpId')
  const cpName = searchParams.get('cpName')
  const isProductMode = !!cpId
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [channels, setChannels] = useState<SambaChannel[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('today')
  const [marketFilter, setMarketFilter] = useState('')
  const [marketStatus, setMarketStatus] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState('')
  const [registrationFilter, setRegistrationFilter] = useState('registered')
  const [inputFilter, setInputFilter] = useState('')
  const [invoiceFilter, setInvoiceFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('cancel_return_excluded')
  // CS 페이지 등 외부에서 ?search=...&search_type=... 로 진입 시 자동 검색
  const initialSearch = searchParams.get('search') || ''
  const [searchText, setSearchText] = useState(initialSearch)
  const [appliedSearchText, setAppliedSearchText] = useState(initialSearch)
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [totalSale, setTotalSale] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
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
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })

  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingTrackings, setEditingTrackings] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  const [editingOrderNumbers, setEditingOrderNumbers] = useState<Record<string, string>>({})

  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  const [collectedProductCosts, setCollectedProductCosts] = useState<Record<string, number>>({})
  const [collectedProductSourceSites, setCollectedProductSourceSites] = useState<Record<string, string>>({})

  const [notifications, setNotifications] = useState<{id: number, message: string, type: string}[]>([])

  const showNotification = (message: string, type: string = 'warning') => {
    const id = Date.now()
    setNotifications(prev => [...prev, { id, message, type }])
  }


  const [refreshLog, setRefreshLog] = useState<Record<string, string>>({})


  const [priceHistoryModal, setPriceHistoryModal] = useState(false)
  const [priceHistoryData, setPriceHistoryData] = useState<Record<string, unknown>[]>([])
  const [priceHistoryProduct, setPriceHistoryProduct] = useState<{ name: string; source_site: string }>({ name: '', source_site: '' })


  const sms = useSmsMessage(accounts)
  const {
    msgModal, setMsgModal,
    msgText, setMsgText,
    msgSending, msgTextRef, msgHistory,
    sentFlags, setSentFlags,
    smsTemplates,
    templateEditModal, setTemplateEditModal,
    isNewTemplate,
    openNewTemplate, openEditTemplate, saveTemplate, deleteTemplate,
    insertMsgTag, openMsgModal, handleSendMsg,
  } = sms


  const [showAlarmSetting, setShowAlarmSetting] = useState(searchParams.get('alarm') === '1')
  const [alarmHour, setAlarmHour] = useState('0')
  const [alarmMin, setAlarmMin] = useState('5')
  const [sleepStart, setSleepStart] = useState('00:00')
  const [sleepEnd, setSleepEnd] = useState('09:00')


  const initialSearchType = searchParams.get('search_type') || 'customer'
  const [searchCategory, setSearchCategory] = useState(initialSearchType)

  const [dateLocked, setDateLocked] = useState(false)
  const [customStart, setCustomStart] = useState(() => formatDateInput(getKstTodayDate()))
  const [startLocked, setStartLocked] = useState(false)
  const [customEnd, setCustomEnd] = useState(() => formatDateInput(getKstTodayDate()))
  const loadOrders = useCallback(async () => {
    setLoading(true)
    try {
      const data = isProductMode
        ? await orderApi.listByCollectedProductPaged({
            collectedProductId: cpId!,
            skip: (currentPage - 1) * pageSize,
            limit: pageSize,
            market_filter: marketFilter,
            site_filter: siteFilter,
            account_filter: accountFilter,
            market_status: marketStatus,
            status_filter: statusFilter,
            input_filter: inputFilter,
            invoice_filter: invoiceFilter,
            registration_filter: registrationFilter,
            search_text: appliedSearchText,
            search_category: searchCategory,
            sort_by: sortBy,
          })
        : await orderApi.listByDateRangePaged({
            start: customStart,
            end: customEnd,
            skip: (currentPage - 1) * pageSize,
            limit: pageSize,
            market_filter: marketFilter,
            site_filter: siteFilter,
            account_filter: accountFilter,
            market_status: marketStatus,
            status_filter: statusFilter,
            input_filter: inputFilter,
            invoice_filter: invoiceFilter,
            registration_filter: registrationFilter,
            search_text: appliedSearchText,
            search_category: searchCategory,
            sort_by: sortBy,
          })
      setOrders(data.items)
      setTotalCount(data.total_count)
      setTotalSale(data.total_sale)
      setPendingCount(data.pending_count)
      setEditingTrackings({})

      const actions: Record<string, string | null> = {}
      for (const o of data.items) {
        if (o.action_tag) actions[o.id] = o.action_tag
      }
      setActiveActions(actions)

      if (data.items.length > 0) {
        proxyApi.fetchSentFlags(data.items.map(o => o.id)).then(flags => {
          setSentFlags(flags)
        }).catch(() => {})
      } else {
        setSentFlags({})
      }
    } catch (e) {
      console.error('주문 조회 실패:', e)
      setLogMessages(prev => [...prev, `[${fmtTime()}] 주문 조회 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`])
    }
    setLoading(false)
  }, [isProductMode, cpId, currentPage, pageSize, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, inputFilter, invoiceFilter, registrationFilter, appliedSearchText, searchCategory, sortBy, customStart, customEnd, setSentFlags])

  const patchOrder = useCallback((id: string, patch: Partial<SambaOrder>) => {
    setOrders(prev => prev.map(order => (
      order.id === id ? { ...order, ...patch } : order
    )))
  }, [])

  const applySearch = useCallback(() => {
    setCurrentPage(1)
    const trimmed = searchText.trim()
    // 검색어가 바뀌면 state 변경만 → loadOrders가 새 값으로 재생성되고 useEffect가 자동 재조회
    // 같은 검색어로 다시 누르면 state가 안 바뀌므로 강제 호출
    if (trimmed === appliedSearchText) loadOrders()
    else setAppliedSearchText(trimmed)
  }, [searchText, appliedSearchText, loadOrders])


  const [siteAliasMap, setSiteAliasMap] = useState<Record<string, string>>({})
  const siteOptions = useMemo(() => {
    const knownSites = ['MUSINSA', 'KREAM', 'FashionPlus', 'Nike', 'Adidas', 'ABCmart', 'REXMONDE', 'SSG', 'LOTTEON', 'GSSHOP', 'ElandMall', 'SSF']
    const options = new Map<string, string>()

    const formatSiteLabel = (site: string) => {
      const formatted = formatSourceSiteLabel(site, siteAliasMap)
      if (formatted) return formatted
      return normalizeSourceSiteName(site)
    }

    for (const site of knownSites) {
      options.set(site, formatSiteLabel(site))
    }
    for (const order of orders) {
      const site = order.source_site?.trim()
      if (!site) continue
      // 괄호 안은 플레이오토 마켓 계정명(예: GS이숍(고경))이 source_site에 섞이는 케이스 — base만 노출
      const baseRaw = site.match(/^(.+?)\(/)?.[1]?.trim() || site
      const baseSite = normalizeSourceSiteName(baseRaw)
      options.set(baseSite, formatSiteLabel(baseSite))
    }

    return [...options.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'ko'))
  }, [orders, siteAliasMap])
  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => {
    setCurrentPage(1)
  }, [pageSize, customStart, customEnd, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, registrationFilter, inputFilter, invoiceFilter, searchCategory, sortBy, isProductMode, cpId])
  useEffect(() => {
    const ids = [...new Set(orders.map(o => o.collected_product_id).filter((id): id is string => !!id))]
    if (ids.length === 0) {
      setCollectedProductCosts({})
      setCollectedProductSourceSites({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const rows = await collectorApi.getProductsByIds(ids)
        if (cancelled) return
        const next: Record<string, number> = {}
        const nextSourceSites: Record<string, string> = {}
        for (const row of rows) {
          next[row.id] = row.cost ?? row.sale_price ?? row.original_price ?? 0
          if (row.source_site) nextSourceSites[row.id] = row.source_site
        }
        setCollectedProductCosts(next)
        setCollectedProductSourceSites(nextSourceSites)
      } catch {
        if (!cancelled) {
          setCollectedProductCosts({})
          setCollectedProductSourceSites({})
        }
      }
    })()
    return () => { cancelled = true }
  }, [orders])

  useEffect(() => {
    orderApi.getAlarmSettings().then(d => {
      setAlarmHour(String(d.hour))
      setAlarmMin(String(d.min))
      setSleepStart(d.sleep_start)
      setSleepEnd(d.sleep_end)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (searchParams.get('alarm') === '1') setShowAlarmSetting(true)
  }, [searchParams])

  useEffect(() => {
    const handler = () => setShowAlarmSetting(true)
    window.addEventListener('open-alarm-setting', handler)
    return () => window.removeEventListener('open-alarm-setting', handler)
  }, [])

  // 페이지 진입 시 미처리 취소요청 알람 (1회)
  useEffect(() => {
    orderApi.getCancelAlertCount().then(({ count }) => {
      if (count > 0) {
        showNotification(`처리 중인 주문 중 취소요청이 ${fmtNum(count)}건 있습니다. 확인해 주세요.`)
      }
    }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  // 마운트 1회 — 5개 메타 API를 하나의 useEffect에서 동시 호출 (DB 커넥션 경합 최소화)
  useEffect(() => {
    Promise.all([
      channelApi.list().then(setChannels).catch(() => {}),
      accountApi.listActive().then(setAccounts).catch(() => {}),
      sourcingAccountApi.list().then(accs => setSourcingAccounts(accs.filter(a => a.is_active))).catch(() => {}),
      proxyApi.aligoRemain().then(r => { if (r.success) setSmsRemain(r) }).catch(() => {}),
      forbiddenApi.getSetting('store_playauto').then(data => {
        const d = data as Record<string, string> | null
        if (!d) return
        const map: Record<string, string> = {}
        for (const k of ['alias1', 'alias2', 'alias3', 'alias4', 'alias5']) {
          const v = d[k] || ''
          const { code, alias } = parsePlayautoAliasEntry(v)
          if (code && alias) map[code] = alias
        }
        setSiteAliasMap(map)
      }).catch(() => {}),
    ])
  }, [])

  const { syncing, syncAccountId, setSyncAccountId, handleFetch } = useOrderSync({
    accounts, period, setLogMessages, showNotification, loadOrders,
  })


  const {
    handleSubmit, handleStatusChange, handleDelete,
    handleCostSave, handleShipFeeSave, calcProfit, calcProfitRate, calcFeeRate,
    handleCopyOrderNumber, handleDanawa, handleNaver, handleTracking,
    toggleAction, handleBulkAction,
  } = useOrderActions({
    channels, form, emptyForm, editingId,
    setShowForm, setEditingId, setForm, loadOrders, patchOrder,
    editingCosts, setEditingCosts,
    editingShipFees, setEditingShipFees,
    activeActions, setActiveActions,
    bulkStatus, setBulkStatus, bulkUpdating, setBulkUpdating,
    selectedIds, setSelectedIds,
    setLogMessages,
    openTrackingModal: (o: SambaOrder) => setTrackingOrder(o),
  })
  const [trackingOrder, setTrackingOrder] = useState<SambaOrder | null>(null)
  const [trackingSyncing, setTrackingSyncing] = useState(false)
  const [trackingStatusOpen, setTrackingStatusOpen] = useState(false)
  const [trackingStatusData, setTrackingStatusData] = useState<{
    counts: Record<string, number>
    recent: Array<{
      id: string; orderId: string; orderNumber: string; customerName: string
      channelName: string; site: string; sourcingOrderNumber: string; sourcingAccountLabel: string
      status: string; courier?: string | null; tracking?: string | null
      lastError?: string | null; attempts: number; updatedAt?: string | null
    }>
  } | null>(null)
  const [trackingPolling, setTrackingPolling] = useState(false)

  const refreshTrackingStatus = useCallback(async () => {
    try {
      const data = await orderApi.listRecentTrackingSyncJobs(50)
      setTrackingStatusData(data)
    } catch (err) {
      setLogMessages(prev => [...prev, `[송장상태] 조회 실패: ${(err as Error).message}`])
    }
  }, [])

  // 송장 상태 모달 열려있으면 5초마다 자동 갱신 (PENDING/DISPATCHED 잡 있을 때만)
  useEffect(() => {
    if (!trackingStatusOpen) return
    refreshTrackingStatus()
    const interval = setInterval(() => {
      const inFlight = (trackingStatusData?.counts.PENDING || 0)
        + (trackingStatusData?.counts.DISPATCHED || 0)
      if (inFlight > 0 || trackingPolling) refreshTrackingStatus()
    }, 5000)
    return () => clearInterval(interval)
  }, [trackingStatusOpen, trackingStatusData, trackingPolling, refreshTrackingStatus])

  const handleTrackingSyncOne = async (o: SambaOrder) => {
    try {
      const res = await orderApi.syncTracking(o.id)
      if (res.skipped) {
        setLogMessages(prev => [...prev, `[송장] 스킵: ${res.reason || '이미 처리됨'}`])
      } else if (res.success) {
        setLogMessages(prev => [...prev, `[송장] 큐 적재 완료 (요청ID ${res.requestId}) — 확장앱이 처리 중...`])
      } else {
        setLogMessages(prev => [...prev, `[송장] 실패: ${res.error || '알 수 없음'}`])
      }
    } catch (err) {
      setLogMessages(prev => [...prev, `[송장] 오류: ${(err as Error).message}`])
    }
  }

  const handleTrackingSyncBulk = async () => {
    if (!await showConfirm('최근 7일 내 미발송 주문(소싱처 주문번호 있고 송장 미입력)의 송장을 일괄 동기화합니다. 진행할까요?')) return
    setTrackingSyncing(true)
    try {
      const res = await orderApi.syncTrackingBulk(500, 7)
      setLogMessages(prev => [
        ...prev,
        `[송장 일괄] 큐 적재 ${fmtNum(res.queued)}건 / 스킵 ${fmtNum(res.skipped)}건 / 오류 ${fmtNum(res.errors.length)}건`,
        ...res.errors.slice(0, 5).map(e => `  · ${e}`),
      ])
      // 적재 직후 상태 모달 자동 오픈 — 진행상황 가시화
      setTrackingStatusOpen(true)
      setTrackingPolling(true)
      setTimeout(() => { setTrackingPolling(false); loadOrders() }, 60000)
    } catch (err) {
      setLogMessages(prev => [...prev, `[송장 일괄] 오류: ${(err as Error).message}`])
    } finally {
      setTrackingSyncing(false)
    }
  }
  const { handleSourceLink, handleMarketLink } = useOrderLinks(accounts)

  const {
    showUrlModal, setShowUrlModal,
    urlModalInput, setUrlModalInput,
    urlModalImageInput, setUrlModalImageInput,
    urlModalSaving,
    openUrlModal, handleUrlSubmit,
  } = useUrlModal({ orders, loadOrders })

  const handleImageClick = (o: SambaOrder) => {
    if (o.product_id && o.product_id.startsWith('http')) { window.open(o.product_id, '_blank'); return }
    if (o.product_id && o.channel_id) { handleMarketLink(o); return }
    if (o.product_image && o.product_image.startsWith('http')) window.open(o.product_image, '_blank')
  }


  const currentPageIds = useMemo(() => orders.map(o => o.id), [orders])


  const toggleSelectAll = () => {
    if (currentPageIds.every(id => selectedIds.has(id))) {
      setSelectedIds(prev => { const next = new Set(prev); currentPageIds.forEach(id => next.delete(id)); return next })
    } else {
      setSelectedIds(prev => { const next = new Set(prev); currentPageIds.forEach(id => next.add(id)); return next })
    }
  }

  
  return (
    <div style={{ color: '#E5E5E5' }}>
      <OrdersTopBar
        notifications={notifications}
        setNotifications={setNotifications}
        setStatusFilter={setStatusFilter}
        setMarketStatus={setMarketStatus}
        setCustomStart={setCustomStart}
        setCustomEnd={setCustomEnd}
        setPeriod={setPeriod}
        isProductMode={isProductMode}
        cpId={cpId}
        cpName={cpName}
        filteredOrdersCount={totalCount}
        pendingCount={pendingCount}
        smsRemain={smsRemain}
        logMessages={logMessages}
        setLogMessages={setLogMessages}
      />

      <OrdersFilterBar
        isProductMode={isProductMode}
        period={period} setPeriod={setPeriod}
        customStart={customStart} setCustomStart={setCustomStart}
        customEnd={customEnd} setCustomEnd={setCustomEnd}
        startLocked={startLocked} setStartLocked={setStartLocked}
        dateLocked={dateLocked} setDateLocked={setDateLocked}
        syncAccountId={syncAccountId} setSyncAccountId={setSyncAccountId}
        syncing={syncing} handleFetch={handleFetch}
        bulkStatus={bulkStatus} setBulkStatus={setBulkStatus}
        bulkUpdating={bulkUpdating} handleBulkAction={handleBulkAction}
        selectedIdsSize={selectedIds.size}
        filteredOrdersCount={totalCount}
        filteredOrdersTotalSale={totalSale}
        searchCategory={searchCategory} setSearchCategory={setSearchCategory}
        searchText={searchText} setSearchText={setSearchText}
        loadOrders={applySearch}
        marketFilter={marketFilter} setMarketFilter={setMarketFilter}
        siteFilter={siteFilter} setSiteFilter={setSiteFilter}
        accountFilter={accountFilter} setAccountFilter={setAccountFilter}
        marketStatus={marketStatus} setMarketStatus={setMarketStatus}
        registrationFilter={registrationFilter} setRegistrationFilter={setRegistrationFilter}
        inputFilter={inputFilter} setInputFilter={setInputFilter}
        invoiceFilter={invoiceFilter} setInvoiceFilter={setInvoiceFilter}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        sortBy={sortBy} setSortBy={setSortBy}
        pageSize={pageSize} setPageSize={setPageSize}
        accounts={accounts} sourcingAccounts={sourcingAccounts}
        siteOptions={siteOptions}
      />

      {/* 송장 자동전송 미니바 — 일괄 트리거 + 안내 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '8px 14px', margin: '6px 0',
        background: '#1a1a1a', border: '1px solid #333', borderRadius: 6,
        fontSize: 13, color: '#ccc',
      }}>
        <span style={{ fontWeight: 600, color: '#fff' }}>📦 송장 자동전송</span>
        <span style={{ color: '#888' }}>
          미발송 주문을 소싱처(무신사/롯데/SSG/ABC/GS/패션플러스/나이키/올리브영)에서 추출 → 마켓 전송
        </span>
        <button
          onClick={() => { setTrackingStatusOpen(true); refreshTrackingStatus() }}
          style={{
            marginLeft: 'auto',
            padding: '6px 14px',
            background: '#374151', color: '#fff', border: 'none', borderRadius: 4,
            cursor: 'pointer', fontSize: 13, fontWeight: 600,
          }}
        >
          📊 진행 현황
        </button>
        <button
          onClick={handleTrackingSyncBulk}
          disabled={trackingSyncing}
          style={{
            padding: '6px 14px',
            background: trackingSyncing ? '#444' : '#2563eb',
            color: '#fff', border: 'none', borderRadius: 4,
            cursor: trackingSyncing ? 'not-allowed' : 'pointer',
            fontSize: 13, fontWeight: 600,
          }}
        >
          {trackingSyncing ? '큐 적재 중...' : '송장수집'}
        </button>
        {selectedIds.size > 0 && (
          <button
            onClick={async () => {
              const ids = Array.from(selectedIds)
              setLogMessages(prev => [...prev, `[송장] 선택한 ${fmtNum(ids.length)}건 큐 적재 시작...`])
              for (const id of ids) {
                const ord = orders.find(o => o.id === id)
                if (ord) await handleTrackingSyncOne(ord)
              }
            }}
            style={{
              padding: '6px 14px',
              background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4,
              cursor: 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            선택 {fmtNum(selectedIds.size)}건 송장수집
          </button>
        )}
      </div>

      <OrdersTable
        loading={loading}
        filteredOrders={orders}
        currentPage={currentPage}
        pageSize={pageSize}
        currentPageIds={currentPageIds}
        selectedIds={selectedIds}
        setSelectedIds={setSelectedIds}
        toggleSelectAll={toggleSelectAll}
        editingCosts={editingCosts}
        setEditingCosts={setEditingCosts}
        editingShipFees={editingShipFees}
        setEditingShipFees={setEditingShipFees}
        editingTrackings={editingTrackings}
        setEditingTrackings={setEditingTrackings}
        editingOrderNumbers={editingOrderNumbers}
        setEditingOrderNumbers={setEditingOrderNumbers}
        activeActions={activeActions}
        collectedProductCosts={collectedProductCosts}
        collectedProductSourceSites={collectedProductSourceSites}
        refreshLog={refreshLog}
        setRefreshLog={setRefreshLog}
        sentFlags={sentFlags}
        siteAliasMap={siteAliasMap}
        sourcingAccounts={sourcingAccounts}
        setPriceHistoryProduct={setPriceHistoryProduct}
        setPriceHistoryData={setPriceHistoryData}
        setPriceHistoryModal={setPriceHistoryModal}
        setLogMessages={setLogMessages}
        calcProfit={calcProfit}
        calcProfitRate={calcProfitRate}
        calcFeeRate={calcFeeRate}
        splitCustomerAddress={splitCustomerAddress}
        renderCopyableText={renderCopyableText}
        handleDelete={handleDelete}
        handleImageClick={handleImageClick}
        handleCopyOrderNumber={handleCopyOrderNumber}
        openMsgModal={openMsgModal}
        handleDanawa={handleDanawa}
        handleNaver={handleNaver}
        handleSourceLink={handleSourceLink}
        handleMarketLink={handleMarketLink}
        openUrlModal={openUrlModal}
        handleTracking={handleTracking}
        loadOrders={loadOrders}
        patchOrder={patchOrder}
        handleStatusChange={handleStatusChange}
        handleCostSave={handleCostSave}
        handleShipFeeSave={handleShipFeeSave}
        toggleAction={toggleAction}
      />


      <OrdersPagination
        totalCount={totalCount}
        pageSize={pageSize}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />


      <OrderEditModal
        open={showForm}
        editingId={editingId}
        form={form}
        setForm={setForm}
        onClose={() => { setShowForm(false); setEditingId(null) }}
        onSubmit={handleSubmit}
      />


      <UrlInputModal
        open={showUrlModal}
        urlInput={urlModalInput}
        setUrlInput={setUrlModalInput}
        imageInput={urlModalImageInput}
        setImageInput={setUrlModalImageInput}
        saving={urlModalSaving}
        onClose={() => setShowUrlModal(false)}
        onSubmit={handleUrlSubmit}
      />


      <PriceHistoryModal
        open={priceHistoryModal}
        product={priceHistoryProduct}
        history={priceHistoryData}
        onClose={() => setPriceHistoryModal(false)}
      />


      <MessageModal
        msgModal={msgModal}
        setMsgModal={setMsgModal}
        msgText={msgText}
        setMsgText={setMsgText}
        msgTextRef={msgTextRef}
        msgSending={msgSending}
        msgHistory={msgHistory}
        smsTemplates={smsTemplates}
        insertMsgTag={insertMsgTag}
        openEditTemplate={openEditTemplate}
        openNewTemplate={openNewTemplate}
        deleteTemplate={deleteTemplate}
        handleSendMsg={handleSendMsg}
      />


      <SmsTemplateEditModal
        template={templateEditModal}
        setTemplate={setTemplateEditModal}
        isNew={isNewTemplate}
        onSave={saveTemplate}
      />


      <AlarmSettingModal
        open={showAlarmSetting}
        onClose={() => setShowAlarmSetting(false)}
        alarmHour={alarmHour}
        setAlarmHour={setAlarmHour}
        alarmMin={alarmMin}
        setAlarmMin={setAlarmMin}
        sleepStart={sleepStart}
        setSleepStart={setSleepStart}
        sleepEnd={sleepEnd}
        setSleepEnd={setSleepEnd}
      />

      <TrackingModal
        open={!!trackingOrder}
        order={trackingOrder}
        onClose={() => setTrackingOrder(null)}
      />

      {/* 송장 자동전송 진행 현황 모달 */}
      {trackingStatusOpen && (
        <div
          onClick={() => setTrackingStatusOpen(false)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#1f2937', color: '#e5e7eb',
              width: 1240, maxWidth: '96vw', maxHeight: '85vh',
              borderRadius: 8, padding: 20, overflow: 'auto',
              border: '1px solid #374151',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>📦 송장 자동전송 진행 현황</h3>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={refreshTrackingStatus}
                  style={{ padding: '4px 10px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                >새로고침</button>
                <button
                  onClick={() => setTrackingStatusOpen(false)}
                  style={{ padding: '4px 10px', background: '#4b5563', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}
                >닫기</button>
              </div>
            </div>

            {/* 상태 카운트 카드 */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
              {[
                { key: 'PENDING', label: '대기', color: '#6b7280' },
                { key: 'DISPATCHED', label: '추출중', color: '#0ea5e9' },
                { key: 'SCRAPED', label: '추출완료', color: '#16a34a' },
                { key: 'SENT_TO_MARKET', label: '마켓전송', color: '#22c55e' },
                { key: 'NO_TRACKING', label: '미발송', color: '#f59e0b' },
                { key: 'CANCELLED', label: '원주문취소', color: '#a855f7' },
                { key: 'FAILED', label: '실패', color: '#ef4444' },
              ].map(({ key, label, color }) => {
                const cnt = trackingStatusData?.counts[key] || 0
                return (
                  <div key={key} style={{
                    flex: 1, minWidth: 110, padding: '10px 12px',
                    background: '#111827', border: `1px solid ${color}`, borderRadius: 6,
                  }}>
                    <div style={{ color, fontSize: 11, fontWeight: 600 }}>{label}</div>
                    <div style={{ fontSize: 22, fontWeight: 700, marginTop: 2 }}>{fmtNum(cnt)}</div>
                  </div>
                )
              })}
            </div>

            {/* 최근 잡 목록 */}
            <div style={{ background: '#111827', borderRadius: 6, overflow: 'hidden', border: '1px solid #374151' }}>
              <div style={{
                display: 'grid', gridTemplateColumns: '36px 88px 150px 80px 100px 80px 90px 90px 120px 1fr',
                padding: '8px 10px', background: '#0f172a', fontSize: 11, fontWeight: 700, color: '#9ca3af',
              }}>
                <div>#</div>
                <div>상태</div>
                <div>상품주문번호</div>
                <div>고객명</div>
                <div>판매처</div>
                <div>소싱처</div>
                <div>소싱처계정</div>
                <div>택배사</div>
                <div>송장번호</div>
                <div>오류/메모</div>
              </div>
              {(trackingStatusData?.recent || []).map((j, idx) => {
                const statusColor: Record<string, string> = {
                  PENDING: '#6b7280', DISPATCHED: '#0ea5e9', SCRAPED: '#16a34a',
                  SENT_TO_MARKET: '#22c55e', NO_TRACKING: '#f59e0b', CANCELLED: '#a855f7', FAILED: '#ef4444',
                }
                return (
                  <div key={j.id} style={{
                    display: 'grid', gridTemplateColumns: '36px 88px 150px 80px 100px 80px 90px 90px 120px 1fr',
                    padding: '6px 10px', borderTop: '1px solid #1f2937', fontSize: 12,
                  }}>
                    <div style={{ color: '#6b7280', fontSize: 11 }}>{fmtNum(idx + 1)}</div>
                    <div>
                      <span style={{
                        padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 700,
                        background: statusColor[j.status] || '#374151', color: '#fff',
                      }}>{j.status}</span>
                    </div>
                    <div style={{ fontFamily: 'monospace', fontSize: 11 }}>{j.orderNumber || j.orderId}</div>
                    <div>{j.customerName || '-'}</div>
                    <div>{j.channelName || '-'}</div>
                    <div>{j.site}</div>
                    <div>{j.sourcingAccountLabel || '-'}</div>
                    <div>{j.courier || '-'}</div>
                    <div style={{ fontFamily: 'monospace' }}>{j.tracking || '-'}</div>
                    <div style={{ color: '#9ca3af', fontSize: 11 }}>{j.lastError || ''}</div>
                  </div>
                )
              })}
              {(!trackingStatusData?.recent || trackingStatusData.recent.length === 0) && (
                <div style={{ padding: 20, textAlign: 'center', color: '#6b7280', fontSize: 12 }}>
                  아직 적재된 송장 잡이 없습니다.
                </div>
              )}
            </div>

            <div style={{ marginTop: 12, fontSize: 11, color: '#6b7280' }}>
              💡 모달이 열려있는 동안 5초마다 자동 갱신됩니다. 일괄 송장수집 직후 60초 동안 자동 폴링됩니다.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


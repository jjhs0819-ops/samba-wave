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
import { showAlert } from '@/components/samba/Modal'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'
import { fmtTime } from '@/lib/samba/utils'
import OrdersTable from './components/OrdersTable'
import { useSmsMessage } from './hooks/useSmsMessage'
import { useOrderSync } from './hooks/useOrderSync'
import { useOrderLinks } from './hooks/useOrderLinks'
import { useFilteredOrders } from './hooks/useFilteredOrders'
import { useOrderActions } from './hooks/useOrderActions'
import { useUrlModal } from './hooks/useUrlModal'
import { renderCopyableText, splitCustomerAddress } from './utils/copyHelpers'
import OrdersFilterBar from './components/OrdersFilterBar'
import OrdersTopBar from './components/OrdersTopBar'
import OrdersPagination from './components/OrdersPagination'
import PriceHistoryModal from './components/PriceHistoryModal'
import MessageModal from './components/MessageModal'
import OrderEditModal from './components/OrderEditModal'
import UrlInputModal from './components/UrlInputModal'
import SmsTemplateEditModal from './components/SmsTemplateEditModal'
import AlarmSettingModal from './components/AlarmSettingModal'

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
  // 상품별 주문이력 조회 모드
  const cpId = searchParams.get('cpId')
  const cpName = searchParams.get('cpName')
  const isProductMode = !!cpId
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [channels, setChannels] = useState<SambaChannel[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('5days')
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
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })
  // 인라인 원가/배송비/송장 수정용 상태
  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingTrackings, setEditingTrackings] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  const [editingOrderNumbers, setEditingOrderNumbers] = useState<Record<string, string>>({})
  // 직배/까대기/선물 토글 상태
  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  const [collectedProductCosts, setCollectedProductCosts] = useState<Record<string, number>>({})
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

  // SMS/카카오 발송 + 템플릿 관리 (hook으로 통합)
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

  // 취소 알림 설정 (URL 파라미터 alarm=1이면 자동 오픈)
  const [showAlarmSetting, setShowAlarmSetting] = useState(searchParams.get('alarm') === '1')
  const [alarmHour, setAlarmHour] = useState('0')
  const [alarmMin, setAlarmMin] = useState('5')
  const [sleepStart, setSleepStart] = useState('00:00')
  const [sleepEnd, setSleepEnd] = useState('09:00')

  // 검색 카테고리
  const [searchCategory, setSearchCategory] = useState('customer')
  // 일자 고정
  const [dateLocked, setDateLocked] = useState(false)
  const [customStart, setCustomStart] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 4)
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
      // SMS/카카오 발송 여부 플래그 조회
      if (data.length > 0) {
        proxyApi.fetchSentFlags(data.map(o => o.id)).then(flags => {
          setSentFlags(flags)
        }).catch(() => {})
      }
    } catch (e) {
      console.error('주문 로딩 실패:', e)
      setLogMessages(prev => [...prev, `[에러] 주문 데이터 로딩 실패: ${e instanceof Error ? e.message : '서버 오류'}`])
    }
    setLoading(false)
  }, [isProductMode, cpId, customStart, customEnd])

  const patchOrder = useCallback((id: string, patch: Partial<SambaOrder>) => {
    setOrders(prev => prev.map(order => (
      order.id === id ? { ...order, ...patch } : order
    )))
  }, [])

  // 플레이오토 마켓번호 별칭 매핑
  const [siteAliasMap, setSiteAliasMap] = useState<Record<string, string>>({})
  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => {
    const ids = [...new Set(orders.map(o => o.collected_product_id).filter((id): id is string => !!id))]
    if (ids.length === 0) {
      setCollectedProductCosts({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const rows = await collectorApi.getProductsByIds(ids)
        if (cancelled) return
        const next: Record<string, number> = {}
        for (const row of rows) {
          next[row.id] = row.cost ?? row.sale_price ?? row.original_price ?? 0
        }
        setCollectedProductCosts(next)
      } catch {
        if (!cancelled) setCollectedProductCosts({})
      }
    })()
    return () => { cancelled = true }
  }, [orders])
  // 취소알람 설정 불러오기
  useEffect(() => {
    orderApi.getAlarmSettings().then(d => {
      setAlarmHour(String(d.hour))
      setAlarmMin(String(d.min))
      setSleepStart(d.sleep_start)
      setSleepEnd(d.sleep_end)
    }).catch(() => {})
  }, [])
  // URL 파라미터 alarm=1 변경 감지 (다른 페이지에서 링크로 이동 시)
  useEffect(() => {
    if (searchParams.get('alarm') === '1') setShowAlarmSetting(true)
  }, [searchParams])
  // CustomEvent 감지 (이미 주문 페이지에 있을 때 헤더 벨 클릭 시)
  useEffect(() => {
    const handler = () => setShowAlarmSetting(true)
    window.addEventListener('open-alarm-setting', handler)
    return () => window.removeEventListener('open-alarm-setting', handler)
  }, [])
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

  const { syncing, syncAccountId, setSyncAccountId, backgroundMode, setBackgroundMode, handleFetch } = useOrderSync({
    accounts, period, setLogMessages, showNotification, loadOrders,
  })


  const {
    handleSubmit, handleStatusChange, handleDelete,
    handleCostSave, handleShipFeeSave, calcProfit, calcProfitRate, calcFeeRate,
    handleCopyOrderNumber, handleDanawa, handleNaver, handleTracking,
    toggleAction, handleBulkAction, fmtNumStr,
  } = useOrderActions({
    channels, form, emptyForm, editingId,
    setShowForm, setEditingId, setForm, loadOrders, patchOrder,
    editingCosts, setEditingCosts,
    editingShipFees, setEditingShipFees,
    activeActions, setActiveActions,
    bulkStatus, setBulkStatus, bulkUpdating, setBulkUpdating,
    selectedIds, setSelectedIds,
    setLogMessages,
  })
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

  // 필터링된 주문 목록
  const filteredOrders = useFilteredOrders({
    orders, accounts, isProductMode,
    customStart, customEnd, marketFilter, siteFilter, accountFilter,
    marketStatus, statusFilter, inputFilter, searchText, searchCategory,
    sortBy, activeActions,
  })

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

  const pendingCount = filteredOrders.filter(o => o.status === 'pending' || o.status === 'preparing').length

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
        filteredOrdersCount={filteredOrders.length}
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
        backgroundMode={backgroundMode} setBackgroundMode={setBackgroundMode}
        bulkStatus={bulkStatus} setBulkStatus={setBulkStatus}
        bulkUpdating={bulkUpdating} handleBulkAction={handleBulkAction}
        selectedIdsSize={selectedIds.size}
        filteredOrdersCount={filteredOrders.length}
        filteredOrdersTotalSale={filteredOrders.reduce((s, o) => s + (o.total_payment_amount ?? o.sale_price ?? 0), 0)}
        searchCategory={searchCategory} setSearchCategory={setSearchCategory}
        searchText={searchText} setSearchText={setSearchText}
        loadOrders={loadOrders}
        marketFilter={marketFilter} setMarketFilter={setMarketFilter}
        siteFilter={siteFilter} setSiteFilter={setSiteFilter}
        accountFilter={accountFilter} setAccountFilter={setAccountFilter}
        marketStatus={marketStatus} setMarketStatus={setMarketStatus}
        inputFilter={inputFilter} setInputFilter={setInputFilter}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        sortBy={sortBy} setSortBy={setSortBy}
        pageSize={pageSize} setPageSize={setPageSize}
        accounts={accounts} sourcingAccounts={sourcingAccounts}
      />
      {/* 주문 테이블 */}
      <OrdersTable
        loading={loading}
        filteredOrders={filteredOrders}
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
        refreshLog={refreshLog}
        setRefreshLog={setRefreshLog}
        sentFlags={sentFlags}
        siteAliasMap={siteAliasMap}
        sourcingAccounts={sourcingAccounts}
        setPriceHistoryProduct={setPriceHistoryProduct}
        setPriceHistoryData={setPriceHistoryData}
        setPriceHistoryModal={setPriceHistoryModal}
        setLogMessages={setLogMessages}
        fmtNumStr={fmtNumStr}
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

      {/* 페이지네이션 */}
      <OrdersPagination
        totalCount={filteredOrders.length}
        pageSize={pageSize}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />

      {/* 주문 수정 모달 */}
      <OrderEditModal
        open={showForm}
        editingId={editingId}
        form={form}
        setForm={setForm}
        onClose={() => { setShowForm(false); setEditingId(null) }}
        onSubmit={handleSubmit}
      />

      {/* 미등록 입력 URL 모달 */}
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

      {/* 가격/재고 이력 모달 */}
      <PriceHistoryModal
        open={priceHistoryModal}
        product={priceHistoryProduct}
        history={priceHistoryData}
        onClose={() => setPriceHistoryModal(false)}
      />

      {/* SMS/카카오 발송 모달 */}
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

      {/* SMS 템플릿 편집 모달 */}
      <SmsTemplateEditModal
        template={templateEditModal}
        setTemplate={setTemplateEditModal}
        isNew={isNewTemplate}
        onSave={saveTemplate}
      />

      {/* 취소 알림 설정 모달 */}
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
    </div>
  )
}

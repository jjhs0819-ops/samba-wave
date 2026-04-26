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
  useEffect(() => { document.title = 'SAMBA-?낅슣?뽪룇??㉱?? }, [])
  const searchParams = useSearchParams()
  // ??⑤갭????낅슣?뽪룇??????브퀗???嶺뚮ㅄ維獄?
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
  const [appliedSearchText, setAppliedSearchText] = useState('')
  const [pageSize, setPageSize] = useState(20)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [totalSale, setTotalSale] = useState(0)
  const [pendingCount, setPendingCount] = useState(0)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkStatus, setBulkStatus] = useState('')
  const [bulkUpdating, setBulkUpdating] = useState(false)
  const [sortBy, setSortBy] = useState('date_desc')
  const [logMessages, _setLogMessagesRaw] = useState<string[]>(['[???? ?낅슣?뽪룇 ?띠럾??筌뤾쑴沅롧뼨??롪퍒???쒖쾸? ???????戮?뻣??紐껊퉵??..'])
  const setLogMessages: typeof _setLogMessagesRaw = (v) => _setLogMessagesRaw(prev => {
    const next = typeof v === 'function' ? v(prev) : v
    return next.slice(-30)
  })
  const [smsRemain, setSmsRemain] = useState<{ SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })
  // ?筌뤾퍔逾?????/?꾩룄????쑏????뚯궋 ??瑜곸젧????⑤객臾?
  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingTrackings, setEditingTrackings] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  const [editingOrderNumbers, setEditingOrderNumbers] = useState<Record<string, string>>({})
  // 嶺뚯쉳??첎?濚밸Ŧ??????ル뱼???? ??⑤객臾?
  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  const [collectedProductCosts, setCollectedProductCosts] = useState<Record<string, number>>({})
  // ??⑥???⑤８堉????肉?
  const [notifications, setNotifications] = useState<{id: number, message: string, type: string}[]>([])

  const showNotification = (message: string, type: string = 'warning') => {
    const id = Date.now()
    setNotifications(prev => [...prev, { id, message, type }])
  }

  // ?낅슣?뽪룇?????낆몥??袁⑤콦 ?β돦裕??(?낅슣?뽪룇 ID ??嶺뚮씭??嶺??띠룄????롪퍒???
  const [refreshLog, setRefreshLog] = useState<Record<string, string>>({})

  // ?띠럾??롪봇維???嶺뚮ㅄ維??
  const [priceHistoryModal, setPriceHistoryModal] = useState(false)
  const [priceHistoryData, setPriceHistoryData] = useState<Record<string, unknown>[]>([])
  const [priceHistoryProduct, setPriceHistoryProduct] = useState<{ name: string; source_site: string }>({ name: '', source_site: '' })

  // SMS/?곸궠?삭맱???꾩룇裕??+ ???ロ깵????㉱??(hook??怨쀬Ŧ ????)
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

  // ???쳛?????逾????깆젧 (URL ???逾ф쾬?롮구??alarm=1????????吏????덊깯)
  const [showAlarmSetting, setShowAlarmSetting] = useState(searchParams.get('alarm') === '1')
  const [alarmHour, setAlarmHour] = useState('0')
  const [alarmMin, setAlarmMin] = useState('5')
  const [sleepStart, setSleepStart] = useState('00:00')
  const [sleepEnd, setSleepEnd] = useState('09:00')

  // ?롪틵????곸궠??誘ㅒ?μ쪚??
  const [searchCategory, setSearchCategory] = useState('customer')
  // ??源놁겱 ??μ쪠??
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
            search_text: appliedSearchText,
            search_category: searchCategory,
            sort_by: sortBy,
          })
      setOrders(data.items)
      setTotalCount(data.total_count)
      setTotalSale(data.total_sale)
      setPendingCount(data.pending_count)
      setEditingTrackings({})
      // ??類ㅼ뮅??????꾩룇猷? action_tag??activeActions ?貫?껆뵳??
      const actions: Record<string, string | null> = {}
      for (const o of data.items) {
        if (o.action_tag) actions[o.id] = o.action_tag
      }
      setActiveActions(actions)
      // SMS/?곸궠?삭맱???꾩룇裕????? ????뗥윜??브퀗???
      if (data.items.length > 0) {
        proxyApi.fetchSentFlags(data.items.map(o => o.id)).then(flags => {
          setSentFlags(flags)
        }).catch(() => {})
      } else {
        setSentFlags({})
      }
    } catch (e) {
      console.error('?낅슣?뽪룇 ?β돦裕녽????덉넮:', e)
      setLogMessages(prev => [...prev, `[????? ?낅슣?뽪룇 ??⑥щ턄???β돦裕녽????덉넮: ${e instanceof Error ? e.message : '??類ㅼ뮅 ???댁쾼'}`])
    }
    setLoading(false)
  }, [isProductMode, cpId, currentPage, pageSize, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, inputFilter, appliedSearchText, searchCategory, sortBy, customStart, customEnd, setSentFlags])

  const patchOrder = useCallback((id: string, patch: Partial<SambaOrder>) => {
    setOrders(prev => prev.map(order => (
      order.id === id ? { ...order, ...patch } : order
    )))
  }, [])

  const applySearch = useCallback(() => {
    setCurrentPage(1)
    setAppliedSearchText(searchText.trim())
  }, [searchText])

  // ??????怨멸텕??嶺뚮씭???삳┛??녾퉰 ?곌랙?닺눧?嶺뚮씞?뗩뇡?
  const [siteAliasMap, setSiteAliasMap] = useState<Record<string, string>>({})
  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => {
    setCurrentPage(1)
  }, [pageSize, customStart, customEnd, marketFilter, siteFilter, accountFilter, marketStatus, statusFilter, inputFilter, searchCategory, sortBy, isProductMode, cpId])
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
  // ???쳛????肉????깆젧 ?釉띾쐞???釉띯뵛
  useEffect(() => {
    orderApi.getAlarmSettings().then(d => {
      setAlarmHour(String(d.hour))
      setAlarmMin(String(d.min))
      setSleepStart(d.sleep_start)
      setSleepEnd(d.sleep_end)
    }).catch(() => {})
  }, [])
  // URL ???逾ф쾬?롮구??alarm=1 ?곌떠????띠룆흮? (???섎???瑜곷턄嶺뚯솘??????嶺뚮씧?긷칰類욎뿉????????
  useEffect(() => {
    if (searchParams.get('alarm') === '1') setShowAlarmSetting(true)
  }, [searchParams])
  // CustomEvent ?띠룆흮? (???? ?낅슣?뽪룇 ??瑜곷턄嶺뚯솘??????깅굵 ?????녹맠 ?????????
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

  // ?熬곥굤?꿰춯?삳궙筌??낅슣?뽪룇 嶺뚮ㅄ維뽨빳?
  const currentPageIds = useMemo(() => orders.map(o => o.id), [orders])

  // ?熬곣뫕????ルㅎ臾???怨몄젷
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
        backgroundMode={backgroundMode} setBackgroundMode={setBackgroundMode}
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
        inputFilter={inputFilter} setInputFilter={setInputFilter}
        statusFilter={statusFilter} setStatusFilter={setStatusFilter}
        sortBy={sortBy} setSortBy={setSortBy}
        pageSize={pageSize} setPageSize={setPageSize}
        accounts={accounts} sourcingAccounts={sourcingAccounts}
      />
      {/* ?낅슣?뽪룇 ???逾??*/}
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

      {/* ??瑜곷턄嶺뚯솘????깅턄??*/}
      <OrdersPagination
        totalCount={totalCount}
        pageSize={pageSize}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />

      {/* ?낅슣?뽪룇 ??瑜곸젧 嶺뚮ㅄ維??*/}
      <OrderEditModal
        open={showForm}
        editingId={editingId}
        form={form}
        setForm={setForm}
        onClose={() => { setShowForm(false); setEditingId(null) }}
        onSubmit={handleSubmit}
      />

      {/* 亦껋꼶梨띈린臾됱뿉????놁졑 URL 嶺뚮ㅄ維??*/}
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

      {/* ?띠럾????????????嶺뚮ㅄ維??*/}
      <PriceHistoryModal
        open={priceHistoryModal}
        product={priceHistoryProduct}
        history={priceHistoryData}
        onClose={() => setPriceHistoryModal(false)}
      />

      {/* SMS/?곸궠?삭맱???꾩룇裕??嶺뚮ㅄ維??*/}
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

      {/* SMS ???ロ깵???筌뤾쑴異?嶺뚮ㅄ維??*/}
      <SmsTemplateEditModal
        template={templateEditModal}
        setTemplate={setTemplateEditModal}
        isNew={isNewTemplate}
        onSave={saveTemplate}
      />

      {/* ???쳛?????逾????깆젧 嶺뚮ㅄ維??*/}
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


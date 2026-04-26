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
  const [logMessages, _setLogMessagesRaw] = useState<string[]>(['[???? ???녿뮝?筌믡굥利???醫딆쓧??癲ル슢???몄쒜嚥▲룗???嚥▲굧?????戮곗?? ???????嶺?筌??嶺뚮ㅎ????..'])
  const setLogMessages: typeof _setLogMessagesRaw = (v) => _setLogMessagesRaw(prev => {
    const next = typeof v === 'function' ? v(prev) : v
    return next.slice(-30)
  })
  const [smsRemain, setSmsRemain] = useState<{ SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })
  // ?癲ル슢??遺셋?????/?熬곣뫖利?????????????????볥궚???????븐뻤??
  const [editingCosts, setEditingCosts] = useState<Record<string, string>>({})
  const [editingTrackings, setEditingTrackings] = useState<Record<string, string>>({})
  const [editingShipFees, setEditingShipFees] = useState<Record<string, string>>({})
  const [editingOrderNumbers, setEditingOrderNumbers] = useState<Record<string, string>>({})
  // ?꿔꺂????筌??μ떜媛?걫????????リ뎬???? ????븐뻤??
  const [activeActions, setActiveActions] = useState<Record<string, string | null>>({})
  const [collectedProductCosts, setCollectedProductCosts] = useState<Record<string, number>>({})
  // ??????????욱룏???????
  const [notifications, setNotifications] = useState<{id: number, message: string, type: string}[]>([])

  const showNotification = (message: string, type: string = 'warning') => {
    const id = Date.now()
    setNotifications(prev => [...prev, { id, message, type }])
  }

  // ???녿뮝?筌믡굥利???????욍걛???ш끽維???汝??吏??(???녿뮝?筌믡굥利?ID ???꿔꺂????????醫딆┣????嚥▲굧????
  const [refreshLog, setRefreshLog] = useState<Record<string, string>>({})

  // ??醫딆쓧??嚥▲굥?멩납????꿔꺂??袁ㅻ븶???
  const [priceHistoryModal, setPriceHistoryModal] = useState(false)
  const [priceHistoryData, setPriceHistoryData] = useState<Record<string, unknown>[]>([])
  const [priceHistoryProduct, setPriceHistoryProduct] = useState<{ name: string; source_site: string }>({ name: '', source_site: '' })

  // SMS/??⑤㈇????????熬곣뫖利든뜏??+ ?????萸?????援온??(hook????Β??????)
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

  // ??????????????繹먮냱??(URL ?????쀪쑴??嚥????alarm=1????????嶺??????꾨Щ)
  const [showAlarmSetting, setShowAlarmSetting] = useState(searchParams.get('alarm') === '1')
  const [alarmHour, setAlarmHour] = useState('0')
  const [alarmMin, setAlarmMin] = useState('5')
  const [sleepStart, setSleepStart] = useState('00:00')
  const [sleepEnd, setSleepEnd] = useState('09:00')

  // ?嚥▲굧??????⑤㈇???亦껋꼨????쒙쭫??
  const [searchCategory, setSearchCategory] = useState('customer')
  // ??濚밸Ŧ?긷칰????쒙쭫??
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
      // ??嶺뚮Ĳ?됭짆??????熬곣뫖利?? action_tag??activeActions ?潁??용끏???
      const actions: Record<string, string | null> = {}
      for (const o of data.items) {
        if (o.action_tag) actions[o.id] = o.action_tag
      }
      setActiveActions(actions)
      // SMS/??⑤㈇????????熬곣뫖利든뜏????? ?????關????됰슦????
      if (data.items.length > 0) {
        proxyApi.fetchSentFlags(data.items.map(o => o.id)).then(flags => {
          setSentFlags(flags)
        }).catch(() => {})
      } else {
        setSentFlags({})
      }
    } catch (e) {
      console.error('???녿뮝?筌믡굥利??汝??吏??뮤??????곌숯:', e)
      setLogMessages(prev => [...prev, `[????? ???녿뮝?筌믡굥利???????????汝??吏??뮤??????곌숯: ${e instanceof Error ? e.message : '??嶺뚮Ĳ?됭짆?????怨몄뵒'}`])
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

  // ????????ㅳ늾????꿔꺂???????꾨탿????⑸룺 ??⑤슢???釉띾떛??꿔꺂?????몃??
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
  // ?????????????繹먮냱?????곗뵯??????곗뵚??
  useEffect(() => {
    orderApi.getAlarmSettings().then(d => {
      setAlarmHour(String(d.hour))
      setAlarmMin(String(d.min))
      setSleepStart(d.sleep_start)
      setSleepEnd(d.sleep_end)
    }).catch(() => {})
  }, [])
  // URL ?????쀪쑴??嚥????alarm=1 ??⑤슢堉?????醫딆┫?? (?????봔?????볥궙?袁р뵾??????????꿔꺂???疫뀀９臾쇘춯癒?돵?????????
  useEffect(() => {
    if (searchParams.get('alarm') === '1') setShowAlarmSetting(true)
  }, [searchParams])
  // CustomEvent ??醫딆┫?? (???? ???녿뮝?筌믡굥利?????볥궙?袁р뵾?????????繹먮굛????????諛몄? ?????????
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

  // ????꾣뤃?饔낃퀣????좏뀮癲????녿뮝?筌믡굥利??꿔꺂??袁ㅻ븶筌믠뫀萸?
  const currentPageIds = useMemo(() => orders.map(o => o.id), [orders])

  // ????썹땟??????ｋ??????ㅼ굣??
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
      {/* ???녿뮝?筌믡굥利???????*/}
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

      {/* ????볥궙?袁р뵾???????繹먮굟瑗??*/}
      <OrdersPagination
        totalCount={totalCount}
        pageSize={pageSize}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />

      {/* ???녿뮝?筌믡굥利?????볥궚???꿔꺂??袁ㅻ븶???*/}
      <OrderEditModal
        open={showForm}
        editingId={editingId}
        form={form}
        setForm={setForm}
        onClose={() => { setShowForm(false); setEditingId(null) }}
        onSubmit={handleSubmit}
      />

      {/* ???붺몭?겹럷??댿뵛??쒕㎥??????怨몄７ URL ?꿔꺂??袁ㅻ븶???*/}
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

      {/* ??醫딆쓧?????????????꿔꺂??袁ㅻ븶???*/}
      <PriceHistoryModal
        open={priceHistoryModal}
        product={priceHistoryProduct}
        history={priceHistoryData}
        onClose={() => setPriceHistoryModal(false)}
      />

      {/* SMS/??⑤㈇????????熬곣뫖利든뜏???꿔꺂??袁ㅻ븶???*/}
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

      {/* SMS ?????萸???癲ル슢???밸퉲??꿔꺂??袁ㅻ븶???*/}
      <SmsTemplateEditModal
        template={templateEditModal}
        setTemplate={setTemplateEditModal}
        isNew={isNewTemplate}
        onSave={saveTemplate}
      />

      {/* ??????????????繹먮냱???꿔꺂??袁ㅻ븶???*/}
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


'use client'

import { Fragment, useEffect, useState, useCallback, useRef } from 'react'
import { orderApi, accountApi } from '@/lib/samba/api/commerce'
import { returnApi, csInquiryApi, type SambaCSInquiry, type CSReplyTemplate } from '@/lib/samba/api/support'
import type { SambaMarketAccount } from '@/lib/samba/api/commerce'

import { showAlert, showConfirm } from '@/components/samba/Modal'

/** HTML ?쒓렇瑜?以꾨컮轅덉쑝濡?蹂?????쒓굅 ??CS 臾몄쓽 ?띿뒪?몃? 源붾걫?섍쾶 ?쒖떆 */
function htmlToText(html: string): string {
  if (!html) return ''
  return html
    .replace(/<\/p>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
import { card, inputStyle, fmtNum } from '@/lib/samba/styles'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { fmtDate, fmtTime } from '@/lib/samba/utils'

// ?듬? ?곹깭 留?
const REPLY_STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: '誘몃떟蹂', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  replied: { label: '?듬??꾨즺', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
}

// 臾몄쓽 ?좏삎 留?
const INQUIRY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  general: { label: '二쇰Ц臾몄쓽', color: '#FF8C00' },
  product: { label: '二쇰Ц臾몄쓽', color: '#FF8C00' },
  qna: { label: '?곹뭹臾몄쓽', color: '#4C9AFF' },
  call_center: { label: '二쇰Ц臾몄쓽', color: '#FF8C00' },
  delivery: { label: '二쇰Ц臾몄쓽', color: '#FF8C00' },
  exchange_return: { label: '二쇰Ц臾몄쓽', color: '#FF8C00' },
  exchange_request: { label: '援먰솚?붿껌', color: '#FFB6C1' },
  cancel_request: { label: '痍⑥냼?붿껌', color: '#FF5050' },
  product_question: { label: '?곹뭹臾몄쓽', color: '#4C9AFF' },
}

// 留덉폆 由ъ뒪??(@/lib/samba/markets?먯꽌 import)


  useEffect(() => { document.title = 'SAMBA-CS' }, [])
  // ?곗씠??
  const [inquiries, setInquiries] = useState<SambaCSInquiry[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<Record<string, unknown>>({})
  const [templates, setTemplates] = useState<Record<string, CSReplyTemplate>>({})
  const [loading, setLoading] = useState(true)

  // ?꾪꽣
  const [filterMarket, setFilterMarket] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('pending')
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [sortDesc, setSortDesc] = useState(true)
  const [pageSize, setPageSize] = useState(30)
  const [page, setPage] = useState(0)

  // 濡쒓렇 + 湲곌컙 + ?꾪꽣 異붽? ?곹깭
  const [csLogMessages, setCsLogMessages] = useState<string[]>(['[?湲? CS 臾몄쓽 媛?몄삤湲?寃곌낵媛 ?ш린???쒖떆?⑸땲??..'])
  const [csPeriod, setCsPeriod] = useState('thisyear')
  const [csSyncAccountId, setCsSyncAccountId] = useState('')
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [csCustomStart, setCsCustomStart] = useState(`${new Date().getFullYear()}-01-01`)
  const [csCustomEnd, setCsCustomEnd] = useState(new Date().toLocaleDateString('sv-SE'))
  const [csStartLocked, setCsStartLocked] = useState(false)
  const [csDateLocked, setCsDateLocked] = useState(false)
  const [searchCategory, setSearchCategory] = useState('customer')
  const [csSiteFilter, setCsSiteFilter] = useState('')
  const [csMarketStatus, setCsMarketStatus] = useState('')
  const [csInputFilter, setCsInputFilter] = useState('')

  // ?좏깮
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // ?듬? 紐⑤떖
  const [replyModal, setReplyModal] = useState<SambaCSInquiry | null>(null)
  const [replyText, setReplyText] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('')

  // 援먰솚/痍⑥냼 ?≪뀡 紐⑤떖
  const [exchangeActionItem, setExchangeActionItem] = useState<SambaCSInquiry | null>(null)
  // 11踰덇? 援먰솚 嫄곕? ?ъ쑀 ?낅젰 紐⑤떖
  const [rejectReasonModal, setRejectReasonModal] = useState(false)
  const [rejectReasonText, setRejectReasonText] = useState('')
  const [rejectTargetItem, setRejectTargetItem] = useState<SambaCSInquiry | null>(null)

  // 11踰덇? 援먰솚 ?뱀씤: returnApi ?ъ슜
  const handleElevenstExchangeApprove = async (item: SambaCSInquiry) => {
    if (!item.market_order_id) { showAlert('二쇰Ц踰덊샇媛 ?놁뒿?덈떎', 'error'); return }
    if (!await showConfirm(`${item.market_order_id} 二쇰Ц??援먰솚???뱀씤(?щ같?? ?섏떆寃좎뒿?덇퉴?`)) return
    try {
      const order = await orderApi.findByOrderNumber(item.market_order_id)
      if (!order) { showAlert('?대떦 二쇰Ц??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const returns = await returnApi.list(order.id, undefined, 'exchange')
      const ret = returns[0]
      if (!ret) { showAlert('援먰솚 ?좎껌 湲곕줉??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const res = await returnApi.exchangeAction(ret.id, 'approve')
      showAlert(res.message || '援먰솚?뱀씤 ?꾨즺', 'success')
      setExchangeActionItem(null)
    } catch (e) { showAlert(e instanceof Error ? e.message : '援먰솚?뱀씤 ?ㅽ뙣', 'error') }
  }

  // 11踰덇? 援먰솚 嫄곕?: ?ъ쑀 ?낅젰 ??泥섎━
  const handleElevenstExchangeReject = (item: SambaCSInquiry) => {
    setRejectTargetItem(item)
    setRejectReasonText('')
    setRejectReasonModal(true)
  }

  const submitElevenstExchangeReject = async () => {
    if (!rejectTargetItem?.market_order_id) { showAlert('二쇰Ц踰덊샇媛 ?놁뒿?덈떎', 'error'); return }
    if (!rejectReasonText.trim()) { showAlert('거부 사유를 입력해주세요', 'error'); return }
    try {
      const order = await orderApi.findByOrderNumber(rejectTargetItem.market_order_id)
      if (!order) { showAlert('?대떦 二쇰Ц??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const returns = await returnApi.list(order.id, undefined, 'exchange')
      const ret = returns[0]
      if (!ret) { showAlert('援먰솚 ?좎껌 湲곕줉??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const res = await returnApi.exchangeAction(ret.id, 'reject', rejectReasonText.trim())
      showAlert(res.message || '援먰솚嫄곕? ?꾨즺', 'success')
      setRejectReasonModal(false)
      setExchangeActionItem(null)
    } catch (e) { showAlert(e instanceof Error ? e.message : '援먰솚嫄곕? ?ㅽ뙣', 'error') }
  }

  const handleExchangeAction = async (item: SambaCSInquiry, action: string) => {
    if (!item.market_order_id) {
      showAlert('二쇰Ц踰덊샇媛 ?놁뒿?덈떎', 'error')
      return
    }
    // 11踰덇? 援먰솚? returnApi ?ъ슜 (reship=approve, reject=reject)
    if (item.market === '11st' || item.market === '11踰덇?') {
      if (action === 'reship') { await handleElevenstExchangeApprove(item); return }
      if (action === 'reject') { handleElevenstExchangeReject(item); return }
    }
    // 湲고? 留덉폆(?ㅻ쭏?몄뒪?좎뼱 ?? ??湲곗〈 諛⑹떇 ?좎?
    const labels: Record<string, string> = { reship: '재배송 승인', reject: '교환 거부', convert_return: '반품 전환' }
    if (!await showConfirm(`${item.market_order_id} 二쇰Ц??${labels[action] || action} 泥섎━?섏떆寃좎뒿?덇퉴?`)) return
    try {
      const order = await orderApi.findByOrderNumber(item.market_order_id)
      if (!order) { showAlert('?대떦 二쇰Ц??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const res = await orderApi.exchangeAction(order.id, action)
      showAlert(res.message || `${labels[action]} ?꾨즺`, 'success')
      setExchangeActionItem(null)
    } catch (e) { showAlert(e instanceof Error ? e.message : `${labels[action]} ?ㅽ뙣`, 'error') }
  }

  const handleCancelApprove = async (item: SambaCSInquiry) => {
    if (!item.market_order_id) {
      showAlert('二쇰Ц踰덊샇媛 ?놁뒿?덈떎', 'error')
      return
    }
    if (!await showConfirm(`${item.market_order_id} 二쇰Ц??痍⑥냼?붿껌???뱀씤?섏떆寃좎뒿?덇퉴?`)) return
    try {
      const order = await orderApi.findByOrderNumber(item.market_order_id)
      if (!order) { showAlert('?대떦 二쇰Ц??李얠쓣 ???놁뒿?덈떎', 'error'); return }
      const res = await orderApi.approveCancel(order.id)
      showAlert(res.message || '痍⑥냼?뱀씤 ?꾨즺', 'success')
    } catch (e) { showAlert(e instanceof Error ? e.message : '痍⑥냼?뱀씤 ?ㅽ뙣', 'error') }
  }

  // ?쒗뵆由?愿由?紐⑤떖
  const [showTemplateManager, setShowTemplateManager] = useState(false)
  const [tplName, setTplName] = useState('')
  const [tplContent, setTplContent] = useState('')
  const tplContentRef = useRef<HTMLTextAreaElement>(null)
  const replyTextRef = useRef<HTMLTextAreaElement>(null)

  // 蹂???쒓렇 紐⑸줉 (CS/SMS/移댁뭅??怨듯넻)
  const VARIABLE_TAGS = [
    { tag: '{{sellerName}}', label: '?먮ℓ?먮챸' },
    { tag: '{{marketName}}', label: '?먮ℓ留덉폆?대쫫' },
    { tag: '{{OrderName}}', label: '二쇰Ц踰덊샇' },
    { tag: '{{rvcName}}', label: '?섏랬?몃챸' },
    { tag: '{{rcvHPNo}}', label: '수령인 연락처' },
    { tag: '{{goodsName}}', label: '상품명' },
  ]

  // textarea???쒓렇 ?쎌엯
  const isProductQuestion = (inquiry?: SambaCSInquiry | null) => inquiry?.inquiry_type === 'product_question'

  const sanitizeReplyTextForInquiry = (text: string, inquiry?: SambaCSInquiry | null) => {
    if (!isProductQuestion(inquiry)) return text
    return text
      .replace(/\{\{sellerName\}\}\s*怨좉컼??,\s]*/g, '')
      .replace(/\{\{sellerName\}\}\s*??,\s]*/g, '')
      .replace(/\{\{sellerName\}\}[^\S\r\n]*[^\s,.!?:;]+[^\S\r\n]*/g, '')
      .replace(/\{\{sellerName\}\}/g, '')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }

  const replyVariableTags = isProductQuestion(replyModal)
    ? VARIABLE_TAGS.filter(v => v.tag !== '{{sellerName}}')
    : VARIABLE_TAGS

  const insertTag = (ref: React.RefObject<HTMLTextAreaElement | null>, setter: (v: string) => void, getter: string, tag: string) => {
    const el = ref.current
    if (!el) { setter(getter + tag); return }
    const start = el.selectionStart
    const end = el.selectionEnd
    const newVal = getter.slice(0, start) + tag + getter.slice(end)
    setter(newVal)
    requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + tag.length; el.focus() })
  }

  // ?곗씠??濡쒕뱶
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [data, st, tpl] = await Promise.all([
        csInquiryApi.list({
          skip: page * pageSize,
          limit: pageSize,
          market: filterMarket || undefined,
          inquiry_type: filterType || undefined,
          reply_status: filterStatus || undefined,
          search: search || undefined,
          sort_desc: sortDesc,
          start_date: csCustomStart || undefined,
          end_date: csCustomEnd || undefined,
        }).catch(() => ({ items: [], total: 0 })),
        csInquiryApi.getStats().catch(() => ({})),
        csInquiryApi.getTemplates().catch(() => ({})),
      ])
      setInquiries(data.items)
      setTotal(data.total)
      setStats(st)
      setTemplates(tpl)
    } catch {
      // ?먮윭 臾댁떆
    }
    setLoading(false)
  }, [filterMarket, filterType, filterStatus, search, sortDesc, pageSize, page, csCustomStart, csCustomEnd])

  useEffect(() => { load() }, [load])
  useEffect(() => { accountApi.listActive().then(setAccounts).catch(() => {}) }, [])

  // 湲곌컙 踰꾪듉 ???좎쭨 怨꾩궛
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

  // 湲곌컙 醫낅즺??怨꾩궛 (吏?쒖＜/吏?쒕떖/?댁젣???대떦 湲곌컙 留덉?留???
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

  // 寃??
  const handleSearch = async () => {
    const ts = fmtTime
    // ?쒕∼?ㅼ슫 value ?뚯떛: "" = ?꾩껜, "market:XXX" = 留덉폆 ?⑥쐞, "account:ID" = 媛쒕퀎 怨꾩젙
    let selectedMarket: string | undefined
    let label: string
    if (csSyncAccountId.startsWith('market:')) {
      selectedMarket = csSyncAccountId.slice(7)
      label = selectedMarket
    } else if (csSyncAccountId.startsWith('account:')) {
      const accountId = csSyncAccountId.slice(8)
      selectedMarket = accounts.find(a => a.id === accountId)?.market_name
      label = selectedMarket || accountId
    } else {
      selectedMarket = undefined
      label = '?꾩껜留덉폆'
    }
    setCsLogMessages(prev => [...prev, `[${ts()}] ${label} CS 臾몄쓽 ?숆린??以?..`])
    try {
      const result = await csInquiryApi.syncFromMarkets(selectedMarket)
      setCsLogMessages(prev => [...prev, `[${ts()}] ${result.message}`])
      setPage(0)
      setSearch('')
      setSearchInput('')
      const [data, st, tpl] = await Promise.all([
        csInquiryApi.list({ skip: 0, limit: pageSize, sort_desc: sortDesc, market: filterMarket || undefined, start_date: csCustomStart || undefined, end_date: csCustomEnd || undefined }).catch(() => ({ items: [], total: 0 })),
        csInquiryApi.getStats().catch(() => ({})),
        csInquiryApi.getTemplates().catch(() => ({})),
      ])
      setInquiries(data.items)
      setTotal(data.total)
      setStats(st)
      setTemplates(tpl)
    } catch (err) {
      setCsLogMessages(prev => [...prev, `[${ts()}] ?숆린???ㅽ뙣: ${err}`])
    }
  }

  // ?꾩껜 ?좏깮
  const toggleAll = () => {
    if (selected.size === inquiries.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(inquiries.map(i => i.id)))
    }
  }

  // 媛쒕퀎 ?좏깮
  const toggleOne = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  // ?좏깮 ??젣
  const handleBatchDelete = async () => {
    if (selected.size === 0) {
      showAlert('??젣????ぉ???좏깮?댁＜?몄슂', 'error')
      return
    }
    if (!await showConfirm(`${selected.size}嫄댁쓣 ??젣?섏떆寃좎뒿?덇퉴?`)) return
    try {
      await csInquiryApi.batchDelete(Array.from(selected))
      setSelected(new Set())
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '??젣 ?ㅽ뙣', 'error')
    }
  }

  // ?듬? ?깅줉
  const handleReply = async () => {
    if (!replyModal || !replyText.trim()) {
      showAlert('?듬? ?댁슜???낅젰?댁＜?몄슂', 'error')
      return
    }
    try {
      const finalReplyText = sanitizeReplyTextForInquiry(replyText, replyModal)
      const res = await csInquiryApi.reply(replyModal.id, finalReplyText)
      const marketMsg = (res as unknown as Record<string, unknown>).market_message as string
      const marketSent = (res as unknown as Record<string, unknown>).market_sent as boolean
      setReplyModal(null)
      setReplyText('')
      setSelectedTemplate('')
      await load()
      if (marketSent) {
        showAlert(marketMsg || '?듬? ?깅줉 + 留덉폆 ?꾩넚 ?꾨즺', 'success')
      } else if (marketMsg) {
        showAlert(`?듬? ????꾨즺 (${marketMsg})`, 'info')
      }
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '?듬? ?깅줉 ?ㅽ뙣', 'error')
    }
  }

  // ?쒗뵆由??좏깮 ???듬?? 梨꾩슦湲?
  const applyTemplate = (key: string) => {
    setSelectedTemplate(key)
    if (key && templates[key]) {
      setReplyText(templates[key].content)
    }
  }

  // ?④굔 ??젣
  const handleDelete = async (id: string) => {
    if (!await showConfirm('??臾몄쓽瑜???젣?섏떆寃좎뒿?덇퉴?')) return
    try {
      await csInquiryApi.delete(id)
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '??젣 ?ㅽ뙣', 'error')
    }
  }

  // ?④린湲?
  const handleHide = async (id: string) => {
    if (!await showConfirm('??臾몄쓽瑜??④린?쒓쿋?듬땲源?')) return
    try {
      await csInquiryApi.hide(id)
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '?④린湲??ㅽ뙣', 'error')
    }
  }

  const totalPages = Math.ceil(total / pageSize)
  const pendingCount = (stats.pending as number) || 0
  const repliedCount = (stats.replied as number) || 0
  const totalCount = (stats.total as number) || 0
  const accountGroups = Object.values(
    accounts.reduce<Record<string, SambaMarketAccount[]>>((groups, account) => {
      const key = account.market_name || account.market_type || '湲고?'
      if (!groups[key]) groups[key] = []
      groups[key].push(account)
      return groups
    }, {})
  )
  const getCsAccountLabel = (account: SambaMarketAccount) => {
    return account.account_label?.trim() || account.seller_id?.trim() || account.business_name?.trim() || account.market_name
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* ?ㅻ뜑 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>CS 문의</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>
            판매마켓별 문의를 조회하고 수집할 수 있습니다.
          </p>
        </div>
      </div>

      {/* 濡쒓렇 ?곸뿭 */}
      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>CS 濡쒓렇</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(csLogMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>蹂듭궗</button>
            <button onClick={() => setCsLogMessages(['[SYSTEM] CS 로그를 초기화했습니다.'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={el => { if (el) el.scrollTop = el.scrollHeight }} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {csLogMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{msg}</p>)}
        </div>
      </div>

      {/* 湲곌컙 ?꾪꽣 諛?*/}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap', alignItems: 'center' }}>
          {PERIOD_BUTTONS.map(pb => (
            <button key={pb.key} onClick={() => {
              if (csDateLocked) return
              setCsPeriod(pb.key)
              if (!csStartLocked) {
                const start = getPeriodStart(pb.key)
                setCsCustomStart(start ? start.toLocaleDateString('sv-SE') : '')
              }
              setCsCustomEnd(getPeriodEnd(pb.key).toLocaleDateString('sv-SE'))
            }}
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: csPeriod === pb.key ? 'rgba(80,80,80,0.8)' : 'rgba(50,50,50,0.8)', border: csPeriod === pb.key ? '1px solid #666' : '1px solid #3D3D3D', color: csPeriod === pb.key ? '#fff' : '#C5C5C5', cursor: csDateLocked ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', opacity: csDateLocked && csPeriod !== pb.key ? 0.5 : 1 }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 4px' }} />
          <input type="date" value={csCustomStart} onChange={e => setCsCustomStart(e.target.value)} style={{ ...inputStyle, padding: '0 0.4rem', fontSize: '0.75rem', height: '28px', ...(csStartLocked ? { borderColor: '#C0392B', color: '#FF8C00' } : {}) }} />
          <button onClick={() => setCsStartLocked(p => !p)} style={{ padding: '0 0.5rem', fontSize: '0.72rem', height: '28px', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: csStartLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: csStartLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: csStartLocked ? '#fff' : '#C5C5C5' }}>怨좎젙</button>
          <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
          <input type="date" value={csCustomEnd} onChange={e => setCsCustomEnd(e.target.value)} style={{ ...inputStyle, padding: '0 0.4rem', fontSize: '0.75rem', height: '28px' }} />
          <button onClick={() => setCsDateLocked(p => !p)} style={{ padding: '0 0.5rem', fontSize: '0.72rem', height: '28px', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: csDateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: csDateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: csDateLocked ? '#fff' : '#C5C5C5' }}>怨좎젙</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <select value={csSyncAccountId} onChange={e => setCsSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0 0.4rem', fontSize: '0.75rem', height: '28px', minWidth: '140px' }}>
            <option value="">?꾩껜 怨꾩젙</option>
            {accountGroups.map(group => {
              const market = group[0]?.market_name || 'æ¹²e³??'
              return (
                <Fragment key={market}>
                  <option value={`market:${market}`}>{market}</option>
                  {group.map(account => (
                    <option key={account.id} value={`account:${account.id}`}>- {getCsAccountLabel(account)}</option>
                  ))}
                </Fragment>
              )
            })}
          </select>
          <button onClick={handleSearch} style={{ padding: '0 0.65rem', fontSize: '0.75rem', height: '28px', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>가져오기</button>
        </div>
      </div>

      {/* ?꾪꽣 諛?*/}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <select style={{ ...inputStyle, width: '68px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="customer">怨좉컼</option>
          <option value="order_number">二쇰Ц踰덊샇</option>
          <option value="product_id">?곹뭹踰덊샇</option>
          <option value="content">臾몄쓽?댁슜</option>
        </select>
        <input style={{ ...inputStyle, width: '120px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={searchInput} onChange={e => setSearchInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleSearch() }} />
        <button onClick={handleSearch} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0 0.6rem', borderRadius: '4px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap', height: '28px' }}>검색</button>
        <button
          onClick={() => setShowTemplateManager(true)}
          style={{ padding: '0 0.6rem', fontSize: '0.75rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap', marginLeft: '4px', height: '28px', lineHeight: '26px' }}
        >
          ?듬??쒗뵆由?愿由?
        </button>
        <button
          onClick={handleBatchDelete}
          style={{ padding: '0 0.6rem', fontSize: '0.75rem', background: 'transparent', border: '1px solid #FF6B6B33', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer', whiteSpace: 'nowrap', height: '28px', lineHeight: '26px' }}
        >
          ?좏깮??젣
        </button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '130px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={filterMarket} onChange={e => { setFilterMarket(e.target.value); setPage(0) }}>
            <option value="">?꾩껜留덉폆蹂닿린</option>
            {[...new Map(accounts.map(a => [a.market_type, a.market_name])).values()].map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <select style={{ ...inputStyle, width: '94px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={csSiteFilter} onChange={e => setCsSiteFilter(e.target.value)}>
            <option value="">?꾩껜?ъ씠?몃낫湲?/option>
            {['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','REXMONDE','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '95px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(0) }}>
            <option value="">?듬??곹깭</option>
            <option value="pending">誘몃떟蹂</option>
            <option value="replied">?듬??꾨즺</option>
          </select>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select style={{ ...inputStyle, width: '75px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} onChange={() => setSortDesc(!sortDesc)}>
            <option>-- ?뺣젹 --</option>
            <option>臾몄쓽?쇱옄??/option>
            <option>臾몄쓽?쇱옄??/option>
          </select>
          <select style={{ ...inputStyle, width: '78px', fontSize: '0.75rem', height: '28px', padding: '0 0.3rem' }} value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0) }}>
            <option value={50}>50媛?蹂닿린</option><option value={100}>100媛?蹂닿린</option><option value={200}>200媛?蹂닿린</option><option value={500}>500媛?蹂닿린</option>
          </select>
        </div>
      </div>

      {/* ?뚯씠釉?*/}
      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>濡쒕뵫 以?..</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #2D2D2D' }}>
                  <th style={{ width: '40px', padding: '0.75rem 0.5rem', textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={inquiries.length > 0 && selected.size === inquiries.length}
                      onChange={toggleAll}
                      style={{ accentColor: '#FF8C00' }}
                    />
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap', width: '80px' }}>
                    ?곹뭹
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>
                    留덉폆
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>
                    二쇰Ц踰덊샇
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>
                    臾몄쓽?좏삎
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>
                    怨좉컼
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', minWidth: '400px' }}>臾몄쓽?댁슜</th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>?듬??щ?</th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>
                    臾몄쓽?쇱떆<br /><span style={{ fontSize: '0.75rem' }}>(臾몄쓽?섏쭛?쇱옄)</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {inquiries.map(item => {
                  const st = REPLY_STATUS_MAP[item.reply_status] || REPLY_STATUS_MAP.pending
                  const tp = INQUIRY_TYPE_MAP[item.inquiry_type] || { label: item.inquiry_type, color: '#888' }
                  return (
                    <tr
                      key={item.id}
                      style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      {/* 泥댄겕諛뺤뒪 */}
                      <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', verticalAlign: 'top' }}>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggleOne(item.id)}
                          style={{ accentColor: '#FF8C00' }}
                        />
                      </td>

                      {/* ?ъ쭊 */}
                      <td style={{ padding: '0.75rem 0.5rem', verticalAlign: 'top', textAlign: 'center' }}>
                        {item.product_image ? (
                          <img
                            src={item.product_image}
                            alt=""
                            onClick={() => item.product_link && window.open(item.product_link, '_blank')}
                            style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', cursor: item.product_link ? 'pointer' : 'default' }}
                          />
                        ) : (
                          <div
                            onClick={() => item.product_link && window.open(item.product_link, '_blank')}
                            style={{ width: '60px', height: '60px', background: '#1A1A1A', borderRadius: '6px', border: '1px solid #2D2D2D', display: 'flex', alignItems: 'center', justifyContent: 'center', color: item.product_link ? '#4C9AFF' : '#444', fontSize: '0.625rem', cursor: item.product_link ? 'pointer' : 'default', textDecoration: item.product_link ? 'underline' : 'none', margin: '0 auto' }}
                          >
                            {item.product_link ? '留곹겕' : 'No IMG'}
                          </div>
                        )}
                        {item.market_inquiry_no && (
                          <div style={{ fontSize: '0.6rem', color: '#555', marginTop: '0.25rem', wordBreak: 'break-all' }}>{item.market_inquiry_no}</div>
                        )}
                      </td>

                      {/* 留덉폆 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap', textAlign: 'center' }}>
                        <div style={{ fontWeight: 600, color: '#E5E5E5' }}>
                          {item.market}
                        </div>
                        {item.account_name && (
                          <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.125rem' }}>{item.account_name}</div>
                        )}
                      </td>

                      {/* 二쇰Ц踰덊샇 + 留곹겕踰꾪듉 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                        <div style={{ fontSize: '0.8125rem', color: '#AAA', textAlign: 'center' }}>
                          {item.market_order_id || '-'}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginTop: '0.375rem', alignItems: 'center' }}>
                          <button
                            onClick={() => item.original_link ? window.open(item.original_link, '_blank') : showAlert('?뚯떛泥??먮Ц留곹겕媛 ?놁뒿?덈떎', 'info')}
                            style={{ fontSize: '0.72rem', padding: '0.15rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: item.original_link ? '#4C9AFF' : '#555', background: 'transparent', cursor: 'pointer', width: '100%', textAlign: 'center' }}
                          >?먮Ц留곹겕</button>
                          <button
                            onClick={() => {
                              const link = item.product_link || item.market_link
                              link ? window.open(link, '_blank') : showAlert('?먮ℓ 援щℓ?섏씠吏 留곹겕媛 ?놁뒿?덈떎', 'info')
                            }}
                            style={{ fontSize: '0.72rem', padding: '0.15rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: (item.product_link || item.market_link) ? '#51CF66' : '#555', background: 'transparent', cursor: 'pointer', width: '100%', textAlign: 'center' }}
                          >?먮ℓ留곹겕</button>
                          <button
                            onClick={() => {
                              if (item.collected_product_id) {
                                window.open(`/samba/products?search=${encodeURIComponent(item.collected_product_id)}&search_type=id&highlight=${item.collected_product_id}`, '_blank')
                              } else if (item.product_name) {
                                window.open(`/samba/products?search=${encodeURIComponent(item.product_name)}`, '_blank')
                              } else {
                                showAlert('?곌껐???곹뭹 ?뺣낫媛 ?놁뒿?덈떎', 'info')
                              }
                            }}
                            style={{ fontSize: '0.72rem', padding: '0.15rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: item.collected_product_id ? '#FF8C00' : '#555', background: 'transparent', cursor: 'pointer', width: '100%', textAlign: 'center' }}
                          >?곹뭹?뺣낫</button>
                        </div>
                      </td>

                      {/* 臾몄쓽?좏삎 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top', textAlign: 'center' }}>
                        {item.inquiry_type === 'exchange_request' ? (
                          <button
                            onClick={() => setExchangeActionItem(item)}
                            style={{ padding: '0.15rem 0.5rem', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 600, background: `${tp.color}22`, color: tp.color, border: `1px solid ${tp.color}44`, cursor: 'pointer' }}
                          >
                            {tp.label}
                          </button>
                        ) : item.inquiry_type === 'cancel_request' ? (
                          <button
                            onClick={() => handleCancelApprove(item)}
                            style={{ padding: '0.15rem 0.5rem', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 600, background: `${tp.color}22`, color: tp.color, border: `1px solid ${tp.color}44`, cursor: 'pointer' }}
                          >
                            {tp.label}
                          </button>
                        ) : (
                          <span style={{ padding: '0.15rem 0.5rem', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 600, background: `${tp.color}22`, color: tp.color }}>
                            {tp.label}
                          </span>
                        )}
                      </td>

                      {/* 怨좉컼 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top', textAlign: 'center' }}>
                        <div style={{ fontSize: '0.8125rem', color: '#AAA' }}>
                          {item.questioner || '-'}
                        </div>
                      </td>

                      {/* 臾몄쓽?댁슜 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                        {/* ?곹뭹紐?+ ?듬? + 留곹겕 */}
                        <div style={{ marginBottom: '0.5rem' }}>
                          {item.product_name && (
                            <span style={{ fontWeight: 600, color: '#E5E5E5', fontSize: '0.8125rem' }}>
                              {item.product_name}
                            </span>
                          )}
                          <button
                            onClick={() => { setReplyModal(item); setReplyText(sanitizeReplyTextForInquiry(item.reply || '', item)); setSelectedTemplate('') }}
                            style={{ marginLeft: item.product_name ? '0.375rem' : 0, padding: '0.1rem 0.4rem', background: item.reply_status === 'pending' ? 'rgba(255,140,0,0.15)' : 'rgba(81,207,102,0.1)', border: `1px solid ${item.reply_status === 'pending' ? 'rgba(255,140,0,0.3)' : 'rgba(81,207,102,0.3)'}`, borderRadius: '4px', color: item.reply_status === 'pending' ? '#FF8C00' : '#51CF66', fontSize: '0.6875rem', cursor: 'pointer', whiteSpace: 'nowrap', verticalAlign: 'middle' }}
                          >
                            {item.reply_status === 'pending' ? '?듬?' : '?듬??섏젙'}
                          </button>
                        </div>

                        {/* 臾몄쓽 ?댁슜 */}
                        <div style={{ color: '#ccc', fontSize: '0.8125rem', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {htmlToText(item.content)}
                        </div>

                        {/* ?듬? ?댁슜 */}
                        {item.reply && (
                          <div style={{ marginTop: '0.5rem', padding: '0.5rem 0.75rem', background: 'rgba(81,207,102,0.08)', borderRadius: '6px', borderLeft: '3px solid #51CF66' }}>
                            <div style={{ fontSize: '0.75rem', color: '#51CF66', marginBottom: '0.25rem', fontWeight: 600 }}>?듬?</div>
                            <div style={{ color: '#aaa', fontSize: '0.8125rem', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                              {htmlToText(item.reply || '')}
                            </div>
                            {item.replied_at && (
                              <div style={{ fontSize: '0.6875rem', color: '#555', marginTop: '0.25rem' }}>
                                [{new Date(item.replied_at).toLocaleString('ko-KR')}]
                              </div>
                            )}
                          </div>
                        )}
                      </td>

                      {/* ?듬? ?щ? */}
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'center', verticalAlign: 'top' }}>
                        <span style={{
                          padding: '0.25rem 0.625rem',
                          borderRadius: '20px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          background: st.bg,
                          color: st.text,
                        }}>
                          {st.label}
                        </span>
                      </td>

                      {/* 臾몄쓽?쇱떆 + ?≪뀡 */}
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'center', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                        <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>
                          {fmtDate(item.inquiry_date)}
                        </div>
                        <div style={{ fontSize: '0.6875rem', color: '#555', marginBottom: '0.5rem' }}>
                          {fmtDate(item.collected_at)}
                        </div>
                        <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'center' }}>
                          <button
                            onClick={() => handleDelete(item.id)}
                            style={{ padding: '0.25rem 0.5rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.2)', borderRadius: '4px', color: '#FF6B6B', fontSize: '0.6875rem', cursor: 'pointer' }}
                          >
                            ??젣
                          </button>
                          <button
                            onClick={() => handleHide(item.id)}
                            style={{ padding: '0.25rem 0.5rem', background: 'rgba(136,136,136,0.1)', border: '1px solid rgba(136,136,136,0.2)', borderRadius: '4px', color: '#888', fontSize: '0.6875rem', cursor: 'pointer' }}
                          >
                            ?④린湲?
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {inquiries.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>
                      臾몄쓽 ?댁뿭???놁뒿?덈떎
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* ?섏씠吏?ㅼ씠??*/}
        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', padding: '1rem', borderTop: '1px solid #2D2D2D' }}>
            <button
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
              style={{ padding: '0.375rem 0.75rem', background: page === 0 ? '#1A1A1A' : '#2A2A2A', border: '1px solid #2D2D2D', borderRadius: '4px', color: page === 0 ? '#444' : '#E5E5E5', fontSize: '0.8125rem', cursor: page === 0 ? 'default' : 'pointer' }}
            >
              ?댁쟾
            </button>
            <span style={{ fontSize: '0.8125rem', color: '#888' }}>
              {page + 1} / {totalPages} ({fmtNum(total)}嫄?
            </span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
              style={{ padding: '0.375rem 0.75rem', background: page >= totalPages - 1 ? '#1A1A1A' : '#2A2A2A', border: '1px solid #2D2D2D', borderRadius: '4px', color: page >= totalPages - 1 ? '#444' : '#E5E5E5', fontSize: '0.8125rem', cursor: page >= totalPages - 1 ? 'default' : 'pointer' }}
            >
              ?ㅼ쓬
            </button>
          </div>
        )}
      </div>

      {/* ?듬? 紐⑤떖 */}
      {replyModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '720px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>?듬? ?묒꽦</h3>
              <button onClick={() => setReplyModal(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>??/button>
            </div>

            {/* 臾몄쓽 ?뺣낫 */}
            <div style={{ background: '#111', borderRadius: '8px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.8125rem' }}>
              <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '0.375rem' }}>
                <div><span style={{ color: '#666' }}>留덉폆: </span><span style={{ color: '#E5E5E5', fontWeight: 600 }}>{replyModal.market}</span></div>
                {replyModal.questioner && <div><span style={{ color: '#666' }}>吏덈Ц?? </span><span style={{ color: '#E5E5E5' }}>{replyModal.questioner}</span></div>}
              </div>
              {replyModal.product_name && <div style={{ color: '#aaa', marginBottom: '0.375rem' }}>{replyModal.product_name}</div>}
              <div style={{ color: '#ccc', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>{htmlToText(replyModal.content || '')}</div>
            </div>

            {/* ?쒗뵆由?移대뱶 洹몃━??*/}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem', marginBottom: '0.75rem' }}>
              {Object.entries(templates).map(([key, tpl]) => (
                <div
                  key={key}
                  onClick={() => { setSelectedTemplate(key); setReplyText(sanitizeReplyTextForInquiry(tpl.content, replyModal)) }}
                  style={{ background: selectedTemplate === key ? 'rgba(255,140,0,0.08)' : '#111', border: `1px solid ${selectedTemplate === key ? '#FF8C00' : '#2D2D2D'}`, borderRadius: '8px', padding: '0.625rem', cursor: 'pointer', transition: 'border-color 0.15s' }}
                  onMouseEnter={e => { if (selectedTemplate !== key) e.currentTarget.style.borderColor = '#444' }}
                  onMouseLeave={e => { if (selectedTemplate !== key) e.currentTarget.style.borderColor = '#2D2D2D' }}
                >
                  <div style={{ fontSize: '0.75rem', fontWeight: 600, color: selectedTemplate === key ? '#FF8C00' : '#E5E5E5', marginBottom: '0.375rem' }}>{tpl.name}</div>
                  <div style={{ fontSize: '0.625rem', color: '#777', lineHeight: '1.4', maxHeight: '3.5rem', overflow: 'hidden', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{tpl.content.slice(0, 80)}...</div>
                </div>
              ))}
            </div>

            {/* 蹂???쒓렇 踰꾪듉 */}
            <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
              {replyVariableTags.map(v => (
                <button
                  key={v.tag}
                  type="button"
                  onClick={() => insertTag(replyTextRef, setReplyText, replyText, v.tag)}
                  style={{ padding: '0.2rem 0.5rem', fontSize: '0.6875rem', background: '#1A1A1A', border: '1px solid #444', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
                >{v.tag} <span style={{ color: '#888' }}>{v.label}</span></button>
              ))}
            </div>

            {/* ?듬? ?낅젰 */}
            <textarea
              ref={replyTextRef}
              value={replyText}
              onChange={e => setReplyText(e.target.value)}
              placeholder="?듬? ?댁슜???낅젰?섏꽭??
              rows={6}
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', marginBottom: '1rem' }}
            />

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setReplyModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>痍⑥냼</button>
              <button onClick={handleReply} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>?듬? ?깅줉</button>
            </div>
          </div>
        </div>
      )}

      {/* ?듬? ?쒗뵆由?愿由?紐⑤떖 */}
      {showTemplateManager && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '600px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>?듬? ?쒗뵆由?愿由?/h3>
              <button onClick={() => setShowTemplateManager(false)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>??/button>
            </div>

            {/* ?쒗뵆由?異붽? ??*/}
            <div style={{ background: '#111', borderRadius: '8px', padding: '1rem', border: '1px solid #2A2A2A', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                <input
                  placeholder="?쒗뵆由??대쫫"
                  value={tplName}
                  onChange={e => setTplName(e.target.value)}
                  style={{ ...inputStyle, flex: 1 }}
                />
              </div>
              <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                {VARIABLE_TAGS.map(v => (
                  <button
                    key={v.tag}
                    type="button"
                    onClick={() => insertTag(tplContentRef, setTplContent, tplContent, v.tag)}
                    style={{ padding: '0.2rem 0.5rem', fontSize: '0.6875rem', background: '#1A1A1A', border: '1px solid #444', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
                  >{v.tag} <span style={{ color: '#888' }}>{v.label}</span></button>
                ))}
              </div>
              <textarea
                ref={tplContentRef}
                placeholder="?쒗뵆由??댁슜"
                value={tplContent}
                onChange={e => setTplContent(e.target.value)}
                rows={5}
                style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5', marginBottom: '0.5rem' }}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  onClick={async () => {
                    if (!tplName.trim() || !tplContent.trim()) {
                      showAlert('?대쫫怨??댁슜???낅젰?댁＜?몄슂', 'error')
                      return
                    }
                    const key = tplName.trim().replace(/\s+/g, '_').toLowerCase()
                    try {
                      await csInquiryApi.addTemplate(key, tplName.trim(), tplContent.trim())
                      setTplName('')
                      setTplContent('')
                      load()
                    } catch (e) {
                      showAlert(e instanceof Error ? e.message : '?쒗뵆由?異붽? ?ㅽ뙣', 'error')
                    }
                  }}
                  style={{ padding: '0.4rem 1rem', background: '#FF8C00', border: 'none', borderRadius: '6px', color: '#fff', fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer' }}
                >異붽?</button>
              </div>
            </div>

            {/* 湲곗〈 ?쒗뵆由?紐⑸줉 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {Object.entries(templates).map(([key, tpl]) => (
                <div key={key} style={{ background: '#111', borderRadius: '8px', padding: '0.75rem 1rem', border: '1px solid #2A2A2A' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.375rem' }}>
                    <span style={{ fontSize: '0.875rem', fontWeight: 600, color: '#FF8C00' }}>{tpl.name}</span>
                    <button
                      onClick={async () => {
                        if (!await showConfirm(`"${tpl.name}" ?쒗뵆由우쓣 ??젣?섏떆寃좎뒿?덇퉴?`)) return
                        try {
                          await csInquiryApi.deleteTemplate(key)
                          load()
                        } catch (e) {
                          showAlert(e instanceof Error ? e.message : '??젣 ?ㅽ뙣', 'error')
                        }
                      }}
                      style={{ padding: '0.15rem 0.5rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.2)', borderRadius: '4px', color: '#FF6B6B', fontSize: '0.6875rem', cursor: 'pointer' }}
                    >??젣</button>
                  </div>
                  <p style={{ fontSize: '0.8125rem', color: '#aaa', lineHeight: '1.5', whiteSpace: 'pre-wrap', margin: 0 }}>
                    {tpl.content}
                  </p>
                </div>
              ))}
              {Object.keys(templates).length === 0 && (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>
                  ?깅줉???쒗뵆由우씠 ?놁뒿?덈떎
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button onClick={() => setShowTemplateManager(false)} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>?リ린</button>
            </div>
          </div>
        </div>
      )}
      {/* 援먰솚 ?≪뀡 ?좏깮 紐⑤떖 */}
      {exchangeActionItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '360px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.5rem' }}>援먰솚?붿껌 泥섎━</h3>
            <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1.5rem' }}>二쇰Ц踰덊샇: {exchangeActionItem.market_order_id || '-'}</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <button
                onClick={() => handleExchangeAction(exchangeActionItem, 'reship')}
                style={{ padding: '0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '8px', color: '#4C9AFF', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
              >援먰솚?щ같??/button>
              <button
                onClick={() => handleExchangeAction(exchangeActionItem, 'reject')}
                style={{ padding: '0.75rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', borderRadius: '8px', color: '#FF6B6B', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
              >援먰솚嫄곕?</button>
              <button
                onClick={() => handleExchangeAction(exchangeActionItem, 'convert_return')}
                style={{ padding: '0.75rem', background: 'rgba(255,165,0,0.1)', border: '1px solid rgba(255,165,0,0.3)', borderRadius: '8px', color: '#FFA500', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
              >諛섑뭹蹂寃?/button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button onClick={() => setExchangeActionItem(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>?リ린</button>
            </div>
          </div>
        </div>
      )}

      {/* 11踰덇? 援먰솚 嫄곕? ?ъ쑀 ?낅젰 紐⑤떖 */}
      {rejectReasonModal && rejectTargetItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 101 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.5rem' }}>援먰솚嫄곕? ?ъ쑀 ?낅젰</h3>
            <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1.25rem' }}>二쇰Ц踰덊샇: {rejectTargetItem.market_order_id || '-'}</p>
            <input
              type="text"
              value={rejectReasonText}
              onChange={e => setRejectReasonText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submitElevenstExchangeReject() }}
              placeholder="嫄곕? ?ъ쑀瑜??낅젰?섏꽭??
              autoFocus
              style={{ width: '100%', padding: '0.625rem 0.75rem', background: '#111', border: '1px solid #444', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem', boxSizing: 'border-box', marginBottom: '1.25rem' }}
            />
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setRejectReasonModal(false); setRejectTargetItem(null) }}
                style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}
              >痍⑥냼</button>
              <button
                onClick={submitElevenstExchangeReject}
                style={{ padding: '0.625rem 1.25rem', background: 'rgba(255,107,107,0.15)', border: '1px solid rgba(255,107,107,0.4)', borderRadius: '8px', color: '#FF6B6B', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
              >嫄곕? ?뺤젙</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

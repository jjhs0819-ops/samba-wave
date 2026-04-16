'use client'

import { useEffect, useState, useCallback, useRef, Fragment } from 'react'
import { accountApi, orderApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { returnApi, type SambaReturn } from '@/lib/samba/api/support'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { card, inputStyle, fmtNum } from '@/lib/samba/styles'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { fmtTime } from '@/lib/samba/utils'

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  requested: { label: '요청됨', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  approved:  { label: '승인됨', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  rejected:  { label: '거절됨', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  completed: { label: '완료됨', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelled: { label: '취소됨', bg: 'rgba(100,100,100,0.2)', text: '#888' },
  collecting:    { label: '수거중', bg: 'rgba(255,165,0,0.15)', text: '#FFA500' },
  collected:     { label: '수거완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  not_collected: { label: '미수거', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
}

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  return:   { label: '반품', color: '#FF6B6B' },
  exchange: { label: '교환', color: '#4C9AFF' },
  cancel:   { label: '취소', color: '#888' },
}

// 구버전 반품사유 목록
const RETURN_REASONS = [
  { value: '', label: '직접입력' },
  { value: '상품 불량/파손', label: '상품 불량/파손' },
  { value: '사이즈 불일치', label: '사이즈 불일치' },
  { value: '색상/디자인 불일치', label: '색상/디자인 불일치' },
  { value: '배송 중 파손', label: '배송 중 파손' },
  { value: '오배송 (다른 상품)', label: '오배송 (다른 상품)' },
  { value: '단순 변심', label: '단순 변심' },
  { value: '상품 설명과 다름', label: '상품 설명과 다름' },
  { value: '배송 지연', label: '배송 지연' },
  { value: '주문 실수', label: '주문 실수' },
  { value: '품질 불만족', label: '품질 불만족' },
]

// 날짜 → M/D 포맷 (예: "2026-03-25" → "3/25")
const fmtMD = (d?: string | null) => {
  if (!d) return '-'
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return '-'
  return `${dt.getMonth() + 1}/${dt.getDate()}`
}

const getAccountOptionLabel = (account: SambaMarketAccount) => (
  account.account_label?.trim()
  || account.seller_id?.trim()
  || account.business_name?.trim()
  || account.market_name
)

const tdCenter = { padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' as const, textAlign: 'center' as const, verticalAlign: 'middle' as const }

export default function ReturnsPage() {
  useEffect(() => { document.title = 'SAMBA-반품관리' }, [])
  const [returns, setReturns] = useState<SambaReturn[]>([])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [stats, setStats] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [detailItem, setDetailItem] = useState<SambaReturn | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  const [form, setForm] = useState({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })

  // 로그 + 검색/필터 상태
  const logRef = useRef<HTMLDivElement>(null)
  const [logMessages, _setLogMessagesRaw] = useState<string[]>(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])
  const setLogMessages: typeof _setLogMessagesRaw = (v) => _setLogMessagesRaw(prev => {
    const next = typeof v === 'function' ? v(prev) : v
    return next.slice(-30)
  })
  const [period, setPeriod] = useState('thisyear')
  const [syncAccountId, setSyncAccountId] = useState('')
  const [customStart, setCustomStart] = useState(`${new Date().getFullYear()}-01-01`)
  const [customEnd, setCustomEnd] = useState(new Date().toLocaleDateString('sv-SE'))
  const [startLocked, setStartLocked] = useState(false)
  const [dateLocked, setDateLocked] = useState(false)
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])

  useEffect(() => { accountApi.listActive().then(setAccounts).catch(() => {}) }, [])
  useEffect(() => { logRef.current && (logRef.current.scrollTop = logRef.current.scrollHeight) }, [logMessages])

  // 기간 버튼 → 날짜 계산
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

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const [searchCategory, setSearchCategory] = useState('customer')
  const [searchText, setSearchText] = useState('')
  const [marketFilter, setMarketFilter] = useState('')
  const [siteFilter, setSiteFilter] = useState('진행중')
  const [marketStatus, setMarketStatus] = useState('')
  const [inputFilter, setInputFilter] = useState('')
  const [pageSize, setPageSize] = useState(50)

  const load = useCallback(async () => {
    setLoading(true)
    const [data, st] = await Promise.all([
      returnApi.list(undefined, filterStatus || undefined, filterType || undefined, 500, customStart || undefined, customEnd || undefined).catch(() => []),
      returnApi.getStats().catch(() => ({})),
    ])
    setReturns(data)
    setStats(st)
    setLoading(false)
  }, [filterStatus, filterType, customStart, customEnd])

  useEffect(() => { load() }, [load])

  // 가져오기 버튼 — 마켓 동기화 후 DB 데이터 로드
  const loadReturns = async () => {
    const ts = fmtTime

    // 마켓타입 선택 시 해당 마켓 계정들만 순회 동기화
    if (syncAccountId.startsWith('type:')) {
      const marketType = syncAccountId.replace('type:', '')
      const marketAccs = accounts.filter(a => a.market_type === marketType)
      const marketName = marketAccs[0]?.market_name || marketType
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 반품교환 동기화 시작 (${marketAccs.length}개 계정)...`])
      let totalSynced = 0
      for (const acc of marketAccs) {
        try {
          const syncResult = await returnApi.syncFromMarkets(30, acc.id)
          for (const r of syncResult.results) {
            if (r.status === 'success') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${fmtNum(r.fetched ?? 0)}건 조회, ${fmtNum(r.synced ?? 0)}건 신규`])
            } else if (r.status === 'error') {
              setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
            }
          }
          totalSynced += syncResult.total_synced
        } catch (e) {
          setLogMessages(prev => [...prev, `[${ts()}] ${acc.market_name}(${acc.seller_id || '-'}) 오류: ${e}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] ${marketName} 동기화 완료 (신규 ${fmtNum(totalSynced)}건)`])
      await load()
      return
    }

    // 전체마켓 또는 개별 계정 동기화
    const isAll = !syncAccountId
    const label = isAll ? '전체마켓' : (accounts.find(a => a.id === syncAccountId)?.market_name || syncAccountId)
    setLogMessages(prev => [...prev, `[${ts()}] ${label} 반품교환 동기화 중...`])
    try {
      const syncResult = await returnApi.syncFromMarkets(30, isAll ? undefined : syncAccountId)
      for (const r of syncResult.results) {
        if (r.status === 'success') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: ${fmtNum(r.fetched ?? 0)}건 조회, ${fmtNum(r.synced ?? 0)}건 신규`])
        } else if (r.status === 'error') {
          setLogMessages(prev => [...prev, `[${ts()}] ${r.account}: 오류 — ${r.message}`])
        }
      }
      setLogMessages(prev => [...prev, `[${ts()}] 동기화 완료 (신규 ${fmtNum(syncResult.total_synced)}건)`])
    } catch (e) {
      setLogMessages(prev => [...prev, `[오류] 동기화 실패: ${e}`])
    }
    await load()
  }

  const handleSubmit = async () => {
    try {
      const reason = form.reason || form.customReason
      if (!reason) {
        showAlert('반품/교환 사유를 입력해주세요', 'error')
        return
      }
      await returnApi.create({
        order_id: form.order_id,
        type: form.type,
        reason,
        quantity: form.quantity,
        requested_amount: form.requested_amount || undefined,
      })
      setShowForm(false)
      setForm({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '저장 실패', 'error')
    }
  }

  const [rejectModal, setRejectModal] = useState<{ id: string; reason: string } | null>(null)
  const [locationModal, setLocationModal] = useState<{ id: string; value: string; address: string } | null>(null)

  const handleApprove = async (id: string) => {
    try { await returnApi.approve(id); load() }
    catch (e) { showAlert(e instanceof Error ? e.message : '승인 실패', 'error') }
  }
  const handleReject = (id: string) => {
    setRejectModal({ id, reason: '' })
  }
  const submitReject = async () => {
    if (!rejectModal || !rejectModal.reason.trim()) {
      showAlert('거절 사유를 입력해주세요', 'error')
      return
    }
    try {
      await returnApi.reject(rejectModal.id, rejectModal.reason)
      setRejectModal(null)
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : '거절 처리 실패', 'error') }
  }
  const handleComplete = async (id: string) => {
    try { await returnApi.complete(id); load() }
    catch (e) { showAlert(e instanceof Error ? e.message : '완료 처리 실패', 'error') }
  }
  const handleCancel = async (id: string) => {
    if (!await showConfirm('취소하시겠습니까?')) return
    try { await returnApi.cancel(id); load() }
    catch (e) { showAlert(e instanceof Error ? e.message : '취소 실패', 'error') }
  }

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) {
      showAlert('삭제할 항목을 선택해주세요', 'info')
      return
    }
    if (!await showConfirm(`${selectedIds.size}건을 삭제하시겠습니까?`)) return
    let deleted = 0
    for (const id of selectedIds) {
      try {
        await returnApi.cancel(id)
        deleted++
      } catch (_e) { /* 무시 */ }
    }
    setSelectedIds(new Set())
    load()
    showAlert(`${fmtNum(deleted)}건 삭제 완료`, 'success')
  }

  // 교환/취소 액션
  const [exchangeActionItem, setExchangeActionItem] = useState<SambaReturn | null>(null)
  const [reshipStep, setReshipStep] = useState(false) // 교환재배송 송장 입력 단계
  const [reshipForm, setReshipForm] = useState({ tracking_number: '', shipping_company: '롯데택배' })

  const handleExchangeAction = async (r: SambaReturn, action: string, extra?: { tracking_number?: string; shipping_company?: string }) => {
    const orderNum = r.order_number || r.order_id
    if (!orderNum) { showAlert('주문번호가 없습니다', 'error'); return }
    const labels: Record<string, string> = { reship: '교환재배송', reject: '교환거부', convert_return: '반품변경' }
    if (!await showConfirm(`${orderNum} 주문을 ${labels[action]} 처리하시겠습니까?`)) return
    try {
      const order = await orderApi.findByOrderNumber(orderNum)
      if (!order) { showAlert('해당 주문을 찾을 수 없습니다', 'error'); return }
      const res = await orderApi.exchangeAction(order.id, action, undefined, extra)
      showAlert(res.message || `${labels[action]} 완료`, 'success')
      setExchangeActionItem(null)
      setReshipStep(false)
      setReshipForm({ tracking_number: '', shipping_company: '롯데택배' })
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : `${labels[action]} 실패`, 'error') }
  }

  const handleCancelApprove = async (r: SambaReturn) => {
    const orderNum = r.order_number || r.order_id
    if (!orderNum) { showAlert('주문번호가 없습니다', 'error'); return }
    if (!await showConfirm(`${orderNum} 주문의 취소요청을 승인하시겠습니까?`)) return
    try {
      const order = await orderApi.findByOrderNumber(orderNum)
      if (!order) { showAlert('해당 주문을 찾을 수 없습니다', 'error'); return }
      const res = await orderApi.approveCancel(order.id)
      showAlert(res.message || '취소승인 완료', 'success')
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : '취소승인 실패', 'error') }
  }

  const handleReturnAction = async (r: SambaReturn, action: string) => {
    const orderNum = r.order_number || r.order_id
    if (!orderNum) { showAlert('주문번호가 없습니다', 'error'); return }
    const label = action === 'approve' ? '반품승인' : '반품거부'
    if (!await showConfirm(`${orderNum} 주문을 ${label} 처리하시겠습니까?`)) return
    try {
      const order = await orderApi.findByOrderNumber(orderNum)
      if (!order) { showAlert('해당 주문을 찾을 수 없습니다', 'error'); return }
      const res = await orderApi.returnAction(order.id, action)
      showAlert(res.message || `${label} 완료`, 'success')
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : `${label} 실패`, 'error') }
  }

  // 수익총액 계산 (정산금액 - 환수금액)
  const totalProfit = returns
    .reduce((sum, r) => sum + ((r.settlement_amount || 0) - (r.recovery_amount || 0)), 0)

  // completion_detail 기준 통계
  const completionCounts = {
    total: returns.length,
    requested: returns.filter(r => (r.completion_detail || '진행중') === '진행중').length,
    completed: returns.filter(r => ['취소', '교환', '반품'].includes(r.completion_detail || '')).length,
    rejected: returns.filter(r => (r.completion_detail || '') === '거부').length,
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 숫자 input 스피너 제거 */}
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
        <a href="/samba/orders" style={{ fontSize: '0.75rem', color: '#888', textDecoration: 'none' }}>← 주문</a>
        <a href="/samba/cs" style={{ fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none' }}>CS →</a>
      </div>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>반품교환</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>반품교환 요청을 관리합니다</p>
        </div>
      </div>

      {/* 통계 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        {[
          { key: 'total', label: '전체', color: '#FF8C00' },
          { key: 'requested', label: '진행내역', color: '#FFD93D' },
          { key: 'completed', label: '완료됨', color: '#51CF66' },
          { key: 'rejected', label: '거절됨', color: '#FF6B6B' },
        ].map(({ key, label, color }) => (
          <div key={key} style={{ ...card, padding: '1rem 1.25rem' }}>
            <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.375rem' }}>{label}</p>
            <p style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{fmtNum(completionCounts[key as keyof typeof completionCounts] ?? 0)}{key === 'requested' ? '건' : ''}</p>
          </div>
        ))}
        {/* 수익총액 통계 */}
        <div style={{ ...card, padding: '1rem 1.25rem', border: `1px solid ${totalProfit >= 0 ? 'rgba(81,207,102,0.2)' : 'rgba(255,107,107,0.2)'}` }}>
          <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.375rem' }}>수익총액</p>
          <p style={{ fontSize: '1.25rem', fontWeight: 700, color: totalProfit >= 0 ? '#51CF66' : '#FF6B6B' }}>₩{fmtNum(totalProfit)}</p>
        </div>
      </div>

      {/* 사유별 분포 */}
      {false && stats.by_reason && Object.keys(stats.by_reason).length > 0 && (() => {
        const reasons = stats.by_reason as Record<string, number>
        const sorted = Object.entries(reasons).sort((a, b) => b[1] - a[1])
        const maxVal = Math.max(...sorted.map(([, v]) => v), 1)
        return (
          <div style={{ ...card, padding: '1rem 1.25rem', marginBottom: '1rem' }}>
            <div style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#FF8C00', marginBottom: '0.625rem' }}>사유별 분포</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {sorted.map(([reason, count]) => (
                <div key={reason} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem' }}>
                  <span style={{ width: '100px', color: '#999', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{reason}</span>
                  <div style={{ flex: 1, height: '14px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{ width: `${(count / maxVal) * 100}%`, height: '100%', background: '#FF8C00', borderRadius: '3px' }} />
                  </div>
                  <span style={{ width: '30px', textAlign: 'right', color: '#E5E5E5', fontWeight: 600 }}>{count}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })()}

      {/* 로그 영역 */}
      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>반품교환 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div ref={logRef} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
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
          <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: '#C0392B', color: '#FF8C00' } : {}) }} />
          <button onClick={() => setStartLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: startLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: startLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: startLocked ? '#fff' : '#C5C5C5' }}>고정</button>
          <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
          <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <button onClick={() => setDateLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: dateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: dateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: dateLocked ? '#fff' : '#C5C5C5' }}>고정</button>
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
                  items.push({ value: a.id, label: `  ${getAccountOptionLabel(a)}`, isGroup: false })
                })
              })
              return items.map(item => (
                <option key={item.value} value={item.value} style={{ fontWeight: item.isGroup ? 600 : 400 }}>{item.label}</option>
              ))
            })()}
          </select>
          <button onClick={loadReturns} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>가져오기</button>
        </div>
      </div>

      {/* 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <select style={{ ...inputStyle, width: '80px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">상품</option>
          <option value="customer">고객</option>
          <option value="product_id">상품번호</option>
          <option value="order_number">주문번호</option>
        </select>
        <input style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadReturns() }} />
        <button onClick={loadReturns} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        <button
          onClick={handleBatchDelete}
          style={{ padding: '0.22rem 0.6rem', fontSize: '0.75rem', background: 'transparent', border: '1px solid #FF6B6B33', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer', whiteSpace: 'nowrap' }}
        >
          선택삭제
        </button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체마켓보기</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
              const items: { value: string; label: string; isGroup: boolean }[] = []
              marketTypes.forEach(([type, name]) => {
                items.push({ value: `type:${type}`, label: name, isGroup: true })
                accounts.filter(a => a.market_type === type).forEach(a => {
                  items.push({ value: `acc:${a.id}`, label: `  ${getAccountOptionLabel(a)}`, isGroup: false })
                })
              })
              return items.map(item => (
                <option key={item.value} value={item.value} style={{ fontWeight: item.isGroup ? 600 : 400 }}>{item.label}</option>
              ))
            })()}
          </select>
          <select style={{ ...inputStyle, width: '110px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}><option value="">전체내역</option>{['진행중','취소','교환','반품','거부'].map(s => <option key={s} value={s}>{s}</option>)}</select>
          <select style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
          </select>
        </div>
      </div>

      {/* 등록 폼 */}
      {showForm && (
        <div style={{ ...card, padding: '1.5rem', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>반품/교환 등록</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>주문 ID</label>
              <input style={inputStyle} value={form.order_id} onChange={(e) => setForm({ ...form, order_id: e.target.value })} />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>유형</label>
              <select style={inputStyle} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value='return'>반품</option>
                <option value='exchange'>교환</option>
                <option value='cancel'>취소</option>
              </select>
            </div>
            {/* 반품사유 드롭다운 */}
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>사유 선택</label>
              <select
                style={inputStyle}
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              >
                {RETURN_REASONS.map(r => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            {/* 직접입력 시 텍스트 필드 */}
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>
                {form.reason ? '추가 상세 사유' : '사유 직접입력'}
              </label>
              <input
                style={inputStyle}
                value={form.customReason}
                onChange={(e) => setForm({ ...form, customReason: e.target.value })}
                placeholder={form.reason ? '추가 설명 (선택)' : '반품/교환 사유를 입력하세요'}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>수량</label>
              <input type='number' style={inputStyle} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.375rem', display: 'block' }}>요청 금액</label>
              <input type='number' style={inputStyle} value={form.requested_amount} onChange={(e) => setForm({ ...form, requested_amount: Number(e.target.value) })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button onClick={() => setShowForm(false)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
            <button onClick={handleSubmit} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>저장</button>
          </div>
        </div>
      )}

      {/* 테이블 */}
      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #1E1E1E' }}>
                  <th rowSpan={2} style={{ width: '36px', textAlign: 'center', padding: '0.3rem 0.5rem', verticalAlign: 'middle' }}>
                    <input
                      type="checkbox"
                      checked={returns.length > 0 && selectedIds.size === returns.length}
                      onChange={(e) => {
                        if (e.target.checked) setSelectedIds(new Set(returns.map(r => r.id)))
                        else setSelectedIds(new Set())
                      }}
                      style={{ width: '13px', height: '13px', cursor: 'pointer', accentColor: '#F59E0B' }}
                    />
                  </th>
                  <th rowSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: '#888', fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap', verticalAlign: 'middle' }}>사진</th>
                  {['고객', '사업자', '주문번호', '마켓', 'CS', '주문일', '정산금액', '환수금액', '수익', '전체내역'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: '#888', fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                  <th colSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: '#888', fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>고객주문</th>
                </tr>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #2D2D2D' }}>
                  {['체크날짜', '전화', '상품명', '메모', 'CS링크', 'CS접수일', '지역', '상품위치', '상태', '반품신청한곳', '원주문'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: '#888', fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {returns.filter(r => !siteFilter || (r.completion_detail || '진행중') === siteFilter).map((r, idx) => {
                  const st = STATUS_MAP[r.status] || { label: r.status, bg: 'rgba(100,100,100,0.2)', text: '#888' }
                  return (
                    <Fragment key={r.id}>
                      <tr>
                        <td rowSpan={2} style={{ width: '36px', textAlign: 'center', padding: '0.5rem', verticalAlign: 'middle' }}>
                          <div style={{ fontSize: '0.675rem', color: '#666', marginBottom: '2px' }}>{idx + 1}</div>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(r.id)}
                            onChange={(e) => {
                              const next = new Set(selectedIds)
                              if (e.target.checked) next.add(r.id)
                              else next.delete(r.id)
                              setSelectedIds(next)
                            }}
                            style={{ width: '13px', height: '13px', cursor: 'pointer', accentColor: '#F59E0B' }}
                          />
                        </td>
                        <td rowSpan={2} style={{ padding: '0.625rem 0.5rem', textAlign: 'center', verticalAlign: 'middle' }}>
                        {r.product_image ? (
                          <img
                            src={r.product_image}
                            alt=""
                            onClick={() => r.return_link && window.open(r.return_link, '_blank')}
                            style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', cursor: r.return_link ? 'pointer' : 'default', display: 'block', margin: '0 auto' }}
                          />
                        ) : (
                          <div
                            onClick={() => r.return_link && window.open(r.return_link, '_blank')}
                            style={{ width: '60px', height: '60px', background: '#1A1A1A', borderRadius: '6px', border: '1px solid #2D2D2D', display: 'flex', alignItems: 'center', justifyContent: 'center', color: r.return_link ? '#4C9AFF' : '#444', fontSize: '0.625rem', cursor: r.return_link ? 'pointer' : 'default', textDecoration: r.return_link ? 'underline' : 'none', margin: '0 auto' }}
                          >
                            {r.return_link ? '링크' : 'No IMG'}
                          </div>
                        )}
                      </td>
                      <td style={tdCenter}>{r.customer_name || '-'}</td>
                      <td style={tdCenter}>{r.business_name || '-'}</td>
                      <td style={{ ...tdCenter, padding: '0.625rem' }}>
                        <button onClick={() => setDetailItem(r)} style={{ background: 'none', border: 'none', color: '#E5E5E5', cursor: 'pointer', fontSize: '0.8125rem', fontWeight: 400 }}>{r.order_number || r.order_id || '-'}</button>
                      </td>
                      <td style={tdCenter}>
                        <span>{r.market || '-'}</span>
                      </td>
                      <td style={{ ...tdCenter, fontSize: '0.75rem' }}>
                        {r.market_order_status?.includes('교환') && !r.market_order_status?.includes('완료') && !r.market_order_status?.includes('거부') ? (
                          <div style={{ display: 'flex', gap: '0.25rem', justifyContent: 'center' }}>
                            <button onClick={() => setExchangeActionItem(r)} style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', fontSize: '0.68rem', fontWeight: 600, background: 'rgba(76,154,255,0.15)', color: '#4C9AFF', border: '1px solid rgba(76,154,255,0.3)', cursor: 'pointer' }}>교환승인</button>
                            <button onClick={() => handleExchangeAction(r, 'reject')} style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', fontSize: '0.68rem', fontWeight: 600, background: 'rgba(255,107,107,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,107,107,0.3)', cursor: 'pointer' }}>교환거부</button>
                          </div>
                        ) : r.market_order_status?.includes('반품') && !r.market_order_status?.includes('완료') && !r.market_order_status?.includes('거부') ? (
                          <div style={{ display: 'flex', gap: '0.25rem', justifyContent: 'center' }}>
                            <button onClick={() => handleReturnAction(r, 'approve')} style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', fontSize: '0.68rem', fontWeight: 600, background: 'rgba(76,154,255,0.15)', color: '#4C9AFF', border: '1px solid rgba(76,154,255,0.3)', cursor: 'pointer' }}>반품승인</button>
                            <button onClick={() => handleReturnAction(r, 'reject')} style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', fontSize: '0.68rem', fontWeight: 600, background: 'rgba(255,107,107,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,107,107,0.3)', cursor: 'pointer' }}>반품거부</button>
                          </div>
                        ) : r.market_order_status?.includes('취소') && !r.market_order_status?.includes('완료') ? (
                          <button onClick={() => handleCancelApprove(r)} style={{ padding: '0.15rem 0.5rem', borderRadius: '12px', fontSize: '0.72rem', fontWeight: 600, background: 'rgba(255,80,80,0.15)', color: '#FF5050', border: '1px solid rgba(255,80,80,0.3)', cursor: 'pointer' }}>{r.market_order_status}</button>
                        ) : (
                          <span style={{ color: r.market_order_status?.includes('완료') ? '#51CF66' : r.market_order_status?.includes('거부') ? '#FF6B6B' : '#E5E5E5' }}>{r.market_order_status || '-'}</span>
                        )}
                      </td>
                      <td style={{ ...tdCenter, color: '#888' }}>{fmtMD(r.order_date)}</td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={r.settlement_amount != null ? fmtNum(r.settlement_amount) : ''}
                          placeholder="0"
                          onFocus={(e) => { e.target.value = String(r.settlement_amount ?? '') }}
                          onChange={(e) => {
                            const raw = e.target.value.replace(/[^0-9.-]/g, '')
                            if (raw === '') { setReturns(prev => prev.map(x => x.id === r.id ? { ...x, settlement_amount: undefined } : x)); return }
                            if (raw === '-') return
                            const num = parseFloat(raw)
                            if (!isNaN(num)) setReturns(prev => prev.map(x => x.id === r.id ? { ...x, settlement_amount: num } : x))
                          }}
                          onBlur={async (e) => {
                            const num = parseFloat(e.target.value.replace(/,/g, ''))
                            if (!isNaN(num)) {
                              try { await returnApi.patch(r.id, { settlement_amount: num }) } catch (_e) { /* 무시 */ }
                            }
                          }}
                          style={{ width: '80px', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.8rem', textAlign: 'right' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={r.recovery_amount != null ? fmtNum(r.recovery_amount) : ''}
                          placeholder="0"
                          onFocus={(e) => { e.target.value = String(r.recovery_amount ?? '') }}
                          onChange={(e) => {
                            const raw = e.target.value.replace(/[^0-9.-]/g, '')
                            if (raw === '') { setReturns(prev => prev.map(x => x.id === r.id ? { ...x, recovery_amount: undefined } : x)); return }
                            if (raw === '-') return
                            const num = parseFloat(raw)
                            if (!isNaN(num)) setReturns(prev => prev.map(x => x.id === r.id ? { ...x, recovery_amount: num } : x))
                          }}
                          onBlur={async (e) => {
                            const num = parseFloat(e.target.value.replace(/,/g, ''))
                            if (!isNaN(num)) {
                              try { await returnApi.patch(r.id, { recovery_amount: num }) } catch (_e) { /* 무시 */ }
                            }
                          }}
                          style={{ width: '80px', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.8rem', textAlign: 'right' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, fontSize: '0.8rem' }}>
                        {(r.settlement_amount != null || r.recovery_amount != null)
                          ? fmtNum((r.settlement_amount ?? 0) - (r.recovery_amount ?? 0))
                          : '-'}
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.completion_detail || '진행중'}
                          onChange={async (e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, completion_detail: val } : x))
                            try {
                              await returnApi.patch(r.id, { completion_detail: val })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="진행중">진행중</option>
                          <option value="취소">취소</option>
                          <option value="교환">교환</option>
                          <option value="반품">반품</option>
                          <option value="거부">거부</option>
                        </select>
                      </td>
                      <td colSpan={2} style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.customer_order_no || 'return_incomplete'}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { customer_order_no: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_order_no: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="return_incomplete">미완료</option>
                          <option value="return_complete">완료</option>
                        </select>
                      </td>
                      </tr>
                      <tr style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <div
                          onClick={() => {
                            const inp = document.getElementById(`ck-${r.id}`) as HTMLInputElement
                            inp?.showPicker?.()
                          }}
                          style={{ cursor: 'pointer', fontSize: '0.8rem', color: r.check_date ? '#E5E5E5' : '#555', minWidth: '40px' }}
                        >
                          {fmtMD(r.check_date)}
                        </div>
                        <input
                          id={`ck-${r.id}`}
                          type="date"
                          value={r.check_date?.slice(0, 10) || ''}
                          onChange={async (e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, check_date: val } : x))
                            try {
                              await returnApi.patch(r.id, { check_date: val || '' })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ width: 0, height: 0, opacity: 0, position: 'absolute', pointerEvents: 'none' }}
                        />
                      </td>
                      <td style={tdCenter}>{r.customer_phone || '-'}</td>
                      <td style={{ ...tdCenter, maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.product_name || '-'}</td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={r.memo || ''}
                          placeholder=""
                          onChange={(e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, memo: val } : x))
                          }}
                          onBlur={async (e) => {
                            try {
                              await returnApi.patch(r.id, { memo: e.target.value })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ width: '100px', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.8rem', textAlign: 'center' }}
                        />
                      </td>
                      <td style={tdCenter}>
                        {r.return_link ? <a href={r.return_link} target="_blank" rel="noopener noreferrer" style={{ color: '#4C9AFF', textDecoration: 'none' }}>링크</a> : '-'}
                      </td>
                      <td style={{ ...tdCenter, color: '#888' }}>{fmtMD(r.return_request_date || r.created_at)}</td>
                      <td style={tdCenter}>{r.region || '-'}</td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.product_location || '고객'}
                          onChange={async (e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, product_location: val } : x))
                            try {
                              await returnApi.patch(r.id, { product_location: val })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="고객">고객</option>
                          <option value="사무실">사무실</option>
                          <option value="원주문">원주문</option>
                          <option value="배송미완료">배송미완료</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.status}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { status: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, status: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="not_collected">미수거</option>
                          <option value="collecting">수거중</option>
                          <option value="collected">수거완료</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select value={r.return_source || '원주문'} onChange={async (e) => {
                          try {
                            await returnApi.patch(r.id, { return_source: e.target.value })
                            loadReturns()
                          } catch {}
                        }} style={{ fontSize: '0.72rem', padding: '2px 4px', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', cursor: 'pointer' }}>
                          <option value="원주문">원주문</option>
                          <option value="홈픽">홈픽</option>
                          <option value="자동회수">자동회수</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.original_order_no || 'return_incomplete'}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { original_order_no: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, original_order_no: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#E5E5E5', fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="return_incomplete">미완료</option>
                          <option value="return_complete">완료</option>
                        </select>
                      </td>
                      </tr>
                    </Fragment>
                  )
                })}
                {returns.length === 0 && (
                  <tr><td colSpan={12} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>반품/교환 내역이 없습니다</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 거절 사유 입력 모달 */}
      {rejectModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>거절 사유 입력</h3>
            <input
              style={inputStyle}
              placeholder="거절 사유를 입력하세요"
              value={rejectModal.reason}
              onChange={e => setRejectModal({ ...rejectModal, reason: e.target.value })}
              onKeyDown={e => e.key === 'Enter' && submitReject()}
              autoFocus
            />
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button onClick={() => setRejectModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button onClick={submitReject} style={{ padding: '0.625rem 1.25rem', background: '#FF6B6B', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>거절</button>
            </div>
          </div>
        </div>
      )}

{/* 상품위치 수정 모달 */}      {locationModal && (        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '420px', maxWidth: '90vw' }}>            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '1rem' }}>상품위치 수정</h3>            {locationModal.address && (              <div style={{ padding: '0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', marginBottom: '1rem', fontSize: '0.85rem', color: '#4C9AFF', lineHeight: 1.5 }}>                <span style={{ color: '#888', fontSize: '0.75rem' }}>전체 주소</span><br/>                {locationModal.address}              </div>            )}            <input style={inputStyle} placeholder="시/군/구 입력" value={locationModal.value} onChange={e => setLocationModal({ ...locationModal, value: e.target.value })} onKeyDown={async e => { if (e.key === 'Enter') { const val = locationModal.value.trim(); setReturns(prev => prev.map(x => x.id === locationModal.id ? { ...x, product_location: val } : x)); try { await returnApi.patch(locationModal.id, { product_location: val }) } catch (_e) { /* */ } setLocationModal(null) } }} autoFocus />            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1rem' }}>              <button onClick={() => setLocationModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>              <button onClick={async () => { const val = locationModal.value.trim(); setReturns(prev => prev.map(x => x.id === locationModal.id ? { ...x, product_location: val } : x)); try { await returnApi.patch(locationModal.id, { product_location: val }) } catch (_e) { /* */ } setLocationModal(null) }} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>저장</button>            </div>          </div>        </div>      )}
      {/* 교환 액션 선택 모달 */}
      {exchangeActionItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '380px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.5rem' }}>교환요청 처리</h3>
            <p style={{ fontSize: '0.8125rem', color: '#888', marginBottom: '1.5rem' }}>주문번호: {exchangeActionItem.order_number || exchangeActionItem.order_id || '-'}</p>
            {!reshipStep ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button onClick={() => setReshipStep(true)} style={{ padding: '0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '8px', color: '#4C9AFF', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>교환재배송</button>
                <button onClick={() => handleExchangeAction(exchangeActionItem, 'convert_return')} style={{ padding: '0.75rem', background: 'rgba(255,165,0,0.1)', border: '1px solid rgba(255,165,0,0.3)', borderRadius: '8px', color: '#FFA500', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>반품변경</button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <p style={{ fontSize: '0.8125rem', color: '#aaa', margin: 0 }}>재배송 송장 정보를 입력하세요 (롯데ON 필수)</p>
                <select
                  value={reshipForm.shipping_company}
                  onChange={e => setReshipForm(f => ({ ...f, shipping_company: e.target.value }))}
                  style={{ padding: '0.5rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem' }}
                >
                  {['CJ대한통운','한진택배','롯데택배','로젠택배','우체국택배','경동택배','대신택배','일양로지스'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <input
                  placeholder="송장번호 입력"
                  value={reshipForm.tracking_number}
                  onChange={e => setReshipForm(f => ({ ...f, tracking_number: e.target.value }))}
                  style={{ padding: '0.5rem 0.75rem', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#E5E5E5', fontSize: '0.875rem' }}
                />
                <button
                  onClick={() => handleExchangeAction(exchangeActionItem, 'reship', { tracking_number: reshipForm.tracking_number, shipping_company: reshipForm.shipping_company })}
                  style={{ padding: '0.75rem', background: 'rgba(76,154,255,0.15)', border: '1px solid rgba(76,154,255,0.4)', borderRadius: '8px', color: '#4C9AFF', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
                >재배송 처리</button>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button
                onClick={() => { setExchangeActionItem(null); setReshipStep(false); setReshipForm({ tracking_number: '', shipping_company: '롯데택배' }) }}
                style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}
              >닫기</button>
            </div>
          </div>
        </div>
      )}

      {/* 상세 모달 + 타임라인 */}
      {detailItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '520px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>
                {TYPE_LABELS[detailItem.type]?.label || detailItem.type} 상세
              </h3>
              <button onClick={() => setDetailItem(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
              {[
                { label: '주문 ID', value: detailItem.order_id },
                { label: '유형', value: TYPE_LABELS[detailItem.type]?.label || detailItem.type },
                { label: '수량', value: String(detailItem.quantity) },
                { label: '요청금액', value: detailItem.requested_amount ? `₩${fmtNum(detailItem.requested_amount)}` : '-' },
                { label: '상태', value: STATUS_MAP[detailItem.status]?.label || detailItem.status },
                { label: '등록일', value: detailItem.created_at?.slice(0, 10) || '-' },
              ].map(({ label, value }) => (
                <div key={label}>
                  <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.25rem' }}>{label}</p>
                  <p style={{ fontSize: '0.875rem', color: '#E5E5E5' }}>{value}</p>
                </div>
              ))}
              {detailItem.reason && (
                <div style={{ gridColumn: '1 / -1' }}>
                  <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.25rem' }}>사유</p>
                  <p style={{ fontSize: '0.875rem', color: '#E5E5E5' }}>{detailItem.reason}</p>
                </div>
              )}
            </div>

            {/* 타임라인 */}
            {detailItem.timeline && detailItem.timeline.length > 0 && (
              <div>
                <h4 style={{ fontSize: '0.8125rem', color: '#888', fontWeight: 600, marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>처리 이력</h4>
                <div style={{ position: 'relative' }}>
                  {detailItem.timeline.map((t, i) => {
                    const st = STATUS_MAP[t.status]
                    return (
                      <div key={i} style={{ display: 'flex', gap: '1rem', marginBottom: i < detailItem.timeline!.length - 1 ? '1rem' : 0 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
                          <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: st?.text || '#555', flexShrink: 0 }} />
                          {i < detailItem.timeline!.length - 1 && (
                            <div style={{ width: '2px', flex: 1, background: '#2D2D2D', minHeight: '20px' }} />
                          )}
                        </div>
                        <div style={{ paddingBottom: i < detailItem.timeline!.length - 1 ? '0.5rem' : 0 }}>
                          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.25rem' }}>
                            <span style={{ fontSize: '0.8125rem', color: st?.text || '#888', fontWeight: 600 }}>{st?.label || t.status}</span>
                            <span style={{ fontSize: '0.75rem', color: '#555' }}>{t.date?.slice(0, 16) || ''}</span>
                          </div>
                          {t.message && <p style={{ fontSize: '0.8125rem', color: '#888' }}>{t.message}</p>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

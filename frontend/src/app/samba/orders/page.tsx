'use client'

import { useEffect, useState, useCallback } from 'react'
import { orderApi, channelApi, accountApi, proxyApi, type SambaOrder, type SambaChannel, type SambaMarketAccount } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending:   { label: '대기중', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  shipped:   { label: '배송중', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  delivered: { label: '배송완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelled: { label: '취소됨', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  returned:  { label: '반품됨', bg: 'rgba(200,100,200,0.15)', text: '#CC5DE8' },
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

export default function OrdersPage() {
  const [orders, setOrders] = useState<SambaOrder[]>([])
  const [channels, setChannels] = useState<SambaChannel[]>([])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('all')
  const [marketFilter, setMarketFilter] = useState('')
  const [marketStatus, setMarketStatus] = useState('')
  const [searchText, setSearchText] = useState('')
  const [pageSize, setPageSize] = useState(50)
  const [logMessages, setLogMessages] = useState<string[]>(['[대기] 주문 가져오기 결과가 여기에 표시됩니다...'])
  const [smsRemain, setSmsRemain] = useState<{ SMS_CNT?: number; LMS_CNT?: number; MMS_CNT?: number } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<OrderForm>({ ...emptyForm })

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

  const handleFetch = () => {
    setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 주문 가져오기 시작...`])
    loadOrders().then(() => {
      setLogMessages(prev => [...prev, `[${new Date().toLocaleTimeString()}] 주문 로드 완료`])
    })
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

  const handleStatusChange = async (id: string, status: string) => {
    try { await orderApi.updateStatus(id, status); loadOrders() }
    catch (e) { showAlert(e instanceof Error ? e.message : '상태 변경 실패', 'error') }
  }
  const handleDelete = async (id: string) => {
    if (!await showConfirm('주문삭제하시겠습니까?')) return
    try { await orderApi.delete(id); loadOrders() }
    catch (e) { showAlert(e instanceof Error ? e.message : '삭제 실패', 'error') }
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
    // 기간 필터
    const periodStart = getPeriodStart(period)
    if (periodStart) {
      const orderDate = new Date(o.created_at)
      if (orderDate < periodStart) return false
    }
    if (marketFilter) {
      const marketName = accounts.find(a => a.market_type === marketFilter)?.market_name || marketFilter
      if (o.channel_name !== marketName && o.channel_id !== marketFilter) return false
    }
    if (searchText && !o.product_name?.toLowerCase().includes(searchText.toLowerCase())
      && !o.customer_name?.toLowerCase().includes(searchText.toLowerCase())
      && !o.order_number?.toLowerCase().includes(searchText.toLowerCase())) return false
    return true
  })

  const pendingCount = filteredOrders.filter(o => o.status === 'pending').length

  return (
    <div style={{ color: '#E5E5E5' }}>
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

      {/* 기간 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap', alignItems: 'center' }}>
          {PERIOD_BUTTONS.map(pb => (
            <button key={pb.key} onClick={() => setPeriod(pb.key)}
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: period === pb.key ? '1px solid #C0392B' : '1px solid #3D3D3D', color: period === pb.key ? '#fff' : '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap' }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 4px' }} />
          <button onClick={handleFetch} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>가져오기</button>
          <button onClick={handleFetch} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>전체마켓 가져오기</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <input type="date" style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
          <input type="date" style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <button style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        </div>
      </div>

      {/* 필터 바 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <select style={{ ...inputStyle, width: '118px' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
          <option value="">전체마켓보기</option>
          {[...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()].map(([type, name]) => (
            <option key={type} value={type}>{name}</option>
          ))}
        </select>
        <select style={{ ...inputStyle, width: '110px' }}><option value="">전체사이트보기</option>{['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','GrandStage','OKmall','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}</select>
        <select style={{ ...inputStyle, width: '112px' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
          <option value="">마켓상태 보기</option>
          {MARKET_STATUS_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
        <input style={{ ...inputStyle, width: '140px' }} placeholder="상품명/고객명 검색" value={searchText} onChange={e => setSearchText(e.target.value)} />
        <select style={{ ...inputStyle, width: '88px' }}><option>-- 정렬 --</option><option>주문일자▲</option><option>주문일자▼</option></select>
        <select style={{ ...inputStyle, width: '92px', marginLeft: 'auto' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
          <option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
        </select>
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
        <div style={{ height: '120px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.73rem', color: '#4A5568', background: '#080A10', lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: '#3D4A60' }}>{msg}</p>)}
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
              <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: '#94A3B8', width: '320px' }}>주문상태</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</td></tr>
            ) : filteredOrders.length === 0 ? (
              <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>주문이 없습니다</td></tr>
            ) : filteredOrders.map(o => {
              const fee = o.sale_price * (o.fee_rate / 100)
              const settlement = o.sale_price - fee
              const profit = settlement - o.cost
              const profitRate = o.sale_price > 0 ? ((profit / o.sale_price) * 100).toFixed(0) : '0'

              return (
                <tr key={o.id} style={{ borderBottom: '1px solid #1C2333', verticalAlign: 'top' }}>
                  {/* 체크박스 */}
                  <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', borderRight: '1px solid #1C2333' }}>
                    <input type="checkbox" style={{ accentColor: '#F59E0B' }} />
                  </td>
                  {/* 주문정보 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8125rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.75rem', color: '#888', background: '#1A1A1A', padding: '0.125rem 0.5rem', borderRadius: '4px' }}>{o.channel_name || '마켓'}</span>
                      <span style={{ fontWeight: 600, color: '#E5E5E5', fontFamily: 'monospace' }}>{o.order_number}</span>
                      <button style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '4px', color: '#4C9AFF', cursor: 'pointer' }}>주문번호복사</button>
                    </div>
                    <div style={{ color: '#C5C5C5', marginBottom: '0.375rem' }}>{o.product_name || '-'}</div>
                    <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
                      {['다나와', '네이버', '상품정보', '가격변경이력', '원문링크', '판매마켓링크', '미등록 입력', '배송조회', '업데이트', '마켓상품삭제', '원주문취소'].map(btn => (
                        <button key={btn} style={{ fontSize: '0.7rem', padding: '0.125rem 0.375rem', background: btn === '다나와' ? 'rgba(255,140,0,0.12)' : btn === '네이버' ? 'rgba(81,207,102,0.12)' : 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: btn === '다나와' ? '#FF8C00' : btn === '네이버' ? '#51CF66' : '#888', cursor: 'pointer' }}>{btn}</button>
                      ))}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.375rem', fontSize: '0.8rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666', minWidth: '40px' }}>주문자</span>
                        <span style={{ color: '#E5E5E5' }}>{o.customer_name || '-'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666', minWidth: '40px' }}>수령인</span>
                        <span style={{ color: '#E5E5E5' }}>{o.customer_name || '-'}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#888' }}>{o.customer_phone || '-'}</span>
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.375rem', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        <span style={{ color: '#666' }}>주소</span>
                        <span style={{ color: '#888' }}>{o.customer_address || '-'}</span>
                      </div>
                    </div>
                    <div style={{ fontSize: '0.75rem', color: '#555', marginTop: '0.5rem' }}>
                      {new Date(o.created_at).toLocaleString('ko-KR')}
                    </div>
                    <button onClick={() => handleDelete(o.id)} style={{ marginTop: '0.5rem', padding: '0.25rem 0.75rem', fontSize: '0.75rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}>주문삭제</button>
                  </td>
                  {/* 금액 */}
                  <td style={{ padding: '0.75rem', borderRight: '1px solid #1C2333', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>결제</span><span>{o.sale_price.toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>정산</span><span>{Math.round(settlement).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>실수익</span><span style={{ color: profit >= 0 ? '#51CF66' : '#FF6B6B' }}>{profit >= 0 ? '+' : ''}{Math.round(profit).toLocaleString()}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#888' }}>실수익률</span><span style={{ color: '#888' }}>{profitRate}%</span></div>
                    </div>
                  </td>
                  {/* 주문상태 */}
                  <td style={{ padding: '0.75rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <span style={{ color: '#888', minWidth: '70px' }}>주문계정</span>
                        <select style={{ ...inputStyle, flex: 1 }}>
                          <option>주문계정 선택</option>
                          {accounts.map(a => <option key={a.id} value={a.id}>{a.market_name} - {a.account_label}</option>)}
                        </select>
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <select value={o.status} onChange={e => handleStatusChange(o.id, e.target.value)}
                          style={{ ...inputStyle, flex: 1, background: (STATUS_MAP[o.status] || STATUS_MAP.pending).bg, color: (STATUS_MAP[o.status] || STATUS_MAP.pending).text, fontWeight: 600 }}
                        >
                          {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                        </select>
                      </div>
                      <div style={{ display: 'flex', gap: '0.375rem' }}>
                        <input style={{ ...inputStyle, flex: 1, fontSize: '0.75rem' }} value={o.order_number} readOnly placeholder="마켓상태" />
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <span style={{ color: '#888', fontSize: '0.75rem' }}>원가(실제구매가)</span>
                        <button style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer' }}>취소승인</button>
                      </div>
                      <div style={{ display: 'flex', gap: '0.375rem' }}>
                        <button style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer' }}>가격X</button>
                        <button style={{ fontSize: '0.7rem', padding: '0.125rem 0.5rem', background: 'rgba(255,211,61,0.1)', border: '1px solid rgba(255,211,61,0.3)', color: '#FFD93D', borderRadius: '4px', cursor: 'pointer' }}>재고X</button>
                      </div>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        <select style={{ ...inputStyle, flex: 1 }}>
                          <option>택배사 선택</option>
                          {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
                        </select>
                        <input style={{ ...inputStyle, flex: 1 }} placeholder="간단메모" />
                      </div>
                      <input style={{ ...inputStyle }} value={o.tracking_number || ''} readOnly placeholder="국내송장번호" />
                      <div style={{ display: 'flex', gap: '0.375rem', marginTop: '0.25rem' }}>
                        <button onClick={() => openEdit(o)} style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem', background: '#2563EB', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>직배</button>
                        <button style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem', background: '#D97706', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>까대기</button>
                        <button style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem', background: '#059669', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>선물</button>
                      </div>
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
    </div>
  )
}

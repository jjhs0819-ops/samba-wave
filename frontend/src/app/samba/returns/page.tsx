'use client'

import { useEffect, useState, useCallback } from 'react'
import { returnApi, type SambaReturn } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  requested: { label: '요청됨', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  approved:  { label: '승인됨', bg: 'rgba(76,154,255,0.15)', text: '#4C9AFF' },
  rejected:  { label: '거절됨', bg: 'rgba(255,107,107,0.15)', text: '#FF6B6B' },
  completed: { label: '완료됨', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
  cancelled: { label: '취소됨', bg: 'rgba(100,100,100,0.2)', text: '#888' },
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

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
}

const inputStyle = {
  width: '100%',
  padding: '0.5rem 0.75rem',
  background: '#1A1A1A',
  border: '1px solid #2D2D2D',
  borderRadius: '6px',
  color: '#E5E5E5',
  fontSize: '0.875rem',
  outline: 'none',
  boxSizing: 'border-box' as const,
}

// 기간 선택 버튼 상수
const PERIOD_BUTTONS = [
  { key: 'today', label: '오늘' },
  { key: '1week', label: '1주일' },
  { key: '15days', label: '15일' },
  { key: '1month', label: '1개월' },
  { key: '3months', label: '3개월' },
  { key: '6months', label: '6개월' },
  { key: 'year', label: '올해' },
  { key: 'all', label: '전체' },
]

export default function ReturnsPage() {
  const [returns, setReturns] = useState<SambaReturn[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [detailItem, setDetailItem] = useState<SambaReturn | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  const [form, setForm] = useState({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })

  // 로그 + 검색/필터 상태
  const [logMessages, setLogMessages] = useState<string[]>(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])
  const [period, setPeriod] = useState('all')
  const [syncAccountId, setSyncAccountId] = useState('')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [startLocked, setStartLocked] = useState(false)
  const [dateLocked, setDateLocked] = useState(false)
  const [searchCategory, setSearchCategory] = useState('customer')
  const [searchText, setSearchText] = useState('')
  const [marketFilter, setMarketFilter] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [marketStatus, setMarketStatus] = useState('')
  const [inputFilter, setInputFilter] = useState('')
  const [pageSize, setPageSize] = useState(50)

  const load = useCallback(async () => {
    setLoading(true)
    const [data, st] = await Promise.all([
      returnApi.list(undefined, filterStatus || undefined, filterType || undefined).catch(() => []),
      returnApi.getStats().catch(() => ({})),
    ])
    setReturns(data)
    setStats(st)
    setLoading(false)
  }, [filterStatus, filterType])

  useEffect(() => { load() }, [load])

  // 가져오기 버튼 핸들러 (load 래핑)
  const loadReturns = () => { load() }

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

  // 환불총액 계산
  const totalRefund = returns
    .filter(r => r.status === 'completed' || r.status === 'approved')
    .reduce((sum, r) => sum + (r.requested_amount || 0), 0)

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>반품교환</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>반품교환 요청을 관리합니다</p>
        </div>
      </div>

      {/* 통계 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        {[
          { key: 'total', label: '전체', color: '#FF8C00' },
          { key: 'requested', label: '요청됨', color: '#FFD93D' },
          { key: 'approved', label: '승인됨', color: '#4C9AFF' },
          { key: 'completed', label: '완료됨', color: '#51CF66' },
          { key: 'rejected', label: '거절됨', color: '#FF6B6B' },
        ].map(({ key, label, color }) => (
          <div key={key} style={{ ...card, padding: '1rem 1.25rem' }}>
            <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.375rem' }}>{label}</p>
            <p style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{stats[key] ?? 0}</p>
          </div>
        ))}
        {/* 환불총액 통계 */}
        <div style={{ ...card, padding: '1rem 1.25rem', border: '1px solid rgba(255,107,107,0.2)' }}>
          <p style={{ fontSize: '0.75rem', color: '#666', marginBottom: '0.375rem' }}>환불총액</p>
          <p style={{ fontSize: '1.25rem', fontWeight: 700, color: '#FF6B6B' }}>₩{totalRefund.toLocaleString()}</p>
        </div>
      </div>

      {/* 로그 영역 */}
      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>반품교환 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{msg}</p>)}
        </div>
      </div>

      {/* 기간 선택 + 계정 + 가져오기 + 날짜 범위 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
        {PERIOD_BUTTONS.map(pb => (
          <button key={pb.key} onClick={() => { setPeriod(pb.key) }}
            style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: period === pb.key ? '1px solid #C0392B' : '1px solid #3D3D3D', color: period === pb.key ? '#fff' : '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >{pb.label}</button>
        ))}
        <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
        <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', minWidth: '140px' }}>
          <option value="">전체 계정</option>
        </select>
        <button onClick={loadReturns} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>가져오기</button>
        <button onClick={loadReturns} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>전체마켓 가져오기</button>
        <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 6px' }} />
        <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
        <button onClick={() => setStartLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: startLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: startLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: startLocked ? '#fff' : '#C5C5C5' }}>고정</button>
        <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
        <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
        <button onClick={() => setDateLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: dateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: dateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: dateLocked ? '#fff' : '#C5C5C5' }}>고정</button>
      </div>

      {/* 검색 + 필터 드롭다운 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <select style={{ ...inputStyle, width: '80px', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="customer">고객</option>
          <option value="order_number">주문번호</option>
          <option value="product">상품명</option>
        </select>
        <input style={{ ...inputStyle, width: '140px' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadReturns() }} />
        <button onClick={loadReturns} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '118px' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체마켓보기</option>
          </select>
          <select style={{ ...inputStyle, width: '110px' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
            <option value="">전체사이트보기</option>
            {['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','GrandStage','OKmall','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '112px' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">마켓상태 보기</option>
          </select>
          <select style={{ ...inputStyle, width: '118px' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="">입력값</option>
          </select>
          <select style={{ ...inputStyle, width: '112px' }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
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
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #2D2D2D' }}>
                  {['사진', '고객', '사업자', '주문번호', '마켓', '확인', '주문일', '고객', '회사', '완료내역', '상품명', '체크날짜', '고객전화번호', '지역', '메모', '반품링크', '반품신청일', '상품위치', '반품신청한곳', '상태', '고객주문', '원주문'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'left', padding: '0.75rem 0.625rem', color: '#888', fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {returns.map((r) => {
                  const st = STATUS_MAP[r.status] || { label: r.status, bg: 'rgba(100,100,100,0.2)', text: '#888' }
                  return (
                    <tr key={r.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '0.625rem 0.5rem', textAlign: 'center', verticalAlign: 'top' }}>
                        {r.product_image ? (
                          <img
                            src={r.product_image}
                            alt=""
                            onClick={() => r.return_link && window.open(r.return_link, '_blank')}
                            style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', cursor: r.return_link ? 'pointer' : 'default' }}
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
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.customer_name || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.business_name || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem' }}>
                        <button onClick={() => setDetailItem(r)} style={{ background: 'none', border: 'none', color: '#FF8C00', cursor: 'pointer', fontSize: '0.8125rem', fontWeight: 500 }}>{r.order_id || '-'}</button>
                      </td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.market || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.confirmed ? '확인' : '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', color: '#888', whiteSpace: 'nowrap' }}>{r.order_date?.slice(0, 10) || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.customer_id || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.company || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.completion_detail || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.product_name || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', color: '#888', whiteSpace: 'nowrap' }}>{r.check_date?.slice(0, 10) || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.customer_phone || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.region || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.memo || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem' }}>
                        {r.return_link ? <a href={r.return_link} target="_blank" rel="noopener noreferrer" style={{ color: '#4C9AFF', textDecoration: 'none' }}>링크</a> : '-'}
                      </td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', color: '#888', whiteSpace: 'nowrap' }}>{r.return_request_date?.slice(0, 10) || r.created_at?.slice(0, 10) || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.product_location || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.return_source || '-'}</td>
                      <td style={{ padding: '0.625rem' }}>
                        <span style={{ padding: '0.2rem 0.5rem', borderRadius: '20px', fontSize: '0.72rem', fontWeight: 600, background: st.bg, color: st.text, whiteSpace: 'nowrap' }}>{st.label}</span>
                      </td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.customer_order_no || '-'}</td>
                      <td style={{ padding: '0.625rem', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>{r.original_order_no || '-'}</td>
                    </tr>
                  )
                })}
                {returns.length === 0 && (
                  <tr><td colSpan={22} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>반품/교환 내역이 없습니다</td></tr>
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
                { label: '요청금액', value: detailItem.requested_amount ? `₩${detailItem.requested_amount.toLocaleString()}` : '-' },
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

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

export default function ReturnsPage() {
  const [returns, setReturns] = useState<SambaReturn[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [detailItem, setDetailItem] = useState<SambaReturn | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  const [form, setForm] = useState({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })

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
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>반품·교환·취소</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>반품/교환/취소 요청을 관리합니다</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '8px', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
        >
          + 등록
        </button>
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

      {/* 필터 */}
      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          style={{ ...inputStyle, width: 'auto', minWidth: '140px' }}
        >
          <option value=''>전체 상태</option>
          {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          style={{ ...inputStyle, width: 'auto', minWidth: '120px' }}
        >
          <option value=''>전체 유형</option>
          {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
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
                  {['주문 ID', '유형', '사유', '수량', '요청금액', '상태', '등록일', '작업'].map((h, i) => (
                    <th key={h} style={{ textAlign: i >= 3 && i <= 4 ? 'right' : i === 7 ? 'right' : 'left', padding: '0.875rem 1.25rem', color: '#888', fontWeight: 500, fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {returns.map((r) => {
                  const st = STATUS_MAP[r.status] || { label: r.status, bg: 'rgba(100,100,100,0.2)', text: '#888' }
                  const typeConf = TYPE_LABELS[r.type] || { label: r.type, color: '#888' }
                  return (
                    <tr key={r.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                    >
                      <td style={{ padding: '0.875rem 1.25rem' }}>
                        <button onClick={() => setDetailItem(r)} style={{ background: 'none', border: 'none', color: '#FF8C00', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 500 }}>{r.order_id}</button>
                      </td>
                      <td style={{ padding: '0.875rem 1.25rem' }}>
                        <span style={{ padding: '0.2rem 0.625rem', borderRadius: '20px', fontSize: '0.75rem', fontWeight: 600, background: `${typeConf.color}22`, color: typeConf.color }}>{typeConf.label}</span>
                      </td>
                      <td style={{ padding: '0.875rem 1.25rem', color: '#888', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.reason || '-'}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'right' }}>{r.quantity}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'right' }}>{r.requested_amount ? `₩${r.requested_amount.toLocaleString()}` : '-'}</td>
                      <td style={{ padding: '0.875rem 1.25rem' }}>
                        <span style={{ padding: '0.25rem 0.75rem', borderRadius: '20px', fontSize: '0.75rem', fontWeight: 600, background: st.bg, color: st.text }}>{st.label}</span>
                      </td>
                      <td style={{ padding: '0.875rem 1.25rem', color: '#555', fontSize: '0.8125rem' }}>{r.created_at?.slice(0, 10) || '-'}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                          {r.status === 'requested' && (
                            <>
                              <button onClick={() => handleApprove(r.id)} style={{ background: 'none', border: 'none', color: '#4C9AFF', fontSize: '0.8125rem', cursor: 'pointer' }}>승인</button>
                              <button onClick={() => handleReject(r.id)} style={{ background: 'none', border: 'none', color: '#FF6B6B', fontSize: '0.8125rem', cursor: 'pointer' }}>거절</button>
                              <button onClick={() => handleCancel(r.id)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '0.8125rem', cursor: 'pointer' }}>취소</button>
                            </>
                          )}
                          {r.status === 'approved' && (
                            <>
                              <button onClick={() => handleComplete(r.id)} style={{ background: 'none', border: 'none', color: '#51CF66', fontSize: '0.8125rem', cursor: 'pointer' }}>완료</button>
                              <button onClick={() => handleCancel(r.id)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '0.8125rem', cursor: 'pointer' }}>취소</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {returns.length === 0 && (
                  <tr><td colSpan={8} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>반품/교환 내역이 없습니다</td></tr>
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

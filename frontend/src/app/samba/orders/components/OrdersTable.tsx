'use client'

import React, { Dispatch, SetStateAction, useState } from 'react'
import {
  orderApi,
  type SambaOrder,
} from '@/lib/samba/api/commerce'
import { type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { inputStyle, fmtNum } from '@/lib/samba/styles'
import { fmtTime } from '@/lib/samba/utils'
import { STATUS_MAP, SHIPPING_COMPANIES, OVERSEAS_SHIPPING_COMPANIES, ACTION_BUTTONS } from '../constants'
import { parseActionTags } from '../utils/actionTag'
import OrderInfoCell from './OrderInfoCell'
import { useTheme } from '@/lib/samba/useTheme'
import { btn } from '@/lib/samba/buttons'

// 같은 주문 송장 동시 전송 차단 — 송장번호 input blur + 마켓전송 버튼 click 이
// 동시에 발동해 중복 전송되면, 첫 전송 성공 후 두 번째가 INVALID_STATUS 실패로 잡힘.
// 전송 중인 주문 id를 담아 두 번째 호출을 무시한다.
const _shippingInFlight = new Set<string>()

// Props 타입 정의
interface OrdersTableProps {
  // 데이터
  loading: boolean
  filteredOrders: SambaOrder[]
  currentPage: number
  pageSize: number
  currentPageIds: string[]
  selectedIds: Set<string>
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  toggleSelectAll: () => void

  // 인라인 편집 상태
  editingCosts: Record<string, string>
  setEditingCosts: Dispatch<SetStateAction<Record<string, string>>>
  editingShipFees: Record<string, string>
  setEditingShipFees: Dispatch<SetStateAction<Record<string, string>>>
  editingTrackings: Record<string, string>
  setEditingTrackings: Dispatch<SetStateAction<Record<string, string>>>
  editingOrderNumbers: Record<string, string>
  setEditingOrderNumbers: Dispatch<SetStateAction<Record<string, string>>>
  activeActions: Record<string, string | null>
  collectedProductCosts: Record<string, number>
  collectedProductSourceSites: Record<string, string>
  productMemos: Record<string, string> // 상품메모(#535)

  // 부가 상태
  refreshLog: Record<string, string>
  setRefreshLog: Dispatch<SetStateAction<Record<string, string>>>
  sentFlags: Record<string, { sms: boolean; kakao: boolean }>
  siteAliasMap: Record<string, string>
  sourcingAccounts: SambaSourcingAccount[]

  // 가격이력 모달 setter
  setPriceHistoryProduct: Dispatch<SetStateAction<{ name: string; source_site: string }>>
  setPriceHistoryData: Dispatch<SetStateAction<Record<string, unknown>[]>>
  setPriceHistoryModal: Dispatch<SetStateAction<boolean>>

  // 로그 setter
  setLogMessages: Dispatch<SetStateAction<string[]>>

  // 헬퍼/핸들러
  calcProfit: (o: SambaOrder) => number
  calcProfitRate: (o: SambaOrder) => string
  calcFeeRate: (o: SambaOrder) => string
  splitCustomerAddress: (
    address: string | null | undefined,
    detailColumn?: string | null,
  ) => { base: string; detail: string }
  renderCopyableText: (
    value: string | null | undefined,
    _label?: string,
    style?: React.CSSProperties
  ) => React.ReactNode
  handleDelete: (id: string) => void | Promise<void>
  handleImageClick: (o: SambaOrder) => void
  handleCopyOrderNumber: (orderNumber: string) => void
  openMsgModal: (type: 'sms' | 'kakao', order: SambaOrder) => void
  handleDanawa: (productName: string) => void
  handleNaver: (productName: string) => void
  handleSourceLink: (o: SambaOrder) => void | Promise<void>
  handleMarketLink: (o: SambaOrder) => void | Promise<void>
  openUrlModal: (orderId: string) => void
  handleTracking: (order: SambaOrder) => void
  loadOrders: () => void | Promise<void>
  patchOrder: (id: string, patch: Partial<SambaOrder>) => void
  handleStatusChange: (id: string, status: string) => void | Promise<void>
  handleCostSave: (id: string) => void | Promise<void>
  handleShipFeeSave: (id: string) => void | Promise<void>
  toggleAction: (orderId: string, actionKey: string) => void | Promise<void>
}

export default function OrdersTable(props: OrdersTableProps) {
  const c = useTheme()
  const {
    loading, filteredOrders, currentPage, pageSize,
    currentPageIds, selectedIds, setSelectedIds, toggleSelectAll,
    editingCosts, setEditingCosts,
    editingShipFees, setEditingShipFees,
    editingTrackings, setEditingTrackings,
    editingOrderNumbers, setEditingOrderNumbers,
    activeActions,
    collectedProductCosts,
    collectedProductSourceSites,
    productMemos,
    refreshLog, setRefreshLog,
    sentFlags, siteAliasMap, sourcingAccounts,
    setPriceHistoryProduct, setPriceHistoryData, setPriceHistoryModal,
    setLogMessages,
    calcProfit, calcProfitRate, calcFeeRate, splitCustomerAddress,
    renderCopyableText,
    handleDelete, handleImageClick, handleCopyOrderNumber, openMsgModal,
    handleDanawa, handleNaver, handleSourceLink, handleMarketLink,
    openUrlModal, handleTracking, loadOrders, patchOrder,
    handleStatusChange, handleCostSave, handleShipFeeSave, toggleAction,
  } = props
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({})

  return (
    <div style={{ border: `1px solid ${c.border}`, borderRadius: '8px', overflowX: 'auto' }}>
      <table style={{ width: '100%', minWidth: '1100px', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: c.headerBg, borderBottom: `2px solid ${c.borderStrong}` }}>
            <th style={{ width: '36px', padding: '0.5rem', textAlign: 'center', borderRight: `1px solid ${c.borderStrong}` }}>
              <input type="checkbox" checked={currentPageIds.length > 0 && currentPageIds.every(id => selectedIds.has(id))} onChange={toggleSelectAll} style={{ accentColor: c.warn, width: '13px', height: '13px', cursor: 'pointer' }} />
            </th>
            <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: c.headerText, borderRight: `1px solid ${c.borderStrong}` }}>주문정보</th>
            <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: c.headerText, borderRight: `1px solid ${c.borderStrong}`, width: '143px' }}>금액</th>
            <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontSize: '0.75rem', fontWeight: 600, color: c.headerText, width: '460px' }}>주문상태</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: c.textMuted }}>로딩 중...</td></tr>
          ) : filteredOrders.length === 0 ? (
            <tr><td colSpan={4} style={{ padding: '3rem', textAlign: 'center', color: c.textMuted }}>주문이 없습니다</td></tr>
          ) : filteredOrders.map((o, index) => {
            // 편집 중에는 사용자 입력을 그대로 표시 (콤마 자동삽입으로 인한 커서 꼬임/계산식 깨짐 방지)
            // Blur 후 editingCosts에서 제거되면 저장값(o.cost)에 콤마 포맷 적용
            const costDisplay = editingCosts[o.id] !== undefined ? editingCosts[o.id] : (o.cost ? fmtNum(o.cost) : '')
            const shipFeeDisplay = editingShipFees[o.id] !== undefined ? editingShipFees[o.id] : (o.shipping_fee ? fmtNum(o.shipping_fee) : '')
            const liveProfit = calcProfit(o)
            const liveProfitRate = calcProfitRate(o)
            const liveFeeRate = calcFeeRate(o)
            const displayCost = o.collected_product_id
              ? (collectedProductCosts[o.collected_product_id] ?? o.cost ?? 0)
              : (o.cost ?? 0)
            const activeActionTags = parseActionTags(activeActions[o.id] ?? o.action_tag ?? null)
            const customerAddress = splitCustomerAddress(o.customer_address, o.customer_address_detail)

            const isCancelRequested = o.status === 'cancel_requested'
            const isReturnRequested = o.status === 'return_requested'
            const isRejectPending = o.status === 'cancel_reject_pending'
            const rowStyle: React.CSSProperties = {
              borderBottom: `1px solid ${c.borderStrong}`,
              verticalAlign: 'top',
            }
            if (isCancelRequested) {
              rowStyle.borderLeft = `4px solid ${c.danger}`
              rowStyle.background = 'rgba(220,38,38,0.05)'
            } else if (isReturnRequested) {
              rowStyle.borderLeft = `4px solid ${c.warn}`
              rowStyle.background = 'rgba(245,158,11,0.05)'
            } else if (isRejectPending) {
              rowStyle.borderLeft = '4px solid #8B5CF6'
              rowStyle.background = 'rgba(139,92,246,0.05)'
            }

            return (
              <tr key={o.id} style={rowStyle}>
                {/* 체크박스 */}
                <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', borderRight: `1px solid ${c.borderStrong}` }}>
                  <div style={{ fontSize: '0.65rem', color: c.text, fontWeight: 'bold', marginBottom: '2px' }}>{(currentPage - 1) * pageSize + index + 1}</div>
                  <input type="checkbox" checked={selectedIds.has(o.id)} onChange={() => setSelectedIds(prev => { const next = new Set(prev); if (next.has(o.id)) next.delete(o.id); else next.add(o.id); return next })} style={{ accentColor: c.warn, cursor: 'pointer' }} />
                </td>
                {/* 주문정보 */}
                <OrderInfoCell
                  o={o}
                  refreshLog={refreshLog}
                  setRefreshLog={setRefreshLog}
                  sentFlags={sentFlags}
                  siteAliasMap={siteAliasMap}
                  actualSourceSite={o.collected_product_id ? (collectedProductSourceSites[o.collected_product_id] || '') : ''}
                  productMemo={o.collected_product_id ? (productMemos[o.collected_product_id] || '') : ''}
                  activeActions={activeActions}
                  setPriceHistoryProduct={setPriceHistoryProduct}
                  setPriceHistoryData={setPriceHistoryData}
                  setPriceHistoryModal={setPriceHistoryModal}
                  customerAddress={customerAddress}
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
                />
                {/* 금액 */}
                <td style={{ padding: '0.75rem', borderRight: `1px solid ${c.borderStrong}`, fontSize: '0.8rem' }}>
                  {/* 취소요청 사유 + 승인/거부 (#246) */}
                  {(isCancelRequested || isReturnRequested) && (() => {
                    const faultBy = (o.cancel_fault_by || '').toUpperCase()
                    const faultColor = faultBy === 'CUSTOMER'
                      ? c.success
                      : (faultBy === 'VENDOR' || faultBy === 'COUPANG' ? c.warn : c.textMuted)
                    const faultLabel = faultBy === 'CUSTOMER' ? '구매자 귀책 (승인 권장)'
                      : faultBy === 'VENDOR' ? '판매자 귀책 (재검토)'
                      : faultBy === 'COUPANG' ? '쿠팡 귀책 (재검토)'
                      : faultBy === 'WMS' ? 'WMS 귀책'
                      : faultBy === 'GENERAL' ? '일반' : ''
                    const cat = [o.cancel_reason_category1, o.cancel_reason_category2].filter(Boolean).join(' / ')
                    const isAlreadyShipped = (o.cancel_release_status || '').toUpperCase() === 'A'
                    const isStopped = (o.cancel_release_status || '').toUpperCase() === 'S'
                    return (
                      <div style={{
                        marginBottom: '0.5rem', padding: '0.4rem',
                        background: 'rgba(220,38,38,0.08)',
                        border: '1px solid rgba(220,38,38,0.3)',
                        borderRadius: '4px', fontSize: '0.7rem',
                      }}>
                        <div style={{ color: c.danger, fontWeight: 600, marginBottom: '0.25rem' }}>
                          {isCancelRequested ? '취소요청' : '반품요청'}
                          {isStopped && <span style={{ marginLeft: 6, padding: '1px 6px', background: c.success, color: '#fff', borderRadius: 3, fontSize: '0.6rem' }}>출고중지 완료</span>}
                          {isAlreadyShipped && <span style={{ marginLeft: 6, padding: '1px 6px', background: c.warn, color: '#fff', borderRadius: 3, fontSize: '0.6rem' }}>이미출고</span>}
                        </div>
                        {cat && <div style={{ color: c.textSub }}>{cat}</div>}
                        {o.cancel_reason_text && <div style={{ color: c.textSub, fontSize: '0.65rem' }}>{o.cancel_reason_text}</div>}
                        {faultLabel && <div style={{ color: faultColor, fontWeight: 600, marginTop: '0.2rem' }}>{faultLabel}</div>}
                        <div style={{ display: 'flex', gap: '4px', marginTop: '0.4rem' }}>
                          <button
                            onClick={async () => {
                              if (isAlreadyShipped) {
                                const company = window.prompt('이미출고 — 택배사 코드 입력 (예: CJGLS, HANJIN, LOTTE)')
                                if (!company) return
                                const invoice = window.prompt('송장번호 입력')
                                if (!invoice) return
                                const yes = await showConfirm('이미출고 취소승인 — 왕복 배송비 판매자 부담. 진행하시겠습니까?')
                                if (!yes) return
                                try {
                                  const res = await orderApi.approveCancelWithShipment(o.id, company, invoice)
                                  showAlert(res.message || '취소승인 완료', 'success')
                                  loadOrders()
                                } catch (err) {
                                  showAlert(err instanceof Error ? err.message : '취소승인 실패', 'error')
                                }
                              } else {
                                const yes = await showConfirm('취소승인 — 출고중지 처리하시겠습니까?')
                                if (!yes) return
                                try {
                                  const res = await orderApi.approveCancel(o.id)
                                  showAlert(res.message || '취소승인 완료', 'success')
                                  loadOrders()
                                } catch (err) {
                                  showAlert(err instanceof Error ? err.message : '취소승인 실패', 'error')
                                }
                              }
                            }}
                            style={{
                              ...btn('primary'),
                              flex: 1, fontSize: '0.65rem', padding: '0.2rem 0',
                            }}
                          >취소 승인</button>
                          <button
                            onClick={async () => {
                              const yes = await showConfirm('취소 거부 — Wing 화면에서 수동 처리 필요. 진행하시겠습니까?')
                              if (!yes) return
                              try {
                                const res = await orderApi.rejectCancel(o.id)
                                showAlert(res.message || '거부 처리 완료', res.manual_required ? 'info' : 'success')
                                loadOrders()
                              } catch (err) {
                                showAlert(err instanceof Error ? err.message : '거부 실패', 'error')
                              }
                            }}
                            style={{
                              ...btn('danger'),
                              flex: 1, fontSize: '0.65rem', padding: '0.2rem 0',
                            }}
                          >취소 거부</button>
                        </div>
                      </div>
                    )
                  })()}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>결제</span><span>{fmtNum(o.total_payment_amount ?? o.sale_price)}</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>정산</span><span>{fmtNum(Math.round(o.revenue))}</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>실수익</span><span>{liveProfit >= 0 ? '+' : ''}{fmtNum(Math.round(liveProfit))}</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>수수료율</span><span style={{ color: c.textMuted }}>{liveFeeRate}%</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>수익률</span><span style={{ color: c.textMuted }}>{liveProfitRate}%</span></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: c.textMuted }}>원가</span><span style={{ color: c.textMuted }}>{fmtNum(displayCost)}</span></div>
                  </div>
                  {/* 주문취소 + 가격X/재고X/직배/까대기/선물 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '4px', marginTop: '0.375rem', borderTop: `1px solid ${c.borderStrong}`, paddingTop: '0.375rem' }}>
                    <button
                      onClick={async () => {
                        const isPlayauto = (o.source === 'playauto' || o.channel_name?.toLowerCase().includes('플레이오토'))
                        const isLotteHome = o.channel_name?.includes('롯데홈')
                        const confirmMsg = isPlayauto ? '플레이오토는 EMP에서 직접 주문취소하셔야 합니다' : isLotteHome ? '롯데홈쇼핑 발송불가 처리하시겠습니까? (롯데홈쇼핑 마켓에 발송불가로 등록됩니다)' : '주문취소하시겠습니까?'
                        const yes = await showConfirm(confirmMsg)
                        if (!yes) return
                        try {
                          const res = await orderApi.sellerCancel(o.id, 'INTENT_CHANGED')
                          showAlert(res.message || '처리 완료', 'success')
                          loadOrders()
                        } catch (err) {
                          showAlert(err instanceof Error ? err.message : '처리 실패', 'error')
                        }
                      }}
                      style={{
                        fontSize: '0.68rem', padding: '0.125rem 0',
                        // 취소·반품 요청 상태일 때만 빨간색, 그 외 중립 (#300)
                        background: isCancelRequested ? c.danger : '#5a5a5a',
                        color: '#fff',
                        border: isCancelRequested ? `1px solid ${c.danger}` : '1px solid #5a5a5a',
                        borderRadius: '4px', cursor: 'pointer', textAlign: 'center',
                        fontWeight: 600,
                      }}
                    >주문취소</button>
                    {ACTION_BUTTONS.map(actionBtn => {
                      const isActive = activeActionTags.includes(actionBtn.key)
                      return (
                        <button
                          key={actionBtn.key}
                          onClick={() => toggleAction(o.id, actionBtn.key)}
                          style={{
                            fontSize: '0.68rem', padding: '0.125rem 0',
                            background: isActive ? actionBtn.activeColor : '#5a5a5a',
                            color: '#fff', border: isActive ? `1px solid ${actionBtn.activeColor}` : '1px solid #5a5a5a',
                            borderRadius: '4px', cursor: 'pointer', textAlign: 'center',
                          }}
                        >{actionBtn.label}</button>
                      )
                    })}
                  </div>
                </td>
                {/* 주문상태 */}
                <td style={{ padding: '0.625rem', fontSize: '0.8rem', height: '1px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', height: '100%' }}>
                    {/* 1행: 상태 드롭박스 + 주문번호 인풋 */}
                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                      <select value={o.status} onChange={e => handleStatusChange(o.id, e.target.value)}
                        style={{
                          ...inputStyle,
                          flex: 1,
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          color: o.status === 'ship_failed' ? c.danger : inputStyle.color,
                        }}
                      >
                        {Object.entries(STATUS_MAP).filter(([k]) => !['preparing', 'arrived', 'cancel_reject_pending', 'return_completed', 'undeliverable'].includes(k)).map(([k, v]) => <option key={k} value={k} style={k === 'ship_failed' ? { color: c.danger } : {}}>{v.label}</option>)}
                      </select>
                      <input
                        type="text"
                        placeholder={o.sourcing_account_id ? "소싱주문번호" : "주문계정 먼저 선택"}
                        disabled={!o.sourcing_account_id}
                        title={!o.sourcing_account_id ? '주문계정을 먼저 선택하세요' : undefined}
                        value={editingOrderNumbers[o.id] ?? o.sourcing_order_number ?? ''}
                        onChange={e => setEditingOrderNumbers(prev => ({ ...prev, [o.id]: e.target.value }))}
                        onBlur={async (e) => {
                          const val = e.target.value.trim()
                          setEditingOrderNumbers(prev => { const n = { ...prev }; delete n[o.id]; return n })
                          if (val === (o.sourcing_order_number ?? '')) return
                          try {
                            // 소싱주문번호 입력 → 상태 '배송대기중'(wait_ship) 자동 전환 (진행된 상태는 역행 안 함)
                            const advanced = ['shipping', 'delivered', 'confirmed', 'cancelled', 'returned', 'cancel_requested', 'return_requested', 'ship_failed']
                            const patch: Partial<SambaOrder> = { sourcing_order_number: val }
                            if (val && !advanced.includes(o.status)) patch.status = 'wait_ship'
                            await orderApi.update(o.id, patch)
                            patchOrder(o.id, patch)
                          } catch { showAlert('소싱주문번호 저장 실패', 'error') }
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            ;(e.target as HTMLInputElement).blur()
                          }
                        }}
                        style={{
                          ...inputStyle,
                          flex: 1,
                          fontSize: '0.75rem',
                          opacity: o.sourcing_account_id ? 1 : 0.5,
                          cursor: o.sourcing_account_id ? 'text' : 'not-allowed',
                        }}
                      />
                    </div>

                    {/* 2행: 주문계정 + 마켓상태 */}
                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'stretch' }}>
                      <select
                        value={o.sourcing_account_id || ''}
                        onChange={async (e) => {
                          const val = e.target.value
                          try {
                            await orderApi.update(o.id, { sourcing_account_id: val || undefined } as Partial<SambaOrder>)
                            patchOrder(o.id, { sourcing_account_id: val || undefined })
                          } catch { /* ignore */ }
                        }}
                        style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer' }}
                      >
                        <option value="">주문계정</option>
                        {(() => {
                          const allSites = [...new Set(sourcingAccounts.map(sa => sa.site_name))]
                          const siteOrder: Record<string, number> = { MUSINSA: 0, LOTTEON: 1, SSG: 2 }
                          const sites = allSites.sort((a, b) => (siteOrder[a] ?? 99) - (siteOrder[b] ?? 99) || a.localeCompare(b))
                          return sites.map(site => (
                            <optgroup key={site} label={site}>
                              {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                                <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                              ))}
                            </optgroup>
                          ))
                        })()}
                        <option value="etc">기타</option>
                      </select>
                      <div style={{
                        flex: 1, padding: '0.25rem 0.375rem',
                        background: c.surface, border: `1px solid ${c.border}`, borderRadius: '6px',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        <span style={{ fontSize: '0.75rem', color: c.text, fontWeight: 600 }}>{(o.shipping_status === '출고지시' || o.shipping_status === '출하지시' || o.shipping_status === '결제완료' || o.shipping_status === '상품준비') ? '주문접수' : o.shipping_status === '발송대기' ? '배송대기중' : o.shipping_status === '송장전송완료' ? '국내배송중' : (STATUS_MAP[o.shipping_status]?.label || o.shipping_status || '-')}</span>
                      </div>
                    </div>

                    {/* 3행: 원가 + 배송비 */}
                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                      <input
                        type="text"
                        style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', textAlign: 'right' }}
                        value={costDisplay}
                        placeholder="실구매가 (식 가능: 30000*.973+2300)"
                        onChange={e => {
                          // 숫자/사칙연산자/괄호/소수점/공백만 허용 (콤마는 입력 중 제거하여 식 평가 가능)
                          const raw = e.target.value.replace(/[^\d+\-*/.() ]/g, '')
                          setEditingCosts(prev => ({ ...prev, [o.id]: raw }))
                        }}
                        onBlur={() => handleCostSave(o.id)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            handleCostSave(o.id)
                          }
                        }}
                      />
                      <input
                        type="text"
                        style={{ ...inputStyle, flex: 1, fontSize: '0.75rem', textAlign: 'right' }}
                        value={shipFeeDisplay}
                        placeholder="배송비 (식 가능)"
                        onChange={e => {
                          const raw = e.target.value.replace(/[^\d+\-*/.() ]/g, '')
                          setEditingShipFees(prev => ({ ...prev, [o.id]: raw }))
                        }}
                        onBlur={() => handleShipFeeSave(o.id)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            handleShipFeeSave(o.id)
                          }
                        }}
                      />
                    </div>

                    {/* 택배사 + 송장번호 + 전송 */}
                    <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                      <select
                        key={`${o.id}-${o.shipping_company}-${o.status}`}
                        id={`ship-co-${o.id}`}
                        style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                        defaultValue={o.shipping_company || ''}
                        onChange={async e => {
                          const co = e.target.value
                          const tn = (document.getElementById(`ship-tn-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                          const alreadyShipped = o.shipping_status === '송장전송완료'
                          if (co && tn && alreadyShipped) {
                            const ts = fmtTime
                            try { await orderApi.update(o.id, { shipping_company: co, tracking_number: tn }) } catch { /* ignore */ }
                            patchOrder(o.id, { shipping_company: co, tracking_number: tn })
                            setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 수정 저장완료 (${co} ${tn}) — 마켓에서는 송장수정이 반영되지 않습니다. 마켓 판매자센터에서 직접 수정해주세요.`])
                          } else if (co && tn) {
                            if (_shippingInFlight.has(o.id)) return
                            _shippingInFlight.add(o.id)
                            const ts = fmtTime
                            setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 중... (${co} ${tn})`])
                            try {
                              const res = await orderApi.shipOrder(o.id, co, tn)
                              if (!res.market_sent) {
                                await orderApi.updateStatus(o.id, 'ship_failed')
                                patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                              } else {
                                patchOrder(o.id, { shipping_company: co, tracking_number: tn, shipping_status: '송장전송완료' })
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                              }
                            } catch {
                              await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                              patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 실패`])
                            } finally {
                              setTimeout(() => _shippingInFlight.delete(o.id), 1500)
                            }
                          } else if (co) {
                            try { await orderApi.update(o.id, { shipping_company: co }) } catch { /* ignore */ }
                            patchOrder(o.id, { shipping_company: co })
                          }
                        }}
                      >
                        <option value="">택배사</option>
                        {SHIPPING_COMPANIES.map(sc => <option key={sc} value={sc}>{sc}</option>)}
                      </select>
                      <input
                        id={`ship-tn-${o.id}`}
                        style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                        value={editingTrackings[o.id] ?? o.tracking_number ?? ''}
                        placeholder="송장번호"
                        onChange={e => setEditingTrackings(prev => ({ ...prev, [o.id]: e.target.value }))}
                        onBlur={async e => {
                          const tn = e.target.value.trim()
                          const co = (document.getElementById(`ship-co-${o.id}`) as HTMLSelectElement)?.value || ''
                          const changed = tn !== (o.tracking_number || '')
                          const retry = o.status === 'ship_failed'
                          const alreadyShipped = o.shipping_status === '송장전송완료'
                          if (co && tn && changed && alreadyShipped) {
                            // 이미 발송된 주문 — DB만 저장, 마켓 수정은 판매자센터에서
                            const ts = fmtTime
                            try { await orderApi.update(o.id, { shipping_company: co, tracking_number: tn }) } catch { /* ignore */ }
                            patchOrder(o.id, { shipping_company: co, tracking_number: tn })
                            setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 수정 저장완료 (${co} ${tn}) — 마켓에서는 송장수정이 반영되지 않습니다. 마켓 판매자센터에서 직접 수정해주세요.`])
                          } else if (co && tn && (changed || retry)) {
                            if (_shippingInFlight.has(o.id)) return
                            _shippingInFlight.add(o.id)
                            const ts = fmtTime
                            setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 중... (${co} ${tn})`])
                            try {
                              const res = await orderApi.shipOrder(o.id, co, tn)
                              if (!res.market_sent) {
                                await orderApi.updateStatus(o.id, 'ship_failed')
                                patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                              } else {
                                patchOrder(o.id, { shipping_company: co, tracking_number: tn, shipping_status: '송장전송완료' })
                                setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} ${res.message}`])
                              }
                            } catch {
                              await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                              patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                              setLogMessages(prev => [...prev, `[${ts()}] ${o.order_number} 송장 전송 실패`])
                            } finally {
                              setTimeout(() => _shippingInFlight.delete(o.id), 1500)
                            }
                          } else if (tn && tn !== (o.tracking_number || '')) {
                            try { await orderApi.update(o.id, { tracking_number: tn }) } catch { /* ignore */ }
                            patchOrder(o.id, { tracking_number: tn })
                          }
                        }}
                        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                      />
                      <button
                        onClick={async () => {
                          const co = (document.getElementById(`ship-co-${o.id}`) as HTMLSelectElement)?.value || o.shipping_company || ''
                          const tn = (editingTrackings[o.id] ?? o.tracking_number ?? '').trim()
                          if (!co || !tn) {
                            setLogMessages(prev => [...prev, `[${fmtTime()}] ${o.order_number} 택배사/송장번호 누락 — 전송 불가`])
                            return
                          }
                          if (_shippingInFlight.has(o.id)) return
                          _shippingInFlight.add(o.id)
                          setLogMessages(prev => [...prev, `[${fmtTime()}] ${o.order_number} 마켓 전송 중... (${co} ${tn})`])
                          try {
                            const res = await orderApi.shipOrder(o.id, co, tn)
                            setLogMessages(prev => [...prev, `[${fmtTime()}] ${o.order_number} ${res.message}`])
                            if (!res.market_sent) {
                              await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                              patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                            } else {
                              patchOrder(o.id, { shipping_company: co, tracking_number: tn, shipping_status: '송장전송완료' })
                            }
                          } catch (err) {
                            await orderApi.updateStatus(o.id, 'ship_failed').catch(() => {})
                            patchOrder(o.id, { shipping_company: co, tracking_number: tn, status: 'ship_failed' })
                            setLogMessages(prev => [...prev, `[${fmtTime()}] ${o.order_number} 마켓 전송 실패: ${(err as Error).message}`])
                          } finally {
                            setTimeout(() => _shippingInFlight.delete(o.id), 1500)
                          }
                        }}
                        style={{ ...btn(o.status === 'ship_failed' ? 'dangerSolid' : 'send'), padding: '0.18rem 0.5rem', fontSize: '0.7rem', whiteSpace: 'nowrap', flexShrink: 0 }}
                        title="택배사+송장번호를 마켓에 전송 (재전송 가능)"
                      >{o.status === 'ship_failed' ? '재전송' : '마켓전송'}</button>
                    </div>

                    {/* [2026-07-02] 크림 전용 — 해외택배사 + 해외송장번호 (SNKRDUNK 해외매입 기록용, 마켓 전송 안 함) */}
                    {(String(o.source_site || '').toUpperCase().includes('KREAM') || String(o.sales_channel_alias || '').toUpperCase().includes('KREAM') || String(o.source_url || '').includes('kream.co.kr')) && (
                      <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                        <input
                          id={`ov-co-${o.id}`}
                          list={`ov-list-${o.id}`}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                          defaultValue={o.overseas_shipping_company || ''}
                          placeholder="해외택배사(일본/직접입력)"
                          onBlur={async () => {
                            const co = (document.getElementById(`ov-co-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                            const tn = (document.getElementById(`ov-tn-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                            if (co === (o.overseas_shipping_company || '') && tn === (o.overseas_tracking_number || '')) return
                            try {
                              // 해외송장번호 입력 → 상태 '국내배송중'(shipping) 자동 전환 (배송완료/확정/취소/반품은 유지)
                              const done = ['delivered', 'confirmed', 'cancelled', 'returned']
                              const patch: Partial<SambaOrder> = { overseas_shipping_company: co, overseas_tracking_number: tn }
                              if (tn && !done.includes(o.status)) patch.status = 'shipping'
                              await orderApi.update(o.id, patch); patchOrder(o.id, patch)
                            } catch { /* ignore */ }
                          }}
                        />
                        <datalist id={`ov-list-${o.id}`}>
                          {OVERSEAS_SHIPPING_COMPANIES.map(c => <option key={c} value={c} />)}
                        </datalist>
                        <input
                          id={`ov-tn-${o.id}`}
                          style={{ ...inputStyle, flex: 1, fontSize: '0.72rem' }}
                          defaultValue={o.overseas_tracking_number || ''}
                          placeholder="해외송장번호"
                          onBlur={async () => {
                            const co = (document.getElementById(`ov-co-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                            const tn = (document.getElementById(`ov-tn-${o.id}`) as HTMLInputElement)?.value.trim() || ''
                            if (co === (o.overseas_shipping_company || '') && tn === (o.overseas_tracking_number || '')) return
                            try {
                              // 해외송장번호 입력 → 상태 '국내배송중'(shipping) 자동 전환 (배송완료/확정/취소/반품은 유지)
                              const done = ['delivered', 'confirmed', 'cancelled', 'returned']
                              const patch: Partial<SambaOrder> = { overseas_shipping_company: co, overseas_tracking_number: tn }
                              if (tn && !done.includes(o.status)) patch.status = 'shipping'
                              await orderApi.update(o.id, patch); patchOrder(o.id, patch)
                            } catch { /* ignore */ }
                          }}
                          onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                        />
                        {/* SNKRDUNK 해외송장 자동조회 — 소싱주문번호(취引ID) 필요, 발송된 건만 채워짐 */}
                        <button
                          type="button"
                          title="SNKRDUNK 발송송장 자동조회"
                          style={{ ...btn('send'), padding: '0.18rem 0.5rem', fontSize: '0.7rem', whiteSpace: 'nowrap', flexShrink: 0 }}
                          onClick={async () => {
                            if (!o.sourcing_order_number) { showAlert('소싱주문번호(취引ID)가 없습니다', 'error'); return }
                            try {
                              const r = await orderApi.fetchSnkrdunkTracking(o.id)
                              if (r.success && r.shipped) {
                                // 송장 수집 성공 → 상태 '국내배송중'(shipping) (백엔드도 동일 저장)
                                patchOrder(o.id, { overseas_shipping_company: r.delivery_company || '', overseas_tracking_number: r.tracking_number || '', status: 'shipping' })
                                const coEl = document.getElementById(`ov-co-${o.id}`) as HTMLInputElement | null
                                const tnEl = document.getElementById(`ov-tn-${o.id}`) as HTMLInputElement | null
                                if (coEl) coEl.value = r.delivery_company || ''
                                if (tnEl) tnEl.value = r.tracking_number || ''
                              } else if (r.success) {
                                showAlert('아직 발송 전입니다 (송장 미발급)', 'info')
                              } else {
                                showAlert(r.error || '조회 실패', 'error')
                              }
                            } catch (e) { showAlert(e instanceof Error ? e.message : '조회 실패', 'error') }
                          }}
                        >가져오기</button>
                      </div>
                    )}

                    {/* 간단메모 */}
                    <textarea
                      style={{ ...inputStyle, fontSize: '0.72rem', resize: 'none', flex: 1, height: 0, minHeight: '1.5rem', overflowY: 'hidden' }}
                      placeholder="간단메모"
                      value={editingNotes[o.id] ?? o.notes ?? ''}
                      onChange={e => setEditingNotes(prev => ({ ...prev, [o.id]: e.target.value }))}
                      onBlur={async e => {
                        const val = e.target.value.trim()
                        if (val !== (o.notes || '')) {
                          try {
                            await orderApi.update(o.id, { notes: val })
                            patchOrder(o.id, { notes: val })
                          } catch { /* ignore */ }
                        }
                        setEditingNotes(prev => {
                          const next = { ...prev }
                          delete next[o.id]
                          return next
                        })
                      }}
                    />
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


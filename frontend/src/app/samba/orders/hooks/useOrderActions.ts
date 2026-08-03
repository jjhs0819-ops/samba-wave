'use client'

import { Dispatch, SetStateAction, useState, useEffect } from 'react'
import {
  orderApi,
  policyApi,
  type SambaOrder,
  type SambaChannel,
} from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { parseActionTags, serializeActionTags } from '../utils/actionTag'

interface OrderForm {
  channel_id: string
  product_name: string
  customer_name: string
  customer_phone: string
  customer_address: string
  sale_price: number
  cost: number
  fee_rate: number
  shipping_company: string
  tracking_number: string
  notes: string
}

interface Args {
  channels: SambaChannel[]
  form: OrderForm
  emptyForm: OrderForm
  editingId: string | null
  setShowForm: Dispatch<SetStateAction<boolean>>
  setEditingId: Dispatch<SetStateAction<string | null>>
  setForm: Dispatch<SetStateAction<OrderForm>>
  loadOrders: () => void | Promise<void>
  patchOrder: (id: string, patch: Partial<SambaOrder>) => void
  editingCosts: Record<string, string>
  setEditingCosts: Dispatch<SetStateAction<Record<string, string>>>
  editingShipFees: Record<string, string>
  setEditingShipFees: Dispatch<SetStateAction<Record<string, string>>>
  activeActions: Record<string, string | null>
  setActiveActions: Dispatch<SetStateAction<Record<string, string | null>>>
  // 일괄 처리
  bulkStatus: string
  setBulkStatus: Dispatch<SetStateAction<string>>
  bulkUpdating: boolean
  setBulkUpdating: Dispatch<SetStateAction<boolean>>
  selectedIds: Set<string>
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  setLogMessages: Dispatch<SetStateAction<string[]>>
  // 배송조회 모달 오픈 콜백
  openTrackingModal: (order: SambaOrder) => void
}

export function useOrderActions(args: Args) {
  // 크림 해외판매 수수료(정책설정) — 기본수수료(원) + 판매가 비율(%). 하드코딩 금지.
  // 옵션이 '해외배송'(박스/카드팩)인 크림 주문 정산금액에서 차감 표시. PSA 카드는 미적용.
  const [kreamOverseasFee, setKreamOverseasFee] = useState({ base: 1370, rate: 3.3 })
  // 실물(신발/의류/시계) 수수료 — 기본수수료 + 등급별 요율, VAT 별도. 등급은 매달 바뀐다.
  const [kreamItemFee, setKreamItemFee] = useState({ base: 2500, rate: 5.6, vat: 10 })
  useEffect(() => {
    policyApi.list(0, 200).then((pols) => {
      for (const p of pols) {
        const k = ((p.market_policies || {}) as Record<string, {
          kreamOverseasBaseFee?: number; kreamOverseasFeeRate?: number
          kreamItemFeeBase?: number; kreamSellerLevel?: number; kreamItemFeeVat?: number
        }>)['KREAM']
        if (k && (k.kreamOverseasBaseFee != null || k.kreamOverseasFeeRate != null)) {
          setKreamOverseasFee({ base: Number(k.kreamOverseasBaseFee ?? 1370), rate: Number(k.kreamOverseasFeeRate ?? 3.3) })
          // 등급→요율 매핑은 백엔드 margin-policy 와 동일값 유지
          const lvRate: Record<number, number> = { 5: 5.50, 4: 5.60, 3: 5.70, 2: 5.85, 1: 6.00 }
          setKreamItemFee({
            base: Number(k.kreamItemFeeBase ?? 2500),
            rate: lvRate[Number(k.kreamSellerLevel ?? 4)] ?? 5.6,
            vat: Number(k.kreamItemFeeVat ?? 10),
          })
          break
        }
      }
    }).catch(() => {})
  }, [])

  // 크림 주문의 실제 정산금액 = 판매가 − 수수료. 크림은 revenue=판매가(수수료 미차감 저장)라
  // 표시 시점에 차감한다. 카테고리별로 수수료 체계가 다르다.
  //   해외배송 옵션(박스/카드팩) → 기본 1,370 + 3.3%
  //   PSA 10 / PSA 9 카드        → 수수료 무료
  //   그 외(신발·의류·시계 등)   → 기본 2,500 + 등급요율(5.60% @4등급), VAT 별도
  // [2026-08-03] '해외배송' 문자열이 있을 때만 차감해 신발 옵션(275, 240(US 5.5))이 전부
  // 빠졌다 — 정산=결제, 수수료율 0.0% 로 표시되던 버그.
  const getRevenue = (o: SambaOrder): number => {
    const isKream = String(o.source_site || '').toUpperCase().includes('KREAM')
      || String(o.sales_channel_alias || '').toUpperCase().includes('KREAM')
    const rev = o.revenue || 0
    if (!isKream || rev <= 0) return rev
    const opt = String(o.product_option || '')
    if (opt.includes('해외배송')) {
      // 10원 단위 절사(크림 정산 표기와 일치)
      const fee = Math.floor((kreamOverseasFee.base + rev * kreamOverseasFee.rate / 100) / 10) * 10
      return rev - fee
    }
    if (/^\s*PSA\s*(9|10)\b/i.test(opt)) return rev  // PSA 카드 수수료 무료
    const itemFee = Math.floor(
      ((kreamItemFee.base + rev * kreamItemFee.rate / 100) * (1 + kreamItemFee.vat / 100)) / 10
    ) * 10
    return rev - itemFee
  }

  const {
    channels, form, emptyForm, editingId,
    setShowForm, setEditingId, setForm,
    loadOrders, patchOrder,
    editingCosts, setEditingCosts,
    editingShipFees, setEditingShipFees,
    activeActions, setActiveActions,
    bulkStatus, setBulkStatus, bulkUpdating, setBulkUpdating,
    selectedIds, setSelectedIds,
    setLogMessages,
    openTrackingModal,
  } = args

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
    try {
      await orderApi.updateStatus(id, status)
      patchOrder(id, { status })
    }
    catch (e) { showAlert(e instanceof Error ? e.message : '상태 변경 실패', 'error') }
  }

  const handleDelete = async (id: string) => {
    if (!await showConfirm('주문삭제하시겠습니까?')) return
    try { await orderApi.delete(id); loadOrders() }
    catch (e) { showAlert(e instanceof Error ? e.message : '삭제 실패', 'error') }
  }

  // 입력값 평가: 숫자/사칙연산자/괄호/소수점만 허용된 안전한 식 평가
  // - "30000*.973+2300" → 31490
  // - 빈값 → 0, 잘못된 식 → null (저장 무시)
  const evalExpr = (raw: string): number | null => {
    const expr = raw.replace(/,/g, '').trim()
    if (!expr) return 0
    if (!/^[\d+\-*/.() ]+$/.test(expr)) return null
    try {
      const result = Function(`"use strict";return (${expr})`)()
      if (typeof result !== 'number' || !Number.isFinite(result) || result < 0) return null
      return Math.round(result)
    } catch {
      return null
    }
  }

  const resolveEditingNumber = (raw: string | undefined, fallback: number) => {
    if (raw === undefined) return fallback
    const parsed = evalExpr(raw)
    return parsed === null ? fallback : parsed
  }

  const handleCostSave = async (id: string) => {
    const val = editingCosts[id]
    if (val === undefined) return
    const nextCost = evalExpr(val)
    if (nextCost === null) {
      // 잘못된 식이면 편집상태만 제거하여 원래 저장값 표시 복원
      setEditingCosts(prev => { const n = { ...prev }; delete n[id]; return n })
      return
    }
    try {
      await orderApi.update(id, { cost: nextCost })
      patchOrder(id, { cost: nextCost })
      setEditingCosts(prev => { const n = { ...prev }; delete n[id]; return n })
    } catch (e) { showAlert(e instanceof Error ? e.message : '원가 저장 실패', 'error') }
  }

  const handleShipFeeSave = async (id: string) => {
    const val = editingShipFees[id]
    if (val === undefined) return
    const nextShippingFee = evalExpr(val)
    if (nextShippingFee === null) {
      setEditingShipFees(prev => { const n = { ...prev }; delete n[id]; return n })
      return
    }
    try {
      await orderApi.update(id, { shipping_fee: nextShippingFee })
      patchOrder(id, { shipping_fee: nextShippingFee })
      setEditingShipFees(prev => { const n = { ...prev }; delete n[id]; return n })
    } catch (e) { showAlert(e instanceof Error ? e.message : '배송비 저장 실패', 'error') }
  }

  const calcProfit = (o: SambaOrder) => {
    const costVal = resolveEditingNumber(editingCosts[o.id], o.cost)
    const shipFeeVal = resolveEditingNumber(editingShipFees[o.id], o.shipping_fee)
    return getRevenue(o) - costVal - shipFeeVal
  }

  const calcProfitRate = (o: SambaOrder) => {
    const profit = calcProfit(o)
    const paymentAmount = o.total_payment_amount ?? o.sale_price
    return paymentAmount > 0 ? ((profit / paymentAmount) * 100).toFixed(1) : '0'
  }

  const calcFeeRate = (o: SambaOrder) => {
    const paymentAmount = o.total_payment_amount ?? o.sale_price
    if (paymentAmount <= 0) return '0.0'
    return (((paymentAmount - getRevenue(o)) / paymentAmount) * 100).toFixed(1)
  }

  const handleCopyOrderNumber = (orderNumber: string) => {
    navigator.clipboard.writeText(orderNumber)
    showAlert('주문번호가 복사되었습니다', 'success')
  }
  const handleDanawa = (productName: string) => {
    window.open(`https://search.danawa.com/dsearch.php?query=${encodeURIComponent(productName || '')}`, '_blank')
  }
  const handleNaver = (productName: string) => {
    window.open(`https://search.shopping.naver.com/search/all?query=${encodeURIComponent(productName || '')}`, '_blank')
  }
  const handleTracking = (order: SambaOrder) => {
    if (!order.tracking_number) {
      showAlert('송장번호가 없습니다', 'error')
      return
    }
    if (!order.shipping_company) {
      showAlert('택배사 정보가 없습니다', 'error')
      return
    }
    openTrackingModal(order)
  }

  const toggleAction = async (orderId: string, actionKey: string, currentActionTag?: string | null) => {
    // 로컬 상태가 없으면(이번 세션에 미조작) 서버값(o.action_tag)을 기준으로 삼아야
    // 서버에서 이미 활성인 태그도 재클릭 시 정상 해제됨. 로컬이 ''(해제됨)면 '' 유지.
    const currentTags = parseActionTags(activeActions[orderId] ?? currentActionTag)
    const nextTags = currentTags.includes(actionKey)
      ? currentTags.filter(tag => tag !== actionKey)
      : [...currentTags, actionKey]
    const newVal = serializeActionTags(nextTags)
    // 해제 시 null 대신 ''로 저장 — null이면 표시 로직(활성태그 ?? o.action_tag)이
    // 스테일 서버값으로 폴백해 해제 후에도 계속 활성으로 보임.
    setActiveActions(prev => ({ ...prev, [orderId]: newVal }))
    try {
      await orderApi.update(orderId, { action_tag: newVal })
    } catch { /* ignore */ }
  }

  const handleBulkAction = async () => {
    if (!bulkStatus || selectedIds.size === 0) return
    if (bulkStatus === 'delete') {
      const confirmed = await showConfirm(`선택된 ${fmtNum(selectedIds.size)}건을 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)
      if (!confirmed) return
    }
    setBulkUpdating(true)
    let ok = 0
    let fail = 0
    for (const id of selectedIds) {
      try {
        if (bulkStatus === 'delete') {
          await orderApi.delete(id)
        } else if (bulkStatus === 'confirm') {
          await orderApi.confirmOrder(id)
        } else if (bulkStatus === 'approve_cancel') {
          await orderApi.approveCancel(id)
        } else {
          await orderApi.updateStatus(id, bulkStatus)
        }
        ok++
      } catch (e) {
        fail++
        console.error('[일괄실행] 실패 id:', id, e)
      }
    }
    const actionLabel =
      bulkStatus === 'delete'         ? '삭제' :
      bulkStatus === 'confirm'        ? '발주확인' :
      bulkStatus === 'approve_cancel' ? '취소승인' :
      `상태변경→${bulkStatus}`
    const failMsg = fail > 0 ? ` (실패 ${fmtNum(fail)}건)` : ''
    setLogMessages(prev => [...prev, `[완료] 일괄 ${actionLabel}: ${fmtNum(ok)}/${fmtNum(selectedIds.size)}건${failMsg}`])
    setSelectedIds(new Set())
    setBulkStatus('')
    setBulkUpdating(false)
    await loadOrders()
  }

  const fmtNumStr = (v: string) => {
    const num = v.replace(/[^\d]/g, '')
    return num ? fmtNum(Number(num)) : ''
  }

  return {
    handleSubmit, handleStatusChange, handleDelete,
    handleCostSave, handleShipFeeSave,
    calcProfit, calcProfitRate, calcFeeRate, getRevenue,
    handleCopyOrderNumber, handleDanawa, handleNaver, handleTracking,
    toggleAction, handleBulkAction, fmtNumStr,
    bulkUpdating,
  }
}

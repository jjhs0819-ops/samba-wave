'use client'

import { Dispatch, SetStateAction } from 'react'
import {
  orderApi,
  type SambaOrder,
  type SambaChannel,
} from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'
import { DELIVERY_TRACKING_URLS } from '@/lib/samba/constants'

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
}

export function useOrderActions(args: Args) {
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

  const handleCostSave = async (id: string) => {
    const val = editingCosts[id]
    if (val === undefined) return
    try {
      const nextCost = Number(val) || 0
      await orderApi.update(id, { cost: nextCost })
      patchOrder(id, { cost: nextCost })
      setEditingCosts(prev => { const n = { ...prev }; delete n[id]; return n })
    } catch (e) { showAlert(e instanceof Error ? e.message : '원가 저장 실패', 'error') }
  }

  const handleShipFeeSave = async (id: string) => {
    const val = editingShipFees[id]
    if (val === undefined) return
    try {
      const nextShippingFee = Number(val) || 0
      await orderApi.update(id, { shipping_fee: nextShippingFee })
      patchOrder(id, { shipping_fee: nextShippingFee })
      setEditingShipFees(prev => { const n = { ...prev }; delete n[id]; return n })
    } catch (e) { showAlert(e instanceof Error ? e.message : '배송비 저장 실패', 'error') }
  }

  const calcProfit = (o: SambaOrder) => {
    const costVal = editingCosts[o.id] !== undefined ? Number(editingCosts[o.id]) || 0 : o.cost
    const shipFeeVal = editingShipFees[o.id] !== undefined ? Number(editingShipFees[o.id]) || 0 : o.shipping_fee
    return o.revenue - costVal - shipFeeVal
  }

  const calcProfitRate = (o: SambaOrder) => {
    const profit = calcProfit(o)
    return o.sale_price > 0 ? ((profit / o.sale_price) * 100).toFixed(1) : '0'
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
  const handleTracking = (shippingCompany: string, trackingNumber: string) => {
    if (!trackingNumber) {
      showAlert('송장번호가 없습니다', 'error')
      return
    }
    const baseUrl = DELIVERY_TRACKING_URLS[shippingCompany] || DELIVERY_TRACKING_URLS['CJ대한통운']
    window.open(`${baseUrl}${trackingNumber}`, '_blank')
  }

  const toggleAction = async (orderId: string, actionKey: string) => {
    const newVal = activeActions[orderId] === actionKey ? null : actionKey
    setActiveActions(prev => ({ ...prev, [orderId]: newVal }))
    try {
      await orderApi.update(orderId, { action_tag: newVal || '' })
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
    for (const id of selectedIds) {
      try {
        if (bulkStatus === 'delete') {
          await orderApi.delete(id)
        } else if (bulkStatus === 'confirm') {
          await orderApi.confirmOrder(id)
        } else if (bulkStatus === 'approve_cancel') {
          await orderApi.approveCancel(id)
        } else {
          await orderApi.update(id, { status: bulkStatus })
        }
        ok++
      } catch { /* ignore */ }
    }
    const actionLabel =
      bulkStatus === 'delete'         ? '삭제' :
      bulkStatus === 'confirm'        ? '발주확인' :
      bulkStatus === 'approve_cancel' ? '취소승인' :
      `상태변경→${bulkStatus}`
    setLogMessages(prev => [...prev, `[완료] 일괄 ${actionLabel}: ${fmtNum(ok)}/${fmtNum(selectedIds.size)}건`])
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
    calcProfit, calcProfitRate,
    handleCopyOrderNumber, handleDanawa, handleNaver, handleTracking,
    toggleAction, handleBulkAction, fmtNumStr,
    bulkUpdating,
  }
}

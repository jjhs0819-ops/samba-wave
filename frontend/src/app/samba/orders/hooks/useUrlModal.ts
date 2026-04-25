'use client'

import { useState } from 'react'
import { orderApi, type SambaOrder } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'

interface Args {
  orders: SambaOrder[]
  loadOrders: () => void | Promise<void>
}

export function useUrlModal({ orders, loadOrders }: Args) {
  const [showUrlModal, setShowUrlModal] = useState(false)
  const [urlModalOrderId, setUrlModalOrderId] = useState('')
  const [urlModalInput, setUrlModalInput] = useState('')
  const [urlModalImageInput, setUrlModalImageInput] = useState('')
  const [urlModalSaving, setUrlModalSaving] = useState(false)

  const openUrlModal = (orderId: string) => {
    const target = orders.find(o => o.id === orderId)
    setUrlModalOrderId(orderId)
    setUrlModalInput(target?.source_url || '')
    setUrlModalImageInput(target?.product_image || '')
    setShowUrlModal(true)
  }

  const handleUrlSubmit = async () => {
    if (!urlModalInput.trim() && !urlModalImageInput.trim()) {
      showAlert('URL을 입력해주세요', 'error')
      return
    }
    setUrlModalSaving(true)
    try {
      const url = urlModalInput.trim()
      const imgUrl = urlModalImageInput.trim()
      await orderApi.update(urlModalOrderId, {
        ...(url ? { source_url: url } : {}),
        ...(imgUrl ? { product_image: imgUrl } : {}),
      })
      setShowUrlModal(false)
      setUrlModalInput('')
      setUrlModalImageInput('')
      loadOrders()
      showAlert('미등록 상품 정보가 등록되었습니다', 'success')
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '저장 실패', 'error')
    }
    setUrlModalSaving(false)
  }

  return {
    showUrlModal, setShowUrlModal,
    urlModalInput, setUrlModalInput,
    urlModalImageInput, setUrlModalImageInput,
    urlModalSaving,
    openUrlModal, handleUrlSubmit,
  }
}

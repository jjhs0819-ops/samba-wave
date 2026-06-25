// content-purchase-gs-order.js — GS샵 직배/까대기 주문처리
;(() => {
  if (window.__sambaGSOrderLoaded) return
  window.__sambaGSOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  // ── 옵션 선택 (확인: .colorattrSel.tmp-select2 > a.current 열기 → ul li a 텍스트 매칭) ──
  async function selectOption(val) {
    val = String(val).trim()
    if (!val) return true
    const parts = val.split('/').map(s => s.trim())
    for (const part of parts) {
      // opener 클릭
      const opener = document.querySelector('.tmp-select2 > a.current, .colorattrSel > a.current, .optionTxt')
      if (opener) { opener.click(); await sleep(800) }
      // 항목 클릭 (current 제외)
      const items = Array.from(document.querySelectorAll('.tmp-select2 a, .colorattrSel a, a.prditmidSel0, .prditmidSel a'))
        .filter(a => !a.classList.contains('current'))
      const target = items.find(a => {
        const t = a.textContent.trim()
        return t === part || t.startsWith(part + '/') || t.startsWith(part + ' ')
      })
      if (target) { target.click(); await sleep(800) }
    }
    return true
  }

  // ── 바로구매 (확인: button#ordButtn) ──
  async function clickBuyNow() {
    const btn = document.querySelector('#ordButtn')
    if (btn && !btn.disabled) { btn.click(); await sleep(3000); return true }
    // 폴백
    for (const b of document.querySelectorAll('button, a')) {
      if (b.textContent.trim() === '바로구매' || b.textContent.trim() === '구매하기') { b.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 주문서: 배송지 변경 (확인: #rcvrNm0, #dlvRcvrCelphn*Telno0 3칸) ──
  function setInputVal(id, val) {
    const el = document.getElementById(id)
    if (!el) return false
    el.value = val
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
    return true
  }
  async function changeShipping(name, phone, address, detail) {
    if (!name) return
    setInputVal('rcvrNm0', name)
    // 전화 3칸 분리 (010-1234-5678 or 01012345678)
    const digits = (phone || '').replace(/\D/g, '')
    if (digits.length >= 10) {
      setInputVal('dlvRcvrCelphnRegonTelno0', digits.slice(0, 3))
      setInputVal('dlvRcvrCelphnTxnoTelno0', digits.slice(3, 7))
      setInputVal('dlvRcvrCelphnDtlTelno0', digits.slice(7))
    }
    if (address) {
      setInputVal('roadNmbaseAddr0', address)
      setInputVal('roadNmdtlAddr0', detail || '')
    }
    await sleep(500)
  }

  // ── 주문서: 쿠폰 ──
  async function selectCoupon() {
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim().includes('쿠폰')) { btn.click(); await sleep(1500); break }
    }
    const dlg = document.querySelector('[role="dialog"], .coupon_area, .coupon_layer, .layer_coupon')
    if (dlg) {
      const items = dlg.querySelectorAll('[role="radio"], li, .coupon_item')
      if (items.length) { items[0].click(); await sleep(500) }
      for (const btn of dlg.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t === '적용' || t === '확인') { btn.click(); await sleep(1000); break }
      }
    }
  }

  // ── 주문서: 실구매가 계산 (GS샵 실측: em.txt_moneys, td.td-order-amount) ──
  function computeActualCost() {
    const parse = (sel) => {
      const el = document.querySelector(sel)
      return el ? parseInt((el.textContent || '').replace(/[^\d]/g, '')) || 0 : 0
    }
    const finalAmount = parse('em.txt_moneys') || parse('td.td-order-amount') || parse('.pay_price em') || 0
    return { finalAmount, actualCost: finalAmount }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /gsshop\.com\/ord\//.test(window.location.href)
        if (!isOrderForm) {
          if (productOption) {
            const ok = await selectOption(productOption)
            if (!ok) { sendResponse({ success: false, error: `옵션 "${productOption}" 선택 실패` }); return }
          }
          await sleep(800)
          const ok = await clickBuyNow()
          if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          await sleep(1500)
          if (orderType === 'direct' || orderType === 'kkadaegi') await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          await selectCoupon()
          const costInfo = computeActualCost()
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

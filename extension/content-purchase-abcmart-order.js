// content-purchase-abcmart-order.js — ABCmart / GrandStage 직배/까대기 주문처리
// 확인된 셀렉터 (GrandStage 기준):
//   바로구매: button.btn.btn-lg (텍스트 '바로구매')
//   옵션: select#selectboxoptionlist (색상), select#search-optn-name (사이즈, display:none jQuery UI)
;(() => {
  if (window.__sambaABCOrderLoaded) return
  window.__sambaABCOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  function triggerJQSelect(sel, val) {
    const target = Array.from(sel.options).find(o => !o.disabled && (o.text.trim() === val || o.text.trim().startsWith(val + ' ') || o.value === val))
    if (!target) return false
    sel.value = target.value
    // jQuery UI select: change 이벤트 + jQuery trigger
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    sel.dispatchEvent(new Event('input', { bubbles: true }))
    if (window.jQuery || window.$) {
      try { (window.jQuery || window.$)(sel).trigger('change') } catch {}
    }
    return true
  }

  // ── 옵션 선택 (select#selectboxoptionlist → select#search-optn-name) ──
  async function selectSize(val) {
    val = String(val).trim()
    if (!val) return true
    const parts = val.split('/').map(s => s.trim())
    const candidates = [
      document.querySelector('select#selectboxoptionlist'),
      document.querySelector('select#search-optn-name'),
      document.querySelector('select#actionbar_selectboxoptionlist'),
    ].filter(Boolean)
    for (const part of parts) {
      for (const sel of candidates) {
        if (triggerJQSelect(sel, part)) { await sleep(900); break }
      }
    }
    return true
  }

  // ── 바로구매 (확인: button.btn.btn-lg 텍스트 '바로구매') ──
  async function clickBuyNow() {
    for (const btn of document.querySelectorAll('button.btn-lg, button.btn')) {
      if (btn.textContent.trim() === '바로구매') { btn.click(); await sleep(3000); return true }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '바로구매' || t === '구매하기' || t === '주문하기') { btn.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 주문서: 배송지 변경 ──
  async function changeShipping(name, phone, address, detail) {
    if (!name || !address) return
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '배송지 변경' || t === '새 배송지' || t === '배송지 추가' || t === '다른 배송지') { btn.click(); await sleep(1500); break }
    }
    const inputs = [...document.querySelectorAll('input[type="text"],input:not([type])')]
    const fill = (ph, v) => {
      const el = inputs.find(i => (i.placeholder || '').includes(ph))
      if (el) { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })) }
    }
    fill('이름', name); fill('수령', name); fill('연락', phone); fill('전화', phone)
    fill('주소', address); fill('상세', detail || '')
    await sleep(500)
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '저장' || t === '확인' || t === '완료') { btn.click(); await sleep(1500); break }
    }
  }

  // ── 주문서: 쿠폰 ──
  async function selectCoupon() {
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim().includes('쿠폰')) { btn.click(); await sleep(1500); break }
    }
    const dlg = document.querySelector('[role="dialog"], .layer-coupon, .coupon-area, .coupon_layer')
    if (dlg) {
      const items = dlg.querySelectorAll('[role="radio"], li')
      if (items.length) { items[0].click(); await sleep(500) }
      for (const btn of dlg.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t === '적용' || t === '확인') { btn.click(); await sleep(1000); break }
      }
    }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /a-rt\.com\/(order|payment|checkout)/.test(window.location.href)
        if (!isOrderForm) {
          if (productOption) await selectSize(productOption)
          await sleep(800)
          const ok = await clickBuyNow()
          if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          await sleep(1500)
          if (orderType === 'direct') await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          await selectCoupon()
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

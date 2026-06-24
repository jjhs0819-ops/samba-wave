// content-purchase-ssg-order.js — SSG 직배/까대기 주문처리
// 확인된 셀렉터: 바로구매 a#actionPayment, 옵션 select#ordOpt1(색상)/select#ordOpt2(사이즈)
;(() => {
  if (window.__sambaSSGOrderLoaded) return
  window.__sambaSSGOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  // 가구매(content-purchase-ssg.js)와 동일한 방식: focus+change+input+blur 4종
  function triggerSelect(sel, val) {
    const target = Array.from(sel.options).find(o => !o.disabled && (
      o.text.trim() === val || o.value === val ||
      o.text.trim().startsWith(val + ' ') || o.text.trim().startsWith(val + '/')
    ))
    if (!target) return false
    sel.value = target.value
    sel.dispatchEvent(new Event('focus', { bubbles: true }))
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    sel.dispatchEvent(new Event('input', { bubbles: true }))
    sel.dispatchEvent(new Event('blur', { bubbles: true }))
    return true
  }

  // ── 옵션 선택 (가구매와 동일: 모든 select 순환, 폴백 li/[data-opt-no]) ──
  async function selectOption(val) {
    val = String(val).trim()
    if (!val) return true
    const parts = val.split('/').map(s => s.trim())
    for (const part of parts) {
      let matched = false
      for (const sel of document.querySelectorAll('select')) {
        if (triggerSelect(sel, part)) { matched = true; await sleep(700); break }
      }
      if (!matched) {
        // 폴백: li/커스텀 옵션
        for (const item of document.querySelectorAll('.opt_list li, .option_list li, [data-opt-no], [data-opt-val]')) {
          const t = item.textContent.trim()
          if (t === part || t.startsWith(part + ' ')) { item.click(); await sleep(700); matched = true; break }
        }
      }
    }
    return true
  }

  // ── 바로구매 (확인: a#actionPayment) ──
  async function clickBuyNow() {
    const btn = document.querySelector('#actionPayment')
    if (btn) { btn.click(); await sleep(3000); return true }
    // 폴백
    for (const b of document.querySelectorAll('button, a')) {
      if (b.textContent.trim() === '바로구매') { b.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 주문서: 배송지 변경 ──
  async function changeShipping(name, phone, address, detail) {
    if (!name || !address) return
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '배송지 변경' || t === '배송지 추가' || t === '새 배송지') { btn.click(); await sleep(1500); break }
    }
    const inputs = [...document.querySelectorAll('input[type="text"],input:not([type])')]
    const fill = (ph, v) => {
      const el = inputs.find(i => (i.placeholder || '').includes(ph))
      if (el) { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) }
    }
    fill('이름', name); fill('연락', phone); fill('전화', phone)
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
      const t = btn.textContent.trim()
      if (t.includes('쿠폰') && (t.includes('선택') || t.includes('적용') || t.includes('없음'))) { btn.click(); await sleep(1500); break }
    }
    const dlg = document.querySelector('[role="dialog"], .layer_coupon, .coupon_list')
    if (dlg) {
      const items = dlg.querySelectorAll('[role="radio"], li.coupon_item, .coupon_item')
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
        const isOrderForm = /(pay\.ssg\.com|ssg\.com)\/(order|payment)/.test(window.location.href)
        if (!isOrderForm) {
          if (productOption) await selectOption(productOption)
          await sleep(800)
          const ok = await clickBuyNow()
          if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          // 배송지 변경은 background(_handleSsgShippingPopup)에서 처리 완료됨
          await sleep(800)
          await selectCoupon()
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

// content-purchase-ssg-order.js — SSG 직배/까대기/선물 주문처리
// 확인된 셀렉터 (CDP 실측):
//   바로구매: a.cdtl_btn_red.cdtl_btn_buy (텍스트 '바로구매')
//   선물하기: a.cdtl_gift_btn (텍스트 '선물')
//   옵션: select#ordOpt1._dropdown (jQuery trigger 필요)
// 배송지 변경: background._handleSsgShippingPopup 에서 처리 (직배/까대기)
;(() => {
  if (window.__sambaSSGOrderLoaded) return
  window.__sambaSSGOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

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

  function jqTrigger(sel) {
    // SSG는 jQuery UI select: native이벤트 + jQuery trigger 필요
    if (window.jQuery || window.$) {
      try { (window.jQuery || window.$)(sel).trigger('change') } catch {}
    }
  }

  async function selectOption(val) {
    val = String(val).trim()
    if (!val) return true
    const parts = val.split('/').map(s => s.trim())
    for (const part of parts) {
      let matched = false
      // SSG: select#ordOpt1._dropdown, select#ordOpt2._dropdown 등
      const sels = [...document.querySelectorAll('select._dropdown, select#ordOpt1, select#ordOpt2')]
      if (!sels.length) {
        // 폴백: 모든 select
        for (const sel of document.querySelectorAll('select')) {
          if (triggerSelect(sel, part)) { jqTrigger(sel); matched = true; await sleep(700); break }
        }
      } else {
        for (const sel of sels) {
          if (triggerSelect(sel, part)) { jqTrigger(sel); matched = true; await sleep(700); break }
        }
      }
      if (!matched) {
        for (const item of document.querySelectorAll('.opt_list li, .option_list li, [data-opt-no], [data-opt-val]')) {
          const t = item.textContent.trim()
          if (t === part || t.startsWith(part + ' ')) { item.click(); await sleep(700); matched = true; break }
        }
      }
    }
    return true
  }

  async function clickBuyNow() {
    // 실측: a.cdtl_btn_red.cdtl_btn_buy 텍스트='바로구매'
    const btn = document.querySelector('a.cdtl_btn_red.cdtl_btn_buy, a.cdtl_btn_buy')
      || [...document.querySelectorAll('a, button')].find(b => b.offsetHeight > 0 && b.textContent.trim() === '바로구매')
    if (btn) { btn.click(); await sleep(3000); return true }
    return false
  }

  // ── 선물하기 버튼 클릭 ──
  async function clickGift() {
    // 실측: a.cdtl_gift_btn 텍스트='선물'
    const btn = document.querySelector('a.cdtl_gift_btn')
      || [...document.querySelectorAll('a, button')].find(b => b.offsetHeight > 0 && b.textContent.trim().includes('선물') && !b.textContent.trim().includes('룰렛'))
    if (btn) { btn.click(); await sleep(3000); return true }
    return false
  }

  // native setter
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  const setVal = (el, v) => {
    if (!el) return
    if (nativeSetter) nativeSetter.call(el, v)
    else el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // ── 선물 주문서: 수령인/전화 입력 ──
  async function fillGiftRecipient(name, phone) {
    if (!name) return
    await sleep(1000)
    const nameEl = document.querySelector('input[placeholder*="이름"]') ||
      document.querySelector('input[placeholder*="수령인"]') ||
      document.querySelector('input[name*="rcvNm"], input[id*="rcvNm"]')
    if (nameEl) setVal(nameEl, name)

    const phoneEl = document.querySelector('input[placeholder*="전화"]') ||
      document.querySelector('input[placeholder*="휴대"]') ||
      document.querySelector('input[type="tel"], input[name*="rcvPhone"]')
    if (phoneEl) setVal(phoneEl, (phone || '').replace(/-/g, ''))

    await sleep(300)
  }

  // ── 실구매가 계산 ──
  function computeActualCost() {
    const getText = (sel) => {
      const el = document.querySelector(sel)
      return el ? parseInt((el.textContent || '').replace(/[^\d]/g, '')) || 0 : 0
    }
    const finalAmount = getText('#totalPayAmt, .total_pay em, .pay_total_price em, [id*="totalPay"]') ||
      getText('#totalPayAmt, .total_pay, .pay_total_price') || 0
    return { finalAmount, actualCost: finalAmount }
  }

  // ── 쿠폰 ──
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
        const { orderType, productOption, shippingName, shippingPhone } = msg
        const isOrderForm = /(pay\.ssg\.com|ssg\.com)\/(order|payment)/.test(window.location.href)
        if (!isOrderForm) {
          if (productOption) await selectOption(productOption)
          await sleep(800)
          let ok = false
          if (orderType === 'gift') {
            ok = await clickGift()
            if (!ok) { sendResponse({ success: false, error: '선물하기 버튼 못 찾음' }); return }
          } else {
            ok = await clickBuyNow()
            if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          // 직배/까대기 배송지는 background._handleSsgShippingPopup에서 처리 완료됨
          await sleep(800)
          if (orderType === 'gift') {
            await fillGiftRecipient(shippingName, shippingPhone)
          }
          await selectCoupon()
          const costInfo = computeActualCost()
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

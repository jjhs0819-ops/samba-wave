// content-purchase-lotteon-order.js — 롯데ON 직배/까대기/선물 주문처리
// 확인된 셀렉터: 바로구매 button.hasBgColor.bgColorRed(텍스트 '바로 구매하기')
// 선물하기: button.gift (텍스트 '선물하기') — CDP 실측 확인
// 옵션: 커스텀 드롭다운 (.selectResult label 클릭 → ul.selectLists li .caption 텍스트 클릭)
;(() => {
  if (window.__sambaLotteonOrderLoaded) return
  window.__sambaLotteonOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  // ── 옵션 선택 (커스텀 드롭다운) ──
  // 구조: .optionWrap > .selectResult > label → 클릭 → ul.selectLists 열림 → li > .labelTextWrap > .caption 클릭
  async function selectOption(val) {
    val = String(val).trim()
    if (!val) return true
    const parts = val.split('/').map(s => s.trim())
    for (const part of parts) {
      for (const wrap of document.querySelectorAll('.optionWrap')) {
        const label = wrap.querySelector('.selectResult label, .selectResult')
        if (label) { label.click(); await sleep(700) }
        const ul = wrap.querySelector('ul.selectLists')
        if (!ul) continue
        let found = false
        for (const li of ul.querySelectorAll('li')) {
          const caption = li.querySelector('.caption, .labelTextWrap span')
          const t = (caption || li).textContent.trim()
          if (t === part || t.startsWith(part + ' ') || t.startsWith(part + '/')) {
            li.click(); await sleep(800); found = true; break
          }
        }
        if (found) break
        if (label) label.click()
      }
      await sleep(300)
    }
    return true
  }

  // ── 바로구매 ──
  async function clickBuyNow() {
    for (const btn of document.querySelectorAll('button.hasBgColor, button')) {
      const t = btn.textContent.trim()
      if (t === '바로 구매하기' || t === '바로구매') { btn.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 선물하기 버튼 클릭 (상품 페이지) ──
  async function clickGift() {
    const btn = [...document.querySelectorAll('button.gift, button[class*="gift"]')].find(b => b.offsetHeight > 0 && b.textContent.includes('선물'))
    if (btn) { btn.click(); await sleep(3000); return true }
    return false
  }

  // ── native setter (Vue readonly input 우회) ──
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  const setVal = (el, v) => {
    if (!el) return
    if (nativeSetter) nativeSetter.call(el, v)
    else el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // ── 주문서: 배송지 변경 (직배/까대기) ──
  // 실측 셀렉터: button.btn-plus 텍스트='배송지 수정하기'
  async function changeShipping(name, phone, address, detail) {
    if (!name) return
    const changeBtn = document.querySelector('button.btn-plus') ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '배송지 수정하기' && b.offsetHeight > 0) ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '변경' && b.offsetHeight > 0)
    if (!changeBtn) return
    changeBtn.click()
    await sleep(1500)

    const modal = document.querySelector('[role="dialog"], .v--modal-box')
    if (!modal) return

    const radios = Array.from(modal.querySelectorAll('input[type="radio"]'))
    let selected = false
    for (const r of radios) {
      const container = r.closest('li, label, div')
      if (container && container.textContent.includes(name)) {
        r.click(); await sleep(500); selected = true; break
      }
    }

    if (!selected) {
      const newBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.includes('새 배송지') || b.textContent.includes('배송지 추가'))
      if (newBtn) { newBtn.click(); await sleep(1000) }

      const nameEl = modal.querySelector('input[placeholder*="받는 분"]') ||
        Array.from(modal.querySelectorAll('input[type="text"]')).find(i => !i.readOnly)
      setVal(nameEl, name)

      const phoneEl = modal.querySelector('input[placeholder*="휴대폰"]') ||
        Array.from(modal.querySelectorAll('input[type="tel"]')).find(i => !i.readOnly)
      setVal(phoneEl, (phone || '').replace(/-/g, ''))

      await sleep(300)
      const saveBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.trim() === '저장')
      if (saveBtn) { saveBtn.click(); await sleep(1500) }
    }

    const confirmBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '확인')
    if (confirmBtn) { confirmBtn.click(); await sleep(1500) }
  }

  // ── 선물 주문서: 수령인/전화 입력 ──
  // 실측: #phoneReceiverMbNm0 (이름), #receiverPhoneNumber0 (전화)
  // radio giftSendOption_single_phone = 기본 체크됨 (전화번호로 보내기)
  async function fillGiftRecipient(name, phone) {
    if (!name) return
    await sleep(800)
    const nameEl = document.querySelector('#phoneReceiverMbNm0') ||
      document.querySelector('input[placeholder="이름"]')
    if (nameEl) setVal(nameEl, name)

    const phoneEl = document.querySelector('#receiverPhoneNumber0') ||
      document.querySelector('input[placeholder="전화번호"][type="tel"]')
    if (phoneEl) setVal(phoneEl, (phone || '').replace(/-/g, ''))

    await sleep(300)
  }

  // ── 주문서: 쿠폰 ──
  async function selectCoupon() {
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim().includes('쿠폰')) { btn.click(); await sleep(1500); break }
    }
    const dlg = document.querySelector('[role="dialog"], .coupon_area, .coupon_list, .layer_coupon')
    if (dlg) {
      const items = dlg.querySelectorAll('[role="radio"], li, .coupon_item')
      if (items.length) { items[0].click(); await sleep(500) }
      for (const btn of dlg.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t === '적용' || t === '확인') { btn.click(); await sleep(1000); break }
      }
    }
  }

  // ── 실구매가 계산 ──
  function computeActualCost() {
    const getText = (sel) => {
      const el = document.querySelector(sel)
      return el ? parseInt((el.textContent || '').replace(/[^\d]/g, '')) || 0 : 0
    }
    // 실측: .totalPriceNum SPAN = '89,000'
    const finalAmount = getText('.totalPriceNum') ||
      getText('.totalPriceDetail') || 0
    return { finalAmount, actualCost: finalAmount }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /lotteon\.com\/(p\/)?order/.test(window.location.href)
        if (!isOrderForm) {
          // 상품 페이지: 옵션 선택 + 구매/선물 버튼 클릭
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
          // 주문서 페이지
          await sleep(1500)
          if (orderType === 'direct' || orderType === 'kkadaegi') {
            await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          } else if (orderType === 'gift') {
            await fillGiftRecipient(shippingName, shippingPhone)
          }
          await selectCoupon()
          // 롯데ON 1페이지(orders/N) → 계속하기 → payments 페이지
          const continueBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '계속하기')
          const costInfo = computeActualCost()
          if (continueBtn) {
            sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
            continueBtn.click()
            return
          }
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

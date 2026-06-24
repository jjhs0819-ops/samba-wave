// content-purchase-lotteon-order.js — 롯데ON 직배/까대기 주문처리
// 확인된 셀렉터: 바로구매 button.hasBgColor.bgColorRed(텍스트 '바로 구매하기')
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
      // 모든 optionWrap을 순서대로 시도
      for (const wrap of document.querySelectorAll('.optionWrap')) {
        const label = wrap.querySelector('.selectResult label, .selectResult')
        if (label) { label.click(); await sleep(700) }
        // 열린 ul에서 항목 찾기
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
        // 못 찾으면 닫기 (label 다시 클릭)
        if (label) label.click()
      }
      await sleep(300)
    }
    return true
  }

  // ── 바로구매 (확인: button.hasBgColor.bgColorRed, 텍스트 '바로 구매하기') ──
  async function clickBuyNow() {
    for (const btn of document.querySelectorAll('button.hasBgColor, button')) {
      const t = btn.textContent.trim()
      if (t === '바로 구매하기' || t === '바로구매') { btn.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 주문서: 배송지 변경 ──
  async function changeShipping(name, phone, address, detail) {
    if (!name || !address) return
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '배송지 변경' || t === '새 배송지' || t === '배송지 추가') { btn.click(); await sleep(1500); break }
    }
    const inputs = [...document.querySelectorAll('input[type="text"],input:not([type])')]
    const fill = (ph, v) => {
      const el = inputs.find(i => (i.placeholder || '').includes(ph))
      if (el) { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })) }
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

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /lotteon\.com\/(p\/)?order/.test(window.location.href)
        if (!isOrderForm) {
          if (productOption) await selectOption(productOption)
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

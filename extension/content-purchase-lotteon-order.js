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
  // 롯데ON payments 구조: '변경' 버튼 → 배송지 등록 폼 모달 열림 → 이름/전화 입력 → 저장
  async function changeShipping(name, phone, address, detail) {
    if (!name) return
    // 배송지 변경 버튼 클릭 (텍스트 '변경')
    const changeBtn = document.querySelector('button.btnAddress') ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '변경' && b.offsetHeight > 0)
    if (!changeBtn) return
    changeBtn.click()
    await sleep(1500)

    const modal = document.querySelector('[role="dialog"], .v--modal-box')
    if (!modal) return

    // native setter로 Vue readonly input 우회
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    const setVal = (el, v) => {
      if (!el) return
      if (nativeSetter) nativeSetter.call(el, v)
      else el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }

    // 배송지 목록에서 이름 매칭 시도 (목록 선택 방식)
    const radios = Array.from(modal.querySelectorAll('input[type="radio"]'))
    let selected = false
    for (const r of radios) {
      const container = r.closest('li, label, div')
      if (container && container.textContent.includes(name)) {
        r.click()
        await sleep(500)
        selected = true
        break
      }
    }

    if (!selected) {
      // 새 배송지 추가 버튼 클릭 (있으면)
      const newBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.includes('새 배송지') || b.textContent.includes('배송지 추가'))
      if (newBtn) { newBtn.click(); await sleep(1000) }

      // 이름 입력 (placeholder: '받는 분을 입력해 주세요.')
      const nameEl = modal.querySelector('input[placeholder*="받는 분"]') ||
        Array.from(modal.querySelectorAll('input[type="text"]')).find(i => !i.readOnly)
      setVal(nameEl, name)

      // 전화 입력 (placeholder: '-없이 휴대폰 번호를 입력해 주세요.')
      const phoneEl = modal.querySelector('input[placeholder*="휴대폰"]') ||
        Array.from(modal.querySelectorAll('input[type="tel"]')).find(i => !i.readOnly)
      setVal(phoneEl, (phone || '').replace(/-/g, ''))

      await sleep(300)

      // 저장 버튼 클릭 (배송지 등록 폼)
      const saveBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.trim() === '저장')
      if (saveBtn) { saveBtn.click(); await sleep(1500) }
    }

    // 확인 버튼 클릭 (배송지 선택 모달)
    const confirmBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '확인')
    if (confirmBtn) { confirmBtn.click(); await sleep(1500) }
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
          // 롯데ON 주문서 1페이지(orders/N)에서 계속하기 클릭 → 결제 페이지(payments)로 이동
          const continueBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '계속하기')
          if (continueBtn) {
            sendResponse({ success: true, status: 'ready-to-pay' })
            continueBtn.click()
            return
          }
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

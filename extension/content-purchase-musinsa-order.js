// content-purchase-musinsa-order.js — 무신사 직배/까대기 주문처리
// 상품 페이지: 옵션 선택 → 바로구매 → 주문서 이동
// 주문서 페이지: 배송지 입력 → 쿠폰 자동선택 → 결제 직전 대기
;(() => {
  if (window.__sambaMusinsaOrderLoaded) return
  window.__sambaMusinsaOrderLoaded = true

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  // 무신사 alert/confirm 차단 (옵션 선택 시 팝업 차단)
  ;(function blockAlert() {
    try {
      Object.defineProperty(window, 'alert', { value: () => {}, writable: false, configurable: false })
      Object.defineProperty(window, 'confirm', { value: () => true, writable: false, configurable: false })
    } catch (e) {
      window.alert = () => {}
      window.confirm = () => true
    }
  })()

  // ── 상품 페이지: 옵션 선택 ──
  // option 형식: "FREE" 또는 "BLACK/FREE" (컬러/사이즈 '/' 구분)
  async function selectSize(option) {
    const val = String(option).trim()
    if (!val) return true

    const parts = val.split('/').map(s => s.trim())

    // 무신사 새 UI: DropdownTriggerBox 방식 (컬러 선택 후 사이즈 박스가 동적으로 생성됨)
    const hasBoxes = document.querySelector('[data-mds="DropdownTriggerBox"]')
    if (hasBoxes) {
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i]
        await sleep(400)

        // 현재 존재하는 DropdownTriggerBox 재조회 (동적 생성 대응)
        const boxes = Array.from(document.querySelectorAll('[data-mds="DropdownTriggerBox"]'))
        if (boxes.length === 0) break

        // 아직 선택 안 된 (closed) 박스 우선, 없으면 i번째
        const targetBox = boxes.find(b => b.getAttribute('data-state') === 'closed' && !b.querySelector('[data-mds="DropdownTriggerInput"]')?.value?.trim()) || boxes[i] || boxes[boxes.length - 1]
        const ph = targetBox.querySelector('[data-mds="DropdownTriggerInput"]')?.getAttribute('placeholder') || ''

        // 박스 클릭으로 드롭다운 열기
        targetBox.click()
        await sleep(500)

        // DropdownItemContent__Container에서 part 텍스트 매칭
        const containers = Array.from(document.querySelectorAll('[class*="DropdownItemContent__Container"]'))
        let matched = false
        for (const c of containers) {
          const t = c.textContent.trim()
          if (t === part || t.startsWith(part) || t.toLowerCase().includes(part.toLowerCase())) {
            c.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
            c.click()
            c.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
            await sleep(500)
            console.log(`[삼바-주문처리-무신사] TriggerBox[${ph}] "${part}" 선택`)
            matched = true
            break
          }
        }
        if (!matched) {
          if (containers.length > 0) {
            containers[0].dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
            containers[0].click()
            await sleep(500)
            console.log(`[삼바-주문처리-무신사] TriggerBox[${ph}] 첫 항목 자동선택 (${containers[0].textContent.trim()})`)
          } else {
            console.log(`[삼바-주문처리-무신사] TriggerBox[${ph}] "${part}" 항목 없음`)
          }
        }
      }

      // 제공된 parts 선택 후 남은 미선택 드롭다운 자동 첫번째 선택 (컬러 등 추가 옵션)
      await sleep(400)
      const remainingBoxes = Array.from(document.querySelectorAll('[data-mds="DropdownTriggerBox"]'))
      for (const box of remainingBoxes) {
        const inp = box.querySelector('[data-mds="DropdownTriggerInput"]')
        if (inp && (!inp.value || !inp.value.trim())) {
          const ph = inp.getAttribute('placeholder') || ''
          box.click()
          await sleep(500)
          const containers = Array.from(document.querySelectorAll('[class*="DropdownItemContent__Container"]'))
          const available = containers.filter(c => !c.closest('[aria-disabled="true"]') && !c.closest('[class*="disabled"]'))
          const target = available.length > 0 ? available[0] : containers[0]
          if (target) {
            target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
            target.click()
            target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
            await sleep(500)
            console.log(`[삼바-주문처리-무신사] 남은 드롭다운[${ph}] 자동선택: ${target.textContent.trim()}`)
          }
        }
      }

      return true
    }

    // DropdownTriggerInput 방식 폴백
    const triggers = Array.from(document.querySelectorAll('[data-mds="DropdownTriggerInput"]'))
    if (triggers.length > 0) {
      for (let i = 0; i < triggers.length; i++) {
        const part = parts[i] || parts[parts.length - 1]
        const trigger = triggers[i]
        const ph = trigger.getAttribute('placeholder') || ''
        if (trigger.value && trigger.value.trim() && part && trigger.value.trim().toLowerCase().includes(part.toLowerCase())) {
          console.log(`[삼바-주문처리-무신사] DropdownTrigger[${ph}] 이미 "${trigger.value}" 선택됨 — 스킵`)
          continue
        }
        trigger.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
        trigger.click()
        await sleep(400)

        let matched = false
        const candidates = Array.from(document.querySelectorAll('[class*="DropdownItemContent"],[class*="SelectedOption__SelectOptionItem"]'))
        for (const el of candidates) {
          const t = el.textContent.trim()
          if (t === part || t.startsWith(part + ' ') || t.toLowerCase() === part.toLowerCase()) {
            el.click()
            await sleep(500)
            console.log(`[삼바-주문처리-무신사] DropdownItem[${ph}] "${part}" 선택`)
            matched = true
            break
          }
        }
        if (!matched) {
          if (candidates.length > 0) {
            candidates[0].click()
            await sleep(500)
            console.log(`[삼바-주문처리-무신사] DropdownItem[${ph}] 첫 항목 자동선택`)
          }
        }
      }
      return true
    }

    // 구 UI 폴백: select 드롭다운
    const selects = Array.from(document.querySelectorAll('select'))
    if (selects.length > 0) {
      for (const part of parts) {
        for (const sel of selects) {
          const opt = Array.from(sel.options).find(
            o => !o.disabled && o.value && (o.text.trim() === part || o.text.trim().startsWith(part + ' '))
          )
          if (opt) {
            sel.value = opt.value
            sel.dispatchEvent(new Event('change', { bubbles: true }))
            await sleep(600)
            break
          }
        }
      }
      return true
    }

    // 구 UI 폴백: 버튼/라디오
    for (const part of parts) {
      for (const btn of document.querySelectorAll('[class*="SizeButton"],[role="radio"],[class*="OptionItem"],button,li')) {
        if (btn.textContent.trim() === part) {
          btn.click()
          await sleep(500)
          break
        }
      }
    }

    return true
  }

  // ── 상품 페이지: 바로구매 클릭 ──
  async function clickBuyNow() {
    // 무신사 "바로구매" 버튼 텍스트 매칭
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '바로구매' || t === '즉시구매' || t === '바로 구매' || t === '구매하기') {
        btn.click()
        await sleep(3000) // 주문서 페이지 이동 대기
        console.log('[삼바-주문처리-무신사] 바로구매 클릭')
        return true
      }
    }
    // 폴백: class에 "buy-now" 포함
    const buyNowBtn = document.querySelector('[class*="buy-now"], [class*="BuyNow"], [class*="buyNow"]')
    if (buyNowBtn) {
      buyNowBtn.click()
      await sleep(3000)
      return true
    }
    return false
  }

  // ── 주문서 페이지: 배송지 변경 ──
  async function changeShippingAddress(name, phone, address, addressDetail) {
    if (!name || !address) return // 이름/주소 없으면 스킵

    // "배송지 변경" 버튼 클릭
    for (const btn of document.querySelectorAll('button')) {
      if (btn.textContent.trim() === '배송지 변경') {
        btn.click()
        await sleep(2000)
        break
      }
    }

    // Drawer 열림 대기
    // 새 배송지 추가 버튼 찾기
    let addNewBtn = null
    for (let i = 0; i < 10; i++) {
      for (const btn of document.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t.includes('새 배송지') || t.includes('배송지 추가') || t.includes('추가하기')) {
          addNewBtn = btn
          break
        }
      }
      if (addNewBtn) break
      await sleep(500)
    }

    if (!addNewBtn) {
      console.warn('[삼바-주문처리-무신사] 새 배송지 추가 버튼 못 찾음 — Drawer 미열림?')
      return
    }

    addNewBtn.click()
    await sleep(1500)

    // 이름, 전화번호, 주소 입력
    const inputs = document.querySelectorAll('input[type="text"], input:not([type])')
    // 이름 input (첫 번째 또는 placeholder 매칭)
    const nameInput = [...inputs].find(i => i.placeholder?.includes('이름') || i.placeholder?.includes('받는') || i.name?.includes('name'))
    if (nameInput) { nameInput.value = name; nameInput.dispatchEvent(new Event('input', { bubbles: true })); nameInput.dispatchEvent(new Event('change', { bubbles: true })) }

    const phoneInput = [...inputs].find(i => i.placeholder?.includes('연락처') || i.placeholder?.includes('전화') || i.placeholder?.includes('번호') || i.name?.includes('phone'))
    if (phoneInput) { phoneInput.value = phone; phoneInput.dispatchEvent(new Event('input', { bubbles: true })) }

    // 주소 검색 (카카오 주소 API 팝업 방식 — 자동화 어려움)
    // 대신 직접 입력 가능한 필드 시도
    const addrInput = [...inputs].find(i => i.placeholder?.includes('주소') && !i.placeholder?.includes('상세'))
    if (addrInput) { addrInput.value = address; addrInput.dispatchEvent(new Event('input', { bubbles: true })) }

    const detailInput = [...inputs].find(i => i.placeholder?.includes('상세') || i.placeholder?.includes('나머지'))
    if (detailInput) { detailInput.value = addressDetail || ''; detailInput.dispatchEvent(new Event('input', { bubbles: true })) }

    await sleep(500)

    // 저장 버튼 클릭
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '저장' || t === '확인' || t === '완료') {
        btn.click()
        await sleep(1500)
        break
      }
    }
    console.log(`[삼바-주문처리-무신사] 배송지 입력 완료: ${name} / ${phone}`)
  }

  // ── 주문서 페이지: 최적 쿠폰 자동선택 ──
  async function selectBestCoupon() {
    // 쿠폰 버튼 클릭 (모달 열기)
    let couponBtn = null
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t.includes('쿠폰') && (t.includes('선택') || t.includes('적용') || t.includes('없음'))) {
        couponBtn = btn
        break
      }
    }
    if (!couponBtn) {
      // "쿠폰 적용 중" 버튼도 클릭해서 재선택
      for (const btn of document.querySelectorAll('button')) {
        if (btn.textContent.trim().includes('쿠폰')) { couponBtn = btn; break }
      }
    }
    if (!couponBtn) { console.log('[삼바-주문처리-무신사] 쿠폰 버튼 못 찾음'); return }

    couponBtn.click()
    await sleep(1500)

    // 쿠폰 모달에서 할인율/금액 최대 쿠폰 선택
    // 쿠폰 목록: [role="radio"] 또는 [class*="CouponItem"] 형태
    const couponItems = document.querySelectorAll('[class*="CouponItem"], [role="radio"][class*="coupon"], [class*="coupon-item"]')
    if (!couponItems.length) {
      // 폴백: dialog 안 라디오 버튼들
      const dialog = document.querySelector('[role="dialog"], [class*="Modal"], [class*="Drawer"]')
      if (dialog) {
        const radios = dialog.querySelectorAll('[role="radio"], button[class*="Item"]')
        if (radios.length) {
          // 첫 번째 선택 (일반적으로 최대 할인이 먼저 나옴)
          radios[0].click()
          await sleep(500)
          console.log('[삼바-주문처리-무신사] 쿠폰 첫 번째 선택')
        }
      }
    } else {
      // 할인금액 최대 쿠폰 찾기
      let bestCoupon = null
      let bestDiscount = 0
      for (const item of couponItems) {
        const text = item.textContent
        const match = text.match(/[-−]([0-9,]+)원/)
        if (match) {
          const discount = parseInt(match[1].replace(/,/g, ''))
          if (discount > bestDiscount) { bestDiscount = discount; bestCoupon = item }
        }
      }
      if (bestCoupon) {
        bestCoupon.click()
        await sleep(500)
        console.log(`[삼바-주문처리-무신사] 최대 쿠폰 선택: -${bestDiscount.toLocaleString()}원`)
      } else if (couponItems.length) {
        couponItems[0].click()
        await sleep(500)
      }
    }

    // 장바구니 쿠폰도 선택 (있는 경우)
    const cartCouponBtns = document.querySelectorAll('[class*="CartCoupon"] button, [class*="cart-coupon"] button')
    for (const btn of cartCouponBtns) {
      const t = btn.textContent.trim()
      if (t.includes('선택') || t.includes('적용')) { btn.click(); await sleep(500); break }
    }

    // 적용 버튼 클릭
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '적용' || t === '확인' || t === '쿠폰 적용') { btn.click(); await sleep(1000); break }
    }

    console.log('[삼바-주문처리-무신사] 쿠폰 선택 완료')
  }

  // ── 주문서 페이지: 적립금 선할인 확인 (기본값 유지) ──
  async function ensurePrepaySelected() {
    // aria-checked="true" 인 선할인 라디오 확인
    for (const radio of document.querySelectorAll('[role="radio"]')) {
      const parent = radio.closest('[class*="SavePoint"], [class*="Prepay"]')
      if (parent && parent.textContent.includes('선할인') && radio.getAttribute('aria-checked') !== 'true') {
        radio.click()
        await sleep(300)
        console.log('[삼바-주문처리-무신사] 적립금 선할인 선택')
      }
    }
  }

  // ── 메인 플로우 ──
  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, quantity, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = window.location.href.includes('/order/order-form') || window.location.href.includes('/order/payment')

        if (!isOrderForm) {
          // ── 상품 페이지 ──
          console.log(`[삼바-주문처리-무신사] 상품 페이지 시작 | opt=${productOption} | type=${orderType}`)

          // 옵션 선택 (실패해도 계속 — FREE 단일사이즈 상품은 선택 UI 없음)
          if (productOption) {
            await selectSize(productOption)
          }
          await sleep(800)

          // 바로구매 클릭
          const buyOk = await clickBuyNow()
          if (!buyOk) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }

          // 주문서 이동 후 이 content script가 새 페이지에서 재주입되어야 함
          // → background가 주문서 로딩 후 다시 이 script를 주입하고 메시지 전송
          sendResponse({ success: true, nextStep: 'order-form', tabId: chrome.runtime.id })
        } else {
          // ── 주문서 페이지 ──
          console.log(`[삼바-주문처리-무신사] 주문서 페이지 시작 | type=${orderType}`)
          await sleep(1500) // 주문서 완전 로드 대기

          // 까대기: 배송지 변경 (기본배송지가 이미 사무실이면 스킵 가능)
          // 직배: 배송지 변경 (고객 주소로)
          // 무신사 까대기는 기본배송지 사용하므로 직배만 변경
          if (orderType === 'direct') {
            await changeShippingAddress(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          }

          // 쿠폰 자동선택
          await selectBestCoupon()

          // 적립금 선할인 기본값 유지 확인
          await ensurePrepaySelected()

          console.log('[삼바-주문처리-무신사] 주문서 준비 완료 — 결제 대기 중')
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) {
        sendResponse({ success: false, error: e.message })
      }
    })()
    return true
  })

  console.log('[삼바-주문처리-무신사] 로드')
})()

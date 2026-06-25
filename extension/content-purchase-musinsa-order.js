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

    const parts = val.split(/[/,]/).map(s => s.trim()).filter(Boolean)

    // 무신사 새 UI: DropdownTriggerBox 방식 (컬러 선택 후 사이즈 박스가 동적으로 생성됨)
    const hasBoxes = document.querySelector('[data-mds="DropdownTriggerBox"]')
    if (hasBoxes) {
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i]
        await sleep(400)

        // 현재 존재하는 DropdownTriggerBox 재조회 (동적 생성 대응)
        const boxes = Array.from(document.querySelectorAll('[data-mds="DropdownTriggerBox"]'))
        if (boxes.length === 0) break

        // 아직 선택 안 된 박스 우선 — innerText(span 표시) 비어있어야 미선택
        const targetBox = boxes.find(b => !b.innerText.trim() && !b.querySelector('[data-mds="DropdownTriggerInput"]')?.value?.trim()) || boxes[i] || boxes[boxes.length - 1]
        const ph = targetBox.querySelector('[data-mds="DropdownTriggerInput"]')?.getAttribute('placeholder') || ''

        // 박스 클릭으로 드롭다운 열기
        targetBox.click()

        // 드롭다운 항목 polling — sleep(500) 고정 대기 시 이미 닫혀버림(실측 0.8초 내 닫힘)
        // 100ms 간격 최대 2초 polling으로 열리자마자 잡기
        const _ITEM_SELS = [
          '[class*="DropdownItemContent__Container"]',
          '[data-mds="DropdownItem"]',
          '[role="option"]',
          '[class*="DropdownItem__Container"]',
          '[class*="dropdown__item"]',
          '[class*="DropdownList"] li',
          '[class*="SelectedOption__SelectOptionItemContainer"]',
        ]
        let allItems = []
        for (let _pi = 0; _pi < 20; _pi++) {
          await sleep(100)
          for (const sel of _ITEM_SELS) {
            const cands = [...document.querySelectorAll(sel)].filter(
              el => el.offsetHeight > 0 && !el.closest('[data-mds="DropdownTriggerBox"]')
            )
            if (cands.length > 0) { allItems = cands; break }
            const all = [...document.querySelectorAll(sel)].filter(el => el.offsetHeight > 0)
            if (all.length > 0) { allItems = all; break }
          }
          if (allItems.length > 0) break
        }
        let matched = false
        if (allItems.length > 0) {
          const target = allItems.find(c => {
            const t = c.textContent.trim()
            return t === part || t.startsWith(part) || t.toLowerCase().includes(part.toLowerCase())
          }) || allItems[0]
          // click()이 PointerEvent보다 안전 — PointerEvent(pointerdown)이 외부클릭으로 감지되어 드롭다운을 닫음
          const clickEl = target.closest('[class*="SelectedOption__SelectOptionIt"]')
            || target.closest('[class*="StaticDropdownMenuItem"]')
            || target
          clickEl.click()
          await sleep(600)
          const isExact = target.textContent.trim() === part
          console.log(`[삼바-주문처리-무신사] TriggerBox[${ph}] "${isExact ? part : target.textContent.trim()}" 선택`)
          matched = true
        }
        if (!matched) {
          console.log(`[삼바-주문처리-무신사] TriggerBox[${ph}] "${part}" 항목 못 찾음`)
        }
      }

      // 제공된 parts 수 < 전체 박스 수인 경우만 나머지 박스 자동선택
      // parts 수 >= 박스 수면 이미 모두 지정됨 → 스킵 (이중선택 방지)
      await sleep(400)
      const remainingBoxes = Array.from(document.querySelectorAll('[data-mds="DropdownTriggerBox"]'))
      if (remainingBoxes.length <= parts.length) {
        // 모든 박스 이미 parts로 지정됨 — 자동선택 불필요
      } else
      for (const box of remainingBoxes) {
        const inp = box.querySelector('[data-mds="DropdownTriggerInput"]')
        // innerText(span 표시) 우선 확인 — value는 항상 ""인 UI
        const _boxSelected = box.innerText.trim() || (inp && inp.value && inp.value.trim()) || ''
        if (!_boxSelected) {
          const ph = inp.getAttribute('placeholder') || ''
          box.click()
          // sleep(500) 고정 대기 → 닫힘 위험, polling으로 대체
          let _items = []
          for (let _ri = 0; _ri < 20; _ri++) {
            await sleep(100)
            for (const sel of ['[data-mds="StaticDropdownMenuItem"]','[class*="DropdownItemContent__Container"]','[data-mds="DropdownItem"]','[role="option"]','[class*="DropdownList"] li','[class*="SelectedOption__SelectOptionItemContainer"]']) {
              const cands = [...document.querySelectorAll(sel)].filter(el => el.offsetHeight > 0 && !el.closest('[data-mds="DropdownTriggerBox"]'))
              if (cands.length > 0) { _items = cands; break }
              const all = [...document.querySelectorAll(sel)].filter(el => el.offsetHeight > 0)
              if (all.length > 0) { _items = all; break }
            }
            if (_items.length > 0) break
          }
          const available = _items.filter(c => !c.closest('[aria-disabled="true"]') && !c.closest('[class*="disabled"]'))
          const target = available.length > 0 ? available[0] : _items[0]
          if (target) {
            const clickEl = target.closest('[class*="SelectedOption__SelectOptionIt"]')
              || target.closest('[class*="StaticDropdownMenuItem"]')
              || target
            clickEl.click()
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

  // ── 주문서 페이지: 배송지 변경 (무조건 신규 추가) ──
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

    // Drawer 열림 대기 (최대 5초)
    let addNewBtn = null
    for (let i = 0; i < 10; i++) {
      addNewBtn = [...document.querySelectorAll('button')].find(b => {
        const t = b.textContent.trim()
        return (t.includes('추가하기') || t.includes('배송지 추가') || t.includes('새 배송지')) && b.offsetHeight > 0
      })
      if (addNewBtn) break
      await sleep(500)
    }
    if (!addNewBtn) { console.warn('[삼바-주문처리-무신사] 배송지 추가 버튼 못 찾음'); return }

    addNewBtn.click()
    await sleep(1500)

    // native setter (React/Vue 우회)
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
    const setVal = (el, v) => {
      if (!el) return
      if (nativeSetter) nativeSetter.call(el, v)
      else el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
      el.dispatchEvent(new Event('change', { bubbles: true }))
    }

    // 이름 입력
    const nameEl = [...document.querySelectorAll('input[type="text"], input:not([type])')].find(
      i => i.placeholder?.includes('이름') || i.placeholder?.includes('받는') || i.name?.includes('name'),
    )
    setVal(nameEl, name)

    // 전화번호 입력
    const phoneEl = [...document.querySelectorAll('input')].find(
      i => i.placeholder?.includes('연락처') || i.placeholder?.includes('전화') || i.placeholder?.includes('번호') || i.type === 'tel',
    )
    setVal(phoneEl, (phone || '').replace(/-/g, ''))

    await sleep(300)

    // 주소 검색 버튼 클릭 → 카카오 팝업 열기
    const addrSearchBtn = [...document.querySelectorAll('button')].find(b => {
      const t = b.textContent.trim()
      return (t.includes('주소 검색') || t.includes('우편번호') || t.includes('검색')) && b.offsetHeight > 0
    })
    if (addrSearchBtn) {
      addrSearchBtn.click()
      await sleep(2000)

      // 카카오 주소 팝업 iframe 접근 시도
      const iframe = [...document.querySelectorAll('iframe')].find(
        f => f.src?.includes('postcode') || f.src?.includes('daum') || f.src?.includes('kakao'),
      )
      if (iframe) {
        try {
          const iDoc = iframe.contentDocument || iframe.contentWindow?.document
          if (iDoc) {
            const searchInput = iDoc.querySelector('input[placeholder*="검색"], input[class*="search"], input[type="text"]')
            if (searchInput) {
              searchInput.focus()
              searchInput.value = address
              searchInput.dispatchEvent(new Event('input', { bubbles: true }))
              await sleep(300)
              // 검색 실행 (Enter 또는 검색 버튼)
              searchInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }))
              searchInput.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', keyCode: 13, bubbles: true }))
              const searchBtn = iDoc.querySelector('button[type="submit"], button')
              if (searchBtn) searchBtn.click()
              await sleep(1500)
              // 첫 번째 결과 클릭
              const firstResult = iDoc.querySelector('[class*="result"] li:first-child, [class*="list"] li:first-child, table tr:first-child td')
              if (firstResult) { firstResult.click(); await sleep(1000) }
            }
          }
        } catch (e) {
          console.warn('[삼바-주문처리-무신사] 카카오 팝업 접근 실패:', e.message)
        }
      }
    }

    await sleep(500)

    // 상세주소 입력
    const detailEl = [...document.querySelectorAll('input[type="text"], input:not([type])')].find(
      i => i.placeholder?.includes('상세') || i.placeholder?.includes('나머지'),
    )
    setVal(detailEl, addressDetail || '')

    await sleep(300)

    // 저장 버튼 클릭
    const saveBtn = [...document.querySelectorAll('button')].find(b => {
      const t = b.textContent.trim()
      return (t === '저장' || t === '확인' || t === '완료') && b.offsetHeight > 0
    })
    if (saveBtn) { saveBtn.click(); await sleep(1500) }

    console.log(`[삼바-주문처리-무신사] 배송지 신규 추가 완료: ${name} / ${phone}`)
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

    // 쿠폰 모달이 아직 열려있으면 닫기 (X 버튼 또는 ESC)
    await sleep(300)
    const openDialog = document.querySelector('[role="dialog"], [class*="Modal"][class*="open"], [class*="modal-wrap"]')
    if (openDialog) {
      const closeBtn = [...openDialog.querySelectorAll('button')].find(b =>
        b.getAttribute('aria-label')?.match(/닫|close/i) ||
        (b.querySelector('svg') && b.textContent.trim() === '') ||
        b.textContent.trim() === '닫기',
      )
      if (closeBtn) { closeBtn.click(); await sleep(500) }
      else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    }

    console.log('[삼바-주문처리-무신사] 쿠폰 선택 완료')
  }

  // ── 주문서 페이지: 적립금 선할인 선택 (선할인 가능한 상품만) ──
  async function ensurePrepaySelected() {
    const discountBtn = document.querySelector('button[role="radio"][value="DISCOUNT"]')
    if (!discountBtn) return
    // radiogroup data-disabled → 선할인 제한 상품 스킵
    const group = discountBtn.closest('[role="radiogroup"]')
    if (group && group.dataset.disabled !== undefined) return
    if (discountBtn.dataset.state === 'checked') return
    discountBtn.scrollIntoView({ block: 'center' })
    await sleep(200)
    discountBtn.click()
    await sleep(500)
    console.log('[삼바-주문처리-무신사] 적립금 선할인 선택')
  }

  // ── 주문서 페이지: 무신사 머니 결제 수단 선택 ──
  async function selectMusinsaMoney() {
    const btn = document.querySelector('button[role="radio"][value="MUSINSAPAY_MONEY"]')
    if (!btn || btn.dataset.state === 'checked') return
    btn.scrollIntoView({ block: 'center' })
    await sleep(200)
    btn.click()
    await sleep(500)
    console.log('[삼바-주문처리-무신사] 무신사 머니 선택')
  }

  // ── 주문서 페이지: 실구매가 계산 ──
  // 실구매가 = 결제금액 - 무신사머니 적립 + 보유적립금 사용액
  function computeActualCost() {
    // 결제하기 버튼에서 마지막 금액 파싱 (예: "49,000원42,000원 결제하기" → 42000)
    const payBtn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('결제하기') && b.offsetHeight > 0)
    const amounts = payBtn?.textContent.match(/[\d,]+원/g) || []
    const finalAmount = amounts.length > 0 ? parseInt(amounts[amounts.length - 1].replace(/[,원]/g, '')) : 0

    // 무신사머니 적립금
    const txt = document.body.innerText
    const moneyMatch = txt.match(/무신사머니 결제[^\d]*([\d,]+)원\s*적립/)
    const musinsaMoneyReward = moneyMatch ? parseInt(moneyMatch[1].replace(/,/g, '')) : 0

    // 보유 적립금 사용액
    const pointInput = document.querySelector('input[placeholder*="보유 적립금"]')
    const pointUsed = parseInt((pointInput?.value || '0').replace(/,/g, '')) || 0

    const actualCost = finalAmount - musinsaMoneyReward + pointUsed
    return { finalAmount, musinsaMoneyReward, pointUsed, actualCost }
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

          // 직배 배송지 변경은 background(_handleMusinsaShippingPopup)에서 이미 처리됨
          // 팝업 창 기반이라 content script에서 처리 불가

          // 쿠폰 자동선택
          await selectBestCoupon()

          // 적립금 선할인 선택 (가능한 경우)
          await ensurePrepaySelected()

          // 무신사 머니 결제 수단 선택
          await selectMusinsaMoney()

          // 실구매가 계산
          const costInfo = computeActualCost()
          console.log(`[삼바-주문처리-무신사] 실구매가: ${costInfo.actualCost.toLocaleString()}원 (결제${costInfo.finalAmount.toLocaleString()} - 머니적립${costInfo.musinsaMoneyReward.toLocaleString()} + 적립금사용${costInfo.pointUsed.toLocaleString()})`)

          console.log('[삼바-주문처리-무신사] 주문서 준비 완료 — 결제 대기 중')
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) {
        sendResponse({ success: false, error: e.message })
      }
    })()
    return true
  })

  console.log('[삼바-주문처리-무신사] 로드')
})()

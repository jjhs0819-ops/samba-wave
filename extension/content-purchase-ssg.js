// content-purchase-ssg.js — SSG 가구매(셀프구매) 장바구니 담기
// SHOW PASS v2.4 content/ssg.js 이식 → 삼바 확장앱 패턴(재주입 가드 + onMessage).
// 흐름: (자동로그인은 background-autologin.js가 선처리) → 옵션 선택 → 장바구니 담기 → 레이어 닫기.
// 결제완료 감지/일시품절 원복은 M3(백엔드 상태머신 + PlayAuto API).
;(() => {
  if (window.__sambaPurchaseSsgLoaded) return
  window.__sambaPurchaseSsgLoaded = true

  // SSG 장바구니 담기 시 뜨는 alert/confirm 차단 (defineProperty로 재정의 방지)
  ;(function blockAlert() {
    const noop = () => {}
    try {
      Object.defineProperty(window, 'alert', { value: noop, writable: false, configurable: false })
      Object.defineProperty(window, 'confirm', { value: () => true, writable: false, configurable: false })
    } catch (e) {
      window.alert = noop
      window.confirm = () => true
    }
  })()

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  // ── 옵션 선택 (select 우선, li/button 폴백) ───────────────────────────────
  async function selectOption(optionValue) {
    const val = String(optionValue)
    for (const sel of document.querySelectorAll('select')) {
      const opts = Array.from(sel.options).filter((o) => !o.disabled)
      const target = opts.find(
        (o) =>
          o.text.trim() === val ||
          o.value === val ||
          o.text.trim().startsWith(val + ' ') ||
          o.text.trim().startsWith(val + '.')
      )
      if (target) {
        sel.value = target.value
        sel.dispatchEvent(new Event('focus', { bubbles: true }))
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        sel.dispatchEvent(new Event('input', { bubbles: true }))
        sel.dispatchEvent(new Event('blur', { bubbles: true }))
        await sleep(700)
        console.log(`[삼바-가구매-SSG] 옵션 "${val}" 선택(select)`)
        return true
      }
    }
    const items = document.querySelectorAll(
      '.opt_list li, .option_list li, .prd_option_list li, [data-opt-no], [data-opt-val]'
    )
    for (const item of items) {
      const text = item.textContent.trim()
      const dataVal = item.dataset.optNo || item.dataset.optVal || ''
      if (text === val || dataVal === val || text.startsWith(val + ' ')) {
        item.click()
        await sleep(700)
        console.log(`[삼바-가구매-SSG] 옵션 "${val}" 선택(li)`)
        return true
      }
    }
    return false
  }

  // ── 장바구니 버튼 클릭 ────────────────────────────────────────────────────
  async function clickAddToCart() {
    const selectors = [
      'button.btn_cart',
      'a.btn_cart',
      '.btn_wrap .btn_cart',
      '.prd_btn_wrap .btn_cart',
      'button[data-btntype="cart"]',
      '.ssg_btn_cart',
    ]
    for (const sel of selectors) {
      const btn = document.querySelector(sel)
      if (btn && !btn.disabled && !btn.classList.contains('disabled')) {
        btn.click()
        await sleep(1200)
        await closeLayerPopup()
        return true
      }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim() === '장바구니') {
        btn.click()
        await sleep(1200)
        await closeLayerPopup()
        return true
      }
    }
    return false
  }

  // ── 장바구니 완료 레이어 닫기 (다음 작업 방해 방지) ───────────────────────
  async function closeLayerPopup() {
    await sleep(400)
    const closeSelectors = [
      '.ly_cart_wrap .btn_close',
      '.layer_cart .btn_close',
      '.cart_layer .btn_close',
      '.ly_wrap .btn_close',
      '.btn_cont_shopping',
      'button.btn_close',
      '.pop_cart .btn_close',
    ]
    for (const sel of closeSelectors) {
      const btn = document.querySelector(sel)
      if (btn) {
        btn.click()
        await sleep(300)
        return
      }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      const txt = btn.textContent.trim()
      if (txt === '계속 쇼핑' || txt === '쇼핑 계속') {
        btn.click()
        await sleep(300)
        return
      }
    }
  }

  // ── 메시지 수신 — background handlePurchaseJob가 호출 ──────────────────────
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || msg.action !== 'samba_purchase_addToCart') return
    ;(async () => {
      try {
        const option = msg.option || ''
        if (option) {
          const ok = await selectOption(option)
          if (!ok) {
            sendResponse({ success: false, error: `옵션 "${option}" 선택 실패` })
            return
          }
          await sleep(500)
        }
        const added = await clickAddToCart()
        if (added) {
          console.log('[삼바-가구매-SSG] 장바구니 담기 완료 ✓')
          sendResponse({ success: true })
        } else {
          sendResponse({ success: false, error: '장바구니 버튼 못 찾음' })
        }
      } catch (e) {
        sendResponse({ success: false, error: e.message })
      }
    })()
    return true
  })

  console.log('[삼바-가구매-SSG] 로드')
})()

// content-purchase-gs.js — GS샵 가구매(셀프구매) 장바구니 담기
// SHOW PASS gsshop.js 이식. ⚠️ SHOW PASS 원본도 "GS샵 실제 셀렉터 확인 필요(TODO)"
// 상태라 셀렉터가 추정값 — 실제 GS샵 상품페이지에서 라이브 보정 필요(옵션 select /
// 장바구니 버튼 클래스). 삼바 확장앱 패턴(재주입 가드 + onMessage)으로 변환.
;(() => {
  if (window.__sambaPurchaseGsLoaded) return
  window.__sambaPurchaseGsLoaded = true

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  async function selectOption(optionValue) {
    const val = String(optionValue)
    for (const sel of document.querySelectorAll('select')) {
      const target = Array.from(sel.options).find((o) => o.text.trim() === val || o.value === val)
      if (target && !target.disabled) {
        sel.value = target.value
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await sleep(600)
        console.log(`[삼바-가구매-GS] 옵션 "${val}" 선택`)
        return true
      }
    }
    return false
  }

  async function clickAddToCart() {
    // ⚠️ [라이브 보정] GS샵 장바구니 버튼 셀렉터 — 실제 페이지에서 확인 후 보정
    const selectors = ['.btn_basket', 'button[class*="basket"]', 'button[class*="cart"]', 'a[class*="cart"]']
    for (const sel of selectors) {
      const btn = document.querySelector(sel)
      if (btn && !btn.disabled) {
        btn.click()
        await sleep(900)
        const closeBtn = document.querySelector('.btn_close, [class*="close"]')
        if (closeBtn) { try { closeBtn.click() } catch {} }
        return true
      }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim() === '장바구니') { btn.click(); await sleep(900); return true }
    }
    return false
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_purchase_addToCart') return
    ;(async () => {
      try {
        const option = msg.option || ''
        if (option) {
          const ok = await selectOption(option)
          if (!ok) { sendResponse({ success: false, error: `옵션 "${option}" 선택 실패 (GS 셀렉터 라이브 보정 필요)` }); return }
          await sleep(500)
        }
        const added = await clickAddToCart()
        if (added) { console.log('[삼바-가구매-GS] 장바구니 담기 완료 ✓'); sendResponse({ success: true }) }
        else sendResponse({ success: false, error: '장바구니 버튼 못 찾음 (GS 셀렉터 라이브 보정 필요)' })
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })

  console.log('[삼바-가구매-GS] 로드 (셀렉터 라이브 보정 대기)')
})()

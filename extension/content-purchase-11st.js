// content-purchase-11st.js — 11번가 가구매(셀프구매) 장바구니 담기 (골격)
// ⚠️⚠️ SHOW PASS에 11번가 소스가 없음 — 셀렉터 전부 추정값(best-effort). 실제 11번가
// 상품페이지에서 라이브 보정 필수 (옵션 선택 방식·장바구니 버튼). 삼바 확장앱 패턴.
;(() => {
  if (window.__sambaPurchase11stLoaded) return
  window.__sambaPurchase11stLoaded = true

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

  async function selectOption(optionValue) {
    const val = String(optionValue)
    // select 방식
    for (const sel of document.querySelectorAll('select')) {
      const target = Array.from(sel.options).find(
        (o) => o.text.trim() === val || o.value === val || o.text.trim().startsWith(val + ' ')
      )
      if (target && !target.disabled) {
        sel.value = target.value
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await sleep(600)
        return true
      }
    }
    // li/버튼 폴백 (11번가 옵션이 커스텀 드롭다운일 수 있음 — 라이브 보정)
    for (const item of document.querySelectorAll('.c_product_option li, [class*="option"] li, [data-optitem], [class*="selectbox"] li')) {
      const text = item.textContent.trim()
      if (text === val || text.startsWith(val + ' ')) { item.click(); await sleep(600); return true }
    }
    return false
  }

  async function clickAddToCart() {
    // ⚠️ [라이브 보정] 11번가 장바구니 버튼 셀렉터 — 추정값. 실제 페이지에서 확인.
    const selectors = ['.btn_cart', 'a[class*="cart"]', 'button[class*="cart"]', 'a[class*="basket"]', 'button[class*="basket"]']
    for (const sel of selectors) {
      const btn = document.querySelector(sel)
      if (btn && !btn.disabled) { btn.click(); await sleep(1000); return true }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '장바구니' || t === '장바구니 담기') { btn.click(); await sleep(1000); return true }
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
          if (!ok) { sendResponse({ success: false, error: `옵션 "${option}" 선택 실패 (11번가 셀렉터 라이브 보정 필요)` }); return }
          await sleep(500)
        }
        const added = await clickAddToCart()
        if (added) { console.log('[삼바-가구매-11번가] 장바구니 담기 완료 ✓'); sendResponse({ success: true }) }
        else sendResponse({ success: false, error: '장바구니 버튼 못 찾음 (11번가 셀렉터 라이브 보정 필요)' })
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })

  console.log('[삼바-가구매-11번가] 로드 (셀렉터 라이브 보정 대기)')
})()

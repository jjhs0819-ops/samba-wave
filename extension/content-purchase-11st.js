// content-purchase-11st.js — 11번가 가구매(셀프구매) 장바구니 담기 (골격)
// ⚠️⚠️ SHOW PASS에 11번가 소스가 없음 — 셀렉터 전부 추정값(best-effort). 실제 11번가
// 상품페이지에서 라이브 보정 필수 (옵션 선택 방식·장바구니 버튼). 삼바 확장앱 패턴.
;(() => {
  if (window.__sambaPurchase11stLoaded) return
  window.__sambaPurchase11stLoaded = true

  // 11번가 alert/confirm 차단 (옵션/장바구니 경고가 흐름 막는 것 방지)
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

  async function selectOption(optionValue) {
    const val = String(optionValue)
    // 11번가 옵션 = 아코디언/커스텀 드롭다운 (라이브 확인 2026-06-19).
    // 옵션 행(li)에서 첫 숫자가 val 과 일치하는 행의 "선택하기"(.c_product_btn_select) 클릭.
    const rowSel =
      '.accordion_body.dropdown_list li, .bot_option_section .dropdown_list li, .c_product_dropdown_wrap .dropdown_list li'
    // 매칭되는 "선택하기" 버튼 찾기 — 버튼 있는 행만(실제 옵션). 카테고리 메뉴 행은 버튼 없어 배제.
    // ⚠️ 11번가 전역 카테고리 메뉴 행("키즈의류(3-8세)" 등)이 숫자와 오매칭되어 그 <a>를
    //    클릭→페이지 이동→content script 사망하던 버그 차단.
    const findBtn = () => {
      for (const li of document.querySelectorAll(rowSel)) {
        const b = li.querySelector('.c_product_btn_select')
        if (!b) continue
        const m = (li.textContent || '').match(/\d+/)
        if (m && m[0] === val) return b
      }
      return null
    }
    // ① 드롭다운 안 열고 먼저 시도 — 옵션 행은 숨김 상태로도 DOM에 있어 클릭됨.
    //    (opener 클릭이 엉뚱하게 카테고리 메뉴를 펼치던 부작용 회피 → 카테고리 팝업 안 뜸)
    let btn = findBtn()
    // ② 못 찾을 때만 드롭다운 열고 재시도
    if (!btn) {
      const opener = document.querySelector(
        '.bot_option_section .accordion_head, .bot_option_section .dropdown_selected, .c_product_dropdown_wrap .dropdown_selected',
      )
      if (opener && !opener.closest('.active')) { opener.click(); await sleep(800) }
      btn = findBtn()
    }
    if (btn) {
      btn.click()
      await sleep(700)
      console.log(`[삼바-가구매-11번가] 옵션 "${val}" 선택`)
      return true
    }
    // 폴백: 네이티브 select
    for (const sel of document.querySelectorAll('select')) {
      const t = Array.from(sel.options).find((o) => o.text.trim() === val || o.value === val)
      if (t && !t.disabled) {
        sel.value = t.value
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        await sleep(600)
        return true
      }
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
        // M2: options 배열(범위/다건) 우선, 없으면 단일 option 폴백
        const options = Array.isArray(msg.options) && msg.options.length ? msg.options.map(String) : (msg.option ? [String(msg.option)] : [])
        const selected = []
        const failed = []
        for (const opt of options) {
          const ok = await selectOption(opt)
          if (ok) selected.push(opt); else failed.push(opt)
          await sleep(450)
        }
        if (options.length && !selected.length) { sendResponse({ success: false, error: `옵션 전부 선택 실패: ${failed.join(',')} (11번가 셀렉터 라이브 보정 필요)` }); return }
        const added = await clickAddToCart()
        if (added) { console.log(`[삼바-가구매-11번가] 장바구니 담기 완료 ✓ (${selected.length || 1}건)`); sendResponse({ success: true, count: selected.length || 1, failed }) }
        else sendResponse({ success: false, error: '장바구니 버튼 못 찾음 (11번가 셀렉터 라이브 보정 필요)' })
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })

  console.log('[삼바-가구매-11번가] 로드 (셀렉터 라이브 보정 대기)')
})()

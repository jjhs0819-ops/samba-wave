// content-purchase-gs.js — GS샵 가구매(셀프구매) 장바구니 담기
// SHOW PASS gsshop.js 이식. ⚠️ SHOW PASS 원본도 "GS샵 실제 셀렉터 확인 필요(TODO)"
// 상태라 셀렉터가 추정값 — 실제 GS샵 상품페이지에서 라이브 보정 필요(옵션 select /
// 장바구니 버튼 클래스). 삼바 확장앱 패턴(재주입 가드 + onMessage)으로 변환.
;(() => {
  if (window.__sambaPurchaseGsLoaded) return
  window.__sambaPurchaseGsLoaded = true

  // GS샵 alert/confirm 차단 (옵션 미선택 경고 등이 흐름 막는 것 방지)
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
    // GS샵 옵션 = select2 스타일 커스텀 드롭다운 (라이브 확인 2026-06-19).
    // 닫힘 상태 .optionTxt("옵션을 선택하세요") 클릭 → 열림. 아이템 = a.prditmidSel0 ("1/free/free/free").
    const opener = document.querySelector('.optionTxt, .prd_option_area .optionTxt, .prditmidSel, .option_tit')
    if (opener) { opener.click(); await sleep(900) }
    // "val/" 접두 매칭 (1→"1/free…"; 10이 1로 오인 안 되게 "/" 구분자)
    const items = document.querySelectorAll('a.prditmidSel0, .prditmidSel a, .tmp-select2 a')
    for (const it of items) {
      const t = it.textContent.trim()
      if (t === val || t.startsWith(val + '/') || t.startsWith(val + ' ')) {
        it.click()
        await sleep(800)
        console.log(`[삼바-가구매-GS] 옵션 "${val}" 선택 (${t.slice(0, 18)})`)
        return true
      }
    }
    // 폴백: 드롭다운 li / 일반 li 안 a
    for (const it of document.querySelectorAll('.prditmidSel li, li a')) {
      if (it.textContent.trim().startsWith(val + '/')) { it.click(); await sleep(800); return true }
    }
    return false
  }

  async function clickAddToCart() {
    // GS샵 장바구니 버튼 = #addCartButton (라이브 확인 2026-06-19). 담은 뒤 레이어 "계속 쇼핑하기" 닫기.
    const selectors = ['#addCartButton', '#addCartButtonFR', '.btn_basket', 'button[class*="basket"]', 'button[class*="cart"]']
    for (const sel of selectors) {
      const btn = document.querySelector(sel)
      if (btn && !btn.disabled && !btn.classList.contains('disabled')) {
        btn.click()
        await sleep(1100)
        // 담기 완료 레이어: "계속 쇼핑하기"(#addCartLayerCntnuButtn) — 장바구니로 이동 방지하며 닫기
        const cont = document.querySelector('#addCartLayerCntnuButtn')
        if (cont) { try { cont.click() } catch {} ; await sleep(300) }
        else { const cb = document.querySelector('.btn_close, [class*="close"]'); if (cb) { try { cb.click() } catch {} } }
        return true
      }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim() === '장바구니') {
        btn.click()
        await sleep(1100)
        const cont = document.querySelector('#addCartLayerCntnuButtn')
        if (cont) { try { cont.click() } catch {} }
        return true
      }
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
        if (options.length && !selected.length) { sendResponse({ success: false, error: `옵션 전부 선택 실패: ${failed.join(',')} (GS 셀렉터 라이브 보정 필요)` }); return }
        const added = await clickAddToCart()
        if (added) { console.log(`[삼바-가구매-GS] 장바구니 담기 완료 ✓ (${selected.length || 1}건)`); sendResponse({ success: true, count: selected.length || 1, failed }) }
        else sendResponse({ success: false, error: '장바구니 버튼 못 찾음 (GS 셀렉터 라이브 보정 필요)' })
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })

  console.log('[삼바-가구매-GS] 로드 (셀렉터 라이브 보정 대기)')
})()

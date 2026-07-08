// content-purchase-abcmart-order.js — ABCmart / GrandStage 직배/까대기 주문처리
// 확인된 셀렉터 (GrandStage 기준):
//   바로구매: button.btn.btn-lg (텍스트 '바로구매')
//   옵션: select#selectboxoptionlist (색상), select#search-optn-name (사이즈, display:none jQuery UI)
// 선물하기 없음 (ABCmart 정책상 미지원)
;(() => {
  if (window.__sambaABCOrderLoaded) return
  window.__sambaABCOrderLoaded = true
  console.log('[삼바-ABC] 로드')
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  function triggerJQSelect(sel, val) {
    const target = Array.from(sel.options).find(o => !o.disabled && (o.text.trim() === val || o.text.trim().startsWith(val + ' ') || o.value === val))
    if (!target) return false
    sel.value = target.value
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    sel.dispatchEvent(new Event('input', { bubbles: true }))
    if (window.jQuery || window.$) {
      try { (window.jQuery || window.$)(sel).trigger('change') } catch {}
    }
    return true
  }

  // 사이즈/옵션 버튼 품절 판정 (텍스트 '품절'/'sold' 또는 disabled/soldout 클래스·속성)
  const _abcSoldOut = (el) =>
    el.disabled || el.getAttribute('disabled') != null || el.getAttribute('aria-disabled') === 'true' ||
    /품절|sold ?out|일시품절/i.test(el.textContent) ||
    /soldout|sold-out|disabled|dimm|out-of-stock/i.test(el.className || '')

  async function selectSize(val) {
    val = String(val).trim()
    if (!val) return true
    // "옵션:값" 접두 제거 (삼바가 그룹명 붙여 보내는 경우 대비)
    const parts = val.split('/').map(s => {
      const p = s.trim()
      const ci = p.indexOf(':')
      return ci >= 0 ? p.slice(ci + 1).trim() : p
    }).filter(Boolean)
    console.log(`[삼바-ABC] selectSize 파트=${JSON.stringify(parts)}`)

    for (const part of parts) {
      // [핵심] 신규 UI 실제 사이즈 버튼: button.btn-prod-size (텍스트=사이즈). 품절 제외, 정확매칭.
      const sizeBtns = [...document.querySelectorAll('button.btn-prod-size, [class*="prod-size"], [class*="btn-size"]')]
        .filter(b => b.offsetHeight > 0)
      let target =
        sizeBtns.find(b => !_abcSoldOut(b) && b.textContent.trim() === part) ||
        sizeBtns.find(b => !_abcSoldOut(b) && b.textContent.trim().startsWith(part))
      // 폴백: 사이즈 텍스트를 가진 li/button (자식 거의 없는 클릭요소)
      if (!target) {
        target = [...document.querySelectorAll('button, li, a, [role="option"]')]
          .find(b => b.offsetHeight > 0 && !_abcSoldOut(b) && b.textContent.trim() === part && b.querySelectorAll('*').length <= 2)
      }
      if (target) {
        target.click()
        await sleep(1000)
        console.log(`[삼바-ABC] 사이즈 "${part}" 버튼 클릭: ${target.tagName}.${(target.className || '').toString().slice(0, 20)}`)
        continue
      }
      // 최후 폴백: 숨은 native select (구형 UI 대비)
      const sel = document.querySelector('select#search-optn-name, select#selectboxoptionlist')
      if (sel && triggerJQSelect(sel, part)) {
        console.log(`[삼바-ABC] 사이즈 "${part}" → native select 폴백 선택`)
        await sleep(900)
      } else {
        console.log(`[삼바-ABC] 사이즈 "${part}" 못 찾음`)
      }
    }
    return true
  }

  async function clickBuyNow() {
    for (const btn of document.querySelectorAll('button.btn-lg, button.btn')) {
      if (btn.textContent.trim() === '바로구매') { btn.click(); await sleep(3000); return true }
    }
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '바로구매' || t === '구매하기' || t === '주문하기') { btn.click(); await sleep(3000); return true }
    }
    return false
  }

  // native setter (React/Vue readonly input 우회)
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  const setVal = (el, v) => {
    if (!el) return
    if (nativeSetter) nativeSetter.call(el, v)
    else el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // ── 주문서: 배송지 변경 (직배/까대기) ──
  async function changeShipping(name, phone, address, detail) {
    if (!name || !address) return
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '배송지 변경' || t === '새 배송지' || t === '배송지 추가' || t === '다른 배송지') { btn.click(); await sleep(1500); break }
    }
    const modal = document.querySelector('[role="dialog"], .modal-body, .address-form-wrap, .delivery-address-wrap')
    const inputs = [...(modal || document).querySelectorAll('input[type="text"],input:not([type])')]
    const fill = (ph, v) => {
      const el = inputs.find(i => (i.placeholder || '').includes(ph))
      if (el) setVal(el, v)
    }
    fill('이름', name); fill('수령', name); fill('연락', phone); fill('전화', phone)
    fill('주소', address); fill('상세', detail || '')
    await sleep(500)
    for (const btn of (modal || document).querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '저장' || t === '확인' || t === '완료') { btn.click(); await sleep(1500); break }
    }
  }

  // ── 실구매가 계산 ──
  function computeActualCost() {
    const getText = (sel) => {
      const el = document.querySelector(sel)
      return el ? parseInt((el.textContent || '').replace(/[^\d]/g, '')) || 0 : 0
    }
    const finalAmount = getText('.total-price strong, .order-total strong, .pay-price strong, [class*="totalPay"] strong') ||
      getText('.total-price, .order-total, .pay-price') || 0
    return { finalAmount, actualCost: finalAmount }
  }

  // ── 쿠폰 조회/적용 ──
  async function selectCoupon() {
    // [수정] 헤더 네비 "이벤트·쿠폰" 링크 오클릭 방지 — 헤더/네비 안 요소 제외 + "이벤트" 제외.
    // 주문서 안 "쿠폰 조회/적용" 류 버튼만 연다.
    const opener = [...document.querySelectorAll('button, a')].find(el => {
      if (el.offsetHeight === 0) return false
      if (el.closest('header, nav, .header, .gnb, [class*="gnb"], [class*="nav"], [class*="menu"]')) return false
      const t = el.textContent.trim()
      if (t.includes('이벤트') || t.length > 16) return false
      return t.includes('쿠폰') && (t.includes('조회') || t.includes('적용') || t.includes('사용') || t.includes('다운'))
    })
    console.log(`[삼바-ABC] 쿠폰 버튼: ${opener ? `"${opener.textContent.trim().slice(0, 16)}"` : '없음(스킵)'}`)
    if (!opener) return
    opener.click()
    await sleep(1800)

    // 쿠폰 모달 (최상위 visible)
    const dlg = [...document.querySelectorAll('[role="dialog"], .layer-coupon, .coupon-area, .coupon_layer, .modal, [class*="modal"], [class*="layer"]')]
      .filter(d => d.offsetHeight > 0 && /쿠폰/.test(d.textContent)).pop()
    if (!dlg) { console.log('[삼바-ABC] 쿠폰 모달 못 찾음'); return }

    // [핵심 수정] 이 드롭다운은 jQuery UI selectmenu 위젯. native select 변경은 500 발생 →
    // 수동과 동일하게 selectmenu 버튼을 클릭해 열고, 열린 ul.ui-selectmenu-menu의
    // li.ui-menu-item 중 "%"가 든 진짜 쿠폰만 클릭한다. (동시적용 충돌 → 1개만)
    const _pct = (t) => parseInt((t.match(/(\d+)\s*%/) || [])[1] || '0', 10)
    // 쿠폰 모달 안 selectmenu 버튼("적용안함" 표시)
    const trigBtns = [...dlg.querySelectorAll('.ui-selectmenu-button, span[class*="selectmenu-button"], [class*="ui-selectmenu"]')]
      .filter(el => el.offsetHeight > 0 && /적용\s*안함/.test(el.textContent))
    console.log(`[삼바-ABC-진단] selectmenu 버튼 ${trigBtns.length}개`)

    // 열린 jQuery UI 메뉴의 진짜 쿠폰 옵션 수집 헬퍼
    const _menuOpts = () => [...document.querySelectorAll('.ui-selectmenu-menu li.ui-menu-item, ul.ui-menu li.ui-menu-item, [id$="-menu"] li')]
      .filter(el => el.offsetHeight > 0 && /\d+\s*%/.test(el.textContent) && !/적용\s*안함|이벤트/.test(el.textContent))
    const _clickOpt = async (el) => {
      const t = el.querySelector('.ui-menu-item-wrapper, a') || el
      for (const type of ['mouseover', 'mouseenter', 'mousedown', 'mouseup', 'click']) {
        t.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }))
      }
      await sleep(1000)
    }

    // [1단계] 각 드롭다운(일반/플러스)을 열어 최고 할인 옵션을 스캔 (선택은 안 함)
    const scan = []  // { btn, pct, label }
    for (const btn of trigBtns) {
      btn.click()
      await sleep(700)
      const opts = _menuOpts()
      if (opts.length) {
        opts.sort((a, b) => _pct(b.textContent) - _pct(a.textContent))
        scan.push({ btn, pct: _pct(opts[0].textContent), label: opts[0].textContent.trim() })
      }
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }))
      await sleep(400)
    }
    console.log(`[삼바-ABC-진단] 쿠폰 스캔: ` + (scan.map(s => `${s.pct}% "${s.label.slice(0, 16)}"`).join(' | ') || '없음'))

    // [2단계] 전체 드롭다운 중 할인율 가장 큰 쿠폰 1개만 적용 (동시적용 500 방지)
    let applied = false
    if (scan.length) {
      scan.sort((a, b) => b.pct - a.pct)
      const best = scan[0]
      best.btn.click()               // 최고할인 쿠폰이 든 드롭다운 다시 열기
      await sleep(800)
      const opts = _menuOpts()
      opts.sort((a, b) => _pct(b.textContent) - _pct(a.textContent))
      const pick = opts[0]
      if (pick) {
        await _clickOpt(pick)
        // 선택 등록 확인 (버튼 표시가 "적용안함" → 쿠폰명이면 성공)
        console.log(`[삼바-ABC] 쿠폰 최대할인 ${best.pct}% 적용: "${pick.textContent.trim().slice(0, 24)}" | 선택후 버튼="${best.btn.textContent.trim().slice(0, 22)}"`)
        applied = true
      }
    }
    if (!applied) console.log('[삼바-ABC] 적용 가능한 쿠폰 옵션 못 찾음')

    await sleep(400)
    const applyBtn = [...dlg.querySelectorAll('button')].find(b => b.offsetHeight > 0 && /^적용하기$|^적용$|^확인$/.test(b.textContent.trim()))
    if (applyBtn) { applyBtn.click(); await sleep(1800); console.log('[삼바-ABC] 쿠폰 적용하기 클릭') }
    else console.log('[삼바-ABC] 쿠폰 적용 버튼 못 찾음')

    // 적용 후에도 모달이 남아있으면(실패/충돌) 닫아서 결제 직전에서 안 멈추게
    const stillOpen = [...document.querySelectorAll('[role="dialog"], [class*="modal"], [class*="layer"]')]
      .find(d => d.offsetHeight > 0 && /쿠폰 조회|쿠폰적용|쿠폰 적용/.test(d.textContent))
    if (stillOpen) {
      const closeBtn = [...stillOpen.querySelectorAll('button, a, [class*="close"]')].find(b => b.offsetHeight > 0 && /^(×|✕|X|닫기)$/.test(b.textContent.trim()) || (b.className || '').toString().includes('close'))
      if (closeBtn) { closeBtn.click(); await sleep(500); console.log('[삼바-ABC] 쿠폰 모달 닫음(적용 실패 대비)') }
    }
  }

  // ── 주문동의 (결제 직전 필수 체크) ──
  // "[필수] 주문 내역에 대한 동의" 체크박스 — 매 주문마다 체크해야 결제 가능
  async function agreeOrder() {
    await sleep(500)
    // "필수 ... 동의" 텍스트 근처 체크박스 (커스텀이라 input이 숨겨질 수 있음 → offsetHeight 무시)
    let chk = null
    for (let _t = 0; _t < 6; _t++) {
      chk = [...document.querySelectorAll('input[type="checkbox"]')].find(c => {
        const box = c.closest('label, li, div, dt, dd')
        const t = (box?.textContent || '')
        return t.includes('필수') && t.includes('동의') && (t.includes('주문') || t.includes('내역'))
      })
      if (chk) break
      await sleep(300)
    }
    if (chk && !chk.checked) {
      const lbl = chk.id ? document.querySelector(`label[for="${chk.id}"]`) : null
      const target = lbl || chk.closest('label') || chk
      target.click()
      await sleep(300)
      if (!chk.checked) { chk.click(); await sleep(200) }
    }
    console.log(`[삼바-ABC] 주문동의 체크: ${!!chk} (checked=${chk?.checked})`)
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /a-rt\.com\/(order|payment|checkout)/.test(window.location.href)
        console.log(`[삼바-ABC] 시작 opt=${productOption} | type=${orderType} | 주문서=${isOrderForm} | url=${window.location.href}`)
        if (!isOrderForm) {
          if (productOption) await selectSize(productOption)
          await sleep(800)
          const ok = await clickBuyNow()
          console.log(`[삼바-ABC] 바로구매 버튼 클릭: ${ok}`)
          if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          await sleep(1500)
          console.log(`[삼바-ABC] 주문서 진입 — 배송지 처리 시작`)
          if (orderType === 'direct' || orderType === 'kkadaegi') {
            await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          }
          await selectCoupon()
          await agreeOrder()
          const costInfo = computeActualCost()
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

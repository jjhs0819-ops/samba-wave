// content-purchase-fashionplus-order.js — 패션플러스 직배/까대기 주문처리
// 확인된 셀렉터 (common-script.js + app_page-productDetail.js 소스 분석 기준):
//   옵션 드롭다운 열기: button.btn_dropdown (in .mm_dropdown.option_list)
//   옵션 항목: .m__option-list li:not(.__option-soldout) button.btn_option
//   구매 버튼: button[data-button="buy"]
//   주문서 URL: /order/write 또는 /order/sheet
;(() => {
  if (window.__sambaFPOrderLoaded) return
  window.__sambaFPOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  // ── 옵션 선택 ──
  // FashionPlus는 단일 드롭다운 (컬러+사이즈 통합: "BLK L", "WHT M" 등)
  async function selectOption(val) {
    val = String(val || '').trim()
    if (!val) return true

    // 드롭다운 열기
    const trigger = document.querySelector('.mm_dropdown.option_list button.btn_dropdown')
    if (!trigger) {
      console.log('[삼바-주문처리-패션플러스] 드롭다운 버튼 없음')
      return false
    }
    trigger.click()
    await sleep(800)

    // 옵션 항목 찾기 — 텍스트 매칭
    const items = Array.from(document.querySelectorAll('.m__option-list li:not(.__option-soldout) button.btn_option'))
    if (!items.length) {
      console.log('[삼바-주문처리-패션플러스] 옵션 항목 없음')
      return false
    }

    // 정확 일치 → 포함 일치 순서로 찾기
    const parts = val.split('/').map(s => s.trim())
    let target = null

    // 전체 값으로 정확 일치
    target = items.find(el => el.querySelector('b')?.textContent.trim() === val)

    // 부분 매칭 (parts 중 하나라도 포함)
    if (!target) {
      target = items.find(el => {
        const text = el.querySelector('b')?.textContent.trim() || ''
        return parts.some(p => text.includes(p))
      })
    }

    // 매칭 실패 시 첫 번째 가용 항목 선택
    if (!target) {
      target = items[0]
      console.log(`[삼바-주문처리-패션플러스] 옵션 "${val}" 매칭 실패 → 첫번째 선택`)
    }

    target.click()
    await sleep(600)
    console.log(`[삼바-주문처리-패션플러스] 옵션 선택: ${target.querySelector('b')?.textContent.trim()}`)
    return true
  }

  // ── 바로구매 버튼 클릭 ──
  async function clickBuyNow() {
    const btn = document.querySelector('button[data-button="buy"]')
    if (!btn) {
      console.log('[삼바-주문처리-패션플러스] 바로구매 버튼 없음')
      return false
    }
    btn.click()
    await sleep(3000)
    return true
  }

  // ── 주문서: 배송지 변경 ──
  async function changeShipping(name, phone, address, detail) {
    if (!name || !address) return

    // 배송지 변경 버튼 클릭
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t === '배송지 변경' || t === '새 배송지' || t === '배송지 추가' || t === '다른 배송지 선택') {
        btn.click()
        await sleep(1500)
        break
      }
    }

    // 입력 필드 채우기
    const inputs = [...document.querySelectorAll('input[type="text"], input:not([type])')]
    const fill = (ph, v) => {
      const el = inputs.find(i => (i.placeholder || '').includes(ph) || (i.name || '').includes(ph))
      if (el) {
        el.value = v
        el.dispatchEvent(new Event('input', { bubbles: true }))
        el.dispatchEvent(new Event('change', { bubbles: true }))
      }
    }
    fill('이름', name)
    fill('수령', name)
    fill('연락', phone)
    fill('전화', phone)
    await sleep(300)

    // 저장/확인 버튼
    for (const btn of document.querySelectorAll('button')) {
      const t = btn.textContent.trim()
      if (t === '저장' || t === '확인' || t === '완료') {
        btn.click()
        await sleep(1500)
        break
      }
    }
  }

  // ── 주문서: 쿠폰 선택 ──
  async function selectCoupon() {
    // 쿠폰 영역 버튼 클릭
    for (const btn of document.querySelectorAll('button, a')) {
      const t = btn.textContent.trim()
      if (t.includes('쿠폰') && (t.includes('선택') || t.includes('적용') || t.includes('조회'))) {
        btn.click()
        await sleep(1500)
        break
      }
    }

    // 다이얼로그/모달에서 첫 번째 쿠폰 선택
    const dlg = document.querySelector('[role="dialog"], .layer-coupon, .coupon-area, .coupon_layer, .mm_modal')
    if (dlg) {
      const radios = dlg.querySelectorAll('[role="radio"], input[type="radio"], li')
      if (radios.length) {
        radios[0].click()
        await sleep(500)
      }
      for (const btn of dlg.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t === '적용' || t === '확인' || t === '사용') {
          btn.click()
          await sleep(1000)
          break
        }
      }
    }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /fashionplus\.co\.kr\/order\/(write|sheet)/.test(window.location.href)

        if (!isOrderForm) {
          // 1단계: 상품 페이지 — 옵션 선택 + 바로구매
          if (productOption) await selectOption(productOption)
          await sleep(600)
          const ok = await clickBuyNow()
          if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          // 2단계: 주문서 — 배송지 + 쿠폰
          await sleep(1500)
          if (orderType === 'direct') {
            await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          }
          await selectCoupon()
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) {
        sendResponse({ success: false, error: e.message })
      }
    })()
    return true
  })
})()

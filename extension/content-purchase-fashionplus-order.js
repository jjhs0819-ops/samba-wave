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
  // 실측 확인 구조:
  //   배송지 변경 링크 클릭 → iframe(delivery-address) 모달 팝업
  //   새 주소 입력 탭: a.btn_tab 텍스트 "새 주소 입력"
  //   우편번호 = a.mm_btn.__btn_darker__ "우편번호 찾기" 클릭 → daum.Postcode.oncomplete 콜백으로만 처리
  //   input.textfield 순서: [0]=이름 [1]=전화 [2]=우편번호(readonly) [3]=도로명(readonly) [4]=상세
  //   제출: button.__btn_primary__ (등록하기)
  async function changeShipping(name, phone, zipcode, address, detail) {
    if (!name || !address) return

    const changeLink = document.querySelector('a.btn-address') ||
      Array.from(document.querySelectorAll('a, button')).find(el => el.textContent.trim() === '배송지 변경')
    if (!changeLink) { console.log('[삼바-주문처리-패션플러스] 배송지 변경 링크 없음'); return }
    changeLink.click()
    await sleep(2500)

    // iframe 탐색
    const iframe = document.querySelector('iframe')
    if (!iframe) { console.log('[삼바-주문처리-패션플러스] 배송지 iframe 없음'); return }
    const iframeWin = iframe.contentWindow
    const doc = iframe.contentDocument || iframeWin.document

    // "새 주소 입력" 탭 — 이미 활성화돼 있으면 스킵
    const newAddrTab = Array.from(doc.querySelectorAll('a.btn_tab'))
      .find(a => a.textContent.trim() === '새 주소 입력')
    if (newAddrTab && !newAddrTab.className.includes('__tab-on')) {
      newAddrTab.click()
      await sleep(800)
    }

    // daum.Postcode mock — script 태그 injection (iframe main world에서 실행)
    // isolated world에서 iframeWin 속성 조건 체크 제거 — script 내부에서 처리
    if (zipcode && address) {
      const safeZip = JSON.stringify(zipcode)
      const safeAddr = JSON.stringify(address)
      const mockScript = doc.createElement('script')
      mockScript.textContent = 'if(window.daum&&window.daum.Postcode){var _op=window.daum.Postcode;window.daum.Postcode=function(opts){return{open:function(){if(opts.oncomplete)opts.oncomplete({zonecode:' + safeZip + ',roadAddress:' + safeAddr + '});window.daum.Postcode=_op;}}};}'
      doc.head.appendChild(mockScript)
      mockScript.remove()
      const zipBtn = Array.from(doc.querySelectorAll('a'))
        .find(a => a.textContent.trim() === '우편번호 찾기')
      if (zipBtn) { zipBtn.click(); await sleep(500) }
    }

    // 이름 / 전화 / 상세주소 입력
    const textfields = doc.querySelectorAll('input.textfield')
    // [0]=이름, [1]=전화, [2]=우편번호(readonly), [3]=도로명(readonly), [4]=상세주소
    const iframeInputProto = iframeWin.HTMLInputElement.prototype
    const nativeSetter = Object.getOwnPropertyDescriptor(iframeInputProto, 'value')

    function setVal(input, value) {
      if (!input) return
      if (nativeSetter && nativeSetter.set) nativeSetter.set.call(input, value)
      else input.value = value
      input.dispatchEvent(new iframeWin.Event('input', { bubbles: true }))
      input.dispatchEvent(new iframeWin.Event('change', { bubbles: true }))
    }

    if (textfields[0]) setVal(textfields[0], name)
    await sleep(200)
    if (textfields[1]) setVal(textfields[1], phone.replace(/[^0-9]/g, ''))
    await sleep(200)
    if (detail && textfields[4]) setVal(textfields[4], detail)
    await sleep(300)

    // 등록하기 버튼 클릭 (버튼은 tabItem 외부 footer에 위치하므로 doc 전체에서 탐색)
    const registerBtn = doc.querySelector('button.__btn_primary__')
    if (registerBtn) {
      registerBtn.click()
      // 배송지 등록 완료 팝업 확인 버튼 폴링 — 최대 15초
      for (let i = 0; i < 75; i++) {
        await sleep(200)
        const confirmBtn = [...document.querySelectorAll('button')].find(
          (b) => b.textContent.trim() === '확인' && b.offsetParent !== null
        )
        if (confirmBtn) {
          confirmBtn.click()
          await sleep(800)
          break
        }
      }
    }
    console.log('[삼바-주문처리-패션플러스] 배송지 등록 완료')
  }

  // ── 주문서: 전체 동의하기 체크 ──
  async function checkAllAgree() {
    // "전체 동의" 텍스트를 가진 label 또는 버튼 탐색
    const allAgreeEl =
      [...document.querySelectorAll('label')].find(
        (l) => l.textContent.trim().includes('전체 동의')
      ) ||
      [...document.querySelectorAll('button, span, div')].find(
        (el) => el.textContent.trim() === '전체 동의하기' && el.offsetParent !== null
      )
    if (!allAgreeEl) return
    // label에 for 속성이 있으면 연결된 checkbox 클릭
    const forId = allAgreeEl.getAttribute && allAgreeEl.getAttribute('for')
    const cb = forId
      ? document.getElementById(forId)
      : allAgreeEl.querySelector('input[type="checkbox"]')
    if (cb) {
      if (!cb.checked) { cb.click(); await sleep(400) }
    } else {
      allAgreeEl.click()
      await sleep(400)
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
        const { orderType, productOption, shippingName, shippingPhone, shippingZipcode, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /fashionplus\.co\.kr\/order\/(\d+|write|sheet)/.test(window.location.href)

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
            await changeShipping(shippingName, shippingPhone, shippingZipcode || '', shippingAddress, shippingAddressDetail)
          }
          // FashionPlus는 쿠폰 자동 적용 — selectCoupon 불필요
          await checkAllAgree()
          sendResponse({ success: true, status: 'ready-to-pay' })
        }
      } catch (e) {
        sendResponse({ success: false, error: e.message })
      }
    })()
    return true
  })
})()

// content-purchase-lotteon-order.js — 롯데ON 직배/까대기/선물 주문처리
// 확인된 셀렉터: 바로구매 button.hasBgColor.bgColorRed(텍스트 '바로 구매하기')
// 선물하기: button.gift (텍스트 '선물하기') — CDP 실측 확인
// 옵션: 커스텀 드롭다운 (.selectResult label 클릭 → ul.selectLists li .caption 텍스트 클릭)
;(() => {
  if (window.__sambaLotteonOrderLoaded) return
  window.__sambaLotteonOrderLoaded = true
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  try { Object.defineProperty(window, 'alert', { value: () => {} }) } catch { window.alert = () => {} }
  try { Object.defineProperty(window, 'confirm', { value: () => true }) } catch { window.confirm = () => true }

  // ── 옵션 선택 (커스텀 드롭다운) ──
  // 구조: .optionWrap > .selectResult > label → 클릭 → ul.selectLists 열림 → li > .labelTextWrap > .caption 클릭
  async function selectOption(val) {
    val = String(val).trim()
    if (!val) return true
    // "옵션:01화이트 / M" → 파트별로 "그룹명:" 접두 제거 → ["01화이트", "M"]
    // (삼바가 옵션 앞에 그룹명을 붙여 보내는 경우가 있어 매칭 실패하던 버그)
    const parts = val.split('/').map(s => {
      const p = s.trim()
      const ci = p.indexOf(':')
      return ci >= 0 ? p.slice(ci + 1).trim() : p
    }).filter(Boolean)

    // [핵심] 무신사처럼 색상을 먼저 골라야 사이즈가 활성화됨 → 옵션 그룹을
    // DOM 순서(보통 색상→사이즈)대로 하나씩 처리. 각 그룹에서 아직 사용 안 한
    // 옵션 중 매칭되는 걸 선택하고, 매칭 없으면 첫 재고 항목 자동선택(다음 그룹
    // 활성화용). 품절('품절' 텍스트) 항목은 제외.
    const usedParts = new Set()
    const _txt = (li) => {
      const cap = li.querySelector('.caption, .labelTextWrap span')
      return (cap || li).textContent.trim()
    }
    // 품절 판정은 캡션 텍스트의 "품절"만으로 한다. li 전체 textContent엔 재고
    // 있는 항목에도 "품절 알림" 등 숨은 텍스트가 있어 M까지 품절로 오판됨.
    const _soldOut = (li) => _txt(li).includes('품절')

    const wraps = Array.from(document.querySelectorAll('.optionWrap'))
    console.log(`[삼바-롯데온-진단] optionWrap ${wraps.length}개 | 파트=${JSON.stringify(parts)}`)
    for (let wi = 0; wi < wraps.length; wi++) {
      // 옵션(색상+사이즈) 다 선택됐으면 중단 — optionWrap이 중복(2세트)이라
      // 다 채운 뒤 남은 박스에서 엉뚱한 자동선택되는 것 방지
      if (usedParts.size >= parts.length) break
      const wrap = wraps[wi]
      const label = wrap.querySelector('.selectResult label, .selectResult')
      const ph = (label?.textContent || '').trim().slice(0, 20)
      if (label) { label.click(); await sleep(700) }

      // 항목 폴링 — 색상 선택 후 사이즈 목록이 늦게 뜨는 경우 대비 (최대 3초)
      let ul = null, lis = []
      for (let _p = 0; _p < 15; _p++) {
        ul = wrap.querySelector('ul.selectLists')
        lis = ul ? Array.from(ul.querySelectorAll('li')) : []
        if (lis.length > 0) break
        await sleep(200)
      }
      // [진단] 이 그룹의 플레이스홀더 + 항목 텍스트 덤프
      console.log(`[삼바-롯데온-진단] [${wi}] ph="${ph}" 항목 ${lis.length}개: ` +
        lis.map((li, k) => `[${k}]"${_txt(li).slice(0, 20)}"품절=${_soldOut(li)}`).join(' || '))
      if (!ul || lis.length === 0) { if (label) label.click(); continue }

      // 이 그룹에서 매칭되는 미사용 옵션 찾기 (정확매칭 우선, 품절 제외)
      let picked = null, pickedPart = ''
      for (const part of parts) {
        if (usedParts.has(part)) continue
        const li =
          lis.find(li => !_soldOut(li) && _txt(li) === part) ||
          lis.find(li => !_soldOut(li) && (
            _txt(li).startsWith(part + ' ') ||
            _txt(li).startsWith(part + '/') ||
            _txt(li).startsWith(part)
          ))
        if (li) { picked = li; pickedPart = part; break }
      }

      if (picked) {
        console.log(`[삼바-롯데온] 옵션 "${_txt(picked)}" 선택 (매칭: ${pickedPart})`)
        picked.click(); await sleep(800); usedParts.add(pickedPart)
      } else {
        // 이 그룹에 매칭 옵션 없음(예: 색상 미지정) → 첫 재고 항목 자동선택
        const avail = lis.filter(li => !_soldOut(li) && _txt(li))
        if (avail.length) {
          console.log(`[삼바-롯데온] 옵션 자동선택: "${_txt(avail[0])}" (매칭 옵션 없음)`)
          avail[0].click(); await sleep(800)
        } else if (label) { label.click(); await sleep(200) }
      }
    }
    return true
  }

  // ── 바로구매 ──
  async function clickBuyNow() {
    for (const btn of document.querySelectorAll('button.hasBgColor, button')) {
      const t = btn.textContent.trim()
      if (t === '바로 구매하기' || t === '바로구매') { btn.click(); await sleep(3000); return true }
    }
    return false
  }

  // ── 선물하기 버튼 클릭 (상품 페이지) ──
  async function clickGift() {
    const btn = [...document.querySelectorAll('button.gift, button[class*="gift"]')].find(b => b.offsetHeight > 0 && b.textContent.includes('선물'))
    if (btn) { btn.click(); await sleep(3000); return true }
    return false
  }

  // ── native setter (Vue readonly input 우회) ──
  const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  const setVal = (el, v) => {
    if (!el) return
    if (nativeSetter) nativeSetter.call(el, v)
    else el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
    el.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // ── 주문서: 배송지 변경 (직배/까대기) ──
  // 실측 셀렉터: button.btn-plus 텍스트='배송지 수정하기'
  async function changeShipping(name, phone, address, detail) {
    if (!name) return
    const changeBtn = document.querySelector('button.btn-plus') ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '배송지 수정하기' && b.offsetHeight > 0) ||
      Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '변경' && b.offsetHeight > 0)
    if (!changeBtn) return
    changeBtn.click()
    await sleep(1500)

    const modal = document.querySelector('[role="dialog"], .v--modal-box')
    if (!modal) return

    const radios = Array.from(modal.querySelectorAll('input[type="radio"]'))
    let selected = false
    for (const r of radios) {
      const container = r.closest('li, label, div')
      if (container && container.textContent.includes(name)) {
        r.click(); await sleep(500); selected = true; break
      }
    }

    if (!selected) {
      const newBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.includes('새 배송지') || b.textContent.includes('배송지 추가'))
      if (newBtn) { newBtn.click(); await sleep(1000) }

      const nameEl = modal.querySelector('input[placeholder*="받는 분"]') ||
        Array.from(modal.querySelectorAll('input[type="text"]')).find(i => !i.readOnly)
      setVal(nameEl, name)

      const phoneEl = modal.querySelector('input[placeholder*="휴대폰"]') ||
        Array.from(modal.querySelectorAll('input[type="tel"]')).find(i => !i.readOnly)
      setVal(phoneEl, (phone || '').replace(/-/g, ''))

      await sleep(300)
      const saveBtn = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.trim() === '저장')
      if (saveBtn) { saveBtn.click(); await sleep(1500) }
    }

    const confirmBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '확인')
    if (confirmBtn) { confirmBtn.click(); await sleep(1500) }
  }

  // ── 선물 주문서: "받는 분 주소로 보내기" 플로우 ──
  // 요구사항: 전화번호로 보내기(X) → 받는 분 주소로 보내기 라디오 → "빠른 선물" 체크
  //          → 배송지 선택하기 → 새 배송지 등록 → 수령인/연락처/주소 입력 → 결제만 남김
  //  · 연락처는 사무실 전화(shippingPhone) 고정값 사용
  const _visBtns = (root) => [...root.querySelectorAll('button')].filter(b => b.offsetHeight > 0)
  async function fillGiftRecipient(opts) {
    const { name, phone, zipcode, address, detail } = opts || {}
    if (!name) return
    await sleep(1000)

    // 1. "받는 분 주소로 보내기" 라디오 선택
    const addrRadio = [...document.querySelectorAll('input[type="radio"]')].find(r => {
      const box = r.closest('label, li, div')
      return box && box.textContent.includes('주소로 보내')
    })
    if (addrRadio && !addrRadio.checked) { addrRadio.click(); await sleep(1000) }
    console.log(`[삼바-롯데온] 1) 주소로보내기 라디오 클릭: ${!!addrRadio}`)

    // 2. "빠른 선물 보내드릴까요?" 체크박스 (받는분 수락없이 바로 배송)
    //    커스텀 체크박스라 실제 input이 offsetHeight=0으로 숨겨져 있음 → offsetHeight 필터 금지.
    //    "빠른 선물" 텍스트를 가진 컨테이너를 먼저 찾고, 그 안/근처의 체크박스 input을 잡아
    //    연결된 label(또는 감싼 label)을 클릭해 토글한다.
    let fastChk = null
    for (let _t = 0; _t < 10; _t++) {
      // "빠른 선물" 텍스트를 가진 가장 안쪽 요소 (자식 많은 큰 컨테이너 제외)
      const labelEl = [...document.querySelectorAll('label, li, div, span, p')].find(
        el => el.offsetHeight > 0 && /빠른\s*선물/.test(el.textContent) && el.querySelectorAll('*').length < 20
      )
      if (labelEl) {
        const cont = labelEl.closest('label, li, div') || labelEl
        fastChk = cont.querySelector('input[type="checkbox"]') ||
          cont.parentElement?.querySelector('input[type="checkbox"]') ||
          cont.closest('div')?.querySelector('input[type="checkbox"]')
        if (fastChk) break
      }
      await sleep(300)
    }
    // [진단] 페이지의 모든 체크박스 덤프 (못 찾을 때 구조 파악용)
    console.log(`[삼바-롯데온-진단] 체크박스 목록: ` +
      [...document.querySelectorAll('input[type="checkbox"]')].map(c => {
        const box = c.closest('label, li, div')
        return `{id=${c.id || '-'} chk=${c.checked} h=${c.offsetHeight} txt="${(box?.textContent || '').trim().slice(0, 14)}"}`
      }).join(' | '))
    if (fastChk && !fastChk.checked) {
      // 숨겨진 input이면 연결된 label 클릭이 안전 (input.click은 커스텀UI 토글 안 될 수 있음)
      const lbl = fastChk.id ? document.querySelector(`label[for="${fastChk.id}"]`) : null
      const clickTarget = lbl || fastChk.closest('label') || fastChk
      clickTarget.click()
      await sleep(500)
      // 여전히 안 되면 input 직접 클릭 재시도
      if (!fastChk.checked) { fastChk.click(); await sleep(400) }
    }
    console.log(`[삼바-롯데온] 2) 빠른선물 체크: ${!!fastChk} (checked=${fastChk?.checked})`)

    // 3. "배송지 선택하기" 버튼
    const selBtn = _visBtns(document).find(b => b.textContent.includes('배송지 선택하기'))
    if (selBtn) { selBtn.click(); await sleep(1800) }
    console.log(`[삼바-롯데온] 3) 배송지선택하기 클릭: ${!!selBtn}`)

    // 4. 배송지 관리 모달 → "새 배송지 등록" 버튼
    const modal = document.querySelector('[role="dialog"], .v--modal-box') || document
    const newBtn = _visBtns(modal).find(b => b.textContent.includes('새 배송지 등록') || b.textContent.includes('새 배송지'))
    if (newBtn) { newBtn.click(); await sleep(1800) }
    console.log(`[삼바-롯데온] 4) 새배송지등록 클릭: ${!!newBtn}`)

    // 5. 배송지 등록 폼(최상위 모달) 스코프 — "우편번호 찾기" 버튼을 포함한 다이얼로그
    const dialogs = [...document.querySelectorAll('[role="dialog"], .v--modal-box')].filter(d => d.offsetHeight > 0)
    const form = dialogs.reverse().find(d => _visBtns(d).some(b => b.textContent.includes('우편번호 찾기'))) || document

    // 텍스트/전화 입력만 (라디오 제외 — 기존 배송지 목록 라디오 수백개 노이즈 제거)
    const txtInputs = [...form.querySelectorAll('input')].filter(
      i => i.offsetHeight > 0 && !['radio', 'checkbox', 'hidden'].includes(i.type)
    )
    console.log(`[삼바-롯데온-진단] 폼 텍스트입력 ${txtInputs.length}개: ` +
      txtInputs.map(i => `{ph="${i.placeholder || ''}" type=${i.type} ro=${i.readOnly}}`).join(' | '))

    // 6. 받는 분(수령인) 입력
    const nameEl = form.querySelector('input[placeholder*="받는 분"]') ||
      txtInputs.find(i => (i.placeholder || '').includes('받는'))
    if (nameEl) setVal(nameEl, name)
    console.log(`[삼바-롯데온] 6) 받는분 입력: ${!!nameEl} → "${name}"`)

    // 7. 휴대폰 번호 입력 (하이픈 제거, 사무실 전화 고정)
    const phoneEl = form.querySelector('input[placeholder*="휴대폰"]') ||
      txtInputs.find(i => (i.placeholder || '').includes('휴대폰') || (i.placeholder || '').includes('번호'))
    if (phoneEl) setVal(phoneEl, (phone || '').replace(/-/g, ''))
    console.log(`[삼바-롯데온] 7) 휴대폰 입력: ${!!phoneEl} → "${(phone || '').replace(/-/g, '')}"`)

    // 주소 데이터 없으면(배포 전) 여기서 안전 정지 — 빈 주소로 저장/검색 방지
    if (!address || !address.trim()) {
      console.log(`[삼바-롯데온] 주소 데이터 없음(addr="${address}") — 배포 전이라 여기서 정지. 배포 후 자동 주소입력 진행됨`)
      return
    }

    // 8. 우편번호 찾기 클릭 → 페이지 내 "주소 검색" 다이얼로그 오픈
    await sleep(300)
    const zipBtn = _visBtns(form).find(b => b.textContent.includes('우편번호 찾기'))
    if (zipBtn) { zipBtn.click(); await sleep(2000) }
    console.log(`[삼바-롯데온] 8) 우편번호찾기 클릭: ${!!zipBtn}`)

    // 9. "주소 검색" 다이얼로그: 검색어 입력 → 검색 → 첫 결과 선택
    const searchDlg = [...document.querySelectorAll('[role="dialog"], .v--modal-box')]
      .filter(d => d.offsetHeight > 0)
      .find(d => d.textContent.includes('주소 검색') || d.querySelector('input[placeholder*="올림픽로"]'))
    if (searchDlg) {
      const sInput = searchDlg.querySelector('input[placeholder*="올림픽로"]') ||
        searchDlg.querySelector('input[type="text"], input[type="search"]')
      if (sInput) {
        setVal(sInput, address.trim())
        await sleep(300)
        // 검색 실행 — 돋보기 버튼 또는 Enter
        const sBtn = _visBtns(searchDlg).find(b => b.querySelector('svg, i') || /검색|찾기/.test(b.textContent))
        if (sBtn) sBtn.click()
        else sInput.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }))
        await sleep(2200)
        // [진단] 결과 구조 확인
        const resLis = [...searchDlg.querySelectorAll('li')].filter(e => e.offsetHeight > 0 && e.textContent.trim().length > 5)
        console.log(`[삼바-롯데온-진단] 주소검색 결과 li ${resLis.length}개: ` +
          resLis.slice(0, 6).map(e => `"${e.textContent.trim().slice(0, 28)}"`).join(' | '))
        // 첫 유효 결과(숫자 포함 = 도로명주소) 선택
        const firstResult = resLis.find(li => /\d/.test(li.textContent)) || resLis[0]
        if (firstResult) {
          firstResult.click()
          await sleep(1500)
          console.log(`[삼바-롯데온] 9) 주소결과 선택: "${firstResult.textContent.trim().slice(0, 30)}"`)
        } else {
          console.log(`[삼바-롯데온] 9) 주소검색 결과 없음 (검색어="${address.trim()}")`)
        }
      } else {
        console.log(`[삼바-롯데온] 9) 주소검색 입력칸 못 찾음`)
      }
    } else {
      console.log(`[삼바-롯데온] 9) 주소검색 다이얼로그 못 찾음`)
    }

    // 10. 상세주소 입력 — 등록 폼의 빈 text input 중 마지막 (기본주소 다음 칸)
    await sleep(500)
    const regForm = [...document.querySelectorAll('[role="dialog"], .v--modal-box')].filter(d => d.offsetHeight > 0)
      .find(d => _visBtns(d).some(b => b.textContent.includes('우편번호 찾기'))) || form
    if (detail && detail.trim()) {
      const detailInput = regForm.querySelector('input[placeholder*="상세"]') ||
        [...regForm.querySelectorAll('input[type="text"]')]
          .filter(i => i.offsetHeight > 0 && !i.readOnly && !i.value.trim()).pop()
      if (detailInput) { setVal(detailInput, detail.trim()); console.log(`[삼바-롯데온] 10) 상세주소 입력: "${detail.trim()}"`) }
      else console.log(`[삼바-롯데온] 10) 상세주소 입력칸 못 찾음`)
    }

    // 11. (필수) 개인정보 동의 체크 — 저장 버튼 활성화 조건
    await sleep(300)
    for (const ch of [...regForm.querySelectorAll('input[type="checkbox"]')].filter(c => c.offsetHeight > 0)) {
      const box = ch.closest('label, li, div')
      if (box && box.textContent.includes('필수') && box.textContent.includes('동의') && !ch.checked) {
        ch.click(); await sleep(200)
      }
    }

    // 12. 저장 → 배송지 선택완료 (결제만 남기고 정지)
    await sleep(400)
    const saveBtn = _visBtns(regForm).find(b => b.textContent.trim() === '저장')
    if (saveBtn && !saveBtn.disabled) { saveBtn.click(); await sleep(2000) }
    console.log(`[삼바-롯데온] 11) 저장 클릭: ${!!saveBtn} (disabled=${saveBtn?.disabled})`)

    // 저장 후 배송지 관리 모달로 복귀 → "선택완료"
    const doneModal = document.querySelector('[role="dialog"], .v--modal-box')
    if (doneModal) {
      const doneBtn = _visBtns(doneModal).find(b => b.textContent.includes('선택완료') || b.textContent.includes('선택 완료'))
      if (doneBtn && !doneBtn.disabled) { doneBtn.click(); await sleep(1500); console.log(`[삼바-롯데온] 12) 선택완료 클릭`) }
    }
    await sleep(300)
  }

  // ── 주문서: 쿠폰 ──
  async function selectCoupon() {
    for (const btn of document.querySelectorAll('button, a')) {
      if (btn.textContent.trim().includes('쿠폰')) { btn.click(); await sleep(1500); break }
    }
    const dlg = document.querySelector('[role="dialog"], .coupon_area, .coupon_list, .layer_coupon')
    if (dlg) {
      const items = dlg.querySelectorAll('[role="radio"], li, .coupon_item')
      if (items.length) { items[0].click(); await sleep(500) }
      for (const btn of dlg.querySelectorAll('button')) {
        const t = btn.textContent.trim()
        if (t === '적용' || t === '확인') { btn.click(); await sleep(1000); break }
      }
    }
  }

  // ── 실구매가 계산 ──
  function computeActualCost() {
    const getText = (sel) => {
      const el = document.querySelector(sel)
      return el ? parseInt((el.textContent || '').replace(/[^\d]/g, '')) || 0 : 0
    }
    // 실측: .totalPriceNum SPAN = '89,000'
    const finalAmount = getText('.totalPriceNum') ||
      getText('.totalPriceDetail') || 0
    return { finalAmount, actualCost: finalAmount }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (!msg || msg.action !== 'samba_place_order') return
    ;(async () => {
      try {
        const { orderType, productOption, shippingName, shippingPhone, shippingZipcode, shippingAddress, shippingAddressDetail } = msg
        const isOrderForm = /lotteon\.com\/(p\/)?order/.test(window.location.href)
        console.log(`[삼바-롯데온] 시작 opt=${productOption} | type=${orderType} | 주문서=${isOrderForm} | url=${window.location.href}`)
        if (!isOrderForm) {
          // 상품 페이지: 옵션 선택 + 구매/선물 버튼 클릭
          if (productOption) {
            const optOk = await selectOption(productOption)
            console.log(`[삼바-롯데온] 옵션선택 시도 완료: ${optOk}`)
          }
          await sleep(800)
          let ok = false
          if (orderType === 'gift') {
            ok = await clickGift()
            console.log(`[삼바-롯데온] 선물하기 버튼 클릭: ${ok}`)
            if (!ok) { sendResponse({ success: false, error: '선물하기 버튼 못 찾음' }); return }
          } else {
            ok = await clickBuyNow()
            console.log(`[삼바-롯데온] 바로구매 버튼 클릭: ${ok}`)
            if (!ok) { sendResponse({ success: false, error: '바로구매 버튼 못 찾음' }); return }
          }
          sendResponse({ success: true, nextStep: 'order-form' })
        } else {
          // 주문서 페이지
          await sleep(1500)
          console.log(`[삼바-롯데온] 주문서 진입 — 수령인/배송지 처리 시작`)
          if (orderType === 'direct' || orderType === 'kkadaegi') {
            await changeShipping(shippingName, shippingPhone, shippingAddress, shippingAddressDetail)
          } else if (orderType === 'gift') {
            await fillGiftRecipient({ name: shippingName, phone: shippingPhone, zipcode: shippingZipcode, address: shippingAddress, detail: shippingAddressDetail })
          }
          await selectCoupon()
          // 롯데ON 1페이지(orders/N) → 계속하기 → payments 페이지
          const continueBtn = Array.from(document.querySelectorAll('button')).find(b => b.offsetHeight > 0 && b.textContent.trim() === '계속하기')
          const costInfo = computeActualCost()
          console.log(`[삼바-롯데온] 계속하기버튼=${!!continueBtn} | 금액=${costInfo.finalAmount}`)
          if (continueBtn) {
            sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
            continueBtn.click()
            return
          }
          sendResponse({ success: true, status: 'ready-to-pay', ...costInfo })
        }
      } catch (e) { sendResponse({ success: false, error: e.message }) }
    })()
    return true
  })
})()

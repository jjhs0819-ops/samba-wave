// content-review-kream.js — KREAM 리뷰 자동작성 (kream-auto-review content/content.js 포팅)
// 인페이지 패턴 — 별점 클릭 → 자동구매확정 팝업 → 리뷰 모달 → 칩 선택 → 제출
;(() => {
  if (window.__sambaKreamReviewLoaded) return
  window.__sambaKreamReviewLoaded = true

  const DEFAULT_WEIGHTS = {
    starWeights: { 5: 70, 4: 25, 3: 5 },
    sizeEvalWeights: { 정사이즈예요: 80, '작게 나왔어요': 10, '크게 나왔어요': 10 },
    sizeCompareWeights: { 정사이즈: 70, '반사이즈 다운': 15, '반사이즈 업': 15 },
    comfortWeights: { 편해요: 60, 보통이에요: 30, 불편해요: 10 },
    widthWeights: { 보통이에요: 60, 넓어요: 25, 좁아요: 15 },
  }
  const W = DEFAULT_WEIGHTS

  function weightedChoice(w) {
    const entries = Object.entries(w)
    const total = entries.reduce((s, [, v]) => s + v, 0)
    let r = Math.random() * total
    for (const [c, v] of entries) { r -= v; if (r <= 0) return c }
    return entries[entries.length - 1][0]
  }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }
  function rand(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a }
  function click(el) { if (el) el.click() }

  function waitFor(fn, timeout = 5000) {
    return new Promise(resolve => {
      const ex = fn()
      if (ex) { resolve(ex); return }
      const ob = new MutationObserver(() => { const el = fn(); if (el) { ob.disconnect(); resolve(el) } })
      ob.observe(document.body, { childList: true, subtree: true })
      setTimeout(() => { ob.disconnect(); resolve(null) }, timeout)
    })
  }

  // 헤더의 '리뷰 쓰기 16' 숫자 — 제출이 실제로 됐는지 판정하는 기준.
  function getPendingCount() {
    const m = (document.body.innerText || '').match(/리뷰\s*쓰기\s*(\d+)/)
    return m ? Number(m[1]) : null
  }

  // 조건이 참이 될 때까지 폴링(waitFor 는 DOM 변경 기준이라 숫자 변화에 약하다).
  async function waitUntil(fn, timeout = 8000, step = 400) {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      try { if (fn()) return true } catch (_) {}
      await sleep(step)
    }
    return false
  }

  function getReviewItems() {
    return Array.from(document.querySelectorAll('.product_list_info_summary')).filter(
      it => !it.closest('[class*="review-write"]') && !it.closest('[class*="layer"]') && !it.dataset.sambaReviewed
    )
  }

  function findStarArea(itemEl) {
    const parent = itemEl.closest('[class*="layout_list_vertical"]')
    if (!parent) return null
    return parent.querySelector('[class*="rating"]') || null
  }

  // el.click() 만으로는 안 먹는 위젯이 있다(별점처럼 포인터 이벤트를 직접 듣는 경우).
  // 실제 마우스처럼 좌표를 실은 이벤트를 순서대로 보낸다.
  function realClick(el, x, y) {
    if (!el) return false
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return false
    const cx = x == null ? r.left + r.width / 2 : x
    const cy = y == null ? r.top + r.height / 2 : y
    const opt = { bubbles: true, cancelable: true, composed: true, clientX: cx, clientY: cy, button: 0 }
    for (const type of ['pointerover', 'pointerenter', 'pointermove', 'pointerdown',
                        'mousedown', 'pointerup', 'mouseup', 'click']) {
      const Ctor = type.startsWith('pointer') ? PointerEvent : MouseEvent
      try { el.dispatchEvent(new Ctor(type, opt)) } catch (_) {
        el.dispatchEvent(new MouseEvent(type.replace('pointer', 'mouse'), opt))
      }
    }
    return true
  }

  function clickStar(starArea, count) {
    let stars = starArea.querySelectorAll('.rating-element')
    if (stars.length === 0) {
      // 클래스명이 바뀌어도 별 개수(5개)로 잡아낸다.
      const kids = Array.from(starArea.children)
      if (kids.length >= 5) stars = kids
    }
    if (stars.length >= count) {
      const t = stars[count - 1]
      const inner = t.querySelector && (t.querySelector('[class*="image-element"]') || t.querySelector('svg, img')) || t
      realClick(inner)
      click(inner)
      return
    }
    // 별 요소를 못 나누면 영역 안에서 위치로 누른다(왼쪽부터 count/5 지점).
    const r = starArea.getBoundingClientRect()
    if (r.width) {
      realClick(starArea, r.left + (r.width * (count - 0.5)) / 5, r.top + r.height / 2)
      return
    }
    click(starArea)
  }

  function findPopupByText(text) {
    const layers = document.querySelectorAll('.layer_container, [class*="layer_container"]')
    for (const l of layers) if (l.textContent.includes(text) && l.querySelector('button')) return l
    for (const d of document.querySelectorAll('div')) {
      if (d.textContent.includes(text) && d.querySelector('button')
          && d.children.length <= 10 && d.offsetWidth > 200 && d.offsetWidth < 600) return d
    }
    // 너비·자식수 조건에 안 걸리는 모달이 있다(크림이 구조를 바꾸면 바로 못 찾음).
    // 마지막 수단 — 문구를 담은 가장 작은 요소부터 버튼 있는 조상까지 거슬러 올라간다.
    const holder = Array.from(document.querySelectorAll('div, section, dialog'))
      .filter(d => d.textContent.includes(text) && d.textContent.length < 300)
      .sort((a, b) => a.textContent.length - b.textContent.length)[0]
    for (let el = holder; el; el = el.parentElement) {
      if (el.querySelector && el.querySelector('button')) return el
    }
    return null
  }

  // 팝업 탐지가 실패해도 버튼 글자만 맞으면 누른다 — 화면 구조 변경에 가장 강하다.
  function clickButtonByText(...labels) {
    const btn = Array.from(document.querySelectorAll('button, [role="button"], a'))
      .find(b => {
        const t = (b.textContent || '').trim()
        return labels.some(l => t === l) && b.offsetParent !== null
      })
    if (btn) { click(btn); return true }
    return false
  }

  function findQuestionText(box) {
    let el = box.previousElementSibling
    while (el) {
      const t = el.textContent.trim()
      if (t.length > 3 && t.length < 100 && t.includes('?')) return t
      const p = el.querySelector('p')
      if (p && p.textContent.trim().length > 3) return p.textContent.trim()
      el = el.previousElementSibling
    }
    return ''
  }

  function pickChip(question, chips) {
    let w
    if (question.includes('사이즈는 어떤가요') || question.includes('구매하신')) w = W.sizeEvalWeights
    else if (question.includes('크게/작게') || question.includes('평소 사이즈에서')) w = W.sizeCompareWeights
    else if (question.includes('착화감')) w = W.comfortWeights
    else if (question.includes('발볼')) w = W.widthWeights
    else return chips[Math.min(1, chips.length - 1)]
    const chosen = weightedChoice(w)
    return Array.from(chips).find(c => c.textContent.trim() === chosen) || chips[0]
  }

  async function fillForm(modal) {
    const container = modal.closest('[class*="layer"]') || modal
    const boxes = container.querySelectorAll('[class*="layout_flow_box"]')
    for (const box of boxes) {
      const chips = box.querySelectorAll('[class*="chip_button"]')
      if (chips.length === 0) continue
      const q = findQuestionText(box)
      const chosen = pickChip(q, chips)
      if (chosen) {
        await sleep(rand(700, 1800))
        chosen.scrollIntoView({ behavior: 'instant', block: 'center' })
        await sleep(300)
        click(chosen)
      }
    }
  }

  function findSubmitButton() {
    const footer = document.querySelector('[class*="review-write_footer"]')
    if (footer) {
      const btn = footer.querySelector('button')
      if (btn) return btn
    }
    return Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('리뷰 제출하기')) || null
  }

  function getLastButton(c) {
    const btns = c.querySelectorAll('button')
    return btns.length > 0 ? btns[btns.length - 1] : null
  }

  async function closeAllModals() {
    for (const btn of document.querySelectorAll('[class*="layer"] button')) {
      if (btn.querySelector('svg') || ['취소', 'X'].includes(btn.textContent.trim())) {
        click(btn); await sleep(300)
      }
    }
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await sleep(400)
  }

  async function processOne() {
    const items = getReviewItems()
    if (items.length === 0) return { noItems: true }
    const itemEl = items[0]
    itemEl.dataset.sambaReviewed = 'true'

    itemEl.scrollIntoView({ behavior: 'instant', block: 'center' })
    await sleep(1000)

    const starArea = findStarArea(itemEl)
    if (!starArea) return { success: false, error: '별점 영역 못 찾음' }

    const starCount = parseInt(weightedChoice(W.starWeights))
    let opened = false
    for (let att = 0; att < 3; att++) {
      clickStar(starArea, starCount)
      const r = await waitFor(() =>
        (document.body.textContent.includes('자동 구매 확정') ? document.body : null)
        || findPopupByText('자동 구매 확정')
        || document.querySelector('[class*="review-write_content"]'),
        5000
      )
      if (r) { opened = true; break }
      await sleep(1300)
    }
    if (!opened) {
      // 다음에 원인을 바로 알 수 있게 별점 영역 상태를 남긴다.
      const stars = starArea.querySelectorAll('.rating-element')
      const rect = starArea.getBoundingClientRect()
      console.warn('[적립금-리뷰] 별점 클릭 실패 진단:', {
        cls: starArea.className, ratingEl: stars.length, kids: starArea.children.length,
        w: Math.round(rect.width), h: Math.round(rect.height), want: starCount,
      })
      return { success: false, error: '별점 클릭 3회 실패' }
    }

    // 자동 구매 확정 팝업 — '취소 / 리뷰 작성' 중 '리뷰 작성' 을 눌러야 넘어간다.
    const alertPopup = findPopupByText('자동 구매 확정')
    if (alertPopup) {
      // 글자로 먼저 찾는다 — 팝업 대신 조상 요소를 잡았을 때 '취소' 를 누르지 않도록.
      const byText = Array.from(alertPopup.querySelectorAll('button'))
        .find(b => ['리뷰 작성', '확인'].includes((b.textContent || '').trim()))
      const c = byText || getLastButton(alertPopup)
      if (c) { await sleep(rand(500, 1300)); click(c); await sleep(rand(1500, 2800)) }
    } else if (document.body.textContent.includes('자동 구매 확정')) {
      // 팝업 요소를 못 잡아도 버튼 글자로 진행한다(여기서 멈춰 서 있던 원인).
      await sleep(rand(500, 1300))
      if (clickButtonByText('리뷰 작성', '확인')) await sleep(rand(1500, 2800))
    }

    const modal = await waitFor(() => document.querySelector('[class*="review-write_content"]'), 10000)
    if (!modal) return { success: false, error: '리뷰 모달 안 열림' }

    await fillForm(modal)
    await sleep(rand(700, 1800))

    const submit = findSubmitButton()
    if (!submit) return { success: false, error: '제출 버튼 못 찾음' }
    const before = getPendingCount()
    realClick(submit)
    click(submit)

    const confirm = await waitFor(() => findPopupByText('제출 후에는'), 5000)
    if (confirm) {
      // 마지막 버튼을 누르면 '취소' 를 누를 수 있다 — 글자를 먼저 본다.
      const byText = Array.from(confirm.querySelectorAll('button'))
        .find(b => ['확인', '제출', '제출하기', '리뷰 제출하기'].includes((b.textContent || '').trim()))
      const f = byText || getLastButton(confirm)
      if (f) { await sleep(rand(400, 1200)); realClick(f); click(f) }
    }
    await sleep(rand(1800, 3500))
    await closeAllModals()

    // 실제로 등록됐는지 확인 — 안 하면 클릭이 씹혀도 '완료' 로 보고된다.
    // 헤더의 '리뷰 쓰기 N' 이 줄어드는 것이 가장 확실한 신호다.
    if (before != null) {
      const ok = await waitUntil(() => {
        const now = getPendingCount()
        return now != null && now < before
      }, 8000)
      if (!ok) return { success: false, error: `제출 확인 안 됨(리뷰 쓰기 ${before}건 그대로)` }
    } else if (document.querySelector('[class*="review-write_content"]')) {
      // 개수를 못 읽으면 최소한 작성 모달이 닫혔는지로 판단한다.
      return { success: false, error: '제출 확인 안 됨(작성 모달이 그대로 열려 있음)' }
    }
    return { success: true, starCount }
  }

  async function loadMore() {
    // KREAM은 페이지 하단 자동 로드 — 스크롤
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
    await sleep(2500)
    return { ok: getReviewItems().length > 0 }
  }

  chrome.runtime.onMessage.addListener((msg, _s, sr) => {
    const a = msg && msg.action
    if (a === 'samba_review_ping') { sr({ loaded: true }); return true }
    ;(async () => {
      try {
        if (a === 'samba_review_getPageInfo') sr({ itemCount: getReviewItems().length })
        else if (a === 'samba_review_processOne') sr(await processOne())
        else if (a === 'samba_review_loadMore') sr(await loadMore())
        else sr({ error: 'unknown' })
      } catch (e) { sr({ success: false, error: e.message }) }
    })()
    return true
  })

  console.log('[삼바-크림리뷰] 로드')
})()

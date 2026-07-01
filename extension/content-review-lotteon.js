// content-review-lotteon.js — 롯데ON 리뷰 자동작성 (kream-auto-review content-lotteon.js 포팅)
// Vue.js 모달 인페이지 패턴 — 리뷰쓰기 버튼 클릭 → 모달 → 폼 채우기 → 제출 → 모달 닫힘
;(() => {
  if (window.__sambaLotteonReviewListener) {
    try { chrome.runtime.onMessage.removeListener(window.__sambaLotteonReviewListener) } catch {}
  }

  // [2026-07-01] 리뷰 신고/숨김 방지 — 기존엔 의류+화장품 문구가 한 풀에 섞여 랜덤 선택돼
  //   티셔츠에 '발림성/피부' 같은 화장품 후기가 달려 "구매상품과 관련없는 글"로 신고·숨김됨(롯데ON 경고).
  //   → 상품 카테고리 감지 후 맞는 문구만 사용. 애매하면 범용(general)만(오배정 시에도 안전).
  const POOLS = {
    general: [
      '배송도 빠르고 상품도 깔끔하게 잘 왔어요 정말 만족합니다',
      '가격 대비 품질이 좋아서 아주 만족스러워요 추천합니다',
      '포장도 꼼꼼하고 상품 상태도 좋아서 마음에 쏙 들어요',
      '생각보다 훨씬 좋아서 다음에도 재구매할 생각입니다',
      '설명 그대로 잘 왔고 전체적으로 만족스러운 상품이에요',
      '믿고 샀는데 역시 좋네요 기분 좋게 잘 쓰고 있습니다',
      '빠른 배송 감사드리고 상품도 기대 이상이라 만족해요',
      '가성비도 좋고 품질도 괜찮아서 주변에 추천하고 싶어요',
      '무난하게 잘 쓰고 있어요 구매하길 잘한 것 같습니다',
      '상품도 좋고 응대도 친절해서 전체적으로 만족스러워요',
    ],
    clothing: [
      '착용감이 편하고 디자인도 예뻐서 자주 입게 돼요 만족합니다',
      '핏이 예쁘고 소재도 부드러워서 데일리로 입기 좋아요',
      '사이즈도 잘 맞고 색상도 화면과 동일해서 마음에 들어요',
      '코디하기 편하고 활용도가 높아서 아주 만족스러워요',
      '재질이 좋고 마감도 깔끔해서 오래 입을 수 있을 것 같아요',
      '가볍고 편해서 오래 입어도 불편하지 않아요 추천해요',
      '디자인이 세련되고 착용감도 좋아서 재구매 의향 있어요',
    ],
    cosmetics: [
      '발림성이 좋고 촉촉하게 마무리돼서 매일 사용하게 돼요',
      '향이 은은하고 순해서 부담 없이 사용하기 좋아요 만족해요',
      '흡수가 빠르고 자극 없이 순해서 계속 쓰게 되는 제품이에요',
      '사용 후 촉촉한 느낌이 오래가서 아주 만족스러워요',
      '발색도 자연스럽고 지속력도 좋아서 마음에 들어요',
      '사용감이 부드럽고 마무리가 깔끔해서 추천합니다',
    ],
  }
  const CAT_KW = {
    clothing: ['티셔츠', '반팔', '긴팔', '셔츠', '블라우스', '니트', '맨투맨', '후드', '스웨트', '가디건', '바지', '팬츠', '청바지', '슬랙스', '반바지', '스커트', '치마', '원피스', '자켓', '재킷', '코트', '패딩', '점퍼', '조끼', '레깅스', '트레이닝', '신발', '운동화', '스니커즈', '구두', '샌들', '부츠', '양말', '모자', '가방', '백팩', '벨트', '스카프'],
    cosmetics: ['에센스', '세럼', '앰플', '토너', '수분크림', '아이크림', '선크림', '선블록', '클렌징', '파운데이션', '쿠션', '컨실러', '립스틱', '립틴트', '틴트', '립밤', '섀도', '마스카라', '아이라이너', '블러셔', '마스크팩', '시트마스크', '향수', '퍼퓸', '바디워시', '바디로션', '샴푸', '트리트먼트', '헤어에센스', '미스트', '프라이머', '하이라이터'],
  }
  function detectCategory(t) {
    t = String(t || '')
    if (CAT_KW.clothing.some(k => t.includes(k))) return 'clothing' // 의류 먼저 — '크림색 티셔츠' 등 오탐 방지
    if (CAT_KW.cosmetics.some(k => t.includes(k))) return 'cosmetics'
    return 'general'
  }
  function productText(btn) {
    const box = btn.closest('li, tr, [class*="item"], [class*="goods"], [class*="product"], [class*="order"]')
    return (box || btn.parentElement?.parentElement || btn.parentElement || document.body).textContent || ''
  }
  function pickText(cat) {
    const pool = (cat && cat !== 'general' && POOLS[cat]) ? POOLS.general.concat(POOLS[cat]) : POOLS.general
    return pool[Math.floor(Math.random() * pool.length)]
  }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }
  function rand(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a }

  function getReviewableButtons() {
    return Array.from(document.querySelectorAll('button')).filter(b => {
      if (b.dataset.sambaReviewed) return false
      return b.textContent.trim().startsWith('리뷰쓰기')
    })
  }

  function waitForModal(timeout = 7000) {
    return new Promise(resolve => {
      const check = (el) => {
        const m = document.querySelector('.v--modal-box')
        if (!m) return null
        const pc = m.querySelector('.popContents')
        if (pc && pc.classList.contains('review-completion')) return null
        return (el < 2000 || m.offsetHeight > 0) ? m : null
      }
      const ex = check(0)
      if (ex) { resolve(ex); return }
      let el = 0
      const poll = setInterval(() => {
        el += 200
        const m = check(el)
        if (m) { clearInterval(poll); resolve(m) }
        else if (el >= timeout) { clearInterval(poll); resolve(null) }
      }, 200)
    })
  }

  function waitForModalClose(modal, timeout = 10000) {
    return new Promise(resolve => {
      let el = 0
      const poll = setInterval(async () => {
        el += 200
        if (!document.body.contains(modal) || modal.offsetHeight === 0) {
          clearInterval(poll); resolve(true); return
        }
        const pc = modal.querySelector('.popContents')
        if (pc && pc.classList.contains('review-completion')) {
          clearInterval(poll)
          const closeBtn = modal.querySelector('.guidClose')
          if (closeBtn) {
            closeBtn.click()
            let w = 0
            while (w < 4000) {
              await sleep(200); w += 200
              if (!document.body.contains(modal) || modal.offsetHeight === 0) break
            }
            if (document.body.contains(modal) && modal.offsetHeight > 0) {
              modal.style.display = 'none'
              const overlay = document.querySelector('.v--overlay')
              if (overlay) overlay.style.display = 'none'
            }
          }
          resolve(true); return
        }
        if (el >= timeout) { clearInterval(poll); resolve(false) }
      }, 200)
    })
  }

  async function processOne() {
    const items = getReviewableButtons()
    if (items.length === 0) return { noItems: true }
    const reviewBtn = items[0]
    const cat = detectCategory(productText(reviewBtn)) // 상품 카테고리 감지 → 맞는 후기문구 선택 (모달 열기 전 목록에서)

    // 잔존 모달 정리
    const stale = document.querySelector('.v--modal-box')
    if (stale && stale.offsetHeight > 0) {
      const sc = stale.querySelector('.guidClose') || stale.querySelector('button[class*="close"]')
      if (sc) { sc.click(); await sleep(600) }
      if (stale.offsetHeight > 0) {
        stale.style.display = 'none'
        const ov = document.querySelector('.v--overlay'); if (ov) ov.style.display = 'none'
      }
      await sleep(400)
    }

    reviewBtn.scrollIntoView({ behavior: 'instant', block: 'center' })
    await sleep(rand(500, 1000))
    reviewBtn.click()

    const modal = await waitForModal(7000)
    if (!modal) return { success: false, error: '모달 안 열림' }
    await sleep(rand(500, 1000))

    // 별점 5점
    let starBtns = []
    let sw = 0
    while (sw < 4000) {
      starBtns = Array.from(modal.querySelectorAll('button')).filter(b => /^[1-5]점$/.test(b.textContent.trim()))
      if (starBtns.length > 0) break
      await sleep(300); sw += 300
    }
    const star5 = starBtns.find(b => b.textContent.trim() === '5점')
    if (!star5) {
      reviewBtn.dataset.sambaReviewed = 'true'
      return { success: false, error: '별점 버튼 없음' }
    }
    star5.click()
    await sleep(500)

    // 사이즈/색상 라디오 (중간값)
    for (const box of modal.querySelectorAll('.review-create__evaluation__box')) {
      const labels = box.querySelectorAll('label')
      if (labels.length >= 3) { labels[1].click(); await sleep(rand(200, 400)) }
      else if (labels.length === 2) { labels[0].click(); await sleep(rand(200, 400)) }
    }
    await sleep(rand(300, 600))

    const ta = modal.querySelector('textarea')
    if (!ta) {
      reviewBtn.dataset.sambaReviewed = 'true'
      return { success: false, error: 'textarea 없음' }
    }
    const text = pickText(cat)
    ta.focus(); await sleep(200)
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set
    if (setter) setter.call(ta, text)
    else ta.value = text
    ta.dispatchEvent(new Event('input', { bubbles: true }))
    ta.dispatchEvent(new Event('change', { bubbles: true }))
    await sleep(400)
    if (ta.value.length < 20) {
      ta.select(); document.execCommand('insertText', false, text)
      ta.dispatchEvent(new Event('input', { bubbles: true }))
      await sleep(300)
    }

    // "다음에 할게요" 체크박스 (포토 첨부 패널티 회피)
    const skipLabel = modal.querySelector('label[for="checkNotUse"]')
    const skipCb = modal.querySelector('#checkNotUse')
    if (skipLabel && !skipCb?.checked) {
      skipLabel.click()
      await sleep(rand(300, 500))
    }

    // 제출
    const submit = Array.from(modal.querySelectorAll('button')).find(b => b.textContent.trim() === '리뷰 등록하기')
    if (!submit) {
      reviewBtn.dataset.sambaReviewed = 'true'
      return { success: false, error: '등록 버튼 없음' }
    }
    let we = 0
    while (submit.disabled && we < 5000) {
      await sleep(200); we += 200
      if (we === 2000 && submit.disabled && skipLabel) {
        if (skipCb?.checked) skipLabel.click()
        skipLabel.click()
      }
    }
    submit.click()
    const closed = await waitForModalClose(modal, 8000)
    reviewBtn.dataset.sambaReviewed = 'true'
    return { success: closed, error: closed ? null : '제출 후 모달 안 닫힘' }
  }

  async function loadMore() {
    const btn = document.querySelector('button.btnReadmore')
    if (btn && btn.offsetHeight > 0) { btn.click(); return { ok: true } }
    return { ok: false }
  }

  window.__sambaLotteonReviewListener = (msg, _s, sr) => {
    const a = msg && msg.action
    if (!['samba_review_ping', 'samba_review_processOne', 'samba_review_loadMore', 'samba_review_getPageInfo'].includes(a)) return
    ;(async () => {
      try {
        if (a === 'samba_review_ping') sr({ loaded: true })
        else if (a === 'samba_review_getPageInfo') sr({ itemCount: getReviewableButtons().length })
        else if (a === 'samba_review_processOne') sr(await processOne())
        else if (a === 'samba_review_loadMore') sr(await loadMore())
      } catch (e) { sr({ success: false, error: e.message }) }
    })()
    return true
  }
  chrome.runtime.onMessage.addListener(window.__sambaLotteonReviewListener)

  console.log('[삼바-롯데리뷰] 로드')
})()

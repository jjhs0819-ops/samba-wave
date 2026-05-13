/**
 * content-tracking-musinsa.js
 *
 * 무신사 배송조회 페이지에서 택배사명 + 송장번호 추출 후 background로 전송.
 * URL 패턴: https://www.musinsa.com/order-service/my/delivery/trace?ord_no={주문번호}
 *
 * DOM (overlink-invoice-extension content-musinsa.js 검증 셀렉터):
 *   택배사:    p.company-name (부모: .delivery-detail-tracking__category)
 *   송장번호:  button.tracking-number
 *
 * 캡챠 감지: document.title 또는 body에 "보안 인증" 텍스트가 있으면 success:false
 *           + error="captcha" 로 백엔드에 보고 → 재시도 백오프
 */
;(() => {
  'use strict'

  const MAX_WAIT_MS = 15000
  const POLL_INTERVAL = 300

  // 원주문 취소 감지 — "취소완료/취소처리완료/구매취소완료/주문이 취소" 같은 완결형 문구만
  // (단순 "주문취소" / "취소요청"은 신청 단계라 제외 — 오탐 방지)
  function isOrderCancelled() {
    try {
      const text = (document.body?.innerText || '').slice(0, 8000)
      return /(취소완료|취소처리완료|구매취소완료|주문이\s*취소|취소된\s*주문)/.test(text)
    } catch { return false }
  }

  function isCaptcha() {
    const title = (document.title || '').toLowerCase()
    if (title.includes('보안 인증') || title.includes('captcha')) return true
    const body = (document.body?.innerText || '').slice(0, 500)
    if (body.includes('보안 인증')) return true
    return false
  }

  async function waitFor(selector, timeoutMs) {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      const el = document.querySelector(selector)
      if (el && (el.textContent || '').trim()) return el
      await new Promise((r) => setTimeout(r, POLL_INTERVAL))
    }
    return null
  }

  async function scrape() {
    if (isCaptcha()) {
      return { success: false, error: 'captcha' }
    }
    if (isOrderCancelled()) {
      return { success: false, cancelled: true, error: 'order_cancelled' }
    }

    // 택배사 셀렉터 (overlink 검증)
    const courierEl = await waitFor('p.company-name', MAX_WAIT_MS)
    if (!courierEl) {
      return { success: false, error: '택배사 DOM 미로드 (미발송 가능)' }
    }
    const courierName = courierEl.textContent.trim()

    const trackingEl = document.querySelector('button.tracking-number')
    const trackingNumber = (trackingEl?.textContent || '').trim()

    if (!trackingNumber) {
      return {
        success: false,
        error: 'no_tracking: 송장번호 없음 (아직 미발송)',
        courierName,
      }
    }

    const params = new URLSearchParams(location.search)
    const ordNo = params.get('ord_no') || ''
    return {
      success: true,
      courierName,
      trackingNumber,
      ordNo,
    }
  }

  function send(requestId, payload) {
    try {
      chrome.runtime.sendMessage({
        type: 'TRACKING_RESULT',
        requestId,
        ...payload,
      })
    } catch (e) {
      console.warn('[송장-무신사] sendMessage 실패:', e)
    }
  }

  // background가 TRACKING_REQUEST 메시지로 requestId를 알려줌
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'TRACKING_REQUEST') {
      sendResponse({ ack: true })
      scrape()
        .then((res) => send(msg.requestId, res))
        .catch((err) =>
          send(msg.requestId, {
            success: false,
            error: String(err?.message || err),
          })
        )
      return true
    }
    return false
  })
})()

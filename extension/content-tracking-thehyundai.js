/**
 * content-tracking-thehyundai.js
 *
 * 더현대(현대Hi) 주문상세에서 송장 추출.
 * URL: https://hi.thehyundai.com/mypage/order/detail?ordNo={주문번호}
 *
 * 흐름 (웨일 CDP 실측 2026-06-05):
 *   1) 주문상세 페이지의 "배송조회" 버튼 클릭 → 같은 페이지 모달(레이어) 오픈
 *   2) 모달 안에 goodsflow 배송추적 iframe 삽입됨 (cross-origin → contentDocument 못 읽음)
 *   3) iframe.src 경로에 택배사코드/송장번호가 박혀 있음:
 *        https://b2c.goodsflow.com/zkm/v1/whereis/{vendor}/{courierCode}/{trackingNumber}
 *        예) .../whereis/thehyundai/cjgls/302914274915  → CJ대한통운 / 302914274915
 *
 * 주의:
 *   - 클래스명은 CSS-module 해시(예: Button_root__xi998, DeliveryStatus_iframe__s80UE)라
 *     빌드마다 바뀜 → 클래스 셀렉터 금지.
 *   - 배송조회 버튼: textContent === '배송조회'
 *   - iframe: src 에 'goodsflow.com' && '/whereis/' 포함
 *   - 미발송 주문은 배송조회 버튼이 없거나 클릭해도 iframe 미생성 → no_tracking(정상)
 */
;(() => {
  'use strict'

  const MAX_WAIT_MS = 20000
  const POLL_INTERVAL = 300

  // goodsflow 택배사코드 → 한글 택배사명 매핑.
  // cjgls 만 실측 확인(2026-06-05). 그 외 코드(한진/롯데/우체국/로젠 등)는
  // 해당 택배사로 배송된 주문을 실측해 추가할 것 — 추측으로 넣지 말 것.
  // 미매핑 코드는 raw 코드를 그대로 전송(백엔드 normalize_courier_name 이 보조 처리).
  const GOODSFLOW_COURIER = {
    cjgls: 'CJ대한통운',
  }

  function isOrderCancelled() {
    try {
      const text = (document.body?.innerText || '').slice(0, 8000)
      return /(취소완료|취소처리완료|구매취소완료|주문이\s*취소|취소된\s*주문)/.test(text)
    } catch {
      return false
    }
  }

  // 배송조회 버튼 탐색 — textContent 정확 매칭(공백 제거 후)
  function findTraceButton() {
    const els = Array.from(document.querySelectorAll('button, a'))
    return els.find((e) => {
      const t = (e.textContent || '').replace(/\s+/g, '')
      return t === '배송조회'
    })
  }

  // goodsflow 배송추적 iframe 탐색
  function findGoodsflowIframe() {
    const ifrs = Array.from(document.querySelectorAll('iframe'))
    return ifrs.find((f) => {
      const src = f.src || ''
      return src.includes('goodsflow.com') && src.includes('/whereis/')
    })
  }

  // iframe src 에서 택배사코드/송장번호 파싱
  function parseGoodsflowSrc(src) {
    // .../whereis/{vendor}/{courierCode}/{trackingNumber}
    const m = (src || '').match(/\/whereis\/[^/]+\/([^/?#]+)\/([^/?#]+)/)
    if (!m) return null
    const courierCode = (m[1] || '').toLowerCase()
    const trackingNumber = (m[2] || '').trim()
    const courierName = GOODSFLOW_COURIER[courierCode] || courierCode.toUpperCase()
    return { courierName, trackingNumber, courierCode }
  }

  async function waitFor(fn, timeoutMs) {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      const v = fn()
      if (v) return v
      await new Promise((r) => setTimeout(r, POLL_INTERVAL))
    }
    return null
  }

  // 배송조회 버튼 클릭 — React onClick 대응.
  // btn.click() 우선(무신사 등 검증된 패턴), 추가로 pointer/mouse 이벤트 시퀀스 폴백.
  function clickTraceButton(btn) {
    try {
      btn.click()
    } catch {}
    try {
      const r = btn.getBoundingClientRect()
      const opt = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: r.x + r.width / 2,
        clientY: r.y + r.height / 2,
      }
      ;['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((type) => {
        const Ctor = type.startsWith('pointer') ? PointerEvent : MouseEvent
        btn.dispatchEvent(new Ctor(type, opt))
      })
    } catch {}
  }

  async function scrape() {
    if (isOrderCancelled()) {
      return { success: false, cancelled: true, error: 'order_cancelled' }
    }

    // 페이지 hydration 대기 후 배송조회 버튼 탐색
    const btn = await waitFor(findTraceButton, MAX_WAIT_MS)
    if (!btn) {
      // 배송조회 버튼 없음 = 아직 발송 전(배송대기/상품준비) 단계
      return { success: false, error: 'no_tracking: 배송조회 버튼 없음 (미발송)' }
    }

    clickTraceButton(btn)

    // 모달 내 goodsflow iframe 생성 대기
    const iframe = await waitFor(findGoodsflowIframe, MAX_WAIT_MS)
    if (!iframe) {
      return { success: false, error: 'no_tracking: 배송추적 iframe 미생성 (미발송 가능)' }
    }

    const parsed = parseGoodsflowSrc(iframe.src)
    if (!parsed) {
      return { success: false, error: `parse_fail: iframe src 파싱 실패 (${iframe.src || ''})` }
    }
    const m = (parsed.trackingNumber || '').match(/\d{6,}/)
    const trackingNumber = m ? m[0] : ''
    if (!trackingNumber) {
      return {
        success: false,
        error: 'no_tracking: 송장번호 미표시 (미발송)',
        courierName: parsed.courierName,
      }
    }
    return { success: true, courierName: parsed.courierName, trackingNumber }
  }

  function send(requestId, payload) {
    try {
      chrome.runtime.sendMessage({ type: 'TRACKING_RESULT', requestId, ...payload })
    } catch (e) {
      console.warn('[송장-더현대] sendMessage 실패:', e)
    }
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'TRACKING_REQUEST') {
      sendResponse({ ack: true })
      scrape()
        .then((r) => send(msg.requestId, r))
        .catch((err) => send(msg.requestId, { success: false, error: String(err?.message || err) }))
      return true
    }
    return false
  })
})()

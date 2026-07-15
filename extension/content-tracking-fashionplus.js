/**
 * content-tracking-fashionplus.js
 *
 * 패션플러스 주문상세에서 송장 추출.
 * 패션플러스는 배송추적에 goodsflow(굿스플로) trace 를 쓰며, 주문상세 페이지의
 * 배송조회 영역에 택배사/송장번호가 노출되는 경우도 있다.
 * → ①DOM 텍스트 정규식 ②goodsflow/배송조회 링크 파라미터 순으로 시도.
 * URL: https://www.fashionplus.co.kr/mypage/order/detail/{주문번호}
 *
 * [실측 로깅] 실제 detail 페이지 DOM 구조를 원격(윈도우PC Chrome)에서 확인할 수 없으므로,
 * 송장 미검출 시 배송 관련 영역의 텍스트/링크 발췌를 error 에 실어 백엔드 DB(last_error)로 보낸다.
 * 첫 라이브 실행 후 그 값으로 셀렉터를 확정한다. (확정되면 발췌 로깅은 축소)
 */
;(() => {
  'use strict'

  function isOrderCancelled() {
    try {
      const text = (document.body?.innerText || '').slice(0, 8000)
      return /(취소완료|취소처리완료|구매취소완료|주문이\s*취소|취소된\s*주문)/.test(text)
    } catch { return false }
  }

  async function waitFor(selector, timeoutMs = 8000) {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      const el = document.querySelector(selector)
      if (el) return el
      await new Promise(r => setTimeout(r, 300))
    }
    return null
  }

  // 택배사 정규화 — 흔한 표기를 표준명으로.
  const COURIER_PATTERNS = [
    { re: /(CJ\s*대한통운|대한통운|CJ택배)/i, name: 'CJ대한통운' },
    { re: /(한진택배|한진)/, name: '한진택배' },
    { re: /(롯데택배|롯데글로벌|현대택배)/, name: '롯데택배' },
    { re: /(우체국택배|우체국)/, name: '우체국택배' },
    { re: /(로젠택배|로젠)/, name: '로젠택배' },
    { re: /(GS\s*Postbox|GS편의점|GS25)/i, name: 'GS Postbox 택배' },
    { re: /(CU\s*편의점|CU택배|CVSnet|편의점택배)/i, name: 'CU 편의점택배' },
    { re: /(경동택배|경동)/, name: '경동택배' },
    { re: /(대신택배|대신)/, name: '대신택배' },
    { re: /(일양로지스|일양)/, name: '일양로지스' },
    { re: /(합동택배|합동)/, name: '합동택배' },
  ]

  function detectCourier(text) {
    for (const p of COURIER_PATTERNS) {
      if (p.re.test(text)) return p.name
    }
    // "택배사 : XXX" 라벨 뒤 임의 표기 폴백
    const m = text.match(/택배(?:사|회사)?\s*[:：]?\s*([가-힣A-Za-z0-9()]+(?:택배|로지스|통운|Postbox))/i)
    return m?.[1]?.trim() || ''
  }

  // goodsflow / 배송조회 링크에서 송장번호 파라미터 추출.
  // 흔한 파라미터명: invoiceNo, inv_no, wblNo, trackingNo, tno, no
  function trackingFromLinks() {
    const links = Array.from(document.querySelectorAll('a[href], area[href]'))
    for (const a of links) {
      const href = a.getAttribute('href') || ''
      if (!/goodsflow|trace|delivery|tracking|배송조회|dvry|wbl|invoice/i.test(href)) continue
      const m = href.match(/(?:invoiceNo|inv_?no|wblNo|trackingNo|tno|carrierTrackNo)=([0-9-]{8,})/i)
      if (m) return m[1].replace(/-/g, '')
    }
    // onclick 핸들러에 송장이 인자로 박힌 케이스
    const clickers = Array.from(document.querySelectorAll('[onclick]'))
    for (const el of clickers) {
      const oc = el.getAttribute('onclick') || ''
      if (!/goodsflow|trace|delivery|배송|invoice|wbl/i.test(oc)) continue
      const m = oc.match(/['"]?(\d{9,13})['"]?/)
      if (m) return m[1]
    }
    return ''
  }

  // [실측 모드 전용] 백엔드 tracking_sync/service.py 의 결과 분기는 error 문자열에
  // 'no_tracking'/'미발송'/'배송대기'/'로그인 실패'/'계정불일치' 등이 있으면 last_error 를
  // 표준문구로 덮어쓴다 → 실측 발췌가 사라진다. 발췌를 DB(last_error)에 그대로 보존하려면
  // 이 토큰들을 마스킹해 어느 분기에도 안 걸리게 하고 else(STATUS_FAILED) 로 흘려보낸다.
  // 구조 확정 후 이 마스킹/실측 로깅은 제거하고 정상 no_tracking 분류로 원복한다.
  function maskBackendKeywords(s) {
    return String(s || '')
      .replace(/no_tracking/gi, 'no-trk')
      .replace(/wrong_account|not_my_order|account_mismatch/gi, 'acc-x')
      .replace(/미발송/g, '미_발송')
      .replace(/배송대기/g, '배송_대기')
      .replace(/로그인 실패/g, '로그인_실패')
      .replace(/계정불일치/g, '계정_불일치')
      .replace(/계정 잠금/g, '계정_잠금')
      .replace(/captcha/gi, 'cap-x')
      .replace(/timeout/gi, 't-out')
  }

  // 배송/송장 위치를 특정하기 위한 실측 발췌. 광고 배너("무료배송/쿠폰")는 제외하고
  // ①현재 URL/제목 ②배송조회·goodsflow 버튼/링크(href·onclick) ③정확한 배송정보 라벨 영역
  // 순으로 담는다. (송장은 대개 배송조회 버튼/goodsflow trace 링크에 파라미터로 존재)
  function deliveryDebugSnippet() {
    try {
      const parts = []
      parts.push(`URL=${location.pathname}`)
      const title = (document.title || '').replace(/\s+/g, ' ').trim()
      if (title) parts.push(`T=${title.slice(0, 30)}`)

      // ① 배송조회/goodsflow/trace 버튼·링크 — href/onclick 원문(송장 파라미터가 여기 있을 확률 높음)
      const btnKw = /송장|운송장|배송조회|배송추적|goodsflow|good's?flow|trace|delivery|tracking|invoice|wbl|dvry/i
      const btns = Array.from(document.querySelectorAll('a[href], [onclick], button'))
        .map(a => {
          const h = a.getAttribute('href') || a.getAttribute('onclick') || ''
          const t = (a.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 16)
          return { h, t }
        })
        .filter(x => btnKw.test(x.h) || btnKw.test(x.t))
        .slice(0, 5)
      if (btns.length) {
        parts.push('BTN=' + btns.map(x => `${x.t}[${x.h.slice(0, 70)}]`).join(' ; '))
      }

      // ② 정확한 배송정보 라벨 영역 (광고 배너 제외)
      const labelKw = /운송장|송장번호|택배사|배송조회|배송상태|배송현황|출고|배송중|배송완료|수령|택배/
      const adKw = /쿠폰|무료배송|할인|적립|이벤트|좋아요|추가하기/
      const els = Array.from(document.querySelectorAll('dl, table, tr, li, div, section, p, span'))
        .filter(el => {
          const t = (el.innerText || '').trim()
          return t && t.length < 200 && labelKw.test(t) && !adKw.test(t)
        })
      const seen = new Set()
      for (const el of els) {
        const t = (el.innerText || '').replace(/\s+/g, ' ').trim()
        if (t && !seen.has(t)) { seen.add(t); parts.push(t) }
        if (parts.length >= 8) break
      }

      // ③ 페이지 내 9~13자리 숫자(송장 후보) 존재 여부 — 파싱 힌트
      const nums = (document.body?.innerText || '').match(/\b\d{9,13}\b/g)
      if (nums && nums.length) parts.push('NUMS=' + Array.from(new Set(nums)).slice(0, 4).join(','))

      return parts.join(' | ').slice(0, 500)
    } catch (e) {
      return `snippet_error:${String(e?.message || e).slice(0, 80)}`
    }
  }

  async function scrape() {
    if (isOrderCancelled()) {
      return { success: false, cancelled: true, error: 'order_cancelled' }
    }
    await waitFor('body', 5000)
    // 배송조회 영역이 lazy 렌더링될 수 있어 잠시 대기
    await new Promise(r => setTimeout(r, 1500))

    const text = document.body?.innerText || ''

    // ① 텍스트에서 송장번호 (라벨 다양성 대응)
    const trackingMatch =
      text.match(/(?:송장|운송장)(?:번호)?\s*[:：]?\s*([0-9][0-9-]{7,})/) ||
      text.match(/(?:invoice|tracking)\s*(?:no)?\s*[:：]?\s*([0-9][0-9-]{7,})/i)
    let trackingNumber = trackingMatch?.[1]?.replace(/-/g, '').trim() || ''
    let courierName = detectCourier(text)

    // ② 링크/onclick 파라미터에서 보조 추출
    if (!trackingNumber) {
      trackingNumber = trackingFromLinks()
    }

    if (!trackingNumber) {
      // [실측 모드] 배송영역 발췌를 error 에 실어 DB(last_error)로 보냄 → 실제 구조 확정용.
      // 접두사/발췌 모두 백엔드 분기 키워드를 회피(마스킹)해 else→STATUS_FAILED 로 보존시킨다.
      // (구조 확정 후 정상 'no_tracking' 접두사 + 마스킹 제거로 원복)
      const snippet = maskBackendKeywords(deliveryDebugSnippet())
      return {
        success: false,
        error: `FP_UNRESOLVED 패션플러스 송장 미검출 [실측] ${snippet}`,
      }
    }
    return { success: true, courierName, trackingNumber }
  }

  function send(requestId, payload) {
    try { chrome.runtime.sendMessage({ type: 'TRACKING_RESULT', requestId, ...payload }) } catch {}
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === 'TRACKING_REQUEST') {
      sendResponse({ ack: true })
      scrape().then(r => send(msg.requestId, r))
        .catch(err => send(msg.requestId, { success: false, error: String(err?.message || err) }))
      return true
    }
    return false
  })
})()

// content-collect-abcmart.js — 일본 ABC-MART / 그랜드스테이지 상품 DOM 수집 [2026-08-30]
// 서버 urllib 수집이 봇차단(一時的なサーバー制限)당해, 실브라우저(확장앱)에서 DOM 을 읽어
// 백엔드로 보낸다. background 가 상품 탭을 열고 이 스크립트에 수집 메시지를 보낸다.
// 반환 구조는 크림 리셀 수집 표준: {code(품번), color, name, price, sizes[], image, siteProductId}.
(() => {
  'use strict'
  const LOG = '[ABC수집]'

  // <th>/<dt>/<td> 라벨의 다음 셀 텍스트
  function labelVal(label) {
    const cells = [...document.querySelectorAll('th, dt, td')]
    const el = cells.find((e) => (e.textContent || '').trim() === label)
    return el && el.nextElementSibling ? (el.nextElementSibling.textContent || '').trim() : ''
  }

  function parsePrice() {
    // 상세가 ¥ 표기 — 할인가(price_sale) 우선, 없으면 첫 ¥숫자
    const scope = document.querySelector('[class*="price"]') || document.body
    const m = (scope.textContent || '').match(/[¥￥]\s*([0-9,]+)/)
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : 0
  }

  function parseSizes() {
    // 사이즈 행: "24.5cm" + (완売/× = 품절) / (○·カートへ入れる = 재고).
    // 구조 무관 — cm 텍스트를 가진 최말단 요소 기준으로 그 행의 재고 여부 판정.
    const out = []
    const seen = new Set()
    const nodes = [...document.querySelectorAll('*')].filter(
      (e) => e.children.length === 0 && /^\s*\d{2}(?:\.\d)?\s*cm\s*$/.test(e.textContent || ''),
    )
    for (const n of nodes) {
      const cm = (n.textContent || '').trim().replace(/\s*cm\s*$/, '')
      if (seen.has(cm)) continue
      // 행 컨테이너(상위 2~3단계) 텍스트로 재고 판정
      let row = n
      for (let i = 0; i < 3 && row.parentElement; i++) row = row.parentElement
      const t = row.textContent || ''
      const soldout = /完売|品切|再入荷|×/.test(t)
      const instock = /カートへ入れる|○|在庫/.test(t)
      if (!soldout && !instock) continue
      seen.add(cm)
      out.push({ name: cm + 'cm', stock: soldout ? 0 : 1 })
    }
    return out
  }

  function parseImage() {
    const og = document.querySelector('meta[property="og:image"]')
    let src = og ? og.content : ''
    // 브라우저 로드 가능한 호스트로 정규화(img. 접두 필수)
    const m = String(src).match(/apim\.abc-mart\.biz(\/img\/\d+\/\d+\/\d+\.jpg)/)
    if (m) src = 'https://img.apim.abc-mart.biz' + m[1]
    return src ? [src] : []
  }

  function collect() {
    const code = labelVal('メーカー品番') // 제조사 품번 = 크림 매칭 키
    const color = labelVal('カラー')
    const brand = labelVal('ブランド')
    const name = labelVal('商品名') || document.title
    // 商品コード = ABC 자체 상품번호(URL g{13자리}) = site_product_id
    let siteProductId = labelVal('商品コード')
    if (!siteProductId) {
      const mu = location.pathname.match(/\/g(\d{10,})\//)
      siteProductId = mu ? mu[1] : ''
    }
    return {
      site: location.host.includes('gs.abc-mart') ? 'GRANDSTAGE_JP' : 'ABCMART_JP',
      siteProductId,
      code,
      color,
      brand,
      name,
      price: parsePrice(),
      sizes: parseSizes(),
      image: parseImage(),
      sourceUrl: location.href.split('?')[0],
    }
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === 'ABC_COLLECT') {
      try {
        const data = collect()
        console.log(`${LOG} ${data.code} (${data.name}) 사이즈 ${data.sizes.length}개`)
        sendResponse({ success: !!data.code, data })
      } catch (e) {
        sendResponse({ success: false, message: e.message })
      }
      return true
    }
  })

  // 페이지 로드 시 자동 수집 → background 릴레이(백엔드 적재).
  // 사용자가 ABC 상품을 열기만 하면 수집된다(봇차단 없이 실브라우저 DOM).
  setTimeout(() => {
    try {
      const data = collect()
      if (data.code && (data.sizes.length || data.price > 0)) {
        chrome.runtime.sendMessage({ type: 'JP_INGEST', data }, () => void chrome.runtime.lastError)
      }
    } catch (e) {
      /* ignore */
    }
  }, 1800)
})()

// content-collect-atmos.js — atmos-tokyo.com 상품 DOM 수집 [2026-08-30]
// atmos 는 Akamai 봇차단이라 서버 fetch/쿠키가 短命. 실브라우저(확장앱)에서 렌더된 DOM 을
// 읽어 백엔드로 보낸다. sku·가격은 JSON-LD, 사이즈·재고는 DOM(사이즈 버튼)에서 뽑는다.
(() => {
  'use strict'
  const LOG = '[atmos수집]'

  function jsonLdProduct() {
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent || '{}')
        for (const b of Array.isArray(d) ? d : [d]) {
          if (b && b['@type'] === 'Product') return b
        }
      } catch (e) {
        /* skip */
      }
    }
    return null
  }

  function parseSizes() {
    // 사이즈 버튼/라벨 — "25.5cm ○"(재고) / "24cm ×·完売"(품절). 구조 무관 최말단 기준.
    const out = []
    const seen = new Set()
    const nodes = [...document.querySelectorAll('*')].filter(
      (e) => e.children.length === 0 && /^\s*\d{2}(?:\.\d)?\s*cm\s*$/.test(e.textContent || ''),
    )
    for (const n of nodes) {
      const cm = (n.textContent || '').trim().replace(/\s*cm\s*$/, '')
      if (seen.has(cm)) continue
      let row = n
      for (let i = 0; i < 3 && row.parentElement; i++) row = row.parentElement
      const t = row.textContent || ''
      const soldout = /完売|品切|再入荷|×|SOLD/i.test(t)
      const instock = /カートに入れる|カートへ|○|在庫|ADD/i.test(t)
      if (!soldout && !instock) continue
      seen.add(cm)
      out.push({ name: cm + 'cm', stock: soldout ? 0 : 1 })
    }
    return out
  }

  function collect() {
    const p = jsonLdProduct() || {}
    let price = 0
    const of = Array.isArray(p.offers) ? p.offers[0] : p.offers
    if (of && of.price) price = parseInt(String(of.price).replace(/[^0-9]/g, ''), 10) || 0
    const imgs = []
    const og = document.querySelector('meta[property="og:image"]')
    if (p.image) imgs.push(...(Array.isArray(p.image) ? p.image : [p.image]))
    else if (og && og.content) imgs.push(og.content)
    // color_cd — item-color 라디오 값(백엔드 사이즈 API 재조회용, 참고)
    const colEl = document.querySelector('[name="item-color"]:checked, [name="item-color"]')
    return {
      site: 'ATMOS',
      siteProductId: String(p.sku || ''),
      code: String(p.sku || ''),
      color: colEl ? colEl.value : '',
      brand: String(p.brand && (p.brand.name || p.brand) ? p.brand.name || p.brand : ''),
      name: String(p.name || document.title),
      price,
      sizes: parseSizes(),
      image: imgs.slice(0, 1),
      sourceUrl: location.href.split('?')[0],
    }
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.type === 'ATMOS_COLLECT') {
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

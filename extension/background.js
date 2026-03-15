// 삼바웨이브 쿠키 연동 - 백그라운드 서비스 워커

const PROXY_URL = 'http://localhost:3001'

// ==================== 무신사 쿠키 ====================

let capturedCookie = ''
let capturedAt = 0

let syncTimer = null
function scheduleCookieSync() {
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(async () => {
    syncTimer = null
    if (!capturedCookie) return
    try {
      await sendCookiesToProxy(capturedCookie)
      console.log('[자동동기화] 무신사 쿠키 프록시 전송 완료')
    } catch (e) {
      console.log('[자동동기화] 프록시 미실행 (무시)')
    }
  }, 3000)
}

// ==================== KREAM 쿠키 ====================

let kreamCookie = ''
let kreamCapturedAt = 0

let kreamSyncTimer = null
function scheduleKreamCookieSync() {
  if (kreamSyncTimer) clearTimeout(kreamSyncTimer)
  kreamSyncTimer = setTimeout(async () => {
    kreamSyncTimer = null
    if (!kreamCookie) return
    try {
      await sendKreamCookiesToProxy(kreamCookie)
      console.log('[자동동기화] KREAM 쿠키 프록시 전송 완료')
    } catch (e) {
      console.log('[자동동기화] 프록시 미실행 (무시)')
    }
  }, 3000)
}

// Service Worker 시작 시 저장된 쿠키 복원
chrome.storage.local.get(['capturedCookie', 'capturedAt', 'kreamCookie', 'kreamCapturedAt']).then(async data => {
  // 무신사
  if (data.capturedCookie) {
    capturedCookie = data.capturedCookie
    capturedAt = data.capturedAt || 0
    console.log(`[복원] 무신사 쿠키 복원: ${capturedCookie.split(';').length}개`)
    try { await sendCookiesToProxy(capturedCookie) } catch {}
  }
  // KREAM
  if (data.kreamCookie) {
    kreamCookie = data.kreamCookie
    kreamCapturedAt = data.kreamCapturedAt || 0
    console.log(`[복원] KREAM 쿠키 복원: ${kreamCookie.split(';').length}개`)
    try { await sendKreamCookiesToProxy(kreamCookie) } catch {}
  }
})

// 무신사 webRequest 캡처
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const cookieHeader = details.requestHeaders?.find(
      h => h.name.toLowerCase() === 'cookie'
    )
    if (cookieHeader?.value && cookieHeader.value.length > capturedCookie.length) {
      capturedCookie = cookieHeader.value
      capturedAt = Date.now()
      chrome.storage.local.set({ capturedCookie, capturedAt })
      console.log(`[캡처] 무신사 쿠키 ${capturedCookie.split(';').length}개`)
      scheduleCookieSync()
    }
  },
  { urls: ['https://*.musinsa.com/*'] },
  ['requestHeaders', 'extraHeaders']
)

// KREAM webRequest 캡처
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const cookieHeader = details.requestHeaders?.find(
      h => h.name.toLowerCase() === 'cookie'
    )
    if (cookieHeader?.value && cookieHeader.value.length > kreamCookie.length) {
      kreamCookie = cookieHeader.value
      kreamCapturedAt = Date.now()
      chrome.storage.local.set({ kreamCookie, kreamCapturedAt })
      console.log(`[캡처] KREAM 쿠키 ${kreamCookie.split(';').length}개`)
      scheduleKreamCookieSync()
    }
  },
  { urls: ['https://*.kream.co.kr/*'] },
  ['requestHeaders', 'extraHeaders']
)

// ==================== 프록시 전송 함수 ====================

async function sendCookiesToProxy(cookieStr) {
  const res = await fetch(`${PROXY_URL}/api/musinsa/set-cookie`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  return res.json()
}

async function sendKreamCookiesToProxy(cookieStr) {
  const res = await fetch(`${PROXY_URL}/api/kream/set-cookie`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  return res.json()
}

// ==================== 무신사 쿠키 조회 ====================

async function getMusinsaCookies() {
  if (!capturedCookie) {
    const data = await chrome.storage.local.get(['capturedCookie', 'capturedAt'])
    if (data.capturedCookie) {
      capturedCookie = data.capturedCookie
      capturedAt = data.capturedAt || 0
    }
  }

  if (capturedCookie) {
    const count = capturedCookie.split(';').length
    const age = Math.round((Date.now() - capturedAt) / 1000)
    return {
      cookies: Array.from({ length: count }, (_, i) => ({ domain: '.musinsa.com', name: `c${i}`, value: '' })),
      cookieStr: capturedCookie,
      isLoggedIn: true,
      cookieNames: [`✅ webRequest 캡처: ${count}개 (${age}초 전)`],
    }
  }

  const all = []
  const seen = new Set()
  for (const url of ['https://www.musinsa.com', 'https://member.one.musinsa.com']) {
    try {
      const cookies = await chrome.cookies.getAll({ url })
      for (const c of cookies) {
        const key = `${c.domain}|${c.name}`
        if (!seen.has(key)) { seen.add(key); all.push(c) }
      }
    } catch {}
  }
  const cookies = all.filter(c => c.value && /^[\x21-\x7E]{1,8000}$/.test(c.value))
  return {
    cookies: all,
    cookieStr: cookies.map(c => `${c.name}=${c.value}`).join('; '),
    isLoggedIn: all.length > 0,
    cookieNames: all.map(c => `${c.domain}:${c.name}`),
  }
}

// ==================== KREAM 수집 큐 폴링 ====================

// 1회성 수집 폴링 — job 있으면 true 반환
async function pollCollectOnce() {
  try {
    const res = await fetch(`${PROXY_URL}/api/kream/collect-queue`)
    const job = await res.json()
    if (job.hasJob) {
      console.log(`[KREAM] 수집 요청: ${job.url}`)
      await handleCollectJob(job)
      return true
    }
    return false
  } catch (e) {
    console.log('[KREAM] collect-queue 폴링 오류:', e.message)
    return false
  }
}

// 수집 작업 처리 — CDP(chrome.debugger) 진짜 클릭으로 옵션 수집
async function handleCollectJob(job) {
  let tabId = null
  try {
    // 1. 백그라운드 탭 생성 (같은 윈도우 → 로그인 세션 공유)
    const tab = await chrome.tabs.create({ url: job.url, active: false })
    tabId = tab.id

    await waitForTabLoad(tabId, 30000)
    await wait(3000) // Nuxt 하이드레이션 대기

    // 2. __NUXT__ 데이터 추출 (기존 로직 유지)
    let nuxtData = null
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => {
          if (!window.__NUXT__?.data) return null
          const data = window.__NUXT__.data
          for (const key of Object.keys(data)) {
            if (data[key]?.jsonLd) return { jsonLd: data[key].jsonLd, key }
          }
          return null
        }
      })
      nuxtData = results?.[0]?.result || null
      if (nuxtData) console.log(`[KREAM] __NUXT__ 추출 성공 (키: ${nuxtData.key})`)
    } catch (e) {
      console.log('[KREAM] __NUXT__ 추출 실패:', e.message)
    }

    // 3. ★ 탭 active 전환 + btn.click() 으로 구매하기 팝업 열기
    // 원인: Chrome 레벨에서 탭이 active여야만 KREAM 팝업이 열림
    // visibilityState JS 스푸핑만으로는 부족 — chrome.tabs.update(active:true) 필요
    let sizeOptions = []
    try {
      // active로 전환하여 Chrome 레벨 visibilityState visible 만들기
      await chrome.tabs.update(tabId, { active: true })
      await wait(500)

      const [clickResult] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => {
          // 구매하기 버튼 클릭
          const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.trim() === '구매하기')
          if (!btn) return false
          btn.click()
          return true
        }
      })
      const clicked = clickResult?.result
      if (clicked) {
        console.log('[KREAM] visibilityState 스푸핑 + 버튼 클릭 완료')
        await wait(1500) // 팝업 렌더링 대기

        // DOM에서 사이즈 옵션 읽기
        const [sizeResult] = await chrome.scripting.executeScript({
          target: { tabId },
          world: 'MAIN',
          func: () => {
            const items = document.querySelectorAll('.select_item')
            return Array.from(items).map(el => {
              const ps = el.querySelectorAll('p')
              return {
                name: ps[0]?.textContent?.trim() || '',
                priceText: ps[1]?.textContent?.trim() || ''
              }
            }).filter(o => o.name)
          }
        })
        const rawOptions = sizeResult?.result || []
        console.log(`[KREAM] .select_item 읽기: ${rawOptions.length}개`)

        sizeOptions = rawOptions.map(o => {
          // 가격 텍스트에 숫자가 있어야 재고 있음 ("구매입찰" 같은 텍스트는 재고 없음)
          const hasNumericPrice = /\d/.test(o.priceText)
          return {
            name: o.name,
            price: hasNumericPrice ? parseInt(o.priceText.replace(/[^0-9]/g, '')) : 0,
            stock: hasNumericPrice ? 1 : 0,
            kreamAsk: hasNumericPrice ? parseInt(o.priceText.replace(/[^0-9]/g, '')) : 0,
            kreamFastPrice: 0,
            kreamGeneralPrice: 0,
            kreamBid: 0,
            kreamLastSale: 0
          }
        })

        // 배송가격 수집은 별도 try/catch — 실패해도 sizeOptions는 유지
        try {
        // 재고 있는 사이즈별 빠른배송/일반배송 가격 수집
        for (let i = 0; i < sizeOptions.length; i++) {
          if (sizeOptions[i].stock === 0) continue

          // 1) 해당 .select_item 클릭
          await chrome.scripting.executeScript({
            target: { tabId }, world: 'MAIN',
            func: (idx) => document.querySelectorAll('.select_item')[idx]?.click(),
            args: [i]
          })
          await wait(1200)

          // 2) 배송옵션 바텀시트에서 빠른배송/일반배송 가격 읽기
          const [deliveryResult] = await chrome.scripting.executeScript({
            target: { tabId }, world: 'MAIN',
            func: () => {
              const sheet = document.querySelector(
                '.layer_bottom_sheet--open .bottomsheet__content > div:first-child'
              )
              if (!sheet) return null
              const result = { fast: 0, general: 0 }
              Array.from(sheet.children).forEach(section => {
                const pTexts = Array.from(section.querySelectorAll('p'))
                  .map(p => p.textContent.trim())
                if (pTexts.some(t => t.includes('일반배송'))) {
                  // 일반배송: 정확히 "숫자,원" 형태만 (~ 붙은 하자가격 제외)
                  const priceText = pTexts.find(t => /^\d[\d,]*원$/.test(t))
                  if (priceText) result.general = parseInt(priceText.replace(/[^0-9]/g, ''))
                }
                if (pTexts.some(t => t.includes('빠른배송'))) {
                  // 빠른배송: "숫자,원" 정확히 끝나야 정상 상품 (95점 하자는 "원~"으로 끝남)
                  // 추가로 "95점" 텍스트가 포함된 섹션 내 가격도 모두 제외
                  const has95 = pTexts.some(t => t.includes('95점'))
                  const priceText = pTexts.find(t => /^\d[\d,]*원$/.test(t))
                  if (priceText && !has95) {
                    result.fast = parseInt(priceText.replace(/[^0-9]/g, ''))
                  } else if (priceText && has95) {
                    // 95점과 함께 있지만 정상 가격도 있는 경우: 95점 이전 가격만 취득
                    const idx95 = pTexts.findIndex(t => t.includes('95점'))
                    const beforeIdx = pTexts.slice(0, idx95).findIndex(t => /^\d[\d,]*원$/.test(t))
                    if (beforeIdx !== -1) {
                      result.fast = parseInt(pTexts.slice(0, idx95)[beforeIdx].replace(/[^0-9]/g, ''))
                    }
                    // 95점 앞에 정상 가격 없으면 fast=0 (95점만 있는 사이즈)
                  }
                }
              })
              return result
            }
          })

          if (deliveryResult?.result) {
            sizeOptions[i].kreamFastPrice = deliveryResult.result.fast || 0
            sizeOptions[i].kreamGeneralPrice = deliveryResult.result.general || 0
          }

          // 3) 배송시트 닫기 → 사이즈 목록으로 복귀
          await chrome.scripting.executeScript({
            target: { tabId }, world: 'MAIN',
            func: () => {
              const sheet = document.querySelector('.layer_bottom_sheet--open')
              const closeBtn = sheet?.querySelector('[class*="close"]')
              if (closeBtn) closeBtn.click()
              else sheet?.querySelector('.bottomsheet__background')?.click()
            }
          })
          await wait(300)
        }
        console.log('[KREAM] 배송가격 수집 완료:',
          sizeOptions.filter(o => o.kreamGeneralPrice > 0).length + '개 일반배송, ' +
          sizeOptions.filter(o => o.kreamFastPrice > 0).length + '개 빠른배송')

        // 일반배송 가격이 있는 옵션은 원가(price)를 일반배송 가격으로 업데이트
        sizeOptions.forEach(o => {
          if (o.kreamGeneralPrice > 0) o.price = o.kreamGeneralPrice
        })
        } catch (deliveryErr) {
          console.log('[KREAM] 배송가격 수집 중 오류 (옵션은 유지):', deliveryErr.message)
        }
      } else {
        console.log('[KREAM] 구매하기 버튼 없음 — 옵션 수집 건너뜀')
      }
    } catch (e) {
      console.log('[KREAM] 옵션 수집 실패:', e.message)
    }

    // 4. content script로 기본 정보 수집 (사이즈는 이미 수집함)
    let response = null
    for (let attempt = 1; attempt <= 5; attempt++) {
      try {
        response = await chrome.tabs.sendMessage(tabId, {
          type: 'COLLECT_KREAM',
          collectSizes: false, // background에서 이미 수집
          nuxtData,
          preCollectedOptions: sizeOptions
        })
        console.log(`[KREAM] content script 응답 수신 (시도 ${attempt}회): success=${response?.success}, msg=${response?.message || '-'}`)
        break
      } catch (e) {
        console.log(`[KREAM] sendMessage 실패 (시도 ${attempt}/5): ${e.message}`)
        if (attempt < 5) await wait(1500)
      }
    }
    if (!response) throw new Error('content script 연결 실패 (5회 시도 초과)')

    // 5. 탭 닫기
    try { await chrome.tabs.remove(tabId) } catch {}

    if (response?.success) {
      const proxyImages = (response.data.images || [])
        .filter(Boolean)
        .map(img => `${PROXY_URL}/api/image-proxy?url=${encodeURIComponent(img)}`)

      const catParts = (response.data.category || '').split(/\s*>\s*/)
      const options = response.data.options || []
      // 재고있는 옵션의 일반배송 가격 우선, 없으면 kreamAsk로 최저가 산출
      const generalPrices = options
        .filter(o => o.stock > 0 && o.kreamGeneralPrice > 0)
        .map(o => o.kreamGeneralPrice)
      const askPrices = options
        .filter(o => o.stock > 0 && o.kreamAsk > 0)
        .map(o => o.kreamAsk)
      const validPrices = generalPrices.length > 0 ? generalPrices : askPrices
      const salePrice = validPrices.length > 0 ? Math.min(...validPrices) : (response.data.price || 0)

      const product = {
        id: `col_kream_${job.productId}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        sourceSite: 'KREAM',
        siteProductId: job.productId,
        sourceUrl: job.url,
        name: response.data.nameKo || response.data.name || '',   // 원 상품명 = 한글명
        nameKo: response.data.nameKo || '',
        nameEn: response.data.nameEn || response.data.name || '',
        brand: response.data.brand || '',
        styleCode: response.data.styleCode || '',
        category: response.data.category || '',
        category1: catParts[0] || '',
        category2: catParts[1] || '',
        category3: catParts[2] || '',
        category4: catParts[3] || '',
        images: proxyImages,
        detailImages: [],
        options,
        originalPrice: response.data.originalPrice || response.data.price || 0,
        salePrice,
        discountRate: 0,
        status: 'collected'
      }

      await fetch(`${PROXY_URL}/api/kream/collect-result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requestId: job.requestId, data: { success: true, product } })
      })
      console.log(`[KREAM] 수집 완료: ${response.data.name} (사이즈 ${options.length}개, 이미지 ${proxyImages.length}개)`)
    } else {
      await fetch(`${PROXY_URL}/api/kream/collect-result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requestId: job.requestId, data: { success: false, message: response?.message || '수집 실패' } })
      })
    }
  } catch (err) {
    console.error('[KREAM] 수집 오류:', err)
    if (tabId) {
      try { await chrome.tabs.remove(tabId) } catch {}
    }
    try {
      await fetch(`${PROXY_URL}/api/kream/collect-result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requestId: job.requestId, data: { success: false, message: err.message } })
      })
    } catch {}
  }
}

// 탭 로드 완료 대기
function waitForTabLoad(tabId, timeout) {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const check = () => {
      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError) return reject(new Error('탭 접근 실패'))
        if (tab.status === 'complete') return resolve()
        if (Date.now() - start > timeout) return reject(new Error('탭 로드 타임아웃'))
        setTimeout(check, 500)
      })
    }
    check()
  })
}

function wait(ms) {
  return new Promise(r => setTimeout(r, ms))
}

// ==================== KREAM 검색 큐 폴링 ====================

// 1회성 검색 폴링 — job 있으면 true 반환
async function pollSearchOnce() {
  try {
    const res = await fetch(`${PROXY_URL}/api/kream/search-queue`)
    const job = await res.json()
    if (job.hasJob) {
      console.log(`[KREAM] 검색 요청: "${job.keyword}"`)
      await handleSearchJob(job)
      return true
    }
    return false
  } catch (e) {
    console.log('[KREAM] search-queue 폴링 오류:', e.message)
    return false
  }
}

// 검색 작업 처리 — 탭 열고 → DOM에서 상품 목록 추출 → 결과 proxy에 반환
async function handleSearchJob(job) {
  let tabId = null
  try {
    // 백그라운드 탭: 사용자 창 간섭 없음
    const tab = await chrome.tabs.create({ url: job.url, active: false })
    tabId = tab.id

    // 페이지 로드 완료 대기
    await waitForTabLoad(tabId, 30000)
    // SPA 렌더링 대기
    await wait(3000)

    // DOM에서 상품 목록 추출
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: () => {
        const seen = new Set()
        const items = []
        document.querySelectorAll('a[href*="/products/"]').forEach(link => {
          const idMatch = link.href.match(/\/products\/(\d+)/)
          if (!idMatch || seen.has(idMatch[1])) return
          seen.add(idMatch[1])
          const texts = Array.from(link.querySelectorAll('*'))
            .filter(el => el.children.length === 0)
            .map(el => el.textContent.trim())
            .filter(t => t.length > 1)
          const imgEl = link.querySelector('img')
          const brand = texts[0] || ''
          const name = texts[1] || texts[0] || ''
          const priceText = texts.find(t => t.includes('원')) || ''
          const discountText = texts.find(t => /^\d+%$/.test(t)) || ''
          const rawImg = imgEl?.src || imgEl?.currentSrc || imgEl?.getAttribute('data-src') || ''
          items.push({
            id: idMatch[1], name, brand,
            price: priceText.replace(/[^0-9]/g, ''),
            discount: parseInt(discountText) || 0,
            image: rawImg.split('?')[0]
          })
        })
        return items
      }
    })

    // 탭 닫기
    try { await chrome.tabs.remove(tabId) } catch {}
    tabId = null

    const domItems = results?.[0]?.result || []
    console.log(`[KREAM] 검색 DOM 파싱: ${domItems.length}개`)

    const products = domItems.filter(it => it.id && it.name).map(it => ({
      id: `col_kream_${it.id}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      sourceSite: 'KREAM',
      siteProductId: it.id,
      sourceUrl: `https://kream.co.kr/products/${it.id}`,
      name: it.name,
      brand: it.brand,
      category: '패션잡화 > 신발 > 스니커즈',
      images: it.image ? [`${PROXY_URL}/api/image-proxy?url=${encodeURIComponent(it.image)}`] : [],
      detailImages: [],
      options: [],
      originalPrice: 0,
      salePrice: parseInt(it.price) || 0,
      discountRate: it.discount || 0,
      status: 'collected',
      appliedPolicyId: null,
      marketPrices: {},
      kreamData: { fetchedAt: new Date().toISOString() },
      collectedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }))

    await fetch(`${PROXY_URL}/api/kream/search-result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requestId: job.requestId,
        data: { success: true, data: products, total: products.length }
      })
    })
    console.log(`[KREAM] 검색 완료: "${job.keyword}" → ${products.length}개`)
  } catch (err) {
    console.error('[KREAM] 검색 오류:', err)
    if (tabId) try { await chrome.tabs.remove(tabId) } catch {}
    try {
      await fetch(`${PROXY_URL}/api/kream/search-result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requestId: job.requestId,
          data: { success: false, message: err.message }
        })
      })
    } catch {}
  }
}

// ==================== chrome.alarms 기반 폴링 엔진 ====================

// 집중 폴링 모드 — job 발견 시 3초 간격 최대 20회 (약 60초)
let focusPollActive = false
async function runFocusPoll() {
  if (focusPollActive) return
  focusPollActive = true
  console.log('[KREAM] 집중 폴링 모드 진입 (3초 간격, 최대 20회)')
  let emptyCount = 0
  while (emptyCount < 20) {
    const hadCollect = await pollCollectOnce()
    const hadSearch = await pollSearchOnce()
    if (hadCollect || hadSearch) {
      emptyCount = 0
    } else {
      emptyCount++
    }
    if (emptyCount < 20) await wait(3000)
  }
  focusPollActive = false
  console.log('[KREAM] 집중 폴링 종료 → alarm 대기 모드 (30초 주기)')
}

// alarm 트리거 시 1회 폴링 — job 있으면 집중 모드 진입
async function runPollCycle() {
  const hadCollect = await pollCollectOnce()
  const hadSearch = await pollSearchOnce()
  if (hadCollect || hadSearch) {
    runFocusPoll()
  }
}

// alarm 설정 (30초 주기) — 중복 방지
function setupAlarm() {
  chrome.alarms.get('kreamPoll', (alarm) => {
    if (!alarm) {
      chrome.alarms.create('kreamPoll', { periodInMinutes: 0.5 })
      console.log('[KREAM] chrome.alarms 설정: 30초 주기')
    }
  })
}

// alarm 이벤트 핸들러
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'kreamPoll') {
    runPollCycle()
  }
})

// 설치/업데이트 시 alarm 등록 + 즉시 1회 실행
chrome.runtime.onInstalled.addListener(() => {
  setupAlarm()
  runPollCycle()
})

// 브라우저 시작 시 alarm 등록 + 즉시 1회 실행
chrome.runtime.onStartup.addListener(() => {
  setupAlarm()
  runPollCycle()
})

// Service Worker 활성화 시 즉시 실행
setupAlarm()
runPollCycle()

// ==================== 메시지 리스너 ====================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // 무신사 쿠키 동기화
  if (msg.type === 'SYNC_COOKIES') {
    getMusinsaCookies().then(async ({ cookies, cookieStr, isLoggedIn }) => {
      if (!isLoggedIn) {
        sendResponse({ success: false, message: '무신사 쿠키가 없습니다.' })
        return
      }
      try {
        const result = await sendCookiesToProxy(cookieStr)
        sendResponse({ success: true, cookieCount: cookies.length, ...result })
      } catch (e) {
        sendResponse({ success: false, message: `프록시 연결 실패: ${e.message}` })
      }
    })
    return true
  }

  // 전체 상태 조회
  if (msg.type === 'GET_STATUS') {
    getMusinsaCookies().then(async ({ cookies, isLoggedIn }) => {
      const alarm = await chrome.alarms.get('kreamPoll')
      sendResponse({
        musinsa: { isLoggedIn, cookieCount: cookies.length },
        kream: { isLoggedIn: !!kreamCookie, cookieCount: kreamCookie ? kreamCookie.split(';').length : 0 },
        polling: !!alarm
      })
    })
    return true
  }

  // KREAM 로그인 페이지 열기
  if (msg.type === 'KREAM_OPEN_LOGIN') {
    chrome.tabs.create({ url: 'https://kream.co.kr/login' })
    sendResponse({ success: true })
    return false
  }
})

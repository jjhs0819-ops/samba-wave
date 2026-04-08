// 삼바웨이브 쿠키 연동 - 백그라운드 서비스 워커

let PROXY_URL = 'https://samba-wave-api-363598397345.asia-northeast3.run.app'
const DEFAULT_PROXY_URL = 'https://samba-wave-api-363598397345.asia-northeast3.run.app'
const API_PREFIX = '/api/v1/samba/proxy'
const API_GATEWAY_KEY = '6woI2L8NjVrcgthMQ05VvvOTH-3HPoVdmvwa123ot1w'

// API Gateway Key가 포함된 fetch 래퍼 (서버 API 호출 전용)
function apiFetch(url, init = {}) {
  const headers = { ...(init.headers || {}), 'X-Api-Key': API_GATEWAY_KEY }
  return fetch(url, { ...init, headers })
}

// ==================== KREAM 셀렉터 설정 (서버에서 동적 변경 가능) ====================

const DEFAULT_SELECTORS = {
  kream_size_items: '.select_item',
  kream_bottom_sheet: '.layer_bottom_sheet--open',
  kream_buy_button_text: '구매하기',
  kream_fast_delivery: '빠른배송',
  kream_normal_delivery: '일반배송',
}

// 서버에서 최신 셀렉터 설정 fetch (실패 시 기본값 유지)
let selectors = { ...DEFAULT_SELECTORS }
apiFetch(`${PROXY_URL}${API_PREFIX}/extension-config`)
  .then(r => r.ok ? r.json() : null)
  .then(config => {
    if (config?.selectors) {
      selectors = { ...DEFAULT_SELECTORS, ...config.selectors }
      console.log('[설정] 서버 셀렉터 로드 완료:', Object.keys(config.selectors).length + '개 오버라이드')
    }
  })
  .catch(() => { console.log('[설정] 서버 셀렉터 로드 실패 (기본값 사용)') })

// ==================== 쿠키 동기화 공용 함수 ====================

function makeScheduleSync(label, getCookie, sendFn) {
  let timer = null
  return function () {
    if (timer) clearTimeout(timer)
    timer = setTimeout(async () => {
      timer = null
      const cookie = getCookie()
      if (!cookie) return
      try {
        await sendFn(cookie)
        console.log(`[자동동기화] ${label} 쿠키 프록시 전송 완료`)
      } catch {
        console.log('[자동동기화] 프록시 미실행 (무시)')
      }
    }, 3000)
  }
}

// ==================== 무신사 쿠키 ====================

let capturedCookie = ''
let capturedAt = 0

// ==================== KREAM 쿠키 ====================

let kreamCookie = ''

// 동기화 스케줄러 (sendCookiesToProxy 정의 후 초기화)
let scheduleCookieSync
let scheduleKreamCookieSync

// 백엔드 URL 변경 감지
chrome.storage.onChanged.addListener((changes) => {
  if (changes.proxyUrl) {
    PROXY_URL = changes.proxyUrl.newValue || DEFAULT_PROXY_URL
    console.log(`[설정] 백엔드 URL 변경: ${PROXY_URL}`)
  }
})

// Service Worker 시작 시 저장된 쿠키 + 설정 복원
chrome.storage.local.get(['capturedCookie', 'capturedAt', 'kreamCookie', 'proxyUrl']).then(async data => {
  if (data.proxyUrl) {
    PROXY_URL = data.proxyUrl
    console.log(`[복원] 백엔드 URL: ${PROXY_URL}`)
  }
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
    if (cookieHeader?.value && cookieHeader.value !== capturedCookie) {
      capturedCookie = cookieHeader.value
      capturedAt = Date.now()
      chrome.storage.local.set({ capturedCookie, capturedAt })
      console.log(`[캡처] 무신사 쿠키 변경감지 ${capturedCookie.split(';').length}개`)
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
    if (cookieHeader?.value && cookieHeader.value !== kreamCookie) {
      kreamCookie = cookieHeader.value
      chrome.storage.local.set({ kreamCookie })
      console.log(`[캡처] KREAM 쿠키 변경감지 ${kreamCookie.split(';').length}개`)
      scheduleKreamCookieSync()
    }
  },
  { urls: ['https://*.kream.co.kr/*'] },
  ['requestHeaders', 'extraHeaders']
)

// ==================== 공용 결과 전송 함수 ====================

async function postResult(endpoint, body) {
  const res = await apiFetch(`${PROXY_URL}${API_PREFIX}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) console.warn(`[결과전송] ${endpoint} 실패: HTTP ${res.status}`)
}

// ==================== 프록시 전송 함수 ====================

async function sendCookiesToProxy(cookieStr) {
  const res = await apiFetch(`${PROXY_URL}${API_PREFIX}/musinsa/set-cookie`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

async function sendKreamCookiesToProxy(cookieStr) {
  const res = await apiFetch(`${PROXY_URL}${API_PREFIX}/kream/set-cookie`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// 동기화 스케줄러 초기화
scheduleCookieSync = makeScheduleSync('무신사', () => capturedCookie, sendCookiesToProxy)
scheduleKreamCookieSync = makeScheduleSync('KREAM', () => kreamCookie, sendKreamCookiesToProxy)

// ==================== 무신사 잔액 수신 (content script → background → server) ====================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'musinsaBalance') {
    const { money, mileage, username, expired } = msg
    if (expired) {
      console.log(`[잔액] 쿠키 만료 감지 — 재로그인 필요`)
      getProfileEmailAndSend({ money: -1, mileage: -1, username, expired: true })
    } else {
      console.log(`[잔액] 무신사 잔액 수신: 머니 ${money?.toLocaleString()} / 적립금 ${mileage?.toLocaleString()} / 유저: ${username}`)
      getProfileEmailAndSend({ money, mileage, username })
    }
    sendResponse({ ok: true })
  }
  if (msg.action === 'abcmartBalance') {
    const { siteName, money, mileage, username, expired } = msg
    console.log(`[잔액] ${siteName} 잔액 수신: 머니 ${money?.toLocaleString()} / 적립금 ${mileage?.toLocaleString()} / 유저: ${username}`)
    sendAbcmartBalance({ siteName, money, mileage, username, expired: !!expired })
    sendResponse({ ok: true })
  }
  if (msg.type === 'SCRAPE_SSG_SCORES') {
    scrapeSSGScores().then(data => sendResponse(data)).catch(e => sendResponse({ error: e.message }))
    return true
  }
  return false
})

async function getProfileEmailAndSend({ money, mileage, username }) {
  let profileEmail = ''
  try {
    const info = await chrome.identity.getProfileUserInfo({ accountStatus: 'ANY' })
    profileEmail = info.email || ''
    console.log(`[잔액] 크롬 프로필 이메일: ${profileEmail}`)
  } catch (e) {
    console.log(`[잔액] 프로필 이메일 조회 실패: ${e.message}`)
  }
  sendMusinsaBalance({ money, mileage, profileEmail, username, cookie: capturedCookie, expired: arguments[0].expired || false })
}

async function sendMusinsaBalance(data) {
  const endpoints = [
    `${PROXY_URL}/api/v1/samba/sourcing-accounts/sync-balance`,
    'http://localhost:28080/api/v1/samba/sourcing-accounts/sync-balance',
  ]
  for (const url of endpoints) {
    try {
      const res = await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (res.ok) {
        const result = await res.json()
        console.log(`[잔액] 서버 저장 완료 (${url.includes('localhost') ? '로컬' : '프로덕션'}):`, result)
      } else {
        console.warn(`[잔액] 서버 저장 실패 (${url.includes('localhost') ? '로컬' : '프로덕션'}): HTTP ${res.status}`)
      }
    } catch (e) {
      console.log(`[잔액] ${url.includes('localhost') ? '로컬' : '프로덕션'} 전송 실패 (무시)`)
    }
  }
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

// 공용 폴링 함수
async function pollOnce(endpoint, handler, label, logField) {
  try {
    const res = await apiFetch(`${PROXY_URL}${API_PREFIX}/${endpoint}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const job = await res.json()
    if (job.hasJob) {
      console.log(`[${label}] ${logField ? job[logField] : '작업 수신'}`)
      await handler(job)
      return true
    }
    return false
  } catch (e) {
    console.log(`[${label}] 폴링 오류:`, e.message)
    return false
  }
}

// 1회성 수집 폴링 — job 있으면 true 반환
function pollCollectOnce() {
  return pollOnce('kream/collect-queue', handleCollectJob, 'KREAM', 'url')
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
    // 현재 활성 탭 기억 (작업 후 복원용)
    let previousTabId = null
    try {
      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true })
      previousTabId = activeTab?.id || null
    } catch { /* ignore */ }
    try {
      // active로 전환하여 Chrome 레벨 visibilityState visible 만들기
      await chrome.tabs.update(tabId, { active: true })
      await wait(500)

      const [clickResult] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: (buyBtnText) => {
          // 구매하기 버튼 클릭 — 다중 매칭 (정확 → 부분)
          const allBtns = Array.from(document.querySelectorAll('button'))
          const btn = allBtns.find(b => b.textContent.trim() === buyBtnText)
            || allBtns.find(b => {
              const t = b.textContent.trim()
              return t.includes('구매') && !t.includes('판매')
            })
          if (!btn) {
            // 디버그: 페이지 내 모든 버튼 텍스트 로깅
            const btnTexts = allBtns.map(b => b.textContent.trim()).filter(t => t)
            console.log('[KREAM] 구매 버튼 매칭 실패. 페이지 버튼 목록:', btnTexts)
            return false
          }
          btn.click()
          return true
        },
        args: [selectors.kream_buy_button_text]
      })
      const clicked = clickResult?.result
      if (clicked) {
        console.log('[KREAM] visibilityState 스푸핑 + 버튼 클릭 완료')
        await wait(1500) // 팝업 렌더링 대기

        // DOM에서 사이즈 옵션 읽기
        const [sizeResult] = await chrome.scripting.executeScript({
          target: { tabId },
          world: 'MAIN',
          func: (sizeSelector) => {
            const items = document.querySelectorAll(sizeSelector)
            return Array.from(items).map(el => {
              const ps = el.querySelectorAll('p')
              return {
                name: ps[0]?.textContent?.trim() || '',
                priceText: ps[1]?.textContent?.trim() || ''
              }
            }).filter(o => o.name)
          },
          args: [selectors.kream_size_items]
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
            func: (idx, sel) => document.querySelectorAll(sel)[idx]?.click(),
            args: [i, selectors.kream_size_items]
          })
          // 바텀시트 열림 대기 — 폴링 (최대 5초)
          for (let pollWait = 0; pollWait < 10; pollWait++) {
            const [sheetCheck] = await chrome.scripting.executeScript({
              target: { tabId }, world: 'MAIN',
              func: (sel) => !!document.querySelector(sel),
              args: [selectors.kream_bottom_sheet]
            })
            if (sheetCheck?.result) break
            await wait(500)
          }

          // 2) 배송옵션 바텀시트에서 빠른배송/일반배송 가격 읽기 (텍스트 기반 탐색)
          const [deliveryResult] = await chrome.scripting.executeScript({
            target: { tabId }, world: 'MAIN',
            func: (fastText, generalText, sheetSel) => {
              // fallback 체인: 여러 셀렉터 시도 (셀렉터 외부화)
              const sheet = document.querySelector(sheetSel + ' .bottomsheet__content')
                || document.querySelector(sheetSel + ' [class*="content"]')
                || document.querySelector(sheetSel)
              if (!sheet) return null
              const result = { fast: 0, general: 0 }

              // 모든 텍스트 노드를 포함하는 요소 순회 — 텍스트 기반 탐색
              const allElements = sheet.querySelectorAll('*')
              const sections = []
              // 배송 유형별 섹션을 그룹화
              allElements.forEach(el => {
                const text = el.textContent?.trim() || ''
                if (text === fastText || text === generalText) {
                  // 이 요소의 가장 가까운 클릭 가능한 부모 (섹션)
                  const section = el.closest('[class*="item"]') || el.closest('[class*="option"]') || el.closest('li') || el.parentElement?.parentElement
                  if (section) sections.push({ type: text, section })
                }
              })

              sections.forEach(({ type, section }) => {
                const sectionTexts = Array.from(section.querySelectorAll('*'))
                  .map(el => el.textContent?.trim() || '')
                // 해외배송 제외
                if (sectionTexts.some(t => t.includes('해외배송'))) return
                // 95점(하자상품) 제외
                if (sectionTexts.some(t => t.includes('95점'))) return
                // 가격 텍스트 찾기: "숫자,숫자원" 패턴
                const priceText = sectionTexts.find(t => /^\d[\d,]*원$/.test(t))
                if (!priceText) return
                const price = parseInt(priceText.replace(/[^0-9]/g, ''))
                if (type === fastText && price > 0) result.fast = price
                if (type === generalText && price > 0) result.general = price
              })

              // fallback: 섹션 그룹화 실패 시 기존 children 순회
              if (result.fast === 0 && result.general === 0) {
                const firstChild = sheet.querySelector(':scope > div:first-child') || sheet
                Array.from(firstChild.children || []).forEach(child => {
                  const pTexts = Array.from(child.querySelectorAll('p, span, div'))
                    .map(p => p.textContent?.trim() || '')
                  if (pTexts.some(t => t.includes('해외배송'))) return
                  if (pTexts.some(t => t.includes('95점'))) return
                  const priceText = pTexts.find(t => /^\d[\d,]*원$/.test(t))
                  if (!priceText) return
                  const price = parseInt(priceText.replace(/[^0-9]/g, ''))
                  if (pTexts.some(t => t.includes(fastText)) && price > 0) result.fast = price
                  if (pTexts.some(t => t.includes(generalText)) && price > 0) result.general = price
                })
              }

              return result
            },
            args: [selectors.kream_fast_delivery, selectors.kream_normal_delivery, selectors.kream_bottom_sheet]
          })

          if (deliveryResult?.result) {
            sizeOptions[i].kreamFastPrice = deliveryResult.result.fast || 0
            sizeOptions[i].kreamGeneralPrice = deliveryResult.result.general || 0
            console.log(`[KREAM] ${sizeOptions[i].name}: 빠른 ${deliveryResult.result.fast}, 일반 ${deliveryResult.result.general}`)
          } else {
            console.log(`[KREAM] ${sizeOptions[i].name}: 배송시트 데이터 없음`)
          }

          // 3) 배송시트 닫기 → 사이즈 목록으로 복귀
          await chrome.scripting.executeScript({
            target: { tabId }, world: 'MAIN',
            func: (sel) => {
              const sheet = document.querySelector(sel)
              const closeBtn = sheet?.querySelector('[class*="close"]')
              if (closeBtn) closeBtn.click()
              else sheet?.querySelector('.bottomsheet__background')?.click()
            },
            args: [selectors.kream_bottom_sheet]
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

    // 원래 활성 탭으로 복원 (창 빼앗김 방지)
    if (previousTabId) {
      try {
        await chrome.tabs.update(previousTabId, { active: true })
      } catch { /* 탭이 닫혔을 수 있음 */ }
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
        .map(img => `${PROXY_URL}${API_PREFIX}/kream/image-proxy?url=${encodeURIComponent(img)}`)

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

      await postResult('kream/collect-result', { requestId: job.requestId, data: { success: true, product } })
      console.log(`[KREAM] 수집 완료: ${response.data.name} (사이즈 ${options.length}개, 이미지 ${proxyImages.length}개)`)
    } else {
      await postResult('kream/collect-result', { requestId: job.requestId, data: { success: false, message: response?.message || '수집 실패' } })
    }
  } catch (err) {
    console.error('[KREAM] 수집 오류:', err)
    if (tabId) {
      try { await chrome.tabs.remove(tabId) } catch {}
    }
    try {
      await postResult('kream/collect-result', { requestId: job.requestId, data: { success: false, message: err.message } })
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

// 1회성 검색 폴링
function pollSearchOnce() {
  return pollOnce('kream/search-queue', handleSearchJob, 'KREAM', 'keyword')
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

    // 무한스크롤 — 목표 수량까지 스크롤 반복
    const targetCount = job.count || 50
    const maxScrolls = Math.min(Math.ceil(targetCount / 50), 10)
    let prevCount = 0

    for (let scroll = 0; scroll < maxScrolls; scroll++) {
      const [countResult] = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => document.querySelectorAll('a[href*="/products/"]').length
      })
      const currentCount = countResult?.result || 0
      console.log(`[KREAM] 스크롤 ${scroll + 1}/${maxScrolls}: ${currentCount}개 로드됨`)

      if (currentCount >= targetCount || (scroll > 0 && currentCount === prevCount)) break
      prevCount = currentCount

      await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => window.scrollTo(0, document.body.scrollHeight)
      })
      await wait(2000)
    }

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
      images: it.image ? [`${PROXY_URL}${API_PREFIX}/kream/image-proxy?url=${encodeURIComponent(it.image)}`] : [],
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

    await postResult('kream/search-result', {
      requestId: job.requestId,
      data: { success: true, data: products, total: products.length }
    })
    console.log(`[KREAM] 검색 완료: "${job.keyword}" → ${products.length}개`)
  } catch (err) {
    console.error('[KREAM] 검색 오류:', err)
    if (tabId) try { await chrome.tabs.remove(tabId) } catch {}
    try {
      await postResult('kream/search-result', {
        requestId: job.requestId,
        data: { success: false, message: err.message }
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
    const hadSourcing = await pollSourcingOnce()
    const hadAi = await pollAiSourcingOnce()
    if (hadCollect || hadSearch || hadSourcing || hadAi) {
      emptyCount = 0
    } else {
      emptyCount++
    }
    if (emptyCount < 20) await wait(3000)
  }
  focusPollActive = false
  console.log('[KREAM] 집중 폴링 종료 → alarm 대기 모드 (30초 주기)')
}

// alarm 트리거 시 1회 폴링 — job 있으면 집중 모드 진입, 없으면 카운트 증가
async function runPollCycle() {
  const hadCollect = await pollCollectOnce()
  const hadSearch = await pollSearchOnce()
  const hadSourcing = await pollSourcingOnce()
  const hadAi = await pollAiSourcingOnce()
  if (hadCollect || hadSearch || hadSourcing || hadAi) {
    emptyPollCount = 0
    runFocusPoll()
  } else {
    emptyPollCount++
    if (emptyPollCount >= MAX_EMPTY_POLLS) {
      stopCollectPolling()
    }
  }
}

// alarm 이벤트 핸들러
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'collectPoll') {
    runPollCycle()
  }
  if (alarm.name === 'balanceCheckPoll') {
    pollBalanceCheckRequest()
  }
})

// 수집 폴링 — job 없으면 5분 후 자동 중지, job 있으면 자동 재시작
let emptyPollCount = 0
let quickPollTimer = null
const MAX_EMPTY_POLLS = 30 // 10초 × 30 = 5분간 빈 결과 → 중지

function startCollectPolling() {
  emptyPollCount = 0
  chrome.alarms.get('collectPoll', (alarm) => {
    if (!alarm) {
      chrome.alarms.create('collectPoll', { periodInMinutes: 0.5 })
      console.log('[수집] alarm 등록 (30초/실제 1분 백업)')
    }
  })
  // setInterval 10초 보조 폴링 — 서비스 워커 활성 중 빠른 응답
  if (!quickPollTimer) {
    quickPollTimer = setInterval(() => {
      if (!focusPollActive) runPollCycle()
    }, 10_000)
    console.log('[수집] 폴링 시작 (10초 주기 + alarm 백업)')
  }
  runPollCycle()
}

function stopCollectPolling() {
  chrome.alarms.clear('collectPoll')
  if (quickPollTimer) {
    clearInterval(quickPollTimer)
    quickPollTimer = null
  }
  console.log('[수집] 폴링 중지 (빈 결과 5분 연속)')
}

// 무신사 잔액 체크 — 버튼 요청 시에만 실행
async function checkMusinsaBalance() {
  console.log('[잔액] 잔액 체크 시작')
  let tab = null
  try {
    tab = await chrome.tabs.create({ url: 'https://www.musinsa.com/mypage', active: false })
    await new Promise(r => setTimeout(r, 15000))
  } catch (e) {
    console.log(`[잔액] 체크 실패: ${e.message}`)
  } finally {
    if (tab?.id) try { await chrome.tabs.remove(tab.id) } catch {}
    // 체크 완료 → 폴링 중지
    chrome.alarms.clear('balanceCheckPoll')
    console.log('[잔액] 체크 완료 → 폴링 중지')
  }
}

// 서버에서 잔액 체크 요청 확인 (버튼 클릭 시에만 폴링 활성)
async function pollBalanceCheckRequest() {
  const urls = [
    'http://localhost:28080/api/v1/samba/sourcing-accounts/balance-check-requested',
    `${PROXY_URL}/api/v1/samba/sourcing-accounts/balance-check-requested`,
  ]
  for (const url of urls) {
    try {
      const r = await apiFetch(url)
      if (r.ok) {
        const data = await r.json()
        if (data.requested) {
          console.log(`[잔액] 서버 요청 감지 → 잔액 체크 실행`)
          checkMusinsaBalance()
          return
        }
      }
    } catch { /* 무시 */ }
  }
}

// 잔액 폴링 (5분 주기, 서버에 요청 없으면 아무 동작 안 함)
chrome.alarms.get('balanceCheckPoll', (alarm) => {
  if (!alarm) {
    chrome.alarms.create('balanceCheckPoll', { periodInMinutes: 5 })
  }
})

// 설치/업데이트/시작 시 — 수집 폴링 자동 시작
chrome.runtime.onInstalled.addListener(() => { startCollectPolling() })
chrome.runtime.onStartup.addListener(() => { startCollectPolling() })
startCollectPolling()

// ==================== AI소싱 큐 폴링 ====================

// AI소싱 큐는 /api/v1/samba/ai-sourcing/ 경로 사용 (proxy 아님)
async function pollAiSourcingOnce() {
  try {
    const res = await apiFetch(`${PROXY_URL}/api/v1/samba/ai-sourcing/collect-queue`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const job = await res.json()
    if (job.hasJob) {
      console.log(`[AI소싱] 작업 수신: ${job.type}`)
      await handleAiSourcingJob(job)
      return true
    }
    return false
  } catch (e) {
    console.log(`[AI소싱] 폴링 오류: ${e.message}`)
    return false
  }
}

// AI소싱 결과 전송도 별도 경로
async function postAiSourcingResult(body) {
  await apiFetch(`${PROXY_URL}/api/v1/samba/ai-sourcing/collect-result`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

async function handleAiSourcingJob(job) {
  const jobType = job.type // 'ranking' 또는 'keywords'
  let tabId = null

  try {
    if (jobType === 'ranking') {
      // 랭킹 아카이브 수집 — API 가로채기 방식
      const date = job.date || '202503'
      const categoryCode = job.categoryCode || '000'
      const url = `https://www.musinsa.com/ranking/archive?date=${date}&categoryCode=${categoryCode}&gf=A`
      console.log(`[AI소싱] 랭킹 수집: ${url}`)

      const [prevActive] = await chrome.tabs.query({ active: true, currentWindow: true })
      const prevId = prevActive?.id

      const tab = await chrome.tabs.create({ url, active: true })
      tabId = tab.id
      await waitForTabLoad(tabId, 30000)
      await wait(3000)

      // 페이지 내에서 fetch를 가로채서 API 응답 수집 + DOM 텍스트 파싱 병행
      const results = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => {
          // DOM 텍스트 기반 파싱 — 렌더링된 상품 카드에서 추출
          const items = []
          const bodyText = document.body.innerText
          const lines = bodyText.split('\n').map(l => l.trim()).filter(Boolean)

          // 상품 링크
          const goodsNos = []
          document.querySelectorAll('a[href*="/products/"]').forEach(link => {
            const m = link.href?.match(/\/products\/(\d+)/)
            if (m && !goodsNos.includes(m[1])) goodsNos.push(m[1])
          })

          // 순위+브랜드+상품명+가격 텍스트 파싱
          let rank = 0
          let brand = ''
          for (let i = 0; i < lines.length; i++) {
            const line = lines[i]
            // 순위 (1~200)
            if (/^\d{1,3}$/.test(line)) {
              const n = parseInt(line)
              if (n >= 1 && n <= 200) { rank = n; brand = ''; continue }
            }
            if (rank > 0 && !brand) {
              // 가격/할인율이 아닌 짧은 텍스트 = 브랜드
              if (line.length < 30 && !/[\d,]+원/.test(line) && !/^\d+%$/.test(line) && !/^[\d,]+$/.test(line)) {
                brand = line; continue
              }
            }
            if (rank > 0 && brand) {
              // 브랜드 다음 긴 텍스트 = 상품명
              if (line.length >= 3 && !/[\d,]+원/.test(line) && !/^\d+%$/.test(line)) {
                let price = 0
                for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
                  const pm = lines[j].replace(/\s/g, '').match(/([\d,]+)원/)
                  if (pm) { price = parseInt(pm[1].replace(/,/g, '')); break }
                }
                items.push({ rank, brand, name: line, price, goodsNo: goodsNos[items.length] || '' })
                rank = 0; brand = ''
              }
            }
          }

          return {
            items,
            debug: {
              title: document.title,
              productLinks: goodsNos.length,
              totalItems: items.length,
              bodyLen: bodyText.length,
              bodyPreview: bodyText.substring(0, 1200),
            },
          }
        },
      })

      try { await chrome.tabs.remove(tabId) } catch {}
      tabId = null
      // 이전 탭 복원
      if (prevId) {
        try { await chrome.tabs.update(prevId, { active: true }) } catch {}
      }

      const data = results?.[0]?.result || {}
      console.log(`[AI소싱] 랭킹: ${data.items?.length || 0}개 상품`)

      await postAiSourcingResult({
        requestId: job.requestId,
        type: 'ranking',
        data,
      })

    } else if (jobType === 'keywords') {
      // 인기/급상승 검색어 수집 — 검색 페이지를 active 탭으로 열어서 키워드 표시
      console.log('[AI소싱] 검색 키워드 수집 시작')
      // 현재 활성 탭 기억 (복원용)
      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true })
      const prevTabId = activeTab?.id

      // 검색 페이지를 active 탭으로 열기 (포커스 필요)
      const tab = await chrome.tabs.create({ url: 'https://www.musinsa.com/search', active: true })
      tabId = tab.id
      await waitForTabLoad(tabId, 30000)
      await wait(2000)

      // 검색 입력 클릭 (인기검색어 표시 트리거)
      await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => {
          // 다양한 셀렉터 시도 (무신사 UI 변경 대응)
          const selectors = [
            'input[type="search"]',
            'input[placeholder*="검색"]',
            'input[name*="search"]',
            'input[aria-label*="검색"]',
            '.search-bar input',
            '#search-input',
            'header input',
          ]
          for (const sel of selectors) {
            const el = document.querySelector(sel)
            if (el) { el.focus(); el.click(); break }
          }
          // 검색 버튼/아이콘 클릭도 시도
          const searchBtn = document.querySelector('[class*="search"] button, button[aria-label*="검색"]')
          if (searchBtn) searchBtn.click()
        },
      })
      await wait(4000)

      const results = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => {
          const popular = []
          const trending = []
          const bodyText = document.body.innerText

          // 방법1: "인기 검색어" / "급상승 검색어" 섹션 텍스트 파싱
          const popularMatch = bodyText.match(/인기\s*검색어([\s\S]*?)(?:급상승\s*검색어|$)/)
          const trendingMatch = bodyText.match(/급상승\s*검색어([\s\S]*?)(?:어바웃|회사|무신사 스토어|$)/)

          function extractKw(text) {
            const kws = []
            const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
            for (const line of lines) {
              const m = line.match(/^(\d{1,2})\s+(.+)$/)
              if (m && m[2].length < 30) {
                kws.push({ rank: parseInt(m[1]), keyword: m[2].trim() })
              }
            }
            return kws
          }

          if (popularMatch) popular.push(...extractKw(popularMatch[1]))
          if (trendingMatch) trending.push(...extractKw(trendingMatch[1]))

          // 방법2: DOM 기반 파싱 (텍스트 매칭 실패 시 fallback)
          if (popular.length === 0 && trending.length === 0) {
            // li 요소에서 순위+키워드 추출 시도
            const listItems = document.querySelectorAll('li, [class*="keyword"], [class*="search-rank"], [class*="popular"]')
            let rank = 1
            listItems.forEach(li => {
              const text = li.textContent?.trim() || ''
              // "1나이키운동화" 또는 "1 나이키 운동화" 패턴
              const m = text.match(/^(\d{1,2})\s*(.{2,25})$/)
              if (m) {
                popular.push({ rank: parseInt(m[1]), keyword: m[2].trim() })
              } else if (text.length >= 2 && text.length <= 25 && !/^(MUSINSA|BEAUTY|SPORTS|OUTLET|BOUTIQUE|KICKS|KIDS|USED|SNAP)$/i.test(text)) {
                // 순위 없이 키워드만 있는 경우
                const exists = popular.some(p => p.keyword === text) || trending.some(t => t.keyword === text)
                if (!exists && rank <= 20) {
                  popular.push({ rank: rank++, keyword: text })
                }
              }
            })
          }

          return {
            keywordItems: [
              ...popular.map(k => ({ ...k, type: 'popular' })),
              ...trending.map(k => ({ ...k, type: 'trending' })),
            ],
            debug: {
              bodyLen: bodyText.length,
              bodyPreview: bodyText.substring(0, 1500),
              hasPopular: !!popularMatch,
              hasTrending: !!trendingMatch,
              domFallback: popular.length > 0 && !popularMatch,
            },
          }
        },
      })

      // 이전 탭으로 복원
      if (prevTabId) {
        try { await chrome.tabs.update(prevTabId, { active: true }) } catch {}
      }

      try { await chrome.tabs.remove(tabId) } catch {}
      tabId = null
      const data = results?.[0]?.result || {}
      console.log(`[AI소싱] 키워드: ${data.keywordItems?.length || 0}개`)

      await postAiSourcingResult({
        requestId: job.requestId,
        type: 'keywords',
        data,
      })
    }
  } catch (err) {
    console.error(`[AI소싱] ${jobType} 오류:`, err)
    if (tabId) try { await chrome.tabs.remove(tabId) } catch {}
    try {
      await postAiSourcingResult({
        requestId: job.requestId,
        type: jobType,
        error: err.message,
      })
    } catch {}
  }
}

// ==================== 통합 소싱 큐 폴링 (ABCmart, GrandStage, REXMONDE, 롯데ON, GSShop) ====================

function pollSourcingOnce() {
  return pollOnce('sourcing/collect-queue', handleSourcingJob, '소싱', 'url')
}

// 소싱 작업 처리 — 탭 열기 → DOM 파싱 → 결과 전송
async function handleSourcingJob(job) {
  let tabId = null
  try {
    // active:true 필요: 패션플러스 상세(lazy 컨텐츠), GS샵 카테고리스캔(JS렌더링)
    const needsActive = (job.type === 'detail' && job.site === 'FashionPlus') || job.type === 'category-scan'
    const tab = await chrome.tabs.create({ url: job.url, active: needsActive })
    tabId = tab.id
    await waitForTabLoad(tabId, 30000)
    await wait(needsActive ? 5000 : 4000) // 패션플러스 상세는 렌더링 시간 추가

    let result = null
    if (job.type === 'category-scan' && job.site === 'GSShop') {
      // GS샵 카테고리 스캔: 검색 결과 페이지에서 카테고리 분포 파싱
      await wait(3000) // JS 렌더링 추가 대기 (active 탭이므로 5s+3s=8s)

      const [scanResult] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => {
          const categories = []
          const seen = new Set()
          const debugInfo = { url: location.href, title: document.title }

          // innerText에서 "이름 (숫자)" 패턴을 전역 탐색
          // DOM 구조에 의존하지 않는 가장 안정적인 방법
          const bodyText = document.body?.innerText || ''
          const lines = bodyText.split('\n')
          for (const line of lines) {
            const trimmed = line.replace(/\s+/g, ' ').trim()
            const match = trimmed.match(/^(.+?)\s*\(([\d,]+)\)\s*$/)
            if (!match) continue
            const name = match[1].trim()
            const count = parseInt(match[2].replace(/,/g, ''), 10)
            // 탭 항목(전체상품, TV상품, 백화점) 및 노이즈 제외
            if (count <= 0 || seen.has(name)) continue
            if (['전체상품', 'TV상품', '백화점', '추천순'].includes(name)) continue
            if (name.includes('검색결과')) continue
            if (name.length > 30 || name.length < 2) continue
            seen.add(name)
            categories.push({ name, count, categoryCode: name, href: '' })
          }

          // href 보강: 카테고리명과 일치하는 a 태그에서 href 추출
          if (categories.length > 0) {
            const allLinks = document.querySelectorAll('a[href]')
            for (const link of allLinks) {
              const linkText = link.textContent.replace(/\s+/g, ' ').trim()
              for (const cat of categories) {
                if (linkText.includes(cat.name) && linkText.includes(`(${cat.count.toLocaleString()}`)) {
                  cat.href = link.getAttribute('href') || ''
                  try {
                    const url = new URL(cat.href, location.origin)
                    cat.categoryCode = url.searchParams.get('cls') || url.searchParams.get('sectCd') || cat.name
                  } catch {}
                  break
                }
              }
            }
          }

          // 백화점 탭 전체 상품 수
          let total = 0
          for (const line of lines) {
            const t = line.replace(/\s+/g, ' ').trim()
            const m = t.match(/백화점\s*\(([\d,]+)\)/)
            if (m) { total = parseInt(m[1].replace(/,/g, ''), 10); break }
          }
          if (total === 0 && categories.length > 0) {
            total = categories.reduce((s, c) => s + c.count, 0)
          }

          debugInfo.categoryCount = categories.length
          debugInfo.bodyTextLength = bodyText.length
          debugInfo.sampleLines = lines.filter(l => l.includes('(')).slice(0, 10).map(l => l.trim().slice(0, 50))

          return { success: categories.length > 0, categories, total, debugInfo }
        }
      })
      result = scanResult?.result || { success: false, categories: [], total: 0, debugInfo: {} }
      console.log(`[소싱] GSShop 카테고리 스캔: ${result.categories?.length || 0}개 카테고리, total=${result.total}`)
      console.log(`[소싱] GSShop 디버그:`, JSON.stringify(result.debugInfo || {}))
    } else if (job.type === 'search' && job.site === 'GSShop') {
      // GS샵: 페이지네이션 반복 수집
      const maxCount = job.maxCount || 999
      const allProducts = []
      const seenIds = new Set()
      let pageNum = 1
      const maxPages = Math.ceil(maxCount / 60) + 1

      while (allProducts.length < maxCount && pageNum <= maxPages) {
        if (pageNum > 1) {
          const eh = btoa(JSON.stringify({ pageNumber: pageNum, selected: 'opt-page' }))
          const nextUrl = new URL(job.url)
          nextUrl.searchParams.set('eh', eh)
          await chrome.tabs.update(tabId, { url: nextUrl.toString() })
          await waitForTabLoad(tabId, 30000)
          await wait(4000)
        }

        const pageResult = await extractSearchResults(tabId, job.site, 999)
        const pageProducts = pageResult?.products || []

        if (pageProducts.length === 0) break

        let newCount = 0
        for (const p of pageProducts) {
          if (!seenIds.has(p.site_product_id)) {
            seenIds.add(p.site_product_id)
            allProducts.push(p)
            newCount++
          }
        }

        console.log(`[소싱] GSShop 페이지 ${pageNum}: +${newCount}건 (총 ${allProducts.length}건)`)
        if (newCount === 0) break

        pageNum++
      }

      result = { success: true, products: allProducts.slice(0, maxCount), total: allProducts.length }
    } else if (job.type === 'search') {
      result = await extractSearchResults(tabId, job.site, job.maxCount || 999)
    } else if (job.type === 'detail') {
      result = await extractDetailData(tabId, job.site, job.productId)
    }

    try { await chrome.tabs.remove(tabId) } catch {}

    await postResult('sourcing/collect-result', { requestId: job.requestId, data: result || { success: false, message: '파싱 실패' } })
    console.log(`[소싱] ${job.site} 완료: ${result?.products?.length || 0}건`)
  } catch (err) {
    console.error(`[소싱] ${job.site} 오류:`, err)
    if (tabId) try { await chrome.tabs.remove(tabId) } catch {}
    try {
      await postResult('sourcing/collect-result', { requestId: job.requestId, data: { success: false, message: err.message } })
    } catch {}
  }
}

// 검색 결과 DOM 파싱 — 범용 상품 카드 추출
async function extractSearchResults(tabId, site, maxCount = 999) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: (siteName, maxItems) => {
      const products = []
      const seen = new Set()

      // 범용 상품 링크 추출 (a 태그 기반)
      const linkPatterns = {
        'ABCmart': /\/product\?prdtNo=(\d+)/,
        'GrandStage': /\/product\?prdtNo=(\d+)/,
        'REXMONDE': /\/products\/detail\/(\d+)/,
        'LOTTEON': /\/product\/productDetail[^"]*spdNo=(\d+)/,
        'GSShop': /\/(?:prd\/prd\.gs\?prdid|deal\/deal\.gs\?dealNo)=(\d+)/,
        'ElandMall': /\/goods\/goods\.action\?goodsNo=(\d+)/,
        'SSF': /\/goods\/([A-Z0-9]+)/,
      }
      const pattern = linkPatterns[siteName]
      if (!pattern) return { success: false, products: [], total: 0 }

      // 모든 a 태그에서 상품 링크 찾기 (GSShop: 컨테이너 스코핑)
      let allLinks
      if (siteName === 'GSShop') {
        const container = document.querySelector('#searchPrdList .prd-list') || document.querySelector('.prd-list') || document
        allLinks = container.querySelectorAll('a[href]')
      } else {
        allLinks = document.querySelectorAll('a[href]')
      }
      for (const link of allLinks) {
        if (products.length >= maxItems) break  // 수량 제한
        const match = link.href.match(pattern)
        if (!match || seen.has(match[1])) continue
        seen.add(match[1])

        // 가장 가까운 상품 카드 컨테이너
        const card = link.closest('[class*="product"]') || link.closest('[class*="item"]') || link.closest('li') || link

        // GSShop 전용 파싱 (prd-name, price-info 등 고유 클래스 활용)
        if (siteName === 'GSShop') {
          const nameEl = card.querySelector('dt.prd-name') || card.querySelector('.prd-name')
          const priceEl = card.querySelector('dd.price-info') || card.querySelector('.price-info')
          const imgEl = card.querySelector('.prd-img img') || card.querySelector('img')

          const name = nameEl?.textContent?.trim() || ''
          let image = imgEl?.src || imgEl?.getAttribute('data-src') || imgEl?.getAttribute('data-original') || ''
          if (image.startsWith('//')) image = 'https:' + image
          // GS샵 이미지 고해상도 변환 (250px → 800px)
          if (image.includes('asset.m-gs.kr') && image.includes('/250')) {
            image = image.replace('/250', '/800')
          }

          let salePrice = 0
          let originalPrice = 0
          if (priceEl) {
            const priceText = priceEl.textContent || ''
            const nums = priceText.match(/[\d,]+/g)?.map(n => parseInt(n.replace(/,/g, ''))).filter(n => n > 100) || []
            if (nums.length >= 2) {
              salePrice = Math.min(...nums)
              originalPrice = Math.max(...nums)
            } else if (nums.length === 1) {
              salePrice = nums[0]
              originalPrice = nums[0]
            }
          }

          if (name || salePrice > 0) {
            products.push({
              site_product_id: match[1],
              name: name || `GSShop ${match[1]}`,
              brand: '',
              original_price: originalPrice,
              sale_price: salePrice,
              images: image ? [image] : [],
              source_site: siteName,
            })
          }
          continue
        }

        // 이미지
        const imgEl = card.querySelector('img')
        let image = imgEl?.src || imgEl?.currentSrc || imgEl?.getAttribute('data-src') || imgEl?.getAttribute('data-lazy') || ''
        if (image.startsWith('//')) image = 'https:' + image

        // 텍스트 노드들 (leaf 노드만)
        const texts = Array.from(card.querySelectorAll('*'))
          .filter(el => el.children.length === 0 && el.textContent.trim().length > 1)
          .map(el => el.textContent.trim())

        // 브랜드 (보통 첫번째 짧은 텍스트)
        const brand = texts.find(t => t.length < 30 && t.length > 1 && !/[0-9,]+원/.test(t)) || ''

        // 상품명 (가장 긴 텍스트)
        const name = texts.reduce((a, b) => (b.length > a.length && !/[0-9,]+원/.test(b) ? b : a), '') || ''

        // 가격 (숫자+원 패턴)
        const priceTexts = texts.filter(t => /[\d,]+원/.test(t) || /^\d[\d,]+$/.test(t))
        let salePrice = 0
        let originalPrice = 0
        for (const pt of priceTexts) {
          const num = parseInt(pt.replace(/[^0-9]/g, ''))
          if (num > 0) {
            if (salePrice === 0) salePrice = num
            else if (num > salePrice) originalPrice = num
            else originalPrice = salePrice, salePrice = num
          }
        }
        if (!originalPrice) originalPrice = salePrice

        if (name || salePrice > 0) {
          products.push({
            site_product_id: match[1],
            name: name || `${siteName} ${match[1]}`,
            brand,
            original_price: originalPrice,
            sale_price: salePrice,
            images: image ? [image] : [],
            source_site: siteName,
          })
        }
      }

      return { success: true, products, total: products.length }
    },
    args: [site, maxCount]
  })

  return result?.result || { success: false, products: [], total: 0 }
}

// 상품 상세 DOM 파싱 — 범용
async function extractDetailData(tabId, site, productId) {
  // 패션플러스: 상세정보 탭 클릭하여 lazy 렌더링 트리거
  if (site === 'FashionPlus') {
    try {
      await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => {
          const tabs = document.querySelectorAll('.mm_tab-link, [class*="tab"] a, [class*="tab"] button')
          for (const tab of tabs) {
            if (tab.textContent.trim().includes('상세정보') || tab.textContent.trim().includes('상세 정보')) {
              tab.click()
              break
            }
          }
        }
      })
      await wait(3000)
    } catch {}
  }

  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: (siteName, prdId) => {
      try {
      // ── 패션플러스 전용 파싱 ──
      if (siteName === 'FashionPlus') {
        let name = '', brand = '', origPrice = 0, salePrice = 0, sku = ''
        const jsonLd = document.querySelector('script[type="application/ld+json"]')
        if (jsonLd) {
          try {
            let d = JSON.parse(jsonLd.textContent)
            if (Array.isArray(d)) d = d.find(x => x['@type'] === 'Product') || d[0]
            if (d?.['@type'] === 'Product') {
              name = d.name || ''
              sku = d.sku || ''
              const o = d.offers || {}
              origPrice = parseInt(o.price || 0)
              salePrice = parseInt(o.sale_price || o.price || 0)
              const b = d.brand || {}
              brand = typeof b === 'object' ? (b.name || '') : String(b)
            }
          } catch {}
        }
        const sellerId = sku.split('_')[0] || ''
        const productImgs = []
        document.querySelectorAll('img').forEach(img => {
          const src = img.src || img.currentSrc || ''
          if (src.includes('product_img') && (!sellerId || src.includes(`/${sellerId}/`)) && !productImgs.includes(src)) {
            productImgs.push(src.replace(/\?.*$/, ''))
          }
        })
        const detailImgs = []
        document.querySelectorAll('.mm_tab-item img, [class*="detail"] img, [class*="desc"] img').forEach(img => {
          const src = img.src || img.currentSrc || ''
          if (src && !src.startsWith('data:') && src.includes('http') && !detailImgs.includes(src) && !src.includes('sidebar') && !src.includes('banner') && !src.includes('favicon')) {
            detailImgs.push(src.startsWith('//') ? 'https:' + src : src)
          }
        })
        const notice = {}
        const noticeArea = document.body.innerHTML.match(/상품\s*정보\s*제공고시([\s\S]*?)(?:상품\s*일반정보|반품|$)/)
        if (noticeArea) {
          const div = document.createElement('div')
          div.innerHTML = noticeArea[1]
          const cells = div.querySelectorAll('th, td')
          for (let i = 0; i < cells.length - 1; i += 2) {
            const key = cells[i].textContent.trim()
            const val = cells[i + 1]?.textContent.trim() || ''
            if (key && val && !key.includes('반품')) notice[key] = val
          }
        }
        let material = '', color = '', manufacturer = '', origin = ''
        let careInstructions = '', qualityGuarantee = ''
        for (const [k, v] of Object.entries(notice)) {
          if (v === '상세설명참조' || v === '상세페이지참조' || !v) continue
          if (k.includes('소재') || k.includes('재질')) material = v
          else if (k === '색상') color = v
          else if (k.includes('제조자') || k.includes('제조사')) manufacturer = v
          else if (k.includes('제조국') || k.includes('원산지')) origin = v
          else if (k.includes('세탁') || k.includes('취급') || k.includes('주의')) careInstructions = v
          else if (k.includes('품질') || k.includes('보증')) qualityGuarantee = v
        }
        const feeMatch = document.body.innerHTML.match(/배송비\s*(\d[\d,]+)\s*원/)
        const shippingFee = feeMatch ? parseInt(feeMatch[1].replace(/,/g, '')) : 3000
        const options = []
        document.querySelectorAll('select option, [class*="option"] li, [class*="size"] button').forEach(el => {
          const t = el.textContent.trim()
          if (t && t !== '선택' && t !== '옵션을 선택하세요' && t.length < 50) {
            options.push({ name: t, stock: 999, isSoldOut: false })
          }
        })
        const allDetailImgs = [...new Set([...productImgs, ...detailImgs])]
        const detailHtml = allDetailImgs.map(src =>
          `<div style="text-align:center;"><img src="${src}" style="max-width:860px;width:100%;" /></div>`
        ).join('\n')
        return {
          success: true, site_product_id: prdId,
          name, brand, original_price: origPrice, sale_price: salePrice,
          images: productImgs.slice(0, 9),
          detail_images: allDetailImgs, detail_html: detailHtml,
          source_site: siteName,
          category: '', category1: '', category2: '', category3: '',
          options, material, color, manufacturer, origin,
          care_instructions: careInstructions, quality_guarantee: qualityGuarantee,
          shipping_fee: shippingFee,
        }
      }

      // ── 롯데ON 전용 파싱 (렌더된 DOM에서 프로모션가/혜택가 추출) ──
      if (siteName === 'LOTTEON') {
        let salePrice = 0
        let originalPrice = 0
        let benefitPrice = 0
        let name = ''
        let brand = ''

        const nameEl = document.querySelector('h3[class*="product"], [class*="tit_product"], [class*="product-name"], [class*="pdp-title"]')
        name = nameEl?.textContent?.trim() || document.querySelector('meta[property="og:title"]')?.content || ''

        const brandEl = document.querySelector('[class*="brand"] a, [class*="brand-name"]')
        brand = brandEl?.textContent?.trim() || ''

        const bodyText = document.body?.innerText || ''

        // "나의 혜택가" 추출
        const benefitMatch = bodyText.match(/([\d,]+)\s*원\s*나의\s*혜택가/)
        if (benefitMatch) {
          benefitPrice = parseInt(benefitMatch[1].replace(/,/g, ''), 10)
        }

        // 프로모션 판매가
        const promoMatch = bodyText.match(/(\d+)%\s+([\d,]+)\s*원/)
        if (promoMatch) {
          salePrice = parseInt(promoMatch[2].replace(/,/g, ''), 10)
        }

        // 정가
        const delEl = document.querySelector('del, s, [class*="origin"] [class*="price"], [class*="before"] [class*="price"]')
        if (delEl) {
          const delNum = delEl.textContent.replace(/[^0-9]/g, '')
          if (delNum) originalPrice = parseInt(delNum, 10)
        }
        if (!originalPrice) originalPrice = salePrice

        // 옵션 (사이즈) + 실재고
        const options = []
        document.querySelectorAll('[class*="option"] li, [class*="option"] button, select option').forEach(el => {
          const t = el.textContent.trim()
          if (!t || t === '선택하세요.' || t.length > 50) return
          const isSoldOut = t.includes('품절')
          const stockMatch = t.match(/(\d+)\s*개\s*남음/)
          let stock = 0
          if (isSoldOut) stock = 0
          else if (stockMatch) stock = parseInt(stockMatch[1], 10)
          else stock = 1
          const cleanName = t.replace(/\[품절\]\s*/g, '').replace(/\s*\d+개\s*남음.*/, '').replace(/\s*\(품절임박\)/, '').trim()
          if (cleanName) {
            options.push({ name: cleanName, stock, isSoldOut })
          }
        })

        const images = []
        document.querySelectorAll('[class*="thumb"] img, [class*="swiper"] img, [class*="slide"] img').forEach(img => {
          let src = img.src || img.currentSrc || img.getAttribute('data-src') || ''
          if (src.startsWith('//')) src = 'https:' + src
          if (src && src.includes('http') && !src.includes('data:') && !images.includes(src)) {
            images.push(src)
          }
        })

        if (name || salePrice > 0) {
          return {
            success: true,
            site_product_id: prdId,
            name, brand,
            original_price: originalPrice,
            sale_price: salePrice || benefitPrice,
            best_benefit_price: benefitPrice,
            images: images.slice(0, 9),
            source_site: siteName,
            category: '', category1: '', category2: '', category3: '',
            options,
          }
        }
      }

      // ── ABCmart/GrandStage 전용 파싱 (최대혜택가 추출) ──
      if (siteName === 'ABCmart' || siteName === 'GrandStage') {
        const bodyText = document.body?.innerText || ''
        let benefitPrice = 0

        // "최대 혜택가 70,400원" 또는 "최대혜택가 70,400원" 패턴
        const benefitMatch = bodyText.match(/최대\s*혜택가\s*([\d,]+)\s*원/)
        if (benefitMatch) {
          benefitPrice = parseInt(benefitMatch[1].replace(/,/g, ''), 10)
        }

        if (benefitPrice > 0) {
          let name = ''
          let salePrice = 0
          let originalPrice = 0
          const nameEl = document.querySelector('h2[class*="name"], [class*="prd-name"], [class*="product_name"]')
          name = nameEl?.textContent?.trim() || document.querySelector('meta[property="og:title"]')?.content || ''

          const priceMatch = bodyText.match(/([\d,]+)\s*원\s*\[\d+%\]/)
          if (priceMatch) salePrice = parseInt(priceMatch[1].replace(/,/g, ''), 10)

          const origMatch = bodyText.match(/([\d,]+)\s*원\s+([\d,]+)\s*원/)
          if (origMatch) {
            originalPrice = parseInt(origMatch[1].replace(/,/g, ''), 10)
            if (!salePrice) salePrice = parseInt(origMatch[2].replace(/,/g, ''), 10)
          }

          return {
            success: true,
            site_product_id: prdId,
            name,
            original_price: originalPrice || salePrice,
            sale_price: salePrice || benefitPrice,
            best_benefit_price: benefitPrice,
            images: [],
            source_site: siteName,
          }
        }
      }

      // ── 범용 파싱 ──
      const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]')
      for (const script of jsonLdScripts) {
        try {
          let data = JSON.parse(script.textContent)
          if (Array.isArray(data)) data = data.find(d => d['@type'] === 'Product') || data[0]
          if (data && data['@type'] === 'Product') {
            const offers = data.offers || {}
            const price = Array.isArray(offers) ? parseInt(offers[0]?.price || 0) : parseInt(offers.price || 0)
            const brandObj = data.brand || {}
            const img = Array.isArray(data.image) ? data.image[0] : (data.image || '')
            return {
              success: true, site_product_id: prdId,
              name: data.name || '', original_price: price, sale_price: price,
              images: img ? [img] : [],
              brand: typeof brandObj === 'object' ? (brandObj.name || '') : String(brandObj),
              source_site: siteName,
              category: '', category1: '', category2: '', category3: '',
              options: [], detail_html: '',
            }
          }
        } catch {}
      }
      const ogTitle = document.querySelector('meta[property="og:title"]')?.content || ''
      const ogImage = document.querySelector('meta[property="og:image"]')?.content || ''
      const ogPrice = document.querySelector('meta[property="product:price:amount"]')?.content || ''
      const allTexts = Array.from(document.querySelectorAll('*'))
        .filter(el => el.children.length === 0)
        .map(el => el.textContent.trim())
        .filter(t => t.length > 1)
      const priceTexts = allTexts.filter(t => /^\d[\d,]+원?$/.test(t))
      let salePrice = ogPrice ? parseInt(ogPrice) : 0
      let originalPrice = 0
      for (const pt of priceTexts) {
        const num = parseInt(pt.replace(/[^0-9]/g, ''))
        if (num > 0) {
          if (!salePrice) salePrice = num
          else if (num > salePrice) originalPrice = num
        }
      }
      const images = []
      document.querySelectorAll('img').forEach(img => {
        const src = img.src || img.currentSrc || img.getAttribute('data-src') || ''
        if (src && (src.includes('product') || src.includes('goods') || src.includes('prd')) && !images.includes(src)) {
          images.push(src.startsWith('//') ? 'https:' + src : src)
        }
      })
      const options = []
      document.querySelectorAll('select option, [class*="option"] li, [class*="size"] button, [class*="size"] a').forEach(el => {
        const text = el.textContent.trim()
        if (text && text !== '선택' && text.length < 30) {
          options.push({ name: text, stock: 999 })
        }
      })
      const breadcrumb = document.querySelector('[class*="breadcrumb"], [class*="location"], nav[aria-label="breadcrumb"]')
      let cats = []
      if (breadcrumb) {
        cats = Array.from(breadcrumb.querySelectorAll('a, span, li'))
          .map(el => el.textContent.trim())
          .filter(t => t.length > 1 && t !== '>' && t !== 'Home' && t !== '홈')
      }
      return {
        success: true, site_product_id: prdId,
        name: ogTitle || document.title || `${siteName} ${prdId}`,
        original_price: originalPrice || salePrice, sale_price: salePrice,
        images: images.length > 0 ? images.slice(0, 10) : (ogImage ? [ogImage] : []),
        brand: '', source_site: siteName,
        category: cats.join(' > '), category1: cats[0] || '',
        category2: cats[1] || '', category3: cats[2] || '',
        options, detail_html: '',
      }
      } catch (e) {
        return { success: false, message: `스크립트 에러: ${e.message}`, url: location.href }
      }
    },
    args: [site, productId]
  })

  return result?.result || { success: false, message: 'DOM 파싱 실패' }
}

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
      const alarm = await chrome.alarms.get('collectPoll')
      sendResponse({
        musinsa: { isLoggedIn, cookieCount: cookies.length },
        kream: { isLoggedIn: !!kreamCookie, cookieCount: kreamCookie ? kreamCookie.split(';').length : 0 },
        polling: !!alarm,
        proxyUrl: PROXY_URL,
      })
    })
    return true
  }

  // 수집 폴링 시작/중지
  if (msg.type === 'START_COLLECT_POLLING') {
    startCollectPolling()
    sendResponse({ success: true })
    return false
  }
  if (msg.type === 'STOP_COLLECT_POLLING') {
    stopCollectPolling()
    sendResponse({ success: true })
    return false
  }

  // 백엔드 URL 변경
  if (msg.type === 'SET_PROXY_URL') {
    const url = (msg.url || '').trim().replace(/\/$/, '')
    if (url) {
      PROXY_URL = url
      chrome.storage.local.set({ proxyUrl: url })
      console.log(`[설정] 백엔드 URL 저장: ${PROXY_URL}`)
      sendResponse({ success: true })
    } else {
      sendResponse({ success: false })
    }
    return false
  }

  // KREAM 로그인 페이지 열기
  if (msg.type === 'KREAM_OPEN_LOGIN') {
    chrome.tabs.create({ url: 'https://kream.co.kr/login' })
    sendResponse({ success: true })
    return false
  }

  // 스마트스토어 셀러센터 굿서비스/패널티 점수 스크래핑
  if (msg.type === 'SCRAPE_STORE_SCORES') {
    ;(async () => {
      try {
        // 1. 셀러센터 탭 찾기
        const tabs = await chrome.tabs.query({ url: 'https://sell.smartstore.naver.com/*' })
        let tab = tabs[0]
        if (!tab) {
          // 셀러센터 탭이 없으면 새로 열기
          tab = await chrome.tabs.create({ url: 'https://sell.smartstore.naver.com/#/seller/good-service-score', active: true })
          // 페이지 로딩 대기
          await new Promise(r => setTimeout(r, 3000))
          sendResponse({ success: false, message: '셀러센터를 열었습니다. 로그인 후 다시 버튼을 눌러주세요.' })
          return
        }

        // 2. 굿서비스 페이지로 이동
        await chrome.tabs.update(tab.id, { url: 'https://sell.smartstore.naver.com/#/seller/good-service-score', active: true })
        await new Promise(r => setTimeout(r, 2500))

        // 3. 굿서비스 DOM 스크래핑
        const gsResult = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            // 로그인 체크
            if (document.querySelector('.login_area') || document.body.innerText.includes('로그인')) {
              if (!document.querySelector('.snb_area') && !document.querySelector('.lnb_area')) {
                return { error: 'login_required' }
              }
            }
            // 점수 항목 추출 (텍스트 기반)
            const scores = {}
            const text = document.body.innerText
            // 항목별 점수 추출 패턴
            const items = document.querySelectorAll('[class*="score"], [class*="grade"], [class*="item"], [class*="metric"], tr, li')
            items.forEach(el => {
              const t = el.innerText.trim()
              // "항목명 N점" 또는 "항목명 N" 패턴
              const m = t.match(/^(.+?)\s+(\d+(?:\.\d+)?)\s*점?$/m)
              if (m && m[1].length < 20) {
                scores[m[1].trim()] = parseFloat(m[2])
              }
            })
            // 전체 점수 텍스트도 포함
            const totalMatch = text.match(/(\d+(?:\.\d+)?)\s*점/)
            return { scores, rawText: text.substring(0, 2000), totalMatch: totalMatch ? totalMatch[1] : null }
          }
        })

        const gsData = gsResult?.[0]?.result
        if (gsData?.error === 'login_required') {
          sendResponse({ success: false, message: '셀러센터에 로그인해주세요.' })
          return
        }

        // 4. 패널티 페이지로 이동
        await chrome.tabs.update(tab.id, { url: 'https://sell.smartstore.naver.com/#/seller/policy', active: true })
        await new Promise(r => setTimeout(r, 2500))

        // 5. 패널티 DOM 스크래핑
        const penResult = await chrome.scripting.executeScript({
          target: { tabId: tab.id },
          func: () => {
            const text = document.body.innerText
            // 패널티 점수/비율 추출
            const penaltyMatch = text.match(/(\d+(?:\.\d+)?)\s*점/)
            const rateMatch = text.match(/(\d+(?:\.\d+)?)\s*%/)
            return { rawText: text.substring(0, 2000), penalty: penaltyMatch ? penaltyMatch[1] : null, penaltyRate: rateMatch ? rateMatch[1] : null }
          }
        })

        const penData = penResult?.[0]?.result

        // 6. 서버로 전송
        const accountId = msg.account_id || ''
        const payload = {
          account_id: accountId,
          good_service: gsData?.scores || null,
          penalty: penData?.penalty ? parseFloat(penData.penalty) : null,
          penalty_rate: penData?.penaltyRate ? parseFloat(penData.penaltyRate) : null,
        }

        const resp = await apiFetch(`${PROXY_URL}/api/v1/samba/monitor/store-scores/update`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        const result = await resp.json()

        sendResponse({
          success: true,
          message: '스토어 점수 수집 완료',
          good_service: gsData?.scores,
          penalty: penData?.penalty,
          penalty_rate: penData?.penaltyRate,
        })
      } catch (e) {
        console.error('[스토어점수] 스크래핑 실패:', e)
        sendResponse({ success: false, message: `스크래핑 실패: ${e.message}` })
      }
    })()
    return true
  }

  // 가격/재고 갱신 요청 (프론트에서 확장앱 경유 필요 상품 전달)
  if (msg.type === 'REFRESH_PRODUCTS') {
    const productIds = msg.product_ids || []
    console.log(`[갱신] ${productIds.length}건 갱신 요청 수신`)
    // 현재는 서버에 다시 전달 (KREAM 등 인증 필요 사이트 수집 트리거)
    apiFetch(`${PROXY_URL}/api/v1/samba/collector/products/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_ids: productIds, auto_retransmit: true }),
    })
      .then(r => r.json())
      .then(data => {
        console.log(`[갱신] 결과:`, data)
        sendResponse({ success: true, ...data })
      })
      .catch(e => {
        console.error(`[갱신] 실패:`, e)
        sendResponse({ success: false, message: e.message })
      })
    return true
  }
})

// ==================== ABCmart / GrandStage 잔액 전송 ====================

async function sendAbcmartBalance(data) {
  try {
    const res = await apiFetch(`${PROXY_URL}/api/v1/samba/sourcing-accounts/sync-balance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...data, site: data.siteName }),
    })
    if (res.ok) {
      const result = await res.json()
      console.log(`[잔액] ${data.siteName} 서버 저장 완료:`, result)
    } else {
      console.warn(`[잔액] ${data.siteName} 서버 저장 실패: HTTP ${res.status}`)
    }
  } catch (e) {
    console.log(`[잔액] ${data.siteName} 서버 전송 실패 (무시): ${e.message}`)
  }
}

// ==================== SSG 판매자등급/평점 스크래핑 ====================

async function scrapeSSGScores() {
  const SSG_HOME_URL = 'https://po.ssgadm.com/main.ssg'
  const result = {}

  const allSsgTabs = await chrome.tabs.query({ url: 'https://po.ssgadm.com/*' })
  const homeTabs = allSsgTabs.filter(t => t.url && t.url.includes('main.ssg'))

  let tabId
  if (homeTabs.length > 0) {
    tabId = homeTabs[0].id
  } else if (allSsgTabs.length > 0) {
    tabId = allSsgTabs[0].id
    await chrome.tabs.update(tabId, { url: SSG_HOME_URL, active: true })
    await new Promise(r => setTimeout(r, 5000))
  } else {
    const tab = await chrome.tabs.create({ url: SSG_HOME_URL, active: false })
    tabId = tab.id
    await new Promise(r => setTimeout(r, 7000))
  }

  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const result = {}
        const parseGradeVal = (text) => {
          const m = text.match(/([\d.]+)\s*[%점]/)
          return m ? m[1] : text.trim()
        }
        const rows = document.querySelectorAll('tr')
        for (const row of rows) {
          const cells = row.querySelectorAll('td, th')
          if (cells.length >= 2) {
            const label = (cells[0].textContent || '').trim()
            const value = (cells[1].textContent || '').trim()
            if (label.includes('서비스평점') || label.includes('서비스 평점')) {
              if (!result.ssg_service_score) { const g = value.match(/([\d.]+)/); result.ssg_service_score = g ? g[1] : value }
            } else if (label.includes('주문이행')) {
              if (!result.ssg_order_fulfill) result.ssg_order_fulfill = parseGradeVal(value)
            } else if (label.includes('출고준수')) {
              if (!result.ssg_ship_comply) result.ssg_ship_comply = parseGradeVal(value)
            } else if (label.includes('24시간') || label.includes('답변')) {
              if (!result.ssg_reply_rate) result.ssg_reply_rate = parseGradeVal(value)
            } else if (label.includes('판매등급') || label.includes('판매자등급')) {
              if (!result.ssg_seller_grade) { const g = value.match(/([A-Z가-힣]+)/); result.ssg_seller_grade = g ? g[1] : value }
            }
          }
        }
        if (!result.ssg_service_score) {
          const fullText = document.body.innerText || ''
          const patterns = {
            ssg_service_score: /서비스\s*평점[:\s]*([\d.]+)/,
            ssg_order_fulfill: /주문이행[:\s]*([\d.]+)/,
            ssg_ship_comply: /출고준수[:\s]*([\d.]+)/,
            ssg_reply_rate: /(?:24시간|답변)[:\s]*([\d.]+)/,
            ssg_seller_grade: /판매(?:자)?등급[:\s]*([A-Z가-힣]+)/,
          }
          for (const [key, re] of Object.entries(patterns)) {
            if (!result[key]) { const m = fullText.match(re); if (m) result[key] = m[1] }
          }
        }
        return result
      },
    })
    Object.assign(result, res.result || {})
  } catch (e) {
    console.error(`[SSG스코어] 스크래핑 실패:`, e)
  }

  return result
}

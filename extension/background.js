importScripts('background-core.js')

// ????? ?? ?? - ????? ??? ??

const {
  API_PREFIX,
  CLOUD_URL,
  DEFAULT_PROXY_URL,
  DEFAULT_SELECTORS,
  apiFetch,
  loadSelectors,
  sendSiteCookieToProxy,
} = globalThis.SambaBackgroundCore

let PROXY_URL = DEFAULT_PROXY_URL

// ==================== KREAM ??? ?? (???? ?? ?? ??) ====================

let selectors = { ...DEFAULT_SELECTORS }
loadSelectors(PROXY_URL).then(nextSelectors => {
  selectors = nextSelectors
})

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

// ==================== 롯데ON 쿠키 ====================

let lotteonCookie = ''

// 동기화 스케줄러 (sendCookiesToProxy 정의 후 초기화)
let scheduleCookieSync
let scheduleKreamCookieSync
let scheduleLotteonCookieSync

// 백엔드 URL 변경 감지
chrome.storage.onChanged.addListener((changes) => {
  if (changes.proxyUrl) {
    PROXY_URL = changes.proxyUrl.newValue || DEFAULT_PROXY_URL
    console.log(`[설정] 백엔드 URL 변경: ${PROXY_URL}`)
  }
})

// Service Worker 시작 시 저장된 쿠키 + 설정 복원
chrome.storage.local.get(['capturedCookie', 'capturedAt', 'kreamCookie', 'lotteonCookie', 'proxyUrl']).then(async data => {
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
  // 롯데ON
  if (data.lotteonCookie) {
    lotteonCookie = data.lotteonCookie
    console.log(`[복원] 롯데ON 쿠키 복원: ${lotteonCookie.split(';').length}개`)
    try { await sendLotteonCookiesToProxy(lotteonCookie) } catch {}
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

// 롯데ON webRequest 캡처
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const cookieHeader = details.requestHeaders?.find(
      h => h.name.toLowerCase() === 'cookie'
    )
    if (cookieHeader?.value && cookieHeader.value !== lotteonCookie) {
      lotteonCookie = cookieHeader.value
      chrome.storage.local.set({ lotteonCookie })
      console.log(`[캡처] 롯데ON 쿠키 변경감지 ${lotteonCookie.split(';').length}개`)
      scheduleLotteonCookieSync()
    }
  },
  { urls: ['https://*.lotteon.com/*'] },
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
  return sendSiteCookieToProxy({ proxyUrl: PROXY_URL, site: 'musinsa', cookieStr })
}

async function sendKreamCookiesToProxy(cookieStr) {
  return sendSiteCookieToProxy({ proxyUrl: PROXY_URL, site: 'kream', cookieStr })
}

async function sendLotteonCookiesToProxy(cookieStr) {
  return sendSiteCookieToProxy({ proxyUrl: PROXY_URL, site: 'lotteon', cookieStr })
}

// 동기화 스케줄러 초기화
scheduleCookieSync = makeScheduleSync('무신사', () => capturedCookie, sendCookiesToProxy)
scheduleKreamCookieSync = makeScheduleSync('KREAM', () => kreamCookie, sendKreamCookiesToProxy)
scheduleLotteonCookieSync = makeScheduleSync('롯데ON', () => lotteonCookie, sendLotteonCookiesToProxy)

// ==================== 무신사 잔액 수신 (content script → background → server) ====================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'musinsaBalance') {
    const { money, mileage, username } = msg
    console.log(`[잔액] 무신사 잔액 수신: 머니 ${money?.toLocaleString()} / 적립금 ${mileage?.toLocaleString()} / 유저: ${username}`)
    findMusinsaIdAndSend({ money, mileage, username })
    sendResponse({ ok: true })
  }
  if (msg.action === 'abcmartBalance') {
    const { siteName, money, mileage, username, expired } = msg
    console.log(`[잔액] ${siteName} 잔액 수신: 머니 ${money?.toLocaleString()} / 적립금 ${mileage?.toLocaleString()} / 유저: ${username}`)
    sendAbcmartBalance({ siteName, money, mileage, username, expired: !!expired })
    sendResponse({ ok: true })
  }
  if (msg.action === 'abcmartMembership') {
    const { membershipRate, membershipGrade } = msg
    console.log(`[ABCmart] 멤버십 감지: ${membershipGrade} (${membershipRate}%)`)
    chrome.storage.local.set({ abcmart_membership_rate: membershipRate, abcmart_membership_grade: membershipGrade })
    syncAbcmartMembership(membershipRate, membershipGrade)
    sendResponse({ ok: true })
  }
  if (msg.type === 'SCRAPE_SSG_SCORES') {
    scrapeSSGScores().then(data => sendResponse(data)).catch(e => sendResponse({ error: e.message }))
    return true // 비동기 응답
  }
  return false
})

async function findMusinsaIdAndSend({ money, mileage, username }) {
  let musinsaId = ''
  try {
    const allCookies = await chrome.cookies.getAll({ domain: 'musinsa.com' })
    for (const c of allCookies) {
      if (['mu_id', 'userId', 'member_srl', 'UID', 'uid', 'login_id', 'musinsa_id'].includes(c.name)) {
        musinsaId = decodeURIComponent(c.value)
        break
      }
    }
    if (!musinsaId) {
      for (const c of allCookies) {
        if (/^[a-zA-Z][a-zA-Z0-9]{3,19}$/.test(c.value) && !['JSESSIONID', 'SCOUTER'].includes(c.name)) {
          console.log(`[잔액] 아이디 후보 쿠키: ${c.name}=${c.value}`)
        }
      }
    }
  } catch (e) {
    console.log(`[잔액] 쿠키 조회 실패: ${e.message}`)
  }
  console.log(`[잔액] 무신사 아이디: ${musinsaId || '(쿠키에서 못 찾음)'}`)
  sendMusinsaBalance({ money, mileage, musinsaId, username, cookie: capturedCookie })
}

async function sendMusinsaBalance(data) {
  try {
    const res = await apiFetch(`${PROXY_URL}/api/v1/samba/sourcing-accounts/sync-balance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (res.ok) {
      const result = await res.json()
      console.log(`[잔액] 서버 저장 완료:`, result)
    } else {
      console.warn(`[잔액] 서버 저장 실패: HTTP ${res.status}`)
    }
  } catch (e) {
    console.log(`[잔액] 서버 전송 실패 (무시): ${e.message}`)
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


importScripts('background-kream.js')
importScripts('background-sourcing.js')
importScripts('background-bootstrap.js')
importScripts('background-messages.js')

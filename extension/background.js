// 삼바웨이브 쿠키 연동 - 백그라운드 서비스 워커

const PROXY_URL = 'http://localhost:3001'

// 캡처된 쿠키 (메모리 + storage.local로 영속)
let capturedCookie = ''
let capturedAt = 0

// 디바운스 타이머 — 쿠키 캡처 시 30초 내 중복 전송 방지
let syncTimer = null
function scheduleCookieSync() {
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(async () => {
    syncTimer = null
    if (!capturedCookie) return
    try {
      await sendCookiesToProxy(capturedCookie)
      console.log('[자동동기화] 쿠키 프록시 전송 완료')
    } catch (e) {
      console.log('[자동동기화] 프록시 미실행 (무시)')
    }
  }, 3000)
}

// Service Worker 시작 시 저장된 쿠키 복원 + 즉시 프록시 전송 시도
chrome.storage.local.get(['capturedCookie', 'capturedAt']).then(async data => {
  if (data.capturedCookie) {
    capturedCookie = data.capturedCookie
    capturedAt = data.capturedAt || 0
    console.log(`[복원] 저장된 쿠키 복원: ${capturedCookie.split(';').length}개`)
    // 복원 즉시 프록시 전송 시도 (프록시 미실행이면 무시)
    try {
      await sendCookiesToProxy(capturedCookie)
      console.log('[자동동기화] 시작 시 쿠키 프록시 전송 완료')
    } catch (e) {
      console.log('[자동동기화] 시작 시 프록시 미실행 (무시)')
    }
  }
})

// 무신사로 나가는 모든 요청의 Cookie 헤더 캡처 (httpOnly 포함)
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const cookieHeader = details.requestHeaders?.find(
      h => h.name.toLowerCase() === 'cookie'
    )
    if (cookieHeader?.value && cookieHeader.value.length > capturedCookie.length) {
      capturedCookie = cookieHeader.value
      capturedAt = Date.now()
      // storage.local에 저장 (브라우저 재시작에도 유지)
      chrome.storage.local.set({ capturedCookie, capturedAt })
      const cnt = capturedCookie.split(';').length
      console.log(`[캡처] 무신사 쿠키 ${cnt}개 캡처됨 (${details.url.slice(0, 50)})`)
      // 디바운스로 자동 프록시 전송
      scheduleCookieSync()
    }
  },
  { urls: ['https://*.musinsa.com/*'] },
  ['requestHeaders', 'extraHeaders']
)

// 무신사 쿠키 반환
async function getMusinsaCookies() {
  // storage.local에서 최신 캡처본 확인
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

  // 폴백: cookies API
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

// 프록시 서버에 쿠키 전송
async function sendCookiesToProxy(cookieStr) {
  const res = await fetch(`${PROXY_URL}/api/musinsa/set-cookie`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  return res.json()
}

// 팝업에서 메시지 수신
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'SYNC_COOKIES') {
    getMusinsaCookies().then(async ({ cookies, cookieStr, isLoggedIn }) => {
      if (!isLoggedIn) {
        sendResponse({ success: false, message: '무신사 쿠키가 없습니다. 무신사 페이지에서 아무 곳이나 클릭 후 다시 시도해주세요.' })
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

  if (msg.type === 'GET_STATUS') {
    getMusinsaCookies().then(({ cookies, isLoggedIn, cookieNames }) => {
      sendResponse({ cookieCount: cookies.length, isLoggedIn, cookieNames })
    })
    return true
  }
})

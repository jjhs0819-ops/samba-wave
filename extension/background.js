// 삼바웨이브 쿠키 연동 - 백그라운드 서비스 워커

const PROXY_URL = 'http://localhost:3001'
const MUSINSA_DOMAIN = '.musinsa.com'

// 로그인에 핵심적인 쿠키 이름 목록 (값에 특수문자 없는 토큰류)
const KEY_COOKIE_NAMES = ['app_atk', 'app_rtk', 'one_pc', '_ds_sessions', 'mss_mac', 'mss_last_login', 'SCOUTER', 'NA_SAC']

// 무신사 쿠키 읽기 (핵심 쿠키만 선별)
async function getMusinsaCookies() {
  const all = await chrome.cookies.getAll({ domain: MUSINSA_DOMAIN })

  // 핵심 쿠키 우선, 없으면 전체에서 value가 간단한 것만 포함
  const keyCookies = all.filter(c => KEY_COOKIE_NAMES.includes(c.name) && c.value)
  const others = all.filter(c => !KEY_COOKIE_NAMES.includes(c.name) && c.value && /^[\x20-\x7E]{1,500}$/.test(c.value))
  const cookies = [...keyCookies, ...others]

  const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join('; ')
  return { cookies: all, cookieStr, keyCount: keyCookies.length }
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

// 무신사 로그인 상태 확인
async function checkLoginStatus(cookieStr) {
  const res = await fetch(`${PROXY_URL}/api/musinsa/check-login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: cookieStr })
  })
  return res.json()
}

// 팝업에서 메시지 수신
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'SYNC_COOKIES') {
    getMusinsaCookies().then(async ({ cookies, cookieStr, keyCount }) => {
      if (keyCount === 0) {
        sendResponse({ success: false, message: '무신사에 로그인되어 있지 않습니다. 무신사 사이트에서 먼저 로그인해주세요.' })
        return
      }

      try {
        const result = await sendCookiesToProxy(cookieStr)
        sendResponse({ success: true, cookieCount: cookies.length, keyCount, ...result })
      } catch (e) {
        sendResponse({ success: false, message: `프록시 연결 실패: ${e.message}` })
      }
    })
    return true // 비동기 응답
  }

  if (msg.type === 'GET_STATUS') {
    getMusinsaCookies().then(async ({ cookies, keyCount }) => {
      const isLoggedIn = keyCount > 0
      sendResponse({ cookieCount: cookies.length, isLoggedIn })
    })
    return true
  }
})

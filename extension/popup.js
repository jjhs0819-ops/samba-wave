const PROXY_URL = 'http://localhost:3001'

// 상태 배지 업데이트
function setBadge(id, text, type) {
  const el = document.getElementById(id)
  el.className = `badge badge-${type}`
  el.innerHTML = `<span class="dot"></span>${text}`
}

function setLog(msg, type = '') {
  const el = document.getElementById('logBox')
  el.textContent = msg
  el.className = `log ${type}`
}

// 초기 상태 확인
async function checkStatus() {
  // 무신사 로그인 확인
  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (res) => {
    if (res?.isLoggedIn) {
      setBadge('loginStatus', '로그인됨', 'green')
    } else if (res?.cookieCount > 0) {
      setBadge('loginStatus', '비로그인', 'red')
    } else {
      setBadge('loginStatus', '쿠키 없음', 'red')
    }
  })

  // 프록시 서버 연결 확인
  try {
    const res = await fetch(`${PROXY_URL}/api/health`, { signal: AbortSignal.timeout(2000) })
    if (res.ok || res.status === 404) {
      setBadge('proxyStatus', '실행 중', 'green')
    } else {
      setBadge('proxyStatus', '연결 오류', 'red')
    }
  } catch {
    setBadge('proxyStatus', '미실행', 'red')
  }
}

// 쿠키 동기화
async function syncCookies() {
  const btn = document.getElementById('syncBtn')
  btn.disabled = true
  setLog('쿠키를 읽는 중...', 'loading')

  chrome.runtime.sendMessage({ type: 'SYNC_COOKIES' }, (res) => {
    btn.disabled = false

    if (res?.success) {
      setLog(`완료! 무신사 쿠키 ${res.cookieCount}개를 프록시에 전달했습니다.`, 'success')
      setBadge('loginStatus', '로그인됨', 'green')
    } else {
      setLog(`실패: ${res?.message || '알 수 없는 오류'}`, 'error')

      if (res?.message?.includes('프록시')) {
        setBadge('proxyStatus', '미실행', 'red')
        setLog('프록시 서버가 실행되지 않았습니다. node proxy-server.mjs를 먼저 실행하세요.', 'error')
      }
    }
  })
}

// 무신사 열기
function openMusinsa() {
  chrome.tabs.create({ url: 'https://www.musinsa.com' })
}

// 프록시 열기
function openProxy() {
  chrome.tabs.create({ url: PROXY_URL })
}

// 초기화
document.addEventListener('DOMContentLoaded', checkStatus)

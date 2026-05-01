
// 쿠키 동기화 alarm (5분 주기)
function setupCookieSyncAlarm() {
  chrome.alarms.get('cookieSync', (alarm) => {
    if (!alarm) {
      chrome.alarms.create('cookieSync', { periodInMinutes: 5 })
      console.log('[쿠키] chrome.alarms 설정: 5분 주기 동기화')
    }
  })
}

// alarm 이벤트 핸들러
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'collectPoll') {
    runPollCycle()
  }
  if (alarm.name === 'cookieSync') {
    if (capturedCookie) sendCookiesToProxy(capturedCookie).catch(() => {})
    if (kreamCookie) sendKreamCookiesToProxy(kreamCookie).catch(() => {})
    if (lotteonCookie) sendLotteonCookiesToProxy(lotteonCookie).catch(() => {})
  }
  if (alarm.name === 'balanceCheckPoll') {
    pollBalanceCheckRequest()
  }
  if (alarm.name === 'chromeProfileSyncPoll') {
    pollChromeProfileSyncRequest()
  }
})

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

async function pollChromeProfileSyncRequest() {
  const urls = [
    'http://localhost:28080/api/v1/samba/sourcing-accounts/chrome-profile-sync-requested',
    `${PROXY_URL}/api/v1/samba/sourcing-accounts/chrome-profile-sync-requested`,
  ]
  for (const url of urls) {
    try {
      const r = await apiFetch(url)
      if (r.ok) {
        const data = await r.json()
        if (data.requested) {
          console.log('[크롬프로필] 서버 동기화 요청 감지')
          syncChromeProfile()
          return
        }
      }
    } catch { /* ignore */ }
  }
}

// 잔액 폴링 (5분 주기, 서버에 요청 없으면 아무 동작 안 함)
chrome.alarms.get('balanceCheckPoll', (alarm) => {
  if (!alarm) {
    chrome.alarms.create('balanceCheckPoll', { periodInMinutes: 5 })
  }
})
chrome.alarms.get('chromeProfileSyncPoll', (alarm) => {
  if (!alarm) {
    chrome.alarms.create('chromeProfileSyncPoll', { periodInMinutes: 0.5 })
  }
})

// ==================== 크롬 프로필 동기화 ====================

async function syncChromeProfile() {
  try {
    const info = await chrome.identity.getProfileUserInfo({ accountStatus: 'ANY' })
    if (!info.email) {
      console.log('[프로필동기화] 이메일 없음 (Google 계정 로그인 필요)')
      return
    }
    console.log(`[프로필동기화] 이메일: ${info.email}, gaia_id: ${info.id}`)
    const body = JSON.stringify({
      email: info.email,
      gaia_id: info.id || '',
      display_name: info.email.split('@')[0],
    })
    const headers = { 'Content-Type': 'application/json' }

    // 클라우드 서버에 전송
    try {
      await apiFetch(
        `${CLOUD_URL}/api/v1/samba/sourcing-accounts/sync-chrome-profile`,
        { method: 'POST', headers, body }
      )
    } catch (e) {
      console.warn('[프로필동기화] 클라우드 전송 실패:', e.message)
    }

    // 로컬 서버에도 전송 (로컬 개발 환경)
    if (PROXY_URL !== CLOUD_URL) {
      try {
        const res = await apiFetch(
          `${PROXY_URL}/api/v1/samba/sourcing-accounts/sync-chrome-profile`,
          { method: 'POST', headers, body }
        )
        if (res.ok) {
          console.log('[프로필동기화] 완료')
        }
      } catch (e) {
        console.log('[프로필동기화] 로컬 서버 없음 (무시):', e.message)
      }
    }
  } catch (e) {
    console.log(`[프로필동기화] 오류 (무시): ${e.message}`)
  }
}

// 사이트별 백그라운드 세션 탭 자동 보장 — 익스텐션 시작 시 1회 실행.
// 사용자가 popup의 "이 PC가 처리할 사이트"에 체크한 사이트에 한해 백그라운드 탭 자동 생성.
// 웨일/Chrome 모두 호환 (pinned:true 의존 X). 핀탭 대신 일반 탭(active:false) 활용.
async function ensureBackgroundSessionTabs() {
  try {
    const data = await chrome.storage.local.get(['allowedSites'])
    const sites = Array.isArray(data.allowedSites) ? data.allowedSites : null
    // allowedSites 미설정(null) → 단일 PC 디폴트, 자동 생성 X (사용자가 명시 선택해야 함)
    // 빈 배열 → 작업 안 받는 PC, 자동 생성 X
    if (!sites || sites.length === 0) return
    if (typeof ensureSiteSessionTab !== 'function') return
    // 사용자 보고 — 확장앱 설치/업데이트만 했는데 메인 페이지 자동으로 뜨는 게 거슬림.
    // 모든 사이트의 세션 탭을 lazy 생성으로 변경:
    //   - ABCmart 멤버십가 in-tab fetch 필요 시 fetchAbcmartBenefitPrice → ensureArtTab → 자동 생성
    //   - LOTTEON 자동로그인 / 쿠키 동기화 시 자동 생성
    //   - SSG는 비로그인 무관 (애초에 불필요)
    // 즉 사전 생성 없이 실제 작업 시점에만 탭 1개 생성 — 사용자 눈에 띄는 깜빡임 최소화.
    // (필요한 사이트가 추가되면 ensureSiteSessionTab을 호출하는 코드 경로에서 자동 처리)
  } catch (e) {
    console.warn('[세션탭] 초기화 실패:', e.message)
  }
}

// 설치/업데이트 시
chrome.runtime.onInstalled.addListener(() => {
  setupCookieSyncAlarm()
  startCollectPolling()
  syncChromeProfile()
  ensureBackgroundSessionTabs()
})
chrome.runtime.onStartup.addListener(() => {
  setupCookieSyncAlarm()
  startCollectPolling()
  syncChromeProfile()
  ensureBackgroundSessionTabs()
})
setupCookieSyncAlarm()
startCollectPolling()
pollChromeProfileSyncRequest()
syncChromeProfile()
ensureBackgroundSessionTabs()

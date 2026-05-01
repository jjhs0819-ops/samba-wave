
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
    // SSG는 카드혜택가가 비로그인에서도 동일하게 노출되어 세션 탭 불필요
    // (사용자가 메인 페이지가 자동으로 뜨는 게 거슬린다고 보고 — 구매페이지만 띄우면 충분)
    const SESSION_TAB_REQUIRED_SITES = new Set(['ABCmart', 'GrandStage', 'LOTTEON'])
    for (const site of sites) {
      if (!SESSION_TAB_REQUIRED_SITES.has(site)) continue
      try {
        await ensureSiteSessionTab(site)
      } catch (e) {
        console.warn(`[세션탭] ${site} 생성 실패: ${e.message}`)
      }
    }
  } catch (e) {
    console.warn('[세션탭] 초기화 실패:', e.message)
  }
}

// 설치/업데이트 시
// 사용자 보고 — install/load 시점에 ABCmart/LOTTEON 메인 탭이 자동으로 떠서 거슬림.
// ensureBackgroundSessionTabs() 호출 제거 — "오토튠 시작" 클릭 시점에만 로그인 트리거 (background-sourcing.js의 _checkAutotuneStartTransition 참조).
chrome.runtime.onInstalled.addListener(() => {
  setupCookieSyncAlarm()
  startCollectPolling()
  syncChromeProfile()
})
chrome.runtime.onStartup.addListener(() => {
  setupCookieSyncAlarm()
  startCollectPolling()
  syncChromeProfile()
})
setupCookieSyncAlarm()
startCollectPolling()
pollChromeProfileSyncRequest()
syncChromeProfile()

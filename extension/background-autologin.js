// 사이트 자동 로그인 엔진
// kream-auto-review v5.2.10 service-worker.js의 _ensureLoggedInSingle 패턴 이식
// Chrome/웨일 비밀번호 관리자에 저장된 첫 번째 계정으로 자동 로그인 수행
//
// 핵심 트릭:
//  1. autocomplete="off" / "new-password" 강제 해제 + 페이지 리로드 → Chrome 자동완성 재평가 유도
//  2. chrome.debugger triple-click(clickCount 1→2→3) → 자동완성 값을 .value에 확정 (Chrome 보안 우회)
//  3. :-webkit-autofill 감지 시 form POST 폴백 (.value 빈 경우)
//  4. chrome.debugger Input.dispatchMouseEvent → trusted click으로 로그인 버튼 클릭
//
// 의존성: background-kream.js의 waitForTabLoad, wait, pauseCollectPolling

const AUTO_LOGIN_SITES = {
  musinsa: {
    name: '무신사',
    loginUrl: 'https://www.musinsa.com/auth/login',
    checkUrl: 'https://www.musinsa.com/mypage/myreview',
    isLoginPage: url => url.includes('/auth/login') || url.includes('member.one.musinsa.com/login') || (url.includes('/login') && url.includes('musinsa')),
    loginButtonSelector: 'button[type="submit"], button.login-btn, form button',
  },
  kream: {
    name: 'KREAM',
    loginUrl: 'https://kream.co.kr/login',
    checkUrl: 'https://kream.co.kr/my/reviews?tab=to_write',
    isLoginPage: url => url.includes('/login'),
    loginButtonSelector: 'button.btn.full.solid, button[type="submit"], .login_btn, button.btn_login',
  },
  abcmart: {
    name: 'ABC마트',
    loginUrl: 'https://abcmart.a-rt.com/login',
    checkUrl: 'https://abcmart.a-rt.com/mypage/claim/claim-order-main?orderPrdtStatCodeClick=10007',
    isLoginPage: url => url.includes('/login'),
    loginButtonSelector: '#login, input#login, button[type="submit"], .btn_login, button.login',
  },
  lotteon: {
    name: '롯데ON',
    loginUrl: 'https://www.lotteon.com/p/member/login/common',
    checkUrl: 'https://www.lotteon.com/p/review/myLotte/reviewWriteListTab',
    isLoginPage: url => url.includes('/login') || url.includes('/member/login'),
    loginButtonSelector: 'button[type="submit"], .btn_login, #loginBtn',
  },
  ssg: {
    name: 'SSG',
    loginUrl: 'https://member.ssg.com/m/member/login.ssg',
    checkUrl: 'https://www.ssg.com/myssg/activityMng/pdtEvalList.ssg?quick=pdtEvalList',
    isLoginPage: url => url.includes('login.ssg') || url.includes('/member/login'),
    loginButtonSelector: 'button[type="submit"], .btn_login, #btn_login',
  },
  gs: {
    name: 'GS샵',
    loginUrl: 'https://www.gsshop.com/cust/login/login.gs',
    checkUrl: 'https://www.gsshop.com/ord/dlvcursta/ordList.gs',
    isLoginPage: url => url.includes('login.gs') || url.includes('/login'),
    loginButtonSelector: '#btnLogin, button[type="submit"], .btn_login, #loginBtn',
  },
}

// 사이트별 자동 로그인 상태 (중복 호출 차단 + 실패 누적 추적)
const autoLoginState = {
  inProgress: {},
  lastAttemptAt: {},
  failedAttempts: {},
  cooldownUntil: {},
}

const AUTO_LOGIN_MAX_RETRIES = 3
const AUTO_LOGIN_COOLDOWN_MS = 5 * 60 * 1000 // 5분간 재시도 차단 (실패 누적 후)
const AUTO_LOGIN_PAUSE_MS = 90 * 1000 // 자동로그인 진행 중 폴링 일시중지 시간

// 오토튠 활성 상태 캐시 — 자동로그인 트리거 전에 체크하여 오토튠 OFF 상태에서는 작동 안 함
let _alAutotuneActiveCache = { value: null, at: 0 }
const _AL_AUTOTUNE_CACHE_MS = 5000

async function _isAutotuneActive() {
  const now = Date.now()
  if (_alAutotuneActiveCache.value !== null && now - _alAutotuneActiveCache.at < _AL_AUTOTUNE_CACHE_MS) {
    return _alAutotuneActiveCache.value
  }
  try {
    const stored = await chrome.storage.local.get('proxyUrl')
    const proxyUrl = stored.proxyUrl || 'https://api.samba-wave.co.kr'
    const res = await fetch(`${proxyUrl}/api/v1/samba/collector/autotune/status`, {
      method: 'GET',
    })
    if (!res.ok) return _alAutotuneActiveCache.value
    const data = await res.json()
    const active = !!data.running
    _alAutotuneActiveCache = { value: active, at: now }
    return active
  } catch (e) {
    console.log(`[자동로그인] 오토튠 상태 조회 실패 (무시): ${e.message}`)
    return _alAutotuneActiveCache.value
  }
}

function alExternalSiteToKey(externalSite) {
  // background-sourcing.js에서 쓰는 사이트 키를 자동로그인 키로 매핑
  // 'ABCmart' / 'GrandStage' → 'abcmart', 'LOTTEON' → 'lotteon', 'SSG' → 'ssg', 'MUSINSA' → 'musinsa', 'KREAM' → 'kream', 'GSShop' → 'gs'
  const map = {
    ABCmart: 'abcmart',
    GrandStage: 'abcmart',
    LOTTEON: 'lotteon',
    SSG: 'ssg',
    MUSINSA: 'musinsa',
    KREAM: 'kream',
    GSShop: 'gs',
  }
  return map[externalSite] || null
}

// 진입점 — 외부에서 자동로그인을 트리거할 때 호출 (3회 재시도)
async function ensureLoggedIn(siteKey) {
  const site = AUTO_LOGIN_SITES[siteKey]
  if (!site) {
    console.log(`[자동로그인] 미지원 사이트: ${siteKey}`)
    return false
  }

  // 오토튠 비활성 상태면 자동로그인 차단 (사용자가 작업 취소했는데 계속 시도되는 것 방지)
  // 백엔드 status API의 running 필드 기준 — 5초 캐시
  const autotuneActive = await _isAutotuneActive()
  if (autotuneActive === false) {
    console.log(`[자동로그인] ${site.name} 트리거 차단 — 오토튠 비활성 상태`)
    return false
  }

  // 중복 호출 차단 — 이미 진행 중이면 즉시 false
  if (autoLoginState.inProgress[siteKey]) {
    console.log(`[자동로그인] ${site.name} 이미 진행 중 — 무시`)
    return false
  }

  // 쿨다운 체크 — 실패 누적 후 일정 시간 차단
  const cooldownUntil = autoLoginState.cooldownUntil[siteKey] || 0
  if (Date.now() < cooldownUntil) {
    const remainSec = Math.ceil((cooldownUntil - Date.now()) / 1000)
    console.log(`[자동로그인] ${site.name} 쿨다운 중 (${remainSec}초 남음) — 무시`)
    return false
  }

  autoLoginState.inProgress[siteKey] = true
  autoLoginState.lastAttemptAt[siteKey] = Date.now()

  // 자동로그인 진행 중에는 폴링 일시중지 (탭 폭주 차단)
  try {
    if (typeof pauseCollectPolling === 'function') {
      pauseCollectPolling(AUTO_LOGIN_PAUSE_MS, `auto-login ${site.name}`)
    }
  } catch {}

  try {
    let ok = false
    for (let attempt = 1; attempt <= AUTO_LOGIN_MAX_RETRIES; attempt++) {
      console.log(`[자동로그인] ${site.name} 시도 (${attempt}/${AUTO_LOGIN_MAX_RETRIES})`)
      ok = await _ensureLoggedInSingle(siteKey)
      if (ok) break
      if (attempt < AUTO_LOGIN_MAX_RETRIES) {
        await wait(3000)
      }
    }

    if (ok) {
      autoLoginState.failedAttempts[siteKey] = 0
      autoLoginState.cooldownUntil[siteKey] = 0
      // 자동로그인 성공 시각 기록 — sourcing detail의 _detectLoginStatus false-positive 방지용
      // (LOTTEON 상세페이지처럼 헤더 셀렉터로 로그인 판정 어려운 사이트의 무한 트리거 차단)
      try { globalThis._lastAutoLoginSuccessAt = globalThis._lastAutoLoginSuccessAt || {} } catch {}
      try { globalThis._lastAutoLoginSuccessAt[siteKey] = Date.now() } catch {}
      console.log(`[자동로그인] ✅ ${site.name} 성공 — 폴링 자동 재개`)
    } else {
      autoLoginState.failedAttempts[siteKey] = (autoLoginState.failedAttempts[siteKey] || 0) + 1
      autoLoginState.cooldownUntil[siteKey] = Date.now() + AUTO_LOGIN_COOLDOWN_MS
      console.log(`[자동로그인] ❌ ${site.name} ${AUTO_LOGIN_MAX_RETRIES}회 실패 — ${AUTO_LOGIN_COOLDOWN_MS / 60000}분 쿨다운`)
      try {
        chrome.notifications?.create?.(`autologin-fail-${siteKey}-${Date.now()}`, {
          type: 'basic',
          iconUrl: 'icon128.png',
          title: 'SAMBA-WAVE 자동로그인 실패',
          message: `${site.name} 자동 로그인이 실패했습니다. 브라우저에서 수동 로그인해주세요. (5분 후 자동 재시도)`,
        })
      } catch {}
    }
    return ok
  } finally {
    autoLoginState.inProgress[siteKey] = false
  }
}

// 단일 사이트 로그인 시도
async function _ensureLoggedInSingle(siteKey) {
  const site = AUTO_LOGIN_SITES[siteKey]
  if (!site) return false

  // 무신사/KREAM/ABC마트는 보안 스크립트가 무거워 타임아웃 30초
  // 롯데ON은 Vue SPA로 폼 동적 렌더링 + 로그인 후 리다이렉트가 느림 → 30초
  const LOGIN_TIMEOUT = (siteKey === 'musinsa' || siteKey === 'kream' || siteKey === 'abcmart' || siteKey === 'lotteon') ? 30000 : 15000
  // SPA 사이트는 로그인 페이지 HTML이 빈 div 뿐, JS로 input이 동적 렌더링됨
  // → reload하면 Chrome autofill 후보 0개로 결정되어 영구 미발동 → reload 스킵하고 동적 렌더링 대기
  const IS_SPA_LOGIN = (siteKey === 'lotteon')
  const POLL_INTERVAL = 2000

  let tabId = null
  let tabCreated = false

  try {
    // 1) checkUrl(마이페이지)로 이동 → 비로그인이면 로그인 페이지로 자동 리다이렉트
    // [중요] 사용자 메인 창의 active 탭을 뺏지 않도록 별도 minimized window로 띄움
    // (chrome.debugger triple-click은 비활성/최소화 창에서도 정상 동작 — 포커스 불필요)
    let win = null
    try {
      win = await chrome.windows.create({ url: site.checkUrl, focused: false, state: 'minimized', type: 'normal' })
    } catch (e) {
      console.log(`[자동로그인] ${site.name} windows.create 실패 → 탭 폴백: ${e?.message || e}`)
    }
    let tab = null
    if (win && Array.isArray(win.tabs) && win.tabs.length) {
      tab = win.tabs[0]
    } else {
      tab = await chrome.tabs.create({ url: site.checkUrl, active: false })
    }
    tabId = tab.id
    tabCreated = true

    try { await waitForTabLoad(tabId, 30000) } catch {}
    await wait(1500) // 리다이렉트 완료 대기

    let tabInfo = await chrome.tabs.get(tabId)
    let currentUrl = tabInfo.url || ''

    // 이미 로그인 상태면 즉시 종료
    if (!site.isLoginPage(currentUrl)) {
      console.log(`[자동로그인] ${site.name} 이미 로그인됨`)
      try { await chrome.tabs.remove(tabId) } catch {}
      return true
    }

    // 2) 명시적으로 로그인 페이지로 이동
    if (!site.isLoginPage(currentUrl)) {
      await chrome.tabs.update(tabId, { url: site.loginUrl })
      try { await waitForTabLoad(tabId, 30000) } catch {}
    }

    // STEP A-pre: SPA 사이트는 input이 동적 렌더링될 때까지 폴링 대기 (최대 10초)
    // 롯데ON 등 Vue/React SPA는 로드 직후 <div id="app"></div>만 있음 → input 등장 대기 필수
    if (IS_SPA_LOGIN) {
      const SPA_WAIT_MAX = 10000
      const SPA_POLL = 300
      const spaStart = Date.now()
      let inputAppeared = false
      while (Date.now() - spaStart < SPA_WAIT_MAX) {
        try {
          const [r] = await chrome.scripting.executeScript({
            target: { tabId },
            func: () => {
              const visible = (el) => el && el.offsetParent !== null
              const id = document.querySelector('input[type="email"], input[type="text"]:not([type="hidden"])')
              const pw = document.querySelector('input[type="password"]')
              return { idVisible: visible(id), pwVisible: visible(pw) }
            },
          })
          if (r?.result?.idVisible && r?.result?.pwVisible) {
            inputAppeared = true
            console.log(`[자동로그인] ${site.name} SPA input 렌더링 감지 (${Date.now() - spaStart}ms)`)
            break
          }
        } catch {}
        await wait(SPA_POLL)
      }
      if (!inputAppeared) {
        console.log(`[자동로그인] ${site.name} SPA input 렌더링 타임아웃 (10초) — 진행은 계속`)
      }
    }

    // STEP A: autocomplete 차단 강제 해제
    // 일반 사이트: 속성 수정 후 reload → Chrome이 새 autocomplete 보고 autofill 재평가
    // SPA 사이트(롯데ON): reload 금지 — reload하면 input이 사라져 Chrome autofill 후보 0개로 결정되어 영구 미발동
    //   대신 input.dispatchEvent로 mutation 트리거하여 Chrome이 동적 변경을 감지하도록 유도
    try {
      const [acResult] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (isSpa) => {
          let changed = 0
          document.querySelectorAll('input[autocomplete="off"]').forEach(inp => {
            if (inp.type === 'email' || inp.type === 'text') {
              inp.setAttribute('autocomplete', 'username email')
              changed++
            } else if (inp.type === 'password') {
              inp.setAttribute('autocomplete', 'current-password')
              changed++
            }
          })
          // ABC마트 등 "new-password"로 자동완성 차단하는 사이트 대응
          document.querySelectorAll('input[autocomplete="new-password"]').forEach(inp => {
            if (inp.type === 'password') {
              inp.setAttribute('autocomplete', 'current-password')
              changed++
            }
          })
          document.querySelectorAll('input:not([autocomplete])').forEach(inp => {
            if (inp.type === 'text' && (inp.name === 'username' || inp.name === 'userId' || inp.name === 'id' || inp.id === 'username')) {
              inp.setAttribute('autocomplete', 'username')
              changed++
            } else if (inp.type === 'password' && !inp.getAttribute('autocomplete')) {
              inp.setAttribute('autocomplete', 'current-password')
              changed++
            }
          })
          // SPA: 속성 변경 후 input event 발화로 Chrome autofill 재평가 유도
          if (isSpa && changed > 0) {
            document.querySelectorAll('input[type="text"], input[type="email"], input[type="password"]').forEach(inp => {
              try {
                inp.dispatchEvent(new Event('focus', { bubbles: true }))
                inp.dispatchEvent(new Event('blur', { bubbles: true }))
              } catch {}
            })
          }
          return changed
        },
        args: [IS_SPA_LOGIN],
      })
      const acChanged = acResult?.result || 0
      if (acChanged > 0) {
        if (IS_SPA_LOGIN) {
          console.log(`[자동로그인] ${site.name} autocomplete ${acChanged}개 필드 강제 해제 (SPA: reload 스킵, mutation 이벤트로 유도)`)
          await wait(1500)
        } else {
          console.log(`[자동로그인] ${site.name} autocomplete ${acChanged}개 필드 강제 해제 → 리로드`)
          await chrome.tabs.reload(tabId)
          try { await waitForTabLoad(tabId, 30000) } catch {}
          await wait(1500)
        }
      }
    } catch (e) {
      console.log(`[자동로그인] autocomplete 해제 실패 (무시): ${e.message}`)
    }

    // STEP B: 아이디 필드 chrome.debugger triple-click → 자동완성 값을 .value에 확정
    try {
      const [posResult] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (key) => {
          // autocomplete 차단이 다시 설정되는 사이트 대응 — 한 번 더 해제
          document.querySelectorAll('input[autocomplete="off"]').forEach(inp => {
            if (inp.type === 'email' || inp.type === 'text') inp.setAttribute('autocomplete', 'username email')
            else if (inp.type === 'password') inp.setAttribute('autocomplete', 'current-password')
          })
          document.querySelectorAll('input[autocomplete="new-password"]').forEach(inp => {
            if (inp.type === 'password') inp.setAttribute('autocomplete', 'current-password')
          })

          let idField = null
          if (key === 'kream') {
            idField = document.querySelector('input[type="email"]')
          } else if (key === 'abcmart') {
            idField = document.querySelector('input#username, input[name="username"]')
          } else {
            idField = document.querySelector('input[type="email"], input#id, input[name="id"], input[name="userId"], input[name="username"], input[name="email"], input#username')
            if (!idField) {
              idField = Array.from(document.querySelectorAll('input[type="text"]')).find(i => i.offsetParent !== null)
            }
          }
          if (idField) {
            const r = idField.getBoundingClientRect()
            return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true }
          }
          return { found: false }
        },
        args: [siteKey],
      })

      const idPos = posResult?.result
      if (idPos?.found) {
        await _alTripleClick(tabId, idPos.x, idPos.y)
        console.log(`[자동로그인] ${site.name} 아이디 필드 triple-click 완료`)

        // SPA(롯데ON): 여러 계정이 저장되어 있어 Chrome autofill 드롭다운이 표시됨
        // ID 필드에 표시된 "edelvise06"은 preview일 뿐, 항목 선택 전에는 PW가 채워지지 않음
        // → ArrowDown(첫 항목 하이라이트) + Enter(선택 확정)로 드롭다운 키보드 선택
        // → Chrome이 ID + PW 모두 확정 입력
        if (IS_SPA_LOGIN) {
          await wait(800) // 드롭다운 렌더링 대기
          try {
            const target = { tabId }
            await chrome.debugger.attach(target, '1.3')
            // ArrowDown: 드롭다운 첫 항목 하이라이트 (이미 첫 항목이 preview로 ID 채웠음)
            await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
              type: 'rawKeyDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown',
            })
            await wait(50)
            await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
              type: 'keyUp', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40, key: 'ArrowDown', code: 'ArrowDown',
            })
            await wait(200)
            // Enter: 선택 확정 → Chrome 비번 매니저가 ID + PW 모두 채움
            await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
              type: 'rawKeyDown', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, key: 'Enter', code: 'Enter',
            })
            await wait(50)
            await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
              type: 'keyUp', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, key: 'Enter', code: 'Enter',
            })
            await chrome.debugger.detach(target)
            console.log(`[자동로그인] ${site.name} ArrowDown+Enter 발화 (autofill 드롭다운 첫 항목 선택)`)
            await wait(1500) // Chrome 비번 매니저가 ID+PW 채우는 시간
          } catch (kbErr) {
            try { await chrome.debugger.detach({ tabId }) } catch {}
            console.log(`[자동로그인] 드롭다운 선택 실패 (무시): ${kbErr.message}`)
          }
        }
      } else {
        console.log(`[자동로그인] ${site.name} 아이디 필드 미발견`)
      }
    } catch (e) {
      console.log(`[자동로그인] 아이디 필드 클릭 실패 (무시): ${e.message}`)
    }

    // STEP C: 비밀번호 필드도 triple-click으로 .value 확정
    try {
      const [pwPosResult] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          const pwField = document.querySelector('input[type="password"]')
          if (pwField) {
            const r = pwField.getBoundingClientRect()
            return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true }
          }
          return { found: false }
        },
      })
      const pwPos = pwPosResult?.result
      if (pwPos?.found) {
        await _alTripleClick(tabId, pwPos.x, pwPos.y)
        console.log(`[자동로그인] ${site.name} 비밀번호 필드 triple-click 완료`)
      }
    } catch (e) {
      console.log(`[자동로그인] 비밀번호 필드 클릭 실패 (무시): ${e.message}`)
    }

    // 자동완성 값 반영 대기 (SPA는 더 길게)
    const autoFillWait = (siteKey === 'musinsa' || siteKey === 'kream' || siteKey === 'abcmart') ? 4000 : (IS_SPA_LOGIN ? 4000 : 2500)
    await wait(autoFillWait)

    // input/change 이벤트 강제 발화 — 사이트 유효성 검사가 자동완성 값을 인식하도록 유도
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          document.querySelectorAll('input[type="text"], input[type="email"], input[type="password"]').forEach(inp => {
            if (inp.value && inp.offsetParent !== null) {
              inp.dispatchEvent(new Event('input', { bubbles: true }))
              inp.dispatchEvent(new Event('change', { bubbles: true }))
            }
          })
        },
      })
    } catch {}

    // 진단: 로그인 버튼 클릭 직전 input 상태 로그 (다음 디버깅 시 즉시 원인 판별용)
    try {
      const [diag] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          const af = (el) => { try { return !!el?.matches?.(':-webkit-autofill') } catch { return false } }
          const id = document.querySelector('input[type="email"], input#id, input[name="id"], input[name="userId"], input[name="username"], input#username')
          const pw = document.querySelector('input[type="password"]')
          return {
            id_found: !!id, id_vlen: id?.value?.length || 0, id_af: af(id),
            pw_found: !!pw, pw_vlen: pw?.value?.length || 0, pw_af: af(pw),
          }
        },
      })
      const d = diag?.result || {}
      console.log(`[자동로그인][진단] ${site.name} 클릭 직전 — id(found=${d.id_found},vlen=${d.id_vlen},af=${d.id_af}) pw(found=${d.pw_found},vlen=${d.pw_vlen},af=${d.pw_af})`)
    } catch {}

    // STEP D: :-webkit-autofill 감지 → form POST 폴백 (.value 빈 경우 ABC마트 등)
    try {
      const [autofillResult] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          const username = document.querySelector('input#username, input[name="username"], input[name="userId"], input#id, input[type="email"]')
          const password = document.querySelector('input[type="password"]')
          if (!username || !password) return { autofilled: false, reason: 'fields_not_found' }

          let isAutofilled = false
          try {
            isAutofilled = username.matches(':-webkit-autofill') && password.matches(':-webkit-autofill')
          } catch {}

          const valueEmpty = !username.value && !password.value
          if (!isAutofilled || !valueEmpty) {
            return { autofilled: false, isAutofilled, valueEmpty }
          }

          const form = username.closest('form')
          if (!form) return { autofilled: true, noForm: true }

          form.method = 'POST'
          form.onsubmit = null
          form.removeAttribute('onsubmit')

          const loginBtn = document.querySelector('#login') || form.querySelector('input[type="button"]') || form.querySelector('button')
          const submitBtn = document.createElement('input')
          submitBtn.type = 'submit'
          submitBtn.value = '로그인'
          submitBtn.id = '__sambaAutoLoginSubmit__'

          if (loginBtn) {
            const rect = loginBtn.getBoundingClientRect()
            submitBtn.style.cssText = `position: fixed; left: ${rect.left}px; top: ${rect.top}px; width: ${rect.width}px; height: ${rect.height}px; z-index: 99999; opacity: 0.01; cursor: pointer;`
            document.body.appendChild(submitBtn)
          } else {
            form.appendChild(submitBtn)
          }

          const r = submitBtn.getBoundingClientRect()
          return {
            autofilled: true,
            formPatched: true,
            submitPos: { x: r.left + r.width / 2, y: r.top + r.height / 2 },
          }
        },
      })

      const af = autofillResult?.result
      if (af?.formPatched && af?.submitPos) {
        console.log(`[자동로그인] ${site.name} :-webkit-autofill 감지 — form POST 폴백 시도`)
        const target = { tabId }
        try {
          await chrome.debugger.attach(target, '1.3')
          await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
            type: 'mousePressed', x: af.submitPos.x, y: af.submitPos.y, button: 'left', clickCount: 1,
          })
          await wait(50)
          await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
            type: 'mouseReleased', x: af.submitPos.x, y: af.submitPos.y, button: 'left', clickCount: 1,
          })
          await chrome.debugger.detach(target)
          await wait(5000)
          tabInfo = await chrome.tabs.get(tabId)
          currentUrl = tabInfo.url || ''
          if (currentUrl && !site.isLoginPage(currentUrl)) {
            console.log(`[자동로그인] ✅ ${site.name} form POST 폴백 성공`)
            try { await chrome.tabs.remove(tabId) } catch {}
            return true
          }
          console.log(`[자동로그인] form POST 폴백 후에도 로그인 페이지 — 일반 클릭 폴백`)
        } catch (dbgErr) {
          console.log(`[자동로그인] form POST debugger 오류: ${dbgErr.message}`)
          try { await chrome.debugger.detach({ tabId }) } catch {}
        }
      }
    } catch (e) {
      console.log(`[자동로그인] STEP D 오류 (무시): ${e.message}`)
    }

    // 4) 로그인 버튼 클릭 + 폴링으로 성공 여부 확인
    let buttonClicked = false
    const startTime = Date.now()
    while (Date.now() - startTime < LOGIN_TIMEOUT) {
      // 진행 중 오토튠 비활성 감지 시 즉시 중단 (사용자가 작업 취소한 경우)
      const stillActive = await _isAutotuneActive()
      if (stillActive === false) {
        console.log(`[자동로그인] ${site.name} 진행 중 오토튠 취소 감지 → 즉시 중단`)
        try { await chrome.tabs.remove(tabId) } catch {}
        return false
      }

      if (!buttonClicked) {
        try {
          const btnSelector = site.loginButtonSelector || 'button[type="submit"]'

          // 0) 로그인 버튼 disabled 강제 해제 (KREAM 등 빈 필드면 disabled되는 사이트 대응)
          await chrome.scripting.executeScript({
            target: { tabId },
            func: (selector) => {
              const selectors = selector.split(',').map(s => s.trim())
              for (const sel of selectors) {
                const btn = document.querySelector(sel)
                if (btn && btn.disabled) {
                  btn.disabled = false
                  btn.classList.remove('disabled')
                }
              }
              for (const b of document.querySelectorAll('button[disabled], input[disabled]')) {
                const txt = (b.textContent || b.value || '').trim()
                if (txt === '로그인' || txt === 'Login' || txt === '로그인하기') {
                  b.disabled = false
                  b.classList.remove('disabled')
                }
              }
            },
            args: [btnSelector],
          })

          // 1) 로그인 버튼 좌표 계산
          const [posResult] = await chrome.scripting.executeScript({
            target: { tabId },
            func: (selector) => {
              const selectors = selector.split(',').map(s => s.trim())
              for (const sel of selectors) {
                const btn = document.querySelector(sel)
                if (btn && btn.getBoundingClientRect().width > 0) {
                  const r = btn.getBoundingClientRect()
                  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
                }
              }
              for (const b of document.querySelectorAll('button, input[type="submit"], input[type="button"], a.btn, div[role="button"]')) {
                const txt = (b.textContent || b.value || '').trim()
                if (txt === '로그인' || txt === 'Login' || txt === 'Sign in' || txt === '로그인하기') {
                  const r = b.getBoundingClientRect()
                  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
                }
              }
              return null
            },
            args: [btnSelector],
          })

          const pos = posResult?.result
          if (pos) {
            // 2) chrome.debugger trusted click + alert 자동 닫기
            const target = { tabId }
            try {
              await chrome.debugger.attach(target, '1.3')
              await chrome.debugger.sendCommand(target, 'Page.enable', {})
              const dialogHandler = (src, method, params) => {
                if (src.tabId === tabId && method === 'Page.javascriptDialogOpening') {
                  console.log(`[자동로그인] alert 자동 닫기: "${(params?.message || '').substring(0, 50)}"`)
                  chrome.debugger.sendCommand(target, 'Page.handleJavaScriptDialog', { accept: true }).catch(() => {})
                }
              }
              chrome.debugger.onEvent.addListener(dialogHandler)

              await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mousePressed', x: pos.x, y: pos.y, button: 'left', clickCount: 1,
              })
              await wait(50)
              await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
                type: 'mouseReleased', x: pos.x, y: pos.y, button: 'left', clickCount: 1,
              })
              await wait(500)
              chrome.debugger.onEvent.removeListener(dialogHandler)
              await chrome.debugger.detach(target)
              console.log(`[자동로그인] ${site.name} 로그인 버튼 trusted click 완료`)
            } catch (dbgErr) {
              console.log(`[자동로그인] debugger 클릭 실패 (${dbgErr.message}) — 일반 click 폴백`)
              try { await chrome.debugger.detach(target) } catch {}
              await chrome.scripting.executeScript({
                target: { tabId },
                func: (x, y) => {
                  const el = document.elementFromPoint(x, y)
                  if (el) el.click()
                },
                args: [pos.x, pos.y],
              })
            }
            buttonClicked = true
            await wait(3000)
          } else {
            console.log(`[자동로그인] ${site.name} 로그인 버튼 미발견`)
            buttonClicked = true
          }
        } catch {
          buttonClicked = true
        }
      }

      await wait(POLL_INTERVAL)

      try {
        tabInfo = await chrome.tabs.get(tabId)
        currentUrl = tabInfo.url || ''
        if (!site.isLoginPage(currentUrl)) {
          console.log(`[자동로그인] ✅ ${site.name} 로그인 성공 — 탭 닫음`)
          try { await chrome.tabs.remove(tabId) } catch {}
          return true
        }
      } catch {
        return false
      }
    }

    console.log(`[자동로그인] ${site.name} 타임아웃 (${LOGIN_TIMEOUT / 1000}초)`)
    return false
  } catch (err) {
    console.error(`[자동로그인] ${site.name} 예외:`, err.message)
    return false
  } finally {
    if (tabCreated && tabId) {
      try { await chrome.tabs.remove(tabId) } catch {}
    }
  }
}

// chrome.debugger triple-click — 텍스트 전체선택 → Chrome이 자동완성 값을 .value에 확정
// (단순 click이나 Tab 키로는 .value가 빈 문자열로 유지되는 Chrome 보안 정책 우회)
async function _alTripleClick(tabId, x, y) {
  const target = { tabId }
  try {
    await chrome.debugger.attach(target, '1.3')
    for (let cc = 1; cc <= 3; cc++) {
      await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
        type: 'mousePressed', x, y, button: 'left', clickCount: cc,
      })
      await wait(30)
      await chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
        type: 'mouseReleased', x, y, button: 'left', clickCount: cc,
      })
      await wait(50)
    }
    await wait(300)
    await chrome.debugger.detach(target)
  } catch (e) {
    try { await chrome.debugger.detach(target) } catch {}
    // 폴백: JS focus/click (자동완성 트리거가 약하지만 일부 사이트는 작동)
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        func: (cx, cy) => {
          const el = document.elementFromPoint(cx, cy)
          if (el) { el.focus(); el.click() }
        },
        args: [x, y],
      })
    } catch {}
    throw e
  }
}

// 외부 모듈에서 사용 가능하도록 globalThis에 노출
globalThis.ensureLoggedIn = ensureLoggedIn
globalThis.alExternalSiteToKey = alExternalSiteToKey
globalThis.AUTO_LOGIN_SITES = AUTO_LOGIN_SITES

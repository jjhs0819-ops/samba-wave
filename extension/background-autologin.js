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
    loginUrl: 'https://abcmart.a-rt.com/login?track=W0005', // [2026-06-29] 홈 로그인링크 실측(?track=W0005).
    // /member/login=404(헤더만 뜸), 맨 /login=로그인상태면 홈 리다이렉트 → 로그아웃 후 진입하면 폼 정상(loginId/loginPwd)
    checkUrl: 'https://abcmart.a-rt.com/mypage/claim/claim-order-main?orderPrdtStatCodeClick=10007',
    isLoginPage: url => url.includes('/login'),
    loginButtonSelector: '#btnLogin, button#btnLogin, button[type="submit"], .btn_login',
  },
  member: {
    // [2026-06-29] ABC-CAMP 멤버십(member.a-rt.com) — abcmart.a-rt.com 과 로그인 세션 분리.
    // 출석체크(abcmart_attendance)가 member 도메인이라 별도 자동로그인 필요. 폼은 abcmart 와 동일(loginId/loginPwd) 추정.
    name: 'ABC멤버십',
    loginUrl: 'https://member.a-rt.com/p/login', // /login 은 server-error 리다이렉트 → /p/login 이 실제 폼
    checkUrl: 'https://member.a-rt.com/p/attendance-check',
    isLoginPage: url => url.includes('/p/login'),
    loginButtonSelector: '#btnLogin, button#btnLogin, button[type="submit"], .btn_login',
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
    // [2026-06-06] m/member(모바일) 페이지가 로그인폼 제거됨 — 검색창(search_shpp)만 렌더링돼
    // selector 매칭 실패 → SSG 자동로그인 전건 실패 → 송장 timeout. PC URL(/member/login.ssg)
    // 엔 로그인폼 정상(CDP 실측 hasIdPw=true) → m/ 제거.
    loginUrl: 'https://member.ssg.com/member/login.ssg',
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
  fashionplus: {
    name: '패션플러스',
    loginUrl: 'https://www.fashionplus.co.kr/auth/login',
    checkUrl: 'https://www.fashionplus.co.kr/mypage/order',
    isLoginPage: url => url.includes('/auth/login') && url.includes('fashionplus'),
    // JS 소스 분석 확인: input#login_id, input[type="password"], button.mm_btn.__btn_lg_primary__
    loginButtonSelector: 'button.mm_btn.__btn_lg_primary__, button[type="submit"], .btn_login',
  },
  thehyundai: {
    // [2026-09-01] hi.thehyundai.com 실측값 (브라우저 확인):
    //   로그인 페이지 = /login (/front/member/login.thd 는 404 — 쓰지 말 것)
    //   아이디 = input[name="loginId"] / 비밀번호 = input[name="password"]
    //   로그인 버튼 = <button type="button">로그인</button> — class 는 CSS-module 해시라
    //   빌드마다 바뀜 → class 셀렉터 금지, 텍스트 폴백('로그인')이 잡는다.
    //   Next.js SPA 라 input 이 늦게 렌더링됨 → SPA_INPUT_WAIT_SITES 에도 등록.
    name: '더현대',
    loginUrl: 'https://hi.thehyundai.com/login',
    checkUrl: 'https://hi.thehyundai.com/mypage',
    isLoginPage: url => /hi\.thehyundai\.com\/login/.test(url),
    loginButtonSelector: 'button[type="submit"], .btn_login', // 해시 class 금지 — 실제로는 텍스트 폴백('로그인')이 잡는다
  },
  // ⚠️ [라이브 보정] 11번가 가구매용 자동로그인 — 로그인 URL·셀렉터 전부 추정값(SHOW PASS 소스 없음).
  // 실제 11번가 로그인 페이지에서 확인 후 보정 필요.
  '11st': {
    name: '11번가',
    loginUrl: 'https://login.11st.co.kr/auth/v2/login.tmall',
    checkUrl: 'https://www.11st.co.kr/',
    isLoginPage: url => url.includes('login.11st') || url.includes('/login'),
    loginButtonSelector: 'button[type="submit"], .btn_login, #loginButton, button.login',
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
const AUTO_LOGIN_PAUSE_MS = 15 * 1000 // 자동로그인 진행 중 폴링 일시중지 시간

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
    const proxyUrl = stored.proxyUrl || ''
    // X-Api-Key 헤더 자동 부착하는 apiFetch 사용 (raw fetch는 ApiGatewayMiddleware에 의해 403)
    const apiFetch = globalThis.SambaBackgroundCore?.apiFetch
    const res = apiFetch
      ? await apiFetch(`${proxyUrl}/api/v1/samba/collector/autotune/status`, { method: 'GET' })
      : await fetch(`${proxyUrl}/api/v1/samba/collector/autotune/status`, { method: 'GET' })
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

// 자동로그인 키 → 백엔드 SambaSourcingAccount.site_name 매핑 (라디오로 지정한 기본 계정 조회용)
const _AL_SITE_NAME_MAP = {
  lotteon: 'LOTTEON',
  abcmart: 'ABCmart',
  ssg: 'SSG',
  musinsa: 'MUSINSA',
  kream: 'KREAM',
  gs: 'GSShop',
  '11st': '11ST',
  thehyundai: 'TheHyundai',
  // [2026-08-13] ABC-CAMP 멤버십(member.a-rt.com)은 ABC마트와 같은 통합회원 계정을 쓴다.
  // 이 매핑이 없어 site_name 이 undefined → 자격증명 조회 null → 출석체크 자동로그인이
  // 시도조차 안 되고 비로그인 탭만 열렸다 닫혔다(계정ID 없이 오는 라디오 기본계정 모드).
  member: 'ABCmart',
}

// 백엔드 fetch — 자격증명 조회.
// accountId 제공 시 해당 계정 단건(주문 매칭 계정), 없으면 site_name 라디오 기본 계정.
async function _fetchLoginCredential(siteKey, accountId) {
  const siteName = _AL_SITE_NAME_MAP[siteKey]
  if (!siteName && !accountId) return null
  try {
    const stored = await chrome.storage.local.get('proxyUrl')
    const proxyUrl = stored.proxyUrl || ''
    const apiFetch = globalThis.SambaBackgroundCore?.apiFetch
    if (!apiFetch) return null
    const qs = accountId
      ? `account_id=${encodeURIComponent(accountId)}`
      : `site_name=${encodeURIComponent(siteName)}`
    const res = await apiFetch(
      `${proxyUrl}/api/v1/samba/sourcing-accounts/login-credential?${qs}`,
      { method: 'GET' }
    )
    if (!res.ok) return null  // 404면 미지정/미존재
    return await res.json()
  } catch (e) {
    console.log(`[자동로그인] 자격증명 조회 실패 (무시): ${e.message}`)
    return null
  }
}

// [2026-06-07] SSG 쿠키 도메인 클리어 강제 로그아웃.
// SSG logout.ssg URL 이 에러 페이지("원하셨던 페이지가 아닌가요")를 응답 → 세션이 안 끊겨
// 계정 전환 실패 → 로그인폼 미표시 → 송장 timeout. 데몬 v1.4.29 와 동일하게 쿠키를 직접
// 비워 강제 로그아웃한다. (getAll({domain:'ssg.com'})은 ssg.com + 모든 서브도메인 포함)
async function _clearSsgCookies() {
  return await _clearCookiesByDomain('ssg.com')
}

// 도메인(+서브도메인) 쿠키 전체 삭제 — 로그아웃 URL 이 없거나 안 먹는 사이트의 강제 로그아웃.
async function _clearCookiesByDomain(domain) {
  let n = 0
  try {
    const cookies = await chrome.cookies.getAll({ domain })
    for (const ck of cookies) {
      const host = ck.domain.replace(/^\./, '')
      const proto = ck.secure ? 'https' : 'http'
      try {
        await chrome.cookies.remove({ url: `${proto}://${host}${ck.path}`, name: ck.name })
        n++
      } catch {}
    }
  } catch (e) {
    console.warn(`[자동로그인][SPA] ${domain} 쿠키 클리어 실패: ${e?.message || e}`)
  }
  return n
}

// ── SSG 계정별 세션 재사용 (2026-06-10, 데몬 account_sessions.json 패턴 이식) ──
// SSG는 잦은 자동 로그인 자체를 "비정상 자동접근"으로 감지해 계정을 잠근다(비번 정확해도 잠김).
// → fresh 로그인 횟수 최소화가 본질: 성공 세션 쿠키를 계정별로 저장하고, 계정 스왑 시
//   저장 세션을 복원해 로그인 상태면 로그인 POST 자체를 생략한다.
let _ssgAccountSessions = null // accountId → cookies[] (storage lazy load)
let _ssgLastLoginAccount = '' // 현재 ssg.com 세션의 계정 (storage 동기화)

async function _loadSsgSessionState() {
  if (_ssgAccountSessions !== null) return
  try {
    const st = await chrome.storage.local.get(['_ssgAccountSessions', '_ssgLastLoginAccount'])
    _ssgAccountSessions = st._ssgAccountSessions || {}
    _ssgLastLoginAccount = st._ssgLastLoginAccount || ''
  } catch {
    _ssgAccountSessions = {}
  }
}

async function _saveSsgSession(accountId) {
  if (!accountId) return
  try {
    await _loadSsgSessionState()
    const cookies = await chrome.cookies.getAll({ domain: 'ssg.com' })
    if (!cookies.length) return
    _ssgAccountSessions[accountId] = cookies
    _ssgLastLoginAccount = accountId
    await chrome.storage.local.set({ _ssgAccountSessions, _ssgLastLoginAccount: accountId })
    console.log(`[자동로그인][SSG] 세션 저장 (acc=${accountId}, 쿠키 ${cookies.length}개) — 재로그인 최소화`)
  } catch (e) {
    console.warn(`[자동로그인][SSG] 세션 저장 실패(무시): ${e?.message || e}`)
  }
}

// 저장 세션 복원 — 현 쿠키 클리어 후 대상 계정 쿠키 주입. 복원할 세션 있으면 true.
async function _restoreSsgSession(accountId) {
  try {
    await _loadSsgSessionState()
    const saved = _ssgAccountSessions?.[accountId]
    await _clearSsgCookies() // 옛/다른 계정 세션 제거
    if (!saved || !saved.length) return false
    for (const ck of saved) {
      const host = ck.domain.replace(/^\./, '')
      const p = {
        url: `${ck.secure ? 'https' : 'http'}://${host}${ck.path}`,
        name: ck.name,
        value: ck.value,
        path: ck.path,
        secure: ck.secure,
        httpOnly: ck.httpOnly,
      }
      if (ck.domain.startsWith('.')) p.domain = ck.domain
      if (ck.sameSite && ck.sameSite !== 'unspecified') p.sameSite = ck.sameSite
      if (ck.expirationDate) p.expirationDate = ck.expirationDate
      try { await chrome.cookies.set(p) } catch {}
    }
    return true
  } catch (e) {
    console.warn(`[자동로그인][SSG] 세션 복원 실패(무시): ${e?.message || e}`)
    return false
  }
}

// SSG 로그인 상태 확인 — SW fetch(쿠키 자동 포함). 비로그인이면 member.ssg.com 로그인 리다이렉트.
async function _isSsgLoggedIn() {
  try {
    const res = await fetch(AUTO_LOGIN_SITES.ssg.checkUrl, { redirect: 'follow', credentials: 'include' })
    return !AUTO_LOGIN_SITES.ssg.isLoginPage(res.url || '')
  } catch {
    return false
  }
}

// ── 계정별 로그인 실패 차단 (데몬 _login_fail_count/_failed_login_accounts 패턴 이식) ──
// 잠긴/비번 틀린 계정에 잡마다 재로그인하면 SSG 잠금이 영구화 → 30분 쿨다운 + 5회 영구차단.
// accountId 명시(송장수집) 호출에도 적용 — 기존 사이트 단위 쿨다운은 accountId 시 우회됐음.
const _ACCOUNT_FAIL_COOLDOWN_MS = 30 * 60 * 1000
const _ACCOUNT_FAIL_MAX = 5
// 5회 누적 차단 뒤에도 마지막 실패로부터 이 시간이 지나면 1회만 재시도(probe) 허용.
// 이게 없으면 데드락: 차단이 로그인 시도 자체를 막는데, 카운터 해제는 로그인
// 성공 시에만 되므로(_clearAccountLoginFail) 성공이 영원히 발생할 수 없다.
// probe 성공 시 기존 경로로 카운터 클리어, 실패 시 at 갱신으로 다시 24h 차단
// (로그인 폭주 없음 — 계정당 24h에 1회). 원래 취지(잠긴/비번틀린 계정에 잡마다
// 재로그인 → 사이트 잠금 영구화 방지)는 그대로 보존된다.
const _ACCOUNT_FAIL_PROBE_MS = 24 * 60 * 60 * 1000
let _accountLoginFail = null // `${siteKey}::${accountId}` → { count, at } (storage 영속)

async function _loadAccountLoginFail() {
  if (_accountLoginFail !== null) return
  try {
    const st = await chrome.storage.local.get('_accountLoginFail')
    _accountLoginFail = st._accountLoginFail || {}
  } catch {
    _accountLoginFail = {}
  }
}

// [2026-09-01] reason(선택) — 마지막 실패 원인을 lastReason 에 보존해 차단 메시지에 노출.
// "왜" 실패했는지(입력필드 못찾음/자격증명 오류/계정 잠금 등) 진단용. 기존 저장 데이터에
// lastReason 이 없어도 옵셔널이라 깨지지 않는다.
async function _recordAccountLoginFail(siteKey, accountId, reason) {
  if (!accountId) return
  await _loadAccountLoginFail()
  const k = `${siteKey}::${accountId}`
  const cur = _accountLoginFail[k] || { count: 0, at: 0 }
  _accountLoginFail[k] = {
    count: cur.count + 1,
    at: Date.now(),
    lastReason: reason ? String(reason).slice(0, 160) : (cur.lastReason || ''),
  }
  try { await chrome.storage.local.set({ _accountLoginFail }) } catch {}
}

async function _clearAccountLoginFail(siteKey, accountId) {
  if (!accountId) return
  await _loadAccountLoginFail()
  const k = `${siteKey}::${accountId}`
  if (_accountLoginFail[k]) {
    delete _accountLoginFail[k]
    try { await chrome.storage.local.set({ _accountLoginFail }) } catch {}
  }
}

// 차단 상태 조회 — null(허용) / 차단 사유 문자열
async function _accountLoginBlocked(siteKey, accountId) {
  if (!accountId) return null
  await _loadAccountLoginFail()
  const rec = _accountLoginFail[`${siteKey}::${accountId}`]
  if (!rec) return null
  if (rec.count >= _ACCOUNT_FAIL_MAX) {
    // 마지막 실패로부터 24h 경과 → probe 1회 허용(null 반환).
    // 성공 시 _clearAccountLoginFail 로 해제, 실패 시 _recordAccountLoginFail 가
    // at 을 갱신하므로 다시 24h 차단된다. 스테일 차단(마지막 실패가 오래전)은
    // 배포 즉시 probe 대상이 되어 수동 조치 없이 자가치유된다.
    const sinceLast = Date.now() - rec.at
    if (sinceLast >= _ACCOUNT_FAIL_PROBE_MS) {
      return null
    }
    const remainH = Math.ceil((_ACCOUNT_FAIL_PROBE_MS - sinceLast) / 3600000)
    const _why = rec.lastReason ? ` (마지막 사유: ${rec.lastReason})` : '' // 옛 데이터엔 없을 수 있음 — 옵셔널
    return `로그인 ${rec.count}회 누적 실패 — 차단 중(${remainH}시간 후 자동 재시도, 성공 1회로 해제)${_why}`
  }
  const elapsed = Date.now() - rec.at
  if (elapsed < _ACCOUNT_FAIL_COOLDOWN_MS) {
    const _why = rec.lastReason ? ` (마지막 사유: ${rec.lastReason})` : ''
    return `로그인 실패 쿨다운 ${Math.ceil((_ACCOUNT_FAIL_COOLDOWN_MS - elapsed) / 60000)}분 남음 (누적 ${rec.count}/${_ACCOUNT_FAIL_MAX}회)${_why}`
  }
  return null
}

// [2026-09-01] 팝업 '자동로그인 차단 해제' 버튼 — 확장앱 로컬 실패 카운터(_accountLoginFail)를
// 즉시 리셋한다. (사이트 계정 잠금이 아니라 확장앱 자체 24h 차단/30분 쿨다운 해제용)
// 메모리 캐시 + storage 둘 다 비워야 하므로 background 에서 처리.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'CLEAR_LOGIN_BLOCK') {
    ;(async () => {
      let cleared = 0
      try {
        await _loadAccountLoginFail()
        cleared = Object.keys(_accountLoginFail || {}).length
      } catch {}
      _accountLoginFail = {} // 모듈 메모리 캐시 리셋
      try { await chrome.storage.local.remove('_accountLoginFail') } catch {}
      console.log(`[자동로그인] 차단 카운터 수동 해제 — ${cleared}건 리셋 (팝업 버튼)`)
      sendResponse({ ok: true, cleared })
    })()
    return true // async sendResponse
  }
  return false
})

// 직전 _spaDirectLogin 의 치명적 실패 정보 — 자격증명 오류/계정 잠금은 재시도 무의미(잠금만 갱신).
// _ensureLoggedInImpl 재시도 루프가 이 플래그를 보고 즉시 중단한다.
let _spaLoginFatal = null // { reason: 'locked'|'credential', message }

// [2026-09-01] 비치명(fatal 아님) 실패의 마지막 원인 — _recordAccountLoginFail 에 넘겨
// 차단 메시지에 "왜 실패했는지"를 남긴다. _spaDirectLogin/_ensureLoggedInSingle 이 갱신.
let _spaLoginLastReason = null

// SPA 직접 로그인 — Chrome 자동완성 의존 없이 .value 직접 설정 + button.click()
// LOTTEON / ABCmart / SSG처럼 vanilla input + form submit 구조의 사이트에서 작동
// (검증 완료: 가짜 자격증명으로도 click()이 서버 응답까지 도달함을 확인)
async function _spaDirectLogin(siteKey, username, password) {
  const site = AUTO_LOGIN_SITES[siteKey]
  if (!site) return false
  _spaLoginFatal = null
  _spaLoginLastReason = null

  // [계정 전환] 정식 로그아웃 URL 호출 → 서버가 세션 expire + Set-Cookie 로 클라 쿠키 정리.
  // 쿠키 직접 삭제는 서버 세션 잔존 + localStorage 잔여 + 무신사 보안 비정상 패턴 감지 위험.
  const _LOGOUT_URLS = {
    musinsa: 'https://www.musinsa.com/auth/logout',
    ssg: 'https://www.ssg.com/comm/login/logout.ssg',
    lotteon: 'https://www.lotteon.com/p/member/logout',
    abcmart: 'https://abcmart.a-rt.com/member/logout',
  }
  if (siteKey === 'ssg') {
    // [2026-06-07] SSG 는 logout URL 이 에러 페이지라 세션이 안 끊김 → 쿠키 직접 클리어로 강제.
    const _cleared = await _clearSsgCookies()
    await wait(800)
    console.log(`[자동로그인][SPA] SSG 쿠키 클리어 강제 로그아웃 (${_cleared}개, logout URL 에러 회피)`)
  } else if (siteKey === 'member') {
    // [2026-08-13] ABC-CAMP(member.a-rt.com)는 로그아웃 URL 이 확인된 게 없다.
    // 다른 계정 세션이 살아있으면 /p/login 이 폼을 안 그리고 튕겨서(통합회원) 로그인 폼 미발견
    // → 자동로그인 실패 → 비로그인으로 출첵창만 열렸다 닫힘. a-rt.com 쿠키를 통째로 비워
    // 확실히 로그아웃한 뒤 잡 계정으로 새로 로그인한다.
    // (abcmart.a-rt.com 세션도 같이 끊기지만, ABC마트 잡은 자체 ensureLoggedIn 으로 복구된다)
    const _cleared = await _clearCookiesByDomain('a-rt.com')
    await wait(800)
    console.log(`[자동로그인][SPA] ABC캠프 a-rt.com 쿠키 클리어 강제 로그아웃 (${_cleared}개)`)
  } else if (siteKey === 'thehyundai') {
    // [2026-09-01] 더현대는 확인된 로그아웃 URL 이 없다(추측 URL 금지 원칙) →
    // thehyundai.com 쿠키 전체 클리어로 강제 로그아웃 후 새 계정으로 로그인한다.
    const _cleared = await _clearCookiesByDomain('thehyundai.com')
    await wait(800)
    console.log(`[자동로그인][SPA] 더현대 thehyundai.com 쿠키 클리어 강제 로그아웃 (${_cleared}개)`)
  } else {
    const _logoutUrl = _LOGOUT_URLS[siteKey]
    if (_logoutUrl) {
      let logoutTabId = null
      try {
        const logoutTab = await chrome.tabs.create({ url: _logoutUrl, active: false })
        logoutTabId = logoutTab.id
        try { await waitForTabLoad(logoutTabId, 15000) } catch {}
        await wait(1500)  // 로그아웃 처리 + Set-Cookie 적용 대기
        console.log(`[자동로그인][SPA] ${site.name} 정식 로그아웃 완료 (계정 전환 위해)`)
      } catch (e) {
        console.warn(`[자동로그인][SPA] 로그아웃 호출 실패: ${e?.message || e}`)
      } finally {
        if (logoutTabId) {
          try { await chrome.tabs.remove(logoutTabId) } catch {}
        }
      }
    }
  }

  let tabId = null
  let tabCreated = false

  try {
    // 로그인 페이지 — 기존 브라우저 새 탭으로 오픈 (minimized window 사용 X, 사용자 요구사항)
    const tab = await chrome.tabs.create({ url: site.loginUrl, active: false })
    tabId = tab.id
    tabCreated = true

    try { await waitForTabLoad(tabId, 30000) } catch {}
    await wait(2000)

    // SPA 사이트는 input이 동적 렌더링 — input 등장까지 폴링 (최대 10초)
    // 무신사는 /auth/login → member.one.musinsa.com/login 리다이렉트 후 SPA 렌더링됨
    // 패션플러스는 로그인 페이지에 쿠폰/캠페인 팝업이 다수 떠 무겁고, 로그인 폼(#login_id 등)이
    // SPA 로 늦게 렌더링됨 → 2초 고정대기론 "fields not found" 로 자동로그인 실패. 폴링 대기 추가.
    // [2026-09-03] 대기 조건을 '아무 text/password input' → '그 사이트의 진짜 로그인칸'으로 교체.
    // 더현대는 백그라운드 탭(active:false)에서 Next.js 렌더가 느려 10초 안에 로그인칸이 안 떠
    // 'fields not found'(=입력필드 못찾음)로 실패했다 — 실측 09-01~09-02 더현대 송장 전량 실패.
    // 또한 헤더 검색창 같은 다른 text input 이 먼저 뜨면 옛 조건은 '준비됨'으로 조기 통과했다.
    // 최대 대기 10초 → 25초 (칸이 먼저 뜨면 즉시 빠져나오므로 정상 사이트엔 비용 0).
    const SPA_INPUT_WAIT_SITES = ['musinsa', 'lotteon', 'fashionplus', 'thehyundai', 'abcmart', 'member']
    if (SPA_INPUT_WAIT_SITES.includes(siteKey)) {
      const spaStart = Date.now()
      const SPA_WAIT_MAX = 25000
      const probe = SPA_INPUT_PROBE[siteKey] || null
      while (Date.now() - spaStart < SPA_WAIT_MAX) {
        try {
          const [r] = await chrome.scripting.executeScript({
            target: { tabId },
            func: (probeArg) => {
              // offsetParent 는 position:fixed 요소에서 null 이라 가시성 판정에 쓰면 오판한다.
              // 실제 렌더 여부는 getClientRects() 로 본다.
              const shown = el => !!(el && el.getClientRects().length > 0)
              if (probeArg) {
                return shown(document.querySelector(probeArg[0])) && shown(document.querySelector(probeArg[1]))
              }
              const id = document.querySelector('input[type="email"], input[type="text"]:not([type="hidden"])')
              const pw = document.querySelector('input[type="password"]')
              return shown(id) && shown(pw)
            },
            args: [probe],
          })
          if (r?.result) {
            console.log(`[자동로그인][SPA] ${site.name} input 렌더링 감지 (${Date.now() - spaStart}ms)`)
            break
          }
        } catch {}
        await wait(300)
      }
      if (Date.now() - spaStart >= SPA_WAIT_MAX) {
        console.warn(`[자동로그인][SPA] ${site.name} ${SPA_WAIT_MAX / 1000}초 대기에도 로그인칸 미등장 — 그대로 진행`)
      }
    }

    // alert dialog 자동 닫기 핸들러 — chrome.debugger Page.handleJavaScriptDialog
    // (가짜 자격증명 또는 잘못된 자격증명 시 alert로 에러 메시지 노출됨, freeze 방지용)
    const target = { tabId }
    let dialogAttached = false
    let dialogMessage = null
    try {
      await chrome.debugger.attach(target, '1.3')
      await chrome.debugger.sendCommand(target, 'Page.enable', {})
      dialogAttached = true
      const dialogHandler = (src, method, params) => {
        if (src.tabId === tabId && method === 'Page.javascriptDialogOpening') {
          dialogMessage = params?.message || ''
          console.log(`[자동로그인][SPA] alert 닫기: "${dialogMessage.substring(0, 80)}"`)
          chrome.debugger.sendCommand(target, 'Page.handleJavaScriptDialog', { accept: true }).catch(() => {})
        }
      }
      chrome.debugger.onEvent.addListener(dialogHandler)

      // 사이트별 셀렉터 + .value 직접 설정 + event dispatch + button.click()
      const scriptResults = await chrome.scripting.executeScript({
        target: { tabId, allFrames: true }, // 로그인 폼이 iframe(ABC마트 통합멤버십 등) 안일 수 있어 전 프레임 실행
        func: (siteKeyArg, usernameArg, passwordArg) => {
          // 사이트별 input/button 셀렉터
          const SELECTORS = {
            lotteon: {
              id: ['#inId', 'input[name="inId"]'],
              pw: ['#Password', 'input[type="password"]'],
              btnId: '[data-cmpnt-name="login_btn_select"]',
            },
            abcmart: {
              // [2026-09-03 실측] abcmart.a-rt.com/login?track=W0005 폼이 다시 바뀌었다.
              //   현재: id=#username(name=username) / pw=#password(name=password) / 버튼=#login(type=button)
              //   06-29 에 넣은 #loginId/#loginPwd/#btnLogin 은 이제 **존재하지 않는다**
              //   → '입력필드 못찾음' 으로 ABC 송장이 계속 실패했다(09-02~03 실측 40건+).
              // ⚠️ 이 페이지엔 **비회원 주문조회** 칸(#orderNo/#orderPw)이 같이 있다.
              //    generic 'input[type=password]' 을 폴백에 두면 orderPw 를 잡아 엉뚱한 로그인
              //    시도가 누적된다(계정 잠금 위험) → generic 폴백을 두지 않는다.
              id: ['#username', 'input[name="username"]', '#loginId', 'input[name="loginId"]'],
              pw: ['#password', 'input[name="password"]', '#loginPwd', 'input[name="loginPwd"]'],
              btnId: '#login, button#login, #btnLogin, button#btnLogin',
            },
            member: {
              // [2026-09-03 실측] member.a-rt.com/p/login — abcmart 와 폼이 **다르다**.
              //   id=#id / pw=#pw / 버튼=#loginBtn (name 속성 없음, id 만 있음)
              //   기존 #loginId/#loginPwd 추정값은 전부 빗나갔다.
              id: ['#id', '#username', '#loginId'],
              pw: ['#pw', '#password', '#loginPwd'],
              btnId: '#loginBtn, button#loginBtn, #login, #btnLogin',
            },
            ssg: {
              // member.ssg.com 실측(2026-06-08, CDP 9222): id="mem_id" name="mbrLoginId" /
              //   pw id="mem_pw" name="password" / 버튼은 id="loginBtn" 이 2개(숨김 div + 진짜 button).
              // [중요·2026-06-08] '#loginBtn' querySelector 는 숨김 <div id="loginBtn">(visible:false)를
              //   먼저 잡아 .click() 무반응 → SSG 로그인 전건 실패 → 송장 26일 정지. 데몬은 v1.4.22에서
              //   동일 버그 고쳤으나(button#loginBtn) 확장앱 auto-login은 누락돼 있었음.
              //   → 태그 한정 'button#loginBtn' 을 맨 앞에 둬 숨김 div 를 건너뛴다.
              id: ['#mem_id', 'input[name="mbrLoginId"]', '#inp_id', '#userId', 'input[name="userId"]', 'input[name="usrId"]', 'input[type="email"]'],
              pw: ['#mem_pw', 'input[name="password"]', '#inp_pw', 'input[type="password"]'],
              btnId: 'button#loginBtn, button[type="submit"], #btn_login, .btn_login',
            },
            musinsa: {
              // member.one.musinsa.com/login — SPA, selector 실측 불가 → 흔한 패턴 다 등록
              // 첫 매칭 input 사용. 첫 실행 시 콘솔 로그에서 어떤 selector가 매칭됐는지 확인.
              id: [
                '#id', '#userId', '#loginId', '#email',
                'input[name="id"]', 'input[name="userId"]', 'input[name="loginId"]', 'input[name="email"]', 'input[name="memberId"]',
                'input[type="email"]', 'input[type="text"]:not([type="hidden"])',
              ],
              pw: ['#password', '#userPw', '#loginPw', 'input[name="password"]', 'input[name="pw"]', 'input[type="password"]'],
              btnId: 'button[type="submit"], button.login-btn, button.btn-login, #loginBtn',
              btnText: '로그인',
            },
            fashionplus: {
              // www.fashionplus.co.kr/auth/login — JS 소스 분석 확인:
              //   id=input#login_id / pw=input[type=password] / 버튼=button.mm_btn.__btn_lg_primary__
              // 셀렉터가 빗나가도 아래 폼-폴백(pw 폼 안 text input) + 버튼 전역탐색이 커버.
              id: ['#login_id', 'input[name="login_id"]', 'input[name="userId"]', 'input[name="id"]', 'input[type="text"]:not([type="hidden"])'],
              pw: ['input[type="password"]', '#login_pw', 'input[name="password"]', 'input[name="passwd"]'],
              btnId: 'button.mm_btn.__btn_lg_primary__, button[type="submit"], .btn_login',
              btnText: '로그인',
            },
            thehyundai: {
              // [2026-09-01] hi.thehyundai.com/login 실측: input[name="loginId"](placeholder="아이디") /
              // input[name="password"]. 버튼은 <button type="button">로그인</button> 인데 class 가
              // CSS-module 해시(빌드마다 변경)라 class 셀렉터 금지 → btnText('로그인') 텍스트 폴백이 잡는다.
              id: ['input[name="loginId"]', 'input[type="text"]:not([type="hidden"])'],
              pw: ['input[name="password"]', 'input[type="password"]'],
              btnId: 'button[type="submit"], .btn_login',
              btnText: '로그인',
            },
          }
          const sel = SELECTORS[siteKeyArg]
          if (!sel) return { success: false, error: 'unsupported site' }

          // ID/PW 필드 찾기 — 첫 매칭 셀렉터 사용 + 디버그 로그
          let idField = null
          let idSelMatched = null
          for (const s of sel.id) {
            const el = document.querySelector(s)
            if (el) { idField = el; idSelMatched = s; break }
          }
          let pwField = null
          let pwSelMatched = null
          for (const s of sel.pw) {
            const el = document.querySelector(s)
            if (el) { pwField = el; pwSelMatched = s; break }
          }
          // [2026-06-29] ID 폴백 — pw는 찾았는데 id 못 찾으면(WebFetch가 id 필드명만 잘못 준 케이스):
          // pw 필드와 같은 form 안의 '보이는 text/tel/email input 중 검색창 아닌 첫 번째'를 ID 필드로 사용.
          if (!idField && pwField) {
            const scope = pwField.closest('form') || document
            const cand = Array.from(scope.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input:not([type])'))
              .find(i => i.offsetParent !== null && i.id !== 'searchBar' && i.name !== 'searchWord' && i.id !== 'brandSearch')
            if (cand) { idField = cand; idSelMatched = `(form-fallback:#${cand.id || cand.name || '?'})` }
          }
          if (!idField || !pwField) {
            // 디버그 — 로그인 관련 input 우선 dump (검색창/헤더 input 에 가려 안 보이던 진짜 로그인칸 노출)
            const dump = i => ({ id: i.id, name: i.name, type: i.type, placeholder: i.placeholder, visible: i.offsetParent !== null })
            const allEls = Array.from(document.querySelectorAll('input'))
            const loginish = allEls.filter(i => /login|user|mbr|pass|pwd/i.test((i.id || '') + ' ' + (i.name || '')) || i.type === 'password')
            return {
              success: false,
              error: 'fields not found',
              idFound: !!idField,
              pwFound: !!pwField,
              loginInputs: loginish.map(dump),
              allInputs: allEls.map(dump).slice(0, 30),
              currentUrl: location.href,
            }
          }
          console.log(`[자동로그인][SPA] selector 매칭: id="${idSelMatched}" pw="${pwSelMatched}"`)

          // Vue 3 reactive 필드는 .value 직접 설정이 v-model에 안 잡힘.
          // native setter로 값 주입 후 input 이벤트 dispatch — Vue/React 공통 패턴.
          const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
          idField.focus()
          nativeSetter.call(idField, usernameArg)
          idField.dispatchEvent(new Event('input', { bubbles: true }))
          idField.dispatchEvent(new Event('change', { bubbles: true }))

          pwField.focus()
          nativeSetter.call(pwField, passwordArg)
          pwField.dispatchEvent(new Event('input', { bubbles: true }))
          pwField.dispatchEvent(new Event('change', { bubbles: true }))

          // 로그인 버튼 찾기 — id 셀렉터 → 텍스트(sel.btnText) → pw 폼 안 로그인버튼 탐색(폴백)
          let btn = null
          if (sel.btnId) {
            btn = document.querySelector(sel.btnId)
          }
          if (!btn && sel.btnText) {
            btn = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a[role="button"]'))
              .find(b => {
                const txt = (b.textContent || b.value || '').trim()
                return txt === sel.btnText && b.offsetParent !== null
              })
          }
          if (!btn) {
            // [2026-06-29] 폴백 — 로그인 버튼이 <form> 밖(JS submit)이거나 id 가 빗나가도 대응.
            // 헤더의 'LOGIN' 링크·비회원·간편·SNS 는 제외하고 '로그인' 텍스트 클릭요소를 페이지 전역에서 탐색.
            const norm = b => (b.textContent || b.value || '').trim()
            const isKoLogin = t => /로그인/.test(t) && !/비회원|회원가입|간편|sns|카카오|네이버|애플|페이|guest|join|아이디|찾기|비밀번호|문의/.test(t)
            const inHeader = b => !!b.closest('header, nav, [class*="header"], [class*="gnb"], [id*="header"], [id*="gnb"]')
            const form = pwField && pwField.closest('form')
            const vis = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a')).filter(b => b.offsetParent !== null)
            btn = vis.find(b => isKoLogin(norm(b)) && form && form.contains(b))     // 1) 폼 안 '로그인'
              || vis.find(b => isKoLogin(norm(b)) && b.type === 'submit')           // 2) submit '로그인'
              || vis.find(b => isKoLogin(norm(b)) && !inHeader(b))                  // 3) 헤더 밖 '로그인'(폼 밖 JS버튼)
              || vis.find(b => b.type === 'submit' && form && form.contains(b))     // 4) 폼 안 submit(텍스트 무관)
          }
          if (!btn) {
            // 디버그 — 페이지 전역의 '로그인/login' 클릭요소 목록 (폼 안 여부 포함)
            const form = pwField && pwField.closest('form')
            const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a'))
              .filter(b => b.offsetParent !== null && /로그인|login/i.test((b.textContent || b.value || '').trim()))
              .map(b => ({ tag: b.tagName, type: b.type, id: b.id, cls: (b.className || '').toString().slice(0, 25), txt: (b.textContent || b.value || '').trim().slice(0, 15), inForm: !!(form && form.contains(b)) }))
            return { success: false, error: 'login button not found', buttons: buttons.slice(0, 15), pwInForm: !!form, currentUrl: location.href }
          }

          // disabled 풀고 click
          btn.disabled = false
          btn.classList?.remove('disabled')
          btn.click()
          return { success: true, idValue: idField.value.length, pwLen: pwField.value.length }
        },
        args: [siteKey, username, password],
      })

      // allFrames 결과 중 성공 프레임 채택 (로그인 폼이 iframe 안이면 그 프레임이 success).
      // 성공 없으면 디버그용으로 부분매칭/마지막 프레임 결과를 남긴다.
      // [2026-09-03] 프레임 결과 채택 순서 수정.
      //   기존: 성공 → (idFound&&pwFound: 죽은 조건) → **배열 마지막** 프레임.
      //   로그인 폼은 메인 프레임에 있는데, 광고·리캡차 iframe 이 뒤에 붙으면 마지막 결과는
      //   그 iframe 의 'fields not found' 였다 → 진짜 실패 사유가 광고창 사유로 덮여 보고됐다.
      //   (더현대 '입력필드 못찾음' 이 이 오염일 가능성 — 라이브 확인 결과 메인 프레임엔
      //    loginId/password/'로그인' 버튼이 모두 존재한다)
      //   수정: 성공 → 메인 프레임(frameId 0) → 폼을 찾은 프레임 → 마지막.
      const _frames = (scriptResults || []).filter(x => x?.result)
      const _pick = _frames.find(x => x.result.success)
        || _frames.find(x => x.frameId === 0)
        || _frames.find(x => x.result.error === 'login button not found')
        || _frames[_frames.length - 1]
      const r = _pick?.result
      if (!r?.success) {
        // [2026-09-04] 로그인 페이지를 열었는데 **로그인 페이지가 아닌 곳**에 와 있으면,
        // 그건 폼이 없는 게 아니라 **이미 로그인돼 있어서 홈으로 리다이렉트된 것**이다.
        // ABC마트(/login)·패션플러스(/auth/login) 가 정확히 이렇게 동작한다 — 실측 09-04:
        // 실패 사유가 '입력필드 못찾음 @abcmart.a-rt.com/', '@www.fashionplus.co.kr/'.
        // 이걸 실패로 세면 멀쩡히 로그인된 PC 에서 5회 누적 차단이 걸리고, 그 차단이
        // 송장수집까지 통째로 막는다(실측: ABC 송장 실패 101건).
        const _curUrlAfter = String(r?.currentUrl || '')
        if (r?.error === 'fields not found' && _curUrlAfter && !site.isLoginPage(_curUrlAfter)) {
          console.log(`[자동로그인][SPA] ${site.name} 로그인 페이지가 아닌 곳으로 리다이렉트됨(${_curUrlAfter}) — 이미 로그인 상태로 판단`)
          _spaLoginLastReason = ''
          chrome.debugger.onEvent.removeListener(dialogHandler)
          return true
        }
        console.log(`[자동로그인][SPA] ${site.name} 스크립트 실행 실패(frame=${_pick?.frameId ?? '?'}):`, JSON.stringify(r))
        // 실패 원인 보존 — 차단 메시지의 "(마지막 사유: …)" 에 노출.
        // URL 을 같이 남긴다 — '로그인 페이지가 아닌 곳에서 폼을 찾고 있었다' 를 구분하기 위해.
        const _where = r?.currentUrl ? ` @${String(r.currentUrl).replace(/^https?:\/\//, '').slice(0, 40)}` : ''
        _spaLoginLastReason =
          r?.error === 'fields not found' ? `입력필드 못찾음${_where}`
          : r?.error === 'login button not found' ? `로그인버튼 못찾음${_where}`
          : `폼 스크립트 실패(${String(r?.error || '결과 없음').slice(0, 60)})`
        chrome.debugger.onEvent.removeListener(dialogHandler)
        return false
      }
      console.log(`[자동로그인][SPA] ${site.name} .value 설정 + click() 완료 (id=${r.idValue}자, pw=${r.pwLen}자) — 응답 폴링`)

      // 응답 폴링 — URL 변경 감지 (로그인 성공 시 isLoginPage=false)
      const POLL_INTERVAL = 1500
      const TIMEOUT = 15000
      const startTime = Date.now()
      // 자격증명 오류로 간주할 alert 메시지 — 다단어 구문만 사용.
      // 단독 키워드("비밀번호"/"확인" 등)는 부수 alert("비밀번호를 변경해 주세요" 등)에
      // 걸려 false-positive 알람을 유발하므로 사용 금지.
      const CREDENTIAL_ERROR_PHRASES = [
        '일치하지 않',
        '일치하는 회원',
        '아이디 또는',
        '비밀번호가 일치',
        '비밀번호를 잘못',
        '비밀번호를 다시',
        '비밀번호가 틀',
        '비밀번호를 확인',
        '아이디를 잘못',
        '아이디를 다시',
        '아이디를 확인',
        '존재하지 않',
        '잘못 입력',
        '잘못되었',
        '재입력',
        '5회 이상',
        '5회를 초과',
        '캡차',
        'captcha',
        '보안문자',
        '로그인 정보가',
        '회원이 아닙',
      ]
      while (Date.now() - startTime < TIMEOUT) {
        await wait(POLL_INTERVAL)

        // URL이 로그인 페이지를 벗어났으면 alert 유무와 관계없이 성공으로 처리
        // (부수 alert가 떴어도 실제 로그인은 이미 완료됨)
        let tabInfo = null
        try { tabInfo = await chrome.tabs.get(tabId) } catch {
          _spaLoginLastReason = '로그인 탭 소실'
          chrome.debugger.onEvent.removeListener(dialogHandler)
          return false
        }
        const _curUrl = tabInfo.url || ''
        const urlLeftLoginPage = !site.isLoginPage(_curUrl)

        // [2026-06-10] findIdPw 리다이렉트 = SSG 계정 보안잠금. 기존엔 "로그인 페이지 이탈"로
        // 성공 오판 → 스크랩 비로그인 timeout → 재시도가 또 로그인 → 잠금 영구 갱신.
        // 잠긴 계정은 재시도해도 계속 튕기며 잠금만 유지 → 즉시 fatal 중단.
        if (/findIdPw/i.test(_curUrl)) {
          console.warn(`[자동로그인][SPA] ${site.name} findIdPw 리다이렉트 — 계정 보안잠금 감지, 재시도 중단`)
          _spaLoginFatal = {
            reason: 'locked',
            message: `로그인 실패(${site.name} 계정 잠금 — findIdPw 리다이렉트). 사이트에서 비밀번호 변경 + samba 소싱처계정 동기화 필요`,
          }
          chrome.debugger.onEvent.removeListener(dialogHandler)
          return false
        }

        // 자격증명 오류 alert만 실패로 간주 (URL이 로그인 페이지에 남아있을 때만)
        if (dialogMessage && dialogMessage.length > 0 && !urlLeftLoginPage) {
          const msgLower = dialogMessage.toLowerCase()
          const looksLikeCredentialError = CREDENTIAL_ERROR_PHRASES.some(p => msgLower.includes(p.toLowerCase()))
          if (looksLikeCredentialError) {
            console.log(`[자동로그인][SPA] ${site.name} 자격증명 오류 alert: "${dialogMessage.substring(0, 60)}"`)
            // 자격증명 오류/캡차/잠금 alert = 재시도해도 같은 결과 + SSG 잠금만 갱신 → fatal
            _spaLoginFatal = {
              reason: 'credential',
              message: `로그인 실패(${site.name} 자격증명 오류: ${dialogMessage.substring(0, 60)})`,
            }
            chrome.debugger.onEvent.removeListener(dialogHandler)
            return false
          }
          // 부수 alert는 메시지만 초기화하고 계속 대기
          console.log(`[자동로그인][SPA] ${site.name} 부수 alert 무시: "${dialogMessage.substring(0, 60)}"`)
          dialogMessage = null
        }

        // 오토튠 진행 중 취소 감지
        const stillActive = await _isAutotuneActive()
        if (stillActive === false) {
          console.log(`[자동로그인][SPA] ${site.name} 오토튠 취소 — 중단`)
          chrome.debugger.onEvent.removeListener(dialogHandler)
          return false
        }

        try {
          if (urlLeftLoginPage) {
            // LOTTEON: URL 이탈만으로 부족 — #memInfo.mbNo 실제 확인 (비로그인 리다이렉트 오판 방지)
            if (siteKey === 'lotteon') {
              await wait(2000)
              try {
                const [ck] = await chrome.scripting.executeScript({
                  target: { tabId },
                  func: () => {
                    const el = document.querySelector('#memInfo')
                    try {
                      const mbNo = el ? JSON.parse(el.value || '{}')?.mbNo || null : null
                      if (mbNo) return 'MEMINFO'
                    } catch {}
                    for (const script of document.querySelectorAll('script')) {
                      const text = script.textContent || ''
                      if (!text || (!text.includes('memInfo') && !text.includes('mbNo'))) continue
                      const m =
                        text.match(/["']mbNo["']\s*:\s*["']([^"']{2,})["']/)
                        || text.match(/\bmbNo\s*:\s*["']([^"']{2,})["']/)
                      if (m?.[1]) return 'SCRIPT'
                    }
                    const headerText = (
                      document.querySelector('header, #header, .header, [class*="header"], nav, [class*="gnb"]')?.innerText
                      || (document.body?.innerText || '').substring(0, 400)
                    ).replace(/\s+/g, ' ')
                    if (['濡쒓렇?꾩썐', '留덉씠濡?뜲', 'MY LOTTE', '二쇰Ц諛곗넚'].some(token => headerText.includes(token))) {
                      return 'HEADER'
                    }
                    if (['濡쒓렇???뚯썝媛??', '濡쒓렇??', '?뚯썝媛??'].some(token => headerText.includes(token))) {
                      return null
                    }
                    return null
                  },
                })
                const mbNo = ck?.result
                if (mbNo) {
                  console.log(`[자동로그인][SPA] ✅ ${site.name} 로그인 확인 — mbNo: ${String(mbNo).slice(0, 4)}****`)
                  chrome.debugger.onEvent.removeListener(dialogHandler)
                  return true
                }
                // mbNo 없어도 URL이 로그인 페이지를 벗어난 것 자체가 로그인 성공 증거
                // (헤더 텍스트 체크 인코딩 문제로 매칭 불가 — URL 이탈 기준으로 단순화)
                // 틀린 자격증명은 위의 alert dialog 핸들러가 이미 처리함
                console.log(`[자동로그인][SPA] ✅ ${site.name} URL 이탈 확인 — #memInfo.mbNo 없음, 로그인 성공 처리`)
                chrome.debugger.onEvent.removeListener(dialogHandler)
                return true
              } catch (e) {
                console.log(`[자동로그인][SPA] ${site.name} mbNo 체크 오류: ${e.message} — URL 이탈로 성공 처리`)
                chrome.debugger.onEvent.removeListener(dialogHandler)
                return true
              }
            } else {
              console.log(`[자동로그인][SPA] ✅ ${site.name} 로그인 성공 — URL: ${tabInfo.url}`)
              chrome.debugger.onEvent.removeListener(dialogHandler)
              return true
            }
          }
        } catch {
          chrome.debugger.onEvent.removeListener(dialogHandler)
          return false
        }
      }

      console.log(`[자동로그인][SPA] ${site.name} 타임아웃 (${TIMEOUT / 1000}초) — 로그인 페이지 잔존`)
      _spaLoginLastReason = '로그인 후에도 로그인페이지(응답 타임아웃)'
      chrome.debugger.onEvent.removeListener(dialogHandler)
      return false
    } catch (err) {
      console.error(`[자동로그인][SPA] ${site.name} 예외:`, err.message)
      _spaLoginLastReason = `예외: ${String(err?.message || err).slice(0, 80)}`
      return false
    } finally {
      if (dialogAttached) {
        try { await chrome.debugger.detach(target) } catch {}
      }
    }
  } finally {
    if (tabCreated && tabId) {
      try { await chrome.tabs.remove(tabId) } catch {}
    }
  }
}

// 동시 진입 race 차단용 in-flight Map — 어떤 await보다 먼저 동기적으로 체크.
// 기존 autoLoginState.inProgress 가드는 첫 await(_isAutotuneActive) 이후에 설정되어
// 같은 tick에 fire-and-forget으로 들어온 호출들이 모두 통과 → 자동로그인 탭 폭증.
// 이 Map은 같은 사이트의 동시 호출을 즉시 같은 Promise로 합쳐 반환한다.
const _ensureLoggedInInflight = new Map()  // siteKey → Promise<boolean>

// 진입점 — 외부에서 자동로그인을 트리거할 때 호출 (3회 재시도)
// opts.accountId — 주문 매칭 계정으로 강제 로그인 (송장 수집 등 계정별 격리 필요시)
// opts.force    — 성공 캐시 무시하고 실제 로그아웃 + 재로그인 (적립금 계정별 잡)
function ensureLoggedIn(siteKey, opts) {
  const accountId = (opts && opts.accountId) || ''
  const force = !!(opts && opts.force)
  // accountId별 inflight key — 같은 사이트라도 계정별로는 독립 처리
  const inflightKey = accountId ? `${siteKey}::${accountId}` : siteKey
  const prev = _ensureLoggedInInflight.get(inflightKey)
  // [2026-08-14] force 호출은 진행 중인 호출에 편승하면 안 된다.
  // 편승하면 그 호출이 성공 캐시로 true 를 돌려줄 수 있어(= 실제 로그인 안 함) force 의
  // 목적('지금 이 세션이 정확히 이 계정')이 깨진다. 앞 호출이 끝나기를 기다린 뒤
  // 내 재로그인을 수행한다(동시 로그인으로 쿠키가 엉키지 않게 편승 대신 직렬).
  if (prev && !force) return prev
  const p = (async () => {
    if (prev) { try { await prev } catch {} }
    try {
      return await _ensureLoggedInImpl(siteKey, accountId, force)
    } finally {
      // 내가 마지막 등록자일 때만 정리 — 뒤에 다른 force 가 붙었으면 그쪽이 소유권을 가진다.
      if (_ensureLoggedInInflight.get(inflightKey) === p) {
        _ensureLoggedInInflight.delete(inflightKey)
      }
    }
  })()
  _ensureLoggedInInflight.set(inflightKey, p)
  return p
}

// [2026-08-14] 쿠키 자(jar) 그룹 — 로그인 세션을 공유하는 사이트키 묶음.
// abcmart(abcmart.a-rt.com)와 member(ABC캠프, member.a-rt.com)는 a-rt.com 쿠키를 공유해서
// 한쪽이 로그인하면 다른 쪽 세션도 그 계정으로 바뀐다. 그런데 성공 캐시는 사이트키별로 따로라
// "member 캐시엔 내 계정 성공이 남아있는데 실제 세션은 abcmart 잡이 갈아끼운 남의 계정" 이
// 될 수 있었다 → 로그인 스킵 → 남의 계정으로 출석. 자 단위로 마지막 로그인 계정을 추적한다.
const _COOKIE_JAR_BY_SITE = { abcmart: 'a-rt', member: 'a-rt' }
function _cookieJarOf(siteKey) {
  return _COOKIE_JAR_BY_SITE[siteKey] || siteKey
}

// 자동로그인 금지 사이트 — 자동 시도가 구조적으로 100% 실패하는 곳.
// 여기 등록된 사이트는 ensureLoggedIn 이 즉시 false 를 돌려주고 **현재 크롬 세션을 그대로
// 쓴다**. 수동 로그인 세션이 살아있으면 송장수집 등은 정상 동작한다.
// 값 = 스킵 사유(로그에 그대로 노출).
const _AUTOLOGIN_DISABLED_SITES = {
  // [2026-09-03] GS샵: 로그인 폼에 invisible reCAPTCHA 상시. 실패가 누적되면 보안문자
  // 입력칸(#confirmNum '상단문자 6자리')까지 떠서 수동 로그인마저 어려워진다.
  gs: '캡차 사이트',
  // [2026-09-04] 롯데ON: 저장된 아이디/비번으로는 롯데온이 계속 거부한다
  //   ("일치하는 회원정보가 없습니다. 아이디 또는 비밀번호를 확인해 주세요.")
  //   — 로그인 폼/셀렉터는 라이브 확인 결과 정상이고 저장값도 형태상 정상이라
  //   자동로그인으로는 넘을 수 없는 계정 문제(소셜로그인 계정 등)로 판단.
  //   그런데 **크롬에 살아있는 세션으로는 송장이 정상 수집된다**(실측 11건).
  //   시도할수록 누적 실패 차단만 걸려 그 멀쩡한 세션까지 막았다(16회 누적 차단).
  lotteon: '자동로그인 불가 계정 — 현 세션 사용',
}

// [2026-09-03] SPA 로그인칸 등장 판정용 프로브 — [아이디칸, 비번칸].
// 아래 주입 스크립트의 SELECTORS 첫 항목과 같은 값을 쓴다(바꿀 때 같이 고칠 것).
const SPA_INPUT_PROBE = {
  thehyundai: ['input[name="loginId"]', 'input[name="password"]'],
  fashionplus: ['#login_id', 'input[type="password"]'],
  // [2026-09-03] ABC 는 백그라운드 탭에서 폼이 늦게 뜨면 비회원 주문조회 칸만 보고
  // 조기 통과하던 경로가 있어, 진짜 로그인칸 등장까지 기다린다.
  abcmart: ['#username', '#password'],
  member: ['#id', '#pw'],
}

async function _ensureLoggedInImpl(siteKey, accountId, force) {
  const site = AUTO_LOGIN_SITES[siteKey]
  if (!site) {
    console.log(`[자동로그인] 미지원 사이트: ${siteKey}`)
    return false
  }

  // 자동로그인 금지 사이트 — 시도 자체를 하지 않고 현재 세션 그대로 진행시킨다.
  // 시도하면 100% 실패하면서 누적 차단만 쌓이고, 그 차단이 멀쩡한 수동 로그인 세션까지
  // 막아 송장수집을 통째로 죽인다. 전역 에러도 남기지 않는다 — 남기면 no_tracking 같은
  // 정상 판정까지 '로그인 실패' 로 덮어써서 오보가 된다.
  const _disabledReason = _AUTOLOGIN_DISABLED_SITES[siteKey]
  if (_disabledReason) {
    console.log(`[자동로그인] ${site.name} ${_disabledReason} — 자동로그인 스킵(현 세션 유지). 세션 만료 시 크롬에서 수동 로그인 필요`)
    try {
      const _le = globalThis._lastEnsureLoginError
      if (_le && _le.siteKey === siteKey) globalThis._lastEnsureLoginError = null
    } catch {}
    // 이미 쌓인 누적 실패 카운터를 지운다 — 안 지우면 금지 사이트인데도 옛 차단이
    // 남아 다른 경로에서 '차단 중' 문구로 계속 실패 보고된다(패플·롯데온 실측).
    try {
      if (typeof _clearAccountLoginFail === 'function') await _clearAccountLoginFail(siteKey, accountId)
    } catch {}
    return false
  }

  // accountId 정상성 가드 — 'etc'(기타) 등 실제 계정 ID(sa_ prefix)가 아니면 자동로그인 대상 아님.
  // retry 루프(3회·6초) 진입 전에 즉시 차단 — 송장수집 다건이면 건당 6초 낭비 방지.
  // 현재 로그인 세션 그대로 송장조회 진행 (호출자가 false 처리).
  if (accountId && !String(accountId).startsWith('sa_')) {
    console.log(`[자동로그인] ${site.name} accountId='${accountId}' 비정상(기타 등) — 자동로그인 스킵, 현 세션 유지`)
    return false
  }

  // 오토튠 비활성 상태면 자동로그인 차단 (사용자가 작업 취소했는데 계속 시도되는 것 방지)
  // 단, accountId 명시(송장 자동수집 등 명시적 사용자 트리거)는 오토튠 게이트 우회 — 별도 기능.
  if (!accountId) {
    const autotuneActive = await _isAutotuneActive()
    if (autotuneActive === false) {
      console.log(`[자동로그인] ${site.name} 트리거 차단 — 오토튠 비활성 상태`)
      return false
    }
  } else {
    console.log(`[자동로그인] ${site.name} 오토튠 게이트 우회 — accountId 명시 트리거`)
  }

  // 중복 호출 차단 — 이미 진행 중이면 즉시 false (in-flight Map과 별개로 cooldown/실패카운트용)
  // accountId 명시(송장 자동수집)는 inflight Map(_ensureLoggedInInflight)으로 이미 격리되므로 우회.
  if (!accountId && autoLoginState.inProgress[siteKey]) {
    console.log(`[자동로그인] ${site.name} 이미 진행 중 — 무시`)
    return false
  }

  // 쿨다운 체크 — 실패 누적 후 일정 시간 차단. accountId 명시 트리거는 쿨다운 무시.
  if (!accountId) {
    const cooldownUntil = autoLoginState.cooldownUntil[siteKey] || 0
    if (Date.now() < cooldownUntil) {
      const remainSec = Math.ceil((cooldownUntil - Date.now()) / 1000)
      console.log(`[자동로그인] ${site.name} 쿨다운 중 (${remainSec}초 남음) — 무시`)
      return false
    }
  }

  // [2026-06-10] 계정별 실패 차단 — accountId 명시(송장수집)에도 적용. 잠긴/비번 틀린 계정에
  // 잡마다 재로그인하면 SSG가 잠금을 못 풀어 영구화됨 → 30분 쿨다운 + 5회 영구차단.
  const _blockReason = await _accountLoginBlocked(siteKey, accountId)
  if (_blockReason) {
    console.warn(`[자동로그인] ${site.name}(${accountId}) 차단 — ${_blockReason}`)
    globalThis._lastEnsureLoginError = {
      fatal: true,
      siteKey, // 어느 사이트의 에러인지 — 다른 사이트 잡이 전역 잔존값을 오독하지 않도록
      message: `로그인 실패(${site.name} ${_blockReason})`,
    }
    return false
  }

  // 계정별 최근 성공 캐시 체크 — 같은 계정으로 10분 이내 로그인 확인됐으면 스킵
  // (송장수집 100건 잡 돌릴 때 매 주문마다 ensureLoggedIn 트리거되는 비용 + alert 폭주 차단)
  // [2026-08-14] force=true 면 캐시를 아예 보지 않는다. 적립금(출첵 등) 계정별 잡은
  // '지금 이 세션이 정확히 이 계정' 이어야 하는데, 캐시는 그걸 보장하지 못한다.
  // (사용자가 브라우저에서 손으로 다른 계정 로그인 / 세션 만료 등은 캐시에 안 잡힘)
  const ACCOUNT_LOGIN_TTL_MS = 10 * 60 * 1000
  if (force) {
    console.log(`[자동로그인] ${site.name}(${accountId || '_default'}) 강제 재로그인 — 성공 캐시 무시`)
  } else try {
    const cache = globalThis._lastAutoLoginSuccessAt?.[siteKey]
    const accKey = accountId || '_default'
    const lastTs = (cache && typeof cache === 'object') ? (cache[accKey] || 0) : 0
    // 쿠키 자를 공유하는 다른 사이트키가 나중에 다른 계정으로 로그인했으면 캐시는 무효다.
    const jar = _cookieJarOf(siteKey)
    const jarAcc = globalThis._lastJarLoginAccount?.[jar]
    const jarMismatch = !!jarAcc && jarAcc !== accKey
    if (jarMismatch && lastTs) {
      console.log(`[자동로그인] ${site.name}(${accKey}) 성공캐시 있으나 ${jar} 세션은 ${jarAcc} — 캐시 무시하고 재로그인`)
    } else if (lastTs && (Date.now() - lastTs) < ACCOUNT_LOGIN_TTL_MS) {
      const ageSec = Math.round((Date.now() - lastTs) / 1000)
      console.log(`[자동로그인] ${site.name}(${accKey}) ${ageSec}초 전 성공 — 스킵`)
      return true
    }
  } catch {}

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
    _spaLoginFatal = null // 이전 사이트/계정의 fatal 잔존값 제거
    _spaLoginLastReason = null // 이전 사이트/계정의 사유 잔존값 제거
    for (let attempt = 1; attempt <= AUTO_LOGIN_MAX_RETRIES; attempt++) {
      console.log(`[자동로그인] ${site.name} 시도 (${attempt}/${AUTO_LOGIN_MAX_RETRIES})`)
      ok = await _ensureLoggedInSingle(siteKey, accountId)
      if (ok) break
      // [2026-06-10] 자격증명 오류/계정 잠금 = 재시도해도 같은 결과 + 로그인 POST 마다
      // SSG 실패 카운트/잠금만 갱신 → 즉시 중단 (잔여 재시도 폐기)
      if (_spaLoginFatal) {
        console.warn(`[자동로그인] ${site.name} 치명적 실패(${_spaLoginFatal.reason}) — 재시도 중단`)
        break
      }
      if (attempt < AUTO_LOGIN_MAX_RETRIES) {
        await wait(3000)
      }
    }

    if (ok) {
      autoLoginState.failedAttempts[siteKey] = 0
      autoLoginState.cooldownUntil[siteKey] = 0
      globalThis._lastEnsureLoginError = null
      await _clearAccountLoginFail(siteKey, accountId) // 성공 → 계정별 실패 카운트 리셋
      if (siteKey === 'ssg') {
        await _saveSsgSession(accountId || '_default') // 세션 저장 → 다음 잡 fresh 로그인 생략
      }
      // 자동로그인 성공 시각 기록 — [siteKey][accountId] 2계층 구조.
      // 같은 사이트라도 계정이 다르면 별도 캐시. accountId 없으면 '_default' 키로 저장.
      // storage 동기화로 서비스 워커 재시작 후에도 캐시 복원.
      try {
        globalThis._lastAutoLoginSuccessAt = globalThis._lastAutoLoginSuccessAt || {}
        const accKey = accountId || '_default'
        // [2026-06-06] 소싱처는 한 브라우저 세션에 한 계정만 로그인 가능(무신사/SSG 등 SPA).
        // 계정별 캐시를 누적(siteMap[accKey]=now)하면 병기 로그인 후 성희 로그인 시 병기 캐시가
        // 살아남아 다음 병기 잡에서 line 575 "이미 로그인됨" 오판(false positive) → 실제 세션
        // (성희)으로 조회 → 무신사=WRONG_ACCOUNT / SSG=비로그인 리다이렉트 timeout.
        // 단일 세션 반영: 마지막 로그인 1계정만 유효하게 **교체**(다른 계정 캐시 삭제).
        // CDP 3단계 검증(무신사): 캐시 클리어 시 ensureLoggedIn 이 실제 로그아웃+병기 로그인으로
        // 세션 전환 성공(myinfo ID=cannonfort) → 캐시 교체가 정확한 스왑 유도.
        globalThis._lastAutoLoginSuccessAt[siteKey] = { [accKey]: Date.now() }
        // 쿠키 자 단위 '지금 이 세션의 주인' 기록 — a-rt.com 처럼 abcmart/member 가 세션을
        // 공유하는 경우, 한쪽 로그인이 다른 쪽 캐시를 무효화하는 근거가 된다.
        globalThis._lastJarLoginAccount = globalThis._lastJarLoginAccount || {}
        globalThis._lastJarLoginAccount[_cookieJarOf(siteKey)] = accKey
        chrome.storage.local.set({
          _lastAutoLoginSuccessAt: globalThis._lastAutoLoginSuccessAt,
          _lastJarLoginAccount: globalThis._lastJarLoginAccount,
        }).catch(() => {})
      } catch {}
      console.log(`[자동로그인] ✅ ${site.name} 성공 — 폴링 자동 재개`)
    } else {
      autoLoginState.failedAttempts[siteKey] = (autoLoginState.failedAttempts[siteKey] || 0) + 1
      autoLoginState.cooldownUntil[siteKey] = Date.now() + AUTO_LOGIN_COOLDOWN_MS
      // 계정별 실패 기록 + 호출자(송장 잡)가 백엔드에 보고할 표준 메시지("로그인 실패" 포함 —
      // 백엔드 서킷브레이커가 이 문구로 계정 단위 재큐잉을 차단한다)
      // fatal(자격증명 오류/계정 잠금)이면 그 메시지를, 아니면 _spaDirectLogin 등이 남긴
      // 마지막 비치명 사유를 lastReason 으로 보존 — 차단 문구에 "(마지막 사유: …)" 로 노출.
      await _recordAccountLoginFail(
        siteKey,
        accountId,
        _spaLoginFatal?.message || _spaLoginLastReason || '원인 미상(자동로그인 실패)'
      )
      globalThis._lastEnsureLoginError = {
        fatal: !!_spaLoginFatal,
        siteKey, // 어느 사이트의 에러인지 — 다른 사이트 잡이 전역 잔존값을 오독하지 않도록
        message: _spaLoginFatal?.message || `로그인 실패(${site.name} 자동로그인 실패 — acc=${accountId || '기본'})`,
      }
      console.log(`[자동로그인] ❌ ${site.name} ${AUTO_LOGIN_MAX_RETRIES}회 실패 — ${AUTO_LOGIN_COOLDOWN_MS / 60000}분 쿨다운`)
      // 알람은 라디오 기본 계정 모드(!accountId)만 발송 — accountId 명시 트리거(송장수집)는
      // 잡당 시도라 실패 알람 폭주 위험. 호출자가 wrong_account 로 분류해서 모달로 보여줌.
      if (!accountId) {
        try {
          chrome.notifications?.create?.(`autologin-fail-${siteKey}-${Date.now()}`, {
            type: 'basic',
            iconUrl: 'icon128.png',
            title: 'SAMBA-WAVE 자동로그인 실패',
            message: `${site.name} 자동 로그인이 실패했습니다. 브라우저에서 수동 로그인해주세요. (5분 후 자동 재시도)`,
          })
        } catch {}
      }
    }
    return ok
  } finally {
    autoLoginState.inProgress[siteKey] = false
    // 자동로그인 완료 시 폴링 즉시 재개 (90초 대기 없이)
    try {
      if (typeof globalThis.resumeCollectPolling === 'function') {
        globalThis.resumeCollectPolling()
      }
    } catch {}
  }
}

// 단일 사이트 로그인 시도
async function _ensureLoggedInSingle(siteKey, accountId) {
  const site = AUTO_LOGIN_SITES[siteKey]
  if (!site) return false

  // accountId 정상성 가드 — 주문계정이 'etc'(기타) 등 실제 계정 ID(sa_ prefix)가 아니면
  // 자동로그인 대상이 아님. 백엔드 /login-credential 이 404 → 알림 폭주를 유발하므로
  // 진입 자체를 막는다. 현재 로그인 세션 그대로 송장조회 진행 (호출자가 false 처리).
  if (accountId && !String(accountId).startsWith('sa_')) {
    console.log(`[자동로그인] ${site.name} accountId='${accountId}' 비정상(기타 등) — 자동로그인 스킵, 현 세션 유지`)
    return false
  }

  // [SPA 분기] LOTTEON / ABCmart / SSG는 백엔드 라디오 지정 계정으로만 자동로그인
  // 사용자 요구 — 소싱처계정의 username/password를 직접 .value 설정 (Chrome 자동완성 드롭다운 사용 X)
  // 백엔드 자격증명 없으면 즉시 실패. chrome.debugger triple-click 폴백 제거 (드롭다운 노출 방지).
  const SPA_DIRECT_LOGIN_SITES = ['lotteon', 'abcmart', 'ssg', 'musinsa', 'member', 'fashionplus', 'thehyundai']
  if (SPA_DIRECT_LOGIN_SITES.includes(siteKey)) {
    // [2026-06-10] SSG 세션 재사용 — fresh 로그인 횟수 자체를 줄여 "비정상 자동접근" 잠금 회피.
    // ① 현 세션이 이미 잡 계정이면 로그인 생략 ② 저장세션 복원으로 살아나면 로그인 생략.
    if (siteKey === 'ssg' && accountId) {
      await _loadSsgSessionState()
      if (_ssgLastLoginAccount === accountId && (await _isSsgLoggedIn())) {
        console.log(`[자동로그인] SSG 현 세션 유지 (acc=${accountId}) — 로그인 생략`)
        return true
      }
      if (await _restoreSsgSession(accountId)) {
        if (await _isSsgLoggedIn()) {
          _ssgLastLoginAccount = accountId
          try { await chrome.storage.local.set({ _ssgLastLoginAccount: accountId }) } catch {}
          console.log(`[자동로그인] SSG 저장세션 복원 성공 (acc=${accountId}) — fresh 로그인 생략`)
          return true
        }
        console.log(`[자동로그인] SSG 저장세션 만료 (acc=${accountId}) — fresh 로그인 진행`)
      }
    }

    // accountId 지정 시 — 사용자 요구 = 자동 로그아웃 + 새 계정 로그인 (송장수집 풀 자동화).
    // 사전 로그인 체크 스킵하고 _spaDirectLogin 진입 (그 함수가 쿠키 삭제 후 새 로그인 수행).
    // accountId 없을 때만(라디오 기본 모드) 이미 로그인됐는지 체크해서 스킵.
    if (!accountId) {
      let alreadyLoggedIn = false
      let spaCheckTabId = null
      try {
        const checkTab = await chrome.tabs.create({ url: site.checkUrl, active: false })
        spaCheckTabId = checkTab.id
        try { await waitForTabLoad(spaCheckTabId, 20000) } catch {}
        await wait(1500)
        const checkTabInfo = await chrome.tabs.get(spaCheckTabId)
        alreadyLoggedIn = !site.isLoginPage(checkTabInfo.url || '')
        try { await chrome.tabs.remove(spaCheckTabId) } catch {}
        spaCheckTabId = null
      } catch (e) {
        console.log(`[자동로그인] ${site.name} 사전 로그인 체크 실패 (무시): ${e.message}`)
        if (spaCheckTabId) try { await chrome.tabs.remove(spaCheckTabId) } catch {}
      }

      if (alreadyLoggedIn) {
        console.log(`[자동로그인] ${site.name} 이미 로그인됨 — 자동로그인 스킵 (라디오 모드)`)
        return true
      }
    }

    const credential = await _fetchLoginCredential(siteKey, accountId)
    if (credential?.username && credential?.password) {
      const tag = accountId ? `주문매칭:${credential.account_label}` : `라디오:${credential.account_label}`
      console.log(`[자동로그인] ${site.name} 백엔드 자격증명 사용 (${tag}) — SPA 직접 로그인 시도`)
      return await _spaDirectLogin(siteKey, credential.username, credential.password)
    }
    // 폴백 없이 즉시 중단 — 사용자가 설정 페이지에서 라디오 지정 필요
    _spaLoginLastReason = '백엔드 자격증명 없음(계정 미지정/미존재)'
    console.log(`[자동로그인] ❌ ${site.name} 백엔드 자격증명 없음 — 자동로그인 중단. 설정 페이지에서 자동로그인 계정 라디오 지정 필요`)
    // 알림은 라디오 기본 계정 모드(!accountId)만 발송. accountId 명시 트리거(송장수집)는
    // 잡당 시도라 실패 알림 폭주 위험 → 호출자가 wrong_account 로 분류해서 모달로 보여줌.
    // (line 615 failure 알림 정책과 동일)
    if (!accountId) {
      try {
        chrome.notifications?.create?.(`autologin-no-credential-${siteKey}-${Date.now()}`, {
          type: 'basic',
          iconUrl: 'icon128.png',
          title: 'SAMBA-WAVE 자동로그인 설정 필요',
          message: `${site.name} 자동로그인 계정이 지정되지 않았습니다. 설정 페이지 → 소싱처 계정에서 라디오 버튼으로 계정을 선택해주세요.`,
        })
      } catch {}
    }
    return false
  }

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
    // 기존 브라우저의 백그라운드 탭으로 오픈 (사용자 요구사항 — 별도 minimized window 띄우지 말것)
    // active: false로 사용자 현재 작업을 방해하지 않음
    const tab = await chrome.tabs.create({ url: site.checkUrl, active: false })
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
    _spaLoginLastReason = '로그인 후에도 로그인페이지(타임아웃)'
    return false
  } catch (err) {
    console.error(`[자동로그인] ${site.name} 예외:`, err.message)
    _spaLoginLastReason = `예외: ${String(err?.message || err).slice(0, 80)}`
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
// 잡 계정의 로그인 아이디 조회용 — 적립금 잡이 '지금 로그인된 계정이 잡 계정 맞는지' 검증할 때 쓴다.
globalThis.alFetchLoginCredential = _fetchLoginCredential
globalThis.AUTO_LOGIN_SITES = AUTO_LOGIN_SITES

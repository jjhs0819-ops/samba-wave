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

// 안전 상한 — 실제 동시 실행 수는 백엔드 _SSG_BATCH로 제어
const SOURCING_MAX_POLL_LIMIT = 10

// 사이트별 동시 처리 세마포어 — 폴링이 받은 작업을 사이트별 캡까지만 병렬 처리
// (프론트 "동시실행" 설정값을 백엔드 status API에서 받아 적용)
const _siteSemaphores = new Map() // site → { active: number }
let _siteConcurrencyCache = { value: null, at: 0 }
const _SITE_CONC_CACHE_MS = 5000

const _SITE_CAP_DEFAULTS = {
  ABCmart: 5, GrandStage: 5, LOTTEON: 2, SSG: 2, MUSINSA: 4, KREAM: 5, GSShop: 1, REXMONDE: 3,
}

async function _getSiteConcurrencyMap() {
  const now = Date.now()
  if (_siteConcurrencyCache.value && now - _siteConcurrencyCache.at < _SITE_CONC_CACHE_MS) {
    return _siteConcurrencyCache.value
  }
  try {
    const stored = await chrome.storage.local.get('proxyUrl')
    const proxyUrl = stored.proxyUrl || 'https://api.samba-wave.co.kr'
    const res = await fetch(`${proxyUrl}/api/v1/samba/collector/autotune/status`, { method: 'GET' })
    if (!res.ok) return _siteConcurrencyCache.value || _SITE_CAP_DEFAULTS
    const data = await res.json()
    const conc = { ..._SITE_CAP_DEFAULTS, ...(data.site_autotune_concurrency || {}) }
    _siteConcurrencyCache = { value: conc, at: now }
    return conc
  } catch {
    return _siteConcurrencyCache.value || _SITE_CAP_DEFAULTS
  }
}

function _normalizeSiteForCap(site) {
  // GrandStage는 a-rt.com 동일 인프라 → ABCmart 캡 공유
  if (site === 'GrandStage') return 'ABCmart'
  return site
}

async function _siteSemAcquire(site) {
  const key = _normalizeSiteForCap(site)
  const concMap = await _getSiteConcurrencyMap()
  const cap = concMap[key] || _SITE_CAP_DEFAULTS[key] || 3
  let sem = _siteSemaphores.get(key)
  if (!sem) {
    sem = { active: 0 }
    _siteSemaphores.set(key, sem)
  }
  // 캡 도달 시 대기 (200ms 폴링)
  let waited = 0
  while (sem.active >= cap) {
    if (waited === 0) console.log(`[동시실행] ${key} 캡 도달(${sem.active}/${cap}) — 슬롯 대기`)
    await wait(200)
    waited += 200
    if (waited > 60000) {
      console.log(`[동시실행] ${key} 60초 대기 후에도 캡 도달 — 강제 진행`)
      break
    }
  }
  sem.active++
}

function _siteSemRelease(site) {
  const key = _normalizeSiteForCap(site)
  const sem = _siteSemaphores.get(key)
  if (sem) sem.active = Math.max(0, sem.active - 1)
}

async function _processJobWithCap(job) {
  const site = job.site || 'unknown'
  await _siteSemAcquire(site)
  try {
    return await handleSourcingJob(job)
  } finally {
    _siteSemRelease(site)
  }
}

// 사이트별 인증 실패 카운트 — 매우 보수적인 자동로그인 트리거 정책 (사용자 직접 로그인 신뢰)
// 정책:
//   - immediate=true(비로그인 확정 신호)여도 1회만으론 트리거 X — 10회 누적 후 트리거
//   - 일반 인증 실패도 10회 누적 후 트리거
//   - 한 번 트리거되면 1시간 쿨다운 (그 안에는 추가 트리거 X)
//   - DOM hydration false-positive로 매 작업 트리거되던 폭주 차단 + 사용자 직접 로그인
//     상태를 함부로 덮지 않음
const _alFailureCount = {}
const _AL_FAILURE_THRESHOLD = 10  // 5 → 10 (사용자 직접 로그인 신뢰 강화)
// 사이트별 마지막 자동로그인 트리거 시각 — 1시간 쿨다운
const _alLastTriggerAt = {}
const _AL_TRIGGER_COOLDOWN_MS = 60 * 60 * 1000  // 5분 → 1시간

// 사용자가 명시적으로 자동로그인을 끄고 싶을 때 chrome.storage.disableAutoLogin = true
// 또는 사이트별 chrome.storage.disableAutoLoginSites = ['LOTTEON','SSG'] 가능
async function _isAutoLoginDisabled(externalSite) {
  try {
    const data = await chrome.storage.local.get(['disableAutoLogin', 'disableAutoLoginSites'])
    if (data.disableAutoLogin === true) return true
    if (Array.isArray(data.disableAutoLoginSites) && data.disableAutoLoginSites.includes(externalSite)) {
      return true
    }
  } catch {}
  return false
}

// immediate 인자는 이제 의미 약화 — 모든 신호에 누적 카운트 적용 (DOM false-positive 차단)
function reportLoginFailure(externalSite, immediate = false) {
  if (!externalSite) return
  _alFailureCount[externalSite] = (_alFailureCount[externalSite] || 0) + 1
  // 누적 임계값 미도달이면 silent (로그도 적당히)
  if (_alFailureCount[externalSite] < _AL_FAILURE_THRESHOLD) {
    if (_alFailureCount[externalSite] === 1 || _alFailureCount[externalSite] % 5 === 0) {
      console.log(`[로그인감지] ${externalSite} 비로그인 신호 누적 ${_alFailureCount[externalSite]}/${_AL_FAILURE_THRESHOLD} (자동로그인 미트리거)`)
    }
    return
  }
  const key = (typeof alExternalSiteToKey === 'function') ? alExternalSiteToKey(externalSite) : null
  if (!key || typeof ensureLoggedIn !== 'function') {
    _alFailureCount[externalSite] = 0
    return
  }
  // 자동로그인 비활성 옵션 검사 (사용자 명시적 OFF)
  _isAutoLoginDisabled(externalSite).then(disabled => {
    if (disabled) {
      console.log(`[로그인감지] ${externalSite} 자동로그인 비활성 옵션 켜짐 — 트리거 스킵`)
      _alFailureCount[externalSite] = 0
      return
    }
    // 쿨다운 검사 (1시간) — 병렬 작업 + 누적 임계값 동시 트리거 방지
    const lastAt = _alLastTriggerAt[externalSite] || 0
    const elapsed = Date.now() - lastAt
    if (lastAt && elapsed < _AL_TRIGGER_COOLDOWN_MS) {
      const remainingMin = Math.ceil((_AL_TRIGGER_COOLDOWN_MS - elapsed) / 60000)
      console.log(`[로그인감지] ${externalSite} 자동로그인 쿨다운 중 (잔여 ${remainingMin}분) — 트리거 스킵`)
      _alFailureCount[externalSite] = 0
      return
    }
    console.log(`[로그인감지] ${externalSite} 비로그인 누적 ${_alFailureCount[externalSite]}회 → 자동로그인 트리거`)
    _alFailureCount[externalSite] = 0
    _alLastTriggerAt[externalSite] = Date.now()
    ensureLoggedIn(key).catch(e => console.error('[자동로그인] 호출 오류:', e?.message || e))
  })
}

function reportLoginSuccess(externalSite) {
  if (_alFailureCount[externalSite]) {
    _alFailureCount[externalSite] = 0
  }
}

// 전 사이트 공통 로그인 상태 감지 — 헤더 영역의 로그인/로그아웃 링크로 판단
// 비로그인 페이지에 노출되는 마케팅 가격(예: LOTTEON "나의 혜택가") false-positive 차단용
// 반환: true(로그인) | false(비로그인) | null(판단 불가, 안전상 로그인으로 간주)
async function _detectLoginStatus(tabId, site) {
  try {
    const [r] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (siteName) => {
        // 사이트별 로그인/로그아웃 식별 패턴
        const cfg = {
          ABCmart:    { login: ['/login', 'member/login'], logout: ['/logout', '/mypage', '/myinfo'] },
          GrandStage: { login: ['/login', 'member/login'], logout: ['/logout', '/mypage', '/myinfo'] },
          LOTTEON:    { login: ['/member/login/common'], logout: ['/logout', '/mypage', '/p/member/logout'] },
          SSG:        { login: ['login.ssg', '/member/login'], logout: ['logout.ssg', '/myssg'] },
          GSShop:     { login: ['login.gs', '/login'], logout: ['logout.gs', '/mypage', '/myinfo'] },
          MUSINSA:    { login: ['/auth/login', 'member.one.musinsa.com/login'], logout: ['/logout', '/mypage'] },
          KREAM:      { login: ['/login'], logout: ['/logout', 'kream.co.kr/my'] },
        }
        const c = cfg[siteName]
        if (!c) return { isLoggedIn: null, reason: 'unsupported' }

        // 헤더 영역 우선 (본문 내 마케팅 링크 노이즈 차단)
        const headerEl = document.querySelector('header, #header, .header, nav, #gnb, .gnb, [class*="gnb"], [class*="header"]')
        const scope = headerEl || document.body

        let hasLoginLink = false
        let hasLogoutLink = false

        const elements = scope.querySelectorAll('a[href], button')
        for (const el of elements) {
          const href = (el.getAttribute('href') || '').toLowerCase()
          const txt = (el.textContent || '').trim()

          // 로그아웃 신호 — 가장 강한 확정 신호
          if (href.includes('logout') || txt === '로그아웃' || txt === 'Logout' || txt === 'LOGOUT') {
            hasLogoutLink = true
            continue
          }

          // 로그인 신호 — 텍스트가 정확히 "로그인"이거나 href에 login 패턴
          if (txt === '로그인' || txt === 'Login' || txt === 'LOGIN') {
            hasLoginLink = true
            continue
          }
          for (const p of c.login) {
            if (href.includes(p.toLowerCase()) && !href.includes('logout')) {
              // href만으로는 약한 신호 — 텍스트가 짧거나 로그인 관련 표시면 인정
              if (txt.length < 20 && (txt.includes('로그인') || txt.includes('Login') || txt === '' || el.querySelector('img[alt*="로그인"], img[alt*="login"]'))) {
                hasLoginLink = true
              }
              break
            }
          }
        }

        if (hasLogoutLink && !hasLoginLink) return { isLoggedIn: true }
        if (hasLoginLink) return { isLoggedIn: false, reason: 'login link present' }
        // 둘 다 없으면 헤더 selector가 안 잡혔거나 사이트 구조 변경 — 보수적으로 null
        return { isLoggedIn: null, reason: 'no signal' }
      },
      args: [site],
    })
    const out = r?.result
    if (out && out.isLoggedIn === false) {
      console.log(`[로그인감지] ${site} 비로그인 (${out.reason || ''})`)
    }
    return out?.isLoggedIn
  } catch (e) {
    console.log(`[로그인감지] ${site} 검사 오류 (무시): ${e.message}`)
    return null
  }
}

async function pollSourcingOnce() {
  // 백엔드가 배치 크기만큼만 큐에 넣으므로 자연히 그 수만큼 처리됨
  const jobs = []
  for (let i = 0; i < SOURCING_MAX_POLL_LIMIT; i++) {
    try {
      const res = await apiFetch(`${PROXY_URL}${API_PREFIX}/sourcing/collect-queue`)
      if (!res.ok) {
        if (res.status === 503) pauseCollectPolling(30000, 'backend shutting down')
        break
      }
      const job = await res.json()
      if (job.shuttingDown) {
        pauseCollectPolling(30000, 'backend shutting down')
        break
      }
      if (!job.hasJob) break
      console.log(`[소싱] ${job.url || '작업 수신'} (${jobs.length + 1}/${SOURCING_MAX_POLL_LIMIT})`)
      jobs.push(job)
    } catch {
      pauseCollectPolling(10000, 'backend unreachable')
      break
    }
  }
  if (jobs.length === 0) return false
  if (jobs.length === 1) {
    await _processJobWithCap(jobs[0])
  } else {
    console.log(`[소싱] 병렬 처리: ${jobs.length}개 (사이트별 동시실행 캡 적용)`)
    await Promise.all(jobs.map(job => _processJobWithCap(job)))
  }
  return true
}

// 롯데ON: sitmNo + 쿠키 기반 pbf API 직접 호출로 혜택가 수집 (탭 불필요)
async function fetchLotteonBenefitPrice(productId, sitmNo) {
  try {
    if (!sitmNo) {
      console.log(`[LOTTEON] pbf 혜택가: sitmNo 없음 — 스킵 (${productId})`)
      return null
    }

    // 1. lotteon.com 쿠키 수집
    const cookies = await chrome.cookies.getAll({ domain: '.lotteon.com' })
    const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join('; ')
    if (!cookieStr) {
      console.log(`[LOTTEON] pbf 혜택가: 쿠키 없음 — 스킵 (${productId})`)
      return null
    }

    // 2. pbf API 호출 (수동 Cookie 헤더 — 서비스워커에서 credentials:'include' 무효)
    const pbfResp = await fetch(`https://pbf.lotteon.com/product/v2/detail/search/base/sitm/${sitmNo}`, {
      headers: {
        'Cookie': cookieStr,
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.lotteon.com',
        'Referer': 'https://www.lotteon.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      }
    })
    const pbfData = await pbfResp.json()
    const data = pbfData.data || {}
    const priceInfo = data.priceInfo || {}
    const slPrc = parseInt(priceInfo.slPrc || 0)
    const immdDc = parseInt(priceInfo.immdDcAplyTotAmt || 0)
    const adtnDc = parseInt(priceInfo.adtnDcAplyTotAmt || 0)

    let benefitPrice = 0
    let salePrice = slPrc
    if (slPrc > 0 && (immdDc > 0 || adtnDc > 0)) {
      benefitPrice = slPrc - immdDc - adtnDc
      if (benefitPrice <= 0 || benefitPrice >= slPrc) benefitPrice = 0
    }

    console.log(`[LOTTEON] pbf 혜택가: ${productId} slPrc=${slPrc}, immdDc=${immdDc}, adtnDc=${adtnDc}, benefit=${benefitPrice}`)

    if (benefitPrice > 0) {
      return {
        success: true,
        site_product_id: productId,
        sale_price: salePrice,
        best_benefit_price: benefitPrice,
        source_site: 'LOTTEON',
      }
    }
    // immdDc=0 → 쿠키 인증 안 됐을 가능성 → null 반환하여 DOM 폴백
    return null
  } catch (err) {
    console.error('[LOTTEON] pbf 혜택가 실패:', err.message)
    return null
  }
}

// ABCmart/GrandStage: 서비스워커에서 직접 fetch — 탭 없이 사용자 IP+세션으로 호출
// LOTTEON pbf 패턴과 동일. 백엔드 IP는 IP-bound 세션 차단당해 alwaysDscntAmt=0 받음.
// 확장앱이 사용자 PC에서 호출하면 loginYn=Y + 정확한 alwaysDscntAmt 수신.
async function fetchAbcmartBenefitPriceServiceWorker(productId, site) {
  try {
    // 1. .a-rt.com 쿠키 수집 (브라우저가 first-party로 저장한 사용자 세션)
    const cookies = await chrome.cookies.getAll({ domain: 'a-rt.com' })
    const cookieStr = cookies.map(c => `${c.name}=${c.value}`).join('; ')
    if (!cookieStr) {
      console.log(`[${site}] SW fetch: 쿠키 없음 — 스킵 (${productId})`)
      return null
    }

    // 2. info API 호출 (수동 Cookie 헤더 — 서비스워커에서 credentials:'include' 무효)
    const subdomain = site === 'GrandStage' ? 'grandstage.a-rt.com' : 'abcmart.a-rt.com'
    const resp = await fetch(`https://${subdomain}/product/info?prdtNo=${productId}`, {
      headers: {
        'Cookie': cookieStr,
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.a-rt.com',
        'Referer': 'https://www.a-rt.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      },
    })
    if (!resp.ok) {
      console.log(`[${site}] SW fetch: HTTP ${resp.status} — 폴백 (${productId})`)
      return null
    }
    const data = await resp.json()
    if (!data || !data.prdtName) {
      console.log(`[${site}] SW fetch: 빈 응답 — 폴백 (${productId})`)
      return null
    }

    const loginYn = (data.loginYn || '').toUpperCase()
    if (loginYn !== 'Y') {
      console.log(`[${site}] SW fetch: 비로그인 응답(loginYn=${loginYn}) — 폴백 (${productId})`)
      return null
    }

    // 3. 가격 계산: sale_price - alwaysDscntAmt - max(coupon discount)
    const pi = data.productPrice || {}
    const sellAmt = parseInt(pi.sellAmt || 0)
    const displayPrice = parseInt(data.displayProductPrice || 0)
    const salePrice = displayPrice > 0 ? displayPrice : sellAmt
    const normalAmt = parseInt(pi.normalAmt || 0) || salePrice

    const membershipDiscount = parseInt(data.alwaysDscntAmt || 0)
    const coupons = data.maxBenefitCoupon || data.coupon || []
    let couponDiscount = 0
    for (const c of coupons) {
      const d = parseInt(c.dscntAmt || 0)
      if (d > couponDiscount) couponDiscount = d
    }

    let benefitPrice = salePrice - membershipDiscount - couponDiscount
    if (benefitPrice <= 0 || benefitPrice > salePrice) benefitPrice = salePrice

    console.log(`[${site}] SW fetch 성공: ${productId} sale=${salePrice} membership=${membershipDiscount} coupon=${couponDiscount} benefit=${benefitPrice}`)
    reportLoginSuccess(site)

    return {
      success: true,
      site_product_id: productId,
      name: (data.prdtName || '').trim(),
      original_price: normalAmt,
      sale_price: salePrice,
      best_benefit_price: benefitPrice,
      source_site: site,
    }
  } catch (err) {
    console.error(`[${site}] SW fetch 실패:`, err.message)
    return null
  }
}

// LOTTEON 로그인 검증 — 다중 쿠키 후보로 판정.
// 후보 중 하나라도 의미있는 값이면 로그인. false-positive(DOM 비로그인 false 알림) 차단.
// 반환: true=로그인 / false=비로그인 / null=판단 불가
async function _checkLotteonLoggedInByCookies() {
  // LOTTEON 로그인 식별 가능 후보들 (사이트 변경에 견고하게 다중 검증)
  const candidates = ['fo_at_yn', 'fo_mlin', 'fo_ac_tkn', 'fo_sso_tkn', 'fo_mno']
  let anyChecked = false
  for (const name of candidates) {
    try {
      const c = await chrome.cookies.get({ url: 'https://www.lotteon.com', name })
      if (!c) continue
      anyChecked = true
      const v = (c.value || '').trim()
      // 의미없는 값(빈/0/N/null) → 다음 후보로
      if (!v || v === '0' || v === 'null' || v.toUpperCase() === 'N') continue
      // 의미있는 값 = 로그인 식별 가능
      console.log(`[LOTTEON] 로그인 인정: ${name}=${v.length > 20 ? v.slice(0, 8) + '...' : v}`)
      return true
    } catch {}
  }
  // 후보 모두 검사했는데 의미있는 값 없음 → 비로그인 추정
  if (anyChecked) {
    console.log(`[LOTTEON] 모든 쿠키 후보 의미없음 — 비로그인 추정`)
    return false
  }
  // 쿠키 자체 접근 실패 → 판단 불가 (DOM 결과 유지)
  return null
}

// 사이트별 백그라운드 세션 탭 자동 보장 — 웨일/Chrome 모두 호환.
// pinned:true 의존 X (웨일에서 핀탭이 세션 컨테이너 역할 못 하는 케이스 회피).
// 일반 탭(active:false)으로 1회 생성, 이후 재사용. 사용자가 닫으면 다음 호출에서 재생성.
// 사용자가 해당 사이트에 1번 직접 로그인 필요 (IP-bound 세션, 자동로그인 보조 가능).
const SITE_HOME_URLS = {
  ABCmart: 'https://abcmart.a-rt.com/',
  GrandStage: 'https://grandstage.a-rt.com/',
  LOTTEON: 'https://www.lotteon.com/',
  SSG: 'https://www.ssg.com/',
}
const SITE_URL_PATTERNS = {
  ABCmart: '*://abcmart.a-rt.com/*',
  GrandStage: '*://grandstage.a-rt.com/*',
  LOTTEON: '*://*.lotteon.com/*',
  SSG: '*://*.ssg.com/*',
}

async function ensureSiteSessionTab(site) {
  const pattern = SITE_URL_PATTERNS[site]
  const homeUrl = SITE_HOME_URLS[site]
  if (!pattern || !homeUrl) return null
  // 이미 해당 사이트의 탭이 어디든 떠 있으면 그걸 재사용 (사용자 직접 연 탭 포함)
  let tabs = []
  try { tabs = await chrome.tabs.query({ url: pattern }) } catch { tabs = [] }
  if (tabs.length) return tabs[0].id

  console.log(`[${site}] 백그라운드 세션 탭 자동 생성: ${homeUrl}`)
  // pinned:true 안 씀 — 웨일 호환. active:false로 사용자 화면 방해 X.
  const tab = await chrome.tabs.create({ url: homeUrl, active: false })
  try { await waitForTabLoad(tab.id, 30000) } catch {}
  await wait(2000) // SPA hydration
  return tab.id
}

// 하위 호환 — 기존 호출자(fetchAbcmartBenefitPrice 등) 그대로 동작
async function ensureArtTab(site) {
  return ensureSiteSessionTab(site)
}

// ABCmart/GrandStage: 사이트별 서브도메인 탭에서 in-tab fetch로 혜택가 수집 (매번 새 탭 X)
// alwaysDscntAmt(멤버십 상시할인) + maxBenefitCoupon 모두 활용해 정확한 best_benefit_price 산출.
// Cross-subdomain CORS 차단되므로 site에 맞는 서브도메인 탭만 사용.
async function fetchAbcmartBenefitPrice(productId, site) {
  try {
    // ABCmart 상품은 abcmart.a-rt.com, GrandStage 상품은 grandstage.a-rt.com 탭에서만 호출 가능
    // 탭 없으면 자동으로 백그라운드 + 핀 탭 1개 생성 (사용자 부담 제거)
    const tabId = await ensureArtTab(site)
    if (!tabId) {
      console.log(`[${site}] in-tab fetch: 탭 생성 실패 → DOM 폴백 (${productId})`)
      return null
    }
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: async (prdtNo) => {
        try {
          // ABC마트 API가 SPA 표준 헤더 검증 — 일반 헤더로 호출 시 500 "잘못된 접근"
          // X-Requested-With + Accept 확장 추가로 SPA fetch 흉내
          const resp = await fetch(`/product/info?prdtNo=${prdtNo}`, {
            credentials: 'include',
            headers: {
              'Accept': 'application/json, text/plain, */*',
              'X-Requested-With': 'XMLHttpRequest',
            }
          })
          const status = resp.status
          const text = await resp.text()
          let data = null
          try { data = JSON.parse(text) } catch {}
          // 디버그: prdtName 없거나 파싱 실패 시 raw 응답 일부 반환
          if (!data || !data.prdtName) {
            return {
              __debug: true,
              status,
              textPrefix: (text || '').slice(0, 300),
              hasData: !!data,
              dataKeys: data ? Object.keys(data).slice(0, 20) : [],
            }
          }
          const pi = data.productPrice || {}
          return {
            name: (data.prdtName || '').trim(),
            displayPrice: parseInt(data.displayProductPrice || 0),
            sellAmt: parseInt(pi.sellAmt || 0),
            normalAmt: parseInt(pi.normalAmt || 0),
            alwaysDscntAmt: parseInt(data.alwaysDscntAmt || 0),
            loginYn: (data.loginYn || '').toUpperCase(),
            coupons: data.maxBenefitCoupon || data.coupon || [],
          }
        } catch (e) {
          return { error: e.message, errorStack: (e.stack || '').slice(0, 200) }
        }
      },
      args: [productId],
    })

    const apiData = result?.result
    if (!apiData || apiData.error || apiData.__debug) {
      console.log(`[${site}] in-tab fetch: 탭 내 API 실패 (${productId}) DEBUG:`, JSON.stringify(apiData)?.slice(0, 400))
      return null
    }

    const { name, displayPrice, sellAmt, normalAmt, alwaysDscntAmt, loginYn, coupons } = apiData
    const salePrice = displayPrice > 0 ? displayPrice : sellAmt
    if (!salePrice) {
      console.log(`[${site}] in-tab fetch: salePrice 0 (${productId})`)
      return null
    }

    // 비로그인 응답이면 alwaysDscntAmt 못 받음 — null 반환해서 다음 폴백으로
    if (loginYn !== 'Y') {
      console.log(`[${site}] in-tab fetch: 비로그인(loginYn=${loginYn}) → DOM 폴백 (${productId})`)
      return null
    }

    let couponDiscount = 0
    for (const c of coupons) {
      const d = parseInt(c.dscntAmt || 0)
      if (d > couponDiscount) couponDiscount = d
    }

    let benefitPrice = salePrice - alwaysDscntAmt - couponDiscount
    if (benefitPrice <= 0 || benefitPrice > salePrice) benefitPrice = salePrice

    console.log(`[${site}] in-tab fetch 성공: ${productId} sale=${salePrice} membership=${alwaysDscntAmt} coupon=${couponDiscount} benefit=${benefitPrice}`)
    reportLoginSuccess(site)

    return {
      success: true,
      site_product_id: productId,
      name,
      original_price: normalAmt || salePrice,
      sale_price: salePrice,
      best_benefit_price: benefitPrice,
      source_site: site,
    }
  } catch (err) {
    console.error(`[${site}] in-tab fetch 실패:`, err.message)
    return null
  }
}

// 소싱 작업 처리 — 탭 열기 → DOM 파싱 → 결과 전송
async function handleSourcingJob(job) {
  // ABCmart/GrandStage detail: DOM 파싱 1순위 (A안).
  // 검증 결과 ABCmart `/product/info` API는 멤버십 상시할인을 일관성 있게 응답하지 않고
  // 페이지 JS가 별도 처리해 표시. SW/in-tab fetch가 사용자 쿠키 컨텍스트에서
  // 부분 응답을 받아 success 반환할 경우 DOM 파싱이 차단되어 페이지 표시값과 다른
  // 가격이 박히는 문제가 있었음(예: 페이지 77,600 → 시스템 77,300, 멤버십 계산 차이).
  // → fast-path 제거. DOM 파싱이 무조건 1순위.
  // SW/in-tab fetch는 페이지에 "최대 혜택가" 표기 자체가 없는 상품(쿠폰/멤버십 0)에
  // 한해서 DOM 파싱 후 fallback으로만 사용 (904 라인 흐름).

  let tabId = null
  let cleanedUp = false
  // hang 방어 timer — try 안 await가 영원히 대기(예: chrome.scripting.executeScript
  // 페이지 컨텍스트 죽음 감지 못함)해도 강제 cleanup. 100초는 백엔드 wrapper(120초)
  // 보다 짧게 잡아 wrapper 만료 전에 탭 정리되게 함.
  const hangTimer = setTimeout(async () => {
    if (!cleanedUp && tabId) {
      console.warn(`[${job.site}] hang 감지(100s) → 강제 탭 닫기: ${job.productId || job.keyword || ''}`)
      try { await chrome.tabs.remove(tabId) } catch {}
      cleanedUp = true
    }
  }, 100000)
  try {
    // active:false — 병렬 처리 시 여러 탭 동시 오픈 (백그라운드 탭도 JS 렌더링 됨)
    const tab = await chrome.tabs.create({ url: job.url, active: false })
    tabId = tab.id
    await waitForTabLoad(tabId, 30000)

    // GSShop: 동적 DOM 감지 (고정 8초 → 평균 2~3초)
    if (job.type === 'category-scan' && job.site === 'GSShop') {
      await waitForGSShopContent(tabId, 8000)
    } else if (job.type === 'search' && job.site === 'GSShop') {
      await waitForGSShopSearchResults(tabId, 6000)
    } else if (job.type === 'detail' && job.site === 'SSG') {
      await wait(6000) // SSG Next.js hydration 대기
    } else {
      await wait(5000) // SPA 렌더링 대기
    }

    let result = null
    if (job.type === 'category-scan' && job.site === 'GSShop') {
      // GS샵 카테고리 스캔: 검색 결과 페이지에서 카테고리 분포 파싱
      // 동적 대기 완료 — 고정 대기 제거

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
          await waitForTabLoad(tabId, 20000)
          await waitForGSShopSearchResults(tabId, 5000)
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
    } else if (job.type === 'detail' && job.site === 'LOTTEON') {
      // DOM 파싱으로 "나의 혜택가" 수집
      result = await extractDetailData(tabId, job.site, job.productId)
      // 혜택가 미수집 시 3초 대기 후 재시도 (렌더링 지연 대비)
      if (!result?.best_benefit_price) {
        console.log(`[LOTTEON] 혜택가 미수집 — 3초 후 재시도: ${job.productId}`)
        await wait(3000)
        result = await extractDetailData(tabId, job.site, job.productId)
      }
      if (result?.best_benefit_price) {
        console.log(`[LOTTEON] DOM 혜택가: ${job.productId} → ${result.best_benefit_price}`)
      } else {
        console.log(`[LOTTEON] 혜택가 없음: ${job.productId}`)
      }
      // 로그인 검증 — 다중 쿠키 후보로 판정 (단일 fo_at_yn은 의미 불명확).
      // DOM hydration 타이밍 false-positive를 차단하고, 쿠키 이름이 변경되어도 견고.
      // 후보 중 하나라도 의미있는 값이 있으면 로그인 상태로 간주 (사용자 직접 로그인 신뢰).
      try {
        const _isLoggedInByCookie = await _checkLotteonLoggedInByCookies()
        if (result && typeof result === 'object') {
          // _isLoggedInByCookie가 true면 로그인 (DOM의 _loginRequired 무시)
          // false면 비로그인 (자동로그인 신호 유지). null이면 판단 불가 → DOM 결과 유지.
          if (_isLoggedInByCookie === true) {
            result._loginRequired = false
          } else if (_isLoggedInByCookie === false) {
            result._loginRequired = true
          }
        }
      } catch (e) {
        console.log(`[LOTTEON] 쿠키 검증 실패: ${e.message} — DOM 결과 유지`)
      }
    } else if (job.type === 'detail' && (job.site === 'ABCmart' || job.site === 'GrandStage')) {
      // ABCmart/GrandStage: 백그라운드 탭(active=false) DOM 파싱 1순위 — 페이지에
      // 표시된 "최대 혜택가"가 사용자 등급별 멤버십+쿠폰 모두 반영된 100% 정확한 값.
      result = await extractDetailData(tabId, job.site, job.productId)
      if (!result?.best_benefit_price) {
        console.log(`[${job.site}] 혜택가 미수집 — 3초 후 재시도: ${job.productId}`)
        await wait(3000)
        result = await extractDetailData(tabId, job.site, job.productId)
      }
      if (result?.best_benefit_price) {
        console.log(`[${job.site}] DOM 혜택가: ${job.productId} → ${result.best_benefit_price}`)
      } else {
        // DOM에 "최대 혜택가" 표기 자체가 없는 상품(쿠폰/멤버십 모두 0) — SW/in-tab으로 fallback
        // 이 경우엔 sale_price = best_benefit_price이므로 API 계산값으로도 정확
        console.log(`[${job.site}] DOM 혜택가 없음 → API fallback: ${job.productId}`)
        const swResult = await fetchAbcmartBenefitPriceServiceWorker(job.productId, job.site)
        if (swResult && swResult.success) {
          result = result && result.success !== false
            ? { ...result, best_benefit_price: swResult.best_benefit_price, sale_price: result.sale_price || swResult.sale_price, original_price: result.original_price || swResult.original_price }
            : swResult
          console.log(`[${job.site}] SW fetch fallback 성공: ${job.productId} → ${swResult.best_benefit_price}`)
        } else {
          const inTabResult = await fetchAbcmartBenefitPrice(job.productId, job.site)
          if (inTabResult && inTabResult.success) {
            result = result && result.success !== false
              ? { ...result, best_benefit_price: inTabResult.best_benefit_price, sale_price: result.sale_price || inTabResult.sale_price, original_price: result.original_price || inTabResult.original_price }
              : inTabResult
            console.log(`[${job.site}] in-tab fetch fallback 성공: ${job.productId} → ${inTabResult.best_benefit_price}`)
          } else {
            console.log(`[${job.site}] DOM + SW + in-tab 모두 미수집: ${job.productId}`)
            reportLoginFailure(job.site)
          }
        }
      }
    } else if (job.type === 'detail' && job.site === 'SSG') {
      // SSG: reCAPTCHA 감지 후 즉시 실패 반환 (25초 타임아웃 낭비 방지)
      const [captchaCheck] = await chrome.scripting.executeScript({
        target: { tabId },
        world: 'MAIN',
        func: () => {
          const body = document.body?.innerText || ''
          return body.includes('연속적인 접근') || body.includes('로봇이 아닙니다')
        }
      })
      if (captchaCheck?.result) {
        console.log(`[SSG] reCAPTCHA 차단 감지: ${job.productId}`)
        result = { success: false, blocked: true, message: 'SSG reCAPTCHA 차단' }
      } else {
        result = await extractDetailData(tabId, job.site, job.productId)
      }
    } else if (job.type === 'detail') {
      result = await extractDetailData(tabId, job.site, job.productId)
    }

    // 전 사이트 공통 — detail 작업 결과 전송 전 로그인 상태 검증
    // 비로그인 페이지에 마케팅 가격(혜택가/판매가)이 노출되어 잘못된 가격 수집되는 것을 차단
    // 비로그인 감지 시: 결과 전송 차단 + 자동로그인 즉시 트리거
    // [버그수정] 가드 변경: result &&  →  (result == null || result.success !== false)
    // LOTTEON 비로그인 페이지는 extractDetailData가 undefined 반환 → result &&로 인해
    // 로그인 감지 블록이 스킵되어 자동로그인이 트리거 안 되던 문제. result null/undefined도 처리.
    if (job.type === 'detail' && tabId && (result == null || result.success !== false)) {
      let loginNeeded = result?._loginRequired
      if (loginNeeded === undefined) {
        // 자동로그인 성공 직후 N분간 detect 스킵 — _detectLoginStatus false-positive 방지
        // (LOTTEON 상세페이지처럼 헤더 셀렉터로 로그아웃 링크 판정 어려운 사이트의 무한 트리거 차단)
        const AL_GRACE_MS = 30 * 60 * 1000  // 30분
        const siteKey = (typeof alExternalSiteToKey === 'function') ? alExternalSiteToKey(job.site) : null
        const lastAt = (siteKey && globalThis._lastAutoLoginSuccessAt) ? globalThis._lastAutoLoginSuccessAt[siteKey] : 0
        if (lastAt && Date.now() - lastAt < AL_GRACE_MS) {
          // 최근 자동로그인 성공 — detect 스킵 (로그인 상태로 간주)
        } else {
          const isLoggedIn = await _detectLoginStatus(tabId, job.site)
          if (isLoggedIn === false) loginNeeded = true
        }
      }
      if (loginNeeded) {
        console.log(`[${job.site}] 비로그인 확정 → 결과 전송 차단 + 자동로그인 즉시 트리거: ${job.productId}`)
        reportLoginFailure(job.site, true)
        result = { success: false, login_required: true, message: '비로그인 — 자동로그인 후 재시도 필요' }
      } else {
        reportLoginSuccess(job.site)
      }
    }

    if (tabId && !cleanedUp) {
      try { await chrome.tabs.remove(tabId) } catch {}
      cleanedUp = true
    }

    await postResult('sourcing/collect-result', { requestId: job.requestId, data: result || { success: false, message: '파싱 실패' } })
    console.log(`[소싱] ${job.site} 완료: ${result?.products?.length || 0}건`)
  } catch (err) {
    console.error(`[소싱] ${job.site} 오류:`, err)
    try {
      await postResult('sourcing/collect-result', { requestId: job.requestId, data: { success: false, message: err.message } })
    } catch {}
  } finally {
    // 정상/예외 모든 경로에서 hang timer 해제 + 탭 강제 cleanup 보장
    clearTimeout(hangTimer)
    if (tabId && !cleanedUp) {
      try { await chrome.tabs.remove(tabId) } catch {}
      cleanedUp = true
    }
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
        'SSG': /\/itemView\.ssg\?itemId=(\d{10,13})/,
        'ElandMall': /\/goods\/goods\.action\?goodsNo=(\d+)/,
        'SSF': /\/goods\/([A-Z0-9]+)/,
      }
      const pattern = linkPatterns[siteName]
      if (!pattern) return { success: false, products: [], total: 0 }

      // SSG 전용: __NEXT_DATA__ JSON에서 상품 추출 (DOM a 태그보다 정확)
      if (siteName === 'SSG') {
        try {
          const nextDataEl = document.querySelector('script#__NEXT_DATA__')
          if (nextDataEl) {
            const nextData = JSON.parse(nextDataEl.textContent || '{}')
            const queries = nextData?.props?.pageProps?.dehydratedState?.queries || []
            let dataList = []
            for (const q of queries) {
              const qk = q.queryKey || []
              // ssg_sourcing.py와 동일: queryKey에 "fetchSearchItemListArea" 포함 체크
              if (!qk.includes('fetchSearchItemListArea')) continue
              const areaList = q?.state?.data?.areaList || []
              for (const area of areaList) {
                if (area.unitType === 'ITEM_UNIT_LIST') {
                  dataList = area.dataList || []
                  break
                }
              }
              if (dataList.length > 0) break
            }
            for (const it of dataList) {
              if (products.length >= maxItems) break
              const pid = String(it.itemId || '')
              if (!pid || seen.has(pid)) continue
              seen.add(pid)
              let img = it.itemImgUrl || ''
              if (img.startsWith('//')) img = 'https:' + img
              const salePrice = parseInt(String(it.finalPrice || it.sellprc || 0).replace(/[^\d]/g, '')) || 0
              const origPrice = parseInt(String(it.strikeOutPrice || it.norprc || 0).replace(/[^\d]/g, '')) || salePrice
              products.push({
                site_product_id: pid,
                name: it.itemName || '',
                brand: it.repBrandNm || it.brandName || '',
                original_price: origPrice,
                sale_price: salePrice,
                images: img ? [img] : [],
                source_site: 'SSG',
                is_sold_out: !!(it.soldOutMessage || '').trim(),
              })
            }
            if (products.length > 0) {
              return { success: true, products, total: products.length }
            }
          }
        } catch (e) {
          console.warn('[SSG] __NEXT_DATA__ parse 실패, DOM 파싱으로 폴백:', e)
        }
        // 폴백: a 태그 정규식 (아래 일반 로직)
      }

      // 모든 a 태그에서 상품 링크 찾기 (GSShop: 컨테이너 스코핑)
      let allLinks
      if (siteName === 'GSShop') {
        const container = document.querySelector('#searchPrdList .prd-list') || document.querySelector('.prd-list') || document
        allLinks = container.querySelectorAll('a[href]')
      } else {
        allLinks = document.querySelectorAll('a[href]')
      }
      for (const link of allLinks) {
        if (products.length >= maxItems) break
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
          // 상세정보 탭 클릭
          const tabs = document.querySelectorAll('.mm_tab-link, [class*="tab"] a, [class*="tab"] button')
          for (const tab of tabs) {
            if (tab.textContent.trim().includes('상세정보') || tab.textContent.trim().includes('상세 정보')) {
              tab.click()
              break
            }
          }
        }
      })
      await wait(3000) // 상세 컨텐츠 렌더링 대기
    } catch {}
  }

  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: 'MAIN',
    func: (siteName, prdId) => {
      try {
      // ── SSG 전용: HTML + resultItemObj 객체 모두 반환 ──
      if (siteName === 'SSG') {
        try {
          // resultItemObj의 최상위 키 + 카테고리 관련 키만 추출 (디버그)
          const obj = window.resultItemObj || {}
          const ctgKeys = Object.keys(obj).filter(k => k.toLowerCase().includes('ctg') || k.toLowerCase().includes('cat'))
          const ctgFields = {}
          for (const k of ctgKeys) {
            try { ctgFields[k] = obj[k] } catch {}
          }
          // JSON 직렬화 가능한 필드만 추림
          const safeObj = {}
          for (const k of Object.keys(obj)) {
            try {
              const v = obj[k]
              if (v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
                safeObj[k] = v
              } else if (typeof v === 'object' && !Array.isArray(v)) {
                // 중첩 객체 키만 기록 (과대 데이터 방지)
                safeObj[k] = Object.keys(v).length > 0 ? '{' + Object.keys(v).slice(0,10).join(',') + '...}' : '{}'
              } else if (Array.isArray(v)) {
                safeObj[k] = `[array len=${v.length}]`
              }
            } catch {}
          }
          // uitemObjList에서 실제 재고 추출 (AJAX 업데이트 후 값, safeObj는 배열 절삭)
          const uitemOptions = Array.isArray(obj.uitemObjList)
            ? obj.uitemObjList.map(u => ({
                name: u.optnDisplayNm || u.optnNm || u.uitemOptnNm1 || u.uitemNm || '',
                usablInvQty: parseInt(u.usablInvQty) || 0,
                isSoldOut: (parseInt(u.usablInvQty) || 0) === 0,
              })).filter(u => u.name)
            : []
          // DOM 파싱 실재고 — JS 렌더링 후 "남은수량 N" 텍스트에서 추출
          const domSizeUl = document.querySelector('ul.selectLists[id^="select-bundleOpt-"]')
          const domOptions = []
          if (domSizeUl) {
            domSizeUl.querySelectorAll('li').forEach(function(li) {
              const rawTxt = (li.querySelector('.txt, .caption') ? li.querySelector('.txt, .caption').textContent : '').trim()
              const cleanName = rawTxt.replace(/^\[품절\]\s*/, '').replace(/\s*\(남은수량\s*\d+\)/, '').trim()
              if (!cleanName) return
              const isSoldOut = li.classList.contains('disabled')
              const mCnt = rawTxt.match(/남은수량\s*(\d+)/)
              const stock = isSoldOut ? 0 : (mCnt ? parseInt(mCnt[1], 10) : null)
              domOptions.push({ name: cleanName, stock: stock, isSoldOut: isSoldOut })
            })
          }
          return {
            success: true,
            site_product_id: prdId,
            source_site: 'SSG',
            html: document.documentElement.outerHTML,
            resultItemObj: safeObj,  // 1차 평면 구조
            ctgFields: ctgFields,  // 카테고리 관련 전체 필드
            uitemOptions: uitemOptions,  // 옵션별 실제 재고 (AJAX 후 값)
            domOptions: domOptions,  // DOM 파싱 실재고 (JS 렌더링 후, 우선순위 최상)
            url: location.href,
          }
        } catch (e) {
          return { success: false, message: 'SSG HTML 추출 실패: ' + e.message, site_product_id: prdId }
        }
      }
      // Unused-SSG branch (dead code — replaced above)
      if (false && siteName === 'SSG') {
        try {
          const obj = window.resultItemObj || {}
          if (!obj.itemNm) {
            return { success: false, message: 'resultItemObj 없음', site_product_id: prdId }
          }
          // 가격 (문자열/숫자 혼용 → int 정규화)
          const toInt = (v) => {
            if (v == null) return 0
            const n = parseInt(String(v).replace(/[^\d]/g, ''))
            return isNaN(n) ? 0 : n
          }
          const salePrice = toInt(obj.sellprc || obj.finalPrice)
          const bestAmt = toInt(obj.bestAmt)
          const origPrice = toInt(obj.norprc || obj.strikeOutPrice) || salePrice
          // 카테고리 (dispCtg 우선, stdCtg 폴백)
          const dispCtgId = String(obj.dispCtgId || '')
          const c1 = obj.dispCtgLclsNm || obj.stdCtgLclsNm || ''
          const c2 = obj.dispCtgMclsNm || obj.stdCtgMclsNm || ''
          const c3 = obj.dispCtgSclsNm || obj.stdCtgSclsNm || ''
          const catParts = [c1, c2, c3].filter(Boolean)
          const catStr = catParts.join(' > ')
          // 이미지
          const imgs = []
          if (obj.itemImgUrl) {
            let img = obj.itemImgUrl
            if (img.startsWith('//')) img = 'https:' + img
            imgs.push(img)
          }
          // 추가 이미지 (uitemObjList의 이미지도 있을 수 있음)
          if (Array.isArray(obj.imgList)) {
            for (const im of obj.imgList) {
              const url = im.imgFilePath || im.imgUrl || ''
              if (url) {
                let fixed = url
                if (fixed.startsWith('//')) fixed = 'https:' + fixed
                if (!imgs.includes(fixed)) imgs.push(fixed)
              }
            }
          }
          // 옵션 (uitemObjList)
          const options = []
          if (Array.isArray(obj.uitemObjList)) {
            for (const u of obj.uitemObjList) {
              options.push({
                name: u.optnDisplayNm || u.optnNm || '',
                price: toInt(u.addAmt || 0),
                stock: toInt(u.usablInvQty || 99),
                isSoldOut: String(u.usablInvQty || '0') === '0',
              })
            }
          }
          const isSoldOut = String(obj.soldOut || 'N').toUpperCase() === 'Y'
          const result = {
            success: true,
            site_product_id: prdId,
            itemNm: obj.itemNm,
            name: obj.itemNm,
            repBrandNm: obj.repBrandNm || obj.brandNm || '',
            brand: obj.repBrandNm || obj.brandNm || '',
            sellprc: salePrice,
            sale_price: salePrice,
            bestAmt: bestAmt,
            best_benefit_price: bestAmt,
            originalPrice: origPrice,
            original_price: origPrice,
            dispCtgId: dispCtgId,
            dispCtgLclsNm: c1,
            dispCtgMclsNm: c2,
            dispCtgSclsNm: c3,
            category: catStr,
            images: imgs,
            options: options,
            soldOut: isSoldOut ? 'Y' : 'N',
            is_sold_out: isSoldOut,
            sourceUrl: 'https://www.ssg.com/item/itemView.ssg?itemId=' + prdId,
            source_site: 'SSG',
            freeShipping: (obj.shppTypeDtlCd || '').includes('FREE'),
          }
          return result
        } catch (e) {
          return { success: false, message: 'SSG 파싱 실패: ' + e.message, site_product_id: prdId }
        }
      }
      // ── 패션플러스 전용 파싱 ──
      if (siteName === 'FashionPlus') {
        // JSON-LD 기본 정보
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

        // 상품 이미지 — 동일 seller_id의 product_img
        const sellerId = sku.split('_')[0] || ''
        const productImgs = []
        document.querySelectorAll('img').forEach(img => {
          const src = img.src || img.currentSrc || ''
          if (src.includes('product_img') && (!sellerId || src.includes(`/${sellerId}/`)) && !productImgs.includes(src)) {
            productImgs.push(src.replace(/\?.*$/, ''))
          }
        })

        // 상세 이미지 — 상세정보 탭 내 렌더링된 이미지
        const detailImgs = []
        document.querySelectorAll('.mm_tab-item img, [class*="detail"] img, [class*="desc"] img').forEach(img => {
          const src = img.src || img.currentSrc || ''
          if (src && !src.startsWith('data:') && src.includes('http') && !detailImgs.includes(src) && !src.includes('sidebar') && !src.includes('banner') && !src.includes('favicon')) {
            detailImgs.push(src.startsWith('//') ? 'https:' + src : src)
          }
        })

        // 고시정보 (상품 정보 제공고시 테이블)
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

        // 고시정보 필드 매핑
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

        // 배송비 추출
        const feeMatch = document.body.innerHTML.match(/배송비\s*(\d[\d,]+)\s*원/)
        const shippingFee = feeMatch ? parseInt(feeMatch[1].replace(/,/g, '')) : 3000

        // 옵션 (사이즈/색상)
        const options = []
        document.querySelectorAll('select option, [class*="option"] li, [class*="size"] button').forEach(el => {
          const t = el.textContent.trim()
          if (t && t !== '선택' && t !== '옵션을 선택하세요' && t.length < 50) {
            options.push({ name: t, stock: 999, isSoldOut: false })
          }
        })

        // 상세 HTML 조합
        const allDetailImgs = [...new Set([...productImgs, ...detailImgs])]
        const detailHtml = allDetailImgs.map(src =>
          `<div style="text-align:center;"><img src="${src}" style="max-width:860px;width:100%;" /></div>`
        ).join('\n')

        return {
          success: true,
          site_product_id: prdId,
          name, brand, original_price: origPrice, sale_price: salePrice,
          images: productImgs.slice(0, 9),
          detail_images: allDetailImgs,
          detail_html: detailHtml,
          source_site: siteName,
          category: '', category1: '', category2: '', category3: '',
          options,
          material, color, manufacturer, origin,
          care_instructions: careInstructions,
          quality_guarantee: qualityGuarantee,
          shipping_fee: shippingFee,
        }
      }

      // ── 롯데ON 전용 파싱 (렌더된 DOM에서 프로모션가/혜택가 추출) ──
      if (siteName === 'LOTTEON') {
        // 로그인 상태 감지 — 헤더의 "로그인" 링크/버튼 존재 여부로 판단
        // 비로그인이면 자동로그인 트리거 신호로 사용 (LOTTEON 페이지에 "나의 혜택가"가 마케팅 텍스트로 노출되어
        // 비로그인 상태에서도 가격이 추출되는 false-positive를 명시적으로 차단)
        const loginAnchors = document.querySelectorAll('a[href*="/login"], a[href*="member/login"], button[class*="login"], a[class*="login"]')
        const logoutAnchors = document.querySelectorAll('a[href*="/logout"], a[href*="member/logout"], a[href*="/myPage"]')
        let hasLoginLink = false
        let hasLogoutLink = false
        for (const a of loginAnchors) {
          const href = (a.getAttribute('href') || '').toLowerCase()
          if (href.includes('logout')) continue
          const txt = (a.textContent || '').trim()
          if (txt === '로그인' || txt === 'Login' || href.includes('/login') || href.includes('member/login')) {
            hasLoginLink = true
            break
          }
        }
        for (const a of logoutAnchors) {
          const href = (a.getAttribute('href') || '').toLowerCase()
          const txt = (a.textContent || '').trim()
          if (href.includes('logout') || txt === '로그아웃' || href.includes('mypage')) {
            hasLogoutLink = true
            break
          }
        }
        const isLoggedIn = hasLogoutLink && !hasLoginLink

        let salePrice = 0
        let originalPrice = 0
        let benefitPrice = 0
        let name = ''
        let brand = ''

        // 상품명
        const nameEl = document.querySelector('h3[class*="product"], [class*="tit_product"], [class*="product-name"], [class*="pdp-title"]')
        name = nameEl?.textContent?.trim() || document.querySelector('meta[property="og:title"]')?.content || ''

        // 브랜드
        const brandEl = document.querySelector('[class*="brand"] a, [class*="brand-name"]')
        brand = brandEl?.textContent?.trim() || ''

        // 가격: 본문에서 "N원" 패턴 추출
        const bodyText = document.body?.innerText || ''

        // "나의 혜택가" 추출 — "N원 나의 혜택가" 패턴
        const benefitMatch = bodyText.match(/([\d,]+)\s*원\s*나의\s*혜택가/)
        if (benefitMatch) {
          benefitPrice = parseInt(benefitMatch[1].replace(/,/g, ''), 10)
        }

        // 프로모션 판매가 — "N% N원" 패턴 (할인율 + 가격)
        const promoMatch = bodyText.match(/(\d+)%\s+([\d,]+)\s*원/)
        if (promoMatch) {
          salePrice = parseInt(promoMatch[2].replace(/,/g, ''), 10)
        }

        // 정가 — 취소선 가격 (del, s 태그 또는 할인가 옆 큰 숫자)
        const delEl = document.querySelector('del, s, [class*="origin"] [class*="price"], [class*="before"] [class*="price"]')
        if (delEl) {
          const delNum = delEl.textContent.replace(/[^0-9]/g, '')
          if (delNum) originalPrice = parseInt(delNum, 10)
        }
        // 정가 폴백: 본문에서 취소선 가격 옆 숫자
        if (!originalPrice && salePrice > 0) {
          const origMatch = bodyText.match(new RegExp((salePrice).toLocaleString() + '\\s*원\\s+([\\.\\d,]+)'))
          if (origMatch) originalPrice = parseInt(origMatch[1].replace(/[^0-9]/g, ''), 10)
        }
        if (!originalPrice) originalPrice = salePrice

        // 옵션 (사이즈별 재고) — 설계문서 §3.5 정밀 셀렉터 (2026-04-23 Phase 1 실측)
        // 기존 [class*="option"] 셀렉터는 느슨해 가짜 매칭이 많아 교체.
        // 구조: ul.selectLists[id^="select-bundleOpt-"] > li
        //   └── .caption ("075" 또는 "[품절] 075")
        //   └── .stock   ("6개 남음" | "품절" | "" — 빈 값은 10개+ 추정, 백엔드 기존값 유지)
        //   └── li.disabled 클래스 → 품절 플래그 (가장 확실)
        const options = []
        const sizeUl = document.querySelector('ul.selectLists[id^="select-bundleOpt-"]')
        if (sizeUl) {
          sizeUl.querySelectorAll('li').forEach(li => {
            const rawCaption = (li.querySelector('.txt, .caption')?.textContent || '').trim()
            const cleanName = rawCaption.replace(/^\[품절\]\s*/, '').replace(/\s*\(남은수량\s*\d+\)/, '').trim()
            if (!cleanName) return
            const stockText = (li.querySelector('.stock')?.textContent || '').trim()
            const isSoldOut = li.classList.contains('disabled') || stockText === '품절'
            const mStock = stockText.match(/(\d+)\s*개/)
            const mCaption = rawCaption.match(/남은수량\s*(\d+)/)
            // stock: 0=품절, 정수 N=실재고("N개 남음" 또는 caption의 "남은수량 N"), null=UI에 숫자 미노출(충분 재고)
            const stock = isSoldOut ? 0 : (mStock ? parseInt(mStock[1], 10) : (mCaption ? parseInt(mCaption[1], 10) : null))
            options.push({ name: cleanName, stock, isSoldOut, raw: stockText })
          })
        }

        // 이미지
        const images = []
        document.querySelectorAll('[class*="thumb"] img, [class*="swiper"] img, [class*="slide"] img').forEach(img => {
          let src = img.src || img.currentSrc || img.getAttribute('data-src') || ''
          if (src.startsWith('//')) src = 'https:' + src
          if (src && src.includes('http') && !src.includes('data:') && !images.includes(src)) {
            images.push(src)
          }
        })

        // 판매자 지점 (§3.5) — 단일 지점 고정 표기 (고객이 볼 수 있는 재고의 소속).
        // 일부 상품에선 null — 필수 필드 아님, 로그/디버그 전용.
        const sellerEl = document.querySelector('ul.sellerList > li.currentProduct .sellerGrade strong')
        const seller = sellerEl?.textContent?.trim() || null

        if (name || salePrice > 0 || options.length > 0) {
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
            seller,  // "롯데백화점 인천점" 등 — 지점 정보
            pageTitle: document.title,  // 백엔드에서 product.name 정합성 검증용 (§12)
            _loginRequired: !isLoggedIn,  // 비로그인 감지 — handleSourcingJob에서 자동로그인 트리거 신호로 사용
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

        // 범용 파싱 결과에 best_benefit_price만 보강하여 반환
        if (benefitPrice > 0) {
          // 기본 정보도 함께 추출
          let name = ''
          let salePrice = 0
          let originalPrice = 0
          const nameEl = document.querySelector('h2[class*="name"], [class*="prd-name"], [class*="product_name"]')
          name = nameEl?.textContent?.trim() || document.querySelector('meta[property="og:title"]')?.content || ''

          // 정상가/판매가: "최대 혜택가" 이전 영역에서만 추출
          // (이후 영역에는 관련상품/추천상품 카드의 가격이 섞여 있어 잘못 매칭됨)
          // ABCmart 표기 규칙:
          //   - 정상가만: "79,000원" (단독, [%] 미포함)
          //   - 정상가+할인된 판매가: "69,000 55,000원 [20%]" (strikethrough + 할인 후 + 할인율)
          //   - 혜택가는 "최대 혜택가 N원 [P%]" 형태로 [%] 포함 → salePrice/originalPrice 후보에서 제외
          const benefitIdx = bodyText.search(/최대\s*혜택가/)
          const beforeBenefit = benefitIdx > 0 ? bodyText.slice(0, benefitIdx) : bodyText

          // 패턴 A: "정상가 할인가 원 [%]" — 정상가+할인된 판매가
          const discountedMatch = beforeBenefit.match(/(\d{1,3}(?:,\d{3})+)\s+(\d{1,3}(?:,\d{3})+)\s*원\s*\[\d+%\]/)
          if (discountedMatch) {
            originalPrice = parseInt(discountedMatch[1].replace(/,/g, ''), 10)
            salePrice = parseInt(discountedMatch[2].replace(/,/g, ''), 10)
          } else {
            // 패턴 B: 단독 "N,NNN원" 중 가장 큰 값 = 정상가 (할인 없음 → 정상가=판매가)
            // [%] 표기가 따라오는 가격은 제외 (혜택가/할인가)
            const standaloneMatches = [...beforeBenefit.matchAll(/(\d{1,3}(?:,\d{3})+)\s*원(?!\s*\[)/g)]
              .map(m => parseInt(m[1].replace(/,/g, ''), 10))
              .filter(n => n >= 1000)  // 배송비 0원, 적립 100P 등 노이즈 제외
            if (standaloneMatches.length > 0) {
              originalPrice = Math.max(...standaloneMatches)
              salePrice = originalPrice
            }
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

      // ── 범용 파싱 (기존 코드) ──
      // JSON-LD 우선 추출
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
              success: true,
              site_product_id: prdId,
              name: data.name || '',
              original_price: price,
              sale_price: price,
              images: img ? [img] : [],
              brand: typeof brandObj === 'object' ? (brandObj.name || '') : String(brandObj),
              source_site: siteName,
              category: '', category1: '', category2: '', category3: '',
              options: [], detail_html: '',
            }
          }
        } catch {}
      }

      // og:태그 fallback
      const ogTitle = document.querySelector('meta[property="og:title"]')?.content || ''
      const ogImage = document.querySelector('meta[property="og:image"]')?.content || ''
      const ogPrice = document.querySelector('meta[property="product:price:amount"]')?.content || ''

      // DOM 텍스트 기반 추출
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

      // 이미지 (상품 관련)
      const images = []
      document.querySelectorAll('img').forEach(img => {
        const src = img.src || img.currentSrc || img.getAttribute('data-src') || ''
        if (src && (src.includes('product') || src.includes('goods') || src.includes('prd')) && !images.includes(src)) {
          images.push(src.startsWith('//') ? 'https:' + src : src)
        }
      })

      // 옵션 (사이즈/색상 select 또는 버튼)
      const options = []
      document.querySelectorAll('select option, [class*="option"] li, [class*="size"] button, [class*="size"] a').forEach(el => {
        const text = el.textContent.trim()
        if (text && text !== '선택' && text.length < 30) {
          options.push({ name: text, stock: 999 })
        }
      })

      // 카테고리 (breadcrumb)
      const breadcrumb = document.querySelector('[class*="breadcrumb"], [class*="location"], nav[aria-label="breadcrumb"]')
      let cats = []
      if (breadcrumb) {
        cats = Array.from(breadcrumb.querySelectorAll('a, span, li'))
          .map(el => el.textContent.trim())
          .filter(t => t.length > 1 && t !== '>' && t !== 'Home' && t !== '홈')
      }

      return {
        success: true,
        site_product_id: prdId,
        name: ogTitle || document.title || `${siteName} ${prdId}`,
        original_price: originalPrice || salePrice,
        sale_price: salePrice,
        images: images.length > 0 ? images.slice(0, 10) : (ogImage ? [ogImage] : []),
        brand: '',
        source_site: siteName,
        category: cats.join(' > '),
        category1: cats[0] || '',
        category2: cats[1] || '',
        category3: cats[2] || '',
        options,
        detail_html: '',
      }
      } catch (e) {
        return { success: false, message: `스크립트 에러: ${e.message}`, url: location.href }
      }
    },
    args: [site, productId]
  })

  return result?.result || { success: false, message: 'DOM 파싱 실패' }
}

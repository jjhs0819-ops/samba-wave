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

// 탭 로드 완료 대기 — 이벤트 구동 방식 (500ms 폴링 제거)
function waitForTabLoad(tabId, timeout) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener)
      reject(new Error('탭 로드 타임아웃'))
    }, timeout)
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') {
        clearTimeout(timer)
        chrome.tabs.onUpdated.removeListener(listener)
        resolve()
      }
    }
    chrome.tabs.onUpdated.addListener(listener)
    // 이미 complete인 경우 즉시 resolve
    chrome.tabs.get(tabId, (tab) => {
      if (!chrome.runtime.lastError && tab?.status === 'complete') {
        clearTimeout(timer)
        chrome.tabs.onUpdated.removeListener(listener)
        resolve()
      }
    })
  })
}

function wait(ms) {
  return new Promise(r => setTimeout(r, ms))
}

// GSShop 카테고리 렌더링 동적 대기 — "(숫자)" 패턴 3개 이상 출현 시 즉시 리턴
async function waitForGSShopContent(tabId, timeoutMs = 8000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const [check] = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => (document.body?.innerText?.match(/\(\d[\d,]*\)/g) || []).length >= 3
      })
      if (check?.result) return true
    } catch {}
    await wait(100)
  }
  return false
}

// GSShop 검색 결과 렌더링 동적 대기 — 상품 링크 1개 이상 출현 시 즉시 리턴
async function waitForGSShopSearchResults(tabId, timeoutMs = 6000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const [check] = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => document.querySelectorAll('a[href*="prd.gs"], a[href*="deal.gs"]').length >= 1
      })
      if (check?.result) return true
    } catch {}
    await wait(100)
  }
  return false
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

// 집중 폴링 모드 — job 발견 시 0.5초 간격 최대 120회 (약 60초)
let focusPollActive = false
async function runFocusPoll() {
  if (focusPollActive) return
  focusPollActive = true
  console.log('[수집] 집중 폴링 모드 진입 (0.5초 간격, 최대 120회)')
  let emptyCount = 0
  while (emptyCount < 120) {
    if (Date.now() < pollPausedUntil) break
    // KREAM/AI소싱 폴링 비활성화
    const hadSourcing = await pollSourcingOnce()
    if (hadSourcing) {
      emptyCount = 0
    } else {
      emptyCount++
    }
    if (emptyCount < 120) await wait(500)
  }
  focusPollActive = false
  console.log('[수집] 집중 폴링 종료 → alarm 대기 모드 (30초 주기)')
}

// alarm 트리거 시 1회 폴링 — job 있으면 집중 모드 진입, 없으면 카운트 증가
let emptyPollCount = 0
let pollPausedUntil = 0

function pauseCollectPolling(ms, reason) {
  const nextUntil = Date.now() + ms
  if (nextUntil > pollPausedUntil) {
    pollPausedUntil = nextUntil
    console.log(`[수집] 폴링 일시중지 ${Math.ceil(ms / 1000)}초: ${reason}`)
  }
}
const MAX_EMPTY_POLLS = 300 // 1초 × 300 = 5분간 빈 결과 → 중지

async function runPollCycle() {
  if (Date.now() < pollPausedUntil) return
  // KREAM(pollCollectOnce, pollSearchOnce), AI소싱(pollAiSourcingOnce) 폴링 비활성화 — 401 오류 방지
  const hadSourcing = await pollSourcingOnce()
  if (hadSourcing) {
    emptyPollCount = 0
    runFocusPoll()
  }
  // 자동중지 제거 — 확장앱이 켜져 있는 한 항상 폴링 (혜택가 수집용)
}

// 수집 폴링 — job 없으면 5분 후 자동 중지
let quickPollTimer = null

function startCollectPolling() {
  emptyPollCount = 0
  pollPausedUntil = 0
  chrome.alarms.get('collectPoll', (alarm) => {
    if (!alarm) {
      chrome.alarms.create('collectPoll', { periodInMinutes: 0.5 })
      console.log('[수집] alarm 등록 (30초/실제 1분 백업)')
    }
  })
  // setInterval 1초 보조 폴링 — 서비스 워커 활성 중 빠른 응답
  if (!quickPollTimer) {
    quickPollTimer = setInterval(() => {
      if (!focusPollActive) runPollCycle()
    }, 1_000)
    console.log('[수집] 폴링 시작 (1초 주기 + alarm 백업)')
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

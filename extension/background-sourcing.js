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

const SOURCING_MAX_CONCURRENT = 5

async function pollSourcingOnce() {
  // 최대 SOURCING_MAX_CONCURRENT개 job을 가져와서 병렬 처리
  const jobs = []
  for (let i = 0; i < SOURCING_MAX_CONCURRENT; i++) {
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
      console.log(`[소싱] ${job.url || '작업 수신'} (${jobs.length + 1}/${SOURCING_MAX_CONCURRENT})`)
      jobs.push(job)
    } catch {
      pauseCollectPolling(10000, 'backend unreachable')
      break
    }
  }
  if (jobs.length === 0) return false
  if (jobs.length === 1) {
    await handleSourcingJob(jobs[0])
  } else {
    console.log(`[소싱] 병렬 처리: ${jobs.length}개`)
    await Promise.all(jobs.map(job => handleSourcingJob(job)))
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

// ABCmart/GrandStage: 쿠키 기반 info API 직접 호출로 혜택가 수집 (탭 불필요)
async function fetchAbcmartBenefitPrice(productId, site) {
  try {
    // 기존 a-rt.com 탭에서 info API 호출 (페이지 컨텍스트 = 세션+인증 자동 포함)
    const tabs = await chrome.tabs.query({ url: '*://*.a-rt.com/*' })
    if (!tabs.length) {
      console.log(`[${site}] maxBenefitCoupon: a-rt.com 탭 없음 → DOM 폴백 (${productId})`)
      return null
    }

    const tabId = tabs[0].id
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: async (prdtNo) => {
        try {
          const resp = await fetch(`/product/info?prdtNo=${prdtNo}`, {
            credentials: 'include',
            headers: { 'Accept': 'application/json' }
          })
          const data = await resp.json()
          if (!data || !data.prdtName) return null
          const pi = data.productPrice || {}
          return {
            name: (data.prdtName || '').trim(),
            salePrice: parseInt(pi.sellAmt || 0),
            normalAmt: parseInt(pi.normalAmt || 0),
            coupons: data.maxBenefitCoupon || data.coupon || [],
          }
        } catch (e) {
          return { error: e.message }
        }
      },
      args: [productId],
    })

    const apiData = result?.result
    if (!apiData || apiData.error || !apiData.salePrice) {
      console.log(`[${site}] maxBenefitCoupon: 탭 내 API 실패 (${productId})`, apiData?.error || '')
      return null
    }

    const { name, salePrice, normalAmt, coupons } = apiData
    let totalDiscount = 0
    for (const c of coupons) {
      totalDiscount += parseInt(c.dscntAmt || 0)
    }

    let benefitPrice = totalDiscount > 0 ? salePrice - totalDiscount : 0
    if (benefitPrice <= 0 || benefitPrice >= salePrice) benefitPrice = 0

    console.log(`[${site}] maxBenefitCoupon: ${productId} sale=${salePrice}, discount=${totalDiscount}, benefit=${benefitPrice}`)
    console.log(`[${site}] maxBenefitCoupon 상세:`, JSON.stringify(coupons))

    if (benefitPrice > 0) {
      return {
        success: true,
        site_product_id: productId,
        name,
        original_price: normalAmt || salePrice,
        sale_price: salePrice,
        best_benefit_price: benefitPrice,
        source_site: site,
      }
    }
    return null
  } catch (err) {
    console.error(`[${site}] maxBenefitCoupon 실패:`, err.message)
    return null
  }
}

// 네이버스토어 상세 — 탭 컨텍스트에서 내부 JSON API(/i/v2) 직접 호출
// 서버 측 curl_cffi/httpx는 모두 429 차단되지만, 실브라우저 same-origin fetch는 통과
async function fetchNaverstoreDetail(tabId, channelUid, productId) {
  if (!channelUid || !productId) {
    return { success: false, message: 'channelUid/productId 누락' }
  }
  const apiUrl = `https://smartstore.naver.com/i/v2/channels/${channelUid}/products/${productId}?withWindow=false`
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: async (url) => {
        try {
          const r = await fetch(url, {
            credentials: 'include',
            headers: { 'Accept': 'application/json, text/plain, */*' }
          })
          if (!r.ok) return { error: `HTTP ${r.status}` }
          const data = await r.json()
          return { data }
        } catch (e) {
          return { error: e.message }
        }
      },
      args: [apiUrl]
    })
    const payload = res?.result
    if (!payload || payload.error) {
      console.log(`[NAVERSTORE] 상세 fetch 실패: ${payload?.error || 'no result'}`)
      return { success: false, message: payload?.error || '탭 fetch 실패' }
    }
    const raw = payload.data
    const product = raw?.data && typeof raw.data === 'object' && raw.data.id ? raw.data : raw
    if (!product?.id) {
      console.log(`[NAVERSTORE] 상세 응답에 id 없음 — keys=${Object.keys(product || {}).slice(0, 10).join(',')}`)
      return { success: false, message: 'product.id 없음' }
    }
    console.log(`[NAVERSTORE] 상세 수집 성공: pid=${product.id} name="${(product.name || '').slice(0, 30)}"`)
    return { success: true, data: product }
  } catch (err) {
    console.error('[NAVERSTORE] 상세 예외:', err.message)
    return { success: false, message: err.message }
  }
}

// 소싱 작업 처리 — 탭 열기 → DOM 파싱 → 결과 전송
async function handleSourcingJob(job) {
  let tabId = null
  try {
    // active:false — 병렬 처리 시 여러 탭 동시 오픈 (백그라운드 탭도 JS 렌더링 됨)
    const tab = await chrome.tabs.create({ url: job.url, active: false })
    tabId = tab.id
    await waitForTabLoad(tabId, 15000)

    // GSShop: 동적 DOM 감지 (고정 8초 → 평균 2~3초)
    if (job.type === 'category-scan' && job.site === 'GSShop') {
      await waitForGSShopContent(tabId, 8000)
    } else if (job.type === 'search' && job.site === 'GSShop') {
      await waitForGSShopSearchResults(tabId, 6000)
    } else if (job.type === 'detail' && job.site === 'NAVERSTORE') {
      // NAVERSTORE 상세는 DOM 파싱이 아닌 consumer API fetch — SPA 렌더링 대기 불필요
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
          await waitForTabLoad(tabId, 15000)
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
        console.log(`[LOTTEON] 혜택가 없음 (로그인 필요?): ${job.productId}`)
      }
    } else if (job.type === 'detail' && (job.site === 'ABCmart' || job.site === 'GrandStage')) {
      // ABCmart/GrandStage SPA 렌더링 대기 후 최대혜택가 파싱
      result = await extractDetailData(tabId, job.site, job.productId)
      if (!result?.best_benefit_price) {
        console.log(`[${job.site}] 혜택가 미수집 — 3초 후 재시도: ${job.productId}`)
        await wait(3000)
        result = await extractDetailData(tabId, job.site, job.productId)
      }
      if (result?.best_benefit_price) {
        console.log(`[${job.site}] DOM 혜택가: ${job.productId} → ${result.best_benefit_price}`)
      } else {
        console.log(`[${job.site}] 혜택가 없음: ${job.productId}`)
      }
    } else if (job.type === 'detail' && job.site === 'NAVERSTORE') {
      // 네이버스토어 — 탭 컨텍스트에서 내부 JSON API 호출 (서비스 워커 직접 fetch는 429 차단됨)
      result = await fetchNaverstoreDetail(tabId, job.channelUid, job.productId)
    } else if (job.type === 'detail') {
      result = await extractDetailData(tabId, job.site, job.productId)
    }

    try { await chrome.tabs.remove(tabId) } catch {}

    await postResult('sourcing/collect-result', { requestId: job.requestId, data: result || { success: false, message: '파싱 실패' } })
    console.log(`[소싱] ${job.site} 완료: ${result?.products?.length || 0}건`)
  } catch (err) {
    console.error(`[소싱] ${job.site} 오류:`, err)
    if (tabId) try { await chrome.tabs.remove(tabId) } catch {}
    try {
      await postResult('sourcing/collect-result', { requestId: job.requestId, data: { success: false, message: err.message } })
    } catch {}
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
        'SSG': /itemView\.ssg\?itemId=(\d{10,13})/,
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
          return {
            success: true,
            site_product_id: prdId,
            source_site: 'SSG',
            html: document.documentElement.outerHTML,
            resultItemObj: safeObj,  // 1차 평면 구조
            ctgFields: ctgFields,  // 카테고리 관련 전체 필드
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
        // 프로모션 판매가 (65,400원 등)
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

        // 옵션 (사이즈 등)
        const options = []
        // 롯데ON: 옵션 select 또는 버튼 목록
        document.querySelectorAll('[class*="option"] li, [class*="option"] button, select option').forEach(el => {
          const t = el.textContent.trim()
          if (!t || t === '선택하세요.' || t.length > 50) return
          const isSoldOut = t.includes('품절')
          // "N개 남음" 패턴에서 실재고 추출
          const stockMatch = t.match(/(\d+)\s*개\s*남음/)
          let stock = 0
          if (isSoldOut) stock = 0
          else if (stockMatch) stock = parseInt(stockMatch[1], 10)
          else stock = 1 // 재고 있지만 수량 불명 → sentinel 1 (worker에서 99로 변환)
          // 옵션명에서 "[품절]", "N개 남음", "(품절임박)" 제거
          const cleanName = t.replace(/\[품절\]\s*/g, '').replace(/\s*\d+개\s*남음.*/, '').replace(/\s*\(품절임박\)/, '').trim()
          if (cleanName) {
            options.push({ name: cleanName, stock, isSoldOut })
          }
        })

        // 이미지
        const images = []
        document.querySelectorAll('[class*="thumb"] img, [class*="swiper"] img, [class*="slide"] img').forEach(img => {
          let src = img.src || img.currentSrc || img.getAttribute('data-src') || ''
          if (src.startsWith('//')) src = 'https:' + src
          if (src && src.includes('http') && !src.includes('data:') && !images.includes(src)) {
            images.push(src)
          }
        })

        if (name || salePrice > 0) {
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

          // 판매가: "N원 [N%]" 패턴
          const priceMatch = bodyText.match(/([\d,]+)\s*원\s*\[\d+%\]/)
          if (priceMatch) salePrice = parseInt(priceMatch[1].replace(/,/g, ''), 10)

          // 정가
          const origMatch = bodyText.match(/([\d,]+)\s*원\s+([\d,]+)\s*원/)
          if (origMatch) {
            originalPrice = parseInt(origMatch[1].replace(/,/g, ''), 10)
            if (!salePrice) salePrice = parseInt(origMatch[2].replace(/,/g, ''), 10)
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

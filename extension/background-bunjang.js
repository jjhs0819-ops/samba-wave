// ==================== 번개장터 검색 큐 폴링 ====================
// 검색 API가 브라우저 서명 헤더(X-BUN-AUTH-TOKEN/X-BUN-CONTEXT)를 요구해 서버 직접호출 불가.
// 확장앱이 실제 검색 페이지를 열어 DOM에서 목록을 추출한다. 상세 조회는 서버가 직접 API 호출.

function pollBunjangSearchOnce() {
  return pollOnce('bunjang/search-queue', handleBunjangSearchJob, '번개장터', 'keyword')
}

async function handleBunjangSearchJob(job) {
  let tabId = null
  try {
    const tab = await chrome.tabs.create({ url: job.url, active: false })
    tabId = tab.id

    await waitForTabLoad(tabId, 30000)
    await wait(2500) // SPA 렌더링 대기

    const targetCount = job.count || 30
    const maxScrolls = Math.min(Math.ceil(targetCount / 20), 8)
    let prevCount = 0

    for (let scroll = 0; scroll < maxScrolls; scroll++) {
      const [countResult] = await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => document.querySelectorAll('a[href*="/products/"]').length
      })
      const currentCount = countResult?.result || 0
      if (currentCount >= targetCount || (scroll > 0 && currentCount === prevCount)) break
      prevCount = currentCount

      await chrome.scripting.executeScript({
        target: { tabId }, world: 'MAIN',
        func: () => window.scrollTo(0, document.body.scrollHeight)
      })
      await wait(1500)
    }

    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: () => {
        const seen = new Set()
        const items = []
        document.querySelectorAll('a[href*="/products/"]').forEach(link => {
          const href = link.getAttribute('href') || ''
          const idMatch = href.match(/\/products\/(\d+)/)
          if (!idMatch || seen.has(idMatch[1])) return
          seen.add(idMatch[1])
          const texts = Array.from(link.querySelectorAll('*'))
            .filter(el => el.children.length === 0)
            .map(el => el.textContent.trim())
            .filter(t => t.length > 0)
          const priceText = texts.find(t => /원$/.test(t)) || ''
          const name = texts.find(t => t !== priceText && !/^\d+분 전$|^\d+시간 전$|^\d+일 전$|^\d+$/.test(t)) || ''
          const img = link.querySelector('img')
          const rawImg = img?.src || img?.getAttribute('src') || ''
          items.push({
            pid: idMatch[1],
            name,
            price: parseInt(priceText.replace(/[^0-9]/g, '')) || 0,
            status: 'SELLING',
            ad: false,
            productImage: rawImg.split('?')[0]
          })
        })
        return items
      }
    })

    try { await chrome.tabs.remove(tabId) } catch {}
    tabId = null

    const items = results?.[0]?.result || []
    console.log(`[번개장터] 검색 DOM 파싱: ${items.length}개`)

    await postResult('bunjang/search-result', { requestId: job.requestId, data: items })
    console.log(`[번개장터] 검색 완료: "${job.keyword}" → ${items.length}개`)
  } catch (err) {
    console.error('[번개장터] 검색 오류:', err)
    if (tabId) { try { await chrome.tabs.remove(tabId) } catch {} }
    try {
      await postResult('bunjang/search-result', { requestId: job.requestId, data: [] })
    } catch {}
  }
}

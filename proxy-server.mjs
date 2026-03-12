/**
 * 무신사 실제 수집 프록시 서버
 * 실행: node proxy-server.mjs
 * 포트: 3001
 *
 * 브라우저 앱에서 CORS 없이 무신사 데이터를 가져오기 위한 로컬 프록시
 */

import express from 'express'
import cors from 'cors'
import { createServer } from 'http'

const app = express()
const PORT = 3001

// 무신사 요청용 브라우저 헤더
const MUSINSA_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'ko-KR,ko;q=0.9',
  'Referer': 'https://www.musinsa.com/',
  'Cache-Control': 'no-cache',
}

app.use(cors())
app.use(express.json())

// ─────────────────────────────────────────────
// 유틸: 무신사 상품 페이지 HTML → 상품 데이터 추출
// ─────────────────────────────────────────────
function parseMusinsaProduct(html, goodsNo) {
  const ndMatch = html.match(/<script id="__NEXT_DATA__" type="application\/json">([\s\S]*?)<\/script>/)
  if (!ndMatch) return null

  let nd
  try {
    nd = JSON.parse(ndMatch[1])
  } catch {
    return null
  }

  const meta = nd.props?.pageProps?.meta
  if (!meta || meta.meta?.result !== 'SUCCESS' || !meta.data) return null

  const d = meta.data
  const gp = d.goodsPrice || {}

  // 이미지 URL 보정 (CDN 도메인 추가)
  const toImageUrl = (path) => {
    if (!path) return ''
    if (path.startsWith('http')) return path
    return `https://image.msscdn.net${path}`
  }

  return {
    id: `col_musinsa_${goodsNo}_${Date.now()}`,
    sourceSite: 'MUSINSA',
    siteProductId: String(d.goodsNo || goodsNo),
    sourceUrl: `https://www.musinsa.com/app/goods/${goodsNo}`,
    searchFilterId: null,
    name: d.goodsNm || '',
    nameEn: d.goodsNmEng || '',
    nameJa: '',
    brand: d.brandInfo?.brandName || d.brand || '',
    brandCode: d.brand || '',
    category: d.category?.categoryDepth2Name || d.category?.categoryDepth1Name || '',
    categoryCode: d.category?.categoryDepth2Code || d.category?.categoryDepth1Code || '',
    images: [
      toImageUrl(d.thumbnailImageUrl),
      ...(d.goodsImages || []).map(img => toImageUrl(img.imageUrl)).slice(0, 4)
    ].filter(Boolean),
    options: [],
    originalPrice: gp.normalPrice || gp.salePrice || 0,
    salePrice: gp.salePrice || gp.normalPrice || 0,
    discountRate: gp.discountRate || 0,
    status: 'collected',
    appliedPolicyId: null,
    marketPrices: {},
    updateEnabled: true,
    priceUpdateEnabled: true,
    stockUpdateEnabled: true,
    marketTransmitEnabled: true,
    registeredAccounts: [],
    sex: d.sex || [],
    storeCodes: d.storeCodes || [],
    isOutlet: d.isOutlet || false,
    isSale: gp.isSale || false,
    collectedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  }
}

// ─────────────────────────────────────────────
// API: 단일 상품 수집 (상품번호로)
// GET /api/musinsa/goods/:goodsNo
// ─────────────────────────────────────────────
app.get('/api/musinsa/goods/:goodsNo', async (req, res) => {
  const { goodsNo } = req.params
  if (!goodsNo || !/^\d+$/.test(goodsNo)) {
    return res.status(400).json({ success: false, message: '유효하지 않은 상품번호입니다.' })
  }

  try {
    const url = `https://www.musinsa.com/app/goods/${goodsNo}`
    const response = await fetch(url, { headers: MUSINSA_HEADERS })

    if (!response.ok) {
      return res.status(response.status).json({ success: false, message: `무신사 응답 오류: ${response.status}` })
    }

    const html = await response.text()
    const product = parseMusinsaProduct(html, goodsNo)

    if (!product) {
      return res.status(404).json({ success: false, message: '상품을 찾을 수 없습니다.' })
    }

    return res.json({ success: true, data: product })
  } catch (err) {
    return res.status(500).json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// API: URL로 상품 수집 (전체 무신사 URL 입력)
// POST /api/musinsa/collect-url
// body: { url: "https://www.musinsa.com/app/goods/3900000" }
// ─────────────────────────────────────────────
app.post('/api/musinsa/collect-url', async (req, res) => {
  const { url } = req.body
  if (!url) return res.status(400).json({ success: false, message: 'URL을 입력해주세요.' })

  // goodsNo 추출
  const match = url.match(/\/(?:app\/)?goods\/(\d+)/)
  if (!match) {
    return res.status(400).json({ success: false, message: '무신사 상품 URL이 아닙니다. (예: /app/goods/3900000)' })
  }

  const goodsNo = match[1]
  req.params = { goodsNo }
  return app._router.handle({ ...req, url: `/api/musinsa/goods/${goodsNo}`, params: { goodsNo } }, res, () => {})
})

// ─────────────────────────────────────────────
// API: 범위 스캔 수집 (검색어 기반 ID 스캔)
// GET /api/musinsa/scan?startId=3900000&count=20&keyword=나이키
// ─────────────────────────────────────────────
app.get('/api/musinsa/scan', async (req, res) => {
  const startId = parseInt(req.query.startId) || 3900000
  const maxCount = Math.min(parseInt(req.query.count) || 20, 100) // 최대 100개
  const keyword = (req.query.keyword || '').toLowerCase()
  const storeCode = req.query.storeCode || '' // musinsa, outlet 등

  const found = []
  const maxScan = maxCount * 10 // 최대 탐색 범위
  let scanned = 0

  // SSE(Server-Sent Events)로 실시간 진행 상황 전송
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')

  const sendEvent = (data) => {
    res.write(`data: ${JSON.stringify(data)}\n\n`)
  }

  sendEvent({ type: 'start', startId, maxCount, keyword })

  let currentId = startId
  while (found.length < maxCount && scanned < maxScan) {
    try {
      const url = `https://www.musinsa.com/app/goods/${currentId}`
      const response = await fetch(url, { headers: MUSINSA_HEADERS })

      if (response.ok) {
        const html = await response.text()
        const product = parseMusinsaProduct(html, currentId)

        if (product) {
          // 키워드 필터링
          const matchKeyword = !keyword ||
            product.name.toLowerCase().includes(keyword) ||
            product.brand.toLowerCase().includes(keyword)

          // 스토어코드 필터링
          const matchStore = !storeCode ||
            product.storeCodes.includes(storeCode)

          if (matchKeyword && matchStore) {
            found.push(product)
            sendEvent({ type: 'product', product, current: found.length, total: maxCount })
          }
        }
      }
    } catch {}

    currentId++
    scanned++

    // rate limit - 100ms 간격
    await new Promise(r => setTimeout(r, 100))
  }

  sendEvent({ type: 'done', found: found.length, scanned })
  res.end()
})

// ─────────────────────────────────────────────
// API: 추천 상품 목록 (알려진 유효 ID 범위 수집)
// GET /api/musinsa/bulk?startId=3900000&endId=3900050&storeCode=musinsa
// ─────────────────────────────────────────────
app.get('/api/musinsa/bulk', async (req, res) => {
  const startId = parseInt(req.query.startId) || 3900000
  const endId = Math.min(parseInt(req.query.endId) || startId + 30, startId + 160)
  const storeCode = req.query.storeCode || ''
  const keyword = (req.query.keyword || '').toLowerCase()

  const results = []
  const errors = []

  // 병렬 처리 (10개씩)
  const batchSize = 10
  const ids = Array.from({ length: endId - startId + 1 }, (_, i) => startId + i)

  for (let i = 0; i < ids.length; i += batchSize) {
    const batch = ids.slice(i, i + batchSize)
    const promises = batch.map(async (goodsNo) => {
      try {
        const url = `https://www.musinsa.com/app/goods/${goodsNo}`
        const response = await fetch(url, { headers: MUSINSA_HEADERS })
        if (!response.ok) return null
        const html = await response.text()
        return parseMusinsaProduct(html, goodsNo)
      } catch {
        return null
      }
    })

    const batchResults = await Promise.all(promises)
    batchResults.forEach((p) => {
      if (!p) return
      const matchKeyword = !keyword ||
        p.name.toLowerCase().includes(keyword) ||
        p.brand.toLowerCase().includes(keyword)
      const matchStore = !storeCode || p.storeCodes.includes(storeCode)
      if (matchKeyword && matchStore) results.push(p)
    })

    // rate limit
    await new Promise(r => setTimeout(r, 50))
  }

  return res.json({
    success: true,
    count: results.length,
    scanned: ids.length,
    data: results
  })
})

// ─────────────────────────────────────────────
// API: 상태 확인
// GET /api/health
// ─────────────────────────────────────────────
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', message: '무신사 프록시 서버 정상 작동중', port: PORT })
})

// ─────────────────────────────────────────────
// 서버 시작
// ─────────────────────────────────────────────
const server = createServer(app)
server.listen(PORT, () => {
  console.log(`
╔══════════════════════════════════════════════════╗
║       무신사 실제 수집 프록시 서버 시작         ║
║  포트: http://localhost:${PORT}                      ║
╠══════════════════════════════════════════════════╣
║  엔드포인트:                                    ║
║  GET  /api/health               상태 확인       ║
║  GET  /api/musinsa/goods/:id    단일 상품 수집   ║
║  GET  /api/musinsa/bulk         범위 수집 (JSON) ║
║  GET  /api/musinsa/scan         실시간 스캔(SSE) ║
╚══════════════════════════════════════════════════╝
  `)
})

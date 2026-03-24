// KREAM 상품 페이지 Content Script
// 더망고 패턴: DOM 읽기만 한다
// 옵션(사이즈/가격)은 background.js에서 chrome.debugger CDP 클릭으로 이미 수집
// → preCollectedOptions로 전달받아 그대로 사용

const LOG_PREFIX = '[KREAM CS]'

// background에서 수집 요청 수신
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'COLLECT_KREAM') {
    collectProductData(msg.collectSizes, msg.nuxtData || null, msg.preCollectedOptions || null)
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, message: err.message }))
    return true
  }
})

// ==================== 메인 수집 흐름 ====================

async function collectProductData(collectSizes = true, preNuxtData = null, preCollectedOptions = null) {
  console.log(`${LOG_PREFIX} 수집 시작`)

  // 1. __NUXT__ 데이터: background scripting API로 받은 것 우선, 없으면 스크립트 주입 시도
  const nuxtData = preNuxtData || await extractNuxtData()
  if (preNuxtData) console.log(`${LOG_PREFIX} __NUXT__ scripting API 데이터 사용`)

  // 2. DOM에서 기본 정보 추출
  const basicInfo = extractBasicInfo()

  // 3. __NUXT__ 데이터 병합 (있으면 더 정확)
  if (nuxtData) {
    mergeNuxtData(basicInfo, nuxtData)
    console.log(`${LOG_PREFIX} __NUXT__ 데이터 병합 완료`)
  }

  // 4. 이미지 수집 (jsonLd 우선 → DOM fallback)
  basicInfo.images = extractImages(nuxtData)

  // 5. 배송 기본 정보
  basicInfo.deliveryInfo = extractDeliveryInfo()

  // 6. ★ 옵션: background에서 CDP 클릭으로 이미 수집한 경우 그대로 사용
  if (preCollectedOptions && preCollectedOptions.length > 0) {
    basicInfo.options = preCollectedOptions
    console.log(`${LOG_PREFIX} preCollectedOptions 사용: ${preCollectedOptions.length}개`)
  }

  // 7. 상품 ID 추출 (URL에서)
  const urlMatch = location.pathname.match(/\/products\/(\d+)/)
  basicInfo.siteProductId = urlMatch ? urlMatch[1] : ''
  basicInfo.sourceUrl = location.href

  console.log(`${LOG_PREFIX} 수집 완료: ${basicInfo.name} (사이즈 ${basicInfo.options.length}개, 이미지 ${basicInfo.images.length}개)`)
  return basicInfo
}

// ==================== __NUXT__ 데이터 추출 (스크립트 주입 방식) ====================
// Content Script는 격리 환경(isolated world)에서 실행되므로
// window.__NUXT__에 직접 접근 불가 → 페이지 컨텍스트에 <script> 주입하여
// CustomEvent로 데이터를 전달받는 방식 사용

async function extractNuxtData() {
  // 최대 3회 시도 (하이드레이션 타이밍 대응)
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt > 0) await wait(1000)

    const result = await new Promise(resolve => {
      const eventName = `__NUXT_EXTRACTED_${Date.now()}_${attempt}__`
      let settled = false

      // CustomEvent 수신 리스너
      const handler = (e) => {
        if (settled) return
        settled = true
        document.removeEventListener(eventName, handler)
        try { resolve(JSON.parse(e.detail)) }
        catch { resolve(null) }
      }
      document.addEventListener(eventName, handler)

      // 페이지 컨텍스트에 스크립트 주입
      const script = document.createElement('script')
      script.textContent = `
        (function() {
          let result = null
          try {
            if (window.__NUXT__ && window.__NUXT__.data) {
              const data = window.__NUXT__.data
              const keys = Object.keys(data)
              for (let i = 0; i < keys.length; i++) {
                const key = keys[i]
                if (key.includes('product-detail') && data[key] && data[key].jsonLd) {
                  result = { jsonLd: data[key].jsonLd, key: key, raw: data[key] }
                  break
                }
              }
              if (!result) {
                for (let i = 0; i < keys.length; i++) {
                  const key = keys[i]
                  if (data[key] && data[key].jsonLd) {
                    result = { jsonLd: data[key].jsonLd, key: key, raw: data[key] }
                    break
                  }
                }
              }
            }
          } catch(e) {}
          document.dispatchEvent(new CustomEvent('${eventName}', {
            detail: JSON.stringify(result)
          }))
        })()
      `
      const target = document.head || document.documentElement
      target.appendChild(script)
      script.remove()

      // 타임아웃 (2초)
      setTimeout(() => {
        if (settled) return
        settled = true
        document.removeEventListener(eventName, handler)
        resolve(null)
      }, 2000)
    })

    if (result) {
      console.log(`${LOG_PREFIX} __NUXT__ jsonLd 발견 (키: ${result.key}, 시도: ${attempt + 1})`)
      return result
    }
  }

  console.log(`${LOG_PREFIX} __NUXT__ 데이터 없음 (스크립트 주입 3회 실패)`)
  return null
}

// ==================== __NUXT__ → basicInfo 병합 ====================

function mergeNuxtData(info, nuxtData) {
  const { jsonLd, raw } = nuxtData
  if (!jsonLd) return

  // __NUXT__ raw 데이터에서 한글명 추출 시도
  // KREAM의 product-detail 데이터에 한글명이 별도 필드로 존재할 수 있음
  if (raw) {
    // product 객체에서 한글명 탐색 (wishTitle, translatedName, nameKo 등)
    const product = raw.product || raw
    const koNameCandidates = [
      product.wishTitle,
      product.translatedName,
      product.nameKo,
      product.name_ko,
      product.koreanName,
    ].filter(Boolean)
    for (const candidate of koNameCandidates) {
      if (/[가-힣]/.test(candidate)) {
        info.nameKo = candidate
        info.name = candidate
        console.log(`${LOG_PREFIX} __NUXT__ raw에서 한글명 발견: ${candidate}`)
        break
      }
    }
  }

  // 영문명 — __NUXT__의 jsonLd.name은 영문명이므로 nameEn에만 저장
  if (jsonLd.name) {
    info.nameEn = jsonLd.name
    // name이 비어있을 때만 영문명 fallback
    if (!info.name) info.name = jsonLd.name
  }

  // 브랜드
  if (jsonLd.brand?.name) info.brand = jsonLd.brand.name

  // 가격 (즉시구매가)
  if (jsonLd.offers?.price) {
    const p = parseInt(String(jsonLd.offers.price).replace(/[^0-9]/g, ''))
    if (p > 0) info.price = p
  }

  // 모델번호
  if (jsonLd.sku) info.styleCode = jsonLd.sku

  // 카테고리
  if (jsonLd.category) info.category = jsonLd.category
}

// ==================== DOM 기본 정보 추출 ====================

function extractBasicInfo() {
  // 한글명 / 영문명 분리 수집
  let nameKo = ''
  let nameEn = ''

  // 방법 1: 상품 타이틀 영역에서 직접 추출 (가장 정확)
  const titleArea = document.querySelector('[class*="title_txt"]') || document.querySelector('[class*="product_title"]')
  if (titleArea) {
    const spans = titleArea.querySelectorAll('span, p, em')
    for (const el of spans) {
      const t = el.textContent.trim()
      if (t.length < 3) continue
      // 경고/공지 문구 필터 (Method 2와 동일)
      if (/주의사항|확인하세요|브랜드 거래|거래 주의|유의사항/.test(t)) continue
      if (/배송|결제|환불|교환|반품/.test(t) && t.length > 20) continue
      if (/[가-힣]/.test(t) && !nameKo) nameKo = t
      else if (!/[가-힣]/.test(t) && !nameEn) nameEn = t
    }
  }

  // 방법 2: p.text-lookup 셀렉터 (fallback)
  if (!nameKo && !nameEn) {
    const textLookups = document.querySelectorAll('p.text-lookup, p[class*="display_paragraph"], [class*="detail_main"] p')
    for (const el of textLookups) {
      const t = el.textContent.trim()
      if (t.length < 3 || t.length > 80) continue
      if (/^\d/.test(t)) continue
      if (/\d+명/.test(t)) continue
      if (/^(상품|리뷰|사이즈|상세|추천|발매가|관심)/.test(t)) continue
      if (/^(구매|판매|즉시|입찰|체결)/.test(t)) continue
      if (/있어요$|있습니다$/.test(t)) continue
      // 공지/경고 문구 필터
      if (/주의사항|확인하세요|브랜드 거래|거래 주의|유의사항/.test(t)) continue
      if (/배송|결제|환불|교환|반품/.test(t) && t.length > 20) continue
      if (/[가-힣]/.test(t) && !nameKo) nameKo = t
      else if (!/[가-힣]/.test(t) && !nameEn) nameEn = t
    }
  }

  // 방법 3: 상세영역 내 한글명 탐색 (KREAM 레이아웃 변경 대응)
  if (!nameKo) {
    const detailSelectors = [
      '[class*="detail_main"] [class*="title"]',
      '[class*="product_info"] [class*="title"]',
      '[class*="main_title"]',
      'h1',
    ]
    for (const sel of detailSelectors) {
      const el = document.querySelector(sel)
      if (!el) continue
      const t = el.textContent.trim()
      if (t.length < 3 || t.length > 80) continue
      if (/주의사항|확인하세요|브랜드 거래|거래 주의|유의사항/.test(t)) continue
      if (/[가-힣]/.test(t)) { nameKo = t; break }
    }
  }

  // 방법 4: og:title 메타태그 (최종 fallback)
  if (!nameKo && !nameEn) {
    const ogTitle = document.querySelector('meta[property="og:title"]')?.content || ''
    if (ogTitle && ogTitle.length > 3) {
      if (/[가-힣]/.test(ogTitle)) nameKo = ogTitle.replace(/\s*\|.*$/, '').trim()
      else nameEn = ogTitle.replace(/\s*\|.*$/, '').trim()
    }
  }

  // 방법 5: <title> 태그에서 한글명 추출
  if (!nameKo) {
    const title = document.title || ''
    // KREAM 타이틀 형식: "상품명 | KREAM"
    const cleaned = title.replace(/\s*\|.*$/, '').replace(/\s*-\s*KREAM.*$/, '').trim()
    if (cleaned.length > 3 && /[가-힣]/.test(cleaned)) {
      nameKo = cleaned
    }
  }

  let name = nameKo || nameEn || ''

  // 브랜드
  const brandSelectors = [
    '[class*="brand"] a',
    '[class*="brand"]',
    '[class*="product_info"] [class*="brand"]'
  ]
  let brand = ''
  for (const sel of brandSelectors) {
    const el = document.querySelector(sel)
    if (el?.textContent?.trim()) { brand = el.textContent.trim(); break }
  }

  // 가격
  const priceSelectors = [
    '[class*="detail_price"] [class*="amount"]',
    '[class*="price"] [class*="num"]',
    '[class*="price"]',
    '[class*="amount"]'
  ]
  let price = 0
  for (const sel of priceSelectors) {
    const el = document.querySelector(sel)
    if (el) {
      const num = parseInt(el.textContent.replace(/[^0-9]/g, ''))
      if (num > 0) { price = num; break }
    }
  }

  // 카테고리 (breadcrumb)
  let category = ''
  const breadcrumb = document.querySelector('[class*="breadcrumb"], nav[aria-label]')
  if (breadcrumb) {
    category = breadcrumb.textContent.replace(/[>\s]+/g, ' > ').trim()
  }
  if (!category) category = '패션잡화 > 신발 > 스니커즈'

  return { name, nameKo, nameEn, brand, price, category, images: [], options: [], styleCode: '' }
}

// ==================== 이미지 추출 ====================

function extractImages(nuxtData) {
  const images = []

  // 1순위: jsonLd.image 배열
  if (nuxtData?.jsonLd?.image) {
    const jsonImages = Array.isArray(nuxtData.jsonLd.image)
      ? nuxtData.jsonLd.image
      : [nuxtData.jsonLd.image]
    images.push(...jsonImages.filter(Boolean))
  }

  // 2순위: swiper 메인 캐러셀 이미지
  if (images.length < 3) {
    const swiperImgs = Array.from(
      document.querySelectorAll('.swiper-slide img.base-image__image, .swiper-slide img.full_width')
    ).map(img => img.src || img.dataset?.src || '').filter(Boolean)
    images.push(...swiperImgs)
  }

  // 3순위: kream-phinf CDN 이미지 전체 탐색
  if (images.length < 3) {
    const cdnImgs = Array.from(document.querySelectorAll('img'))
      .map(img => img.src || img.dataset?.src || '')
      .filter(src =>
        src.includes('kream-phinf')
        || (src.includes('kream') && /\.(png|jpg|jpeg|webp)/i.test(src))
      )
    images.push(...cdnImgs)
  }

  // 중복 제거 + 쿼리파라미터 제거 + 최대 10개 (string이 아닌 값 방어 처리)
  return [...new Set(images.map(src => {
    if (typeof src === 'string') return src.split('?')[0]
    if (src?.url) return String(src.url).split('?')[0]
    if (src?.contentUrl) return String(src.contentUrl).split('?')[0]
    return ''
  }).filter(Boolean))].slice(0, 10)
}

// ==================== 배송 기본 정보 추출 ====================

function extractDeliveryInfo() {
  const info = { fastShippingFee: 0, normalShippingFee: 0 }

  // 배송비 정보를 담고 있는 텍스트 탐색
  const allTexts = Array.from(document.querySelectorAll('*'))
    .filter(el => el.children.length === 0)
    .map(el => el.textContent.trim())
    .filter(t => t.includes('배송') && t.includes('원'))

  for (const text of allTexts) {
    const fastMatch = text.match(/빠른배송.*?(\d{1,3}(?:,\d{3})*)원/)
    if (fastMatch) info.fastShippingFee = parseInt(fastMatch[1].replace(/,/g, ''))
    const normalMatch = text.match(/일반배송.*?(\d{1,3}(?:,\d{3})*)원/)
    if (normalMatch) info.normalShippingFee = parseInt(normalMatch[1].replace(/,/g, ''))
  }

  return info
}

// ==================== 유틸 ====================

function wait(ms) {
  return new Promise(r => setTimeout(r, ms))
}

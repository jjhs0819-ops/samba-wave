/**
 * 무신사 실제 수집 프록시 서버
 * 실행: node proxy-server.mjs
 * 포트: 3001
 *
 * 방식: 무신사 내부 JSON API 직접 호출 (HTML 파싱 X)
 * - 상품 상세: goods-detail.musinsa.com/api2/goods/{goodsNo}
 * - 옵션 데이터: goods-detail.musinsa.com/api2/goods/{goodsNo}/options
 * - 상품고시정보: goods-detail.musinsa.com/api2/goods/{goodsNo}/essential
 * - 검색: api.musinsa.com/api2/dp/v1/plp/goods
 */

import express from 'express'
import cors from 'cors'
import { createServer } from 'http'
import crypto from 'crypto'
import { execSync } from 'child_process'
import { readFileSync, writeFileSync, copyFileSync, existsSync, unlinkSync, readdirSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { fileURLToPath } from 'url'
import { dirname } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

const app = express()
const PORT = 3001

// 무신사 API 공통 헤더
const API_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'application/json',
  'Accept-Language': 'ko-KR,ko;q=0.9',
  'Referer': 'https://www.musinsa.com/',
  'Origin': 'https://www.musinsa.com',
}

app.use(cors())
app.use(express.json())

// ─────────────────────────────────────────────
// 무신사 인증 쿠키 관리 (로그인 기반 최대혜택가용)
// ─────────────────────────────────────────────
let musinsaCookie = ''

// 쿠키 캐시 파일 (서버 재시작 후에도 로그인 유지)
const COOKIE_CACHE_FILE = join(__dirname, '.musinsa-cookie.json')

function saveCookieCache(cookieStr) {
  try {
    writeFileSync(COOKIE_CACHE_FILE, JSON.stringify({ cookie: cookieStr, savedAt: new Date().toISOString() }))
  } catch (e) {
    console.log('[쿠키저장] 실패:', e.message)
  }
}

// 서버 시작 시 저장된 쿠키 복원
if (existsSync(COOKIE_CACHE_FILE)) {
  try {
    const cached = JSON.parse(readFileSync(COOKIE_CACHE_FILE, 'utf8'))
    if (cached.cookie) {
      musinsaCookie = cached.cookie
      console.log(`[쿠키복원] 저장된 로그인 쿠키 복원 완료 (저장일: ${cached.savedAt?.slice(0, 10) || '-'})`)
    }
  } catch (e) {
    console.log('[쿠키복원] 실패 (무시):', e.message)
  }
}

// 인증 헤더 생성 (쿠키가 있으면 포함)
const getHeaders = (extra = {}) => {
  const h = { ...API_HEADERS, ...extra }
  if (musinsaCookie) h['Cookie'] = musinsaCookie
  return h
}

// ─────────────────────────────────────────────
// 유틸: 로그인 헬퍼
// ─────────────────────────────────────────────

// AES-128-CBC 암호화 (무신사 로그인 폼 암호화 대응)
function aesEncrypt(text, key) {
  const keyBuf = Buffer.alloc(16)
  Buffer.from(key, 'utf8').copy(keyBuf)
  const iv = Buffer.alloc(16, 0)
  const cipher = crypto.createCipheriv('aes-128-cbc', keyBuf, iv)
  return cipher.update(text, 'utf8', 'base64') + cipher.final('base64')
}

// 응답 헤더에서 Set-Cookie 배열 추출
function getSetCookies(headers) {
  try {
    if (typeof headers.getSetCookie === 'function') return headers.getSetCookie()
  } catch {}
  const raw = headers.get('set-cookie')
  return raw ? raw.split(/,(?=[^ ,][^=,]*=)/) : []
}

// Set-Cookie 배열 → 쿠키 맵으로 파싱
function parseCookies(setCookieArr) {
  const map = {}
  for (const line of setCookieArr) {
    const [nameVal] = line.split(';')
    const eqIdx = nameVal.indexOf('=')
    if (eqIdx < 0) continue
    const name = nameVal.slice(0, eqIdx).trim()
    const val = nameVal.slice(eqIdx + 1).trim()
    if (name) map[name] = val
  }
  return map
}

// 쿠키 맵 → 쿠키 문자열
function cookieMapToStr(map) {
  return Object.entries(map).map(([k, v]) => `${k}=${v}`).join('; ')
}

// ─────────────────────────────────────────────
// 유틸: 이미지 URL 보정
// ─────────────────────────────────────────────
const toImageUrl = (path) => {
  if (!path) return ''
  if (path.startsWith('http')) return path
  if (path.startsWith('//')) return `https:${path}`
  return `https://image.msscdn.net${path}`
}

// ─────────────────────────────────────────────
// 유틸: 무신사 JSON API로 상품 상세 + 옵션 수집
// ─────────────────────────────────────────────
async function fetchMusinsaProduct(goodsNo) {
  // 1) 상품 상세 API
  const detailRes = await fetch(
    `https://goods-detail.musinsa.com/api2/goods/${goodsNo}`,
    { headers: getHeaders() }
  )
  if (!detailRes.ok) throw new Error(`상품 API ${detailRes.status}`)
  const detailJson = await detailRes.json()
  if (detailJson.meta?.result !== 'SUCCESS' || !detailJson.data) {
    throw new Error('상품 데이터 없음')
  }

  const d = detailJson.data
  const gp = d.goodsPrice || {}
  const cat = d.category || {}

  // 2) 옵션 API (별도 호출)
  let options = []
  let optionValueNoMap = {} // optionValueNo → optionItem.no 매핑
  try {
    const optRes = await fetch(
      `https://goods-detail.musinsa.com/api2/goods/${goodsNo}/options`,
      { headers: getHeaders() }
    )
    if (optRes.ok) {
      const optJson = await optRes.json()
      if (optJson.meta?.result === 'SUCCESS' && optJson.data) {
        const items = optJson.data.optionItems || []
        // optionValueNo 목록 수집 (재고 API 호출용)
        const allOptionValueNos = []
        for (const item of items) {
          for (const v of (item.optionValues || [])) {
            if (v.no) {
              allOptionValueNos.push(v.no)
              optionValueNoMap[v.no] = item.no
            }
          }
        }

        // 2-1) 재고 API 호출 (옵션별 remainQuantity + outOfStock)
        let inventoryMap = {} // optionItemNo → { remainQuantity, outOfStock }
        if (allOptionValueNos.length > 0) {
          try {
            const invRes = await fetch(
              `https://goods-detail.musinsa.com/api2/goods/${goodsNo}/options/v2/prioritized-inventories`,
              {
                method: 'POST',
                headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
                body: JSON.stringify({ optionValueNos: allOptionValueNos }),
              }
            )
            if (invRes.ok) {
              const invJson = await invRes.json()
              if (invJson.meta?.result === 'SUCCESS' && Array.isArray(invJson.data)) {
                for (const inv of invJson.data) {
                  // productVariantId === optionItem.no 로 직접 매핑
                  const optItemNo = inv.productVariantId
                  if (optItemNo) {
                    inventoryMap[optItemNo] = {
                      remainQuantity: inv.remainQuantity,
                      outOfStock: inv.outOfStock || false,
                      isRedirect: inv.isRedirect || false,
                      deliveryType: inv.domesticDelivery?.deliveryType || '',
                    }
                  }
                }
                console.log(`[재고] ${goodsNo} ${Object.keys(inventoryMap).length}개 옵션 재고 확인`)
              }
            }
          } catch (invErr) {
            console.log(`[재고] ${goodsNo} 재고 API 실패 (무시): ${invErr.message}`)
          }
        }

        options = items
          .filter(item => item.activated && !item.isDeleted)
          .map(item => {
            const vals = (item.optionValues || []).map(v => v.name).filter(Boolean)
            const inv = inventoryMap[item.no]
            // 재고 해석: remainQuantity=null이면 충분(999), 숫자면 해당 수량, outOfStock이면 0
            let stock = null
            let isSoldOut = false
            let isBrandDelivery = false
            if (inv) {
              isBrandDelivery = inv.isRedirect === true
              if (inv.outOfStock && !isBrandDelivery) {
                // 진짜 품절 (무신사 재고 없음 + 브랜드 배송도 아님)
                stock = 0
                isSoldOut = true
              } else if (isBrandDelivery) {
                // 브랜드 배송: 무신사 재고는 없지만 브랜드에서 발송 가능
                stock = null
                isSoldOut = false
              } else if (inv.remainQuantity !== null && inv.remainQuantity !== undefined) {
                stock = inv.remainQuantity
              } else {
                stock = 999 // 충분한 재고 (수량 미공개)
              }
            }
            return {
              no: item.no,
              name: vals.join(' / ') || item.managedCode || '',
              price: (gp.immediateDiscountedPrice || gp.salePrice || 0) + (item.price || 0),  // 쿠폰적용가 기준 옵션 가격
              stock,
              isSoldOut,
              isBrandDelivery,
              deliveryType: inv?.deliveryType || '',
              managedCode: item.managedCode || '',
            }
          })
      }
    }
  } catch (e) {
    console.log(`[옵션] ${goodsNo} 옵션 수집 실패: ${e.message}`)
  }

  // 3) 상품고시정보 API (제조사, 소재, 색상, 치수, 취급주의, 품질보증 등)
  let essential = {}
  try {
    const essRes = await fetch(
      `https://goods-detail.musinsa.com/api2/goods/${goodsNo}/essential`,
      { headers: getHeaders() }
    )
    if (essRes.ok) {
      const essJson = await essRes.json()
      if (essJson.meta?.result === 'SUCCESS' && essJson.data?.essentials) {
        for (const item of essJson.data.essentials) {
          const name = (item.name || '').trim()
          const value = (item.value || '').trim()
          if (!value) continue
          // 항목명 기반 매칭 (카테고리별로 항목이 다르므로 유연하게)
          if (name.includes('소재') || name.includes('재질')) essential.material = value
          else if (name === '색상') essential.color = value
          // 치수/사이즈: 취급 관련 단어가 없는 경우만 매칭
          else if ((name.includes('치수') || name.includes('사이즈')) && !name.includes('취급') && !name.includes('주의')) essential.size = value
          else if (name.includes('제조사') || name.includes('제조자')) essential.manufacturer = value
          else if (name.includes('제조국') || name.includes('원산지')) essential.origin = value
          // 취급주의/세탁방법: 치수/사이즈 단어가 없는 경우만 매칭
          else if ((name.includes('세탁') || name.includes('취급') || name.includes('주의사항')) && !name.includes('치수') && !name.includes('사이즈')) essential.careInstructions = value
          else if (name.includes('품질보증')) essential.qualityGuarantee = value
        }
        console.log(`[고시] ${goodsNo} 제조사=${essential.manufacturer || '-'} 제조국=${essential.origin || '-'}`)
      }
    }
  } catch (e) {
    console.log(`[고시] ${goodsNo} 고시정보 수집 실패: ${e.message}`)
  }

  // 카테고리
  const categoryLevels = [
    cat.categoryDepth1Name, cat.categoryDepth2Name,
    cat.categoryDepth3Name, cat.categoryDepth4Name
  ].filter(Boolean)

  // 상세페이지 이미지 추출
  const descHtml = d.goodsContents || ''
  const detailImages = []
  const imgRegex = /<img[^>]+src=["']([^"']+)["']/gi
  let imgMatch
  while ((imgMatch = imgRegex.exec(descHtml)) !== null) {
    const src = toImageUrl(imgMatch[1])
    if (src && !src.includes('icon') && !src.includes('btn_')) detailImages.push(src)
  }

  // 이미지: 썸네일 + 상품이미지 최대 8장
  const allImages = [
    toImageUrl(d.thumbnailImageUrl),
    ...(d.goodsImages || []).map(img => toImageUrl(img.imageUrl || img.url || ''))
  ].filter(Boolean)
  const uniqueImages = [...new Set(allImages)].slice(0, 9)

  // 소재 정보
  const materials = d.goodsMaterial?.materials || []
  const materialStr = materials.map(m => {
    const name = m.materialName || m.name || ''
    const rate = m.rate || m.ratio || ''
    return rate ? `${name} ${rate}%` : name
  }).filter(Boolean).join(', ')

  // 시즌 정보
  const seasonYear = d.seasonYear && d.seasonYear !== '0000' ? d.seasonYear : ''
  const seasonCode = d.season && d.season !== '0' ? d.season : ''
  const season = [seasonYear, seasonCode].filter(Boolean).join(' ')

  // 4) 최대혜택가 계산
  // immediateDiscountedPrice 우선 → salePrice → normalPrice 순서로 실 판매가 결정
  // (일부 상품은 salePrice가 정가보다 높은 이상값을 반환하는 케이스 존재)
  const normalP = gp.normalPrice || 0
  const rawSale = gp.immediateDiscountedPrice || gp.salePrice || 0
  const sPrice = (rawSale > 0 && (normalP === 0 || rawSale <= normalP)) ? rawSale : (normalP || rawSale)
  // 멤버 등급 할인율 — 필드명 여러 개 시도
  const memberRate = gp.memberDiscountRate || gp.gradeDiscountRate || gp.memberGradeDiscountRate || gp.gradeRate || 0

  console.log(`[가격] ${goodsNo} immediateDiscountedPrice=${gp.immediateDiscountedPrice} salePrice=${gp.salePrice} normalPrice=${normalP} couponPrice=${gp.couponPrice} benefitSalePrice=${gp.benefitSalePrice} bestBenefitPrice=${gp.bestBenefitPrice} maxBenefitPrice=${gp.maxBenefitPrice} memberRate=${memberRate} → sPrice=${sPrice}`)
  console.log(`[gp필드] ${goodsNo}: ${Object.keys(gp).join(', ')}`)

  // API가 직접 제공하는 최대혜택가가 있으면 우선 사용 (필드명 여러 개 시도)
  const apiBestBenefit = gp.maxBenefitPrice || gp.benefitSalePrice || gp.bestBenefitPrice || 0
  // couponPrice가 0이면 발급형 쿠폰(쿠폰받기)일 수 있으므로 0은 무시
  let bestCouponDiscount = (gp.couponPrice > 0 && gp.couponPrice < sPrice) ? (sPrice - gp.couponPrice) : 0
  // API 직접 제공 혜택가가 있으면 더 큰 할인 적용
  if (apiBestBenefit > 0 && apiBestBenefit < sPrice) {
    const apiDiscount = sPrice - apiBestBenefit
    if (apiDiscount > bestCouponDiscount) {
      bestCouponDiscount = apiDiscount
      console.log(`[가격] ${goodsNo} API 제공 혜택가 적용: ${apiBestBenefit} (할인: -${apiDiscount})`)
    }
  }

  // 5) 쿠폰 API 호출 — 비로그인도 공개 쿠폰 반환하므로 항상 시도
  try {
    const couponUrl = `https://api.musinsa.com/api2/coupon/coupons/getUsableCouponsByGoodsNo?goodsNo=${goodsNo}&brand=${d.brand || ''}&comId=${d.comId || ''}&salePrice=${sPrice}`
    const couponRes = await fetch(couponUrl, { headers: getHeaders() })
    if (couponRes.ok) {
      const couponJson = await couponRes.json()
      const coupons = couponJson.data?.list || couponJson.data || []
      console.log(`[쿠폰] ${goodsNo} 쿠폰목록: ${Array.isArray(coupons) ? coupons.length : 0}개, 샘플: ${JSON.stringify(coupons[0] || {}).slice(0, 200)}`)
      if (Array.isArray(coupons)) {
        for (const c of coupons) {
          let actualDiscount = 0
          if (c.salePrice > 0 && c.salePrice < sPrice) {
            actualDiscount = sPrice - c.salePrice
          } else if (c.discountPrice > 0) {
            actualDiscount = c.discountPrice
          }
          if (actualDiscount > bestCouponDiscount) bestCouponDiscount = actualDiscount
        }
      }
      if (bestCouponDiscount > 0) {
        console.log(`[쿠폰] ${goodsNo} ${musinsaCookie ? '로그인' : '비로그인'} 최대쿠폰할인: -${bestCouponDiscount}원 → 혜택가: ${sPrice - bestCouponDiscount}`)
      } else {
        console.log(`[쿠폰] ${goodsNo} 사용 가능한 쿠폰 없음`)
      }
    } else {
      console.log(`[쿠폰] ${goodsNo} API 오류: ${couponRes.status}`)
    }
  } catch (e) {
    console.log(`[쿠폰] ${goodsNo} API 호출 실패: ${e.message}`)
  }

  // 5-2) 무신사 benefit API — 로그인 시 등급할인+적립금 포함 최대혜택가 조회 시도
  // benefit API가 반환하는 값은 이미 등급할인+적립금이 모두 포함된 최종 최대혜택가이므로
  // 이 값이 있으면 추가 할인 계산(I) 없이 직접 사용 (이중할인 방지)
  let directBenefitPrice = 0
  if (musinsaCookie) {
    try {
      const benefitRes = await fetch(
        `https://goods-detail.musinsa.com/api2/goods/${goodsNo}/benefit`,
        { headers: getHeaders() }
      )
      if (benefitRes.ok) {
        const bJson = await benefitRes.json()
        const bd = bJson.data || {}
        const bPrice = bd.maxBenefitPrice || bd.benefitSalePrice || bd.maxBenefitSalePrice || 0
        console.log(`[benefit] ${goodsNo}: ${JSON.stringify(bd).slice(0, 200)}`)
        if (bPrice > 0 && bPrice < sPrice) {
          directBenefitPrice = bPrice  // 최종 최대혜택가 직접 사용
          const bDiscount = sPrice - bPrice
          if (bDiscount > bestCouponDiscount) bestCouponDiscount = bDiscount
          console.log(`[benefit] ${goodsNo} benefit API 최대혜택가: ${bPrice.toLocaleString()} (할인: -${bDiscount.toLocaleString()})`)
        }
      }
    } catch (e) {
      console.log(`[benefit] ${goodsNo} benefit API 실패 (무시): ${e.message}`)
    }
  }

  const T = Math.floor(bestCouponDiscount / 10) * 10
  const I = memberRate > 0 ? Math.floor((sPrice - T) * (memberRate / 100) / 10) * 10 : 0
  // benefit API 직접 제공 값 우선 사용 → 중복할인 방지
  const bestBenefitPrice = directBenefitPrice > 0 ? directBenefitPrice : (sPrice - T - I)

  console.log(`[상품] ${goodsNo} ${d.goodsNm} | 옵션 ${options.length}개 | 혜택가 ${bestBenefitPrice.toLocaleString()} | ${musinsaCookie ? '로그인' : '비로그인'}`)

  return {
    id: `col_musinsa_${goodsNo}_${Date.now()}`,
    sourceSite: 'MUSINSA',
    siteProductId: String(d.goodsNo || goodsNo),
    sourceUrl: `https://www.musinsa.com/products/${goodsNo}`,
    searchFilterId: null,
    name: d.goodsNm || '',
    nameEn: d.goodsNmEng || '',
    nameJa: '',
    brand: d.brandInfo?.brandName || d.brand || '',
    brandCode: d.brand || '',
    category: categoryLevels.join(' > '),
    category1: cat.categoryDepth1Name || '',
    category2: cat.categoryDepth2Name || '',
    category3: cat.categoryDepth3Name || '',
    category4: cat.categoryDepth4Name || '',
    categoryCode: cat.categoryDepth4Code || cat.categoryDepth3Code || cat.categoryDepth2Code || cat.categoryDepth1Code || '',
    images: uniqueImages,
    detailImages,
    detailHtml: descHtml,
    options,
    originalPrice: gp.normalPrice || rawSale || 0,
    salePrice: sPrice,
    couponPrice: (gp.couponPrice > 0 && gp.couponPrice < sPrice) ? gp.couponPrice : sPrice,
    bestBenefitPrice: bestBenefitPrice,
    memberDiscountRate: memberRate,
    isLoggedIn: !!musinsaCookie,
    discountRate: gp.discountRate || 0,
    origin: essential.origin || '',
    material: essential.material || materialStr,
    manufacturer: essential.manufacturer || '',
    color: essential.color || '',
    sizeInfo: essential.size || '',
    careInstructions: essential.careInstructions || '',
    qualityGuarantee: essential.qualityGuarantee || '',
    brandNation: d.brandInfo?.brandNationName || '',
    season,
    styleCode: d.styleNo || '',
    kcCert: '',
    tags: [],
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
    isOutOfStock: d.isOutOfStock || false,
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
    const product = await fetchMusinsaProduct(goodsNo)
    return res.json({ success: true, data: product })
  } catch (err) {
    console.log(`[상품] ${goodsNo} 수집 실패: ${err.message}`)
    return res.status(500).json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// API: 무신사 검색 API
// GET /api/musinsa/search-api?keyword=아디다스+운동화&page=1&size=30
// ─────────────────────────────────────────────
app.get('/api/musinsa/search-api', async (req, res) => {
  const keyword = req.query.keyword || ''
  const page = parseInt(req.query.page) || 1
  const size = Math.min(parseInt(req.query.size) || 30, 200)
  const sort = req.query.sort || 'POPULAR'
  const category = req.query.category || ''

  if (!keyword) {
    return res.status(400).json({ success: false, message: '검색 키워드를 입력해주세요.' })
  }

  try {
    const params = new URLSearchParams({
      caller: 'SEARCH',
      keyword,
      page: String(page),
      size: String(size),
      sort,
      gf: 'A',
    })
    if (category) params.set('category', category)

    const apiUrl = `https://api.musinsa.com/api2/dp/v1/plp/goods?${params}`
    console.log(`[검색] keyword="${keyword}" page=${page} size=${size}`)

    const response = await fetch(apiUrl, { headers: getHeaders() })
    if (!response.ok) {
      return res.status(response.status).json({ success: false, message: `무신사 API 오류: ${response.status}` })
    }

    const apiData = await response.json()
    if (apiData.meta?.result !== 'SUCCESS') {
      return res.status(500).json({ success: false, message: '무신사 API 결과 실패' })
    }

    const list = apiData.data?.list || []
    const pagination = apiData.data?.pagination || {}
    console.log(`[검색] ${list.length}개 반환 (총 ${pagination.totalCount}개)`)

    // 검색 결과를 기본 포맷으로 변환 (상세는 enrichment에서 처리)
    const products = list.map(item => ({
      id: `col_musinsa_${item.goodsNo}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      sourceSite: 'MUSINSA',
      siteProductId: String(item.goodsNo),
      sourceUrl: item.goodsLinkUrl || `https://www.musinsa.com/products/${item.goodsNo}`,
      searchFilterId: null,
      name: item.goodsName || '',
      nameEn: '',
      nameJa: '',
      brand: item.brandName || item.brand || '',
      brandCode: item.brand || '',
      category: '',
      images: [item.thumbnail].filter(Boolean),
      detailImages: [],
      detailHtml: '',
      options: [],
      originalPrice: item.normalPrice || item.price || 0,
      salePrice: item.price || item.normalPrice || 0,
      discountRate: item.saleRate || 0,
      origin: '',
      material: '',
      manufacturer: '',
      season: '',
      styleCode: '',
      kcCert: '',
      tags: [],
      status: 'collected',
      isSoldOut: item.isSoldOut || false,
      appliedPolicyId: null,
      marketPrices: {},
      updateEnabled: true,
      priceUpdateEnabled: true,
      stockUpdateEnabled: true,
      marketTransmitEnabled: true,
      registeredAccounts: [],
      collectedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }))

    return res.json({
      success: true,
      count: products.length,
      totalCount: pagination.totalCount || 0,
      totalPages: pagination.totalPages || 0,
      page: pagination.page || page,
      data: products,
    })
  } catch (err) {
    console.error('[검색] 예외:', err.message)
    return res.status(500).json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// API: URL 기반 검색/리다이렉트 처리
// GET /api/musinsa/search?url=https://...
// ─────────────────────────────────────────────
app.get('/api/musinsa/search', async (req, res) => {
  const { url } = req.query
  if (!url || !(url.includes('musinsa.com') || url.includes('musinsa.onelink.me'))) {
    return res.status(400).json({ success: false, message: '무신사 URL을 입력해주세요.' })
  }

  try {
    if (url.includes('musinsa.onelink.me')) {
      const response = await fetch(url, {
        headers: { 'User-Agent': API_HEADERS['User-Agent'] },
        redirect: 'follow'
      })
      const finalUrl = response.url
      const goodsNoMatch = finalUrl.match(/\/(?:app\/)?(?:goods|products)\/(\d{4,8})/)
      if (goodsNoMatch) {
        return res.json({ success: true, count: 1, goodsNos: [goodsNoMatch[1]], source: 'redirect' })
      }
    }

    try {
      const parsedUrl = new URL(url)
      const keyword = parsedUrl.searchParams.get('keyword')
        || parsedUrl.searchParams.get('q')
        || parsedUrl.searchParams.get('query')
        || ''

      if (keyword) {
        const params = new URLSearchParams({
          caller: 'SEARCH', keyword, page: '1', size: '50', sort: 'POPULAR', gf: 'A',
        })
        const apiRes = await fetch(`https://api.musinsa.com/api2/dp/v1/plp/goods?${params}`, {
          headers: API_HEADERS
        })
        if (apiRes.ok) {
          const apiData = await apiRes.json()
          if (apiData.meta?.result === 'SUCCESS') {
            const goodsNos = (apiData.data?.list || []).map(item => String(item.goodsNo))
            return res.json({ success: true, count: goodsNos.length, goodsNos, source: 'api' })
          }
        }
      }
    } catch {}

    const goodsNoMatch = url.match(/\/(?:app\/)?(?:goods|products)\/(\d{4,8})/)
    if (goodsNoMatch) {
      return res.json({ success: true, count: 1, goodsNos: [goodsNoMatch[1]], source: 'url-pattern' })
    }

    return res.json({ success: true, count: 0, goodsNos: [], source: 'none' })
  } catch (err) {
    return res.status(500).json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// 브라우저 쿠키 자동 읽기 (Chrome + Naver Whale 지원)
// ─────────────────────────────────────────────
const LOCAL_APP_DATA = process.env.LOCALAPPDATA
  || join(process.env.USERPROFILE || '', 'AppData', 'Local')

// 브라우저별 UserData 루트 경로
const BROWSER_ROOTS = [
  { name: '웨일(Whale)', userDataDir: join(LOCAL_APP_DATA, 'Naver', 'Naver Whale', 'User Data') },
  { name: '크롬(Chrome)', userDataDir: join(LOCAL_APP_DATA, 'Google', 'Chrome', 'User Data') },
]

// 지원 브라우저 프로필 목록 동적 생성 (Default + Profile 1~N 모두 포함)
const BROWSER_PROFILES = (() => {
  const profiles = []
  for (const browser of BROWSER_ROOTS) {
    if (!existsSync(browser.userDataDir)) continue
    const localState = join(browser.userDataDir, 'Local State')
    if (!existsSync(localState)) continue

    let items
    try { items = readdirSync(browser.userDataDir) } catch { continue }
    const profileDirs = items.filter(d => d === 'Default' || /^Profile \d+$/.test(d))

    for (const dir of profileDirs) {
      profiles.push({
        name: `${browser.name} [${dir}]`,
        cookiePaths: [
          join(browser.userDataDir, dir, 'Network', 'Cookies'),
          join(browser.userDataDir, dir, 'Cookies'),
        ],
        localState,
      })
    }
  }
  return profiles
})()

// Chromium 계열 DPAPI 복호화로 AES 키 추출
async function getAesKey(localStatePath) {
  const localState = JSON.parse(readFileSync(localStatePath, 'utf-8'))
  const encKeyB64 = localState.os_crypt?.encrypted_key
  if (!encKeyB64) throw new Error('암호화 키 없음')

  const encKey = Buffer.from(encKeyB64, 'base64').slice(5)
  const b64 = encKey.toString('base64')

  const psCmd = `Add-Type -AssemblyName System.Security; ` +
    `$b=[System.Convert]::FromBase64String('${b64}'); ` +
    `$d=[System.Security.Cryptography.ProtectedData]::Unprotect($b,$null,'CurrentUser'); ` +
    `[System.Convert]::ToBase64String($d)`

  const result = execSync(`powershell -NoProfile -Command "${psCmd}"`, {
    encoding: 'utf-8', timeout: 10000
  }).trim()
  return Buffer.from(result, 'base64')
}

// 하위 호환용 alias
async function getChromeAesKey() { return getAesKey(BROWSER_PROFILES[1].localState) }

// Chrome 쿠키 값 AES-256-GCM 복호화
function decryptChromeValue(encryptedValue, aesKey) {
  try {
    const buf = Buffer.isBuffer(encryptedValue) ? encryptedValue : Buffer.from(encryptedValue)
    const prefix = buf.slice(0, 3).toString()
    if (prefix === 'v10' || prefix === 'v20') {
      const nonce = buf.slice(3, 15)
      const tag = buf.slice(buf.length - 16)
      const ciphertext = buf.slice(15, buf.length - 16)
      const decipher = crypto.createDecipheriv('aes-256-gcm', aesKey, nonce)
      decipher.setAuthTag(tag)
      return decipher.update(ciphertext) + decipher.final('utf-8')
    }
    return buf.toString('utf-8')
  } catch {
    return ''
  }
}

// 브라우저(웨일/크롬)에서 무신사 쿠키 읽기 (로그인된 브라우저 자동 탐지)
async function readChromeMusinsaCookies() {
  // 각 브라우저 프로필을 순서대로 시도
  for (const profile of BROWSER_PROFILES) {
    const cookiePath = profile.cookiePaths.find(p => existsSync(p))
    if (!cookiePath) continue
    if (!existsSync(profile.localState)) continue

    const tmpPath = join(tmpdir(), `mc_${Date.now()}.db`)
    const tmpWal = tmpPath + '-wal'
    try {
      copyFileSync(cookiePath, tmpPath)
      const walPath = cookiePath + '-wal'
      if (existsSync(walPath)) copyFileSync(walPath, tmpWal)

      const { default: initSqlJs } = await import('sql.js')
      const SQL = await initSqlJs({
        locateFile: () => join(__dirname, 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm')
      })
      const db = new SQL.Database(readFileSync(tmpPath))
      const [results] = db.exec(
        `SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%.musinsa.com' ORDER BY name`
      )
      db.close()

      if (!results?.values?.length) {
        console.log(`[쿠키] ${profile.name}: 무신사 쿠키 없음 (로그인 필요)`)
        continue  // 다음 브라우저 시도
      }

      const aesKey = await getAesKey(profile.localState)
      const cookieMap = {}
      for (const [name, encVal] of results.values) {
        const value = decryptChromeValue(encVal, aesKey)
        // HTTP 헤더에 사용 불가한 비ASCII 문자 포함 쿠키 제외
        if (value && name && /^[\x20-\x7E]*$/.test(value)) cookieMap[name] = value
      }

      const cookieStr = Object.entries(cookieMap).map(([k, v]) => `${k}=${v}`).join('; ')
      console.log(`[쿠키] ${profile.name}에서 무신사 쿠키 ${Object.keys(cookieMap).length}개 읽음`)
      return cookieStr
    } finally {
      try { unlinkSync(tmpPath) } catch {}
      try { unlinkSync(tmpWal) } catch {}
    }
  }
  throw new Error('웨일/크롬 브라우저에서 무신사에 로그인해주세요')
}

// ─────────────────────────────────────────────
// API: Chrome 쿠키 자동 로그인
// GET /api/musinsa/chrome-login
// ─────────────────────────────────────────────
app.get('/api/musinsa/chrome-login', async (req, res) => {
  try {
    const cookieStr = await readChromeMusinsaCookies()

    // 회원정보 API로 검증
    const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
      headers: { ...API_HEADERS, 'Cookie': cookieStr }
    })
    const meJson = await meRes.json()

    if (!meJson.data?.memberId) {
      return res.json({ success: false, message: 'Chrome에서 무신사에 로그인해주세요' })
    }

    musinsaCookie = cookieStr
    saveCookieCache(cookieStr)
    console.log(`[Chrome로그인] ${meJson.data.memberId} (${meJson.data.gradeName || '-'})`)

    return res.json({
      success: true,
      isLoggedIn: true,
      memberId: meJson.data.memberId,
      gradeName: meJson.data.gradeName || '',
      message: `${meJson.data.memberId} 로그인 성공 (${meJson.data.gradeName || '등급미확인'})`,
    })
  } catch (err) {
    console.log(`[Chrome로그인] 실패: ${err.message}`)
    return res.json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// API: 브라우저 확장에서 쿠키 직접 전달
// POST /api/musinsa/set-cookie  { cookie: "..." }
// ─────────────────────────────────────────────
app.post('/api/musinsa/set-cookie', async (req, res) => {
  try {
    const { cookie } = req.body
    if (!cookie) return res.json({ success: false, message: '쿠키가 없습니다' })

    // 회원정보 API로 검증
    const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
      headers: { ...API_HEADERS, 'Cookie': cookie }
    })
    const meJson = await meRes.json()

    if (!meJson.data?.memberId) {
      return res.json({ success: false, message: '유효하지 않은 쿠키입니다 (로그인 상태 아님)' })
    }

    musinsaCookie = cookie
    saveCookieCache(cookie)
    console.log(`[확장로그인] ${meJson.data.memberId} (${meJson.data.gradeName || '-'})`)

    return res.json({
      success: true,
      isLoggedIn: true,
      memberId: meJson.data.memberId,
      gradeName: meJson.data.gradeName || '',
      message: `${meJson.data.memberId} 로그인 성공 (${meJson.data.gradeName || '등급미확인'})`,
    })
  } catch (err) {
    console.log(`[확장로그인] 실패: ${err.message}`)
    return res.json({ success: false, message: err.message })
  }
})

// ─────────────────────────────────────────────
// API: 무신사 로그인 상태 확인
// POST /api/musinsa/check-login  { cookie: "..." }
// ─────────────────────────────────────────────
app.post('/api/musinsa/check-login', async (req, res) => {
  try {
    const cookieToCheck = req.body?.cookie || musinsaCookie
    if (!cookieToCheck) return res.json({ isLoggedIn: false })

    const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
      headers: { ...API_HEADERS, 'Cookie': cookieToCheck }
    })
    const meJson = await meRes.json()
    const isLoggedIn = !!meJson.data?.memberId

    return res.json({
      isLoggedIn,
      memberId: meJson.data?.memberId || '',
      gradeName: meJson.data?.gradeName || '',
    })
  } catch {
    return res.json({ isLoggedIn: false })
  }
})

// ─────────────────────────────────────────────
// API: 무신사 간편 로그인 (ID/PW → 세션쿠키 획득)
// POST /api/musinsa/login  { id, password }
// ─────────────────────────────────────────────
app.post('/api/musinsa/login', async (req, res) => {
  const { id, password } = req.body
  if (!id || !password) {
    return res.status(400).json({ success: false, code: 'MISSING_CREDENTIALS', message: '아이디와 비밀번호를 입력해주세요.' })
  }

  // 로컬 쿠키 저장소 (요청 단위)
  const jar = {}
  const getJarStr = () => cookieMapToStr(jar)
  const absorb = (headers) => Object.assign(jar, parseCookies(getSetCookies(headers)))

  try {
    // 1단계: 무신사 로그인 진입 → entryToken 획득
    const entryRes = await fetch('https://www.musinsa.com/auth/login', {
      headers: { ...API_HEADERS, 'Accept': 'text/html,application/xhtml+xml,*/*' },
      redirect: 'manual',
    })
    absorb(entryRes.headers)

    const entryLocation = entryRes.headers.get('location') || ''
    let entryToken = ''
    const etMatch = entryLocation.match(/[?&]entryToken=([^&\s]+)/)
    if (etMatch) entryToken = decodeURIComponent(etMatch[1])

    if (!entryToken && entryRes.status !== 302) {
      const entryHtml = await entryRes.text()
      const etBody = entryHtml.match(/entryToken['":\s=]+([A-Za-z0-9._-]{20,})/)
      if (etBody) entryToken = etBody[1]
    }

    if (!entryToken) {
      throw Object.assign(new Error('entryToken 획득 실패'), { code: 'ENTRY_TOKEN_FAILED' })
    }
    console.log(`[로그인] entryToken 획득 완료`)

    // 2단계: one.musinsa.com 로그인 페이지 → AES 키 + loginToken 추출
    let oneUrl = `https://member.one.musinsa.com/login?entryToken=${encodeURIComponent(entryToken)}`
    let oneHtml = ''
    for (let i = 0; i < 5; i++) {
      const oneRes = await fetch(oneUrl, {
        headers: { ...API_HEADERS, 'Accept': 'text/html,application/xhtml+xml,*/*', 'Cookie': getJarStr() },
        redirect: 'manual',
      })
      absorb(oneRes.headers)
      if (oneRes.status === 302) {
        const loc = oneRes.headers.get('location') || ''
        if (!loc) break
        oneUrl = loc.startsWith('http') ? loc : new URL(loc, oneUrl).href
      } else {
        oneHtml = await oneRes.text()
        break
      }
    }

    // AES 키 패턴 탐색
    const aesPatterns = [
      /name=["']aesKey["']\s+value=["']([^"']+)["']/,
      /"aesKey"\s*:\s*"([^"]+)"/,
      /var\s+aesKey\s*=\s*["']([^"']+)["']/,
      /aesKey\s*[=:]\s*["']([^"']{16,32})["']/,
    ]
    let aesKey = ''
    for (const pat of aesPatterns) {
      const m = oneHtml.match(pat)
      if (m) { aesKey = m[1]; break }
    }

    // loginToken 추출
    const ltMatch = oneHtml.match(/name=["']loginToken["']\s+value=["']([^"']+)["']/)
      || oneHtml.match(/"loginToken"\s*:\s*"([^"]+)"/)
    const loginToken = ltMatch ? ltMatch[1] : ''
    console.log(`[로그인] AES키=${aesKey ? '확인' : '없음'} loginToken=${loginToken ? '확인' : '없음'}`)

    // 3단계: 자격증명 암호화 + 로그인 POST
    const form = new URLSearchParams()
    form.set('userId', id)
    form.set('password', password)
    if (aesKey) {
      form.set('encUserId', aesEncrypt(id, aesKey))
      form.set('encPassword', aesEncrypt(password, aesKey))
    }
    if (loginToken) form.set('loginToken', loginToken)
    form.set('entryToken', entryToken)

    const postRes = await fetch('https://member.one.musinsa.com/login', {
      method: 'POST',
      headers: {
        ...API_HEADERS,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie': getJarStr(),
        'Origin': 'https://member.one.musinsa.com',
        'Referer': oneUrl,
      },
      body: form.toString(),
      redirect: 'manual',
    })
    absorb(postRes.headers)

    const postLocation = postRes.headers.get('location') || ''
    let postBody = ''
    if (postRes.status !== 302) {
      postBody = await postRes.text().catch(() => '')
    }

    // 실패 패턴 감지
    if (postLocation.includes('error') || postLocation.includes('fail') || postLocation.includes('invalid')
      || postBody.includes('올바르지') || postBody.includes('일치하지')) {
      return res.json({ success: false, code: 'INVALID_CREDENTIALS', message: '아이디 또는 비밀번호가 올바르지 않습니다.' })
    }
    if (postLocation.includes('captcha') || postLocation.includes('verify')
      || postBody.includes('captcha') || postBody.includes('보안문자')) {
      return res.json({ success: false, code: 'REQUIRES_VERIFICATION', message: '보안 인증이 필요합니다. 쿠키 직접 입력을 이용해주세요.' })
    }

    // 리다이렉트 체인 따라가기 (최대 4회)
    if (postRes.status === 302 && postLocation) {
      let followUrl = postLocation.startsWith('http') ? postLocation : new URL(postLocation, 'https://member.one.musinsa.com').href
      for (let i = 0; i < 4; i++) {
        const followRes = await fetch(followUrl, {
          headers: { ...API_HEADERS, 'Cookie': getJarStr() },
          redirect: 'manual',
        })
        absorb(followRes.headers)
        const nextLoc = followRes.headers.get('location') || ''
        if (!nextLoc || followRes.status !== 302) break
        followUrl = nextLoc.startsWith('http') ? nextLoc : new URL(nextLoc, followUrl).href
      }
    }

    // 4단계: 회원정보 API로 로그인 검증
    const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
      headers: { ...API_HEADERS, 'Cookie': getJarStr() },
    })
    const meJson = await meRes.json()

    if (!meJson.data?.memberId) {
      return res.json({ success: false, code: 'LOGIN_FAILED', message: '로그인에 실패했습니다. 쿠키 직접 입력을 이용해주세요.' })
    }

    // 성공: 서버 전역 쿠키에 저장
    musinsaCookie = getJarStr()
    saveCookieCache(musinsaCookie)
    console.log(`[로그인] 성공: ${meJson.data.memberId} (${meJson.data.gradeName || '등급미확인'})`)

    return res.json({
      success: true,
      isLoggedIn: true,
      memberId: meJson.data.memberId,
      gradeName: meJson.data.gradeName || '',
      message: `${meJson.data.memberId} 로그인 성공 (${meJson.data.gradeName || '등급미확인'})`,
    })

  } catch (err) {
    const code = err.code || 'LOGIN_FAILED'
    console.error(`[로그인] 오류: ${err.message}`)
    if (code === 'ENTRY_TOKEN_FAILED') {
      return res.status(503).json({ success: false, code, message: '무신사 서버 연결에 실패했습니다. 잠시 후 다시 시도해주세요.' })
    }
    return res.status(500).json({ success: false, code, message: '로그인 처리 중 오류 발생. 쿠키 직접 입력을 이용해주세요.' })
  }
})

// ─────────────────────────────────────────────
// API: 무신사 인증 쿠키 관리
// ─────────────────────────────────────────────
app.post('/api/musinsa/auth', (req, res) => {
  const { cookie } = req.body
  if (!cookie || typeof cookie !== 'string') {
    musinsaCookie = ''
    return res.json({ success: true, message: '인증 쿠키가 초기화되었습니다', isLoggedIn: false })
  }
  musinsaCookie = cookie.trim()
  console.log(`[인증] 무신사 쿠키 설정됨 (${musinsaCookie.length}자)`)
  // 쿠키 유효성 검증 (회원정보 API 호출)
  fetch('https://api.musinsa.com/api2/member/v1/me', {
    headers: getHeaders()
  }).then(r => r.json()).then(data => {
    if (data.data?.memberId) {
      console.log(`[인증] 로그인 확인: ${data.data.memberId} (등급: ${data.data.gradeName || '-'})`)
      res.json({
        success: true,
        isLoggedIn: true,
        memberId: data.data.memberId,
        gradeName: data.data.gradeName || '',
        message: `${data.data.memberId} 로그인 확인 (${data.data.gradeName || '등급미확인'})`
      })
    } else {
      musinsaCookie = ''
      res.json({ success: false, isLoggedIn: false, message: '유효하지 않은 쿠키입니다. 다시 확인해주세요.' })
    }
  }).catch(() => {
    res.json({ success: true, isLoggedIn: true, message: '쿠키가 설정되었습니다 (검증 생략)' })
  })
})

app.get('/api/musinsa/auth/status', (req, res) => {
  res.json({ isLoggedIn: !!musinsaCookie, cookieLength: musinsaCookie.length })
})

app.delete('/api/musinsa/auth', (req, res) => {
  musinsaCookie = ''
  console.log('[인증] 쿠키 초기화')
  res.json({ success: true, isLoggedIn: false, message: '로그아웃 완료' })
})

// ─────────────────────────────────────────────
// API: 상태 확인
// ─────────────────────────────────────────────
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', message: '무신사 프록시 서버 정상 작동중', port: PORT, isLoggedIn: !!musinsaCookie })
})

// ─────────────────────────────────────────────
// 서버 시작
// ─────────────────────────────────────────────
const server = createServer(app)
server.listen(PORT, () => {
  console.log(`
╔══════════════════════════════════════════════════╗
║   무신사 수집 프록시 서버 (JSON API 방식)        ║
║   포트: http://localhost:${PORT}                      ║
╠══════════════════════════════════════════════════╣
║   GET  /api/health              상태 확인        ║
║   GET  /api/musinsa/goods/:id   상품+옵션 수집   ║
║   GET  /api/musinsa/search-api  검색 API         ║
║   GET  /api/musinsa/search      URL→검색 변환    ║
║   GET  /api/musinsa/chrome-login Chrome 자동로그인║
║   POST /api/musinsa/login       ID/PW 로그인     ║
╚══════════════════════════════════════════════════╝
  `)
})

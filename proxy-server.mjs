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
import iconv from 'iconv-lite'
import { XMLParser } from 'fast-xml-parser'

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

  console.log(`[가격] ${goodsNo} salePrice=${gp.salePrice} normalPrice=${normalP} couponPrice=${gp.couponPrice} memberRate=${memberRate} → sPrice=${sPrice}`)
  console.log(`[적립] ${goodsNo} savePoint=${gp.savePoint} savePointPercent=${gp.savePointPercent} memberSavePointRate=${gp.memberSavePointRate} memberSaveMoneyRate=${gp.memberSaveMoneyRate} totalDiscount=${gp.totalDiscount} couponDiscount=${gp.couponDiscount}`)

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
          // salePrice 해석: 상품가의 50% 미만이면 "할인금액", 이상이면 "적용 후 가격"
          if (c.salePrice > 0 && c.salePrice < sPrice) {
            if (c.salePrice < sPrice * 0.5) {
              actualDiscount = c.salePrice  // 할인금액 자체
            } else {
              actualDiscount = sPrice - c.salePrice  // 적용 후 가격에서 차감
            }
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
      console.log(`[benefit] ${goodsNo} 응답상태: ${benefitRes.status}`)
      if (benefitRes.ok) {
        const bJson = await benefitRes.json()
        const bd = bJson.data || {}
        console.log(`[benefit] ${goodsNo}: ${JSON.stringify(bd).slice(0, 500)}`)

        // benefit API 응답 해석: "가격" vs "할인금액" 구분
        // salePrice의 50% 이상이면 "가격", 미만이면 "할인금액"
        const half = sPrice * 0.5
        const candidates = [
          bd.benefitSalePrice,       // 혜택 적용 후 가격 (우선)
          bd.maxBenefitSalePrice,    // 최대혜택 적용 후 가격
        ].filter(v => v > 0 && v > half && v < sPrice)

        // 할인금액 필드 (가격이 아님)
        const discountFields = [
          bd.maxBenefitPrice,        // 최대 혜택 금액 (할인+적립 합계)
          bd.totalBenefitPrice,
        ].filter(v => v > 0 && v < half)

        if (candidates.length > 0) {
          // "가격" 필드가 있으면 직접 사용
          directBenefitPrice = Math.min(...candidates)
          const bDiscount = sPrice - directBenefitPrice
          if (bDiscount > bestCouponDiscount) bestCouponDiscount = bDiscount
          console.log(`[benefit] ${goodsNo} 최대혜택가(가격): ${directBenefitPrice.toLocaleString()} (할인: -${bDiscount.toLocaleString()})`)
        } else if (discountFields.length > 0) {
          // "할인금액" 필드만 있으면 salePrice에서 차감
          const maxDiscount = Math.max(...discountFields)
          directBenefitPrice = sPrice - maxDiscount
          if (maxDiscount > bestCouponDiscount) bestCouponDiscount = maxDiscount
          console.log(`[benefit] ${goodsNo} 최대혜택가(할인금액 차감): ${directBenefitPrice.toLocaleString()} (할인: -${maxDiscount.toLocaleString()})`)
        }
      }
    } catch (e) {
      console.log(`[benefit] ${goodsNo} benefit API 실패 (무시): ${e.message}`)
    }
  }

  // 최대혜택가 계산 (쿠폰적용가 - 등급할인 - 적립금사용)
  // 쿠폰적용가
  const couponAppliedPrice = (gp.couponPrice > 0 && gp.couponPrice < sPrice) ? gp.couponPrice : sPrice

  // 등급 할인 — 실제 가격 할인, 10원 단위 절사
  const gradeDiscountRate = gp.memberDiscountRate || 0
  const gradeDiscount = Math.floor(couponAppliedPrice * gradeDiscountRate / 100 / 10) * 10
  const priceAfterGradeDiscount = couponAppliedPrice - gradeDiscount

  // 적립금 사용 (goods-detail API 필드 기반, 상품·회원별로 다름)
  // 무신사 규칙: 보유 적립금 5,000원 이상이어야 사용 가능
  const MIN_POINT_BALANCE = 5000
  let pointUsage = 0
  const isPointRestricted = d.isRestictedUsePoint === true
  const maxUsePointRate = d.maxUsePointRate || 0
  const memberPoint = d.point?.memberPoint || 0
  if (!isPointRestricted && maxUsePointRate > 0 && memberPoint >= MIN_POINT_BALANCE) {
    const maxUsable = Math.floor(priceAfterGradeDiscount * maxUsePointRate / 10) * 10
    pointUsage = Math.min(maxUsable, memberPoint)
  }

  // benefit API 값이 있으면 우선, 없으면 쿠폰가 - 등급할인 - 적립금사용
  let bestBenefitPrice
  if (directBenefitPrice > 0) {
    bestBenefitPrice = directBenefitPrice
  } else {
    bestBenefitPrice = priceAfterGradeDiscount - pointUsage
  }
  console.log(`[혜택] ${goodsNo} 쿠폰가=${couponAppliedPrice} 등급할인=${gradeDiscount}(${gradeDiscountRate}%) 적립금사용=${pointUsage}(한도:${maxUsePointRate}, 잔액:${memberPoint}, 금지:${isPointRestricted}) → 최대혜택가=${bestBenefitPrice}`)

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

// 하위 호환용 alias (프로필이 1개뿐일 경우 TypeError 방지)
async function getChromeAesKey() {
  const profile = BROWSER_PROFILES[1] || BROWSER_PROFILES[0]
  if (!profile) throw new Error('사용 가능한 브라우저 프로필이 없습니다')
  return getAesKey(profile.localState)
}

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
    const cookieNames = cookieStr.split(';').map(c => c.trim().split('=')[0])
    console.log(`[Chrome로그인] DB에서 읽은 쿠키 ${cookieNames.length}개: ${cookieNames.join(', ')}`)

    // 일단 쿠키 저장 (검증 전)
    musinsaCookie = cookieStr
    saveCookieCache(cookieStr)

    // 회원정보 API로 검증 (실패해도 저장 유지)
    try {
      const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
        headers: { ...API_HEADERS, 'Cookie': cookieStr }
      })
      const meJson = await meRes.json()

      if (meJson.data?.memberId) {
        console.log(`[Chrome로그인] 인증 확인: ${meJson.data.memberId} (${meJson.data.gradeName || '-'})`)
        return res.json({
          success: true,
          isLoggedIn: true,
          memberId: meJson.data.memberId,
          gradeName: meJson.data.gradeName || '',
          message: `${meJson.data.memberId} 로그인 성공 (${meJson.data.gradeName || '등급미확인'})`,
        })
      }
      console.log(`[Chrome로그인] 인증 API 실패 (쿠키는 저장됨), 응답: ${JSON.stringify(meJson).slice(0, 100)}`)
    } catch (verifyErr) {
      console.log(`[Chrome로그인] 인증 API 예외 (쿠키는 저장됨): ${verifyErr.message}`)
    }

    return res.json({
      success: true,
      isLoggedIn: true,
      message: `Chrome DB에서 쿠키 ${cookieNames.length}개 저장 완료 (수집 시 로그인 여부 확인됩니다)`,
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

    // 일단 쿠키 저장 (검증은 시도만 - 실패해도 저장)
    musinsaCookie = cookie
    saveCookieCache(cookie)

    // 회원정보 API로 검증 시도 (실패해도 성공으로 처리)
    try {
      const meRes = await fetch('https://api.musinsa.com/api2/member/v1/me', {
        headers: { ...API_HEADERS, 'Cookie': cookie }
      })
      const meJson = await meRes.json()

      if (meJson.data?.memberId) {
        console.log(`[확장로그인] ${meJson.data.memberId} (${meJson.data.gradeName || '-'})`)
        return res.json({
          success: true,
          isLoggedIn: true,
          memberId: meJson.data.memberId,
          gradeName: meJson.data.gradeName || '',
          message: `${meJson.data.memberId} 로그인 성공 (${meJson.data.gradeName || '등급미확인'})`,
        })
      }
    } catch (verifyErr) {
      console.log(`[확장로그인] 검증 API 실패 (쿠키는 저장됨): ${verifyErr.message}`)
    }

    // 검증 실패해도 쿠키 저장 성공으로 응답
    console.log(`[확장로그인] 쿠키 저장 완료 (검증 생략, ${cookie.length}자)`)
    return res.json({
      success: true,
      isLoggedIn: true,
      message: '쿠키가 설정되었습니다. 수집 시 로그인 여부가 확인됩니다.',
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

// ═══════════════════════════════════════════════════════════
// 롯데홈쇼핑(롯데아이몰) OpenAPI 연동
// EUC-KR 인코딩 요청 / XML 응답 처리
// ═══════════════════════════════════════════════════════════

// 롯데홈쇼핑 API 환경 설정
const LOTTE_BASE = {
  test: 'http://openapitst.lotteimall.com/openapi/',
  prod: 'https://openapi.lotteimall.com/openapi/'
}

// 인증 캐시 파일 경로
const LOTTE_AUTH_FILE = join(__dirname, '.lottehome-auth.json')

// 메모리 인증 캐시 (서버 실행 중 유지)
let lotteAuthCache = null

// 서버 시작 시 기존 인증 캐시 복원
if (existsSync(LOTTE_AUTH_FILE)) {
  try {
    lotteAuthCache = JSON.parse(readFileSync(LOTTE_AUTH_FILE, 'utf8'))
    const remaining = lotteAuthCache ? (new Date(lotteAuthCache.expiresAt) - Date.now()) / 60000 : 0
    if (remaining > 0) {
      console.log(`[롯데홈쇼핑] 인증 캐시 복원 (잔여: ${Math.floor(remaining)}분)`)
    } else {
      lotteAuthCache = null
      console.log('[롯데홈쇼핑] 캐시된 인증키 만료, 재인증 필요')
    }
  } catch (e) {
    console.log('[롯데홈쇼핑] 인증 캐시 복원 실패:', e.message)
  }
}

// XML 파서 설정
const xmlParser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: '@_',
  textNodeName: '#text',
  parseTagValue: true,
  trimValues: true
})

/**
 * 롯데홈쇼핑 API 공통 호출 (EUC-KR 인코딩)
 * @param {string} endpoint - API 엔드포인트명 (예: createCertification.lotte)
 * @param {string} method - GET | POST
 * @param {object} params - 요청 파라미터 (평문 UTF-8, 전송 시 EUC-KR 변환)
 * @param {string} env - 'test' | 'prod'
 */
async function callLotteApi(endpoint, method, params = {}, env = 'test') {
  const baseUrl = LOTTE_BASE[env] || LOTTE_BASE.test
  let url = baseUrl + endpoint

  // EUC-KR로 인코딩된 쿼리스트링 생성
  const encodeEucKr = (val) => {
    const buf = iconv.encode(String(val), 'euc-kr')
    return [...buf].map(b => '%' + b.toString(16).toUpperCase().padStart(2, '0')).join('')
  }

  const buildQuery = (obj) =>
    Object.entries(obj)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeEucKr(v)}`)
      .join('&')

  const headers = {
    'Content-Type': 'application/x-www-form-urlencoded; charset=euc-kr',
    'Accept': 'text/xml; charset=euc-kr',
    'Accept-Charset': 'euc-kr'
  }

  let response
  if (method === 'GET') {
    const qs = buildQuery(params)
    if (qs) url += '?' + qs
    response = await fetch(url, { method: 'GET', headers })
  } else {
    const body = buildQuery(params)
    response = await fetch(url, { method: 'POST', headers, body })
  }

  // EUC-KR 응답을 Buffer로 받아 UTF-8 변환
  const arrayBuf = await response.arrayBuffer()
  const rawBuf = Buffer.from(arrayBuf)
  const xmlStr = iconv.decode(rawBuf, 'euc-kr')

  // XML 파싱
  const parsed = xmlParser.parse(xmlStr)
  return parseLotteResponse(parsed, xmlStr)
}

/**
 * 롯데홈쇼핑 응답 파싱 (성공/에러 분기)
 * 실제 응답 구조: { Response: { Errors: { Error: { Code, Message } }, ... } }
 */
function parseLotteResponse(parsed, rawXml = '') {
  // 실제 루트는 대문자 Response
  const root = parsed?.Response || parsed?.response || parsed?.result || parsed

  // 에러 블록 확인 (Response.Errors.Error)
  const errorBlock = root?.Errors?.Error || root?.errors?.error
  if (errorBlock) {
    const code = errorBlock.Code ?? errorBlock.code ?? ''
    const msg = errorBlock.Message || errorBlock.message || '알 수 없는 오류'
    // 코드 0은 성공으로 간주
    if (code !== 0 && String(code) !== '0') {
      const err = new Error(`[${code}] ${msg}`)
      err.lotteCode = String(code)
      err.lotteMsg = msg
      throw err
    }
  }

  return { success: true, data: root, rawXml }
}

/**
 * 응답 객체에서 인증키 필드를 재귀 탐색
 * 롯데 API 응답 구조가 버전/환경마다 다를 수 있어 광범위하게 탐색
 */
function findCertKey(obj, depth = 0) {
  if (!obj || typeof obj !== 'object' || depth > 5) return null

  // 알려진 인증키 필드명 패턴 (대소문자 무시)
  const certKeyNames = [
    'certification_key', 'certkey', 'cert_key', 'strCertKey',
    'certificationkey', 'authkey', 'auth_key', 'token',
    'strtoken', 'sessionkey', 'session_key'
  ]

  for (const [k, v] of Object.entries(obj)) {
    const keyLower = k.toLowerCase()
    if (certKeyNames.some(name => keyLower === name.toLowerCase()) && v && typeof v !== 'object') {
      return String(v)
    }
  }

  // 재귀 탐색
  for (const v of Object.values(obj)) {
    if (v && typeof v === 'object') {
      const found = findCertKey(v, depth + 1)
      if (found) return found
    }
  }
  return null
}

/**
 * 롯데홈쇼핑 인증키 자동 관리
 * - 캐시된 인증키가 있고 30분 이상 남아있으면 재사용
 * - 만료 30분 전이거나 없으면 새로 발급
 */
async function ensureLotteAuth(userId, password, agncNo = '', env = 'test') {
  const now = Date.now()
  const REFRESH_BEFORE_MS = 30 * 60 * 1000 // 만료 30분 전 갱신

  // 캐시가 유효하면 재사용
  if (lotteAuthCache &&
      lotteAuthCache.userId === userId &&
      lotteAuthCache.env === env &&
      new Date(lotteAuthCache.expiresAt).getTime() - now > REFRESH_BEFORE_MS) {
    return lotteAuthCache
  }

  // 새 인증키 발급
  console.log('[롯데홈쇼핑] 인증키 발급 요청...')
  const params = { strUserId: userId, strPassWd: password }
  if (agncNo) params.strAgncNo = agncNo

  const result = await callLotteApi('createCertification.lotte', 'POST', params, env)
  const data = result.data

  console.log('[롯데홈쇼핑] 인증 응답:', JSON.stringify(data, null, 2))

  // 응답 객체 전체에서 인증키 재귀 탐색
  const certKey = findCertKey(data)
  if (!certKey) {
    throw new Error(`인증키를 응답에서 찾을 수 없습니다. 응답 구조: ${JSON.stringify(data)}`)
  }

  // 24시간 유효 (23시간 55분으로 설정하여 여유 확보)
  const expiresAt = new Date(now + 23 * 60 * 60 * 1000 + 55 * 60 * 1000).toISOString()

  lotteAuthCache = {
    userId, env, certKey, agncNo,
    issuedAt: new Date().toISOString(),
    expiresAt
  }

  // 파일에 저장 (서버 재시작 후 복원용)
  try {
    writeFileSync(LOTTE_AUTH_FILE, JSON.stringify(lotteAuthCache))
  } catch (e) {
    console.warn('[롯데홈쇼핑] 인증 캐시 저장 실패:', e.message)
  }

  console.log(`[롯데홈쇼핑] 인증키 발급 완료 (만료: ${expiresAt})`)
  return lotteAuthCache
}

// ─────────────────────────────────────────────
// 롯데홈쇼핑 API: 인증
// ─────────────────────────────────────────────

// POST /api/lottehome/auth - 인증키 발급
app.post('/api/lottehome/auth', async (req, res) => {
  const { userId, password, agncNo, env } = req.body
  if (!userId || !password) {
    return res.status(400).json({ success: false, message: '협력업체ID와 비밀번호를 입력해주세요.' })
  }
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo || '', env || 'test')
    const remaining = Math.floor((new Date(auth.expiresAt).getTime() - Date.now()) / 60000)
    return res.json({
      success: true,
      message: `인증 성공 (잔여: ${Math.floor(remaining / 60)}시간 ${remaining % 60}분)`,
      certKey: auth.certKey,
      expiresAt: auth.expiresAt,
      remaining
    })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode || 'AUTH_FAILED' })
  }
})

// GET /api/lottehome/auth/status - 캐시된 인증 상태 확인
app.get('/api/lottehome/auth/status', (req, res) => {
  if (!lotteAuthCache) {
    return res.json({ authenticated: false, message: '인증 정보 없음' })
  }
  const remaining = Math.floor((new Date(lotteAuthCache.expiresAt).getTime() - Date.now()) / 60000)
  if (remaining <= 0) {
    lotteAuthCache = null
    return res.json({ authenticated: false, message: '인증키 만료됨' })
  }
  return res.json({
    authenticated: true,
    userId: lotteAuthCache.userId,
    env: lotteAuthCache.env,
    expiresAt: lotteAuthCache.expiresAt,
    remaining,
    message: `인증 유효 (잔여: ${Math.floor(remaining / 60)}시간 ${remaining % 60}분)`
  })
})

// DELETE /api/lottehome/auth - 인증 캐시 초기화
app.delete('/api/lottehome/auth', (req, res) => {
  lotteAuthCache = null
  if (existsSync(LOTTE_AUTH_FILE)) {
    try { unlinkSync(LOTTE_AUTH_FILE) } catch {}
  }
  console.log('[롯데홈쇼핑] 인증 캐시 초기화')
  return res.json({ success: true, message: '인증 캐시가 초기화되었습니다.' })
})

// ─────────────────────────────────────────────
// 롯데홈쇼핑 API: 기초정보 조회
// ─────────────────────────────────────────────

// GET /api/lottehome/brands?brnd_nm=나이키&userId=...&password=...
app.get('/api/lottehome/brands', async (req, res) => {
  const { userId, password, agncNo, env, brnd_nm } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchBrandListOpenApi.lotte', 'GET', {
      strCertKey: auth.certKey,
      brnd_nm: brnd_nm || ''
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// GET /api/lottehome/categories?disp_tp_cd=&md_gsgr_no=
app.get('/api/lottehome/categories', async (req, res) => {
  const { userId, password, agncNo, env, disp_tp_cd, md_gsgr_no } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchDispCatListOpenApi.lotte', 'GET', {
      strCertKey: auth.certKey,
      disp_tp_cd: disp_tp_cd || '',
      md_gsgr_no: md_gsgr_no || ''
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// GET /api/lottehome/md-groups
app.get('/api/lottehome/md-groups', async (req, res) => {
  const { userId, password, agncNo, env } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchMdGsgrListOpenApi.lotte', 'GET', {
      strCertKey: auth.certKey
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// GET /api/lottehome/delivery-policies
app.get('/api/lottehome/delivery-policies', async (req, res) => {
  const { userId, password, agncNo, env } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchDlvPolcListOpenApi.lotte', 'GET', {
      strCertKey: auth.certKey
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// POST /api/lottehome/delivery-policies - 배송비정책 등록
app.post('/api/lottehome/delivery-policies', async (req, res) => {
  const { userId, password, agncNo, env, ...policyData } = req.body
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('registApiDlvPolcInfo.lotte', 'POST', {
      strCertKey: auth.certKey,
      ...policyData
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// GET /api/lottehome/delivery-places
app.get('/api/lottehome/delivery-places', async (req, res) => {
  const { userId, password, agncNo, env } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchDlvPlcListOpenApi.lotte', 'GET', {
      strCertKey: auth.certKey
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// ─────────────────────────────────────────────
// 롯데홈쇼핑 API: 상품 CRUD
// ─────────────────────────────────────────────

// POST /api/lottehome/goods - 신규상품등록
app.post('/api/lottehome/goods', async (req, res) => {
  const { userId, password, agncNo, env, ...goodsData } = req.body
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('registApiGoodsInfo.lotte', 'POST', {
      strCertKey: auth.certKey,
      ...goodsData
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// PUT /api/lottehome/goods/new/:goodsReqNo - 신규상품수정
app.put('/api/lottehome/goods/new/:goodsReqNo', async (req, res) => {
  const { goodsReqNo } = req.params
  const { userId, password, agncNo, env, ...goodsData } = req.body
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('upateApiNewGoodsInfo.lotte', 'POST', {
      strCertKey: auth.certKey,
      goods_req_no: goodsReqNo,
      ...goodsData
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// PUT /api/lottehome/goods/display/:goodsNo - 전시상품수정
app.put('/api/lottehome/goods/display/:goodsNo', async (req, res) => {
  const { goodsNo } = req.params
  const { userId, password, agncNo, env, ...goodsData } = req.body
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('upateApiDisplayGoodsInfo.lotte', 'POST', {
      strCertKey: auth.certKey,
      goods_no: goodsNo,
      ...goodsData
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// PATCH /api/lottehome/goods/:goodsNo/status - 판매상태 변경
app.patch('/api/lottehome/goods/:goodsNo/status', async (req, res) => {
  const { goodsNo } = req.params
  const { userId, password, agncNo, env, sale_stat_cd } = req.body
  // sale_stat_cd: 10=판매진행, 20=품절, 30=영구중단
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('updateGoodsSaleStat.lotte', 'POST', {
      strCertKey: auth.certKey,
      goods_no: goodsNo,
      sale_stat_cd: sale_stat_cd || '20'
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// ─────────────────────────────────────────────
// 롯데홈쇼핑 API: 재고
// ─────────────────────────────────────────────

// PUT /api/lottehome/stock - 재고수정
app.put('/api/lottehome/stock', async (req, res) => {
  const { userId, password, agncNo, env, goods_no, item_no, inv_qty } = req.body
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('registStock.lotte', 'POST', {
      strCertKey: auth.certKey,
      goods_no, item_no, inv_qty
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// GET /api/lottehome/stock?goods_no=
app.get('/api/lottehome/stock', async (req, res) => {
  const { userId, password, agncNo, env, goods_no } = req.query
  try {
    const auth = await ensureLotteAuth(userId, password, agncNo, env)
    const result = await callLotteApi('searchStockList.lotte', 'GET', {
      strCertKey: auth.certKey,
      goods_no: goods_no || ''
    }, env || 'test')
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.lotteCode })
  }
})

// ═══════════════════════════════════════════════════════════
// GS샵(GS리테일) 제휴 API V3 연동
// 인증: supCd(헤더) + token(AES256 암호화: Sysdate+supCd)
// 운영: https://withgs-api.gsshop.com
// 테스트: https://atwithgs-api.gsshop.com
// ═══════════════════════════════════════════════════════════

const GS_BASE = {
  prod: 'https://withgs-api.gsshop.com',
  dev:  'https://atwithgs-api.gsshop.com'
}

/**
 * GSSHOP V3 인증 토큰 생성
 * token = AES256_CBC(yyyyMMddHHmmss + supCd, aesKey)
 * 인증가이드 V3.0.1 기준:
 *   - key: UTF-8 인코딩 후 32바이트 맞춤 (ljust(32)[:32])
 *   - IV: key 앞 16글자 UTF-8 (Java: key.substring(0,16), Python: key[:16])
 *   - padding: PKCS5Padding (= Node.js aes-256-cbc 기본값)
 *   - 결과: Base64 인코딩
 * @param {string} supCd - 협력사코드
 * @param {string} aesKey - AES256 키 (UTF-8 문자열)
 */
function generateGsToken(supCd, aesKey) {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const sysdate = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
  const plainText = sysdate + supCd

  // IV = key 앞 16글자 UTF-8 (인증가이드: key.substring(0,16))
  const iv = Buffer.from(aesKey.substring(0, 16), 'utf8')
  // key = UTF-8 인코딩 후 32바이트로 맞춤 (부족하면 0패딩, 초과하면 자름)
  const keyBytes = Buffer.from(aesKey, 'utf8')
  const keyBuf = Buffer.alloc(32)
  keyBytes.copy(keyBuf, 0, 0, Math.min(keyBytes.length, 32))

  const cipher = crypto.createCipheriv('aes-256-cbc', keyBuf, iv)
  const encrypted = Buffer.concat([cipher.update(plainText, 'utf8'), cipher.final()])
  return encrypted.toString('base64')
}

/**
 * GS샵 V3 API 공통 호출
 * @param {string} path - API 경로 (예: /api/v3/products)
 * @param {string} method - GET | POST | PUT
 * @param {object|null} body - 요청 바디 (POST/PUT)
 * @param {object} params - 쿼리 파라미터
 * @param {string} supCd - 협력사코드
 * @param {string} token - 생성된 AES256 토큰
 */
async function callGsApi(path, method, body = null, params = {}, supCd = '', token = '', env = 'dev') {
  const base = GS_BASE[env] || GS_BASE.dev
  const qs = new URLSearchParams(params).toString()
  const url = base + path + (qs ? '?' + qs : '')

  const options = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'supCd': supCd,
      'token': token
    }
  }
  if (body && method !== 'GET') {
    options.body = JSON.stringify(body)
  }

  console.log(`[GS샵V3] ${method} ${url}`)
  const response = await fetch(url, options)
  const text = await response.text()

  let data
  try { data = JSON.parse(text) } catch { data = { raw: text } }

  console.log(`[GS샵V3] ${method} ${path} → ${response.status}`, data?.resultCode || '')

  if (!response.ok) {
    const err = new Error(`[${response.status}] ${data?.message || data?.msg || text.substring(0, 120)}`)
    err.gsCode = response.status
    err.gsData = data
    throw err
  }

  return { success: true, data, status: response.status }
}

/**
 * 요청에서 GS샵 자격증명 추출 후 토큰 생성
 */
function extractGsCreds(req) {
  const supCd    = req.headers['x-gs-sup-cd']  || req.body?.supCd  || req.query?.supCd  || ''
  const aesKey   = req.headers['x-gs-aes-key'] || req.body?.aesKey || req.query?.aesKey || ''
  const subSupCd = req.headers['x-gs-sub-sup-cd'] || req.body?.subSupCd || ''
  const env      = req.headers['x-gs-env'] || req.query?.env || 'dev'  // 'dev'=테스트, 'prod'=운영
  const token    = aesKey && supCd ? generateGsToken(supCd, aesKey) : ''
  return { supCd, aesKey, subSupCd, env, token }
}

// ─────────────────────────────────────────────
// GS샵 API: 인증 확인 (MDID 조회로 검증)
// GET /api/gsshop/auth/check
// ─────────────────────────────────────────────
app.get('/api/gsshop/auth/check', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  if (!supCd || !token) {
    return res.json({ success: false, authenticated: false, message: 'supCd와 aesKey가 필요합니다.' })
  }
  try {
    // MDID 조회로 인증 유효성 간접 검증
    const result = await callGsApi('/api/v3/products/getSupMdidList.gs', 'GET', null, {}, supCd, token, env)
    return res.json({ success: true, authenticated: true, env, message: `인증 성공 (${env === 'prod' ? '운영' : '테스트'})`, data: result.data })
  } catch (e) {
    return res.json({ success: false, authenticated: false, message: e.message, code: e.gsCode })
  }
})

// ─────────────────────────────────────────────
// GS샵 API: 기초정보 조회
// ─────────────────────────────────────────────

// GET /api/gsshop/brands?brandNm=검색어  → /api/v3/products/getPrdBrandList (이름으로 검색)
// GET /api/gsshop/brands?fromDtm=&toDtm= → /SupSendBrandInfo.gs (변경분 배치 조회)
app.get('/api/gsshop/brands', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { brandNm, fromDtm, toDtm } = req.query
  try {
    let result
    if (brandNm !== undefined) {
      // 이름 검색 API
      result = await callGsApi('/api/v3/products/getPrdBrandList', 'GET', null, { brandNm: brandNm || '' }, supCd, token, env)
    } else {
      // 변경분 배치 API (fromDtm/toDtm, 최대 7일)
      result = await callGsApi('/SupSendBrandInfo.gs', 'GET', null,
        { ...(fromDtm && { fromDtm }), ...(toDtm && { toDtm }) }, supCd, token, env)
    }
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/categories?sectSts=A&shopAttrCd=S  → 전시매장(GS 카테고리) 조회
app.get('/api/gsshop/categories', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { sectSts = 'A', shopAttrCd = '' } = req.query
  try {
    const result = await callGsApi('/api/v3/products/getAllSectList', 'GET', null,
      { ...(sectSts && { sectSts }), ...(shopAttrCd && { shopAttrCd }) }, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/product-categories  → 상품분류코드 전체 조회 (1일 1회 배치용)
app.get('/api/gsshop/product-categories', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  try {
    const result = await callGsApi('/SupSendPrdClsInfo.gs', 'GET', null, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/delivery-places  → 출고지/반송지 전체 조회
// Query: supAddrCd, addrGbnNm, dirdlvRelspYn, dirdlvRetpYn
app.get('/api/gsshop/delivery-places', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { supAddrCd, addrGbnNm, dirdlvRelspYn, dirdlvRetpYn } = req.query
  const params = {}
  if (supAddrCd)    params.supAddrCd    = supAddrCd
  if (addrGbnNm)    params.addrGbnNm    = addrGbnNm
  if (dirdlvRelspYn) params.dirdlvRelspYn = dirdlvRelspYn
  if (dirdlvRetpYn)  params.dirdlvRetpYn  = dirdlvRetpYn
  try {
    const result = await callGsApi('/api/v3/products/getSupAddrList.gs', 'GET', null, params, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/delivery-places/register  → 출고지/반송지 등록
app.post('/api/gsshop/delivery-places/register', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { supCd: _s, aesKey: _k, ...addrData } = req.body
  try {
    const result = await callGsApi('/api/v3/supAddrReg.gs', 'POST', addrData, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/delivery-places/update  → 출고지/반송지 수정
app.post('/api/gsshop/delivery-places/update', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { supCd: _s, aesKey: _k, ...addrData } = req.body
  try {
    const result = await callGsApi('/api/v3/supAddrMod.gs', 'POST', addrData, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/md-list  → 협력사 MDID 조회 (V1.0.1)
// Query: subSupCheckYn(Y/N), subSupCd
//        prcModAuthYn(A=전체/Y=권한있음/N=권한없음)
//        prdNmModAuthYn(A/Y/N), descdModAuthYn(A/Y/N)
// 권한 중 하나라도 N이면 상품등록 시 GS상품코드 미리턴 → MD승인 필요
app.get('/api/gsshop/md-list', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const {
    subSupCheckYn = 'N', subSupCd,
    prcModAuthYn = 'A', prdNmModAuthYn = 'A', descdModAuthYn = 'A'
  } = req.query
  const params = { prcModAuthYn, prdNmModAuthYn, descdModAuthYn, subSupCheckYn }
  if (subSupCd) params.subSupCd = subSupCd
  try {
    const result = await callGsApi('/api/v3/products/getSupMdidList.gs', 'GET', null, params, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// ─────────────────────────────────────────────
// GS샵 API: 상품 등록/수정
// ─────────────────────────────────────────────

// POST /api/gsshop/goods  → 상품 등록
app.post('/api/gsshop/goods', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { supCd: _s, aesKey: _k, env: _e, ...goodsData } = req.body
  try {
    const result = await callGsApi('/api/v3/products', 'POST', goodsData, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode, detail: e.gsData })
  }
})

// POST /api/gsshop/goods/:supPrdCd/base-info  → 기본부가정보 수정
app.post('/api/gsshop/goods/:supPrdCd/base-info', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  const { supCd: _s, aesKey: _k, env: _e, ...bodyData } = req.body
  try {
    const result = await callGsApi(`/api/v3/products/${supPrdCd}/base-info`, 'POST', bodyData, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/goods/:supPrdCd/price  → 가격 수정
app.post('/api/gsshop/goods/:supPrdCd/price', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token, subSupCd } = extractGsCreds(req)
  const { prdPrcInfo } = req.body
  try {
    const result = await callGsApi(`/api/v3/products/${supPrdCd}/price`, 'POST',
      { subSupCd, prdPrcInfo }, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/goods/:supPrdCd/sale-status  → 판매상태 변경
app.post('/api/gsshop/goods/:supPrdCd/sale-status', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  const { saleEndDtm, attrSaleEndStModYn = 'Y' } = req.body
  try {
    const result = await callGsApi(`/api/v3/products/${supPrdCd}/sale-status`, 'POST',
      { saleEndDtm, attrSaleEndStModYn }, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/goods/:supPrdCd/images  → 이미지 수정
app.post('/api/gsshop/goods/:supPrdCd/images', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  const { prdCntntListCntntUrlNm, mobilBannerImgUrl } = req.body
  try {
    const result = await callGsApi(`/api/v3/products/${supPrdCd}/images`, 'POST',
      { prdCntntListCntntUrlNm, mobilBannerImgUrl }, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/goods/:supPrdCd/attributes  → 속성(옵션) 수정
app.post('/api/gsshop/goods/:supPrdCd/attributes', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  const { attrPrdList, prdTypCd, subSupCd } = req.body
  try {
    const result = await callGsApi(`/api/v3/products/${supPrdCd}/attributes`, 'POST',
      { prdTypCd, subSupCd, attrPrdList }, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/goods/:supPrdCd/approve-status  → 상품 승인상태 조회
// 응답: prdStCd(R=승인요청,F=반려,N=대기,Y=판매중,E=종료,T=품절,D=완전종료), prdCd, ecExposYn, returnDesc
app.get('/api/gsshop/goods/:supPrdCd/approve-status', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  try {
    const result = await callGsApi('/api/v3/getPrdAprvInfo.gs', 'GET', null,
      { supCd, supPrdCd }, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// GET /api/gsshop/goods/:supPrdCd  → 상품 상세 조회 (MD승인 완료 상품만)
// Query: searchItmCd (ALL|NM,PRC,ATTR,DLV,ADD,CMP,SECT,SAFE,GOV,SPEC,HTML,IMG,QADE)
app.get('/api/gsshop/goods/:supPrdCd', async (req, res) => {
  const { supPrdCd } = req.params
  const { supCd, env, token } = extractGsCreds(req)
  const { searchItmCd = 'ALL' } = req.query
  try {
    const result = await callGsApi('/api/v3/getPrdInfo.gs', 'GET', null,
      { supCd, supPrdCd, searchItmCd }, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// ─────────────────────────────────────────────
// GS샵 API: 프로모션
// ─────────────────────────────────────────────

// GET /api/gsshop/promotions  → 프로모션 목록 조회
// Query: fromDtm(필수), toDtm(필수), pmoApplySt, prdCd, prdNm, brandCd, rowsPerPage, pageIdx
app.get('/api/gsshop/promotions', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { fromDtm, toDtm, pmoApplySt = 'ALL', prdCd, prdNm, brandCd, rowsPerPage = 100, pageIdx = 1 } = req.query
  if (!fromDtm || !toDtm) {
    return res.json({ success: false, message: 'fromDtm, toDtm 필수 (yyyyMMdd, 최대 7일)' })
  }
  const params = { fromDtm, toDtm, pmoApplySt, rowsPerPage, pageIdx, params: {} }
  if (prdCd)   params.prdCd   = prdCd
  if (prdNm)   params.prdNm   = prdNm
  if (brandCd) params.brandCd = brandCd
  try {
    const result = await callGsApi('/api/v3/getPromotionList.gs', 'GET', null, params, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// POST /api/gsshop/promotions/approve  → 프로모션 승인/반려 처리
// Body: { saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd(30=승인/40=반려), aprvRetRsn }
app.post('/api/gsshop/promotions/approve', async (req, res) => {
  const { supCd, env, token } = extractGsCreds(req)
  const { saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd, aprvRetRsn } = req.body
  if (!saleproAgreeDocNo || !pmoReqNo || !prdCd || !aprvStCd) {
    return res.json({ success: false, message: 'saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd 필수' })
  }
  const body = { saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd }
  if (aprvRetRsn) body.aprvRetRsn = aprvRetRsn
  try {
    const result = await callGsApi('/api/v3/modifyPromotionStatus.gs', 'POST', body, {}, supCd, token, env)
    return res.json({ success: true, data: result.data })
  } catch (e) {
    return res.json({ success: false, message: e.message, code: e.gsCode })
  }
})

// ═══════════════════════════════════════════════════════════
// 알리고(ALIGO) SMS / 카카오 알림톡
// ═══════════════════════════════════════════════════════════

/**
 * 알리고 API 공통 호출 (application/x-www-form-urlencoded)
 */
async function callAligoApi(url, params) {
  const body = new URLSearchParams(params).toString()
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body
  })
  const text = await res.text()
  try { return JSON.parse(text) } catch { return { result_code: '-1', message: text } }
}

// POST /api/aligo/sms/test  → SMS API Key 잔액조회로 검증
app.post('/api/aligo/sms/test', async (req, res) => {
  const { userId, apiKey } = req.body
  if (!userId || !apiKey) return res.json({ success: false, message: 'userId와 apiKey가 필요합니다.' })
  try {
    const data = await callAligoApi('https://apis.aligo.in/remain/', { key: apiKey, user_id: userId })
    if (Number(data.result_code) > 0) {
      return res.json({ success: true, message: `인증 성공 (SMS잔여: ${data.SMS_CNT}건)`, data })
    }
    return res.json({ success: false, message: data.message || '인증 실패' })
  } catch (e) {
    return res.json({ success: false, message: e.message })
  }
})

// POST /api/aligo/kakao/test  → 카카오 알림톡 토큰 발급으로 검증
app.post('/api/aligo/kakao/test', async (req, res) => {
  const { userId, apiKey } = req.body
  if (!userId || !apiKey) return res.json({ success: false, message: 'userId와 apiKey가 필요합니다.' })
  try {
    const data = await callAligoApi('https://kakaoapi.aligo.in/akv10/token/create/30/s/', { userid: userId, apikey: apiKey })
    if (Number(data.code) === 0) {
      return res.json({ success: true, message: '카카오 알림톡 인증 성공', token: data.token })
    }
    return res.json({ success: false, message: data.message || '인증 실패' })
  } catch (e) {
    return res.json({ success: false, message: e.message })
  }
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
║   POST /api/lottehome/auth      롯데홈쇼핑 인증  ║
║   GET  /api/lottehome/*         롯데홈쇼핑 기초정보║
║   POST /api/lottehome/goods     롯데홈쇼핑 상품등록║
║   GET  /api/gsshop/auth/check  GS샵 인증확인     ║
║   POST /api/gsshop/goods       GS샵 상품등록      ║
║   GET  /api/gsshop/goods/:id   GS샵 상품조회      ║
╚══════════════════════════════════════════════════╝
  `)
})

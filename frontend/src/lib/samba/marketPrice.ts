// 정책 기반 마켓별 판매가 계산 — 백엔드 calc_market_price(shipment/service.py)와 동일 로직
// 상품관리(ProductCard)와 수동등록(ManualProductCard)이 공유
import { fmtNum } from '@/lib/samba/styles'

const fmt = fmtNum

// 가격범위별 마진 매칭 (백엔드 _resolve_margin_rate와 동일: cost >= min && cost < max)
export function pickRangeMargin(
  cost: number,
  ranges: Array<{ min?: number; max?: number; rate?: number }>,
  fallback: number,
): number {
  for (const r of ranges) {
    const min = r.min ?? 0
    const max = r.max || 9999999999
    if (cost >= min && cost < max) return r.rate ?? fallback
  }
  return fallback
}

// 소싱처별 추가 마진 추출 (GSShop 대소문자 별칭 지원)
export function getSourceSiteMargin(
  sourceSiteMargins: Record<string, { marginRate?: number; marginAmount?: number; pointOnly?: boolean }>,
  sourceSite: string,
): { marginRate?: number; marginAmount?: number; pointOnly?: boolean } {
  if (sourceSiteMargins[sourceSite]) return sourceSiteMargins[sourceSite]
  if (sourceSite === 'GSSHOP' && sourceSiteMargins.GSShop) return sourceSiteMargins.GSShop
  if (sourceSite === 'GSShop' && sourceSiteMargins.GSSHOP) return sourceSiteMargins.GSSHOP
  return {}
}

// 마켓 최종 판매가 계산 (원가 + 마진 + 배송비 → 소싱추가마진 → 수수료 역산 → 추가요금 → 100원 절사)
export function calcPrice(
  cost: number, mRate: number, ship: number, fee: number, extra: number, minMargin: number,
  ssMRate = 0, ssMAmount = 0, curSym = '₩',
): { price: number; marginAmt: number; usedMin: boolean; feeAmt: number; calcStr: string } {
  let marginAmt = Math.round(cost * mRate / 100)
  const usedMin = minMargin > 0 && marginAmt < minMargin
  if (usedMin) marginAmt = minMargin
  let price = cost + marginAmt + ship
  // 소싱처별 추가 마진 (수수료 역산 전 적용 — 백엔드 calc_market_price와 동일)
  if (ssMRate !== 0) price += Math.round(cost * ssMRate / 100)
  if (ssMAmount !== 0) price += ssMAmount
  if (fee > 0 && price > 0) price = Math.ceil(price / (1 - fee / 100))
  if (extra > 0) price += extra
  // 100원 단위 절사 (백엔드 calc_market_price와 동일)
  price = Math.floor(price / 100) * 100
  const feeAmt = fee > 0 && price > 0 ? Math.round(price * fee / 100) : 0
  const ssAmt = Math.round(cost * ssMRate / 100) + ssMAmount
  const ssRateLabel = ssMRate !== 0 && ssMAmount !== 0
    ? ` (${ssMRate}% + ${fmt(ssMAmount)})`
    : ssMRate !== 0
      ? ` (${ssMRate}%)`
      : ''
  const ssExtra = ssMRate !== 0 || ssMAmount !== 0
    ? ` + 소싱추가마진 ${fmt(ssAmt)}${ssRateLabel}`
    : ''
  const parts = [
    `원가 ${fmt(cost)}`,
    usedMin ? `마진 ${fmt(marginAmt)}(최소마진)` : `마진 ${fmt(marginAmt)}(${mRate}%)`,
    `배송비 ${fmt(ship)}`,
    `추가요금 ${fmt(extra)}`,
    `수수료 ${fmt(feeAmt)}(${fee}%)`,
  ]
  return { price, marginAmt, usedMin, feeAmt, calcStr: `${curSym}${fmt(price)} = ${parts.join(' + ')}${ssExtra}` }
}

interface MarketPolicyEntry {
  accountId?: string
  feeRate?: number
  shippingCost?: number
  marginRate?: number
  brand?: string
  extraFeeRate?: number
}

interface PricingInput {
  marginRate?: number
  feeRate?: number
  shippingCost?: number
  extraCharge?: number
  minMarginAmount?: number
  useRangeMargin?: boolean
  rangeMargins?: Array<{ min?: number; max?: number; rate?: number }>
  sourceSiteMargins?: Record<string, { marginRate?: number; marginAmount?: number; pointOnly?: boolean }>
}

interface AccountLike {
  id: string
  additional_fields?: Record<string, unknown>
}

export interface MarketPriceRow {
  marketName: string
  price: number
  calcStr: string
}

// 정책의 market_policies를 순회하며 계정 연결된 마켓별 판매가 목록 생성
// 백엔드 calc_market_price + ProductCard의 마켓별 보정(스스/롯데홈/신세계)과 동일
export function buildMarketPriceList(params: {
  pricing: Record<string, unknown>
  marketPolicies: Record<string, unknown>
  accounts: AccountLike[]
  cost: number
  sourceSite: string
  isPointRestricted?: boolean | null
  curSym?: string
}): MarketPriceRow[] {
  const { accounts, cost, sourceSite, isPointRestricted, curSym = '₩' } = params
  const pricing = params.pricing as PricingInput
  const marketPolicies = params.marketPolicies as Record<string, MarketPolicyEntry>

  const baseMarginRate = pricing.marginRate || 15
  const useRangeMargin = Boolean(pricing.useRangeMargin)
  const rangeMargins = pricing.rangeMargins || []
  const marginRate = useRangeMargin && rangeMargins.length > 0
    ? pickRangeMargin(cost, rangeMargins, baseMarginRate)
    : baseMarginRate
  const extraCharge = pricing.extraCharge || 0
  const shippingCost = pricing.shippingCost || 0
  const feeRate = pricing.feeRate || 0
  const minMarginAmount = pricing.minMarginAmount || 0

  // 소싱처별 추가 마진 게이트 (백엔드와 동일: pointOnly면 적립금 사용 가능 상품에만)
  const sourceSiteMargins = pricing.sourceSiteMargins || {}
  const ssmData = getSourceSiteMargin(sourceSiteMargins, sourceSite)
  const ssmApply = !ssmData.pointOnly || isPointRestricted === false
  const ssMRate = ssmApply ? ssmData.marginRate || 0 : 0
  const ssMAmount = ssmApply ? ssmData.marginAmount || 0 : 0

  const accMap = new Map(accounts.map(a => [a.id, a]))

  return Object.entries(marketPolicies)
    .filter(([, v]) => v.accountId)
    .map(([marketName, v]) => {
      const acct = v.accountId ? accMap.get(v.accountId) : undefined
      const af = (acct?.additional_fields as Record<string, unknown> | undefined) ?? {}
      const acctFeeRate = Number(af.feeRate || 0)
      const acctExtraFeeRate = Number(af.extraFeeRate || 0)
      const r = calcPrice(cost, marginRate, (v.shippingCost ?? shippingCost) || shippingCost, acctFeeRate || v.feeRate || feeRate, extraCharge, minMarginAmount, ssMRate, ssMAmount, curSym)
      let displayPrice = r.price
      let displayCalcStr = r.calcStr
      // 스마트스토어: 300원 올림 (네이버 수수료 역산)
      if (marketName.includes('스마트스토어')) {
        displayPrice = Math.ceil(r.price / 300) * 300
        const diff = displayPrice - r.price
        if (diff > 0) {
          displayCalcStr = `${curSym}${fmt(displayPrice)} = ${r.calcStr.split(' = ')[1]} + 300원올림 +${fmt(diff)}`
        }
      }
      // 롯데홈쇼핑: 추가수수료율 역산 + 10원 단위 올림
      if (marketName === '롯데홈쇼핑') {
        const lhExtraFeeRate = Number((v as Record<string, unknown>).extraFeeRate || 0)
        if (lhExtraFeeRate > 0 && lhExtraFeeRate < 100) {
          const before = displayPrice
          displayPrice = Math.ceil(before / (1 - lhExtraFeeRate / 100))
          const extraAmt = displayPrice - before
          const baseCalc = displayCalcStr.split(' = ').slice(1).join(' = ')
          displayCalcStr = `${curSym}${fmt(displayPrice)} = ${baseCalc} + 추가수수료 ${fmt(extraAmt)}(${lhExtraFeeRate}%)`
        }
        const rounded = Math.ceil(displayPrice / 10) * 10
        if (rounded !== displayPrice) {
          displayCalcStr = displayCalcStr.replace(/^[₩$][\d,]+/, `${curSym}${fmt(rounded)}`)
          displayPrice = rounded
        }
      }
      // 신세계몰(전시): 추가수수료율 역산 + 100원 단위 올림
      if (marketName === '신세계몰(전시)') {
        if (acctExtraFeeRate > 0) {
          const before = displayPrice
          displayPrice = Math.ceil(before / (1 - acctExtraFeeRate / 100))
          const extraAmt = displayPrice - before
          const baseCalc = displayCalcStr.split(' = ').slice(1).join(' = ')
          displayCalcStr = `${curSym}${fmt(displayPrice)} = ${baseCalc} + 추가수수료 ${fmt(extraAmt)}(${acctExtraFeeRate}%)`
        }
        const rounded = Math.ceil(displayPrice / 100) * 100
        if (rounded !== displayPrice) {
          displayCalcStr = displayCalcStr.replace(/^[₩$][\d,]+/, `${curSym}${fmt(rounded)}`)
          displayPrice = rounded
        }
      }
      return { marketName, price: displayPrice, calcStr: displayCalcStr }
    })
}

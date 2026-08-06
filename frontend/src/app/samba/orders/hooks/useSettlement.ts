'use client'

// 정산금 계산 공용 훅 — PC 주문화면(useOrderActions)과 폰 화면(/m)이 같은 식을 쓰도록 분리.
// 여기 로직을 고치면 양쪽에 동시 반영된다. 복붙 금지.

import { useEffect, useState } from 'react'
import { policyApi, type SambaOrder } from '@/lib/samba/api/commerce'

export function useSettlement() {
  // 크림 해외판매 수수료(정책설정) — 기본수수료(원) + 판매가 비율(%). 하드코딩 금지.
  // 옵션이 '해외배송'(박스/카드팩)인 크림 주문 정산금액에서 차감 표시. PSA 카드는 미적용.
  const [kreamOverseasFee, setKreamOverseasFee] = useState({ base: 1370, rate: 3.3 })
  // 실물(신발/의류/시계) 수수료 — 기본수수료 + 등급별 요율, VAT 별도. 등급은 매달 바뀐다.
  const [kreamItemFee, setKreamItemFee] = useState({ base: 2500, rate: 5.6, vat: 10 })

  useEffect(() => {
    policyApi.list(0, 200).then((pols) => {
      for (const p of pols) {
        const k = ((p.market_policies || {}) as Record<string, {
          kreamOverseasBaseFee?: number; kreamOverseasFeeRate?: number
          kreamItemFeeBase?: number; kreamSellerLevel?: number; kreamItemFeeVat?: number
        }>)['KREAM']
        if (k && (k.kreamOverseasBaseFee != null || k.kreamOverseasFeeRate != null)) {
          setKreamOverseasFee({ base: Number(k.kreamOverseasBaseFee ?? 1370), rate: Number(k.kreamOverseasFeeRate ?? 3.3) })
          // 등급→요율 매핑은 백엔드 margin-policy 와 동일값 유지
          const lvRate: Record<number, number> = { 5: 5.50, 4: 5.60, 3: 5.70, 2: 5.85, 1: 6.00 }
          setKreamItemFee({
            base: Number(k.kreamItemFeeBase ?? 2500),
            rate: lvRate[Number(k.kreamSellerLevel ?? 4)] ?? 5.6,
            vat: Number(k.kreamItemFeeVat ?? 10),
          })
          break
        }
      }
    }).catch(() => {})
  }, [])

  // 주문의 실제 정산금액 = 판매가 − 수수료. 크림은 revenue=판매가(수수료 미차감 저장)라
  // 표시 시점에 차감한다. 카테고리별로 수수료 체계가 다르다.
  //   해외배송 옵션(박스/카드팩) → 기본 1,370 + 3.3%
  //   PSA 10 / PSA 9 카드        → 수수료 무료
  //   그 외(신발·의류·시계 등)   → 기본 2,500 + 등급요율(5.60% @4등급), VAT 별도
  // [2026-08-03] '해외배송' 문자열이 있을 때만 차감해 신발 옵션(275, 240(US 5.5))이 전부
  // 빠졌다 — 정산=결제, 수수료율 0.0% 로 표시되던 버그.
  const getRevenue = (o: SambaOrder): number => {
    const isKream = String(o.source_site || '').toUpperCase().includes('KREAM')
      || String(o.sales_channel_alias || '').toUpperCase().includes('KREAM')
    const rev = o.revenue || 0
    if (!isKream || rev <= 0) return rev
    const opt = String(o.product_option || '')
    if (opt.includes('해외배송')) {
      // 10원 단위 절사(크림 정산 표기와 일치)
      const fee = Math.floor((kreamOverseasFee.base + rev * kreamOverseasFee.rate / 100) / 10) * 10
      return rev - fee
    }
    if (/^\s*PSA\s*(9|10)\b/i.test(opt)) return rev  // PSA 카드 수수료 무료
    const itemFee = Math.floor(
      ((kreamItemFee.base + rev * kreamItemFee.rate / 100) * (1 + kreamItemFee.vat / 100)) / 10
    ) * 10
    return rev - itemFee
  }

  return { getRevenue }
}

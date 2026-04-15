'use client'

import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  accountApi,
  collectorApi,
  forbiddenApi,
  proxyApi,
  proxyConfigApi,
  type SambaMarketAccount,
  type ProxyConfigItem,
  type ProxyPurpose,
} from '@/lib/samba/api/commerce'
import { API_BASE } from '@/lib/samba/api/shared'
import {
  sourcingAccountApi,
  tenantApi,
  type SambaSourcingAccount,
  type ChromeProfile,
  type TenantUsage,
} from '@/lib/samba/api/operations'
import { MARKET_SELECT_OPTIONS } from '@/lib/samba/markets'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { card, inputStyle, fmtNum, parseNum } from '@/lib/samba/styles'
import { NumInputStr as NumInput } from '@/components/samba/NumInput'

// 마켓 셀렉트 옵션 (markets.ts 단일 소스)
const MARKET_TYPES = MARKET_SELECT_OPTIONS

const CLAUDE_MODELS = [
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (권장)' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6 (고성능)' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5 (빠름/저렴)' },
]

const AI_FEATURES = [
  { key: 'productName', label: '상품명 가공' },
  { key: 'description', label: '상세설명 생성' },
  { key: 'csReply', label: 'CS 자동 답변' },
  { key: 'autoTag', label: '태그 자동 생성' },
  { key: 'imageProcess', label: '이미지 가공' },
]


// 마켓별 스토어 연결 필드 정의
type ExchangeCurrencyCode = 'USD' | 'JPY' | 'CNY' | 'EUR'

type ExchangeRateItem = {
  code: ExchangeCurrencyCode
  label: string
  baseRate: number
  adjustment: number
  fixedRate: number
  effectiveRate: number
  useFixed: boolean
}

type ExchangeRateResponse = {
  provider: string
  base: string
  fetchedAt?: string
  publishedAt?: string
  currencies: Record<ExchangeCurrencyCode, ExchangeRateItem>
}

const EXCHANGE_CURRENCY_ORDER: ExchangeCurrencyCode[] = ['USD', 'JPY', 'CNY', 'EUR']
const getExchangeDisplayMultiplier = (code: ExchangeCurrencyCode) => code === 'JPY' ? 100 : 1

const EMPTY_EXCHANGE_RATES: ExchangeRateResponse = {
  provider: '',
  base: 'KRW',
  currencies: {
    USD: { code: 'USD', label: '달러', baseRate: 0, adjustment: 0, fixedRate: 0, effectiveRate: 0, useFixed: false },
    JPY: { code: 'JPY', label: '엔화', baseRate: 0, adjustment: 0, fixedRate: 0, effectiveRate: 0, useFixed: false },
    CNY: { code: 'CNY', label: '위안화', baseRate: 0, adjustment: 0, fixedRate: 0, effectiveRate: 0, useFixed: false },
    EUR: { code: 'EUR', label: '유로화', baseRate: 0, adjustment: 0, fixedRate: 0, effectiveRate: 0, useFixed: false },
  },
}

interface MarketConfig {
  key: string
  label: string
  authField?: string
  guideUrl?: string // API 가이드 링크
  fields: { name: string; label: string; type: string; placeholder?: string; options?: { value: string; label: string }[]; disabled?: boolean; fixedValue?: number; description?: string }[]
}

const STORE_MARKETS: MarketConfig[] = [
  { key: 'smartstore', label: '스마트스토어', authField: 'clientSecret', guideUrl: 'https://apicenter.commerce.naver.com/ko/member/home', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'clientId', label: 'Client ID', type: 'text' },
    { name: 'clientSecret', label: 'Client Secret', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', disabled: true, fixedValue: 25, description: 'SmartStore 판매가 10원 단위 제약으로 25% 고정' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'returnSafeguard', label: '반품안심케어', type: 'select', options: [
      { value: '', label: '설정안함' },
      { value: 'true', label: '설정함' },
    ]},
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'naverShopping', label: '가격비교 사이트 등록', type: 'checkbox', placeholder: '네이버쇼핑에 상품 노출' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' },
      { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
    { name: '_info_storeMember', label: '알림받기 동의고객 포인트는 셀러센터에서 직접 설정', type: 'info' },
  ]},
  { key: 'gmarket', label: '지마켓', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'auction', label: '옥션', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'coupang', label: '쿠팡', authField: 'secretKey', guideUrl: 'https://wing.coupang.com/vendor/openapi/application', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'vendorId', label: 'Vendor 업체코드', type: 'text', placeholder: 'Wing 판매자 업체코드' },
    { name: 'accessKey', label: 'Access key', type: 'text' },
    { name: 'secretKey', label: 'Secret key', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '0507-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'lotteon', label: '롯데ON', authField: 'apiKey', guideUrl: 'https://openapi.lotteon.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: '롯데ON API key', type: 'text' },
    { name: 'dvCstPolNo', label: '배송정책번호', type: 'text', placeholder: '예: 3757145' },
    { name: 'dvIslandCstPolNo', label: '도서산간 배송정책번호', type: 'text', placeholder: '예: 3757146' },
    { name: 'owhpNo', label: '출고지번호', type: 'text', placeholder: '예: PLO3293317' },
    { name: 'rtrpNo', label: '회수지번호', type: 'text', placeholder: '예: PLO3293317' },
    { name: 'bundleDelivery', label: '묶음배송', type: 'select', options: [
      { value: 'N', label: '불가능' }, { value: 'Y', label: '가능' },
    ]},
    { name: 'dispatchDays', label: '발송완료 N일 이내', type: 'select', options: [
      { value: '1', label: '1일' }, { value: '2', label: '2일' }, { value: '3', label: '3일' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'promotionMessage', label: '상품홍보문구', type: 'text', placeholder: '홍보 문구 입력' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_point', label: '스토어 즉시할인', type: 'divider' },
    { name: 'discountRate', label: '즉시 할인율 (%)', type: 'number', placeholder: '0 (미설정)' },
    { name: '_divider_review', label: 'LPOINT 추가적립', type: 'divider' },
    { name: 'reviewTextPoint', label: '구매확정 적립 LPOINT', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '리뷰작성시 LPOINT', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '사진첨부시 LPOINT', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '동영상첨부시 LPOINT', type: 'number', placeholder: '원' },
    { name: '_divider_purchase_confirm', label: '구매확정', type: 'divider' },
    { name: 'purchaseConfirmDays', label: '구매확정기간', type: 'select', options: [
      { value: '1', label: '1일' }, { value: '3', label: '3일' }, { value: '5', label: '5일' },
      { value: '7', label: '7일' }, { value: '10', label: '10일' }, { value: '14', label: '14일' },
      { value: '20', label: '20일' }, { value: '30', label: '30일' },
    ]},
    { name: '_divider_event_exclude', label: '행사 제외 설정', type: 'divider' },
    { name: 'ownerDiscountExclude', label: '오너스할인', type: 'radio', options: [
      { value: 'N', label: '제외안함' }, { value: 'Y', label: '제외' },
    ]},
    { name: 'unitCouponExclude', label: '상품단위쿠폰', type: 'radio', options: [
      { value: 'N', label: '제외안함' }, { value: 'Y', label: '제외' },
    ]},
    { name: 'deliveryCouponExclude', label: '배송쿠폰', type: 'radio', options: [
      { value: 'N', label: '제외안함' }, { value: 'Y', label: '제외' },
    ]},
    { name: 'cmPcsExclude', label: '가격비교채널할인(CM+PCS)', type: 'radio', options: [
      { value: 'N', label: '제외안함' }, { value: 'Y', label: '제외' },
    ]},
    { name: 'pcsExclude', label: '가격비교(PCS)할인', type: 'radio', options: [
      { value: 'N', label: '제외안함' }, { value: 'Y', label: '제외' },
    ]},
  ]},
  { key: '11st', label: '11번가', authField: 'apiKey', guideUrl: 'https://openapi.11st.co.kr/openapi/OpenApiServiceRegister.tmall', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '상품전송 ID', type: 'text', placeholder: '11번가 셀러 ID' },
    { name: 'apiKey', label: 'Open API Key', type: 'text', placeholder: '32자리 Open API Key' },
    { name: 'sellerType', label: '판매자 형태', type: 'select', options: [
      { value: 'domestic', label: '국내판매자(국내사업자)' },
      { value: 'global', label: '글로벌판매자(국내사업자)' },
      { value: 'overseas', label: '국내판매자(해외사업자)' },
    ]},
    { name: 'taxType', label: '과세구분', type: 'select', options: [
      { value: '01', label: '과세' }, { value: '02', label: '면세' },
    ]},
    { name: 'deliveryType', label: '배송비 유형', type: 'select', options: [
      { value: 'DV_FREE', label: '무료배송' }, { value: 'DV_FIX', label: '유료배송(고정)' }, { value: 'DV_COND', label: '조건부 무료' },
    ]},
    { name: 'deliveryFee', label: '배송비', type: 'number', placeholder: '0' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S안내', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '4000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '8000' },
    { name: 'jejuFee', label: '제주 추가배송비', type: 'number', placeholder: '4000' },
    { name: 'islandFee', label: '도서지역 추가배송비', type: 'number', placeholder: '5000' },
    { name: 'shipFromAddress', label: '출고지 주소', type: 'text', placeholder: '출고지 주소 입력' },
    { name: 'returnAddress', label: '반품지 주소', type: 'text', placeholder: '반품지 주소 입력' },
    { name: 'origin', label: '원산지', type: 'text', placeholder: '기타' },
    { name: 'returnExchangeGuide', label: '반품/교환 안내', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'minorRestrict', label: '청소년구매불가', type: 'select', options: [
      { value: 'N', label: '아니오' }, { value: 'Y', label: '예' },
    ]},
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '복수구매 할인', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매 할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseBasisType', label: '기준', type: 'select', options: [
      { value: '01', label: '수량기준' }, { value: '02', label: '금액기준' },
    ]},
    { name: 'multiPurchaseDiscountMethod', label: '할인', type: 'select', options: [
      { value: '02', label: '원 할인' }, { value: '01', label: '% 할인' },
    ]},
    { name: 'multiPurchaseQty', label: 'N개 이상 구매시', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseAmt', label: '개당 할인값 (원 또는 %)', type: 'number', placeholder: '1000' },
    { name: 'multiPurchasePeriodEnabled', label: '할인 적용기간 설정', type: 'checkbox' },
    { name: 'multiPurchaseStartDate', label: '할인 시작일 (YYYYMMDD)', type: 'text', placeholder: '20260101' },
    { name: 'multiPurchaseEndDate', label: '할인 종료일 (YYYYMMDD)', type: 'text', placeholder: '20261231' },
    { name: '_divider_point', label: '11Pay 포인트', type: 'divider' },
    { name: 'llpayPointEnabled', label: '11Pay 포인트 적립', type: 'checkbox' },
    { name: 'llpayPointType', label: '적립 방식', type: 'select', options: [
      { value: '02', label: '정액 (원)' }, { value: '01', label: '정률 (%)' },
    ]},
    { name: 'llpayPointValue', label: '적립 값 (원 또는 %)', type: 'number', placeholder: '100' },
  ]},
  { key: 'toss', label: '토스', authField: 'apiKey', guideUrl: 'https://shopping-docs.toss.im/dev', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'apiSecret', label: 'API Secret', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'ssg', label: '신세계몰', authField: 'apiKey', guideUrl: 'https://opn-ssg.ssgadm.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: '_divider_margin', label: '가격 설정', type: 'divider' },
    { name: 'marginRate', label: '마진율(%)', type: 'number', placeholder: '15' },
    { name: '_divider_delivery_ssg', label: '배송 설정', type: 'divider' },
    { name: 'shppRqrmDcnt', label: '배송소요일', type: 'number', placeholder: '3' },
    { name: '_divider_shipping_code', label: '배송비/출고지 (SSG API 조회)', type: 'divider' },
    { name: 'whoutShppcstId', label: '출고배송비', type: 'ssg-shipping-select', placeholder: '버튼으로 불러오기' },
    { name: 'retShppcstId', label: '반품배송비', type: 'ssg-shipping-select', placeholder: '버튼으로 불러오기' },
    { name: 'addShppcstIdJeju', label: '제주 추가배송비', type: 'ssg-extra-select', placeholder: '버튼으로 불러오기' },
    { name: 'addShppcstIdIsland', label: '도서산간 추가배송비', type: 'ssg-extra-select', placeholder: '버튼으로 불러오기' },
    { name: 'whoutAddrId', label: '출고지', type: 'ssg-addr-select', placeholder: '버튼으로 불러오기' },
    { name: 'snbkAddrId', label: '반송지', type: 'ssg-addr-select', placeholder: '버튼으로 불러오기' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
  ]},
  { key: 'gsshop', label: 'GSSHOP', authField: 'apiKeyProd', guideUrl: 'https://partners.gsshop.com/api/apiMain', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKeyDev', label: '개발 AES256 인증키', type: 'password' },
    { name: 'apiKeyProd', label: '운영 AES256 인증키', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'lottehome', label: '롯데홈쇼핑', authField: 'password', guideUrl: 'https://partner.lottehomeshopping.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '로그인 ID', type: 'text', placeholder: '롯데홈쇼핑 로그인 ID' },
    { name: 'agncNo', label: '업체번호', type: 'text', placeholder: '예: 037800LT' },
    { name: 'password', label: '비밀번호', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'homeand', label: '홈앤쇼핑', authField: 'apiKey', guideUrl: 'https://partner.home-and.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiId', label: 'API ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'hmall', label: 'HMALL', authField: 'apiKey', guideUrl: 'https://partner.hmall.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiId', label: 'API ID', type: 'text' },
    { name: 'apiKey', label: 'API KEY', type: 'text' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'kream', label: 'KREAM', guideUrl: 'https://kream.co.kr/login', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'saleType', label: '판매유형', type: 'select', options: [
      { value: 'general', label: '일반판매' }, { value: 'storage', label: '보관판매' }, { value: 'grade95', label: '95점판매' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'poison', label: '포이즌', authField: 'apiKey', guideUrl: 'https://www.poizon.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '셀러 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key / Token', type: 'text' },
    { name: 'apiSecret', label: 'API Secret', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'qoo10', label: 'Qoo10', authField: 'apiKey', guideUrl: 'https://qsm.qoo10.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Seller ID', type: 'text' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'userKey', label: 'User Key', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'jp', label: 'Japan' }, { value: 'sg', label: 'Singapore' }, { value: 'global', label: 'Global' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'rakuten', label: '라쿠텐', authField: 'apiKey', guideUrl: 'https://webservice.rakuten.co.jp/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key / Service Secret', type: 'text' },
    { name: 'apiSecret', label: 'License Key', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'buyma', label: '바이마', authField: 'apiKey', guideUrl: 'https://www.buyma.com/buyer/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '셀러 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key / Token', type: 'text' },
    { name: 'apiSecret', label: 'API Secret', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'lazada', label: 'Lazada', authField: 'accessToken', guideUrl: 'https://open.lazada.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Seller ID', type: 'text' },
    { name: 'appKey', label: 'App Key', type: 'text' },
    { name: 'appSecret', label: 'App Secret', type: 'password' },
    { name: 'accessToken', label: 'Access Token', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'sg', label: 'Singapore' }, { value: 'my', label: 'Malaysia' }, { value: 'th', label: 'Thailand' },
      { value: 'ph', label: 'Philippines' }, { value: 'id', label: 'Indonesia' }, { value: 'vn', label: 'Vietnam' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'shopify', label: 'Shopify', authField: 'accessToken', guideUrl: 'https://shopify.dev/docs/api', fields: [
    { name: 'businessName', label: '스토어명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 도메인', type: 'text', placeholder: 'mystore.myshopify.com' },
    { name: 'accessToken', label: 'Admin API Access Token', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'shopee', label: 'Shopee', authField: 'accessToken', guideUrl: 'https://open.shopee.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Shop ID', type: 'text' },
    { name: 'partnerId', label: 'Partner ID', type: 'text' },
    { name: 'partnerKey', label: 'Partner Key', type: 'password' },
    { name: 'accessToken', label: 'Access Token', type: 'password' },
    { name: 'region', label: '지역', type: 'select', options: [
      { value: 'sg', label: 'Singapore' }, { value: 'my', label: 'Malaysia' }, { value: 'th', label: 'Thailand' },
      { value: 'ph', label: 'Philippines' }, { value: 'id', label: 'Indonesia' }, { value: 'vn', label: 'Vietnam' },
      { value: 'tw', label: 'Taiwan' }, { value: 'br', label: 'Brazil' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'zoom', label: 'Zum(줌)', authField: 'apiKey', guideUrl: 'https://shopping.zum.com/seller', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '스토어 ID', type: 'text' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'apiSecret', label: 'API Secret', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'ebay', label: 'eBay', authField: 'oauthToken', guideUrl: 'https://developer.ebay.com/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'eBay Seller ID', type: 'text' },
    { name: 'clientId', label: 'App ID (Client ID)', type: 'text' },
    { name: 'clientSecret', label: 'Cert ID (Client Secret)', type: 'password' },
    { name: 'oauthToken', label: 'OAuth Refresh Token', type: 'password' },
    { name: 'siteId', label: 'Site ID', type: 'select', options: [
      { value: '0', label: 'US (0)' }, { value: '3', label: 'UK (3)' }, { value: '77', label: 'DE (77)' }, { value: '15', label: 'AU (15)' },
    ]},
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'amazon', label: '아마존', authField: 'accessToken', guideUrl: 'https://developer-docs.amazon.com/sp-api/', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: 'Seller ID', type: 'text' },
    { name: 'accessToken', label: 'Refresh Token', type: 'password' },
    { name: 'clientId', label: 'Client ID (LWA)', type: 'text' },
    { name: 'clientSecret', label: 'Client Secret (LWA)', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
  { key: 'playauto', label: '플레이오토', authField: 'apiKey', guideUrl: 'https://www.plto.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '판매자 ID', type: 'text' },
    { name: 'password', label: 'PASSWORD', type: 'password' },
    { name: 'apiKey', label: 'API Key', type: 'text' },
    { name: 'apiSecret', label: '솔루션코드', type: 'password' },
    { name: '_divider_alias', label: '마켓번호 별칭 (주문페이지 표시용)', type: 'divider' },
    { name: 'alias1', label: '계정 1', type: 'alias', placeholder: '037800LT' },
    { name: 'alias2', label: '계정 2', type: 'alias', placeholder: '마켓번호' },
    { name: 'alias3', label: '계정 3', type: 'alias', placeholder: '마켓번호' },
  ]},
  { key: 'cafe24', label: '카페24', authField: 'accessToken', guideUrl: 'https://developers.cafe24.com', fields: [
    { name: 'businessName', label: '사업자명', type: 'text', placeholder: '상호명 입력' },
    { name: 'storeId', label: '쇼핑몰 ID (mall_id)', type: 'text' },
    { name: 'clientId', label: 'Client ID', type: 'text' },
    { name: 'clientSecret', label: 'Client Secret', type: 'password' },
    { name: 'accessToken', label: 'Access Token', type: 'password' },
    { name: 'asPhone', label: 'A/S 전화번호', type: 'text', placeholder: '010-1234-5678' },
    { name: 'asMessage', label: 'A/S 안내 문구', type: 'text', placeholder: '상세페이지 참조' },
    { name: 'discountRate', label: '즉시할인율(%)', type: 'number', placeholder: '0 (미설정)' },
    { name: 'returnFee', label: '반품배송비(편도)', type: 'number', placeholder: '3000' },
    { name: 'exchangeFee', label: '교환배송비(왕복)', type: 'number', placeholder: '6000' },
    { name: 'jejuFee', label: '제주/도서산간 추가비', type: 'number', placeholder: '3000' },
    { name: 'stockQuantity', label: '재고수량', type: 'number', placeholder: '999 (기본값)' },
    { name: 'maxCount', label: '최대 등록 갯수', type: 'number', placeholder: '∞ 무제한' },
    { name: '_divider_purchase', label: '구매/리뷰 혜택 조건', type: 'divider' },
    { name: 'multiPurchaseDiscount', label: '복수구매할인', type: 'select', options: [
      { value: '', label: '설정안함' }, { value: 'true', label: '설정함' },
    ]},
    { name: 'multiPurchaseQty', label: '복수구매 수량 (N개 이상)', type: 'number', placeholder: '2' },
    { name: 'multiPurchaseRate', label: '복수구매 할인율 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_point', label: '포인트', type: 'divider' },
    { name: 'purchasePointEnabled', label: '상품 구매 시 지급', type: 'checkbox' },
    { name: 'purchasePointRate', label: '구매 적립률 (%)', type: 'number', placeholder: '1' },
    { name: '_divider_review', label: '상품리뷰 작성시 지급', type: 'divider' },
    { name: 'reviewPointEnabled', label: '리뷰 포인트 지급', type: 'checkbox' },
    { name: 'reviewTextPoint', label: '텍스트 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewPhotoPoint', label: '포토/동영상 리뷰 작성', type: 'number', placeholder: '원' },
    { name: 'reviewMonthTextPoint', label: '한달사용 텍스트 리뷰', type: 'number', placeholder: '원' },
    { name: 'reviewMonthPhotoPoint', label: '한달사용 포토/동영상 리뷰', type: 'number', placeholder: '원' },
  ]},
]

// select 필드에 대해 DB에 값이 없을 때 주입할 "안전한 기본값"
// ※ 이곳에 등록된 필드만 초기값이 자동 주입된다.
// ※ 의도치 않은 정책 변경(예: dispatchDays) 방지를 위해 화이트리스트 방식으로 관리.
const SAFE_SELECT_DEFAULTS: Record<string, string> = {
  bundleDelivery: 'N',   // 롯데ON 합배송 — 보수적 기본값("불가능")
}

export default function SettingsPage() {
  useEffect(() => { document.title = 'SAMBA-설정' }, [])
  // 티어/사용량
  const [tenantUsage, setTenantUsage] = useState<TenantUsage | null>(null)

  // Accounts state
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])
  const [accountLoading, setAccountLoading] = useState(true)

  // 스토어 연결
  const [storeTab, setStoreTab] = useState('smartstore')
  const [visiblePasswords, setVisiblePasswords] = useState<Set<string>>(new Set())
  const [storeData, setStoreData] = useState<Record<string, Record<string, string>>>({})
  const [savedStoreData, setSavedStoreData] = useState<Record<string, Record<string, string>>>({})
  const [storeStatus, setStoreStatus] = useState<Record<string, string>>({})
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null) // 수정 중인 계정 ID
  // SSG 배송비/주소 옵션 (SSG 탭 진입 시 동적 로드)
  const [ssgShippingOptions, setSsgShippingOptions] = useState<{ value: string; label: string; divCd: number }[]>([])
  const [ssgAddrOptions, setSsgAddrOptions] = useState<{ value: string; label: string }[]>([])

  // 알리고 SMS 설정
  const [smsUserId, setSmsUserId] = useState('')
  const [smsApiKey, setSmsApiKey] = useState('')
  const [smsSender, setSmsSender] = useState('')
  const [smsStatus, setSmsStatus] = useState('')

  // 카카오 알림톡 설정
  const [kakaoUserId, setKakaoUserId] = useState('')
  const [kakaoApiKey, setKakaoApiKey] = useState('')
  const [kakaoSenderKey, setKakaoSenderKey] = useState('')
  const [kakaoSender, setKakaoSender] = useState('')
  const [kakaoStatus, setKakaoStatus] = useState('')

  // Probe 상태
  const [probeData, setProbeData] = useState<Record<string, Record<string, Record<string, unknown>>>>({})
  const [probeLoading, setProbeLoading] = useState(false)

  // Claude AI API 설정
  const [claudeApiKey, setClaudeApiKey] = useState('')
  const [claudeModel, setClaudeModel] = useState('claude-sonnet-4-6')
  const [claudeStatus, setClaudeStatus] = useState('')
  const [aiFeatures, setAiFeatures] = useState<Record<string, boolean>>({ productName: true })

  // Gemini AI 설정 (이미지 변환 / AI태그)
  const [geminiApiKey, setGeminiApiKey] = useState('')
  const [geminiModel, setGeminiModel] = useState('gemini-2.5-flash')
  const [geminiStatus, setGeminiStatus] = useState('')


  // 모델 프리셋
  const [presets, setPresets] = useState<{ key: string; label: string; desc: string; image: string | null }[]>([])
  const [editingPreset, setEditingPreset] = useState<string | null>(null)
  const [editingDesc, setEditingDesc] = useState('')
  const [editingLabel, setEditingLabel] = useState('')
  const [regenerating, setRegenerating] = useState<string | null>(null)
  const [presetZoom, setPresetZoom] = useState<string | null>(null)

  // 금지어/삭제어 (전역)
  const [forbiddenText, setForbiddenText] = useState('')
  const [deletionText, setDeletionText] = useState('')
  const [initialForbiddenText, setInitialForbiddenText] = useState('')
  const [initialDeletionText, setInitialDeletionText] = useState('')
  const [optionDeletionText, setOptionDeletionText] = useState('')
  const [initialOptionDeletionText, setInitialOptionDeletionText] = useState('')
  const [wordsSaving, setWordsSaving] = useState(false)

  // 태그 금지어
  const [tagBanned, setTagBanned] = useState<{ rejected: string[]; brands: string[]; source_sites: string[] }>({ rejected: [], brands: [], source_sites: [] })

  // 환율 설정
  const [exchangeRates, setExchangeRates] = useState<ExchangeRateResponse>(EMPTY_EXCHANGE_RATES)
  const [exchangeStatus, setExchangeStatus] = useState('')
  const [exchangeSaving, setExchangeSaving] = useState(false)
 
  // Cloudflare R2 설정
  const [r2AccountId, setR2AccountId] = useState('')
  const [r2AccessKey, setR2AccessKey] = useState('')
  const [r2SecretKey, setR2SecretKey] = useState('')
  const [r2BucketName, setR2BucketName] = useState('')
  const [r2PublicUrl, setR2PublicUrl] = useState('')
  const [r2Status, setR2Status] = useState('')

  // 프록시 설정
  const [proxies, setProxies] = useState<ProxyConfigItem[]>([])
  const [proxyModalOpen, setProxyModalOpen] = useState(false)
  const [proxyEditIdx, setProxyEditIdx] = useState<number | null>(null)
  const [proxyForm, setProxyForm] = useState<ProxyConfigItem>({ name: '', url: '', purposes: [], enabled: true })
  const [proxyFields, setProxyFields] = useState({ username: '', password: '', ip: '', port: '' })
  const [proxyTesting, setProxyTesting] = useState<number | null>(null)
  const [proxySaving, setProxySaving] = useState(false)

  // URL ↔ 필드 변환
  const parseProxyUrl = (url: string) => {
    // http://user:pass@host:port
    const m = url.match(/^https?:\/\/([^:]+):([^@]+)@([^:]+):(\d+)$/)
    if (m) return { username: m[1], password: m[2], ip: m[3], port: m[4] }
    return { username: '', password: '', ip: '', port: '' }
  }
  const buildProxyUrl = (f: typeof proxyFields) =>
    f.ip ? `http://${f.username}:${f.password}@${f.ip}:${f.port}` : ''

  // 소싱처 계정 상태
  const [sourcingAccounts, setSourcingAccounts] = useState<SambaSourcingAccount[]>([])
  const [sourcingSites, setSourcingSites] = useState<{ id: string; name: string; group: string }[]>([])
  const [chromeProfiles, setChromeProfiles] = useState<ChromeProfile[]>([])
  const [chromeProfilesSyncing, setChromeProfilesSyncing] = useState(false)
  const [sourcingTab, setSourcingTab] = useState('MUSINSA')
  const [sourcingFormOpen, setSourcingFormOpen] = useState(false)
  const [sourcingEditId, setSourcingEditId] = useState<string | null>(null)
  const [sourcingForm, setSourcingForm] = useState({ site_name: 'MUSINSA', account_label: '', username: '', password: '', chrome_profile: '', memo: '' })
  const [balanceLoading, setBalanceLoading] = useState<Record<string, boolean>>({})
  const normalizedChromeProfiles = useMemo(() => {
    const seen = new Set<string>()
    return chromeProfiles.filter(profile => {
      const key = (profile.email || profile.directory || '').trim().toLowerCase()
      if (!key || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [chromeProfiles])

  const loadAccounts = useCallback(async () => {
    setAccountLoading(true)
    try { setAccounts(await accountApi.list()) } catch { /* ignore */ }
    setAccountLoading(false)
  }, [])

  // 스토어 연결 설정 로드
  // ※ 과거 버그: savedStoreData만 세팅하고 storeData는 빈 상태였음 → select UI는 첫 옵션이 시각적으로 보이지만 state는 ''라서
  //    저장 시 merge 로직이 select 필드값을 누락해 DB에 합배송 key 자체가 들어가지 않음 → 백엔드가 기본값 "Y"로 등록 (합배송 불가 UI와 불일치)
  //    → storeData도 함께 세팅 + 안전한 기본값이 명시된 select 필드(SAFE_SELECT_DEFAULTS)에 한해 초기값 주입해 일관성 확보
  const loadStoreSettings = useCallback(async () => {
    const loaded: Record<string, Record<string, string>> = {}
    const statuses: Record<string, string> = {}
    for (const market of STORE_MARKETS) {
      try {
        const data = await forbiddenApi.getSetting(`store_${market.key}`).catch(() => null) as Record<string, string> | null
        if (data && Object.keys(data).length > 0) {
          loaded[market.key] = data
          statuses[market.key] = '연결됨'
        }
      } catch { /* ignore */ }
    }
    // 안전한 기본값을 가진 select 필드에만 초기값 주입
    const withDefaults: Record<string, Record<string, string>> = {}
    for (const market of STORE_MARKETS) {
      const base = { ...(loaded[market.key] || {}) }
      for (const field of market.fields) {
        if (field.type === 'select' && field.name in SAFE_SELECT_DEFAULTS && !(field.name in base)) {
          base[field.name] = SAFE_SELECT_DEFAULTS[field.name]
        }
      }
      withDefaults[market.key] = base
    }
    setSavedStoreData(withDefaults)
    setStoreData(withDefaults)
    setStoreStatus(statuses)
  }, [])

  const updateStoreField = (marketKey: string, fieldName: string, value: string) => {
    setStoreData(prev => ({
      ...prev,
      [marketKey]: { ...(prev[marketKey] || {}), [fieldName]: value }
    }))
  }

  const saveStoreSettings = async (marketKey: string) => {
    try {
      // 기존 저장 데이터와 현재 입력 데이터 병합
      // select 필드에서 ''(설정안함)을 선택한 경우 해당 키 삭제
      const current = storeData[marketKey] || {}
      const marketCfgForMerge = STORE_MARKETS.find(m => m.key === marketKey)
      const selectFields = new Set(
        (marketCfgForMerge?.fields ?? []).filter(f => f.type === 'select').map(f => f.name)
      )
      const clearKeys = Object.entries(current)
        .filter(([k, v]) => v === '' && selectFields.has(k))
        .map(([k]) => k)
      const filtered = Object.fromEntries(Object.entries(current).filter(([, v]) => v !== ''))
      const merged = { ...(savedStoreData[marketKey] || {}), ...filtered }
      // select "설정안함" 선택 시 해당 키 삭제
      for (const k of clearKeys) delete merged[k]
      // 마스킹된 password 필드(****xxxx)가 있으면 savedStoreData 원본으로 복원
      const pwdFieldsForSave = new Set(
        (marketCfgForMerge?.fields ?? []).filter(f => f.type === 'password').map(f => f.name)
      )
      const savedOrig = savedStoreData[marketKey] || {}
      for (const field of pwdFieldsForSave) {
        if (merged[field]?.startsWith('****') && savedOrig[field]) {
          merged[field] = savedOrig[field]
        }
      }
      const data = merged
      await forbiddenApi.saveSetting(`store_${marketKey}`, data)
      const marketCfg = STORE_MARKETS.find(m => m.key === marketKey)
      const label = marketCfg?.label || marketKey

      // 계정 자동 생성/업데이트
      const sellerId = data.storeId || data.account || data.email || data.userId || data.vendorId || data.apiKey || ''
      const businessName = data.businessName || ''
      if (sellerId || businessName) {
        // API 인증정보를 additional_fields에 저장 (계정별 독립 인증)
        const { businessName: _bn, storeId: _si, maxCount: _mc, ...apiFields } = data
        const accountData: Partial<SambaMarketAccount> = {
          market_type: marketKey,
          market_name: label,
          account_label: `${businessName}${sellerId ? '-' + (sellerId.length > 16 ? sellerId.slice(0, 8) + '...' : sellerId) : ''}`.replace(/^-|-$/g, '') || marketKey,
          seller_id: sellerId,
          business_name: businessName,
          is_active: true,
          additional_fields: apiFields, // clientId, clientSecret 등 API 인증정보
        }

        if (editingAccountId) {
          // 수정 모드: 해당 계정 업데이트
          await accountApi.update(editingAccountId, accountData)
          setEditingAccountId(null)
        } else {
          // 신규: 동일 seller_id 계정이 있으면 업데이트, 없으면 생성
          const existing = accounts.find(a => a.market_type === marketKey && a.seller_id === sellerId)
          if (existing) {
            await accountApi.update(existing.id, accountData)
          } else {
            await accountApi.create(accountData)
          }
        }
        await loadAccounts()
      }
      // 저장 후 savedStoreData 갱신 + 폼에 저장된 값 유지
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
      setStoreData(prev => ({ ...prev, [marketKey]: { ...data } }))
      setStoreStatus(prev => ({ ...prev, [marketKey]: '연결됨' }))
      setEditingAccountId(null)

      showAlert(`${label} 설정이 저장되었습니다.`, 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  const testStoreAuth = async (marketKey: string) => {
    const data = storeData[marketKey] || {}
    const hasKey = Object.values(data).some(v => v && v.length > 0)
    if (!hasKey) {
      setStoreStatus(prev => ({ ...prev, [marketKey]: '필드를 입력해주세요' }))
      return
    }
    setStoreStatus(prev => ({ ...prev, [marketKey]: '인증 확인 중...' }))
    try {
      // 마스킹된 password 필드(****xxxx)가 있으면 savedStoreData 원본으로 복원
      const marketCfg = STORE_MARKETS.find(m => m.key === marketKey)
      const pwdFields = new Set(
        (marketCfg?.fields ?? []).filter(f => f.type === 'password').map(f => f.name)
      )
      const saved = savedStoreData[marketKey] || {}
      const safeData = { ...data }
      for (const field of pwdFields) {
        if (safeData[field]?.startsWith('****') && saved[field]) {
          safeData[field] = saved[field]
        }
      }
      // 먼저 설정 저장
      await forbiddenApi.saveSetting(`store_${marketKey}`, safeData)
      setSavedStoreData(prev => ({ ...prev, [marketKey]: { ...safeData } }))
      // 마켓별 인증 테스트
      let result: { success: boolean; message: string }
      if (marketKey === 'smartstore') {
        result = await proxyApi.smartstoreAuthTest()
      } else if (marketKey === '11st') {
        result = await proxyApi.elevenstAuthTest()
      } else if (marketKey === 'coupang') {
        result = await proxyApi.coupangAuthTest()
      } else if (marketKey === 'lotteon') {
        const lotteonResult = await proxyApi.lotteonAuthTest()
        result = lotteonResult
        // 인증 성공 시 배송인프라 값을 폼에 자동 반영
        if (lotteonResult.success && lotteonResult.data) {
          const infra = lotteonResult.data
          const updated = { ...data }
          if (infra.dvCstPolNo && !data.dvCstPolNo) updated.dvCstPolNo = infra.dvCstPolNo
          if (infra.owhpNo && !data.owhpNo) updated.owhpNo = infra.owhpNo
          if (infra.rtrpNo && !data.rtrpNo) updated.rtrpNo = infra.rtrpNo
          setStoreData(prev => ({ ...prev, [marketKey]: updated }))
        }
      } else if (marketKey === 'ssg') {
        result = await proxyApi.ssgAuthTest()
      } else if (marketKey === 'gsshop') {
        result = await proxyApi.gsshopAuthTest()
      } else {
        result = await proxyApi.marketAuthTest(marketKey)
      }
      if (result.success) {
        setStoreStatus(prev => ({ ...prev, [marketKey]: `✓ ${result.message}` }))
        showAlert(result.message, 'success')
      } else {
        setStoreStatus(prev => ({ ...prev, [marketKey]: `✗ ${result.message}` }))
        showAlert(result.message, 'error')
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '알 수 없는 오류'
      const displayMsg = msg === 'Failed to fetch'
        ? '백엔드 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요.'
        : `인증 테스트 실패: ${msg}`
      setStoreStatus(prev => ({ ...prev, [marketKey]: '연결 실패' }))
      showAlert(displayMsg, 'error')
    }
  }

  // 설정 로드 (SMS/카카오/Claude)
  const loadExchangeRates = useCallback(async (forceRefresh = false) => {
    try {
      const data = await forbiddenApi.getExchangeRates(forceRefresh)
      setExchangeRates(data as ExchangeRateResponse)
      if (forceRefresh) setExchangeStatus('최신 환율을 불러왔습니다.')
    } catch {
      setExchangeRates(prev => prev || EMPTY_EXCHANGE_RATES)
      setExchangeStatus('환율 정보를 불러오지 못했습니다. 저장된 고정/조정 환율만 입력할 수 있습니다.')
      if (forceRefresh) showAlert('환율 정보를 불러오지 못했습니다.', 'error')
    }
  }, [])

  const updateExchangeField = (
    code: ExchangeCurrencyCode,
    field: 'adjustment' | 'fixedRate',
    value: string,
  ) => {
    setExchangeRates(prev => {
      const multiplier = getExchangeDisplayMultiplier(code)
      const numericValue = (parseNum(value) || 0) / multiplier
      const current = prev.currencies[code]
      const nextAdjustment = field === 'adjustment' ? numericValue : current.adjustment
      const nextFixedRate = field === 'fixedRate' ? numericValue : current.fixedRate
      const useFixed = nextFixedRate > 0
      return {
        ...prev,
        currencies: {
          ...prev.currencies,
          [code]: {
            ...current,
            [field]: numericValue,
            adjustment: nextAdjustment,
            fixedRate: nextFixedRate,
            effectiveRate: useFixed
              ? nextFixedRate
              : Math.max(current.baseRate + nextAdjustment, 0),
            useFixed,
          },
        },
      }
    })
  }

  const saveExchangeSettings = async () => {
    setExchangeSaving(true)
    try {
      const payload = {
        currencies: Object.fromEntries(
          EXCHANGE_CURRENCY_ORDER.map((code) => [
            code,
            {
              adjustment: exchangeRates.currencies[code].adjustment || 0,
              fixedRate: exchangeRates.currencies[code].fixedRate || 0,
            },
          ]),
        ),
      }
      await forbiddenApi.saveSetting('exchange_rates', payload)
      setExchangeStatus('환율 설정이 저장되었습니다.')
      await loadExchangeRates(true)
      showAlert('환율 설정이 저장되었습니다.', 'success')
    } catch {
      setExchangeStatus('환율 설정 저장에 실패했습니다.')
      showAlert('환율 설정 저장에 실패했습니다.', 'error')
    } finally {
      setExchangeSaving(false)
    }
  }

  const loadExternalSettings = useCallback(async () => {
    try {
      const sms = await forbiddenApi.getSetting('aligo_sms').catch(() => null) as Record<string, string> | null
      if (sms) {
        setSmsUserId(sms.userId || '')
        setSmsApiKey(sms.apiKey || '')
        setSmsSender(sms.sender || '')
        if (sms.apiKey) setSmsStatus('저장됨')
      }
    } catch { /* ignore */ }
    try {
      const kakao = await forbiddenApi.getSetting('aligo_kakao').catch(() => null) as Record<string, string> | null
      if (kakao) {
        setKakaoUserId(kakao.userId || '')
        setKakaoApiKey(kakao.apiKey || '')
        setKakaoSenderKey(kakao.senderKey || '')
        setKakaoSender(kakao.sender || '')
        if (kakao.apiKey) setKakaoStatus('저장됨')
      }
    } catch { /* ignore */ }
    try {
      const claude = await forbiddenApi.getSetting('claude').catch(() => null) as Record<string, unknown> | null
      if (claude) {
        setClaudeApiKey(String(claude.apiKey || ''))
        setClaudeModel(String(claude.model || 'claude-sonnet-4-6'))
        if (claude.apiKey) setClaudeStatus('저장됨')
        if (claude.aiFeatures && typeof claude.aiFeatures === 'object') {
          setAiFeatures(claude.aiFeatures as Record<string, boolean>)
        }
      }
    } catch { /* ignore */ }
    try {
      const gm = await forbiddenApi.getSetting('gemini').catch(() => null) as Record<string, unknown> | null
      if (gm) {
        setGeminiApiKey(String(gm.apiKey || ''))
        setGeminiModel(String(gm.model || 'gemini-2.5-flash'))
        if (gm.apiKey) setGeminiStatus('저장됨')
      }
      // fal_ai: 미사용 (추후 구현)
    } catch { /* ignore */ }
    try {
      const r2 = await forbiddenApi.getSetting('cloudflare_r2').catch(() => null) as Record<string, unknown> | null
      if (r2) {
        setR2AccountId(String(r2.accountId || ''))
        setR2AccessKey(String(r2.accessKey || ''))
        setR2SecretKey(String(r2.secretKey || ''))
        setR2BucketName(String(r2.bucketName || ''))
        setR2PublicUrl(String(r2.publicUrl || ''))
        if (r2.accessKey) setR2Status('저장됨')
      }
    } catch { /* ignore */ }
  }, [])

  const loadSourcingAccounts = useCallback(async () => {
    try {
      const [accounts, sites, profiles] = await Promise.all([
        sourcingAccountApi.list(),
        sourcingAccountApi.getSites(),
        sourcingAccountApi.getChromeProfiles(),
      ])
      setSourcingAccounts(accounts)
      setSourcingSites(sites)
      setChromeProfiles(profiles)
    } catch { /* ignore */ }
  }, [])

  const handleSyncChromeProfiles = async () => {
    setChromeProfilesSyncing(true)
    try {
      await sourcingAccountApi.requestChromeProfileSync()

      let profiles: ChromeProfile[] = []
      for (let i = 0; i < 12; i++) {
        await new Promise(resolve => setTimeout(resolve, 2500))
        profiles = await sourcingAccountApi.getChromeProfiles()
        setChromeProfiles(profiles)
        if (profiles.length > 0) break
      }

      if (profiles.length > 0) {
        showAlert(`크롬 프로필 ${profiles.length}개를 동기화했습니다.`, 'success')
      } else {
        showAlert('동기화 요청은 보냈지만 프로필이 아직 없습니다. 확장앱 로그인 상태를 확인하세요.', 'error')
      }
    } catch (err) {
      showAlert(err instanceof Error ? err.message : '크롬 프로필 동기화 실패', 'error')
    }
    setChromeProfilesSyncing(false)
  }

  // 프록시 설정 로드
  const loadProxies = useCallback(async () => {
    try {
      const data = await proxyConfigApi.list()
      if (Array.isArray(data)) setProxies(data)
    } catch { /* ignore */ }
  }, [])

  const saveProxies = async (items: ProxyConfigItem[], silent?: boolean) => {
    setProxySaving(true)
    try {
      await proxyConfigApi.save(items)
      setProxies(items)
      if (!silent) showAlert('프록시 설정이 저장되었습니다.', 'success')
    } catch {
      if (!silent) showAlert('프록시 저장 실패', 'error')
    }
    setProxySaving(false)
  }

  const testProxy = async (idx: number) => {
    const p = proxies[idx]
    if (!p.url) {
      // 메인 IP는 httpbin으로 직접 테스트
      setProxyTesting(idx)
      try {
        const res = await fetch('https://httpbin.org/ip').then(r => r.json())
        showAlert(`메인 IP 확인: ${res.origin}`, 'success')
      } catch { showAlert('메인 IP 테스트 실패', 'error') }
      setProxyTesting(null)
      return
    }
    setProxyTesting(idx)
    try {
      const res = await proxyConfigApi.test(p.url)
      if (res.success) {
        showAlert(`연결 성공 — 외부 IP: ${res.ip}`, 'success')
      } else {
        showAlert(`연결 실패: ${res.message}`, 'error')
      }
    } catch (e) {
      showAlert(`테스트 오류: ${e instanceof Error ? e.message : '오류'}`, 'error')
    }
    setProxyTesting(null)
  }

  const openProxyAdd = () => {
    setProxyEditIdx(null)
    setProxyForm({ name: '', url: '', purposes: [], enabled: true })
    setProxyFields({ username: '', password: '', ip: '', port: '' })
    setProxyModalOpen(true)
  }

  const openProxyEdit = (idx: number) => {
    setProxyEditIdx(idx)
    setProxyForm({ ...proxies[idx], purposes: [...proxies[idx].purposes] })
    setProxyFields(parseProxyUrl(proxies[idx].url))
    setProxyModalOpen(true)
  }

  const handleProxySave = async () => {
    if (!proxyForm.name.trim()) {
      showAlert('이름을 입력하세요.', 'error')
      return
    }
    if (proxyForm.purposes.length === 0) {
      showAlert('용도를 1개 이상 선택하세요.', 'error')
      return
    }
    // 필드에서 URL 조합 (메인 IP는 빈값)
    const assembledUrl = buildProxyUrl(proxyFields)
    const formWithUrl = { ...proxyForm, url: assembledUrl }
    const updated = [...proxies]
    if (proxyEditIdx !== null) {
      updated[proxyEditIdx] = formWithUrl
    } else {
      updated.push(formWithUrl)
    }
    await saveProxies(updated)
    setProxyModalOpen(false)
  }

  const handleProxyDelete = async (idx: number) => {
    if (!await showConfirm(`"${proxies[idx].name}" 프록시를 삭제하시겠습니까?`)) return
    const updated = proxies.filter((_, i) => i !== idx)
    await saveProxies(updated)
  }

  const handleProxyToggle = async (idx: number) => {
    const updated = [...proxies]
    updated[idx] = { ...updated[idx], enabled: !updated[idx].enabled }
    await saveProxies(updated)
  }

  const toggleProxyPurpose = (purpose: ProxyConfigItem['purposes'][number]) => {
    setProxyForm(prev => ({
      ...prev,
      purposes: prev.purposes.includes(purpose)
        ? prev.purposes.filter(p => p !== purpose)
        : [...prev.purposes, purpose],
    }))
  }

  useEffect(() => {
    loadAccounts(); loadSourcingAccounts(); loadProxies()
    tenantApi.getMyUsage().then(setTenantUsage).catch(() => {})
  }, [loadAccounts, loadSourcingAccounts, loadProxies])

  const loadProbeStatus = useCallback(async () => {
    try {
      const data = await collectorApi.probeStatus() as Record<string, Record<string, Record<string, unknown>>>
      if (data) setProbeData(data)
    } catch { /* ignore */ }
  }, [])

  const runProbe = async () => {
    setProbeLoading(true)
    try {
      const data = await collectorApi.probeRun() as Record<string, Record<string, Record<string, unknown>>>
      if (data) setProbeData(data)
      showAlert('헬스체크 완료', 'success')
    } catch (e) {
      showAlert(`헬스체크 실패: ${e instanceof Error ? e.message : '오류'}`, 'error')
    }
    setProbeLoading(false)
  }

  useEffect(() => { loadExchangeRates(); loadExternalSettings(); loadStoreSettings(); loadProbeStatus() }, [loadExchangeRates, loadExternalSettings, loadStoreSettings, loadProbeStatus])

  // SSG 탭 진입 시 배송비/주소 옵션 자동 로드
  useEffect(() => {
    if (storeTab !== 'ssg') return
    if (ssgShippingOptions.length > 0 || ssgAddrOptions.length > 0) return
    const ssgData = savedStoreData['ssg'] || storeData['ssg'] || {}
    if (!ssgData.apiKey) return
    proxyApi.ssgShippingPolicies().then(res => {
      if (!res.success || !res.policies?.length) return
      const opts = res.policies.map((p: { shppcstId: string; feeAmt: number; prpayCodDivNm: string; shppcstAplUnitNm: string; divCd: number }) => {
        const fee = p.feeAmt ? `${fmtNum(Number(p.feeAmt))}원` : '무료'
        const parts = [p.shppcstId, fee]
        if (p.prpayCodDivNm) parts.push(p.prpayCodDivNm)
        if (p.shppcstAplUnitNm) parts.push(p.shppcstAplUnitNm)
        return { value: p.shppcstId, label: parts.join(' / '), divCd: p.divCd }
      })
      setSsgShippingOptions(opts)
    }).catch(() => {})
    proxyApi.ssgAddresses().then(res => {
      if (!res.success || !res.addresses?.length) return
      setSsgAddrOptions(res.addresses.map((a: { grpAddrId: string; doroAddrId?: string; addrNm: string; bascAddr: string }) => ({
        value: a.doroAddrId || a.grpAddrId,
        label: `${a.addrNm}${a.bascAddr ? ` (${a.bascAddr})` : ''}`,
      })))
    }).catch(() => {})
  }, [storeTab, savedStoreData, storeData, ssgShippingOptions.length, ssgAddrOptions.length])

  // 금지어/삭제어 + 태그 금지어 로드
  useEffect(() => {
    forbiddenApi.listWords().then((words: { id: string; word: string; type: string }[]) => {
      const dedupe = (arr: string[]) => [...new Set(arr.map(w => w.trim()).filter(Boolean))]
      const ft = dedupe(words.filter(w => w.type === 'forbidden').map(w => w.word)).join('; ')
      const dt = dedupe(words.filter(w => w.type === 'deletion').map(w => w.word)).join('; ')
      const ot = dedupe(words.filter(w => w.type === 'option_deletion').map(w => w.word)).join('; ')
      setForbiddenText(ft)
      setDeletionText(dt)
      setOptionDeletionText(ot)
      setInitialForbiddenText(ft)
      setInitialDeletionText(dt)
      setInitialOptionDeletionText(ot)
    }).catch(() => {})
    forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})
  }, [])

  const handleAccountToggle = async (id: string) => { await accountApi.toggle(id); loadAccounts() }
  const handleAccountDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    await accountApi.delete(id); loadAccounts()
  }

  // SMS 설정 저장
  const saveSmsSettings = async () => {
    try {
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      setSmsStatus('저장됨')
      showAlert('SMS 설정이 저장되었습니다.', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // SMS Key 테스트 - 설정 저장 후 알리고 API로 잔여건수 조회
  const testSmsKey = async () => {
    if (!smsUserId || !smsApiKey) {
      showAlert('Identifier와 API Key를 먼저 입력하세요.', 'error')
      return
    }
    setSmsStatus('확인 중...')
    try {
      // 먼저 설정 저장
      await forbiddenApi.saveSetting('aligo_sms', { userId: smsUserId, apiKey: smsApiKey, sender: smsSender })
      // 알리고 잔여건수 조회
      const result = await proxyApi.aligoRemain()
      if (result.success) {
        setSmsStatus(`인증 완료 (SMS: ${result.SMS_CNT}건, LMS: ${result.LMS_CNT}건, MMS: ${result.MMS_CNT}건)`)
        showAlert(`인증 완료 — SMS: ${result.SMS_CNT}건, LMS: ${result.LMS_CNT}건, MMS: ${result.MMS_CNT}건`, 'success')
      } else {
        setSmsStatus('인증 실패')
        showAlert(result.message || '알리고 API 인증 실패', 'error')
      }
    } catch (e) {
      setSmsStatus('연결 실패')
      showAlert(`알리고 API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // 카카오 알림톡 저장
  const saveKakaoSettings = async () => {
    try {
      await forbiddenApi.saveSetting('aligo_kakao', { userId: kakaoUserId, apiKey: kakaoApiKey, senderKey: kakaoSenderKey, sender: kakaoSender })
      setKakaoStatus('저장됨')
      showAlert('카카오 알림톡 설정이 저장되었습니다.', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // 카카오 Key 테스트
  const testKakaoKey = async () => {
    if (!kakaoUserId || !kakaoApiKey) {
      showAlert('Identifier와 API Key를 먼저 입력하세요.', 'error')
      return
    }
    setKakaoStatus('확인 중...')
    if (kakaoApiKey.length > 5) {
      setKakaoStatus('Key 형식 유효')
      showAlert('API Key 형식이 유효합니다. 실제 연결은 알림톡 발송 시 확인됩니다.', 'success')
    } else {
      setKakaoStatus('Key 형식 오류')
      showAlert('API Key가 너무 짧습니다.', 'error')
    }
  }

  // Claude API 저장
  const saveClaudeSettings = async () => {
    if (!claudeApiKey) {
      showAlert('API Key를 입력해주세요', 'error')
      return
    }
    try {
      await forbiddenApi.saveSetting('claude', { apiKey: claudeApiKey, model: claudeModel, aiFeatures, updatedAt: new Date().toISOString() })
      setClaudeStatus(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Claude API 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // Claude API 테스트 — 실제 API 호출로 검증
  const testClaudeApi = async () => {
    if (!claudeApiKey) {
      showAlert('API Key를 먼저 입력해주세요', 'error')
      return
    }
    if (!claudeApiKey.startsWith('sk-ant-')) {
      setClaudeStatus('유효하지 않은 API Key 형식 (sk-ant- 로 시작해야 합니다)')
      return
    }
    setClaudeStatus('API 연결 확인 중...')
    try {
      // 먼저 설정 저장
      await forbiddenApi.saveSetting('claude', { apiKey: claudeApiKey, model: claudeModel, aiFeatures, updatedAt: new Date().toISOString() })
      // 실제 API 호출 테스트
      const result = await proxyApi.claudeTest()
      if (result.success) {
        setClaudeStatus(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setClaudeStatus(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setClaudeStatus('연결 실패')
      showAlert(`Claude API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  const toggleAiFeature = (key: string) => {
    setAiFeatures(prev => ({ ...prev, [key]: !prev[key] }))
  }

  // Gemini API 테스트
  const testGeminiApi = async () => {
    if (!geminiApiKey) { showAlert('API Key를 먼저 입력해주세요', 'error'); return }
    setGeminiStatus('API 연결 확인 중...')
    try {
      await forbiddenApi.saveSetting('gemini', { apiKey: geminiApiKey, model: geminiModel, updatedAt: new Date().toISOString() })
      const result = await proxyApi.geminiTest()
      if (result.success) {
        setGeminiStatus(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setGeminiStatus(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setGeminiStatus('연결 실패')
      showAlert(`Gemini API 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // Gemini AI 저장 (이미지 변환 / AI태그)
  const saveGeminiSettings = async () => {
    if (!geminiApiKey) { showAlert('API Key를 입력해주세요', 'error'); return }
    try {
      await forbiddenApi.saveSetting('gemini', { apiKey: geminiApiKey, model: geminiModel, updatedAt: new Date().toISOString() })
      setGeminiStatus(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Gemini 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }


  // 프리셋 로드
  const loadPresets = useCallback(async () => {
    try {
      const res = await proxyApi.listPresets()
      if (res.success) setPresets(res.presets)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { loadPresets() }, [loadPresets])

  // 프리셋 텍스트만 저장 (이미지 재생성 없이)
  const handleSavePreset = async (key: string, label: string, desc: string) => {
    try {
      const res = await proxyApi.regeneratePreset(key, desc, label, true)
      if (res.success) {
        showAlert('프리셋 저장 완료', 'success')
        setEditingPreset(null)
        await loadPresets()
      } else showAlert(res.message, 'error')
    } catch (e) {
      showAlert(`저장 실패: ${e instanceof Error ? e.message : ''}`, 'error')
    }
  }

  // 프리셋 재생성
  const handleRegeneratePreset = async (key: string, desc?: string, label?: string) => {
    setRegenerating(key)
    try {
      const res = await proxyApi.regeneratePreset(key, desc, label)
      if (res.success) {
        showAlert(res.message, 'success')
        setEditingPreset(null)
        await loadPresets()
      } else showAlert(res.message, 'error')
    } catch (e) {
      showAlert(`재생성 실패: ${e instanceof Error ? e.message : ''}`, 'error')
    } finally { setRegenerating(null) }
  }

  // Cloudflare R2 저장
  const saveR2Settings = async () => {
    try {
      await forbiddenApi.saveSetting('cloudflare_r2', {
        accountId: r2AccountId, accessKey: r2AccessKey, secretKey: r2SecretKey,
        bucketName: r2BucketName, publicUrl: r2PublicUrl, updatedAt: new Date().toISOString(),
      })
      setR2Status(`저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})`)
      showAlert('Cloudflare R2 설정이 저장되었습니다', 'success')
    } catch { showAlert('저장 실패', 'error') }
  }

  // Cloudflare R2 테스트
  const testR2 = async () => {
    if (!r2AccessKey || !r2SecretKey || !r2BucketName) {
      showAlert('Access Key, Secret Key, Bucket Name을 입력해주세요', 'error')
      return
    }
    setR2Status('연결 확인 중...')
    try {
      await forbiddenApi.saveSetting('cloudflare_r2', {
        accountId: r2AccountId, accessKey: r2AccessKey, secretKey: r2SecretKey,
        bucketName: r2BucketName, publicUrl: r2PublicUrl, updatedAt: new Date().toISOString(),
      })
      const result = await proxyApi.r2Test()
      if (result.success) {
        setR2Status(`✓ ${result.message}`)
        showAlert(result.message, 'success')
      } else {
        setR2Status(`✗ ${result.message}`)
        showAlert(result.message, 'error')
      }
    } catch (e) {
      setR2Status('연결 실패')
      showAlert(`R2 연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  // ── 소싱처 계정 핸들러 ──
  const handleSourcingSave = async () => {
    if (!sourcingForm.account_label || !sourcingForm.username || !sourcingForm.password) {
      showAlert('별칭, 아이디, 비밀번호는 필수입니다', 'error')
      return
    }
    try {
      if (sourcingEditId) {
        await sourcingAccountApi.update(sourcingEditId, sourcingForm)
      } else {
        await sourcingAccountApi.create({ ...sourcingForm, site_name: sourcingTab })
      }
      setSourcingEditId(null)
      setSourcingForm({ site_name: sourcingTab, account_label: '', username: '', password: '', chrome_profile: '', memo: '' })
      loadSourcingAccounts()
    } catch (err) { showAlert(err instanceof Error ? err.message : '저장 실패', 'error') }
  }

  const handleSourcingDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    await sourcingAccountApi.delete(id)
    loadSourcingAccounts()
  }

  const handleSourcingEdit = (a: SambaSourcingAccount) => {
    setSourcingEditId(a.id)
    setSourcingForm({
      site_name: a.site_name,
      account_label: a.account_label,
      username: a.username,
      password: a.password,
      chrome_profile: a.chrome_profile || '',
      memo: a.memo || '',
    })
  }

  const handleFetchBalance = async (id: string) => {
    setBalanceLoading(prev => ({ ...prev, [id]: true }))
    try {
      await loadSourcingAccounts()
      showAlert('잔액 갱신 완료 (확장앱에서 수집된 데이터)', 'success')
    } catch (err) { showAlert(err instanceof Error ? err.message : '잔액 조회 실패', 'error') }
    setBalanceLoading(prev => ({ ...prev, [id]: false }))
  }

  const handleFetchAllBalances = async () => {
    try {
      await sourcingAccountApi.requestBalanceCheck()
      showAlert('잔액 체크 요청 완료 — 확장앱이 30초 내 자동 수집합니다', 'success')
      // 15초 후 자동 새로고침
      setTimeout(() => loadSourcingAccounts(), 15000)
    } catch (err) { showAlert(err instanceof Error ? err.message : '잔액 체크 요청 실패', 'error') }
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 플랜 / 사용량 */}
      {tenantUsage?.usage && (() => {
        const PLAN_LABELS: Record<string, string> = { free: 'Free', basic: 'Basic', pro: 'Pro', enterprise: 'Enterprise' }
        const PLAN_COLORS: Record<string, string> = { free: '#666', basic: '#4C9AFF', pro: '#FF8C00', enterprise: '#A855F7' }
        const planColor = PLAN_COLORS[tenantUsage.plan] || '#666'
        const items = [
          { label: '상품', ...tenantUsage.usage.products },
          { label: '마켓', ...tenantUsage.usage.markets },
          { label: '소싱', ...tenantUsage.usage.sourcing },
        ]
        return (
          <div style={{ ...card, padding: '1.25rem', marginBottom: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
              <span style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>플랜</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, color: planColor, background: `${planColor}18`, padding: '0.2rem 0.6rem', borderRadius: '4px' }}>
                {PLAN_LABELS[tenantUsage.plan] || tenantUsage.plan}
              </span>
              {tenantUsage.autotune_enabled && (
                <span style={{ fontSize: '0.6875rem', color: '#22C55E', background: '#22C55E18', padding: '0.15rem 0.5rem', borderRadius: '4px' }}>오토튠 ON</span>
              )}
              {tenantUsage.subscription_end && (
                <span style={{ fontSize: '0.6875rem', color: '#666', marginLeft: 'auto' }}>
                  만료: {new Date(tenantUsage.subscription_end).toLocaleDateString('ko-KR')}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: '1.5rem' }}>
              {items.map(({ label, current, max }) => {
                const isUnlimited = max === -1
                const pct = isUnlimited ? 0 : Math.min((current / max) * 100, 100)
                const barColor = pct >= 90 ? '#EF4444' : pct >= 70 ? '#F59E0B' : '#4C9AFF'
                return (
                  <div key={label} style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#999', marginBottom: '0.35rem' }}>
                      <span>{label}</span>
                      <span>{fmtNum(current)} / {isUnlimited ? '무제한' : fmtNum(max)}</span>
                    </div>
                    <div style={{ height: '6px', background: '#1A1A1A', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ width: isUnlimited ? '0%' : `${pct}%`, height: '100%', background: barColor, borderRadius: '3px', transition: 'width 0.3s' }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      
        <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.35rem' }}>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>환율 설정</div>
            <span style={{ fontSize: '0.75rem', color: '#888' }}>
              해외 소싱가를 원화 계산가로 바꿀 때 사용됩니다.
            </span>
            <button
              onClick={() => loadExchangeRates(true)}
              style={{ marginLeft: 'auto', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', padding: '0.35rem 0.8rem', borderRadius: '6px', fontSize: '0.78rem', cursor: 'pointer' }}
            >
              최신환율 새로고침
            </button>
            <button
              onClick={saveExchangeSettings}
              disabled={exchangeSaving}
              style={{ background: exchangeSaving ? '#333' : 'rgba(255,140,0,0.16)', border: '1px solid rgba(255,140,0,0.35)', color: exchangeSaving ? '#777' : '#FF8C00', padding: '0.35rem 0.8rem', borderRadius: '6px', fontSize: '0.78rem', cursor: exchangeSaving ? 'not-allowed' : 'pointer' }}
            >
              환율 저장
            </button>
          </div>
          <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1rem' }}>
            + / - 조정은 기준 환율에 가감되고, 고정 환율을 입력하면 해당 통화는 고정값이 우선 적용됩니다.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.875rem' }}>
            {EXCHANGE_CURRENCY_ORDER.map((code) => {
              const item = exchangeRates.currencies[code]
              const multiplier = getExchangeDisplayMultiplier(code)
              const unitLabel = code === 'JPY' ? '100' : '1'
              return (
                <div key={code} style={{ background: '#161616', border: '1px solid #2D2D2D', borderRadius: '10px', padding: '0.9rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                    <div>
                      <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#E5E5E5' }}>{item.label}</div>
                      <div style={{ fontSize: '0.72rem', color: '#777' }}>{code} {unitLabel} = ₩{fmtNum(Math.round(item.effectiveRate * multiplier))}</div>
                    </div>
                    <span style={{ fontSize: '0.68rem', color: item.useFixed ? '#FF8C00' : '#4C9AFF' }}>
                      {item.useFixed ? '고정 적용' : '실시간 적용'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                    <div>
                      <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>기준 환율</div>
                      <div style={{ ...inputStyle, color: '#A3A3A3' }}>₩{fmtNum(Math.round(item.baseRate * multiplier))}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>+ / - 조정</div>
                      <NumInput
                        style={{ width: '100%' }}
                        value={String((item.adjustment || 0) * multiplier)}
                        onChange={(value) => updateExchangeField(code, 'adjustment', value)}
                        placeholder="0"
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>고정 환율</div>
                      <NumInput
                        style={{ width: '100%' }}
                        value={item.fixedRate ? String(item.fixedRate * multiplier) : ''}
                        onChange={(value) => updateExchangeField(code, 'fixedRate', value)}
                        placeholder="비워두면 실시간"
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: '0.72rem', color: '#777', marginBottom: '0.25rem' }}>계산 환율</div>
                      <div style={{ ...inputStyle, color: '#FF8C00', fontWeight: 700 }}>₩{fmtNum(Math.round(item.effectiveRate * multiplier))}</div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginTop: '0.9rem', fontSize: '0.75rem', color: '#666' }}>
            <span>통화 매핑: Amazon/eBay/Shopify=USD, Rakuten/BUYMA=JPY, Poizon/Zoom=CNY</span>
            <span>{exchangeStatus || (exchangeRates.publishedAt ? `기준 시각: ${String(exchangeRates.publishedAt)}` : '')}</span>
          </div>
        </div>


      {/* 마켓 계정 */}
          {/* 스토어 연결 */}
          <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>스토어 연결</div>
            <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1.25rem' }}>API 연결 및 계정 설정을 관리합니다</p>

            {/* 마켓 탭바 — 국내/해외 구분 */}
            {(() => {
              const domestic = ['smartstore', 'coupang', '11st', 'gmarket', 'auction', 'lotteon', 'toss', 'ssg', 'gsshop', 'lottehome', 'homeand', 'hmall', 'musinsa', 'kream', 'playauto', 'cafe24']
              const overseas = ['amazon', 'ebay', 'rakuten', 'qoo10', 'lazada', 'shopee', 'buyma', 'shopify', 'zoom', 'poison']
              const domesticMarkets = STORE_MARKETS.filter(m => domestic.includes(m.key))
              const overseasMarkets = STORE_MARKETS.filter(m => overseas.includes(m.key))
              const renderTab = (m: typeof STORE_MARKETS[number]) => (
                <button
                  key={m.key}
                  onClick={() => {
                    // 이전 탭 + 전환 대상 탭 모두 storeData 초기화 (잔류값 방지)
                    setStoreData(prev => {
                      const next = { ...prev }
                      delete next[storeTab]  // 이전 탭 데이터 제거
                      delete next[m.key]     // 전환 대상 탭 데이터 제거
                      return next
                    })
                    setStoreTab(m.key)
                    setEditingAccountId(null)
                  }}
                  style={{
                    padding: '0.5rem 0.75rem', background: 'none', border: 'none',
                    borderBottom: storeTab === m.key ? '2px solid #FF8C00' : '2px solid transparent',
                    color: storeTab === m.key ? '#FF8C00' : '#666',
                    fontSize: '0.8125rem', fontWeight: storeTab === m.key ? 600 : 400,
                    cursor: 'pointer', marginBottom: '-1px', whiteSpace: 'nowrap',
                  }}
                >
                  {m.label}
                </button>
              )
              return (
                <div style={{ borderBottom: '1px solid #2D2D2D', marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0 }}>
                    <span style={{ fontSize: '0.68rem', color: '#FF8C00', fontWeight: 600, padding: '0.5rem 0.5rem 0.5rem 0', whiteSpace: 'nowrap' }}>국내</span>
                    {domesticMarkets.map(renderTab)}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0 }}>
                    <span style={{ fontSize: '0.68rem', color: '#4C9AFF', fontWeight: 600, padding: '0.5rem 0.5rem 0.5rem 0', whiteSpace: 'nowrap' }}>해외</span>
                    {overseasMarkets.map(renderTab)}
                  </div>
                </div>
              )
            })()}

            {/* 마켓별 설정 폼 + 연결계정 */}
            {STORE_MARKETS.filter(m => m.key === storeTab).map(market => (
              <div key={market.key} style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>
              <div style={{ flex: 1, maxWidth: '560px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                  <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5' }}>{market.label} 설정</span>
                  {editingAccountId && (
                    <>
                      <span style={{ fontSize: '0.75rem', color: '#FF8C00', fontWeight: 600 }}>
                        ({accounts.find(a => a.id === editingAccountId)?.account_label} 수정중)
                      </span>
                      <button
                        onClick={() => {
                          setEditingAccountId(null)
                          setStoreData(prev => { const next = { ...prev }; delete next[market.key]; return next })
                        }}
                        style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer' }}
                      >취소</button>
                    </>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {market.fields.map(field => field.type === 'divider' ? (
                    <div key={field.name} style={{ borderTop: '1px solid #2D2D2D', paddingTop: '0.75rem', marginTop: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#FFB84D' }}>{field.label}</span>
                      {market.key === 'ssg' && field.name === '_divider_shipping_code' && (
                        <button
                          onClick={async () => {
                            try {
                              // 현재 입력된 API Key로 먼저 설정 저장
                              const data = storeData['ssg'] || savedStoreData['ssg'] || {}
                              if (!data.apiKey) {
                                showAlert('API KEY를 먼저 입력하세요.', 'error')
                                return
                              }
                              await forbiddenApi.saveSetting('store_ssg', data)
                              // 배송비정책 조회
                              const shipRes = await proxyApi.ssgShippingPolicies()
                              if (shipRes.success && shipRes.policies?.length) {
                                setSsgShippingOptions(shipRes.policies.map((p: { shppcstId: string; feeAmt: number; prpayCodDivNm: string; shppcstAplUnitNm: string; divCd: number }) => {
                                  const fee = p.feeAmt ? `${fmtNum(Number(p.feeAmt))}원` : '무료'
                                  const parts = [p.shppcstId, fee]
                                  if (p.prpayCodDivNm) parts.push(p.prpayCodDivNm)
                                  if (p.shppcstAplUnitNm) parts.push(p.shppcstAplUnitNm)
                                  return { value: p.shppcstId, label: parts.join(' / '), divCd: p.divCd }
                                }))
                              }
                              // 주소 조회
                              const addrRes = await proxyApi.ssgAddresses()
                              if (addrRes.success && addrRes.addresses?.length) {
                                setSsgAddrOptions(addrRes.addresses.map((a: { grpAddrId: string; doroAddrId?: string; addrNm: string; bascAddr: string }) => ({
                                  value: a.doroAddrId || a.grpAddrId,
                                  label: `${a.addrNm}${a.bascAddr ? ` (${a.bascAddr})` : ''}`,
                                })))
                              }
                              showAlert('배송비/주소 정보를 불러왔습니다.', 'success')
                            } catch {
                              showAlert('배송비/주소 조회 실패', 'error')
                            }
                          }}
                          style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                        >배송비/주소 불러오기</button>
                      )}
                    </div>
                  ) : field.type === 'info' ? (
                    <div key={field.name} style={{ padding: '0.4rem 0.6rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: '#FF8C00' }}>{field.label}</span>
                    </div>
                  ) : field.type === 'alias' ? (
                    <div key={field.name} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '180px', flexShrink: 0 }}>{field.label}</label>
                      <input
                        type="text"
                        style={{ ...inputStyle, flex: 1 }}
                        value={(() => {
                          const v = storeData[market.key]?.[field.name] || ''
                          return v.includes('-') ? v.split('-')[0] : v
                        })()}
                        onChange={(e) => {
                          const nick = (storeData[market.key]?.[field.name] || '').split('-').slice(1).join('-')
                          updateStoreField(market.key, field.name, nick ? `${e.target.value}-${nick}` : e.target.value)
                        }}
                        placeholder={field.placeholder || '마켓번호'}
                      />
                      <span style={{ color: '#555', fontSize: '0.8rem', flexShrink: 0 }}>—</span>
                      <input
                        type="text"
                        style={{ ...inputStyle, width: '120px', flexShrink: 0 }}
                        value={(() => {
                          const v = storeData[market.key]?.[field.name] || ''
                          return v.includes('-') ? v.split('-').slice(1).join('-') : ''
                        })()}
                        onChange={(e) => {
                          const code = (storeData[market.key]?.[field.name] || '').split('-')[0]
                          updateStoreField(market.key, field.name, e.target.value ? `${code}-${e.target.value}` : code)
                        }}
                        placeholder="사업자"
                      />
                    </div>
                  ) : (
                    <div key={field.name} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '180px', flexShrink: 0 }}>{field.label}</label>
                      {(field.type === 'ssg-shipping-select' || field.type === 'ssg-extra-select') ? (
                        <select
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                        >
                          <option value=''>버튼으로 불러오기</option>
                          {ssgShippingOptions
                            .filter(o => {
                              if (field.name === 'whoutShppcstId') return o.divCd === 10
                              if (field.name === 'retShppcstId') return o.divCd === 20
                              if (field.name === 'addShppcstIdJeju') return o.divCd === 70
                              if (field.name === 'addShppcstIdIsland') return o.divCd === 60
                              return false
                            })
                            .map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      ) : field.type === 'ssg-addr-select' ? (
                        <select
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                        >
                          <option value=''>버튼으로 불러오기</option>
                          {ssgAddrOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      ) : field.type === 'select' ? (
                        <select
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                        >
                          {field.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      ) : field.type === 'radio' ? (
                        <div style={{ display: 'flex', gap: '0.5rem', flex: 1 }}>
                          {field.options?.map(o => {
                            const selected = (storeData[market.key]?.[field.name] || field.options?.[0]?.value || '') === o.value
                            return (
                              <button
                                key={o.value}
                                type="button"
                                onClick={() => updateStoreField(market.key, field.name, o.value)}
                                style={{
                                  padding: '0.4rem 1rem',
                                  background: selected ? '#FF8C00' : 'transparent',
                                  color: selected ? '#000' : '#888',
                                  border: `1px solid ${selected ? '#FF8C00' : '#2D2D2D'}`,
                                  borderRadius: '6px',
                                  fontSize: '0.8125rem',
                                  fontWeight: selected ? 600 : 400,
                                  cursor: 'pointer',
                                  minWidth: '80px',
                                }}
                              >{o.label}</button>
                            )
                          })}
                        </div>
                      ) : field.type === 'checkbox' ? (
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={storeData[market.key]?.[field.name] === 'true' || storeData[market.key]?.[field.name] as unknown === true}
                            onChange={(e) => updateStoreField(market.key, field.name, e.target.checked ? 'true' : 'false')}
                            style={{ accentColor: '#FF8C00', width: '14px', height: '14px' }}
                          />
                          {field.placeholder && <span style={{ fontSize: '0.72rem', color: '#888' }}>({field.placeholder})</span>}
                        </label>
                      ) : field.type === 'number' ? (
                        <>
                          <NumInput
                            style={{ flex: 1, ...(field.disabled ? { opacity: 0.6, pointerEvents: 'none' as const } : {}) }}
                            value={field.disabled && field.fixedValue != null ? String(field.fixedValue) : (storeData[market.key]?.[field.name] || '')}
                            onChange={(v) => { if (!field.disabled) updateStoreField(market.key, field.name, v) }}
                            placeholder={field.placeholder || '0'}
                          />
                          {field.description && <span style={{ fontSize: '0.7rem', color: '#888', flexShrink: 0 }}>{field.description}</span>}
                        </>
                      ) : field.type === 'password' ? (
                        <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
                          <input
                            type={visiblePasswords.has(`${market.key}_${field.name}`) ? 'text' : 'password'}
                            style={{ ...inputStyle, flex: 1 }}
                            value={storeData[market.key]?.[field.name] || ''}
                            onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                            placeholder={field.placeholder || ''}
                          />
                          <button
                            type="button"
                            onClick={() => setVisiblePasswords(prev => {
                              const next = new Set(prev)
                              const k = `${market.key}_${field.name}`
                              next.has(k) ? next.delete(k) : next.add(k)
                              return next
                            })}
                            style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}
                          >{visiblePasswords.has(`${market.key}_${field.name}`) ? '숨김' : '보기'}</button>
                        </div>
                      ) : (
                        <input
                          type={field.type}
                          style={{ ...inputStyle, flex: 1 }}
                          value={storeData[market.key]?.[field.name] || ''}
                          onChange={(e) => updateStoreField(market.key, field.name, e.target.value)}
                          placeholder={field.placeholder || ''}
                        />
                      )}
                      {/* API 인증 필드 우측에 인증 테스트 버튼 */}
                      {market.authField === field.name && !field.name.startsWith('_') && (
                        <>
                          <button
                            onClick={() => testStoreAuth(market.key)}
                            style={{ padding: '0.375rem 0.875rem', background: '#FF8C00', color: '#000', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                          >인증 테스트</button>
                          {market.guideUrl && (
                            <a href={market.guideUrl} target="_blank" rel="noopener noreferrer"
                              style={{ padding: '0.375rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap', flexShrink: 0 }}
                            >API 발급</a>
                          )}
                        </>
                      )}
                      {/* 11번가 출고지정보 가져오기 버튼 */}
                      {market.key === '11st' && field.name === 'shipFromAddress' && (
                        <button
                          onClick={async () => {
                            try {
                              // 현재 입력된 API Key로 먼저 설정 저장
                              const data = storeData['11st'] || {}
                              if (data.apiKey) {
                                await forbiddenApi.saveSetting('store_11st', data)
                              }
                              const res = await proxyApi.elevenstSellerInfo()
                              if (res.success && res.data) {
                                const d = res.data
                                if (d.shipFromAddress) updateStoreField('11st', 'shipFromAddress', d.shipFromAddress)
                                if (d.returnAddress) updateStoreField('11st', 'returnAddress', d.returnAddress)
                                if (d.returnFee) updateStoreField('11st', 'returnFee', d.returnFee)
                                if (d.exchangeFee) updateStoreField('11st', 'exchangeFee', d.exchangeFee)
                                showAlert('출고지/반품지 정보를 가져왔습니다.', 'success')
                              } else {
                                showAlert(res.message || '정보를 가져올 수 없습니다.', 'error')
                              }
                            } catch {
                              showAlert('출고지 정보 조회 실패', 'error')
                            }
                          }}
                          style={{ padding: '0.375rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
                        >출고지정보 가져오기</button>
                      )}
                    </div>
                  ))}
                  {storeStatus[market.key] && (
                    <div style={{ fontSize: '0.8125rem', color: storeStatus[market.key]?.includes('연결') || storeStatus[market.key]?.includes('저장') || storeStatus[market.key]?.includes('✓') ? '#51CF66' : storeStatus[market.key]?.includes('중...') ? '#FFD93D' : '#FF6B6B' }}>
                      {storeStatus[market.key]}
                    </div>
                  )}
                </div>

                {/* 설정 저장 */}
                <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                  <button
                    onClick={() => saveStoreSettings(market.key)}
                    style={{ padding: '0.625rem 1.75rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 700, fontSize: '0.875rem', cursor: 'pointer' }}
                  >설정 저장</button>
                  {market.key === 'playauto' && (
                    <button
                      onClick={async () => {
                        if (!await showConfirm('플레이오토 API에서 등록상품을 조회하여 DB 상품과 매칭 후 registered_accounts에 추가합니다.')) return
                        try {
                          const res = await collectorApi.bulkAddAccount()
                          showAlert(`플레이오토 상품 ${res.pa_products}개 중 ${res.matched}개 매칭, ${res.updated}개 추가 (이미등록 ${res.already}개)`, 'success')
                        } catch (e) { showAlert(`실패: ${e}`, 'error') }
                      }}
                      style={{ padding: '0.625rem 1.25rem', background: 'rgba(81,207,102,0.1)', border: '1px solid rgba(81,207,102,0.3)', borderRadius: '6px', fontSize: '0.8rem', color: '#51CF66', cursor: 'pointer', fontWeight: 600 }}
                    >등록상품 일괄매칭</button>
                  )}
                </div>
              </div>

              {/* 우측: 해당 마켓 연결계정 */}
              <div style={{ width: '260px', flexShrink: 0 }}>
                <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#888', marginBottom: '0.5rem' }}>연결 계정</div>
                {(() => {
                  const marketAccounts = accounts.filter(a => a.market_type === market.key)
                  if (marketAccounts.length === 0) return (
                    <div style={{ fontSize: '0.78rem', color: '#555', padding: '0.5rem 0' }}>등록된 계정 없음</div>
                  )
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                      {marketAccounts.map(a => (
                        <div
                          key={a.id}
                          style={{
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            padding: '0.4rem 0.625rem', background: 'rgba(255,255,255,0.02)',
                            borderRadius: '6px', border: '1px solid rgba(45,45,45,0.5)',
                          }}>
                          <div style={{ flex: 1, minWidth: 0, fontSize: '0.8rem', color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {a.account_label}
                          </div>
                          <button
                            onClick={() => {
                              setEditingAccountId(a.id)
                              // password 타입 필드는 계정 API에서 마스킹(****xxxx)된 값이므로 제외
                              // savedStoreData(설정 API 원본)의 값을 유지해야 DB 손상 방지
                              const passwordFieldNames = new Set(
                                market.fields.filter(f => f.type === 'password').map(f => f.name)
                              )
                              const accFields = Object.fromEntries(
                                Object.entries((a.additional_fields || {}) as Record<string, string>)
                                  .filter(([k]) => !passwordFieldNames.has(k))
                              )
                              const savedFields = savedStoreData[market.key] || {}
                              const formData: Record<string, string> = {
                                businessName: a.business_name || '',
                                storeId: a.seller_id || '',
                                ...savedFields,
                                ...accFields,
                              }
                              setStoreData(prev => ({ ...prev, [market.key]: formData }))
                            }}
                            style={{
                              padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                              background: editingAccountId === a.id ? 'rgba(255,140,0,0.15)' : 'rgba(60,60,60,0.8)',
                              color: editingAccountId === a.id ? '#FF8C00' : '#C5C5C5',
                              border: editingAccountId === a.id ? '1px solid #FF8C00' : '1px solid #3D3D3D',
                              cursor: 'pointer', whiteSpace: 'nowrap',
                            }}
                          >{editingAccountId === a.id ? '수정중' : '수정'}</button>
                          <button
                            onClick={() => handleAccountDelete(a.id)}
                            style={{
                              padding: '0.15rem 0.4rem', borderRadius: '4px', fontSize: '0.7rem',
                              background: 'rgba(255,80,80,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,80,80,0.3)',
                              cursor: 'pointer', whiteSpace: 'nowrap',
                            }}
                          >삭제</button>
                        </div>
                      ))}
                    </div>
                  )
                })()}
              </div>
              </div>
            ))}
          </div>

      {/* ═══════ 소싱처 계정 관리 ═══════ */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.5rem' }}>
        <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>소싱처 계정</div>
        <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1.25rem' }}>소싱처별 로그인 계정을 관리합니다</p>

        {/* 소싱처 탭바 */}
        <div style={{ borderBottom: '1px solid #2D2D2D', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0 }}>
            {sourcingSites.map(site => {
              const count = sourcingAccounts.filter(a => a.site_name === site.id).length
              return (
                <button
                  key={site.id}
                  onClick={() => { setSourcingTab(site.id); setSourcingEditId(null); setSourcingForm({ site_name: site.id, account_label: '', username: '', password: '', chrome_profile: '', memo: '' }) }}
                  style={{
                    padding: '0.5rem 0.75rem', background: 'none', border: 'none',
                    borderBottom: sourcingTab === site.id ? '2px solid #FF8C00' : '2px solid transparent',
                    color: sourcingTab === site.id ? '#FF8C00' : '#666',
                    fontSize: '0.8125rem', fontWeight: sourcingTab === site.id ? 600 : 400,
                    cursor: 'pointer', marginBottom: '-1px', whiteSpace: 'nowrap',
                  }}
                >{site.name}{count > 0 ? ` (${fmtNum(count)})` : ''}</button>
              )
            })}
          </div>
        </div>

        {/* 좌측: 인라인 폼 + 우측: 계정 리스트 */}
        <div style={{ display: 'flex', gap: '2rem', alignItems: 'flex-start' }}>
          {/* 좌측: 입력 폼 */}
          <div style={{ flex: 1, maxWidth: '560px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5' }}>
                {sourcingSites.find(s => s.id === sourcingTab)?.name || sourcingTab} 계정
              </span>
              {sourcingEditId && (
                <>
                  <span style={{ fontSize: '0.75rem', color: '#FF8C00', fontWeight: 600 }}>
                    ({sourcingAccounts.find(a => a.id === sourcingEditId)?.account_label} 수정중)
                  </span>
                  <button
                    onClick={() => { setSourcingEditId(null); setSourcingForm({ site_name: sourcingTab, account_label: '', username: '', password: '', chrome_profile: '', memo: '' }) }}
                    style={{ padding: '0.2rem 0.5rem', fontSize: '0.7rem', background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer' }}
                  >취소</button>
                </>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '120px', flexShrink: 0 }}>별칭</label>
                <input style={{ ...inputStyle, flex: 1 }} placeholder="별칭" value={sourcingForm.account_label} onChange={e => setSourcingForm(prev => ({ ...prev, account_label: e.target.value }))} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '120px', flexShrink: 0 }}>아이디</label>
                <input style={{ ...inputStyle, flex: 1 }} placeholder="로그인 아이디" value={sourcingForm.username} onChange={e => setSourcingForm(prev => ({ ...prev, username: e.target.value }))} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '120px', flexShrink: 0 }}>비밀번호</label>
                <input style={{ ...inputStyle, flex: 1 }} type="password" placeholder="로그인 비밀번호" value={sourcingForm.password} onChange={e => setSourcingForm(prev => ({ ...prev, password: e.target.value }))} />
              </div>
              {sourcingTab === 'MUSINSA' && (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '120px', flexShrink: 0 }}>크롬 프로필</label>
                    <select style={{ ...inputStyle, flex: 1 }} value={sourcingForm.chrome_profile} onChange={e => setSourcingForm(prev => ({ ...prev, chrome_profile: e.target.value }))}>
                      <option value="">선택 안함</option>
                      {normalizedChromeProfiles.map((p, idx) => <option key={`${p.email || p.directory || 'profile'}-${idx}`} value={p.email || p.directory}>{p.display_name || p.name} ({p.email || p.directory})</option>)}
                    </select>
                    <button
                      type="button"
                      onClick={handleSyncChromeProfiles}
                      disabled={chromeProfilesSyncing}
                      style={{
                        padding: '0.55rem 0.8rem',
                        background: 'rgba(76,154,255,0.12)',
                        color: chromeProfilesSyncing ? '#666' : '#4C9AFF',
                        border: '1px solid rgba(76,154,255,0.35)',
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        cursor: chromeProfilesSyncing ? 'not-allowed' : 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {chromeProfilesSyncing ? '동기화중' : '동기화'}
                    </button>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '120px', flexShrink: 0 }}>지메일</label>
                    <input style={{ ...inputStyle, flex: 1 }} placeholder="지메일 주소" value={sourcingForm.memo} onChange={e => setSourcingForm(prev => ({ ...prev, memo: e.target.value }))} />
                  </div>
                </>
              )}
            </div>

            {/* 저장 버튼 */}
            <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.5rem' }}>
              <button
                onClick={handleSourcingSave}
                style={{ padding: '0.625rem 1.75rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 700, fontSize: '0.875rem', cursor: 'pointer' }}
              >{sourcingEditId ? '계정 수정' : '계정 추가'}</button>
              <button
                onClick={handleFetchAllBalances}
                style={{ padding: '0.625rem 1.25rem', background: 'rgba(76,154,255,0.15)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', borderRadius: '6px', fontWeight: 600, fontSize: '0.875rem', cursor: 'pointer' }}
              >잔액 새로고침</button>
            </div>
          </div>

          {/* 우측: 해당 소싱처 계정 리스트 */}
          <div style={{ width: '320px', flexShrink: 0 }}>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#888', marginBottom: '0.5rem' }}>등록 계정</div>
            {(() => {
              const siteAccounts = sourcingAccounts.filter(a => a.site_name === sourcingTab).sort((a, b) => (a.chrome_profile || '').localeCompare(b.chrome_profile || '', undefined, { numeric: true }))
              if (siteAccounts.length === 0) return (
                <div style={{ fontSize: '0.78rem', color: '#555', padding: '0.5rem 0' }}>등록된 계정 없음</div>
              )
              return (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                  {siteAccounts.map(a => (
                    <div key={a.id} style={{
                      padding: '0.5rem 0.625rem',
                      background: sourcingEditId === a.id ? 'rgba(255,140,0,0.08)' : 'rgba(255,255,255,0.02)',
                      borderRadius: '6px',
                      border: sourcingEditId === a.id ? '1px solid rgba(255,140,0,0.3)' : '1px solid rgba(45,45,45,0.5)',
                      opacity: a.is_active ? 1 : 0.5,
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                        <span style={{ flex: 1, fontSize: '0.8rem', fontWeight: 600, color: '#E5E5E5', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.account_label}({a.username})</span>
                        {sourcingTab === 'MUSINSA' && a.chrome_profile && <span style={{ fontSize: '0.68rem', color: '#888', fontFamily: 'monospace' }}>{a.chrome_profile}</span>}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', fontSize: '0.7rem' }}>
                        {sourcingTab === 'MUSINSA' && a.chrome_profile && <span style={{ color: '#666', background: '#1A1A1A', padding: '0.05rem 0.3rem', borderRadius: '3px' }}>{chromeProfiles.find(p => p.email === a.chrome_profile || p.directory === a.chrome_profile)?.display_name || chromeProfiles.find(p => p.email === a.chrome_profile || p.directory === a.chrome_profile)?.name || a.chrome_profile}</span>}
                        {sourcingTab === 'MUSINSA' && a.memo && <span style={{ color: '#888' }}>{a.memo}</span>}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem', fontSize: '0.7rem' }}>
                        {(a.additional_fields as Record<string, unknown>)?.cookie_expired ? (
                          <span style={{ color: '#FF6B6B', fontWeight: 600 }}>쿠키 만료 — 재로그인 필요</span>
                        ) : (
                          <>
                            <span style={{ color: '#51CF66', fontWeight: 600 }}>머니 {fmtNum(a.balance ?? 0)}</span>
                            <span style={{ color: '#4C9AFF', fontWeight: 600 }}>적립금 {fmtNum(Number((a.additional_fields as Record<string, unknown>)?.mileage ?? 0))}</span>
                          </>
                        )}
                        {a.balance_updated_at && <span style={{ color: '#666' }}>{new Date(a.balance_updated_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>}
                      </div>
                      <div style={{ display: 'flex', gap: '0.25rem' }}>
                        <button onClick={() => handleFetchBalance(a.id)} disabled={balanceLoading[a.id]} style={{ padding: '0.15rem 0.4rem', fontSize: '0.68rem', background: 'rgba(81,207,102,0.1)', border: '1px solid rgba(81,207,102,0.3)', color: '#51CF66', borderRadius: '4px', cursor: 'pointer', opacity: balanceLoading[a.id] ? 0.5 : 1 }}>{balanceLoading[a.id] ? '조회중' : '잔액'}</button>
                        <button onClick={() => sourcingAccountApi.toggle(a.id).then(() => loadSourcingAccounts())} style={{ padding: '0.15rem 0.4rem', fontSize: '0.68rem', background: a.is_active ? 'rgba(76,154,255,0.1)' : 'rgba(100,100,100,0.2)', border: `1px solid ${a.is_active ? 'rgba(76,154,255,0.3)' : '#555'}`, color: a.is_active ? '#4C9AFF' : '#888', borderRadius: '4px', cursor: 'pointer' }}>{a.is_active ? 'ON' : 'OFF'}</button>
                        <button
                          onClick={() => handleSourcingEdit(a)}
                          style={{
                            padding: '0.15rem 0.4rem', fontSize: '0.68rem', borderRadius: '4px', cursor: 'pointer',
                            background: sourcingEditId === a.id ? 'rgba(255,140,0,0.15)' : 'rgba(60,60,60,0.8)',
                            color: sourcingEditId === a.id ? '#FF8C00' : '#C5C5C5',
                            border: sourcingEditId === a.id ? '1px solid #FF8C00' : '1px solid #3D3D3D',
                          }}
                        >{sourcingEditId === a.id ? '수정중' : '수정'}</button>
                        <button onClick={() => handleSourcingDelete(a.id)} style={{ padding: '0.15rem 0.4rem', fontSize: '0.68rem', background: 'rgba(255,80,80,0.15)', color: '#FF6B6B', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', cursor: 'pointer' }}>삭제</button>
                      </div>
                    </div>
                  ))}
                </div>
              )
            })()}
          </div>
        </div>
      </div>

      {/* SMS / 카카오 알림톡 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.5rem' }}>

        {/* SMS 설정 */}
        <div style={{ paddingBottom: '1.5rem', marginBottom: '1.5rem', borderBottom: '1px solid #2D2D2D' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#4C9AFF' }}>SMS 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 문자메세지 설정을 할 수 있습니다.</span>
            {smsStatus && <span style={{ fontSize: '0.8rem', color: smsStatus === '저장됨' || smsStatus.includes('유효') ? '#51CF66' : smsStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{smsStatus === '저장됨' ? '✓ 저장됨' : smsStatus}</span>}
            <a href="https://smartsms.aligo.in/admin/api/info.html" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
            <button onClick={saveSmsSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>SMS API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={smsUserId} onChange={(e) => setSmsUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={smsApiKey} onChange={(e) => setSmsApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testSmsKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>SMS 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={smsSender} onChange={(e) => setSmsSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>

        {/* 카카오 알림톡 설정 */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FFB84D' }}>카카오 알림톡 설정</span>
            <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 알리고(ALIGO) 카카오 알림톡 설정을 할 수 있습니다.</span>
            {kakaoStatus && <span style={{ fontSize: '0.8rem', color: kakaoStatus === '저장됨' || kakaoStatus.includes('유효') ? '#51CF66' : kakaoStatus.includes('오류') ? '#FF6B6B' : '#FFD93D' }}>{kakaoStatus === '저장됨' ? '✓ 저장됨' : kakaoStatus}</span>}
            <a href="https://smartsms.aligo.in/admin/api/kakao.html" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
            <button onClick={saveKakaoSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
              <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem', flexShrink: 0 }}>알림톡 API KEY</label>
              <input style={{ ...inputStyle, flex: 2, minWidth: '100px' }} value={kakaoUserId} onChange={(e) => setKakaoUserId(e.target.value)} placeholder='Identifier' />
              <input style={{ ...inputStyle, flex: 4, minWidth: '140px' }} value={kakaoApiKey} onChange={(e) => setKakaoApiKey(e.target.value)} placeholder='API Key' />
              <button onClick={() => window.open('https://www.aligo.in/index.html', '_blank')} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>Key 발급</button>
              <button onClick={testKakaoKey} style={{ background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>테스트</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 SenderKey</label>
              <input style={{ ...inputStyle, flex: 1 }} value={kakaoSenderKey} onChange={(e) => setKakaoSenderKey(e.target.value)} placeholder='Senderkey를 입력하세요.' />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <label style={{ color: '#888', minWidth: '160px', fontSize: '0.875rem' }}>알림톡 발신번호</label>
              <input style={{ ...inputStyle, width: '160px', flexShrink: 0 }} value={kakaoSender} onChange={(e) => setKakaoSender(e.target.value)} placeholder='010-0000-0000' />
              <span style={{ fontSize: '0.8125rem', color: '#FF6B6B' }}>※ 발신번호는 사전에 알리고에 등록하신 후 입력해주시기 바랍니다.</span>
            </div>
          </div>
        </div>
      </div>

      {/* Gemini AI (이미지 변환 / AI태그) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#4285F4' }}>Gemini AI (이미지 변환 / AI태그)</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>상품사진 → 모델착용컷 생성 (₩430/장)</span>
          <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(66,133,244,0.1)', border: '1px solid rgba(66,133,244,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4285F4', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveGeminiSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>API Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input type={visiblePasswords.has('gemini_apiKey') ? 'text' : 'password'} style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={geminiApiKey} onChange={(e) => setGeminiApiKey(e.target.value)} placeholder='AIzaSy...' />
              <button type="button" onClick={() => setVisiblePasswords(prev => { const n = new Set(prev); n.has('gemini_apiKey') ? n.delete('gemini_apiKey') : n.add('gemini_apiKey'); return n })} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('gemini_apiKey') ? '숨김' : '보기'}</button>
            </div>
            <button onClick={testGeminiApi} style={{ background: 'rgba(66,133,244,0.1)', border: '1px solid rgba(66,133,244,0.35)', color: '#4285F4', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>모델</label>
            <select style={{ ...inputStyle, width: '300px' }} value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)}>
              <option value="gemini-2.5-flash">Gemini 2.5 Flash (권장)</option>
              <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
            </select>
          </div>
          {geminiStatus && (
            <div style={{ fontSize: '0.8125rem', color: geminiStatus.includes('저장') ? '#7BAF7E' : '#C4736E', padding: '0.4rem 0' }}>
              {geminiStatus}
            </div>
          )}
        </div>
      </div>

      {/* Cloudflare R2 연동 (이미지 저장) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#F59E0B' }}>Cloudflare R2 연동</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 변환된 이미지 저장용 (미설정 시 서버 로컬 저장)</span>
          <a href="https://dash.cloudflare.com/?to=/:account/r2/api-tokens" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveR2Settings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Account ID</label>
            <input type='text' style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2AccountId} onChange={(e) => setR2AccountId(e.target.value)} placeholder='Cloudflare Account ID' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Access Key ID</label>
            <input type='text' style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2AccessKey} onChange={(e) => setR2AccessKey(e.target.value)} placeholder='R2 Access Key ID' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Secret Access Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input type={visiblePasswords.has('r2_secretKey') ? 'text' : 'password'} style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }} value={r2SecretKey} onChange={(e) => setR2SecretKey(e.target.value)} placeholder='R2 Secret Access Key' />
              <button type="button" onClick={() => setVisiblePasswords(prev => { const n = new Set(prev); n.has('r2_secretKey') ? n.delete('r2_secretKey') : n.add('r2_secretKey'); return n })} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('r2_secretKey') ? '숨김' : '보기'}</button>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Bucket Name</label>
            <input type='text' style={{ ...inputStyle, flex: 1 }} value={r2BucketName} onChange={(e) => setR2BucketName(e.target.value)} placeholder='samba-images' />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '120px', fontSize: '0.875rem' }}>Public URL</label>
            <input type='text' style={{ ...inputStyle, flex: 1 }} value={r2PublicUrl} onChange={(e) => setR2PublicUrl(e.target.value)} placeholder='https://pub-xxx.r2.dev' />
            <button onClick={testR2} style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.35)', color: '#F59E0B', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          {r2Status && (
            <div style={{ fontSize: '0.8125rem', color: r2Status.includes('저장') || r2Status.includes('✓') ? '#7BAF7E' : r2Status.includes('확인') ? '#FFB84D' : '#C4736E', padding: '0.4rem 0' }}>
              {r2Status}
            </div>
          )}
        </div>
      </div>

      {/* Claude AI API 연동 */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#A78BFA' }}>Claude AI API 연동</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** Anthropic Claude API를 연결하면 상품명 가공, CS 자동 답변 등 AI 기능을 사용할 수 있습니다.</span>
          <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" style={{ padding: '0.3rem 0.75rem', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', borderRadius: '6px', fontSize: '0.75rem', color: '#4C9AFF', textDecoration: 'none', whiteSpace: 'nowrap' }}>API 발급</a>
          <button onClick={saveClaudeSettings} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>설정저장</button>
        </div>
        <div style={{ maxWidth: '720px', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>API Key</label>
            <div style={{ display: 'flex', flex: 1, gap: '4px', alignItems: 'center' }}>
              <input
                type={visiblePasswords.has('claude_apiKey') ? 'text' : 'password'}
                style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }}
                value={claudeApiKey}
                onChange={(e) => setClaudeApiKey(e.target.value)}
                placeholder='sk-ant-api03-...'
              />
              <button type="button" onClick={() => setVisiblePasswords(prev => { const n = new Set(prev); n.has('claude_apiKey') ? n.delete('claude_apiKey') : n.add('claude_apiKey'); return n })} style={{ padding: '0.3rem 0.5rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#888', cursor: 'pointer', whiteSpace: 'nowrap' }}>{visiblePasswords.has('claude_apiKey') ? '숨김' : '보기'}</button>
            </div>
            <button onClick={testClaudeApi} style={{ background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.35)', color: '#A78BFA', padding: '0.35rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}>연결 테스트</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <label style={{ color: '#888', minWidth: '100px', fontSize: '0.875rem' }}>모델 선택</label>
            <select style={{ ...inputStyle, width: '260px' }} value={claudeModel} onChange={(e) => setClaudeModel(e.target.value)}>
              {CLAUDE_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          {claudeStatus && (
            <div style={{ fontSize: '0.8125rem', color: claudeStatus.includes('저장') ? '#51CF66' : claudeStatus.includes('유효') ? '#FFB84D' : '#FF6B6B', padding: '0.4rem 0' }}>
              {claudeStatus.includes('저장') ? '✓ ' : claudeStatus.includes('유효') ? '⚠ ' : '✗ '}{claudeStatus}
            </div>
          )}
        </div>
      </div>

      {/* AI 모델 프리셋 관리 */}
      {presets.length > 0 && (
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#FF8C00' }}>AI 모델 프리셋</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 모델 착용 이미지 생성 시 참조하는 기준 모델</span>
          <button onClick={loadPresets} style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>새로고침</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '1rem' }}>
          {presets.map(p => (
            <div key={p.key} style={{ background: 'rgba(30,30,30,0.6)', borderRadius: '8px', border: '1px solid #2D2D2D', overflow: 'hidden' }}>
              <div style={{ position: 'relative', paddingTop: '120%', background: '#1A1A1A' }}>
                {p.image ? (
                  <img
                    src={`${API_BASE}${p.image}?t=${Date.now()}`}
                    alt={p.label}
                    style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover', cursor: 'pointer' }}
                    onClick={() => setPresetZoom(`${API_BASE}${p.image}?t=${Date.now()}`)}
                  />
                ) : (
                  <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', color: '#555', fontSize: '0.7rem', textAlign: 'center' }}>이미지 없음</div>
                )}
                {/* 이미지 업로드 버튼 */}
                <button
                  style={{ position: 'absolute', bottom: 4, right: 4, background: 'rgba(0,0,0,0.7)', border: '1px solid #555', color: '#CCC', borderRadius: '4px', padding: '2px 6px', fontSize: '0.6rem', cursor: 'pointer' }}
                  onClick={() => {
                    const input = document.createElement('input')
                    input.type = 'file'
                    input.accept = 'image/*'
                    input.onchange = async (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0]
                      if (!file) return
                      setRegenerating(p.key)
                      try {
                        const res = await proxyApi.uploadPresetImage(p.key, file)
                        if (res.success) { showAlert(res.message, 'success'); await loadPresets() }
                        else showAlert(res.message, 'error')
                      } catch { showAlert('업로드 실패', 'error') }
                      finally { setRegenerating(null) }
                    }
                    input.click()
                  }}
                >업로드</button>
                {regenerating === p.key && (
                  <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#FF8C00', fontSize: '0.75rem' }}>
                    처리중...
                  </div>
                )}
              </div>
              <div style={{ padding: '0.5rem' }}>
                {editingPreset === p.key ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    <input
                      value={editingLabel}
                      onChange={e => setEditingLabel(e.target.value)}
                      style={{ ...inputStyle, fontSize: '0.7rem', fontWeight: 600 }}
                      placeholder="프리셋 이름"
                    />
                    <textarea
                      value={editingDesc}
                      onChange={e => setEditingDesc(e.target.value)}
                      rows={3}
                      style={{ ...inputStyle, fontSize: '0.7rem', resize: 'vertical' }}
                      placeholder="모델 설명 프롬프트"
                    />
                    <div style={{ display: 'flex', gap: '0.25rem' }}>
                      <button
                        onClick={() => handleRegeneratePreset(p.key, editingDesc, editingLabel)}
                        disabled={regenerating !== null}
                        style={{ flex: 1, padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '4px', color: '#FF8C00', cursor: 'pointer' }}
                      >저장 & 재생성</button>
                      <button
                        onClick={() => handleSavePreset(p.key, editingLabel, editingDesc)}
                        style={{ flex: 1, padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,255,255,0.08)', border: '1px solid #444', borderRadius: '4px', color: '#CCC', cursor: 'pointer' }}
                      >저장만</button>
                      <button
                        onClick={() => setEditingPreset(null)}
                        style={{ padding: '0.2rem 0.4rem', fontSize: '0.65rem', background: 'rgba(255,80,80,0.1)', border: '1px solid rgba(255,80,80,0.3)', borderRadius: '4px', color: '#FF6B6B', cursor: 'pointer' }}
                      >취소</button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '0.2rem' }}>{p.label}</div>
                    <div style={{ fontSize: '0.65rem', color: '#888', marginBottom: '0.35rem', lineHeight: 1.3 }}>{p.desc.length > 40 ? p.desc.slice(0, 40) + '...' : p.desc}</div>
                    <button
                      onClick={() => { setEditingPreset(p.key); setEditingLabel(p.label); setEditingDesc(p.desc) }}
                      style={{ width: '100%', padding: '0.2rem', fontSize: '0.65rem', background: 'rgba(255,255,255,0.05)', border: '1px solid #333', borderRadius: '4px', color: '#AAA', cursor: 'pointer' }}
                    >수정</button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      )}

      {/* 금지어 / 삭제어 (전역) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#E5E5E5' }}>금지어 / 삭제어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>모든 그룹·상품에 공통 적용</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FF6B6B', fontWeight: 600 }}>
                금지어 (IP위험 브랜드 포함) — 세미콜론(;) 구분
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(forbiddenText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('forbidden', words)
                    const deduped = words.join('; ')
                    setForbiddenText(deduped)
                    setInitialForbiddenText(deduped)
                    showAlert(`금지어 ${words.length}개 저장 완료`, 'success')
                  } catch { showAlert('저장 실패', 'error') }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                  color: '#FF6B6B', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={forbiddenText}
              onChange={e => setForbiddenText(e.target.value)}
              placeholder="구찌; 루이비통; 샤넬; 프라다"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {forbiddenText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600 }}>
                삭제어 — 상품명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(deletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('deletion', words)
                    const deduped = words.join('; ')
                    setDeletionText(deduped)
                    setInitialDeletionText(deduped)
                    showAlert(`삭제어 ${words.length}개 저장 완료`, 'success')
                  } catch { showAlert('저장 실패', 'error') }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(255,184,77,0.12)', border: '1px solid rgba(255,184,77,0.3)',
                  color: '#FFB84D', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={deletionText}
              onChange={e => setDeletionText(e.target.value)}
              placeholder="매장정품; 정품; 해외직구; 무료배송"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {deletionText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <div style={{ fontSize: '0.8125rem', color: '#A29BFE', fontWeight: 600 }}>
                옵션삭제어 — 옵션명에서 자동 제거
              </div>
              <button
                disabled={wordsSaving}
                onClick={async () => {
                  setWordsSaving(true)
                  try {
                    const words = [...new Set(optionDeletionText.split(';').map(w => w.trim()).filter(Boolean))]
                    await forbiddenApi.bulkSaveWords('option_deletion', words)
                    const deduped = words.join('; ')
                    setOptionDeletionText(deduped)
                    setInitialOptionDeletionText(deduped)
                    showAlert(`옵션삭제어 ${words.length}개 저장 완료`, 'success')
                  } catch { showAlert('저장 실패', 'error') }
                  setWordsSaving(false)
                }}
                style={{
                  padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
                  background: 'rgba(162,155,254,0.12)', border: '1px solid rgba(162,155,254,0.3)',
                  color: '#A29BFE', cursor: 'pointer',
                }}
              >{wordsSaving ? '...' : '저장'}</button>
            </div>
            <textarea
              value={optionDeletionText}
              onChange={e => setOptionDeletionText(e.target.value)}
              placeholder="01(; 02(; ); [품절]"
              style={{
                width: '100%', height: '100px', background: '#0A0A0A', border: '1px solid #2D2D2D',
                borderRadius: '6px', padding: '8px', color: '#E5E5E5', fontSize: '0.8125rem',
                resize: 'vertical', fontFamily: 'monospace',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: '#666', marginTop: '2px' }}>
              {optionDeletionText.split(';').filter(w => w.trim()).length}개
            </div>
          </div>
        </div>
      </div>

      {/* 태그 금지어 (스마트스토어 등록불가 단어) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: '#C4736E' }}>태그 금지어</span>
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>** 스마트스토어 등록 시 자동 제외되는 단어 (API 거부 + 소싱처 + 브랜드)</span>
          <button onClick={() => forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})}
            style={{ marginLeft: 'auto', background: 'rgba(50,50,50,0.8)', border: '1px solid #3D3D3D', color: '#C5C5C5', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>새로고침</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* API 거부 태그 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#C4736E', fontWeight: 600, marginBottom: '0.4rem' }}>
              API 거부 태그 ({tagBanned.rejected.length}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>전송 실패 시 자동 누적 + 직접 추가 가능</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
              {tagBanned.rejected.length === 0 && <span style={{ fontSize: '0.75rem', color: '#555' }}>아직 없음</span>}
              {tagBanned.rejected.map((w, i) => (
                <span key={i} style={{
                  fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px',
                  background: 'rgba(196,115,110,0.12)', border: '1px solid rgba(196,115,110,0.3)', color: '#C4736E',
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                }}>
                  {w}
                  <span style={{ cursor: 'pointer', color: '#888', fontSize: '0.8rem', lineHeight: 1 }}
                    onClick={async () => {
                      const updated = tagBanned.rejected.filter((_, idx) => idx !== i)
                      await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                      setTagBanned(prev => ({ ...prev, rejected: updated }))
                    }}>×</span>
                </span>
              ))}
              <input
                type="text"
                placeholder="금지어 입력 후 Enter"
                style={{ fontSize: '0.7rem', padding: '2px 7px', border: '1px solid #2D2D2D', borderRadius: '4px', color: '#C5C5C5', background: '#1A1A1A', outline: 'none', width: '140px' }}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') {
                    const val = e.currentTarget.value.trim().toLowerCase()
                    if (!val || tagBanned.rejected.includes(val)) return
                    const updated = [...tagBanned.rejected, val]
                    await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                    setTagBanned(prev => ({ ...prev, rejected: updated }))
                    e.currentTarget.value = ''
                  }
                }}
              />
            </div>
          </div>
          {/* 수집 브랜드 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#FFB84D', fontWeight: 600, marginBottom: '0.4rem' }}>
              수집 브랜드 ({tagBanned.brands.length}개)
              <span style={{ fontWeight: 400, color: '#666', marginLeft: '0.5rem' }}>브랜드명 포함 태그 자동 제외</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', maxHeight: '80px', overflow: 'auto' }}>
              {tagBanned.brands.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(255,184,77,0.08)', border: '1px solid rgba(255,184,77,0.25)', color: '#FFB84D' }}>{w}</span>
              ))}
            </div>
          </div>
          {/* 소싱처 */}
          <div>
            <div style={{ fontSize: '0.8125rem', color: '#4C9AFF', fontWeight: 600, marginBottom: '0.4rem' }}>
              소싱처 ({tagBanned.source_sites.length}개)
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {tagBanned.source_sites.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(76,154,255,0.08)', border: '1px solid rgba(76,154,255,0.25)', color: '#4C9AFF' }}>{w}</span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 프록시 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
          <div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>프록시 / IP 설정</div>
            <p style={{ fontSize: '0.8125rem', color: '#666', margin: '0.25rem 0 0' }}>전송·수집·오토튠에 사용할 IP/프록시를 관리합니다</p>
          </div>
          <button
            onClick={openProxyAdd}
            style={{ padding: '0.4rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer' }}
          >+ 추가</button>
        </div>

        {proxies.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: '#555', fontSize: '0.8125rem' }}>
            등록된 프록시가 없습니다
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem', fontSize: '0.8125rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D', color: '#888' }}>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 500 }}>이름</th>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 500 }}>IP / URL</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>용도</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>상태</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>관리</th>
              </tr>
            </thead>
            <tbody>
              {proxies.map((p, i) => {
                const isMainIp = !p.url
                const masked = isMainIp ? '34.47.122.131 (직접 연결)' : p.url.includes('@') ? `***@${p.url.split('@').pop()}` : p.url.replace(/^https?:\/\//, '')
                const PURPOSE_STYLES: Record<ProxyPurpose, { bg: string; color: string; label: string }> = {
                  transmit: { bg: 'rgba(0,200,150,0.1)', color: '#00C896', label: '전송' },
                  collect: { bg: 'rgba(255,184,77,0.1)', color: '#FFB84D', label: '수집' },
                  autotune: { bg: 'rgba(76,154,255,0.1)', color: '#4C9AFF', label: '오토튠' },
                }
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #1A1A1A' }}>
                    <td style={{ padding: '0.6rem 0.75rem', color: '#E5E5E5' }}>
                      {isMainIp && <span style={{ color: '#00C896', marginRight: '4px', fontSize: '0.7rem' }}>●</span>}
                      {p.name}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', color: isMainIp ? '#00C896' : '#999', fontFamily: 'monospace', fontSize: '0.75rem' }}>{masked}</td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                        {(p.purposes || []).map(pp => {
                          const s = PURPOSE_STYLES[pp]
                          return s ? <span key={pp} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: s.bg, color: s.color }}>{s.label}</span> : null
                        })}
                      </div>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                      <span
                        onClick={() => handleProxyToggle(i)}
                        style={{
                          display: 'inline-block', width: '36px', height: '20px', borderRadius: '10px', cursor: 'pointer', position: 'relative',
                          background: p.enabled ? '#FF8C00' : '#333',
                          transition: 'background 0.2s',
                        }}
                      >
                        <span style={{
                          position: 'absolute', top: '2px', left: p.enabled ? '18px' : '2px',
                          width: '16px', height: '16px', borderRadius: '50%', background: '#fff',
                          transition: 'left 0.2s',
                        }} />
                      </span>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center', whiteSpace: 'nowrap' }}>
                      <button
                        onClick={() => testProxy(i)}
                        disabled={proxyTesting === i}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: proxyTesting === i ? '#555' : '#4C9AFF', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer', marginRight: '4px' }}
                      >{proxyTesting === i ? '테스트중' : '테스트'}</button>
                      <button
                        onClick={() => openProxyEdit(i)}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: '#999', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer', marginRight: '4px' }}
                      >수정</button>
                      <button
                        onClick={() => handleProxyDelete(i)}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: '#C4736E', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer' }}
                      >삭제</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* 프록시 추가/수정 모달 */}
      {proxyModalOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setProxyModalOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ ...card, padding: '1.5rem', width: '420px', maxWidth: '90vw' }}>
            <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '1rem' }}>
              {proxyEditIdx !== null ? '프록시 수정' : '프록시 추가'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '4px', display: 'block' }}>이름</label>
                <input value={proxyForm.name} onChange={e => setProxyForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="프록시칩 1" style={{ ...inputStyle }} />
              </div>
              <div style={{ background: '#141414', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem' }}>
                <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>프록시 인증 정보 <span style={{ color: '#555' }}>(비워두면 메인 IP)</span></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Username</label>
                    <input value={proxyFields.username} onChange={e => setProxyFields(f => ({ ...f, username: e.target.value }))}
                      placeholder="username" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Password</label>
                    <input value={proxyFields.password} onChange={e => setProxyFields(f => ({ ...f, password: e.target.value }))}
                      placeholder="password" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>IP Address</label>
                    <input value={proxyFields.ip} onChange={e => setProxyFields(f => ({ ...f, ip: e.target.value }))}
                      placeholder="0.0.0.0" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Port</label>
                    <input value={proxyFields.port} onChange={e => setProxyFields(f => ({ ...f, port: e.target.value }))}
                      placeholder="0000" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                </div>
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '6px', display: 'block' }}>용도 (복수 선택 가능)</label>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  {([
                    { key: 'transmit' as ProxyPurpose, label: '전송', color: '#00C896' },
                    { key: 'collect' as ProxyPurpose, label: '수집', color: '#FFB84D' },
                    { key: 'autotune' as ProxyPurpose, label: '오토튠', color: '#4C9AFF' },
                  ]).map(({ key, label, color }) => {
                    const active = proxyForm.purposes.includes(key)
                    return (
                      <button key={key} onClick={() => toggleProxyPurpose(key)}
                        style={{
                          padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer',
                          background: active ? `${color}20` : '#1A1A1A',
                          border: `1px solid ${active ? color : '#2D2D2D'}`,
                          color: active ? color : '#666',
                          fontWeight: active ? 600 : 400,
                        }}>{label}</button>
                    )
                  })}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input type="checkbox" checked={proxyForm.enabled} onChange={e => setProxyForm(p => ({ ...p, enabled: e.target.checked }))} />
                <label style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>활성화</label>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.25rem' }}>
              <button onClick={() => setProxyModalOpen(false)}
                style={{ padding: '0.4rem 1rem', background: '#333', color: '#999', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleProxySave} disabled={proxySaving}
                style={{ padding: '0.4rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer', opacity: proxySaving ? 0.6 : 1 }}>
                {proxySaving ? '저장중...' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 프리셋 이미지 확대 모달 */}
      {presetZoom && (
        <div
          onClick={() => setPresetZoom(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out' }}
        >
          <img src={presetZoom} alt="프리셋 확대" style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain', borderRadius: '8px' }} />
        </div>
      )}
    </div>
  )
}

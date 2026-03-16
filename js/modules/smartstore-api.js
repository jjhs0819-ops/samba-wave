/**
 * 네이버 스마트스토어 Commerce API 브라우저측 래퍼
 * proxy-server.mjs의 /api/smartstore/* 엔드포인트를 호출
 *
 * 사용 방법:
 *   const api = new SmartStoreApi({ clientId, clientSecret })
 *   await api.authenticate()
 *   await api.registerProduct(productData)
 *
 * 참고: https://apicenter.commerce.naver.com/docs/commerce-api/current
 */

class SmartStoreApi {
  constructor(credentials = {}) {
    this.credentials = {
      clientId: credentials.clientId || '',
      clientSecret: credentials.clientSecret || ''
    }
    this.proxyBase = 'http://localhost:3001'
  }

  // ─────────────────────────────────────────────
  // 인증
  // ─────────────────────────────────────────────

  /** OAuth2 토큰 발급 (Client Credentials) */
  async authenticate(clientId, clientSecret) {
    const body = {
      clientId: clientId || this.credentials.clientId,
      clientSecret: clientSecret || this.credentials.clientSecret
    }
    const res = await fetch(`${this.proxyBase}/api/smartstore/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    return await res.json()
  }

  /** 현재 토큰 상태 확인 */
  async checkAuthStatus() {
    const res = await fetch(`${this.proxyBase}/api/smartstore/token`)
    return await res.json()
  }

  /** 토큰 캐시 초기화 */
  async clearAuth() {
    const res = await fetch(`${this.proxyBase}/api/smartstore/token`, { method: 'DELETE' })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 카테고리
  // ─────────────────────────────────────────────

  /** 카테고리 속성 조회 (leafCategoryId로 필수속성 확인) */
  async getCategoryAttributes(categoryId) {
    const res = await fetch(`${this.proxyBase}/api/smartstore/categories/${categoryId}/attributes`)
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 상품 CRUD
  // ─────────────────────────────────────────────

  /** 원부 상품 등록 */
  async registerProduct(productData) {
    const res = await fetch(`${this.proxyBase}/api/smartstore/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 원부 상품 목록 조회 */
  async getProducts(params = {}) {
    const query = new URLSearchParams({ ...this.credentials, ...params })
    const res = await fetch(`${this.proxyBase}/api/smartstore/products?${query}`)
    return await res.json()
  }

  /** 원부 상품 단건 조회 */
  async getProduct(originProductNo) {
    const query = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/smartstore/products/${originProductNo}?${query}`)
    return await res.json()
  }

  /** 원부 상품 수정 */
  async updateProduct(originProductNo, productData) {
    const res = await fetch(`${this.proxyBase}/api/smartstore/products/${originProductNo}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 원부 상품 삭제 */
  async deleteProduct(originProductNo) {
    const query = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/smartstore/products/${originProductNo}?${query}`, {
      method: 'DELETE'
    })
    return await res.json()
  }

  /** 채널 상품 판매상태 변경 */
  async updateSaleStatus(channelProductNo, statusType) {
    // statusType: 'SALE' | 'SUSPENSION' | 'OUTOFSTOCK'
    const res = await fetch(`${this.proxyBase}/api/smartstore/channel-products/${channelProductNo}/sale-status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, statusType })
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 데이터 매핑 (삼바웨이브 수집상품 → 스마트스토어 파라미터)
  // ─────────────────────────────────────────────

  /**
   * 수집상품 데이터를 스마트스토어 API 파라미터로 변환
   * @param {object} product - collectedProducts의 상품 객체
   * @param {object} defaults - IndexedDB settings의 smartstore_defaults
   * @param {string} accountId - 마켓 계정 ID (marketPrices 조회용)
   * @returns {object} 스마트스토어 API 파라미터
   */
  mapProductToSmartStoreParams(product, defaults = {}, accountId = '') {
    // 판매가: 계정별 가격 우선, 없으면 salePrice
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)

    // 대표 이미지 (첫 번째)
    const images = product.images || []
    const representativeImage = images[0] ? { url: images[0] } : undefined
    const optionalImages = images.slice(1, 10).map(url => ({ url }))

    // 옵션 구성
    let optionInfo = undefined
    if (product.options && product.options.length > 0) {
      // 옵션명 추출 (첫 번째 옵션의 attributes key들)
      const firstOpt = product.options[0]
      const optionGroupNames = firstOpt.attributes
        ? Object.keys(firstOpt.attributes)
        : (firstOpt.name ? [firstOpt.name] : ['옵션'])

      optionInfo = {
        optionCombinationGroupNames: {
          // 최대 3개 옵션그룹 지원
          optionGroupName1: optionGroupNames[0] || '',
          optionGroupName2: optionGroupNames[1] || '',
          optionGroupName3: optionGroupNames[2] || ''
        },
        optionCombinations: product.options.map((opt, idx) => {
          const vals = opt.attributes
            ? Object.values(opt.attributes)
            : [opt.value || opt.name || '']
          return {
            id: idx + 1,
            optionName1: vals[0] || '',
            optionName2: vals[1] || '',
            optionName3: vals[2] || '',
            stockQuantity: opt.stock ?? 999,
            price: 0, // 옵션 추가금액 (기본 0)
            usable: true
          }
        })
      }
    }

    const params = {
      originProduct: {
        statusType: 'SALE',
        leafCategoryId: defaults.leafCategoryId || '',
        name: (product.name || '').slice(0, 100), // 최대 100자
        detailContent: product.detailHtml || `<p>${product.name || ''}</p>`,
        images: {
          representativeImage,
          optionalImages: optionalImages.length > 0 ? optionalImages : undefined
        },
        salePrice: Math.round(salePrice),
        stockQuantity: product.stock ?? 999,
        ...(optionInfo && { optionInfo }),
        deliveryInfo: {
          deliveryType: 'DELIVERY',
          deliveryAttributeType: 'NORMAL',
          deliveryFee: {
            deliveryFeeType: defaults.deliveryFeeType || 'FREE',
            baseFee: defaults.baseFee ?? 0,
            freeConditionalAmount: defaults.freeConditionalAmount || undefined
          },
          returnDeliveryFee: defaults.returnDeliveryFee ?? 3000,
          exchangeDeliveryFee: defaults.exchangeDeliveryFee ?? 3000,
          deliveryCompanyCode: defaults.deliveryCompanyCode || 'CJGLS',
          outboundLocationId: defaults.outboundLocationId || undefined
        },
        returnExchangePolicy: {
          returnFeeType: 'PAID',
          returnFee: defaults.returnFee ?? 3000,
          exchangeFeeType: 'PAID',
          exchangeFee: defaults.exchangeFee ?? 3000,
          returnAddress: defaults.returnAddress || undefined
        },
        // 제조사/원산지
        ...(product.manufacturer && { manufacturer: product.manufacturer }),
        ...(product.origin && { originArea: { originAreaCode: '01', importer: product.origin } })
      },
      smartstoreChannelProduct: {
        naverShoppingRegistration: defaults.naverShoppingRegistration ?? true,
        channelProductDisplayStatusType: 'ON'
      }
    }

    return params
  }

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }
}

// 글로벌 인스턴스
const smartStoreApi = new SmartStoreApi()

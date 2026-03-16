/**
 * 쿠팡 WING(셀러) API 브라우저측 래퍼
 * proxy-server.mjs의 /api/coupang/* 엔드포인트를 호출
 *
 * 사용 방법:
 *   const api = new CoupangApi({ accessKey, secretKey, vendorId })
 *   await api.registerProduct(productData)
 *
 * 인증 방식: HMAC-SHA256 서명 (proxy-server에서 처리)
 * 참고: https://developers.coupangcorp.com/hc/ko
 */

class CoupangApi {
  constructor(credentials = {}) {
    this.credentials = {
      accessKey: credentials.accessKey || '',
      secretKey: credentials.secretKey || '',
      vendorId: credentials.vendorId || ''
    }
    this.proxyBase = 'http://localhost:3001'
  }

  // ─────────────────────────────────────────────
  // 인증 테스트
  // ─────────────────────────────────────────────

  /** 연결 테스트 — 쿠팡 API 자격증명 검증 */
  async testAuth(accessKey, secretKey, vendorId) {
    const res = await fetch(`${this.proxyBase}/api/coupang/test-auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        accessKey: accessKey || this.credentials.accessKey,
        secretKey: secretKey || this.credentials.secretKey,
        vendorId: vendorId || this.credentials.vendorId
      })
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 상품 CRUD
  // ─────────────────────────────────────────────

  /** 상품 등록 */
  async registerProduct(productData) {
    const res = await fetch(`${this.proxyBase}/api/coupang/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 상품 목록 조회 */
  async getProducts(params = {}) {
    const query = new URLSearchParams({ ...this.credentials, ...params })
    const res = await fetch(`${this.proxyBase}/api/coupang/products?${query}`)
    return await res.json()
  }

  /** 상품 단건 조회 */
  async getProduct(sellerProductId) {
    const query = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/coupang/products/${sellerProductId}?${query}`)
    return await res.json()
  }

  /** 상품 수정 */
  async updateProduct(sellerProductId, productData) {
    const res = await fetch(`${this.proxyBase}/api/coupang/products/${sellerProductId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 상품 삭제 */
  async deleteProduct(sellerProductId) {
    const query = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/coupang/products/${sellerProductId}?${query}`, {
      method: 'DELETE'
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 데이터 매핑 (삼바웨이브 수집상품 → 쿠팡 파라미터)
  // ─────────────────────────────────────────────

  /**
   * 수집상품 데이터를 쿠팡 API 파라미터로 변환
   * @param {object} product - collectedProducts의 상품 객체
   * @param {object} defaults - IndexedDB settings의 coupang_defaults
   * @param {string} accountId - 마켓 계정 ID (marketPrices 조회용)
   * @returns {object} 쿠팡 셀러 API 파라미터
   */
  mapProductToCoupangParams(product, defaults = {}, accountId = '') {
    // 판매가: 계정별 가격 우선, 없으면 salePrice
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)

    // 이미지 목록 (최대 10개)
    const images = (product.images || []).slice(0, 10).map(url => ({
      imageOrder: 0,
      imageType: 'REPRESENTATION',
      vendorPath: url
    }))
    if (images.length > 0) {
      // 첫 번째 이미지를 대표 이미지로 지정
      images[0].imageType = 'REPRESENTATION'
      // 나머지는 추가 이미지
      for (let i = 1; i < images.length; i++) {
        images[i].imageType = 'DETAIL'
        images[i].imageOrder = i
      }
    }

    // 옵션 구성 (쿠팡 items 배열)
    let items = []
    if (product.options && product.options.length > 0) {
      items = product.options.map((opt, idx) => {
        // 옵션 속성 추출
        const attrs = opt.attributes || {}
        const attrKeys = Object.keys(attrs)
        const attrVals = Object.values(attrs)

        // 쿠팡 attributes 배열 (옵션명-옵션값 쌍)
        const attributes = attrKeys.length > 0
          ? attrKeys.map((k, i) => ({
              attributeTypeName: k,
              attributeValueName: attrVals[i] || ''
            }))
          : [{ attributeTypeName: '옵션', attributeValueName: opt.value || opt.name || `옵션${idx + 1}` }]

        return {
          itemName: (product.name || '').slice(0, 100),
          originalPrice: Math.round(salePrice),
          salePrice: Math.round(salePrice),
          maximumBuyCount: defaults.maximumBuyCount || 99,
          maximumBuyForPerson: defaults.maximumBuyForPerson || 0,
          outboundShippingTimeDay: defaults.outboundShippingTimeDay || 2,
          unitCount: 1,
          attributes,
          images: images.length > 0 ? images : undefined,
          notices: [],
          contents: [{
            contentsType: 'TEXT',
            contentDetails: [{ content: product.detailHtml || `<p>${product.name || ''}</p>` }]
          }],
          searchTags: (product.tags || []).slice(0, 10),
          sku: opt.sku || `SKU-${Date.now()}-${idx}`,
          vendorInventoryManagement: false,
          stockQuantity: opt.stock ?? 999
        }
      })
    } else {
      // 옵션 없는 단일 상품
      items = [{
        itemName: (product.name || '').slice(0, 100),
        originalPrice: Math.round(salePrice),
        salePrice: Math.round(salePrice),
        maximumBuyCount: defaults.maximumBuyCount || 99,
        maximumBuyForPerson: defaults.maximumBuyForPerson || 0,
        outboundShippingTimeDay: defaults.outboundShippingTimeDay || 2,
        unitCount: 1,
        attributes: [],
        images: images.length > 0 ? images : undefined,
        notices: [],
        contents: [{
          contentsType: 'TEXT',
          contentDetails: [{ content: product.detailHtml || `<p>${product.name || ''}</p>` }]
        }],
        searchTags: (product.tags || []).slice(0, 10),
        sku: `SKU-${Date.now()}`,
        vendorInventoryManagement: false,
        stockQuantity: product.stock ?? 999
      }]
    }

    const params = {
      displayCategoryCode: defaults.displayCategoryCode || 56137,
      sellerProductName: (product.name || '').slice(0, 100),
      vendorId: this.credentials.vendorId || defaults.vendorId || '',
      saleStartedAt: defaults.saleStartedAt || '2020-01-01T00:00:00',
      saleEndedAt: defaults.saleEndedAt || '2099-01-01T00:00:00',
      displayProductName: (product.name || '').slice(0, 100),
      brand: product.brand || defaults.brand || '브랜드 없음',
      generalProductName: (product.name || '').slice(0, 100),
      productGroup: defaults.productGroup || '패션의류',
      // 배송 정보
      deliveryChargeType: defaults.deliveryChargeType || 'FREE',
      deliveryCharge: defaults.deliveryCharge ?? 0,
      freeShipOverAmount: defaults.freeShipOverAmount ?? 0,
      backwardDeliveryCharge: defaults.backwardDeliveryCharge ?? 3000,
      exchangeDeliveryCharge: defaults.exchangeDeliveryCharge ?? 3000,
      outboundShippingTimeDay: defaults.outboundShippingTimeDay || 2,
      unionDeliveryType: defaults.unionDeliveryType || 'UNION_DELIVERY',
      // 반품/교환
      returnCenterCode: defaults.returnCenterCode || '',
      returnChargeName: defaults.returnChargeName || '기본 반품',
      pickupAddress: defaults.pickupAddress || null,
      // 상품 항목
      items,
      // 공지 사항 (필수 정보)
      notices: defaults.notices || [],
      // 인증 정보
      certifications: defaults.certifications || [],
      // 원산지
      manufacturedAt: defaults.manufacturedAt || '',
      producedAt: defaults.producedAt || '',
      requiredDocuments: defaults.requiredDocuments || []
    }

    return params
  }

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }
}

// 글로벌 인스턴스
const coupangApi = new CoupangApi()

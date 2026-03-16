/**
 * 11번가 셀러 Open API 브라우저측 래퍼
 * proxy-server.mjs의 /api/11st/* 엔드포인트를 호출
 *
 * 사용 방법:
 *   const api = new ElevenStApi({ apiKey })
 *   await api.registerProduct(productData)
 *
 * 인증 방식: API Key (요청 헤더 openapikey)
 * 참고: https://openapi.11st.co.kr/openapi/OpenApiInfo.tmall
 */

class ElevenStApi {
  constructor(credentials = {}) {
    this.credentials = {
      apiKey: credentials.apiKey || ''
    }
    this.proxyBase = 'http://localhost:3001'
  }

  // ─────────────────────────────────────────────
  // 인증 테스트
  // ─────────────────────────────────────────────

  /** 연결 테스트 — 11번가 API 자격증명 검증 */
  async testAuth(apiKey) {
    const res = await fetch(`${this.proxyBase}/api/11st/test-auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: apiKey || this.credentials.apiKey
      })
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 상품 CRUD
  // ─────────────────────────────────────────────

  /** 상품 등록 */
  async registerProduct(productData) {
    const res = await fetch(`${this.proxyBase}/api/11st/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 상품 단건 조회 */
  async getProduct(productCode) {
    const query = new URLSearchParams({ apiKey: this.credentials.apiKey })
    const res = await fetch(`${this.proxyBase}/api/11st/products/${productCode}?${query}`)
    return await res.json()
  }

  /** 상품 수정 */
  async updateProduct(productCode, productData) {
    const res = await fetch(`${this.proxyBase}/api/11st/products/${productCode}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 상품 삭제 */
  async deleteProduct(productCode) {
    const query = new URLSearchParams({ apiKey: this.credentials.apiKey })
    const res = await fetch(`${this.proxyBase}/api/11st/products/${productCode}?${query}`, {
      method: 'DELETE'
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 데이터 매핑 (삼바웨이브 수집상품 → 11번가 XML)
  // ─────────────────────────────────────────────

  /**
   * 수집상품 데이터를 11번가 API XML 파라미터로 변환
   * @param {object} product - collectedProducts의 상품 객체
   * @param {object} defaults - IndexedDB settings의 11st_defaults
   * @param {string} accountId - 마켓 계정 ID (marketPrices 조회용)
   * @returns {string} 11번가 상품 등록 XML 문자열
   */
  mapProductToElevenStXml(product, defaults = {}, accountId = '') {
    // 판매가: 계정별 가격 우선, 없으면 salePrice
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)

    // 대표 이미지 URL (첫 번째)
    const mainImage = (product.images || [])[0] || ''

    // 상품명 (최대 100자)
    const productName = (product.name || '').slice(0, 100)

    // 카테고리 코드 (defaults 우선, 없으면 패션 기본값)
    const categoryId = defaults.categoryId || '10000'

    // 재고 수량
    const stock = product.stock ?? defaults.stock ?? 999

    // 배송비 유형: 무료(01), 유료(02), 조건부무료(03)
    const deliveryFeeType = defaults.deliveryFeeType || '01'
    const deliveryFee = defaults.deliveryFee || 0

    // 상품 상세 내용 (HTML → CDATA)
    const detailHtml = product.detailHtml || `<p>${productName}</p>`

    // 옵션 구성 XML 생성
    let optionXml = ''
    if (product.options && product.options.length > 0) {
      const optionItems = product.options.map((opt, idx) => {
        const optName = opt.value || opt.name || `옵션${idx + 1}`
        const optPrice = opt.additionalPrice || 0
        const optStock = opt.stock ?? stock
        return `
      <option>
        <optNm>${escapeXml(optName)}</optNm>
        <addAmt>${optPrice}</addAmt>
        <stock>${optStock}</stock>
      </option>`
      }).join('')
      optionXml = `<options>${optionItems}
    </options>`
    }

    // 11번가 상품 등록 XML 구성
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<product>
  <prdNm>${escapeXml(productName)}</prdNm>
  <dispCtgrNo>${categoryId}</dispCtgrNo>
  <sellerPrdCd>${product.id || 'PRD-' + Date.now()}</sellerPrdCd>
  <prdStatCd>new</prdStatCd>
  <minorSelFl>n</minorSelFl>
  <selQty>${stock}</selQty>
  <prdImage01>${escapeXml(mainImage)}</prdImage01>
  <htmlDetail><![CDATA[${detailHtml}]]></htmlDetail>
  <selPrc>${Math.round(salePrice)}</selPrc>
  <dlvFeeTypCd>${deliveryFeeType}</dlvFeeTypCd>
  <dlvFee>${deliveryFee}</dlvFee>
  <rtrvDlvFee>${defaults.returnFee || 3000}</rtrvDlvFee>
  <exchDlvFee>${defaults.exchangeFee || 3000}</exchDlvFee>
  <outWrhsNm>${escapeXml(defaults.warehouseName || '기본창고')}</outWrhsNm>
  ${optionXml}
</product>`

    return xml
  }

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }
}

/**
 * XML 특수문자 이스케이프
 * CDATA 구간이 아닌 일반 텍스트 노드에 사용
 */
function escapeXml(str) {
  if (!str) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

// 글로벌 인스턴스
const elevenStApi = new ElevenStApi()

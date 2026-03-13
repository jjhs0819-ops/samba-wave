/**
 * 롯데홈쇼핑(롯데아이몰) OpenAPI 브라우저측 래퍼
 * proxy-server.mjs의 /api/lottehome/* 엔드포인트를 호출
 *
 * 사용 방법:
 *   const api = new LotteHomeApi({ userId, password, agncNo, env })
 *   await api.authenticate()
 *   await api.registerGoods(productData)
 */

class LotteHomeApi {
  constructor(credentials = {}) {
    // 기본 자격증명 (settings에서 로드한 값)
    this.credentials = {
      userId: credentials.userId || '',
      password: credentials.password || '',
      agncNo: credentials.agncNo || '',
      env: credentials.env || 'test'
    }
    this.proxyBase = 'http://localhost:3001'
  }

  // ─────────────────────────────────────────────
  // 인증
  // ─────────────────────────────────────────────

  /** 인증키 발급 */
  async authenticate(userId, password, agncNo, env) {
    const body = {
      userId: userId || this.credentials.userId,
      password: password || this.credentials.password,
      agncNo: agncNo || this.credentials.agncNo,
      env: env || this.credentials.env
    }
    const res = await fetch(`${this.proxyBase}/api/lottehome/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    return await res.json()
  }

  /** 현재 인증 상태 확인 */
  async checkAuthStatus() {
    const res = await fetch(`${this.proxyBase}/api/lottehome/auth/status`)
    return await res.json()
  }

  /** 인증 캐시 초기화 */
  async clearAuth() {
    const res = await fetch(`${this.proxyBase}/api/lottehome/auth`, { method: 'DELETE' })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 기초정보 조회
  // ─────────────────────────────────────────────

  /** 브랜드 검색 */
  async searchBrands(brandName = '') {
    const params = new URLSearchParams({
      ...this.credentials,
      brnd_nm: brandName
    })
    const res = await fetch(`${this.proxyBase}/api/lottehome/brands?${params}`)
    return await res.json()
  }

  /** 전시카테고리 조회 */
  async searchCategories(dispTpCd = '', mdGsgrNo = '') {
    const params = new URLSearchParams({
      ...this.credentials,
      disp_tp_cd: dispTpCd,
      md_gsgr_no: mdGsgrNo
    })
    const res = await fetch(`${this.proxyBase}/api/lottehome/categories?${params}`)
    return await res.json()
  }

  /** MD상품군 목록 조회 */
  async searchMdGroups() {
    const params = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/lottehome/md-groups?${params}`)
    return await res.json()
  }

  /** 배송비정책 목록 조회 */
  async searchDeliveryPolicies() {
    const params = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/lottehome/delivery-policies?${params}`)
    return await res.json()
  }

  /** 배송비정책 등록 */
  async registerDeliveryPolicy(policyData) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/delivery-policies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...policyData })
    })
    return await res.json()
  }

  /** 출고지/반품지 목록 조회 */
  async searchDeliveryPlaces() {
    const params = new URLSearchParams(this.credentials)
    const res = await fetch(`${this.proxyBase}/api/lottehome/delivery-places?${params}`)
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 상품 CRUD
  // ─────────────────────────────────────────────

  /** 신규상품 등록 */
  async registerGoods(productData) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/goods`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 신규상품 수정 (임시상품번호 기준) */
  async updateNewGoods(goodsReqNo, productData) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/goods/new/${goodsReqNo}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 전시상품 수정 (상품번호 기준) */
  async updateDisplayGoods(goodsNo, productData) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/goods/display/${goodsNo}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...productData })
    })
    return await res.json()
  }

  /** 판매상태 변경 (10=판매진행, 20=품절, 30=영구중단) */
  async updateGoodsSaleStatus(goodsNo, saleStatCd) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/goods/${goodsNo}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, sale_stat_cd: saleStatCd })
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 재고
  // ─────────────────────────────────────────────

  /** 재고 수정 */
  async updateStock(goodsNo, itemNo, invQty) {
    const res = await fetch(`${this.proxyBase}/api/lottehome/stock`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, goods_no: goodsNo, item_no: itemNo, inv_qty: invQty })
    })
    return await res.json()
  }

  /** 재고 조회 */
  async searchStock(goodsNo) {
    const params = new URLSearchParams({ ...this.credentials, goods_no: goodsNo || '' })
    const res = await fetch(`${this.proxyBase}/api/lottehome/stock?${params}`)
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 데이터 매핑 (삼바웨이브 상품 → 롯데홈쇼핑 파라미터)
  // ─────────────────────────────────────────────

  /**
   * 수집상품 데이터를 롯데홈쇼핑 API 파라미터로 변환
   * @param {object} product - collectedProducts의 상품 객체
   * @param {object} defaults - IndexedDB settings의 lottehome_defaults
   * @param {string} accountId - 마켓 계정 ID (marketPrices 조회용)
   * @returns {object} 롯데홈쇼핑 API 파라미터
   */
  mapProductToLotteParams(product, defaults = {}, accountId = '') {
    const params = {}

    // ── 기본 상품 정보 매핑 ──
    params.goods_nm = product.name || ''

    // 판매가: 계정별 가격 우선, 없으면 salePrice
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)
    params.sale_prc = Math.round(salePrice)

    // 이미지 매핑 (최대 6장)
    const images = product.images || []
    if (images[0]) params.img_url = images[0]
    for (let i = 1; i <= 5; i++) {
      if (images[i]) params[`img_url${i}`] = images[i]
    }

    // 상세페이지 HTML
    if (product.detailHtml) params.dtl_info_fcont = product.detailHtml

    // 제조사 / 원산지
    if (product.manufacturer) params.mfcp_nm = product.manufacturer
    if (product.origin) params.orpl_nm = product.origin

    // ── 옵션 매핑 ──
    if (product.options && product.options.length > 0) {
      // 옵션명: "컬러:사이즈" 형식 (콜론 구분)
      const firstOpt = product.options[0]
      if (firstOpt.attributes) {
        params.opt_nm = Object.keys(firstOpt.attributes).join(':')
      } else if (firstOpt.name) {
        // "컬러 / 사이즈" → "컬러:사이즈" 변환
        params.opt_nm = firstOpt.name.replace(/\s*\/\s*/g, ':')
      }

      // item_list: "옵션값1,옵션값2,재고,업체단품번호:..." 포맷
      const itemLines = product.options.map((opt, idx) => {
        const optVals = opt.attributes
          ? Object.values(opt.attributes).join(',')
          : (opt.value || opt.name || '')
        const stock = opt.stock || 999
        const corpItemNo = `${product.id}_${idx}` // 업체단품번호 자동생성
        return `${optVals},${stock},${corpItemNo}`
      })
      params.item_list = itemLines.join(':')
    }

    // ── lottehome_defaults 프리셋 병합 ──
    const defaultKeys = [
      'pur_shp_cd', 'sale_shp_cd', 'tdf_sct_cd', 'dlv_polc_no',
      'corp_dlvp_sn', 'corp_rls_pl_sn', 'inv_mgmt_yn', 'item_mgmt_yn',
      'dlv_proc_tp_cd', 'gift_pkg_yn', 'exch_rtgs_sct_cd', 'dlv_mean_cd',
      'dlv_goods_sct_cd', 'dlv_dday', 'byr_age_lmt_cd', 'sum_pkg_psb_yn',
      'brnd_no', 'md_gsgr_no', 'disp_no', 'mrgn_rt'
    ]
    for (const key of defaultKeys) {
      if (defaults[key] !== undefined && defaults[key] !== '') {
        params[key] = defaults[key]
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
const lotteHomeApi = new LotteHomeApi()

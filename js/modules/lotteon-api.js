/**
 * 롯데ON Open API 브라우저측 래퍼
 * proxy-server.mjs의 /api/lotteon/* 엔드포인트를 호출
 *
 * 인증 방식: Authorization: Bearer {apiKey}
 * 기본 URL: https://openapi.lotteon.com
 */

class LotteonApi {
  constructor(credentials = {}) {
    this.credentials = {
      apiKey: credentials.apiKey || '',
      trGrpCd: credentials.trGrpCd || '',  // identity API에서 자동 획득
      trNo: credentials.trNo || '',          // identity API에서 자동 획득
      owhpNo: credentials.owhpNo || '',      // 출고지번호
      dvCstPolNo: credentials.dvCstPolNo || '', // 배송비정책번호
      rtrpNo: credentials.rtrpNo || ''       // 회수지번호
    }
    this.proxyBase = 'http://localhost:3001'
  }

  /** 연결 테스트 — 거래처 정보 조회 (trGrpCd, trNo 자동 획득) */
  async testAuth(apiKey) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/test-auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: apiKey || this.credentials.apiKey })
    })
    const data = await res.json()
    // 인증 성공 시 거래처 정보 자동 저장
    if (data.success && data.data?.data) {
      this.credentials.trGrpCd = data.data.data.trGrpCd
      this.credentials.trNo = data.data.data.trNo
    }
    return data
  }

  /** 상품 등록 */
  async registerProduct(productData) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/products`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...productData })
    })
    return await res.json()
  }

  /** 상품 단건 조회 */
  async getProduct(spdNo) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/products/${spdNo}?apiKey=${this.credentials.apiKey}`)
    return await res.json()
  }

  /** 브랜드 검색 (브랜드명으로 brnd_id 조회) */
  async searchBrand(keyword, apiKey) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/brands?apiKey=${encodeURIComponent(apiKey || this.credentials.apiKey)}&keyword=${encodeURIComponent(keyword)}&limit=20`)
    return await res.json()
  }

  /** 표준카테고리 조회 */
  async getStandardCategories(catId, depth, apiKey) {
    const params = new URLSearchParams({ apiKey: apiKey || this.credentials.apiKey })
    if (catId) params.set('catId', catId)
    if (depth) params.set('depth', depth)
    const res = await fetch(`${this.proxyBase}/api/lotteon/categories/standard?${params}`)
    return await res.json()
  }

  /** 전시카테고리 조회 */
  async getDisplayCategories(catId, parentId, apiKey) {
    const params = new URLSearchParams({ apiKey: apiKey || this.credentials.apiKey })
    if (catId) params.set('catId', catId)
    if (parentId) params.set('parentId', parentId)
    const res = await fetch(`${this.proxyBase}/api/lotteon/categories/display?${params}`)
    return await res.json()
  }

  /** 속성 조회 */
  async getAttributes(attrId, apiKey) {
    const params = new URLSearchParams({ apiKey: apiKey || this.credentials.apiKey })
    if (attrId) params.set('attrId', attrId)
    const res = await fetch(`${this.proxyBase}/api/lotteon/attributes?${params}`)
    return await res.json()
  }

  /** 상품 목록 조회 */
  async getProductList(params) {
    const { trGrpCd, trNo } = this.credentials
    const body = {
      apiKey: this.credentials.apiKey,
      trGrpCd: trGrpCd || 'SR',
      trNo: trNo || '',
      ...params
    }
    const res = await fetch(`${this.proxyBase}/api/lotteon/products/list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    return await res.json()
  }

  /** 상품 상세조회 */
  async getProductDetail(spdNo) {
    const { trGrpCd, trNo } = this.credentials
    const res = await fetch(`${this.proxyBase}/api/lotteon/products/detail`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        trGrpCd: trGrpCd || 'SR',
        trNo: trNo || '',
        spdNo
      })
    })
    return await res.json()
  }

  /** 승인 상품 수정 */
  async updateProduct(spdLst) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/products/update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, spdLst })
    })
    return await res.json()
  }

  /** 단품 재고 변경 */
  async updateStock(itmStkLst) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, itmStkLst })
    })
    return await res.json()
  }

  /** 단품 가격 변경 */
  async updatePrice(itmPrcLst) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/price`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, itmPrcLst })
    })
    return await res.json()
  }

  /** 상품 판매상태 변경 (slStatCd: SALE | SOUT | END) */
  async changeProductStatus(spdLst) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, spdLst })
    })
    return await res.json()
  }

  /** 승인상태변경이력 조회 */
  async getApproveHistory(spdNo, hstStrtDttm, hstEndDttm) {
    const { trGrpCd, trNo } = this.credentials
    const res = await fetch(`${this.proxyBase}/api/lotteon/approve-history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        trGrpCd: trGrpCd || 'SR',
        trNo: trNo || '',
        spdNo,
        hstStrtDttm,
        hstEndDttm
      })
    })
    return await res.json()
  }

  /** 상품 QnA 조회 */
  async getQnaList(params) {
    const { trGrpCd, trNo } = this.credentials
    const res = await fetch(`${this.proxyBase}/api/lotteon/qna/list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        trGrpCd: trGrpCd || 'SR',
        trNo: trNo || '',
        ...params
      })
    })
    return await res.json()
  }

  /** 상품 QnA 답변 등록 */
  async replyQna(ansInfo) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/qna/reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ansInfo })
    })
    return await res.json()
  }

  /** 추가상품 재고 변경 */
  async updateAdtnStock(adtnStkLst) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/adtn-stock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, adtnStkLst })
    })
    return await res.json()
  }

  /** 표준카테고리 단위용량정보 조회 */
  async getUnitCapa(scatNo) {
    const params = new URLSearchParams({ apiKey: this.credentials.apiKey })
    if (scatNo) params.set('scatNo', scatNo)
    const res = await fetch(`${this.proxyBase}/api/lotteon/unitcapa?${params}`)
    return await res.json()
  }

  /** 셀러 주문 혜택 정보 조회 */
  async getOrderBenefit(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/order/benefit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 취소요청(완료) 목록 조회 */
  async getCancelList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/cancel-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 야놀자 결제 취소 */
  async cancelYaPay(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/ya-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 반품요청/접수 목록조회 */
  async getReturnList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/return-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 반품(요청)취소 목록조회 */
  async getReturnWithdrawList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/return-withdraw-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 교환요청/접수 목록조회 */
  async getExchangeList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/exchange-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 교환(요청)취소 목록조회 */
  async getExchangeWithdrawList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/exchange-withdraw-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 미수령신고 조회 */
  async getNonReceiptList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/non-receipt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 미수령신고 철회요청처리 */
  async cancelNonReceipt(odNo, odSeq, procSeq, nrcptDeclWhdrReqCnts, lrtrNo) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/non-receipt-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        odNo, odSeq, procSeq, nrcptDeclWhdrReqCnts,
        ...(lrtrNo ? { lrtrNo } : {})
      })
    })
    return await res.json()
  }

  /** 구매확정후취소 */
  async cancelAfterPurchaseConfirm(odNo, odSeq, procSeq, slrRsnCd, slrRsnCnts, lrtrNo) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/pur-cfrm-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        odNo, odSeq, procSeq,
        ...(slrRsnCd ? { slrRsnCd } : {}),
        ...(slrRsnCnts ? { slrRsnCnts } : {}),
        ...(lrtrNo ? { lrtrNo } : {})
      })
    })
    return await res.json()
  }

  /** 구매확정후취소 목록조회 */
  async getPurCfrmCancelList(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/pur-cfrm-cancel-list`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 취소요청 승인처리 */
  async approveCancelRequest(odNo, clmNo, itemList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/cancel-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, odNo, clmNo, itemList })
    })
    return await res.json()
  }

  /** 취소요청 거부처리 */
  async rejectCancelRequest(odNo, clmNo, itemList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/cancel-reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, odNo, clmNo, itemList })
    })
    return await res.json()
  }

  /** 클레임혜택 취소 조회 */
  async getClaimBenefitCancel(odNo, clmNo, lrtrNo) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/benefit-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        apiKey: this.credentials.apiKey,
        odNo,
        ...(clmNo ? { clmNo } : {}),
        ...(lrtrNo ? { lrtrNo } : {})
      })
    })
    return await res.json()
  }

  /** 판매자 직접취소 */
  async directCancel(odNo, itemList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/direct-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, odNo, itemList })
    })
    return await res.json()
  }

  // ─── 배송(Delivery) 모듈 ────────────────────────────

  /** 출고/회수지시 조회 */
  async getDeliveryOrders(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/delivery/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  /** 출고/회수지시 연동완료 통보 */
  async notifyDeliveryComplete(ifCompleteList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/delivery/if-complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ifCompleteList })
    })
    return await res.json()
  }

  /** 배송상태 통보 V1 */
  async notifyDeliveryStatus(deliveryProgressStateList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/delivery/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, deliveryProgressStateList })
    })
    return await res.json()
  }

  /** 배송상태 통보 V2 (복수 송장 지원, 최대 500건) */
  async notifyDeliveryStatusV2(deliveryProgressStateList) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/delivery/status-v2`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, deliveryProgressStateList })
    })
    return await res.json()
  }

  /** 배송상태 조회 */
  async searchDeliveryStatus(params) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/delivery/status-search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, ...params })
    })
    return await res.json()
  }

  // ─── 정산(Settle) 모듈 ──────────────────────────────

  /** 상품별 주문내역 조회 (startDate, endDate: yyyymmdd) */
  async getSettleProduct(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/product`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 상품별 할인내역 조회 (startDate, endDate: yyyymmdd) */
  async getSettleDiscount(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/discount`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 상품별 수수료내역 조회 (startDate, endDate: yyyymmdd) */
  async getSettleCommission(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/commission`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 중개셀러 통합정보 조회 (startDate, endDate: yyyymmdd) */
  async getSettleItmdSales(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/itmd-sales`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 공통코드 그룹 목록 조회 */
  async getGroupCodes() {
    const res = await fetch(`${this.proxyBase}/api/lotteon/common/group-codes?apiKey=${this.credentials.apiKey}`)
    return await res.json()
  }

  /** 공통코드 상세 조회 (grpCd 필수, langCd 기본 'ko') */
  async getDetailCodes(grpCd, langCd = 'ko') {
    const params = new URLSearchParams({ apiKey: this.credentials.apiKey, grpCd, langCd })
    const res = await fetch(`${this.proxyBase}/api/lotteon/common/detail-codes?${params}`)
    return await res.json()
  }

  /** 상품별 배송비내역 조회 (startDate, endDate: yyyymmdd) */
  async getSettleDelivery(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/delivery`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 상품별 차감내역 조회 (startDate, endDate: yyyymmdd) */
  async getSettleSubtraction(startDate, endDate) {
    const res = await fetch(`${this.proxyBase}/api/lotteon/settle/subtraction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: this.credentials.apiKey, startDate, endDate })
    })
    return await res.json()
  }

  /** 발송가능여부 조회 */
  async checkSendPossible(odNo, odSeq, procSeq) {
    const params = new URLSearchParams({
      apiKey: this.credentials.apiKey,
      odNo,
      odSeq,
      procSeq
    })
    const res = await fetch(`${this.proxyBase}/api/lotteon/claim/send-possible?${params}`)
    return await res.json()
  }

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }

  /**
   * 수집상품 데이터를 롯데ON 상품 등록 파라미터로 변환
   * @param {object} product - collectedProducts의 상품 객체
   * @param {object} defaults - IndexedDB settings의 lotteon_credentials
   * @param {string} accountId - 마켓 계정 ID
   * @returns {object} 롯데ON 상품 등록 API 파라미터
   */
  mapProductToLotteonParams(product, defaults = {}, accountId = '') {
    const creds = { ...this.credentials, ...defaults }

    // 판매가
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)

    // 이미지 목록 → 단품이미지 + 상품파일
    const images = (product.images || []).slice(0, 10)
    const pdFileLst = images.map(url => ({
      fileTypCd: 'PD',
      fileDvsCd: 'WDTH',
      origImgFileNm: url
    }))

    // 단품이미지 (첫 번째가 대표)
    const itmImgLst = images.map((url, idx) => ({
      epsrTypCd: 'IMG',
      epsrTypDtlCd: 'IMG_SQRE',
      origImgFileNm: url,
      rprtImgYn: idx === 0 ? 'Y' : 'N'
    }))

    // 단품 목록 구성
    let itmLst = []
    if (product.options && product.options.length > 0) {
      itmLst = product.options.map((opt, idx) => ({
        eitmNo: opt.sku || `OPT-${Date.now()}-${idx}`,
        dpYn: 'Y',
        sortSeq: idx + 1,
        itmOptLst: [{
          optNm: Object.keys(opt.attributes || {})[0] || '옵션',
          optVal: opt.value || opt.name || `옵션${idx + 1}`
        }],
        itmImgLst,
        slPrc: Math.round(salePrice),
        stkQty: opt.stock ?? 999
      }))
    } else {
      itmLst = [{
        eitmNo: product.id ? `${product.id}-01` : `PRD-${Date.now()}-01`,
        dpYn: 'Y',
        sortSeq: 1,
        itmOptLst: [],
        itmImgLst,
        slPrc: Math.round(salePrice),
        stkQty: product.stock ?? 999
      }]
    }

    // 판매 시작/종료일시
    const now = new Date()
    const slStrtDttm = now.toISOString().replace(/[-T:]/g, '').slice(0, 14)
    const slEndDttm = '20991231235959'

    const params = {
      spdLst: [{
        trGrpCd: creds.trGrpCd || 'SR',
        trNo: creds.trNo || '',
        scatNo: creds.scatNo || defaults.scatNo || '',       // 표준카테고리번호 (카테고리맵핑에서)
        dcatLst: [{
          mallCd: 'LTON',
          lfDcatNo: creds.lfDcatNo || defaults.lfDcatNo || '' // 전시카테고리번호
        }],
        epdNo: product.id ? String(product.id).slice(0, 30) : '',
        slTypCd: 'GNRL',
        pdTypCd: 'GNRL_GNRL',
        spdNm: (product.name || '').slice(0, 150),
        brdNo: product.brandNo || '',
        mfcrNm: product.brand || '',
        oplcCd: 'KR',                                        // 원산지: 국내
        tdfDvsCd: '01',                                      // 과세
        slStrtDttm,
        slEndDttm,
        pdItmsInfo: {
          pdItmsCd: creds.pdItmsCd || '38',                  // 기타(재화) 기본값
          pdItmsArtlLst: [
            { pdArtlCd: '0160', pdArtlCnts: product.name || '상품명' },
            { pdArtlCd: '0060', pdArtlCnts: '대한민국' },
            { pdArtlCd: '0070', pdArtlCnts: product.brand || '제조자 정보 없음' },
            { pdArtlCd: '0080', pdArtlCnts: '소비자 기본법에 따름' },
            { pdArtlCd: '0090', pdArtlCnts: product.brand || '판매자 문의' }
          ]
        },
        purPsbQtyInfo: {
          itmByMinPurYn: 'N',
          itmByMaxPurPsbQtyYn: 'N',
          maxPurLmtTypCd: 'PERIOD'
        },
        ageLmtCd: '0',
        prstPsbYn: 'N',
        prstPckPsbYn: 'N',
        prstMsgPsbYn: 'N',
        prcCmprEpsrYn: 'Y',
        pdStatCd: 'NEW',
        dpYn: 'Y',
        scKwdLst: (product.tags || []).slice(0, 5),
        pdFileLst: pdFileLst.length > 0 ? pdFileLst : undefined,
        epnLst: [{
          pdEpnTypCd: 'DSCRP',
          cnts: product.detailHtml || `<p>${product.name || ''}</p>`
        }],
        cnclPsbYn: 'Y',
        dmstOvsDvDvsCd: 'DMST',
        dvProcTypCd: 'LO_ENTP',
        dvPdTypCd: 'GNRL',
        sndBgtNday: 2,
        dvRgsprGrpCd: 'GN101',
        dvMnsCd: 'DPCL',
        owhpNo: creds.owhpNo || '',                          // 출고지번호
        dvCstPolNo: creds.dvCstPolNo || '',                  // 배송비정책번호
        cmbnDvPsbYn: 'Y',
        rtngPsbYn: 'Y',
        xchgPsbYn: 'Y',
        cmbnRtngPsbYn: 'Y',
        rtngRtrvPsbYn: 'Y',
        rtrpNo: creds.rtrpNo || '',                          // 회수지번호
        stkMgtYn: 'Y',
        sitmYn: product.options && product.options.length > 0 ? 'Y' : 'N',
        itmLst,
        rtrvTypCd: 'ENTP_RTRV'
      }]
    }

    return params
  }
}

// 글로벌 인스턴스
const lotteonApi = new LotteonApi()

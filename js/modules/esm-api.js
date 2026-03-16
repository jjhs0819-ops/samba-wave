/**
 * ESM Trading API (지마켓 / 옥션) 브라우저측 래퍼
 * proxy-server.mjs의 /api/esm/* 엔드포인트를 호출
 *
 * 인증 방식: JWT HMAC-SHA256 (프록시 서버에서 생성)
 *   - Header: { alg, typ, kid(masterId) }
 *   - Payload: { iss(domain), sub:'sell', aud:'sa.esmplus.com', ssi:'siteId:sellerId' }
 * 기본 URL: https://sa2.esmplus.com
 * 문서: https://etapi.gmarket.com
 *
 * siteId: 'A' = 옥션, 'G' = G마켓
 */

class EsmApi {
  /**
   * @param {object} credentials
   * @param {string} credentials.masterId   - ESM+ 마스터 ID
   * @param {string} credentials.secretKey  - ESM+ 시크릿 키
   * @param {string} credentials.siteId     - 'A'(옥션) | 'G'(G마켓)
   * @param {string} credentials.sellerId   - 판매자 ID
   * @param {string} [credentials.domain]   - 판매자 도메인 (기본: 'samba-wave')
   */
  constructor(credentials = {}) {
    this.credentials = {
      masterId:  credentials.masterId  || '',
      secretKey: credentials.secretKey || '',
      siteId:    credentials.siteId    || 'G',  // 'A'(옥션) | 'G'(G마켓)
      sellerId:  credentials.sellerId  || '',
      domain:    credentials.domain    || 'samba-wave'
    }
    this.proxyBase = 'http://localhost:3001'
  }

  /** 인증 정보를 body에 포함하는 공통 POST 헬퍼 */
  async _post(endpoint, params = {}) {
    const res = await fetch(`${this.proxyBase}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.credentials, ...params })
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // CS API
  // ─────────────────────────────────────────────

  /**
   * 판매자문의 조회
   * @param {object} params
   * @param {number} params.qnaType    - 1:옥션일반, 2:옥션비밀글, 3:전체
   * @param {number} params.status     - 1:전체, 2:미처리, 3:처리완료, 4:처리중, 5:중복
   * @param {number} params.type       - 조회기준 (현재 1:접수일만 지원)
   * @param {string} params.startDate  - 'YYYY-MM-DD' (7일 이내)
   * @param {string} params.endDate    - 'YYYY-MM-DD'
   */
  async getQnaList(params) {
    return await this._post('/api/esm/cs/qna-list', params)
  }

  /**
   * 판매자문의 답변
   * @param {object} params
   * @param {string} params.messageNo    - 조회에서 받은 문의번호
   * @param {string} params.token        - 조회에서 받은 토큰
   * @param {number} params.answerStatus - 1:처리중, 2:처리완료
   * @param {string} params.title        - 답변 제목
   * @param {string} params.comments     - 답변 내용 (1,000byte 이내)
   */
  async replyQna(params) {
    return await this._post('/api/esm/cs/qna-reply', params)
  }

  /**
   * 긴급알리미 조회
   * @param {object} params
   * @param {number} params.status     - 1:전체, 2:미처리, 3:처리완료
   * @param {number} params.type       - 1:접수일 (접수일만 지원)
   * @param {string} params.startDate  - 'YYYY-MM-DD'
   * @param {string} params.endDate    - 'YYYY-MM-DD'
   */
  async getEmergencyList(params) {
    return await this._post('/api/esm/cs/emergency-list', params)
  }

  /**
   * 긴급알리미 답변
   * @param {object} params
   * @param {string} params.emerMessageNo  - 조회에서 받은 문의번호
   * @param {number} params.answerStatus   - 1:처리중, 2:처리완료
   * @param {string} params.comments       - 답변 내용
   */
  async replyEmergency(params) {
    return await this._post('/api/esm/cs/emergency-reply', params)
  }

  /**
   * ESM 공지사항 조회 (월 단위)
   * @param {object} params
   * @param {number} params.siteType   - 1:ESM+전체, 2:옥션, 3:G마켓
   * @param {string} params.startDate  - 'YYYY-MM-DD'
   * @param {string} params.endDate    - 'YYYY-MM-DD'
   */
  async getNotices(params) {
    return await this._post('/api/esm/cs/notices', params)
  }

  // ─────────────────────────────────────────────
  // 주문/배송 API
  // ─────────────────────────────────────────────

  /**
   * 입금확인중 주문조회 (무통장 입금)
   * @param {object} params
   * @param {number} params.siteType          - 1:옥션, 2:G마켓
   * @param {string} params.requestDateFrom   - 'YYYY-MM-DD hh:mm' (31일 이내)
   * @param {string} params.requestDateTo     - 'YYYY-MM-DD hh:mm'
   * @param {number} [params.pageIndex]
   * @param {number} [params.pageSize]
   */
  async getPreRequestOrders(params) {
    return await this._post('/api/esm/order/pre-request', params)
  }

  /**
   * 주문조회
   * @param {object} params
   * @param {number} params.siteType           - 1:옥션, 2:G마켓
   * @param {number} params.orderStatus        - 0:주문번호, 1~5:상태별, 6:결제번호
   * @param {number} params.requestDateType    - 1:주문일, 2:결제완료일 등
   * @param {string} params.requestDateFrom    - 'YYYY-MM-DD hh:mm'
   * @param {string} params.requestDateTo      - 'YYYY-MM-DD hh:mm'
   */
  async getOrders(params) {
    return await this._post('/api/esm/order/list', params)
  }

  /**
   * 주문확인 (→ 배송준비중)
   * @param {number|string} orderNo  - 주문번호
   * @param {object} [body]          - SellerOrderNo, SellerItemNo (선택)
   */
  async confirmOrder(orderNo, body = {}) {
    return await this._post('/api/esm/order/confirm', { orderNo, ...body })
  }

  /**
   * 발송예정일 등록
   * @param {object} params
   * @param {number} params.orderNo              - 주문번호
   * @param {number} params.ReasonType           - 1:재고부족, 2:고객요청, 3:기타
   * @param {string} params.ShippingExpectedDate - 'YYYY-MM-DD' (+1일~)
   * @param {string} [params.ReasonDetail]       - 지연사유 직접입력
   */
  async setShippingExpectedDate(params) {
    return await this._post('/api/esm/order/shipping-expected', params)
  }

  /**
   * 발송처리 (송장번호 등록)
   * @param {object} params
   * @param {number} params.OrderNo              - 주문번호
   * @param {string} params.ShippingDate         - 'YYYY-MM-DDThh:mm:ss'
   * @param {number} params.DeliveryCompanyCode  - 택배사 코드
   * @param {string} params.InvoiceNo            - 송장번호
   */
  async shipOrder(params) {
    return await this._post('/api/esm/order/ship', params)
  }

  /**
   * 배송완료 처리
   * @param {number|string} orderNo - 주문번호
   */
  async completeDelivery(orderNo) {
    return await this._post('/api/esm/order/delivery-complete', { orderNo })
  }

  /**
   * 주문상태 조회
   * @param {object} params
   * @param {number} [params.orderNo]                    - 주문번호 (기간조회 시 0)
   * @param {number} [params.SearchDateConditionType]    - 1~9: 결제일~취소일
   * @param {string} [params.FromDate]                   - 'YYYY-MM-DD' (7일 이내)
   * @param {string} [params.ToDate]                     - 'YYYY-MM-DD'
   * @param {number} [params.Page]                       - 페이지번호
   */
  async getOrderStatus(params) {
    return await this._post('/api/esm/order/status', params)
  }

  /**
   * 배송진행정보 조회 (클레임 히스토리 포함)
   * @param {number|string} orderNo - 주문번호
   */
  async getDeliveryProgress(orderNo) {
    return await this._post('/api/esm/order/delivery-progress', { orderNo })
  }

  // ─────────────────────────────────────────────
  // 클레임 API
  // ─────────────────────────────────────────────

  /**
   * 취소조회
   * @param {object} params
   * @param {number} params.SiteType     - 1:옥션, 3:G마켓
   * @param {number} params.CancelStatus - 0:전체, 1:요청, 2:처리중, 3:완료, 4:철회, 5:직권환불, 6:송금후취소
   * @param {number} params.Type         - 0:주문번호, 1:장바구니, 2:신청일, 3:완료일, 4:결제일
   * @param {string} params.StartDate    - 'YYYY-MM-DD' (7일 이내)
   * @param {string} params.EndDate      - 'YYYY-MM-DD'
   */
  async getCancelList(params) {
    return await this._post('/api/esm/claim/cancel-list', params)
  }

  /**
   * 취소승인
   * @param {number|string} orderNo  - 주문번호
   * @param {number} siteType        - 1:옥션, 2:G마켓
   */
  async approveCancel(orderNo, siteType) {
    return await this._post('/api/esm/claim/cancel-approve', { orderNo, SiteType: siteType })
  }

  /**
   * 판매취소 (품절)
   * @param {number|string} orderNo  - 주문번호
   * @param {number} siteType        - 1:옥션, 2:G마켓
   */
  async cancelSoldOut(orderNo, siteType) {
    return await this._post('/api/esm/claim/cancel-soldout', { orderNo, SiteType: siteType })
  }

  /**
   * 옥션 거래완료 후 환불 (옥션 전용)
   * @param {number|string} orderNo - 주문번호
   */
  async cancelAfterRemittance(orderNo) {
    return await this._post('/api/esm/claim/cancel-after-remittance', { orderNo, SiteType: 1 })
  }

  /**
   * 교환조회
   * @param {object} params
   * @param {number} params.SiteType       - 1:옥션, 2:G마켓
   * @param {number} params.Type           - 0:주문번호, 1:장바구니, 2:교환신청일 등
   * @param {number} params.ExchangeStatus - 1:요청, 2:승인, 3:수거, 4:처리완료, 5:철회
   * @param {string} [params.StartDate]    - 'YYYY-MM-DD'
   * @param {string} [params.EndDate]      - 'YYYY-MM-DD'
   */
  async getExchangeList(params) {
    return await this._post('/api/esm/claim/exchange-list', params)
  }

  /**
   * 교환수거 송장등록
   * @param {number|string} orderNo
   * @param {object} params
   * @param {number} params.DeliveryCompCode - 택배사 5자리 코드
   * @param {string} params.InvoiceNo        - 송장번호
   * @param {number} params.SiteType         - 1:옥션, 2:G마켓
   */
  async registerExchangePickup(orderNo, params) {
    return await this._post('/api/esm/claim/exchange-pickup', { orderNo, ...params })
  }

  /**
   * 교환수거완료 처리
   * @param {number|string} orderNo
   * @param {number} siteType              - 1:옥션, 2:G마켓
   * @param {string} [pickupCompleteDate]  - 'YYYY-MM-DD'
   */
  async completeExchangePickup(orderNo, siteType, pickupCompleteDate) {
    return await this._post('/api/esm/claim/exchange-pickup-complete', { orderNo, SiteType: siteType, PickupCompleteDate: pickupCompleteDate })
  }

  /**
   * 교환재발송 송장등록
   * @param {number|string} orderNo
   * @param {object} params
   * @param {number} params.DeliveryCompCode - 택배사 5자리 코드
   * @param {string} params.InvoiceNo        - 송장번호
   * @param {number} params.SiteType         - 1:옥션, 2:G마켓
   */
  async registerExchangeResend(orderNo, params) {
    return await this._post('/api/esm/claim/exchange-resend', { orderNo, ...params })
  }

  /**
   * 교환재발송 배송완료
   * @param {number|string} orderNo
   * @param {number} siteType              - 1:옥션, 2:G마켓
   * @param {string} [pickupCompleteDate]  - 'YYYY-MM-DD'
   */
  async completeExchangeResend(orderNo, siteType, pickupCompleteDate) {
    return await this._post('/api/esm/claim/exchange-resend-complete', { orderNo, SiteType: siteType, PickupCompleteDate: pickupCompleteDate })
  }

  /**
   * 미수령신고 조회 (30일 이내)
   * @param {object} params
   * @param {string} params.SearchType  - '0':주문번호 조회, '1':미수령신고일 조회
   * @param {number} [params.orderNo]   - 주문번호
   * @param {string} [params.StartDate] - 'YYYY-MM-DD'
   * @param {string} [params.EndDate]   - 'YYYY-MM-DD'
   */
  async getNonReceiptList(params) {
    return await this._post('/api/esm/claim/non-receipt', params)
  }

  // ─────────────────────────────────────────────
  // 정산조회 API
  // ─────────────────────────────────────────────

  /**
   * 판매대금 정산조회
   * @param {object} params
   * @param {string} params.SiteType      - 'A':옥션, 'G':G마켓
   * @param {string} params.SrchType      - 기간검색 구분 D1~D10
   * @param {string} params.SrchStartDate - 'YYYY-MM-DD'
   * @param {string} params.SrchEndDate   - 'YYYY-MM-DD'
   * @param {number} params.PageNo        - 페이지번호
   * @param {number} params.PageRowCnt    - 페이지당 건수
   */
  async getSettleOrder(params) {
    return await this._post('/api/esm/settle/order', params)
  }

  /**
   * 배송비 정산조회
   * @param {object} params
   * @param {string} params.SiteType      - 'A':옥션, 'G':G마켓
   * @param {string} params.SrchType      - D1~D10
   * @param {string} params.SrchStartDate - 'YYYY-MM-DD'
   * @param {string} params.SrchEndDate   - 'YYYY-MM-DD'
   * @param {number} params.PageNo
   * @param {number} params.PageRowCnt
   */
  async getSettleDelivery(params) {
    return await this._post('/api/esm/settle/delivery', params)
  }

  /**
   * 글로벌셀러 예치금 송금내역 조회
   * @param {object} params
   * @param {string} params.SiteType      - 'A':옥션, 'G':G마켓
   * @param {string} params.SrchStartDate - 'YYYY-MM-DD'
   * @param {string} params.SrchEndDate   - 'YYYY-MM-DD'
   * @param {number} params.PageNo
   * @param {number} params.PageRowCnt
   */
  async getGlobalTransfer(params) {
    return await this._post('/api/esm/settle/global-transfer', params)
  }

  // ─────────────────────────────────────────────
  // 상품 API
  // ─────────────────────────────────────────────

  /**
   * 상품 등록
   * @param {object} goodsData - 상품 전문 객체 (goodsName, category, price, stock, shipping, descriptions, images 등)
   */
  async registerGoods(goodsData) {
    return await this._post('/api/esm/goods/register', goodsData)
  }

  /**
   * 상품 수정
   * @param {number|string} goodsNo - 마스터 상품번호
   * @param {object} goodsData      - 수정할 상품 전문
   */
  async updateGoods(goodsNo, goodsData) {
    return await this._post('/api/esm/goods/update', { goodsNo, ...goodsData })
  }

  /**
   * 상품 조회
   * @param {number|string} goodsNo - 마스터 상품번호
   */
  async getGoods(goodsNo) {
    return await this._post('/api/esm/goods/get', { goodsNo })
  }

  /**
   * 가격/재고/판매상태 수정
   * @param {number|string} goodsNo - 마스터 상품번호
   * @param {object} params
   * @param {object} params.isSell         - { gmkt: boolean, iac: boolean }
   * @param {object} params.itemBasicInfo  - { price: {gmkt, iac}, stock: {gmkt, iac}, sellingPeriod: {gmkt, iac} }
   */
  async updateSellStatus(goodsNo, params) {
    return await this._post('/api/esm/goods/update-sell-status', { goodsNo, ...params })
  }

  /**
   * 가격 수정 (10원 단위)
   * @param {number|string} goodsNo  - 마스터 상품번호
   * @param {number} [gmkt]          - G마켓 판매가
   * @param {number} [iac]           - 옥션 판매가
   */
  async updatePrice(goodsNo, gmkt, iac) {
    return await this._post('/api/esm/goods/update-price', { goodsNo, gmkt, iac })
  }

  /**
   * 재고 수정 (1~99,999)
   * @param {number|string} goodsNo  - 마스터 상품번호
   * @param {object} stock           - { gmkt: number, iac: number }
   */
  async updateStock(goodsNo, stock) {
    return await this._post('/api/esm/goods/update-stock', { goodsNo, stock })
  }

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }
}

// 글로벌 싱글톤
const esmApi = new EsmApi()

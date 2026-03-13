/**
 * GS샵(GS리테일) 제휴 API V3 브라우저 측 래퍼
 * proxy-server.mjs의 /api/gsshop/* 엔드포인트를 호출
 *
 * 인증:
 *   - supCd  : 협력사코드
 *   - aesKey : AES256 키 (withgs.gsshop.com 로그인 → 메인화면에서 확인)
 *   - env    : 'dev'(테스트) | 'prod'(운영)
 *   - 토큰 생성은 프록시 서버에서 처리 (AES256_CBC(yyyyMMddHHmmss+supCd))
 *
 * API 도메인:
 *   - 테스트: https://atwithgs-api.gsshop.com
 *   - 운영:   https://withgs-api.gsshop.com
 */

class GsShopApi {
  constructor(credentials = {}) {
    this.credentials = {
      supCd:    credentials.supCd    || '',  // 협력사코드 (예: 1036018)
      aesKey:   credentials.aesKey   || '',  // AES256 키 (포털 메인화면에서 확인)
      subSupCd: credentials.subSupCd || '',  // 하위협력사코드 (백화점 전용)
      env:      credentials.env      || 'dev'  // 'dev'=테스트서버, 'prod'=운영서버
    }
    this.proxyBase = 'http://localhost:3001'
  }

  // ─────────────────────────────────────────────
  // 공통: 인증 헤더 포함 fetch
  // ─────────────────────────────────────────────

  _headers() {
    return {
      'Content-Type': 'application/json',
      'x-gs-sup-cd':     this.credentials.supCd,
      'x-gs-aes-key':    this.credentials.aesKey,
      'x-gs-sub-sup-cd': this.credentials.subSupCd,
      'x-gs-env':        this.credentials.env
    }
  }

  async _get(path, params = {}) {
    const qs = new URLSearchParams(params).toString()
    const url = `${this.proxyBase}${path}${qs ? '?' + qs : ''}`
    const res = await fetch(url, { headers: this._headers() })
    return await res.json()
  }

  async _post(path, body = {}) {
    const res = await fetch(`${this.proxyBase}${path}`, {
      method: 'POST',
      headers: this._headers(),
      body: JSON.stringify(body)
    })
    return await res.json()
  }

  async _put(path, body = {}) {
    const res = await fetch(`${this.proxyBase}${path}`, {
      method: 'PUT',
      headers: this._headers(),
      body: JSON.stringify(body)
    })
    return await res.json()
  }

  // ─────────────────────────────────────────────
  // 인증
  // ─────────────────────────────────────────────

  /** AES256 키 + 협력사코드 유효성 검증 */
  async checkAuth() {
    return await this._get('/api/gsshop/auth/check')
  }

  // ─────────────────────────────────────────────
  // 기초정보 조회
  // ─────────────────────────────────────────────

  /**
   * 브랜드 이름 검색 → /api/v3/products/getPrdBrandList
   * @param {string} brandNm - 브랜드명 키워드
   */
  async getBrandsByName(brandNm = '') {
    return await this._get('/api/gsshop/brands', { brandNm })
  }

  /**
   * 브랜드 변경분 배치 조회 → /SupSendBrandInfo.gs
   * @param {string} fromDtm - 조회시작일시 (yyyyMMddHHmmss, 최대 7일)
   * @param {string} toDtm - 조회종료일시
   */
  async getBrandChanges(fromDtm = '', toDtm = '') {
    return await this._get('/api/gsshop/brands', { fromDtm, toDtm })
  }

  /**
   * 전시매장(GS 카테고리) 목록 조회
   * @param {string} sectSts - 매장상태 (A:노출, S:대기, H:숨김)
   * @param {string} shopAttrCd - 매장속성 (S:일반, D:백화점)
   */
  async getCategories(sectSts = 'A', shopAttrCd = '') {
    return await this._get('/api/gsshop/categories', { sectSts, shopAttrCd })
  }

  /**
   * 상품분류코드 전체 조회 → /SupSendPrdClsInfo.gs
   * 응답: lrgClsCd/Nm, midClsCd/Nm, smlClsCd/Nm, dtlClsCd/Nm, useYn, taxTypSelCd, govPublsPrdGrpCd 등
   */
  async getProductCategories() {
    return await this._get('/api/gsshop/product-categories')
  }

  /**
   * 출고지/반송지 전체 조회 → /api/v3/products/getSupAddrList.gs
   * @param {object} params - { supAddrCd, addrGbnNm, dirdlvRelspYn, dirdlvRetpYn }
   */
  async getDeliveryPlaces(params = {}) {
    return await this._get('/api/gsshop/delivery-places', params)
  }

  /**
   * 출고지/반송지 등록 → /api/v3/supAddrReg.gs
   * @param {object} addrData - { addrGbnNm, asignrNm, zipcd, baseAddr, dtlAddr, telno, faxNo, dirdlvRelspYn, dirdlvRetpYn }
   */
  async registerDeliveryPlace(addrData) {
    return await this._post('/api/gsshop/delivery-places/register', addrData)
  }

  /**
   * 출고지/반송지 수정 → /api/v3/supAddrMod.gs
   * @param {object} addrData - registerDeliveryPlace와 동일 + supAddrCd(필수)
   */
  async updateDeliveryPlace(addrData) {
    return await this._post('/api/gsshop/delivery-places/update', addrData)
  }

  /**
   * 협력사 MDID 조회 → /api/v3/products/getSupMdidList.gs (V1.0.1)
   * 응답: mdId, mdNm, fixMargnRt(마진율%), prcModAuthYn, prdNmModAuthYn, descdModAuthYn
   *
   * 권한이 하나라도 N이면 상품등록 후 GS상품코드가 리턴되지 않음 (MD승인 필요)
   *
   * @param {object} params
   * @param {string} params.prcModAuthYn   - 가격수정권한 (A=전체조회, Y=권한있음만, N=권한없음만)
   * @param {string} params.prdNmModAuthYn - 상품명수정권한 (A/Y/N)
   * @param {string} params.descdModAuthYn - 기술서수정권한 (A/Y/N)
   * @param {string} params.subSupCheckYn  - 하위협력사 포함 (Y/N)
   * @param {string} params.subSupCd       - 특정 하위협력사코드
   */
  async getMdList(params = {}) {
    // 기본값: 전체 권한 조회 (A = all)
    const defaults = { prcModAuthYn: 'A', prdNmModAuthYn: 'A', descdModAuthYn: 'A' }
    return await this._get('/api/gsshop/md-list', { ...defaults, ...params })
  }

  // ─────────────────────────────────────────────
  // 상품 조회
  // ─────────────────────────────────────────────

  /**
   * 상품 상세 조회 (MD 승인 완료 상품만 가능)
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {string} searchItmCd - 조회항목 (ALL | NM,PRC,ATTR,DLV,ADD,CMP,SECT,SAFE,GOV,SPEC,HTML,OPT)
   */
  async getGoods(supPrdCd, searchItmCd = 'ALL') {
    return await this._get(`/api/gsshop/goods/${supPrdCd}`, { searchItmCd })
  }

  /**
   * 상품 승인상태 조회
   * @param {string} supPrdCd - 협력사 상품코드
   */
  async getGoodsApproveStatus(supPrdCd) {
    return await this._get(`/api/gsshop/goods/${supPrdCd}/approve-status`)
  }

  // ─────────────────────────────────────────────
  // 상품 등록/수정
  // ─────────────────────────────────────────────

  /**
   * 상품 등록 (POST /api/v3/products)
   * @param {object} productData - mapProductToGsParams() 결과물
   */
  async registerGoods(productData) {
    return await this._post('/api/gsshop/goods', productData)
  }

  /**
   * 상품 기본부가정보 수정
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {object} baseInfo - prdBaseAddInfo 객체
   */
  async updateGoodsBaseInfo(supPrdCd, baseInfo) {
    return await this._post(`/api/gsshop/goods/${supPrdCd}/base-info`, baseInfo)
  }

  /**
   * 상품 가격 수정
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {object} prdPrcInfo - { prdPrcSalePrc, prdPrcSupGivRtamt, prdPrcValidStrDtm, prdPrcValidEndDtm }
   */
  async updateGoodsPrice(supPrdCd, prdPrcInfo) {
    return await this._post(`/api/gsshop/goods/${supPrdCd}/price`, {
      subSupCd: this.credentials.subSupCd,
      prdPrcInfo
    })
  }

  /**
   * 상품 판매상태 변경
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {string} saleEndDtm - 판매종료일시 (예: 29991231235959)
   * @param {string} attrSaleEndStModYn - 속성 판매종료상태 수정 여부
   */
  async updateGoodsSaleStatus(supPrdCd, saleEndDtm = '29991231235959', attrSaleEndStModYn = 'Y') {
    return await this._post(`/api/gsshop/goods/${supPrdCd}/sale-status`, { saleEndDtm, attrSaleEndStModYn })
  }

  /**
   * 상품 이미지 수정
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {string[]} imageUrls - 이미지 URL 배열 (최대 6개)
   * @param {string} mobilBannerImgUrl - 모바일 배너 이미지 URL
   */
  async updateGoodsImages(supPrdCd, imageUrls = [], mobilBannerImgUrl = '') {
    return await this._post(`/api/gsshop/goods/${supPrdCd}/images`, {
      prdCntntListCntntUrlNm: imageUrls,
      mobilBannerImgUrl
    })
  }

  /**
   * 상품 속성(옵션) 수정
   * @param {string} supPrdCd - 협력사 상품코드
   * @param {object[]} attrPrdList - 속성상품 목록
   */
  async updateGoodsAttributes(supPrdCd, attrPrdList = []) {
    return await this._post(`/api/gsshop/goods/${supPrdCd}/attributes`, {
      prdTypCd: 'S',
      subSupCd: this.credentials.subSupCd,
      attrPrdList
    })
  }

  // ─────────────────────────────────────────────
  // 데이터 매핑: 수집상품 → GS샵 V3 API 파라미터
  // ─────────────────────────────────────────────

  /**
   * 수집상품 → GS샵 V3 상품등록 파라미터 변환
   * @param {object} product - collectedProducts 상품 객체
   * @param {object} defaults - IndexedDB settings의 gsshop_defaults
   *   {
   *     brandCd, prdClsCd, operMdId, dlvsCoCd,
   *     chrDlvYn, chrDlvcAmt, shipLimitAmt,
   *     rtpAmt, exchAmt, prdRelspAddrCd, prdRetpAddrCd
   *   }
   * @param {string} accountId - 마켓 계정 ID (계정별 판매가 오버라이드)
   */
  mapProductToGsParams(product, defaults = {}, accountId = '') {
    const salePrice = (accountId && product.marketPrices?.[accountId])
      ? product.marketPrices[accountId]
      : (product.salePrice || product.originalPrice || 0)

    const supPrdCd = String(product.id || Date.now())

    // 속성(옵션) 매핑
    const attrPrdList = (product.options && product.options.length > 0)
      ? product.options.map((opt, idx) => ({
          supAttrPrdCd: `${supPrdCd}_${idx}`,  // 협력사 속성상품코드
          attrVal1: opt.color || opt.name || '',
          attrVal2: opt.size || opt.value || '',
          saleQty: opt.stock || 999,
          saleStrDtm: defaults.saleStrDtm || '20240101000000',
          saleEndDtm: defaults.saleEndDtm || '29991231235959'
        }))
      : [{
          supAttrPrdCd: `${supPrdCd}_0`,
          attrVal1: '',
          attrVal2: '',
          saleQty: product.stock || 999,
          saleStrDtm: defaults.saleStrDtm || '20240101000000',
          saleEndDtm: defaults.saleEndDtm || '29991231235959'
        }]

    return {
      supPrdCd,
      subSupCd: this.credentials.subSupCd || defaults.subSupCd || '',

      // 상품 기본부가정보
      prdBaseAddInfo: {
        brandCd: defaults.brandCd || '',
        prdClsCd: defaults.prdClsCd || '',          // 상품분류코드 (필수)
        operMdId: defaults.operMdId || '',           // 운영 MD ID (필수)
        dlvsCoCd: defaults.dlvsCoCd || 'DH',        // 택배사 (DH:대한통운)
        dlvPickMthodCd: defaults.dlvPickMthodCd || 3200,
        prdNm: product.name || '',                  // 상품명(송장)
        orgpNm: product.origin || defaults.orgpNm || '국내',
        mnfcCoNm: product.manufacturer || defaults.mnfcCoNm || '',
        taxTypCd: defaults.taxTypCd || '02',        // 02:과세
        prdTypCd: 'S',                              // S:일반상품
        ordPrdTypCd: '02',
        chrDlvYn: defaults.chrDlvYn || 'N',        // 유료배송여부
        chrDlvcAmt: Number(defaults.chrDlvcAmt || 0),
        shipLimitAmt: Number(defaults.shipLimitAmt || 0),
        exchRtpChrYn: defaults.exchRtpChrYn || 'Y',
        rtpAmt: Number(defaults.rtpAmt || 3000),
        exchAmt: Number(defaults.exchAmt || 3000),
        chrDlvAddYn: 'N',
        ilndDlvPsblYn: defaults.ilndDlvPsblYn || 'Y',
        jejuDlvPsblYn: defaults.jejuDlvPsblYn || 'Y',
        ilndChrDlvYn: 'Y',
        ilndChrDlvcAmt: Number(defaults.ilndChrDlvcAmt || 5000),
        ilndExchRtpChrYn: 'Y',
        ilndRtpAmt: Number(defaults.ilndRtpAmt || 10000),
        ilndExchAmt: Number(defaults.ilndExchAmt || 10000),
        jejuChrDlvYn: 'Y',
        jejuChrDlvcAmt: Number(defaults.jejuChrDlvcAmt || 5000),
        jejuExchRtpChrYn: 'Y',
        jejuRtpAmt: Number(defaults.jejuRtpAmt || 10000),
        jejuExchAmt: Number(defaults.jejuExchAmt || 10000),
        bundlDlvCd: defaults.bundlDlvCd || 'A01',
        prdRelspAddrCd: defaults.prdRelspAddrCd || '0001',
        prdRetpAddrCd: defaults.prdRetpAddrCd || '0001',
        attrTypExposCd: 'L',
        adultCertYn: 'N',
        saleStrDtm: defaults.saleStrDtm || '20240101000000',
        saleEndDtm: defaults.saleEndDtm || '29991231235959',
        prdBaseCmposCntnt: product.name || '',
        orgprdPkgCnt: 1,
        stdRelsDdcnt: Number(defaults.stdRelsDdcnt || 1),
        // 옵션 타입명
        attrTypNm1: (product.options && product.options.length > 0) ? (defaults.attrTypNm1 || '색상') : '',
        attrTypNm2: (product.options && product.options.length > 0) ? (defaults.attrTypNm2 || '사이즈') : ''
      },

      // 가격정보
      prdPrcInfo: {
        prdPrcValidStrDtm: defaults.saleStrDtm || '20240101000000',
        prdPrcValidEndDtm: defaults.saleEndDtm || '29991231235959',
        prdPrcSalePrc: Math.round(salePrice),
        prdPrcSupGivRtamt: Math.round(product.cost || product.originalPrice || salePrice * 0.7),
        prdPrcSupGivRtamtCd: '01'
      },

      // 상품명 변경정보 (노출명)
      prdNmChgInfo: {
        prdNmChgExposPrdNm: product.name || '',
        prdNmChgExposPmoNm: '',
        prdNmChgExposPrSntncNm: ''
      },

      // 이미지정보
      prdImgInfo: {
        prdCntntListCntntUrlNm: (product.images || []).slice(0, 6),
        mobilBannerImgUrl: product.images?.[0] || ''
      },

      // 상품기술서
      prdDescdHtmlInfo: {
        prdDescdHtmlDescdExplnCntnt: product.detailHtml || `<p>${product.name || ''}</p>`
      },

      // 속성상품 (옵션)
      attrPrdList,

      // 전시매장 (defaults.sectList로 전달)
      prdSectList: defaults.sectList || [],

      // 안전인증 (미인증)
      prdSafeCertInfo: {
        safeCertGbnCd: defaults.safeCertGbnCd || 0,
        safeCertOrgCd: defaults.safeCertOrgCd || 0
      },

      // 정보고시
      prdGovPublsItmList: defaults.govPublsItmList || []
    }
  }

  // ─────────────────────────────────────────────
  // 프로모션
  // ─────────────────────────────────────────────

  /**
   * 프로모션 목록 조회 → /api/v3/getPromotionList.gs
   * @param {string} fromDtm - 조회시작일자 (yyyyMMdd, 필수)
   * @param {string} toDtm - 조회종료일자 (yyyyMMdd, 필수, 최대 7일)
   * @param {object} opts - { pmoApplySt(ALL/10/20/30/40), prdCd, prdNm, brandCd, rowsPerPage, pageIdx }
   */
  async getPromotions(fromDtm, toDtm, opts = {}) {
    return await this._get('/api/gsshop/promotions', { fromDtm, toDtm, ...opts })
  }

  /**
   * 프로모션 승인/반려 → /api/v3/modifyPromotionStatus.gs
   * @param {object} data - { saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd(30=승인/40=반려), aprvRetRsn }
   */
  async approvePromotion(data) {
    return await this._post('/api/gsshop/promotions/approve', data)
  }

  // ─────────────────────────────────────────────
  // 유틸
  // ─────────────────────────────────────────────

  /** 자격증명 업데이트 */
  updateCredentials(credentials) {
    this.credentials = { ...this.credentials, ...credentials }
  }
}

// 글로벌 인스턴스
const gsShopApi = new GsShopApi()

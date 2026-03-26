"""롯데ON Open API 클라이언트 - 상품 등록/수정.

인증 방식: Bearer {apiKey}
기본 URL: https://openapi.lotteon.com
카테고리/브랜드: https://onpick-api.lotteon.com (별도 도메인)

거래처 정보(trGrpCd, trNo)는 identity API에서 자동 획득.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from backend.domain.samba.proxy.notice_utils import build_lotteon_notice as _build_lot_notice

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class LotteonClient:
  """롯데ON Open API 클라이언트."""

  BASE_URL = "https://openapi.lotteon.com"
  # 카테고리/브랜드는 별도 도메인
  ONPICK_URL = "https://onpick-api.lotteon.com"

  def __init__(self, api_key: str) -> None:
    self.api_key = api_key
    self.tr_grp_cd: str = ""
    self.tr_no: str = ""

  def _headers(self) -> dict[str, str]:
    return {
      "Authorization": f"Bearer {self.api_key}",
      "Content-Type": "application/json;charset=UTF-8",
      "Accept": "application/json",
      "Accept-Language": "ko",
      "X-Timezone": "GMT+09:00",
    }

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
    base_url: Optional[str] = None,
    _shared_client: Optional[Any] = None,
  ) -> dict[str, Any]:
    """공통 API 호출. _shared_client 제공 시 TCP 연결 재사용."""
    url = f"{base_url or self.BASE_URL}{path}"
    headers = self._headers()

    async def _do(c: Any) -> Any:
      if method == "GET":
        return await c.get(url, headers=headers, params=params)
      elif method == "POST":
        return await c.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        return await c.put(url, headers=headers, json=body or {})
      elif method == "DELETE":
        return await c.delete(url, headers=headers, params=params)
      raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

    if _shared_client is not None:
      resp = await _do(_shared_client)
    else:
      async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
        resp = await _do(client)

    try:
      data = resp.json()
    except Exception:
      data = {"raw": resp.text}

    logger.info(f"[롯데ON] {method} {path} → {resp.status_code}")

    if not resp.is_success:
      msg = data.get("message", "") or data.get("msg", "") or resp.text[:300]
      logger.warning(f"[롯데ON] HTTP {resp.status_code} 응답 body: {resp.text[:500]}")
      raise LotteonApiError(f"HTTP {resp.status_code}: {msg}")

    # HTTP 200이어도 응답 body에 에러 코드가 있을 수 있음
    # returnCode: 요청 레벨 에러 (카테고리 누락 등)
    res_code = (
      data.get("returnCode") or data.get("code")
      or data.get("resultCode") or data.get("rspnCd") or ""
    )
    if res_code and res_code not in ("0000", "00", "SUCCESS"):
      msg = data.get("message", "") or data.get("msg", "") or data.get("rspnMsgCntn", "") or str(data)
      logger.warning(f"[롯데ON] 응답 에러 코드: {res_code} — {msg}")
      logger.warning(f"[롯데ON] 응답 전체 body: {data}")
      raise LotteonApiError(f"응답 에러 ({res_code}): {msg}")

    return data

  # ------------------------------------------------------------------
  # 인증
  # ------------------------------------------------------------------

  async def test_auth(self) -> dict[str, Any]:
    """거래처 정보 조회 (인증 테스트) — trGrpCd, trNo 자동 획득."""
    result = await self._call_api("GET", "/v1/openapi/common/v1/identity")
    data = result.get("data", {})
    if data:
      self.tr_grp_cd = data.get("trGrpCd", "")
      self.tr_no = data.get("trNo", "")
    return {"success": True, "message": "인증 성공", "data": data}

  # ------------------------------------------------------------------
  # 상품 등록/수정/조회
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    롯데ON은 returnCode=0000(요청 접수)이어도
    data[].resultCode=9999이면 개별 상품 등록 실패.
    """
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/registration/request",
      body=product_data,
    )
    # 개별 상품 결과 검증 (data는 리스트)
    data_list = result.get("data", [])
    if isinstance(data_list, list) and data_list:
      item = data_list[0]
      if isinstance(item, dict):
        item_code = item.get("resultCode", "")
        if item_code and item_code not in ("0000", "00", "SUCCESS"):
          msg = item.get("resultMessage", "") or str(item)
          logger.warning(f"[롯데ON] 상품 등록 실패: {item_code} — {msg}")
          raise LotteonApiError(f"상품 등록 실패 ({item_code}): {msg}")
        # 성공 시 spdNo 추출
        spd_no = item.get("spdNo") or item.get("epdNo") or ""
        return {"success": True, "data": result, "spdNo": spd_no}
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """승인 상품 수정.

    등록과 동일하게 data[].resultCode 검증 필요.
    """
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/modification/request",
      body=product_data,
    )
    # 개별 상품 결과 검증
    data_list = result.get("data", [])
    if isinstance(data_list, list) and data_list:
      item = data_list[0]
      if isinstance(item, dict):
        item_code = item.get("resultCode", "")
        if item_code and item_code not in ("0000", "00", "SUCCESS"):
          msg = item.get("resultMessage", "") or str(item)
          logger.warning(f"[롯데ON] 상품 수정 실패: {item_code} — {msg}")
          raise LotteonApiError(f"상품 수정 실패 ({item_code}): {msg}")
        spd_no = item.get("spdNo") or item.get("epdNo") or ""
        return {"success": True, "data": result, "spdNo": spd_no}
    return {"success": True, "data": result}

  async def get_product(self, spd_no: str) -> dict[str, Any]:
    """상품 단건 조회 (POST 방식)."""
    body = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "spdNo": spd_no,
    }
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/detail",
      body=body,
    )

  async def update_stock(self, itm_stk_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 재고 변경."""
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/item/stock/change",
      body={"itmStkLst": itm_stk_lst},
    )

  async def update_price(self, itm_prc_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 가격 변경."""
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/item/price/change",
      body={"itmPrcLst": itm_prc_lst},
    )

  async def change_status(self, spd_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """상품 판매상태 변경 (slStatCd: SALE | SOUT | END).

    trGrpCd/trNo는 등록/수정 API와 동일하게 spdLst 각 아이템 안에 위치해야 함.
    """
    enriched = [
      {"trGrpCd": self.tr_grp_cd or "SR", "trNo": self.tr_no, **item}
      for item in spd_lst
    ]
    body: dict[str, Any] = {"spdLst": enriched}
    logger.info(f"[롯데ON] change_status 요청 body: {body}")
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/status/change",
      body=body,
    )

  async def delete_product(self, spd_no: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/delete",
      body={"spdLst": [{"spdNo": spd_no, "selPrdNo": spd_no}]},
    )
    return {"success": True, "data": result}

  # ------------------------------------------------------------------
  # 주문 조회
  # ------------------------------------------------------------------

  async def get_orders(self, days: int = 7) -> list[dict[str, Any]]:
    """최근 N일 주문 목록 조회.

    롯데ON Order API — camelCase 액션 방식 사용.
    날짜 형식: yyyymmddhh24miss (전체 datetime)
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    start = (now - timedelta(days=days)).strftime("%Y%m%d") + "000000"
    end = now.strftime("%Y%m%d") + "235959"

    body: dict[str, Any] = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "lrtrNo": self.tr_no,
      "srchStrtDttm": start,
      "srchEndDttm": end,
      "pageNo": 1,
      "pageSize": 100,
      # 주문 상태 전체 조회 (일부 API에서 필수)
      "orderStatusList": [],
    }
    logger.info(f"[롯데ON] 주문 조회 {start}~{end}, trGrpCd={self.tr_grp_cd}, trNo={self.tr_no}")

    # 문서 확인된 경로: getSROrderList
    result = await self._call_api(
      "POST", "/v1/openapi/order/v1/getSROrderList", body=body
    )
    logger.info(f"[롯데ON] 주문 API 응답 키: {list(result.keys())}")

    # 응답 구조 탐색 (data.orderItems 또는 data.list 등)
    data = result.get("data") or {}
    if isinstance(data, list):
      return data
    if isinstance(data, dict):
      for key in ("orderItems", "orderList", "list", "content", "items", "orders"):
        val = data.get(key)
        if isinstance(val, list):
          logger.info(f"[롯데ON] 주문 데이터 키='{key}', 건수={len(val)}")
          return val
    logger.warning(f"[롯데ON] 주문 응답 구조 미파악: {list(result.keys())}")
    return []

  async def get_claims(self, days: int = 7) -> list[dict[str, Any]]:
    """최근 N일 클레임(반품/교환/취소) 목록 조회.

    문서 확인된 경로:
    - 반품: returningOpenApi/returnRequestSearch
    - 교환: exchangeOpenApi/exchangeSearch
    - 취소: cancellationOpenApi/getCancellationRequestAndComplateList
         + cancellationOpenApi/purFvrCnclSearch (구매자 취소)
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    start = (now - timedelta(days=days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")

    body: dict[str, Any] = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "srchStDt": start,
      "srchEdDt": end,
      "pageNo": 1,
      "pageSize": 100,
    }

    # (경로, 클레임 타입) 쌍 — 타입을 각 아이템에 주입해 구분
    claim_endpoints = [
      ("/v1/openapi/claim/v1/returningOpenApi/returnRequestSearch", "RETURN"),
      ("/v1/openapi/claim/v1/exchangeOpenApi/exchangeSearch", "EXCHANGE"),
      ("/v1/openapi/claim/v1/cancellationOpenApi/getCancellationRequestAndComplateList", "CANCEL"),
      ("/v1/openapi/claim/v1/cancellationOpenApi/purFvrCnclSearch", "CANCEL"),
    ]
    all_claims: list[dict[str, Any]] = []
    for path, claim_type in claim_endpoints:
      try:
        r = await self._call_api("POST", path, body=body)
        logger.info(f"[롯데ON] 클레임 API 성공: {path}, 키: {list(r.keys())}")
        logger.info(f"[롯데ON] 클레임 응답 전체: {str(r)[:300]}")
        d = r.get("data") or r.get("list") or []
        if isinstance(d, dict):
          d = (d.get("list") or d.get("content")
               or d.get("claimList") or d.get("items") or [])
        if isinstance(d, list) and d:
          for item in d:
            if isinstance(item, dict):
              item.setdefault("_claimType", claim_type)
          all_claims.extend(d)
          logger.info(f"[롯데ON] {claim_type} 클레임 {len(d)}건")
      except LotteonApiError as e:
        err_str = str(e)
        if "404" in err_str or "403" in err_str:
          logger.info(f"[롯데ON] 클레임 API {err_str[:20]} — 건너뜀: {path}")
          continue
        raise

    logger.info(f"[롯데ON] 클레임 총 {len(all_claims)}건 수집")
    return all_claims

  async def get_cs_inquiries(self, days: int = 30) -> list[dict[str, Any]]:
    """CS 문의(QnA) 목록 조회 — 엔드포인트 자동 탐색."""
    from datetime import datetime, timedelta
    now = datetime.now()
    start = (now - timedelta(days=days)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")

    body: dict[str, Any] = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "srchStDt": start,
      "srchEdDt": end,
      "pageNo": 1,
      "pageSize": 100,
    }
    candidate_paths = [
      "/v1/openapi/qna/v1/qna/list",
      "/v1/openapi/cs/v1/qna/list",
      "/v1/openapi/cs/v1/inquiry/list",
      "/v1/openapi/qna/v1/qnas",
    ]
    result: dict[str, Any] = {}
    for path in candidate_paths:
      try:
        result = await self._call_api("POST", path, body=body)
        logger.info(f"[롯데ON] CS문의 API 성공 경로: {path}")
        break
      except LotteonApiError as e:
        if "404" in str(e):
          logger.info(f"[롯데ON] CS문의 API 404 — 다음 경로 시도: {path}")
          continue
        raise
    if not result:
      logger.warning("[롯데ON] CS문의 API — 모든 후보 경로 404")
      return []
    data = result.get("data") or result.get("qnaList") or result.get("list") or []
    if isinstance(data, dict):
      data = data.get("qnaList") or data.get("list") or data.get("content") or []
    return data if isinstance(data, list) else []

  async def reply_cs_inquiry(self, qna_no: str, content: str) -> dict[str, Any]:
    """CS 문의 답변 등록.

    롯데ON QnA 답변 API: POST /v1/openapi/qna/v1/qna/answer
    """
    body: dict[str, Any] = {
      "trGrpCd": self.tr_grp_cd or "SR",
      "trNo": self.tr_no,
      "qnaNo": qna_no,
      "answerContent": content,
    }
    return await self._call_api(
      "POST",
      "/v1/openapi/qna/v1/qna/answer",
      body=body,
    )

  # ------------------------------------------------------------------
  # 카테고리 / 브랜드 (onpick-api 도메인)
  # ------------------------------------------------------------------

  async def get_categories(
    self,
    cat_id: str = "",
    depth: str = "",
    parent_id: str = "",
    _shared_client: Optional[Any] = None,
  ) -> dict[str, Any]:
    """표준카테고리 조회 (onpick-api 도메인).

    Args:
      cat_id: filter_1 — 특정 카테고리 ID 조회
      depth: filter_3 — 뎁스 레벨 (1~4)
      parent_id: filter_2 — 부모 카테고리 ID로 하위 목록 조회
      _shared_client: 대량 조회 시 TCP 연결 재사용용 httpx 클라이언트
    """
    params: dict[str, str] = {"job": "cheetahStandardCategory"}
    if cat_id:
      params["filter_1"] = cat_id
    if parent_id:
      params["filter_2"] = parent_id
    if depth:
      params["filter_3"] = depth
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params=params,
      base_url=self.ONPICK_URL,
      _shared_client=_shared_client,
    )

  async def get_delivery_zones(self) -> dict[str, Any]:
    """배송권역 그룹 목록 조회."""
    return await self._call_api(
      "GET",
      "/v1/openapi/delivery/v1/zone/group/list",
    )

  async def search_brand(self, keyword: str) -> dict[str, Any]:
    """브랜드 검색 (onpick-api 도메인)."""
    return await self._call_api(
      "GET",
      "/cheetah/econCheetah.ecn",
      params={"job": "cheetahBrnd", "mf_1": keyword},
      base_url=self.ONPICK_URL,
    )

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_id: str = "",
    tr_grp_cd: str = "SR",
    tr_no: str = "",
    disp_cat_id: str = "",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 롯데ON 상품 등록 데이터 변환.

    Args:
      category_id: 표준카테고리번호 (BC...)
      disp_cat_id: 전시카테고리번호 (FC...) — 없으면 category_id 사용
    """
    # 이미지 URL 정규화: //로 시작하면 https: 추가, http로 시작하지 않으면 제외
    def _normalize_url(url: str) -> str:
      if url.startswith("//"):
        return "https:" + url
      return url

    raw_images = product.get("images") or []
    images = [_normalize_url(u) for u in raw_images if u and (u.startswith("http") or u.startswith("//"))][:10]
    from backend.utils.logger import logger as _log
    _log.info(f"[롯데ON] 이미지 원본: {raw_images[:3]}")
    _log.info(f"[롯데ON] 이미지 정규화: {images[:3]}")
    sale_price = int(product.get("sale_price", 0))
    name = (product.get("name", "") or "")[:150]

    # 할인율 적용 (계정 설정)
    discount_rate = product.get("_discount_rate", 0)
    if discount_rate:
      sale_price = int(sale_price * (1 - discount_rate / 100))

    # 재고 수량 오버라이드
    default_stock = product.get("_stock_quantity", 0) or 999

    # 반품/교환 배송비
    return_fee = product.get("_return_fee", 0) or 0
    exchange_fee = product.get("_exchange_fee", 0) or 0
    jeju_fee = product.get("_jeju_fee", 0) or 0

    # 판매 시작/종료 일시 (현재~1년 후)
    now = datetime.now()
    sl_strt = now.strftime("%Y%m%d%H%M%S")
    sl_end = (now + timedelta(days=365)).strftime("%Y%m%d%H%M%S")

    # URL에서 파일명 추출 헬퍼
    def _extract_filename(url: str) -> str:
      """URL에서 파일명 추출. 없으면 image.jpg 반환."""
      path = urlparse(url).path
      fname = path.rsplit("/", 1)[-1] if "/" in path else ""
      return fname if fname else "image.jpg"

    # 상품 파일 목록 (origFileNm도 전체 URL로 설정)
    pd_file_lst = [
      {
        "fileTypCd": "PD",
        "fileDvsCd": "WDTH",
        "origImgFileNm": url,
        "origFileNm": url,
      }
      for url in images
    ]

    # 단품 이미지
    itm_img_lst = [
      {
        "epsrTypCd": "IMG",
        "epsrTypDtlCd": "IMG_SQRE",
        "origImgFileNm": url,
        "origFileNm": _extract_filename(url),
        "rprtImgYn": "Y" if idx == 0 else "N",
      }
      for idx, url in enumerate(images)
    ]

    # 단품(옵션) 목록
    options = product.get("options") or []
    itm_lst = []

    def _detect_opt_nm(opt: dict[str, Any], all_opts: list) -> str:
      """옵션 타입 자동 감지 (색상/사이즈/기타)."""
      keys = set(opt.keys())
      if "color" in keys or any("color" in str(k).lower() for k in keys):
        return "색상"
      if "size" in keys or any("size" in str(k).lower() for k in keys):
        return "사이즈"
      # 옵션값이 숫자(사이즈)인지 색상명인지 추정
      val = opt.get("name", "") or opt.get("value", "") or ""
      size_keywords = ["S", "M", "L", "XL", "XXL", "XS", "FREE", "프리", "스몰", "라지"]
      if val.strip().upper() in size_keywords or (val.replace(".", "").isdigit()):
        return "사이즈"
      return "옵션"

    if options:
      # 상품 전체 옵션에서 optNm을 한 번만 결정 (단품 간 optNm 불일치 시 9999 에러)
      product_opt_nm = _detect_opt_nm(options[0], options)
      for idx, opt in enumerate(options):
        opt_name = opt.get("name", "") or opt.get("size", "") or opt.get("value", "") or f"옵션{idx + 1}"
        opt_stock = opt.get("stock", default_stock) or default_stock
        itm_lst.append({
          "eitmNo": f"OPT{idx}",
          "dpYn": "Y",
          "sortSeq": idx + 1,
          "itmOptLst": [{"optNm": product_opt_nm, "optVal": opt_name}],
          "itmImgLst": itm_img_lst,
          "slPrc": sale_price,
          "stkQty": opt_stock,
        })
    else:
      itm_lst.append({
        "eitmNo": "OPT0",
        "dpYn": "Y",
        "sortSeq": 1,
        "itmOptLst": [],
        "itmImgLst": itm_img_lst,
        "slPrc": sale_price,
        "stkQty": default_stock,
      })

    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    brand = product.get("brand", "")

    return {
      "spdLst": [{
        "trGrpCd": tr_grp_cd,
        "trNo": tr_no,
        "scatNo": category_id,
        # 전시카테고리(FC...)가 있으면 사용, 없으면 표준카테고리로 fallback (dcatLst는 필수)
        "dcatLst": [{"mallCd": "LTON", "lfDcatNo": disp_cat_id or category_id}],
        "slTypCd": "GNRL",
        "pdTypCd": "GNRL_GNRL",
        "spdNm": name,
        # 브랜드번호 (brdNo) — 브랜드 API로 검색 후 번호 전달 필요
        # 미지정 시 무브랜드로 등록
        "brdNo": product.get("brand_no", ""),
        "mfcrNm": brand or "제조사 미확인",
        "oplcCd": "KR",
        "tdfDvsCd": "01",
        # 판매 기간 (필수)
        "slStrtDttm": sl_strt,
        "slEndDttm": sl_end,
        # 출고지/배송비정책/회수지 번호 (거래처 사전 등록 필요)
        "owhpNo": product.get("owhp_no", ""),
        "dvCstPolNo": product.get("dv_cst_pol_no", ""),
        "rtrpNo": product.get("rtrp_no", ""),
        # 선물포장/메시지 여부
        "prstPckPsbYn": "N",
        "prstMsgPsbYn": "N",
        "pdItmsInfo": _build_lot_notice(product),
        "purPsbQtyInfo": {
          "itmByMinPurYn": "N",
          "itmByMaxPurPsbQtyYn": "N",
          "maxPurLmtTypCd": "PERIOD",
        },
        "ageLmtCd": "0",
        "prcCmprEpsrYn": "Y",
        "pdStatCd": "NEW",
        "dpYn": "Y",
        "pdFileLst": pd_file_lst if pd_file_lst else None,
        "epnLst": [{"pdEpnTypCd": "DSCRP", "cnts": detail_html}],
        "cnclPsbYn": "Y",
        "dmstOvsDvDvsCd": "DMST",
        "dvProcTypCd": "LO_ENTP",
        "dvPdTypCd": "GNRL",
        "sndBgtNday": 2,
        "dvMnsCd": "DPCL",
        "cmbnDvPsbYn": product.get("cmbn_dv_psb_yn", "Y"),
        # 합반품여부는 합배송여부와 동일하게 설정 (롯데ON 규칙)
        "cmbnRtngPsbYn": product.get("cmbn_dv_psb_yn", "Y"),
        "rtngPsbYn": "Y",
        "xchgPsbYn": "Y",
        # 반품/교환 배송비 (0이면 필드 생략 — 정책번호 기본값 사용)
        **({"rtngFee": return_fee} if return_fee else {}),
        **({"xchgFee": exchange_fee} if exchange_fee else {}),
        # 도서산간 추가배송비
        **({"islandAddDlvFee": jeju_fee} if jeju_fee else {}),
        "stkMgtYn": "Y",
        "sitmYn": "Y" if options else "N",
        "itmLst": itm_lst,
        "rtrvTypCd": "ENTP_RTRV",
        # 배송권역 그룹코드 (GN000=전국, GN004=제주, GN006=도서산간 등)
        "dvRgsprGrpCd": "GN000",
      }]
    }


class LotteonApiError(Exception):
  """롯데ON API 에러."""
  pass

"""롯데ON Open API 클라이언트 - 상품 등록/수정.

인증 방식: Bearer {apiKey}
기본 URL: https://openapi.lotteon.com
카테고리/브랜드: https://onpick-api.lotteon.com (별도 도메인)

거래처 정보(trGrpCd, trNo)는 identity API에서 자동 획득.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

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
  ) -> dict[str, Any]:
    """공통 API 호출."""
    url = f"{base_url or self.BASE_URL}{path}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=30) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers, params=params)
      elif method == "POST":
        resp = await client.post(url, headers=headers, json=body or {})
      elif method == "PUT":
        resp = await client.put(url, headers=headers, json=body or {})
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      try:
        data = resp.json()
      except Exception:
        data = {"raw": resp.text}

      logger.info(f"[롯데ON] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        msg = data.get("message", "") or data.get("msg", "") or resp.text[:200]
        raise LotteonApiError(f"HTTP {resp.status_code}: {msg}")

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
    """상품 등록."""
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/registration/request",
      body=product_data,
    )
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """승인 상품 수정."""
    result = await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/modification/request",
      body=product_data,
    )
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
    """상품 판매상태 변경 (slStatCd: SALE | SOUT | END)."""
    return await self._call_api(
      "POST",
      "/v1/openapi/product/v1/product/status/change",
      body={"spdLst": spd_lst},
    )

  # ------------------------------------------------------------------
  # 카테고리 / 브랜드 (onpick-api 도메인)
  # ------------------------------------------------------------------

  async def get_categories(
    self, cat_id: str = "", depth: str = "", parent_id: str = ""
  ) -> dict[str, Any]:
    """표준카테고리 조회 (onpick-api 도메인).

    Args:
      cat_id: filter_1 — 특정 카테고리 ID 조회
      depth: filter_3 — 뎁스 레벨 (1~4)
      parent_id: filter_2 — 부모 카테고리 ID로 하위 목록 조회
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
    images = (product.get("images") or [])[:10]
    sale_price = int(product.get("sale_price", 0))
    name = (product.get("name", "") or "")[:150]

    # 판매 시작/종료 일시 (현재~1년 후)
    now = datetime.now()
    sl_strt = now.strftime("%Y%m%d%H%M%S")
    sl_end = (now + timedelta(days=365)).strftime("%Y%m%d%H%M%S")

    # URL에서 파일명 추출 헬퍼
    def _extract_filename(url: str) -> str:
      """URL에서 파일명 추출. 없으면 image.jpg 반환."""
      from urllib.parse import urlparse
      path = urlparse(url).path
      fname = path.rsplit("/", 1)[-1] if "/" in path else ""
      return fname if fname else "image.jpg"

    # 상품 파일 목록
    pd_file_lst = [
      {
        "fileTypCd": "PD",
        "fileDvsCd": "WDTH",
        "origImgFileNm": url,
        "origFileNm": _extract_filename(url),
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
    if options:
      for idx, opt in enumerate(options):
        opt_name = opt.get("name", "") or opt.get("size", "") or opt.get("value", "") or f"옵션{idx + 1}"
        opt_stock = opt.get("stock", 999)
        itm_lst.append({
          "eitmNo": f"OPT-{idx}",
          "dpYn": "Y",
          "sortSeq": idx + 1,
          "itmOptLst": [{"optNm": "옵션", "optVal": opt_name}],
          "itmImgLst": itm_img_lst,
          "slPrc": sale_price,
          "stkQty": opt_stock,
        })
    else:
      itm_lst.append({
        "eitmNo": "OPT-0",
        "dpYn": "Y",
        "sortSeq": 1,
        "itmOptLst": [],
        "itmImgLst": itm_img_lst,
        "slPrc": sale_price,
        "stkQty": 999,
      })

    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    brand = product.get("brand", "")

    return {
      "spdLst": [{
        "trGrpCd": tr_grp_cd,
        "trNo": tr_no,
        "scatNo": category_id,
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
        "pdItmsInfo": {
          "pdItmsCd": "38",
          "pdItmsArtlLst": [
            {"pdArtlCd": "0160", "pdArtlCnts": name},
            {"pdArtlCd": "0060", "pdArtlCnts": "대한민국"},
            {"pdArtlCd": "0070", "pdArtlCnts": brand or "제조자 정보 없음"},
            {"pdArtlCd": "0080", "pdArtlCnts": "소비자 기본법에 따름"},
            {"pdArtlCd": "0090", "pdArtlCnts": brand or "판매자 문의"},
          ],
        },
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
        "cmbnDvPsbYn": "Y",
        "rtngPsbYn": "Y",
        "xchgPsbYn": "Y",
        "stkMgtYn": "Y",
        "sitmYn": "Y" if options else "N",
        "itmLst": itm_lst,
        "rtrvTypCd": "ENTP_RTRV",
      }]
    }


class LotteonApiError(Exception):
  """롯데ON API 에러."""
  pass

"""롯데ON Open API 클라이언트 - 상품 등록/수정.

인증 방식: Bearer {apiKey}
기본 URL: https://openapi.lotteon.com

기존 js/modules/lotteon-api.js를 Python으로 포팅.
거래처 정보(trGrpCd, trNo)는 identity API에서 자동 획득.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from backend.utils.logger import logger


class LotteonClient:
  """롯데ON Open API 클라이언트."""

  BASE_URL = "https://openapi.lotteon.com"

  def __init__(self, api_key: str) -> None:
    self.api_key = api_key
    self.tr_grp_cd: str = ""
    self.tr_no: str = ""

  def _headers(self) -> dict[str, str]:
    return {
      "Authorization": f"Bearer {self.api_key}",
      "Content-Type": "application/json;charset=UTF-8",
      "Accept": "application/json",
    }

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, str]] = None,
  ) -> dict[str, Any]:
    """공통 API 호출."""
    url = f"{self.BASE_URL}{path}"
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
    result = await self._call_api("GET", "/v1/identity")
    data = result.get("data", {})
    if data:
      self.tr_grp_cd = data.get("trGrpCd", "")
      self.tr_no = data.get("trNo", "")
    return {"success": True, "message": "인증 성공", "data": data}

  # ------------------------------------------------------------------
  # 상품 등록/수정
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    롯데ON Open API: POST /v1/product/save
    """
    result = await self._call_api("POST", "/v1/product/save", body=product_data)
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """승인 상품 수정."""
    result = await self._call_api("POST", "/v1/product/update", body=product_data)
    return {"success": True, "data": result}

  async def get_product(self, spd_no: str) -> dict[str, Any]:
    """상품 단건 조회."""
    return await self._call_api("GET", f"/v1/product/{spd_no}")

  async def update_stock(self, itm_stk_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 재고 변경."""
    return await self._call_api(
      "POST", "/v1/product/stock", body={"itmStkLst": itm_stk_lst}
    )

  async def update_price(self, itm_prc_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """단품 가격 변경."""
    return await self._call_api(
      "POST", "/v1/product/price", body={"itmPrcLst": itm_prc_lst}
    )

  async def change_status(self, spd_lst: list[dict[str, Any]]) -> dict[str, Any]:
    """상품 판매상태 변경 (slStatCd: SALE | SOUT | END)."""
    return await self._call_api(
      "POST", "/v1/product/status", body={"spdLst": spd_lst}
    )

  async def get_categories(
    self, cat_id: str = "", depth: str = ""
  ) -> dict[str, Any]:
    """표준카테고리 조회."""
    params: dict[str, str] = {}
    if cat_id:
      params["catId"] = cat_id
    if depth:
      params["depth"] = depth
    return await self._call_api("GET", "/v1/category/standard", params=params)

  async def search_brand(self, keyword: str) -> dict[str, Any]:
    """브랜드 검색."""
    return await self._call_api(
      "GET", "/v1/brand/search", params={"keyword": keyword}
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
  ) -> dict[str, Any]:
    """SambaCollectedProduct → 롯데ON 상품 등록 데이터 변환.

    기존 lotteon-api.js의 mapProductToLotteonParams를 Python으로 포팅.
    """
    images = (product.get("images") or [])[:10]
    sale_price = int(product.get("sale_price", 0))
    name = (product.get("name", "") or "")[:150]

    # 상품 파일 목록
    pd_file_lst = [
      {
        "fileTypCd": "PD",
        "fileDvsCd": "WDTH",
        "origImgFileNm": url,
      }
      for url in images
    ]

    # 단품 이미지
    itm_img_lst = [
      {
        "epsrTypCd": "IMG",
        "epsrTypDtlCd": "IMG_SQRE",
        "origImgFileNm": url,
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
        "dcatLst": [{"mallCd": "LTON", "lfDcatNo": category_id}],
        "slTypCd": "GNRL",
        "pdTypCd": "GNRL_GNRL",
        "spdNm": name,
        "mfcrNm": brand,
        "oplcCd": "KR",
        "tdfDvsCd": "01",
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

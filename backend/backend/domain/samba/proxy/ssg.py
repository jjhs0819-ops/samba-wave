"""SSG(신세계몰) Open API 클라이언트 - 상품 등록/수정.

인증 방식: Authorization 헤더에 업체 인증키
기본 URL: https://eapi.ssgadm.com
버전: 0.5

사이트번호:
- 6001: 이마트몰
- 6004: 신세계몰
- 6009: 신세계백화점몰

eapi.ssgadm.com/info/item/insertItem.ssg 스펙 기반.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from backend.utils.logger import logger


class SSGClient:
  """SSG Open API 클라이언트."""

  BASE_URL = "https://eapi.ssgadm.com"

  def __init__(self, api_key: str, site_no: str = "6004") -> None:
    """api_key: 업체 인증키, site_no: 사이트번호 (기본 신세계몰)."""
    self.api_key = api_key
    self.site_no = site_no

  def _headers(self, accept: str = "application/json") -> dict[str, str]:
    return {
      "Authorization": self.api_key,
      "Content-Type": "application/json;charset=UTF-8",
      "Accept": accept,
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

      logger.info(f"[SSG] {method} {path} → {resp.status_code}")

      if not resp.is_success:
        msg = data.get("message", "") or data.get("msg", "") or resp.text[:200]
        raise SSGApiError(f"HTTP {resp.status_code}: {msg}")

      return data

  # ------------------------------------------------------------------
  # 인증 테스트
  # ------------------------------------------------------------------

  async def test_auth(self) -> dict[str, Any]:
    """인증 테스트 — 브랜드 목록 조회로 키 유효성 확인."""
    result = await self._call_api(
      "GET", "/api/item/listBrand.ssg", params={"version": "0.5"}
    )
    return {"success": True, "message": "인증 성공", "data": result}

  # ------------------------------------------------------------------
  # 상품 등록/수정
  # ------------------------------------------------------------------

  async def register_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 등록.

    SSG Open API: POST /api/item/insertItem.ssg?version=0.5
    """
    result = await self._call_api(
      "POST",
      "/api/item/insertItem.ssg",
      body=product_data,
      params={"version": "0.5"},
    )
    return {"success": True, "data": result}

  async def update_product(self, product_data: dict[str, Any]) -> dict[str, Any]:
    """상품 수정."""
    result = await self._call_api(
      "POST",
      "/api/item/updateItem.ssg",
      body=product_data,
      params={"version": "0.5"},
    )
    return {"success": True, "data": result}

  async def get_product(self, item_id: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api(
      "GET",
      "/api/item/getItemList.ssg",
      params={"version": "0.5", "itemId": item_id},
    )

  async def get_brands(self, keyword: str = "") -> dict[str, Any]:
    """브랜드 목록 조회."""
    params = {"version": "0.5"}
    if keyword:
      params["brandNm"] = keyword
    return await self._call_api("GET", "/api/item/listBrand.ssg", params=params)

  async def get_categories(self, std_ctg_id: str = "") -> dict[str, Any]:
    """표준카테고리 조회."""
    params = {"version": "0.5"}
    if std_ctg_id:
      params["stdCtgId"] = std_ctg_id
    return await self._call_api("GET", "/api/item/listStdCtg.ssg", params=params)

  # ------------------------------------------------------------------
  # 상품 데이터 변환
  # ------------------------------------------------------------------

  def transform_product(
    self,
    product: dict[str, Any],
    category_id: str = "",
    brand_id: str = "",
  ) -> dict[str, Any]:
    """SambaCollectedProduct → SSG 상품 등록 데이터 변환."""
    name = (product.get("name", "") or "")[:100]
    sale_price = int(product.get("sale_price", 0))
    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    images = product.get("images") or []
    brand = product.get("brand", "")

    now = datetime.now(timezone.utc)
    disp_start = now.strftime("%Y%m%d")
    disp_end = "20991231"

    # 옵션 처리
    options = product.get("options") or []

    # 이미지 목록
    item_images = []
    for idx, url in enumerate(images[:10]):
      item_images.append({
        "imgPathNm": url,
        "imgTypCd": "10" if idx == 0 else "20",  # 10=대표, 20=추가
        "imgSeq": idx + 1,
      })

    # 옵션(단품) 목록
    item_options = []
    if options:
      for idx, opt in enumerate(options):
        opt_name = opt.get("name", "") or opt.get("size", "") or f"옵션{idx + 1}"
        opt_stock = opt.get("stock", 999)
        item_options.append({
          "optNm": opt_name,
          "sellPrc": sale_price,
          "stockQty": opt_stock,
        })

    return {
      "itemNm": name,
      "brandId": brand_id,
      "stdCtgId": category_id,
      "itemChrctDivCd": "10",
      "itemChrctDtlCd": "10",
      "exusItemDivCd": "10",
      "exusItemDtlCd": "10",
      "manufcoNm": brand or "제조사 정보 없음",
      "prodManufCntryId": "KR",
      "srchPsblYn": "Y",
      "sites": [
        {
          "siteNo": self.site_no,
          "sellStatCd": "20",
        }
      ],
      "minOnetOrdPsblQty": 1,
      "maxOnetOrdPsblQty": 20,
      "max1dyOrdPsblQty": 20,
      "dispCtgs": [{"siteNo": self.site_no, "stdCtgId": category_id}] if category_id else [],
      "dispStrtDts": disp_start,
      "dispEndDts": disp_end,
      "buyFrmCd": "60",  # 위수탁
      "txnDivCd": "10",  # 과세
      "adultItemTypeCd": "90",  # 일반상품
      "sellPrc": sale_price,
      "itemImages": item_images if item_images else None,
      "itemOptions": item_options if item_options else None,
      "itemDtlDesc": detail_html,
    }


class SSGApiError(Exception):
  """SSG API 에러."""
  pass

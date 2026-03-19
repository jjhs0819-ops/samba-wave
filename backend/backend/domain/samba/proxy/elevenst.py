"""11번가 OpenAPI 클라이언트 - 상품 등록/수정.

인증 방식: 32자리 Open API Key (헤더 전달)
- openapikey: {apiKey}
- 상품 등록: POST /rest/prodservices/prod
- 상품 수정: PUT /rest/prodservices/prod/{prdNo}
"""

from __future__ import annotations

from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from backend.utils.logger import logger


class ElevenstClient:
  """11번가 셀러 API 클라이언트."""

  BASE_URL = "https://api.11st.co.kr/rest/prodservices"
  # 상품 등록: POST /rest/prodservices/product
  # 상품 조회: GET /rest/prodservices/product/{productCode}
  # 상품 수정: PUT /rest/prodservices/product/{productCode}

  def __init__(self, api_key: str) -> None:
    self.api_key = api_key

  def _headers(self) -> dict[str, str]:
    return {
      "openapikey": self.api_key,
      "Content-Type": "application/xml;charset=UTF-8",
      "Accept": "application/xml",
    }

  @staticmethod
  def _parse_xml(text: str) -> dict[str, Any]:
    """XML 응답 파싱."""
    try:
      root = ET.fromstring(text)
      result: dict[str, Any] = {}
      for child in root:
        tag = child.tag
        if list(child):
          inner: dict[str, Any] = {}
          for sub in child:
            inner[sub.tag] = (sub.text or "").strip()
          result[tag] = inner
        else:
          result[tag] = (child.text or "").strip()
      return result
    except ET.ParseError:
      return {"raw": text}

  async def _call_api(
    self,
    method: str,
    path: str,
    body: Optional[str] = None,
  ) -> dict[str, Any]:
    """공통 API 호출 (XML 기반)."""
    url = f"{self.BASE_URL}{path}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=30) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers)
      elif method == "POST":
        resp = await client.post(url, headers=headers, content=body)
      elif method == "PUT":
        resp = await client.put(url, headers=headers, content=body)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      logger.info(f"[11번가] {method} {path} → {resp.status_code}")

      data = self._parse_xml(resp.text)

      if not resp.is_success:
        msg = data.get("message", "") or data.get("raw", resp.text[:200])
        raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")

      # 에러코드 체크
      result_code = data.get("resultCode", "") or data.get("ResultCode", "")
      if result_code and str(result_code) != "200" and str(result_code) != "0":
        msg = data.get("resultMessage", "") or data.get("message", "")
        raise ElevenstApiError(f"API 에러 ({result_code}): {msg}")

      return data

  # ------------------------------------------------------------------
  # 상품 등록/수정
  # ------------------------------------------------------------------

  async def register_product(self, xml_data: str) -> dict[str, Any]:
    """상품 등록.

    11번가 셀러 API: POST /rest/prodservices/product
    """
    result = await self._call_api("POST", "/product", body=xml_data)
    return {"success": True, "data": result}

  async def update_product(self, prd_no: str, xml_data: str) -> dict[str, Any]:
    """상품 수정."""
    result = await self._call_api("PUT", f"/product/{prd_no}", body=xml_data)
    return {"success": True, "data": result}

  async def get_product(self, prd_no: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api("GET", f"/product/{prd_no}")

  # ------------------------------------------------------------------
  # 상품 데이터 변환 (수집 상품 → 11번가 XML 형식)
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_code: str = "",
  ) -> str:
    """SambaCollectedProduct → 11번가 상품 등록 XML 변환."""
    name = product.get("name", "")
    sale_price = int(product.get("sale_price", 0))
    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    images = product.get("images") or []
    brand = product.get("brand", "")

    # 이미지 XML
    image_xml = ""
    if images:
      image_xml += f"<imageUrl>{_escape_xml(images[0])}</imageUrl>"
      for i, url in enumerate(images[1:4], start=1):
        image_xml += f"<addImageUrl{i}>{_escape_xml(url)}</addImageUrl{i}>"

    # 옵션 처리
    options = product.get("options") or []
    option_xml = ""
    if options:
      option_xml = "<sellerOptions>"
      for opt in options:
        opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
        opt_stock = opt.get("stock", 999)
        option_xml += f"""<sellerOption>
          <optionName>옵션</optionName>
          <optionValue>{_escape_xml(opt_name)}</optionValue>
          <stockQty>{opt_stock}</stockQty>
          <sellerOptionPrice>0</sellerOptionPrice>
        </sellerOption>"""
      option_xml += "</sellerOptions>"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Product>
  <sellerPrdCd></sellerPrdCd>
  <prdNm>{_escape_xml(name)}</prdNm>
  <prdStatCd>01</prdStatCd>
  <dispCtgrNo>{category_code}</dispCtgrNo>
  <brand>{_escape_xml(brand)}</brand>
  <selPrc>{sale_price}</selPrc>
  <prdWeight>0</prdWeight>
  <dlvCnFee>0</dlvCnFee>
  <dlvGrntYn>Y</dlvGrntYn>
  <minorSelCnYn>N</minorSelCnYn>
  <htmlDetail><![CDATA[{detail_html}]]></htmlDetail>
  {image_xml}
  {option_xml}
  <asDetail>상세페이지 참조</asDetail>
  <rtngExchDetail>상세페이지 참조</rtngExchDetail>
</Product>"""
    return xml


def _escape_xml(text: str) -> str:
  """XML 특수문자 이스케이프."""
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )


class ElevenstApiError(Exception):
  """11번가 API 에러."""
  pass

"""11번가 OpenAPI 클라이언트 - 상품 등록/수정.

인증 방식: 32자리 Open API Key (헤더 전달)
- openapikey: {apiKey}
- 상품 등록: POST /rest/prodservices/prod
- 상품 수정: PUT /rest/prodservices/prod/{prdNo}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from backend.core.config import settings

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
      "Content-Type": "text/xml; charset=UTF-8",
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

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      if method == "GET":
        resp = await client.get(url, headers=headers)
      elif method == "POST":
        resp = await client.post(url, headers=headers, content=body)
      elif method == "PUT":
        resp = await client.put(url, headers=headers, content=body)
      elif method == "DELETE":
        resp = await client.delete(url, headers=headers)
      else:
        raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

      logger.info(f"[11번가] {method} {path} → {resp.status_code}")
      if body:
        logger.info(f"[11번가] 요청 XML: {body[:800]}")
      logger.info(f"[11번가] 응답 본문: {resp.text[:800]}")

      data = self._parse_xml(resp.text)

      if not resp.is_success:
        msg = data.get("message", "") or data.get("raw", "") or resp.text[:300]
        raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")

      # 에러코드 체크
      result_code = data.get("resultCode", "") or data.get("ResultCode", "")
      if result_code and str(result_code) != "200" and str(result_code) != "0":
        msg = data.get("resultMessage", "") or data.get("message", "")
        raise ElevenstApiError(f"API 에러 ({result_code}): {msg}")

      return data

  # ------------------------------------------------------------------
  # 카테고리 조회
  # ------------------------------------------------------------------

  async def get_categories(self) -> dict[str, Any]:
    """전체 카테고리 조회. (cateservice 엔드포인트 사용)"""
    url = "https://api.11st.co.kr/rest/cateservice/category"
    headers = self._headers()
    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info(f"[11번가] GET /cateservice/category → {resp.status_code}")
      logger.debug(f"[11번가] 카테고리 응답: {resp.text[:500]}")
      data = self._parse_xml(resp.text)
      if not resp.is_success:
        msg = data.get("message", "") or data.get("raw", "") or resp.text[:300]
        raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")
      return data

  async def get_category_by_id(self, category_id: str) -> dict[str, Any]:
    """특정 카테고리 하위 조회. (cateservice 엔드포인트 사용)"""
    url = f"https://api.11st.co.kr/rest/cateservice/category/{category_id}"
    headers = self._headers()
    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info(f"[11번가] GET /cateservice/category/{category_id} → {resp.status_code}")
      data = self._parse_xml(resp.text)
      if not resp.is_success:
        msg = data.get("message", "") or data.get("raw", "") or resp.text[:300]
        raise ElevenstApiError(f"HTTP {resp.status_code}: {msg}")
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

  async def delete_product(self, prd_no: str) -> dict[str, Any]:
    """상품 삭제 (리스트에서 완전 제거)."""
    result = await self._call_api("DELETE", f"/product/{prd_no}")
    return {"success": True, "data": result}

  async def get_product(self, prd_no: str) -> dict[str, Any]:
    """상품 조회."""
    return await self._call_api("GET", f"/product/{prd_no}")

  async def get_orders(self, start_time: str, end_time: str) -> list[dict[str, Any]]:
    """기간별 결제완료 주문 목록 조회.

    Args:
        start_time: 검색시작일 YYYYMMDDhhmm (예: 202603010000)
        end_time:   검색종료일 YYYYMMDDhhmm (예: 202603071200)
        최대 조회 기간: 7일 제한 → 초과 시 자동 분할 조회
    """
    import re as _re
    from datetime import datetime, timedelta

    fmt = "%Y%m%d%H%M"
    start_dt = datetime.strptime(start_time, fmt)
    end_dt = datetime.strptime(end_time, fmt)

    # 7일 단위로 청크 분할
    all_orders: list[dict[str, Any]] = []
    chunk_start = start_dt
    while chunk_start < end_dt:
      chunk_end = min(chunk_start + timedelta(days=7), end_dt)
      chunk_orders = await self._fetch_orders_chunk(
        chunk_start.strftime(fmt), chunk_end.strftime(fmt)
      )
      all_orders.extend(chunk_orders)
      chunk_start = chunk_end

    logger.info("[11번가] 전체 주문 조회 완료: %d건", len(all_orders))
    return all_orders

  async def _fetch_orders_chunk(self, start_time: str, end_time: str) -> list[dict[str, Any]]:
    """7일 이내 단일 구간 주문 조회."""
    import re as _re

    url = f"https://api.11st.co.kr/rest/ordservices/complete/{start_time}/{end_time}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] GET /ordservices/complete/%s/%s → %s", start_time, end_time, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    # EUC-KR 인코딩 처리
    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    # 네임스페이스 + XML 선언 제거 (ET가 euc-kr 멀티바이트 인코딩 미지원)
    xml_text = text.replace("ns2:", "")
    xml_text = _re.sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError as e:
      logger.error("[11번가] 주문 XML 파싱 실패: %s", e)
      return []

    # result_code 확인 (0=결과없음 정상, 음수=에러)
    result_code = root.findtext("result_code", "")
    if result_code:
      if result_code == "0":
        return []
      result_text = root.findtext("result_text", "")
      raise ElevenstApiError(f"주문 조회 에러 ({result_code}): {result_text}")

    orders: list[dict[str, Any]] = []
    for order_el in root.findall("order"):
      order_dict: dict[str, Any] = {}
      for child in order_el:
        order_dict[child.tag] = (child.text or "").strip()
      orders.append(order_dict)

    return orders

  async def confirm_order(
    self,
    ord_no: str,
    ord_prd_seq: str,
    dlv_no: str,
    add_prd_yn: str = "N",
    add_prd_no: str = "null",
  ) -> bool:
    """발주확인처리.

    Args:
        ord_no:      주문번호 (ordNo)
        ord_prd_seq: 주문순번 (ordPrdSeq)
        dlv_no:      배송번호 (dlvNo)
        add_prd_yn:  추가구성상품 여부 (Y/N, 기본 N)
        add_prd_no:  추가구성상품 번호 (없으면 null)

    Returns:
        True if 발주확인 성공
    """
    import re as _re

    url = (
      f"https://api.11st.co.kr/rest/ordservices/reqpackaging"
      f"/{ord_no}/{ord_prd_seq}/{add_prd_yn}/{add_prd_no}/{dlv_no}"
    )
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] 발주확인 ordNo=%s ordPrdSeq=%s → %s", ord_no, ord_prd_seq, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"발주확인 HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    xml_text = _re.sub(r"<\?xml[^?]*\?>", "", text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      raise ElevenstApiError(f"발주확인 응답 XML 파싱 실패: {text[:200]}")

    result_code = root.findtext("result_code", "")
    result_text = root.findtext("result_text", "")
    logger.info("[11번가] 발주확인 결과: code=%s, text=%s", result_code, result_text)

    if result_code != "0":
      raise ElevenstApiError(f"발주확인 에러 ({result_code}): {result_text}")

    return True

  async def ship_order(
    self,
    dlv_no: str,
    invc_no: str,
    dlv_etprs_cd: str,
    dlv_mthd_cd: str = "01",
    send_dt: Optional[str] = None,
  ) -> bool:
    """발송처리 (배송중 처리).

    Args:
        dlv_no:       배송번호 (주문 응답의 dlvNo)
        invc_no:      송장번호
        dlv_etprs_cd: 택배사 코드 (예: 00034=CJ대한통운, 00012=롯데, 00011=한진)
        dlv_mthd_cd:  배송방식 (01=택배, 03=직접, 04=퀵, 05=배송없음, 기본 01)
        send_dt:      발송일 YYYYMMDDhhmm (미입력 시 현재 시각)

    Returns:
        True if 발송처리 성공
    """
    import re as _re
    from datetime import datetime

    if not send_dt:
      send_dt = datetime.now().strftime("%Y%m%d%H%M")

    url = (
      f"https://api.11st.co.kr/rest/ordservices/reqdelivery"
      f"/{send_dt}/{dlv_mthd_cd}/{dlv_etprs_cd}/{invc_no}/{dlv_no}"
    )
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] 발송처리 dlvNo=%s invcNo=%s → %s", dlv_no, invc_no, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"발송처리 HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    xml_text = _re.sub(r"<\?xml[^?]*\?>", "", text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      raise ElevenstApiError(f"발송처리 응답 XML 파싱 실패: {text[:200]}")

    result_code = root.findtext("result_code", "")
    result_text = root.findtext("result_text", "")
    logger.info("[11번가] 발송처리 결과: code=%s, text=%s", result_code, result_text)

    if result_code != "0":
      raise ElevenstApiError(f"발송처리 에러 ({result_code}): {result_text}")

    return True

  async def get_order_status(self, ord_no: str) -> dict[str, Any]:
    """주문번호별 배송/상태 조회.

    Args:
        ord_no: 주문번호

    Returns:
        ordPrdStat 포함 주문 상태 dict
        상태 코드: 202=결제완료, 301=발주확인, 401=발송완료,
                   501=배송완료, 901=수취확인, A01=반품완료, B01=주문취소
    """
    import re as _re

    url = f"https://api.11st.co.kr/rest/claimservice/orderlistalladdr/{ord_no}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] 주문상태 조회 ordNo=%s → %s", ord_no, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"주문상태 조회 HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    xml_text = text.replace("ns2:", "")
    xml_text = _re.sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError as e:
      logger.error("[11번가] 주문상태 XML 파싱 실패: %s", e)
      return {}

    result: dict[str, Any] = {}
    for child in root:
      result[child.tag] = (child.text or "").strip()
    return result

  async def get_outbound_addresses(self) -> list[dict[str, str]]:
    """출고지 주소 목록 조회. GET /rest/areaservice/outboundarea"""
    return await self._get_area_addresses("outboundarea")

  async def get_inbound_addresses(self) -> list[dict[str, str]]:
    """반품/교환지 주소 목록 조회. GET /rest/areaservice/inboundarea"""
    return await self._get_area_addresses("inboundarea")

  async def _get_area_addresses(self, area_type: str) -> list[dict[str, str]]:
    """출고지/반품지 주소 조회 공통 메서드."""
    from xml.etree import ElementTree as ET

    url = f"https://api.11st.co.kr/rest/areaservice/{area_type}"
    headers = self._headers()
    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] GET /areaservice/%s → %s", area_type, resp.status_code)

    if not resp.is_success:
      logger.warning("[11번가] %s 조회 실패: HTTP %s", area_type, resp.status_code)
      return []

    # XML 파싱 (네임스페이스 제거)
    xml_text = resp.text.replace("ns2:", "")
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      logger.error("[11번가] %s XML 파싱 실패", area_type)
      return []

    # result_message 확인
    result_msg = root.findtext("result_message", "")
    if result_msg and result_msg != "SUCCESS":
      logger.warning("[11번가] %s 결과: %s", area_type, result_msg)
      return []

    addresses = []
    for addr_el in root.findall("inOutAddress"):
      addr = {
        "addr": (addr_el.findtext("addr") or "").strip(),
        "addrNm": (addr_el.findtext("addrNm") or "").strip(),
        "addrSeq": (addr_el.findtext("addrSeq") or "").strip(),
        "rcvrNm": (addr_el.findtext("rcvrNm") or "").strip(),
        "gnrlTlphnNo": (addr_el.findtext("gnrlTlphnNo") or "").strip(),
        "prtblTlphnNo": (addr_el.findtext("prtblTlphnNo") or "").strip(),
      }
      if addr["addr"]:
        addresses.append(addr)

    logger.info("[11번가] %s 조회 완료: %d건", area_type, len(addresses))
    return addresses

  # ------------------------------------------------------------------
  # 상품 데이터 변환 (수집 상품 → 11번가 XML 형식)
  # ------------------------------------------------------------------

  @staticmethod
  def transform_product(
    product: dict[str, Any],
    category_code: str = "",
    settings: Optional[dict[str, Any]] = None,
  ) -> str:
    """SambaCollectedProduct → 11번가 상품 등록 XML 변환.

    settings: 계정의 additional_fields (배송비, 출고지, 반품지 등)
    """
    cfg = settings or {}
    name = product.get("name", "")
    sale_price = int(product.get("sale_price", 0))
    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    images = product.get("images") or []
    brand = product.get("brand", "")

    # 계정 설정값 (없으면 기본값)
    tax_type = cfg.get("taxType", "01")
    delivery_type = cfg.get("deliveryType", "DV_FREE")
    delivery_fee = int(cfg.get("deliveryFee", 0) or 0)
    return_fee = int(cfg.get("returnFee", 4000) or 4000)
    exchange_fee = int(cfg.get("exchangeFee", 8000) or 8000)
    ship_from = cfg.get("shipFromAddress", "")
    return_addr = cfg.get("returnAddress", "")
    origin = cfg.get("origin", "") or product.get("origin", "") or "기타"
    as_message = cfg.get("asMessage", "") or "상세페이지 참조"
    return_exchange = cfg.get("returnExchangeGuide", "") or "상세페이지 참조"
    minor_restrict = cfg.get("minorRestrict", "N")

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
  <selMthdCd>01</selMthdCd>
  <aplBgnDy>{datetime.now().strftime('%Y%m%d')}</aplBgnDy>
  <aplEndDy>{(datetime.now().replace(year=datetime.now().year + 1)).strftime('%Y%m%d')}</aplEndDy>
  <prdWeight>0</prdWeight>
  <dlvCnFee>{delivery_fee}</dlvCnFee>
  <dlvGrntYn>Y</dlvGrntYn>
  <dlvCstInstBasiCd>{delivery_type}</dlvCstInstBasiCd>
  <rtngdDlvCst>{return_fee}</rtngdDlvCst>
  <exchDlvCst>{exchange_fee}</exchDlvCst>
  <dlvBsPlc>{_escape_xml(ship_from)}</dlvBsPlc>
  <rtngBsPlc>{_escape_xml(return_addr)}</rtngBsPlc>
  <orgnNm>{_escape_xml(origin)}</orgnNm>
  <taxTypCd>{tax_type}</taxTypCd>
  <minorSelCnYn>{minor_restrict}</minorSelCnYn>
  <htmlDetail><![CDATA[{detail_html}]]></htmlDetail>
  {image_xml}
  {option_xml}
  <asDetail>{_escape_xml(as_message)}</asDetail>
  <rtngExchDetail>{_escape_xml(return_exchange)}</rtngExchDetail>
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

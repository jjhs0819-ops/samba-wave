"""11번가 OpenAPI 클라이언트 - 상품 등록/수정.

인증 방식: 32자리 Open API Key (헤더 전달)
- openapikey: {apiKey}
- 상품 등록: POST /rest/prodservices/prod
- 상품 수정: PUT /rest/prodservices/prod/{prdNo}
"""

from __future__ import annotations

import math
import re
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
        logger.info(f"[11번가] 요청 XML (전체 {len(body)}자): {body}")
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
  # 취소 처리
  # ------------------------------------------------------------------

  async def get_cancel_requests(self, start_time: str, end_time: str) -> list[dict[str, Any]]:
    """기간별 취소 요청 목록 조회.

    Args:
        start_time: 검색시작일 YYYYMMDDhhmm
        end_time:   검색종료일 YYYYMMDDhhmm
        최대 조회 기간: 30일 제한 → 초과 시 자동 분할 조회
    """
    from datetime import timedelta

    fmt = "%Y%m%d%H%M"
    start_dt = datetime.strptime(start_time, fmt)
    end_dt = datetime.strptime(end_time, fmt)

    all_items: list[dict[str, Any]] = []
    chunk_start = start_dt
    while chunk_start < end_dt:
      chunk_end = min(chunk_start + timedelta(days=30), end_dt)
      chunk_items = await self._fetch_claim_list(
        "cancelorders", chunk_start.strftime(fmt), chunk_end.strftime(fmt)
      )
      all_items.extend(chunk_items)
      chunk_start = chunk_end

    logger.info("[11번가] 취소 요청 목록 조회 완료: %d건", len(all_items))
    return all_items

  async def confirm_cancel(
    self,
    ord_prd_cn_seq: str,
    ord_no: str,
    ord_prd_seq: str,
  ) -> bool:
    """취소 승인 처리.

    Args:
        ord_prd_cn_seq: 클레임번호 (취소요청코드)
        ord_no:         주문번호
        ord_prd_seq:    주문순번

    Returns:
        True if 취소승인 성공
    """
    import re as _re

    url = (
      f"https://api.11st.co.kr/rest/claimservice/cancelreqconf"
      f"/{ord_prd_cn_seq}/{ord_no}/{ord_prd_seq}"
    )
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] 취소승인 ordPrdCnSeq=%s ordNo=%s → %s", ord_prd_cn_seq, ord_no, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"취소승인 HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    xml_text = text.replace("ns2:", "").replace("s2:", "")
    xml_text = __import__("re").sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      raise ElevenstApiError(f"취소승인 응답 XML 파싱 실패: {text[:200]}")

    result_code = root.findtext("result_code", "")
    result_text = root.findtext("result_text", "")
    logger.info("[11번가] 취소승인 결과: code=%s, text=%s", result_code, result_text)

    if result_code and result_code != "0":
      raise ElevenstApiError(f"취소승인 에러 ({result_code}): {result_text}")

    return True

  # ------------------------------------------------------------------
  # 반품 처리
  # ------------------------------------------------------------------

  async def get_return_requests(self, start_time: str, end_time: str) -> list[dict[str, Any]]:
    """기간별 반품 요청 목록 조회.

    Args:
        start_time: 검색시작일 YYYYMMDDhhmm
        end_time:   검색종료일 YYYYMMDDhhmm
        최대 조회 기간: 30일 제한 → 초과 시 자동 분할 조회
    """
    from datetime import timedelta

    fmt = "%Y%m%d%H%M"
    start_dt = datetime.strptime(start_time, fmt)
    end_dt = datetime.strptime(end_time, fmt)

    all_items: list[dict[str, Any]] = []
    chunk_start = start_dt
    while chunk_start < end_dt:
      chunk_end = min(chunk_start + timedelta(days=30), end_dt)
      chunk_items = await self._fetch_claim_list(
        "returnorders", chunk_start.strftime(fmt), chunk_end.strftime(fmt)
      )
      all_items.extend(chunk_items)
      chunk_start = chunk_end

    logger.info("[11번가] 반품 요청 목록 조회 완료: %d건", len(all_items))
    return all_items

  async def confirm_return(
    self,
    clm_req_seq: str,
    ord_no: str,
    ord_prd_seq: str,
  ) -> bool:
    """반품 승인 처리.

    Args:
        clm_req_seq:  클레임번호 (반품요청코드)
        ord_no:       주문번호
        ord_prd_seq:  주문순번

    Returns:
        True if 반품승인 성공
    """
    import re as _re

    url = (
      f"https://api.11st.co.kr/rest/claimservice/returnreqconf"
      f"/{clm_req_seq}/{ord_no}/{ord_prd_seq}"
    )
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] 반품승인 clmReqSeq=%s ordNo=%s → %s", clm_req_seq, ord_no, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"반품승인 HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    xml_text = text.replace("ns2:", "").replace("s2:", "")
    xml_text = __import__("re").sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()
    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError:
      raise ElevenstApiError(f"반품승인 응답 XML 파싱 실패: {text[:200]}")

    result_code = root.findtext("result_code", "")
    result_text = root.findtext("result_text", "")
    logger.info("[11번가] 반품승인 결과: code=%s, text=%s", result_code, result_text)

    if result_code and result_code != "0":
      raise ElevenstApiError(f"반품승인 에러 ({result_code}): {result_text}")

    return True

  async def _fetch_claim_list(
    self, claim_type: str, start_time: str, end_time: str
  ) -> list[dict[str, Any]]:
    """취소/반품 목록 단일 구간 조회 공통 메서드.

    Args:
        claim_type: 'cancelorders' 또는 'returnorders'
        start_time: YYYYMMDDhhmm
        end_time:   YYYYMMDDhhmm
    """
    import re as _re

    url = f"https://api.11st.co.kr/rest/claimservice/{claim_type}/{start_time}/{end_time}"
    headers = self._headers()

    async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
      resp = await client.get(url, headers=headers)
      logger.info("[11번가] GET /claimservice/%s/%s/%s → %s", claim_type, start_time, end_time, resp.status_code)

    if not resp.is_success:
      raise ElevenstApiError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    try:
      text = resp.content.decode("euc-kr")
    except Exception:
      text = resp.text

    # 네임스페이스 + XML 선언 제거
    xml_text = text.replace("ns2:", "").replace("s2:", "")
    xml_text = _re.sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()

    try:
      root = ET.fromstring(xml_text)
    except ET.ParseError as e:
      logger.error("[11번가] %s XML 파싱 실패: %s", claim_type, e)
      return []

    # result_code 확인 (0=결과없음 정상, 음수=에러)
    result_code = root.findtext("result_code", "")
    if result_code:
      if result_code == "0":
        return []
      result_text = root.findtext("result_text", "")
      raise ElevenstApiError(f"{claim_type} 조회 에러 ({result_code}): {result_text}")

    items: list[dict[str, Any]] = []
    for order_el in root.findall("order"):
      item: dict[str, Any] = {}
      for child in order_el:
        item[child.tag] = (child.text or "").strip()
      items.append(item)

    return items

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
    from datetime import datetime
    cfg = settings or {}
    name = _clean_product_name(product.get("name", ""))
    sale_price = math.ceil(int(product.get("sale_price", 0)) / 10) * 10
    detail_html = product.get("detail_html", "") or f"<p>{name}</p>"
    images = product.get("images") or []
    brand = product.get("brand", "")

    # 계정 설정값 (없으면 기본값)
    tax_type = cfg.get("taxType", "01")
    # 배송비 종류 코드 변환 (구 문자열 → 11번가 공식 숫자 코드)
    # 01=무료, 02=고정, 03=상품조건부무료, 05=1개당, 07=판매자조건부, 08=출고지조건부, 09=통합출고지
    _dlv_code_map = {"DV_FREE": "01", "DV_FIXED": "02", "DV_COND": "03"}
    raw_dlv = cfg.get("deliveryType", "01")
    delivery_type = _dlv_code_map.get(raw_dlv, raw_dlv) or "01"
    delivery_fee = int(cfg.get("deliveryFee", 0) or 0)
    return_fee = int(cfg.get("returnFee", 4000) or 4000)
    exchange_fee = int(cfg.get("exchangeFee", 8000) or 8000)
    ship_from = cfg.get("shipFromAddress", "")
    return_addr = cfg.get("returnAddress", "")
    # 계정 설정 origin이 '기타'이면 무시하고 상품 실제 원산지 우선 사용
    cfg_origin = cfg.get("origin") or ""
    if cfg_origin == "기타":
      cfg_origin = ""
    origin_raw = cfg_origin or product.get("origin") or ""
    orgn_typ_cd, orgn_dtls_cd, orgn_nm_val = _resolve_origin(origin_raw)
    as_phone = product.get("_as_phone") or cfg.get("asPhone") or ""
    _cfg_as_msg = cfg.get("asMessage", "") or ""
    # "상세페이지 참조" 는 기본값으로 간주 → 전화번호 우선
    if _cfg_as_msg and _cfg_as_msg != "상세페이지 참조":
      as_message = _cfg_as_msg
    elif as_phone:
      as_message = f"A/S 문의: {as_phone}"
    else:
      as_message = "상세페이지 참조"
    return_exchange = cfg.get("returnExchangeGuide", "") or "상세페이지 참조"
    minor_restrict = cfg.get("minorRestrict", "Y")

    # 11Pay 포인트 적립 설정 (계정별 on/off)
    # 셀러오피스 form 필드명 확인: pay11YN, pay11Value, pay11WyCd
    # pay11WyCd=02: 정액(원), pay11WyCd=01: 정률(%)
    llpay_pnt_yn = "Y" if cfg.get("llpayPointEnabled") and str(cfg.get("llpayPointEnabled")) not in ("", "false", "0") else "N"
    llpay_pnt_type = str(cfg.get("llpayPointType", "02") or "02")  # 02=정액, 01=정률
    llpay_pnt_value = int(cfg.get("llpayPointValue", 100) or 100)

    # 복수구매 할인 설정 (계정별 on/off)
    # 셀러오피스 form 필드명: pluYN, pluDscCd(기준유형), pluDscMthdCd(할인방식), pluDscBasis(기준값), pluDscAmtPercnt(할인값)
    # pluDscCd: 01=수량기준, 02=금액기준
    # pluDscMthdCd: 02=정액(원), 01=정률(%)
    mnp_buy_yn = "Y" if cfg.get("multiPurchaseDiscount") and str(cfg.get("multiPurchaseDiscount")) not in ("", "false", "0") else "N"
    mnp_buy_basis_type = str(cfg.get("multiPurchaseBasisType", "01") or "01")
    mnp_buy_dsc_method = str(cfg.get("multiPurchaseDiscountMethod", "02") or "02")
    mnp_buy_qty = int(cfg.get("multiPurchaseQty", 2) or 2)
    mnp_buy_amt = int(cfg.get("multiPurchaseAmt", 1000) or 1000)

    # 이미지 XML — 공식 필드명: prdImage01~04 (imageUrl 아님)
    image_xml = ""
    if images:
      image_xml += f"<prdImage01>{_escape_xml(images[0])}</prdImage01>"
      for i, url in enumerate(images[1:4], start=2):
        image_xml += f"<prdImage0{i}>{_escape_xml(url)}</prdImage0{i}>"

    # 옵션 처리 (싱글옵션 방식 — 옵션개편 이후 공식 포맷)
    # 공식 예제: http://openapi.11st.co.kr/example/singleOption1.txt
    options = product.get("options") or []
    if options:
      option_xml = "<optSelectYn>Y</optSelectYn>\n  <txtColCnt>1</txtColCnt>\n  <colTitle>사이즈</colTitle>\n  <prdExposeClfCd>00</prdExposeClfCd>"
      for opt in options:
        opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
        raw_stock = opt.get("stock")
        is_sold_out = opt.get("isSoldOut", False)
        # stock이 None이면 재고미상(999), 0이면 품절(useYn=N), 양수면 그대로
        if raw_stock is None:
          stock_qty = 999
          use_yn = "Y"
        elif raw_stock <= 0 or is_sold_out:
          stock_qty = 0
          use_yn = "N"
        else:
          stock_qty = int(raw_stock)
          use_yn = "Y"
        stock_code = opt.get("managedCode", "") or ""
        option_xml += f"""
  <ProductOption>
    <useYn>{use_yn}</useYn>
    <colOptPrice>0</colOptPrice>
    <colValue0>{_escape_xml(str(opt_name))}</colValue0>
    <colCount>{stock_qty}</colCount>
    <colSellerStockCd>{_escape_xml(stock_code)}</colSellerStockCd>
  </ProductOption>"""
    else:
      # 옵션 없는 상품: 기본 옵션 1개 등록 (재고 999)
      option_xml = """<optSelectYn>Y</optSelectYn>
  <txtColCnt>1</txtColCnt>
  <colTitle>옵션</colTitle>
  <prdExposeClfCd>00</prdExposeClfCd>
  <ProductOption>
    <useYn>Y</useYn>
    <colOptPrice>0</colOptPrice>
    <colValue0>기본</colValue0>
    <colCount>999</colCount>
  </ProductOption>"""

    # 홍보문구 자동 생성 (advrtStmt — 한글 14자/영문 28자 제한)
    promo_text = _generate_promo_text(product, name)

    # 상품정보 제공고시 XML (카테고리별 동적 생성)
    notice_xml = _build_elevenst_notice_xml(product)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Product>
  <sellerPrdCd></sellerPrdCd>
  <prdNm>{_escape_xml(name)}</prdNm>
  <advrtStmt>{_escape_xml(promo_text)}</advrtStmt>
  <prdStatCd>01</prdStatCd>
  <prdTypCd>01</prdTypCd>
  <dispCtgrNo>{category_code}</dispCtgrNo>
  <brand>{_escape_xml(brand)}</brand>
  <selPrc>{sale_price}</selPrc>
  <selMthdCd>01</selMthdCd>
  <aplBgnDy>{datetime.now().strftime('%Y%m%d')}</aplBgnDy>
  <selTermUseYn>N</selTermUseYn>
  <prdWeight>0</prdWeight>
  <rmaterialTypCd>04</rmaterialTypCd>
  <orgnTypCd>{orgn_typ_cd}</orgnTypCd>
  {f'<orgnTypDtlsCd>{orgn_dtls_cd}</orgnTypDtlsCd>' if orgn_dtls_cd else ''}
  {f'<orgnNmVal>{_escape_xml(orgn_nm_val)}</orgnNmVal>' if orgn_nm_val else ''}
  <dlvCnFee>{delivery_fee}</dlvCnFee>
  <dlvGrntYn>Y</dlvGrntYn>
  <dlvCstInstBasiCd>{delivery_type}</dlvCstInstBasiCd>
  <rtngdDlvCst>{return_fee}</rtngdDlvCst>
  <exchDlvCst>{exchange_fee}</exchDlvCst>
  <dlvBsPlc>{_escape_xml(ship_from)}</dlvBsPlc>
  <rtngBsPlc>{_escape_xml(return_addr)}</rtngBsPlc>
  <taxTypCd>{tax_type}</taxTypCd>
  <minorSelCnYn>{minor_restrict}</minorSelCnYn>
  <pay11YN>{llpay_pnt_yn}</pay11YN>
  {f'<pay11Value>{llpay_pnt_value}</pay11Value><pay11WyCd>{llpay_pnt_type}</pay11WyCd>' if llpay_pnt_yn == 'Y' else ''}
  <pluYN>{mnp_buy_yn}</pluYN>
  {f'<pluDscCd>{mnp_buy_basis_type}</pluDscCd><pluDscMthdCd>{mnp_buy_dsc_method}</pluDscMthdCd><pluDscBasis>{mnp_buy_qty}</pluDscBasis><pluDscAmtPercnt>{mnp_buy_amt}</pluDscAmtPercnt>' if mnp_buy_yn == 'Y' else ''}
  <crtfGrpObjClfCd01>03</crtfGrpObjClfCd01>
  <crtfGrpObjClfCd02>03</crtfGrpObjClfCd02>
  <crtfGrpObjClfCd03>03</crtfGrpObjClfCd03>
  <crtfGrpObjClfCd04>05</crtfGrpObjClfCd04>
  {image_xml}
  <htmlDetail><![CDATA[{detail_html.replace("]]>", "]]]]><![CDATA[>")}]]></htmlDetail>
  {option_xml}
  {notice_xml}
  <asDetail>{_escape_xml(as_message)}</asDetail>
  <rtngExchDetail>{_escape_xml(return_exchange)}</rtngExchDetail>
</Product>"""
    return xml


# ──────────────────────────────────────────────────────────────
# 원산지 코드 매핑 (셀러오피스 신규상품등록 페이지 실측값 기준)
# 국내(01): orgnTypDtlsCd 불필요 (비농산물 기준)
# 해외(02): orgnTypDtlsCd = 국가코드
# 기타(03): orgnNmVal = 텍스트
# ──────────────────────────────────────────────────────────────
_ORIGIN_COUNTRY_MAP: dict[str, str] = {
  # 아시아
  "그루지야": "1254", "georgia": "1254",
  "네팔": "1255", "nepal": "1255",
  "동티모르": "1256", "east timor": "1256", "timor-leste": "1256",
  "라오스": "1257", "laos": "1257",
  "레바논": "1258", "lebanon": "1258",
  "말레이시아": "1259", "malaysia": "1259",
  "몰디브": "1260", "maldives": "1260",
  "몽골": "1261", "mongolia": "1261",
  "미얀마": "1262", "myanmar": "1262", "burma": "1262",
  "바레인": "1263", "bahrain": "1263",
  "방글라데시": "1264", "bangladesh": "1264",
  "베트남": "1265", "vietnam": "1265", "viet nam": "1265",
  "부탄": "1266", "bhutan": "1266",
  "브루나이": "1267", "brunei": "1267",
  "사우디아라비아": "1268", "saudi arabia": "1268",
  "스리랑카": "1269", "sri lanka": "1269",
  "시리아": "1270", "syria": "1270",
  "싱가포르": "1271", "singapore": "1271",
  "아랍에미리트": "1272", "uae": "1272", "u.a.e.": "1272",
  "아르메니아": "1273", "armenia": "1273",
  "아제르바이잔": "1274", "azerbaijan": "1274",
  "아프가니스탄": "1275", "afghanistan": "1275",
  "예멘": "1276", "yemen": "1276",
  "오만": "1277", "oman": "1277",
  "요르단": "1278", "jordan": "1278",
  "우즈베키스탄": "1279", "uzbekistan": "1279",
  "이라크": "1280", "iraq": "1280",
  "이란": "1281", "iran": "1281",
  "이스라엘": "1282", "israel": "1282",
  "인도": "1283", "india": "1283",
  "인도네시아": "1284", "indonesia": "1284",
  "일본": "1285", "japan": "1285",
  "중국": "1287", "china": "1287",
  "카자흐스탄": "1288", "kazakhstan": "1288",
  "카타르": "1289", "qatar": "1289",
  "캄보디아": "1290", "cambodia": "1290",
  "쿠웨이트": "1291", "kuwait": "1291",
  "키르기스스탄": "1292", "kyrgyzstan": "1292",
  "태국": "1293", "thailand": "1293",
  "타이완": "1294", "taiwan": "1294",
  "타지키스탄": "1295", "tajikistan": "1295",
  "투르크메니스탄": "1296", "turkmenistan": "1296",
  "파키스탄": "1297", "pakistan": "1297",
  "필리핀": "1298", "philippines": "1298",
  # 아프리카
  "가나": "1299", "ghana": "1299",
  "가봉": "1300", "gabon": "1300",
  "감비아": "1301", "gambia": "1301",
  "기니": "1302", "guinea": "1302",
  "나미비아": "1304", "namibia": "1304",
  "나이지리아": "1305", "nigeria": "1305",
  "남아프리카공화국": "1306", "남아공": "1306", "south africa": "1306",
  "르완다": "1310", "rwanda": "1310",
  "모로코": "1315", "morocco": "1315",
  "에티오피아": "1334", "ethiopia": "1334",
  "이집트": "1336", "egypt": "1336",
  "케냐": "1345", "kenya": "1345",
  "탄자니아": "1350", "tanzania": "1350",
  "튀니지": "1352", "tunisia": "1352",
  # 유럽
  "그리스": "1353", "greece": "1353",
  "네덜란드": "1354", "netherlands": "1354", "holland": "1354",
  "노르웨이": "1355", "norway": "1355",
  "덴마크": "1356", "denmark": "1356",
  "독일": "1357", "germany": "1357",
  "러시아": "1359", "russia": "1359",
  "루마니아": "1360", "romania": "1360",
  "룩셈부르크": "1361", "luxembourg": "1361",
  "벨기에": "1370", "belgium": "1370",
  "불가리아": "1373", "bulgaria": "1373",
  "스웨덴": "1376", "sweden": "1376",
  "스위스": "1377", "switzerland": "1377",
  "스페인": "1378", "spain": "1378",
  "슬로바키아": "1379", "slovakia": "1379",
  "아일랜드": "1382", "ireland": "1382",
  "알바니아": "1384", "albania": "1384",
  "에스토니아": "1385", "estonia": "1385",
  "영국": "1386", "uk": "1386", "united kingdom": "1386", "britain": "1386",
  "오스트리아": "1387", "austria": "1387",
  "우크라이나": "1388", "ukraine": "1388",
  "이탈리아": "1389", "italy": "1389",
  "체코": "1390", "czech": "1390", "czechia": "1390",
  "크로아티아": "1391", "croatia": "1391",
  "튀르키예": "1393", "turkey": "1393", "터키": "1393",
  "포르투갈": "1394", "portugal": "1394",
  "폴란드": "1395", "poland": "1395",
  "프랑스": "1396", "france": "1396",
  "핀란드": "1397", "finland": "1397",
  "헝가리": "1398", "hungary": "1398",
  # 북아메리카
  "과테말라": "1399", "guatemala": "1399",
  "멕시코": "1404", "mexico": "1404",
  "미국": "1405", "usa": "1405", "us": "1405", "united states": "1405",
  "캐나다": "1417", "canada": "1417",
  "코스타리카": "1418", "costa rica": "1418",
  "쿠바": "1419", "cuba": "1419",
  "파나마": "1421", "panama": "1421",
  # 남아메리카
  "브라질": "1425", "brazil": "1425",
  "아르헨티나": "1427", "argentina": "1427",
  "에콰도르": "1428", "ecuador": "1428",
  "우루과이": "1429", "uruguay": "1429",
  "칠레": "1430", "chile": "1430",
  "콜롬비아": "1431", "colombia": "1431",
  "페루": "1433", "peru": "1433",
  # 오세아니아
  "뉴질랜드": "1435", "new zealand": "1435",
  "오스트레일리아": "1441", "호주": "1441", "australia": "1441",
  "파푸아뉴기니": "1445", "papua new guinea": "1445",
  "피지": "1447", "fiji": "1447",
}

# 국내로 인식할 키워드
_ORIGIN_DOMESTIC_KEYWORDS = {"한국", "국내", "korea", "south korea", "대한민국"}


def _resolve_origin(origin: str) -> tuple[str, str, str]:
  """원산지 문자열 → (orgnTypCd, orgnTypDtlsCd, orgnNmVal).

  Returns:
    orgnTypCd: 01=국내, 02=해외, 03=기타
    orgnTypDtlsCd: 해외일 때 국가코드 (셀러오피스 실측값)
    orgnNmVal: 기타일 때 원산지명 텍스트
  """
  if not origin:
    return ("03", "", "기타")

  normalized = origin.strip().lower()

  if normalized in _ORIGIN_DOMESTIC_KEYWORDS:
    return ("01", "", "")

  country_code = _ORIGIN_COUNTRY_MAP.get(normalized)
  if country_code:
    return ("02", country_code, "")

  # 매핑 없는 국가명은 기타로 처리
  return ("03", "", origin.strip())


def _escape_xml(text: str) -> str:
  """XML 특수문자 이스케이프."""
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )


# ──────────────────────────────────────────────────────────────
# 상품명 정제 + 홍보문구 자동 생성
# 공식 필드: prdNm(100자), advrtStmt(한글 14자/영문 28자)
# ──────────────────────────────────────────────────────────────

# 세부 카테고리 키워드 → 홍보문구 템플릿 (한글 14자 이내)
_PROMO_CATEGORY_TEMPLATES: list[tuple[str, str]] = [
  # 아우터
  ("패딩",    "시즌 필수 패딩 아이템"),
  ("코트",    "프리미엄 클래식 코트"),
  ("야상",    "스트릿 감성 아우터"),
  ("점퍼",    "스타일 업 아우터"),
  ("바람막이", "경량 스포티 아우터"),
  ("아우터",  "시즌 트렌드 아우터"),
  # 상의
  ("후드티",  "캐주얼 스트릿 무드"),
  ("후드",    "캐주얼 스트릿 무드"),
  ("맨투맨",  "베이직 캐주얼 완성"),
  ("스웨트",  "베이직 캐주얼 완성"),
  ("니트",    "시즌 감성 니트"),
  ("블라우스", "페미닌 감성 스타일"),
  ("셔츠",    "클래식 셔츠 스타일"),
  ("티셔츠",  "베이직 데일리 티"),
  ("상의",    "데일리 무드 완성"),
  # 하의
  ("청바지",  "데님 데일리 스타일"),
  ("데님",    "데님 데일리 스타일"),
  ("슬랙스",  "세련된 보텀 스타일"),
  ("레깅스",  "액티브 데일리 룩"),
  ("스커트",  "페미닌 스타일 완성"),
  ("치마",    "페미닌 스타일 완성"),
  ("반바지",  "시즌 데일리 쇼츠"),
  ("바지",    "트렌디 보텀 스타일"),
  ("하의",    "트렌디 보텀 스타일"),
  # 원피스/세트
  ("원피스",  "페미닌 감성 드레스"),
  ("드레스",  "페미닌 감성 드레스"),
  ("세트",    "코디 완성 세트"),
  # 신발
  ("스니커즈", "데일리 스타일 완성"),
  ("운동화",  "데일리 스타일 완성"),
  ("구두",    "클래식 포멀 슈즈"),
  ("부츠",    "시즌 트렌드 부츠"),
  ("샌들",    "시즌 감성 샌들"),
  ("슬리퍼",  "편안한 데일리 슈즈"),
  ("신발",    "데일리 스타일 완성"),
  # 가방
  ("백팩",    "실용 데일리 백팩"),
  ("크로스백", "데일리 크로스 스타일"),
  ("숄더백",  "시즌 트렌드 숄더백"),
  ("토트백",  "실용 데일리 토트백"),
  ("가방",    "프리미엄 패션 백"),
  # 잡화/액세서리
  ("모자",    "데일리 포인트 모자"),
  ("벨트",    "스타일 포인트 벨트"),
  ("지갑",    "슬림 패션 지갑"),
  ("시계",    "세련된 패션 시계"),
  ("주얼리",  "감성 패션 주얼리"),
  ("액세서리", "패션 감성 완성"),
]

# 그룹별 기본 템플릿 (세부 키워드 미매칭 시)
_PROMO_GROUP_TEMPLATES: dict[str, list[str]] = {
  "wear":        ["데일리 무드 컬렉션", "시즌 트렌드 패션", "프리미엄 패션 아이템"],
  "shoes":       ["데일리 스타일 완성", "트렌디 슈즈 컬렉션", "시즌 인기 슈즈"],
  "bag":         ["프리미엄 패션 백", "시즌 트렌드 가방", "데일리 스타일 백"],
  "accessories": ["패션 감성 완성", "시즌 트렌드 잡화", "데일리 패션 잡화"],
  "etc":         ["프리미엄 품질 보장", "시즌 트렌드 아이템", "데일리 추천 상품"],
}

# 상품명 금지 패턴 (배송/이벤트/할인 관련)
_NAME_REMOVE_PATTERNS = [
  r'무료\s*배송', r'배송\s*무료', r'당일\s*발송', r'오늘\s*발송',
  r'\d+\s*%\s*할인', r'할인\s*\d+\s*%', r'할인가', r'특가',
  r'이벤트', r'사은품', r'증정품', r'기간\s*한정', r'한정\s*수량',
  r'\[세일\]', r'\[특가\]', r'\[할인\]', r'\[행사\]',
  r':?\s*세일', r'세일\s*:?',
]


def _clean_product_name(name: str) -> str:
  """11번가 등록용 상품명 정제 (금지어 제거 + 100자 제한)."""
  for pattern in _NAME_REMOVE_PATTERNS:
    name = re.sub(pattern, "", name, flags=re.IGNORECASE)
  # 연속 공백 정리
  name = re.sub(r"\s+", " ", name).strip()
  # 100자 제한
  return name[:100].strip()


def _validate_promo_clean(promo: str, name: str) -> bool:
  """홍보문구 클린체크 6가지 기준 검증.

  1) 상품명 단어 2개 이상 중복 → 부적합
  2) 숫자/특수문자만 → 부적합
  3) 3글자 이하 → 부적합
  4) 배송 정보 포함 → 부적합
  5) 인사말/부적합 단어 → 부적합
  6) 전화번호 포함 → 부적합
  + 한글 14자 초과 → 부적합
  """
  promo = promo.strip()
  if not promo:
    return False
  # 길이 체크 (한글 기준 14자)
  if len(promo) > 14:
    return False
  # 3글자 이하
  if len(promo) <= 3:
    return False
  # 숫자/특수문자만
  if re.match(r"^[0-9\W]+$", promo):
    return False
  # 배송 정보
  if re.search(r"무료배송|오늘발송|당일배송|빠른배송|익일배송|오늘출발", promo):
    return False
  # 인사말/부적합 단어
  if re.search(r"상세설명참조|감사합니다|안녕하세요|문의주세요", promo):
    return False
  # 전화번호
  if re.search(r"\d{2,4}[-\s]?\d{3,4}[-\s]?\d{4}", promo):
    return False
  # 상품명 단어 2개 이상 겹치면 부적합 (2자 이상 한글/영문)
  name_words = set(re.findall(r"[가-힣a-zA-Z]{2,}", name))
  promo_words = set(re.findall(r"[가-힣a-zA-Z]{2,}", promo))
  if len(name_words & promo_words) >= 2:
    return False
  return True


def _generate_promo_text(product: dict, name: str) -> str:
  """카테고리 기반 홍보문구 자동 생성 (한글 14자 이내).

  우선순위: 세부 카테고리 키워드 → 그룹 기본 템플릿 → fallback
  """
  from backend.domain.samba.proxy.notice_utils import detect_notice_group

  group = detect_notice_group(product)
  search_text = " ".join(filter(None, [
    product.get("category") or "",
    product.get("category1") or "",
    product.get("name") or "",
  ])).lower()

  # 세부 키워드 매핑 시도
  for keyword, template in _PROMO_CATEGORY_TEMPLATES:
    if keyword in search_text:
      if _validate_promo_clean(template, name):
        return template

  # 그룹 기본 템플릿
  for template in _PROMO_GROUP_TEMPLATES.get(group, _PROMO_GROUP_TEMPLATES["etc"]):
    if _validate_promo_clean(template, name):
      return template

  return "프리미엄 브랜드 상품"


# ──────────────────────────────────────────────────────────────
# 상품정보 제공고시 (11번가 공식 API 문서 + 셀러오피스 UI 실측값 기준)
# 출처: openapi.11st.co.kr 상품관리 > 상품등록 파라미터 및
#       soffice.11st.co.kr/product/BulkProductReg.tmall?method=goProductNotiPop
# ──────────────────────────────────────────────────────────────

# detect_notice_group() 반환값 → 11번가 유형 코드
_ELEVENST_NOTICE_TYPE_CODE: dict[str, str] = {
  "wear": "891011",         # 의류
  "shoes": "891012",        # 구두/신발
  "bag": "891013",          # 가방
  "accessories": "891014",  # 패션잡화 (모자/벨트/액세서리 등)
}

# 유형별 항목 코드 목록 (code, 항목명) — 공식 문서 실측값
# API XML: <item><code>코드</code><name>값</name></item>
_ELEVENST_NOTICE_ITEMS: dict[str, list[tuple[str, str]]] = {
  "wear": [
    ("11835",    "색상"),
    ("23756520", "세탁방법 및 취급시 주의사항"),
    ("23759095", "제조국"),
    ("23760437", "A/S 책임자와 전화번호"),
    ("23759468", "제품 소재"),
    ("23760034", "치수"),
    ("23760386", "품질보증기준"),
    ("11905",    "제조자/수입자"),
    ("23759308", "제조연월"),
  ],
  "shoes": [
    ("11835",    "색상"),
    ("11905",    "제조자/수입자"),
    ("23759095", "제조국"),
    ("40748371", "제품 주소재"),
    ("23760034", "치수"),
    ("23760386", "품질보증기준"),
    ("23760437", "A/S 책임자와 전화번호"),
    ("23759972", "취급시 주의사항"),
  ],
  "bag": [
    ("11835",    "색상"),
    ("11848",    "소재"),
    ("11905",    "제조자/수입자"),
    ("11908",    "종류"),
    ("23760437", "A/S 책임자와 전화번호"),
    ("23759095", "제조국"),
    ("23759972", "취급시 주의사항"),
    ("23760386", "품질보증기준"),
    ("11932",    "크기,용량,형태"),
  ],
  "accessories": [
    ("11848",    "소재"),
    ("11905",    "제조자/수입자"),
    ("11908",    "종류"),
    ("23760437", "A/S 책임자와 전화번호"),
    ("23759972", "취급시 주의사항"),
    ("23760034", "치수"),
    ("23760386", "품질보증기준"),
    ("23759095", "제조국"),
  ],
}

# 카테고리별 취급주의사항 기본 문구
_ELEVENST_CAUTION_DEFAULTS: dict[str, str] = {
  "wear": "세탁 시 뒤집어서 단독 손세탁, 표백제 사용 금지, 직사광선을 피해 그늘에서 건조",
  "shoes": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 화학제품 사용 금지",
  "bag": "직사광선 및 고온 다습한 환경을 피해 보관, 마찰에 의한 색 이염 주의",
  "accessories": "직사광선 및 습기를 피해 보관, 화학제품 접촉 주의",
}


def _build_elevenst_notice_xml(product: dict[str, Any]) -> str:
  """상품 카테고리에 맞는 11번가 상품정보 제공고시 XML 블록 생성.

  - XML 태그: <ProductNotification> (공식 API 문서 기준)
  - 항목 구조: <item><code>항목코드</code><name>값</name></item>
  - 항목 코드: 11번가 공식 문서(goProductNotiPop) 실측값
  - 무신사 수집 데이터(material/color/manufacturer 등) 동적 매핑
  """
  from backend.domain.samba.proxy.notice_utils import detect_notice_group

  group = detect_notice_group(product)
  type_code = _ELEVENST_NOTICE_TYPE_CODE.get(group, "891011")
  items = _ELEVENST_NOTICE_ITEMS.get(group, _ELEVENST_NOTICE_ITEMS["wear"])

  fallback = "상세페이지 참조"

  # 취급 주의사항: 수집값 우선, 없으면 카테고리별 기본문구
  # HTML 태그 및 이스케이프된 태그 제거
  def _strip_html(text: str) -> str:
    import re as _re
    text = _re.sub(r'&lt;[^&]*&gt;', ' ', text)   # &lt;br&gt; 등 이스케이프된 태그 제거
    text = _re.sub(r'<[^>]+>', ' ', text)           # <br> 등 일반 HTML 태그 제거
    text = _re.sub(r'\s+', ' ', text).strip()
    return text

  raw_caution = (
    product.get("care_instructions", "")
    or product.get("careInstructions", "")
    or ""
  )
  caution = _strip_html(raw_caution) if raw_caution else _ELEVENST_CAUTION_DEFAULTS.get(group, fallback)

  # 옵션에서 사이즈 텍스트 생성
  options = product.get("options") or []
  sizes = [opt.get("name") or opt.get("size", "") for opt in options]
  size_text = ", ".join(filter(None, sizes)) if sizes else fallback

  # 항목 코드 → 값 매핑
  code_value_map: dict[str, str] = {
    "11835":    product.get("color", "") or fallback,          # 색상
    "23756520": caution,                                        # 세탁방법 및 취급시 주의사항
    "23759972": caution,                                        # 취급시 주의사항
    "23759095": product.get("origin", "") or fallback,         # 제조국
    "23760437": product.get("_as_phone") or fallback,            # A/S 책임자와 전화번호
    "23759468": product.get("material", "") or fallback,       # 제품 소재
    "40748371": product.get("material", "") or fallback,       # 제품 주소재
    "11848":    product.get("material", "") or fallback,       # 소재
    "23760034": size_text,                                      # 치수
    "23760386": "제품 이상 시 공정거래위원회 고시 소비자분쟁해결기준에 의거 보상합니다.",  # 품질보증기준
    "11905":    product.get("manufacturer", "") or product.get("brand", "") or fallback,  # 제조자/수입자
    "23759308": fallback,                                       # 제조연월
    "11932":    fallback,                                       # 크기,용량,형태
    "11908":    fallback,                                       # 종류
  }

  items_xml = ""
  for code, _ in items:
    value = code_value_map.get(code, fallback)
    items_xml += f"""
  <item>
    <code>{code}</code>
    <name>{_escape_xml(value)}</name>
  </item>"""

  # company: 제조사/수입사 (API 문서 별도 필드)
  company = product.get("manufacturer", "") or product.get("brand", "") or "없음"

  return f"""<ProductNotification>
  <type>{type_code}</type>{items_xml}
  <company>{_escape_xml(company)}</company>
  <modelNm>{_escape_xml(product.get("style_code", "") or "없음")}</modelNm>
</ProductNotification>"""


class ElevenstApiError(Exception):
  """11번가 API 에러."""
  pass

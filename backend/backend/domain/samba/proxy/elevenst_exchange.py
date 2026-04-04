"""11번가 교환 처리 클레임 서비스 클라이언트.

elevenst.py의 들여쓰기 혼용 문제로 인해 교환 관련 메서드를 별도 파일로 분리.
ElevenstExchangeClient를 통해 사용하거나, ElevenstClient에 mixin 방식으로 사용.

11번가 교환 처리 API (클레임 서비스):
  - GET /rest/claimservice/exchangeorders/{start}/{end}  — 교환 요청 목록 조회
  - GET /rest/claimservice/exchangereqconf/{clmReqSeq}/{ordNo}/{ordPrdSeq}  — 교환 승인
  - GET /rest/claimservice/exchangereqrej/{clmReqSeq}/{ordNo}/{ordPrdSeq}   — 교환 거부

11번가 API가 제공하지 않는 정보 (samba_return 테이블 수기 입력 필드로 관리):
  - 교환 상품 회수 상태/일자 (exchange_retrieval_status, exchange_retrieved_at)
  - 소싱처 재출고 택배사/송장 (exchange_reship_company, exchange_reship_tracking)
  - 고객 교환 상품 도착 일자 (exchange_delivered_at)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class ElevenstApiError(Exception):
    """11번가 API 호출 오류."""


class ElevenstExchangeClient:
    """11번가 교환 클레임 처리 클라이언트."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {
            "openapikey": self.api_key,
            "Content-Type": "text/xml; charset=UTF-8",
            "Accept": "application/xml",
        }

    def _parse_claim_xml(self, text: str) -> list[dict[str, Any]]:
        """클레임 목록 XML 응답 파싱."""
        xml_text = text.replace("ns2:", "").replace("s2:", "")
        xml_text = re.sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error("[11번가 교환] XML 파싱 실패: %s", e)
            return []

        result_code = root.findtext("result_code", "")
        if result_code:
            if result_code == "0":
                return []
            result_text = root.findtext("result_text", "")
            raise ElevenstApiError(
                f"교환 목록 조회 에러 ({result_code}): {result_text}"
            )

        items: list[dict[str, Any]] = []
        for order_el in root.findall("order"):
            item: dict[str, Any] = {}
            for child in order_el:
                item[child.tag] = (child.text or "").strip()
            items.append(item)

        return items

    def _parse_action_xml(self, text: str, action_name: str) -> bool:
        """교환 승인/거부 XML 응답 파싱."""
        xml_text = text.replace("ns2:", "").replace("s2:", "")
        xml_text = re.sub(r"<\?xml[^?]*\?>", "", xml_text, count=1).strip()

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            raise ElevenstApiError(f"{action_name} 응답 XML 파싱 실패: {text[:200]}")

        result_code = root.findtext("result_code", "")
        result_text = root.findtext("result_text", "")
        logger.info(
            "[11번가] %s 결과: code=%s, text=%s", action_name, result_code, result_text
        )

        if result_code and result_code != "0":
            raise ElevenstApiError(f"{action_name} 에러 ({result_code}): {result_text}")

        return True

    async def _get_euc_kr(self, url: str) -> str:
        """GET 요청 후 EUC-KR 디코딩."""
        async with httpx.AsyncClient(timeout=settings.http_timeout_default) as client:
            resp = await client.get(url, headers=self._headers())

        if not resp.is_success:
            raise ElevenstApiError(f"HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            return resp.content.decode("euc-kr")
        except Exception:
            return resp.text

    async def get_exchange_requests(
        self, start_time: str, end_time: str
    ) -> list[dict[str, Any]]:
        """기간별 교환 요청 목록 조회.

        11번가 클레임 서비스 API:
          GET /rest/claimservice/exchangeorders/{start}/{end}

        Args:
            start_time: 검색시작일 YYYYMMDDhhmm
            end_time:   검색종료일 YYYYMMDDhhmm
            최대 조회 기간: 30일 제한 → 초과 시 자동 분할 조회

        Returns:
            교환 요청 목록. 주요 필드 (11번가 API 제공):
              ordNo, ordPrdSeq, clmReqSeq, clmRsn, clmRqsDt,
              prdNm, sellAmt, qty, buyMbrNm, rcvNm, rcvAddr, rcvTelNo,
              ordPrdStatCd

            ※ 회수 상태/일자, 소싱처 출고 정보, 고객 도착일은 API 미제공
              → samba_return 테이블 수기 입력 필드로 관리
        """
        fmt = "%Y%m%d%H%M"
        start_dt = datetime.strptime(start_time, fmt)
        end_dt = datetime.strptime(end_time, fmt)

        all_items: list[dict[str, Any]] = []
        chunk_start = start_dt
        while chunk_start < end_dt:
            chunk_end = min(chunk_start + timedelta(days=30), end_dt)
            url = (
                f"https://api.11st.co.kr/rest/claimservice/exchangeorders"
                f"/{chunk_start.strftime(fmt)}/{chunk_end.strftime(fmt)}"
            )
            logger.info(
                "[11번가 교환] GET exchangeorders %s ~ %s",
                chunk_start.strftime(fmt),
                chunk_end.strftime(fmt),
            )
            text = await self._get_euc_kr(url)
            items = self._parse_claim_xml(text)
            all_items.extend(items)
            chunk_start = chunk_end

        logger.info("[11번가 교환] 교환 요청 목록 조회 완료: %d건", len(all_items))
        return all_items

    async def confirm_exchange(
        self,
        clm_req_seq: str,
        ord_no: str,
        ord_prd_seq: str,
    ) -> bool:
        """교환 승인(재배송) 처리.

        11번가 클레임 서비스 API:
          GET /rest/claimservice/exchangereqconf/{clmReqSeq}/{ordNo}/{ordPrdSeq}

        Args:
            clm_req_seq:  클레임번호 (교환요청코드)
            ord_no:       주문번호
            ord_prd_seq:  주문순번

        Returns:
            True if 교환승인 성공
        """
        url = (
            f"https://api.11st.co.kr/rest/claimservice/exchangereqconf"
            f"/{clm_req_seq}/{ord_no}/{ord_prd_seq}"
        )
        logger.info("[11번가 교환] 교환승인 clmReqSeq=%s ordNo=%s", clm_req_seq, ord_no)
        text = await self._get_euc_kr(url)
        return self._parse_action_xml(text, "교환승인")

    async def reject_exchange(
        self,
        clm_req_seq: str,
        ord_no: str,
        ord_prd_seq: str,
        reason: str = "판매자 교환 거부",
    ) -> bool:
        """교환 거부 처리.

        11번가 클레임 서비스 API:
          GET /rest/claimservice/exchangereqrej/{clmReqSeq}/{ordNo}/{ordPrdSeq}

        Args:
            clm_req_seq:  클레임번호 (교환요청코드)
            ord_no:       주문번호
            ord_prd_seq:  주문순번
            reason:       거부 사유 (내부 기록용 — 11번가 API 사유 파라미터 미지원)

        Returns:
            True if 교환거부 성공
        """
        url = (
            f"https://api.11st.co.kr/rest/claimservice/exchangereqrej"
            f"/{clm_req_seq}/{ord_no}/{ord_prd_seq}"
        )
        logger.info(
            "[11번가 교환] 교환거부 clmReqSeq=%s ordNo=%s reason=%s",
            clm_req_seq,
            ord_no,
            reason,
        )
        text = await self._get_euc_kr(url)
        return self._parse_action_xml(text, "교환거부")

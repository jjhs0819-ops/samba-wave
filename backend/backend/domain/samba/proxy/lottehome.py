"""롯데홈쇼핑(롯데아이몰) OpenAPI 클라이언트 - httpx 기반.

proxy-server.mjs의 롯데홈쇼핑 관련 로직을 Python으로 포팅.
EUC-KR 인코딩 요청 / XML 응답 처리를 지원한다.

주요 특징:
- EUC-KR 인코딩 요청 (UTF-8 → EUC-KR 자동 변환)
- XML 응답 파싱 (defusedxml 사용)
- 인증키 자동 관리 (24시간 유효, 캐시 지원)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx

from backend.core.config import settings
from backend.utils.logger import logger


class LotteHomeClient:
    """롯데홈쇼핑(롯데아이몰) OpenAPI 클라이언트."""

    TEST_BASE = "http://openapitst.lotteimall.com/openapi/"
    PROD_BASE = "https://openapi.lotteimall.com/openapi/"

    def __init__(
        self,
        user_id: str,
        password: str,
        agnc_no: str = "",
        env: str = "test",
    ) -> None:
        self.user_id = user_id
        self.password = password
        self.agnc_no = agnc_no
        self.env = env

        # 인증 캐시 (메모리)
        self._cert_key: str = ""
        self._cert_expires_at: Optional[datetime] = None

    @property
    def base_url(self) -> str:
        return self.PROD_BASE if self.env == "prod" else self.TEST_BASE

    # ------------------------------------------------------------------
    # EUC-KR encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_euc_kr(val: str) -> str:
        """UTF-8 문자열을 EUC-KR 퍼센트 인코딩으로 변환."""
        try:
            encoded = val.encode("euc-kr")
        except (UnicodeEncodeError, LookupError):
            encoded = val.encode("utf-8")
        return "".join(f"%{b:02X}" for b in encoded)

    @staticmethod
    def _build_query(params: dict[str, Any]) -> str:
        """파라미터를 EUC-KR 인코딩된 쿼리스트링으로 변환."""
        parts = []
        for k, v in params.items():
            if v is None or v == "":
                continue
            from urllib.parse import quote

            parts.append(f"{quote(k)}={LotteHomeClient._encode_euc_kr(str(v))}")
        return "&".join(parts)

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_xml_to_dict(element: ET.Element) -> Any:
        """XML Element를 dict/str로 재귀 변환."""
        children = list(element)
        if not children:
            return (element.text or "").strip()

        result: dict[str, Any] = {}
        # 속성 포함
        for attr_name, attr_val in element.attrib.items():
            result[f"@_{attr_name}"] = attr_val

        for child in children:
            tag = child.tag
            value = LotteHomeClient._parse_xml_to_dict(child)
            if tag in result:
                existing = result[tag]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    result[tag] = [existing, value]
            else:
                result[tag] = value
        return result

    @staticmethod
    def _parse_lotte_response(xml_str: str) -> dict[str, Any]:
        """롯데홈쇼핑 XML 응답 파싱 (성공/에러 분기)."""
        root_el = ET.fromstring(xml_str)
        parsed = LotteHomeClient._parse_xml_to_dict(root_el)

        # 실제 루트는 대문자 Response
        root = parsed if isinstance(parsed, dict) else {}

        # 에러 블록 확인
        errors = root.get("Errors") or root.get("errors")
        if errors:
            error_block = (
                errors.get("Error")
                if isinstance(errors, dict)
                else errors
            )
            if isinstance(error_block, dict):
                code = error_block.get("Code", error_block.get("code", ""))
                msg = error_block.get("Message") or error_block.get("message", "알 수 없는 오류")
                if str(code) != "0":
                    raise LotteApiError(code=str(code), message=str(msg))

        return {"success": True, "data": root, "rawXml": xml_str}

    @staticmethod
    def _find_cert_key(obj: Any, depth: int = 0) -> Optional[str]:
        """응답 객체에서 인증키 필드를 재귀 탐색."""
        if not isinstance(obj, dict) or depth > 5:
            return None

        cert_key_names = [
            "certification_key",
            "certkey",
            "cert_key",
            "strcertkey",
            "certificationkey",
            "authkey",
            "auth_key",
            "token",
            "strtoken",
            "sessionkey",
            "session_key",
            "subscriptionid",
        ]

        for k, v in obj.items():
            if k.lower() in cert_key_names and v and not isinstance(v, dict):
                return str(v)

        for v in obj.values():
            if isinstance(v, dict):
                found = LotteHomeClient._find_cert_key(v, depth + 1)
                if found:
                    return found
        return None

    # ------------------------------------------------------------------
    # Low-level API caller
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        endpoint: str,
        method: str = "POST",
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """롯데홈쇼핑 API 공통 호출 (EUC-KR 인코딩)."""
        params = params or {}
        url = self.base_url + endpoint
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=euc-kr",
            "Accept": "text/xml; charset=euc-kr",
            "Accept-Charset": "euc-kr",
        }

        timeout = httpx.Timeout(settings.http_timeout_default, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                qs = self._build_query(params)
                if qs:
                    url = f"{url}?{qs}"
                resp = await client.get(url, headers=headers)
            else:
                body = self._build_query(params)
                resp = await client.post(url, content=body, headers=headers)

            # EUC-KR 응답을 UTF-8로 변환
            raw_bytes = resp.content
            try:
                xml_str = raw_bytes.decode("euc-kr")
            except (UnicodeDecodeError, LookupError):
                xml_str = raw_bytes.decode("utf-8", errors="replace")

            # XML 선언의 encoding="EUC-KR"을 제거 (이미 UTF-8로 디코딩됨)
            xml_str = re.sub(r'<\?xml[^?]*\?>', '', xml_str).strip()
            return self._parse_lotte_response(xml_str)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def _ensure_auth(self) -> str:
        """인증키 자동 관리 - 캐시 유효하면 재사용, 만료 30분 전이면 갱신."""
        now = datetime.now(tz=timezone.utc)
        refresh_before = timedelta(minutes=30)

        if (
            self._cert_key
            and self._cert_expires_at
            and (self._cert_expires_at - now) > refresh_before
        ):
            return self._cert_key

        params: dict[str, Any] = {
            "strUserId": self.user_id,
            "strPassWd": self.password,
        }
        if self.agnc_no:
            params["strAgncNo"] = self.agnc_no

        result = await self._call_api("createCertification.lotte", "POST", params)
        data = result.get("data", {})

        cert_key = self._find_cert_key(data)
        if not cert_key:
            raise LotteApiError(
                code="AUTH_FAILED",
                message=f"인증키를 응답에서 찾을 수 없습니다. 응답 구조: {data}",
            )

        # 24시간 유효 (23시간 55분)
        self._cert_key = cert_key
        self._cert_expires_at = now + timedelta(hours=23, minutes=55)

        logger.info(
            f"[롯데홈쇼핑] 인증키 발급 완료 (만료: {self._cert_expires_at.isoformat()})"
        )
        return self._cert_key

    async def authenticate(self) -> dict[str, Any]:
        """인증키 발급 (명시적 호출)."""
        cert_key = await self._ensure_auth()
        remaining_minutes = 0
        if self._cert_expires_at:
            remaining_minutes = int(
                (self._cert_expires_at - datetime.now(tz=timezone.utc)).total_seconds()
                / 60
            )
        return {
            "success": True,
            "message": (
                f"인증 성공 (잔여: {remaining_minutes // 60}시간 {remaining_minutes % 60}분)"
            ),
            "certKey": cert_key,
            "expiresAt": (
                self._cert_expires_at.isoformat() if self._cert_expires_at else ""
            ),
            "remaining": remaining_minutes,
        }

    def get_auth_status(self) -> dict[str, Any]:
        """캐시된 인증 상태 확인."""
        if not self._cert_key or not self._cert_expires_at:
            return {"authenticated": False, "message": "인증 정보 없음"}

        remaining = int(
            (self._cert_expires_at - datetime.now(tz=timezone.utc)).total_seconds() / 60
        )
        if remaining <= 0:
            self._cert_key = ""
            self._cert_expires_at = None
            return {"authenticated": False, "message": "인증키 만료됨"}

        return {
            "authenticated": True,
            "userId": self.user_id,
            "env": self.env,
            "expiresAt": self._cert_expires_at.isoformat(),
            "remaining": remaining,
            "message": f"인증 유효 (잔여: {remaining // 60}시간 {remaining % 60}분)",
        }

    def clear_auth(self) -> dict[str, Any]:
        """인증 캐시 초기화."""
        self._cert_key = ""
        self._cert_expires_at = None
        return {"success": True, "message": "인증 캐시가 초기화되었습니다."}

    # ------------------------------------------------------------------
    # 기초정보 조회
    # ------------------------------------------------------------------

    async def search_brands(self, brand_name: str = "") -> dict[str, Any]:
        """브랜드 목록 조회."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "searchBrandListOpenApi.lotte",
            "GET",
            {"subscriptionId": cert_key, "brnd_nm": brand_name},
        )

    async def search_categories(
        self, disp_tp_cd: str = "", md_gsgr_no: str = ""
    ) -> dict[str, Any]:
        """전시카테고리 목록 조회."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "searchDispCatListOpenApi.lotte",
            "GET",
            {
                "subscriptionId": cert_key,
                "disp_tp_cd": disp_tp_cd,
                "md_gsgr_no": md_gsgr_no,
            },
        )

    async def search_md_list(self, md_nm: str = "", md_id: str = "") -> dict[str, Any]:
        """매입담당자(MD) 목록 조회."""
        cert_key = await self._ensure_auth()
        params: dict[str, Any] = {"subscriptionId": cert_key}
        if md_nm:
            params["md_nm"] = md_nm
        if md_id:
            params["md_id"] = md_id
        return await self._call_api(
            "searchMDListOpenApi.lotte",
            "GET",
            params,
        )

    async def search_md_groups(self, md_id: str = "") -> dict[str, Any]:
        """MD관리상품군 조회. md_id 필수."""
        cert_key = await self._ensure_auth()
        if not md_id:
            # md_id 미지정 시 자동으로 첫 번째 MD 코드 조회
            md_result = await self.search_md_list()
            md_data = md_result.get("data", {})
            md_list = md_data.get("Result", md_data)
            # MDInfoList > MDInfo에서 첫 번째 MDCode 추출
            info_list = md_list.get("MDInfoList", {}) if isinstance(md_list, dict) else {}
            md_info = info_list.get("MDInfo", {}) if isinstance(info_list, dict) else {}
            if isinstance(md_info, list) and md_info:
                md_id = md_info[0].get("MDCode", "")
            elif isinstance(md_info, dict):
                md_id = md_info.get("MDCode", "")
            if not md_id:
                return {"success": False, "message": "배정된 MD가 없습니다"}
            logger.info(f"[롯데홈쇼핑] MD코드 자동 조회: {md_id}")
        return await self._call_api(
            "searchMDGsgrListOpenApi.lotte",
            "GET",
            {"subscriptionId": cert_key, "md_id": md_id},
        )

    async def search_delivery_policies(self) -> dict[str, Any]:
        """배송비정책 목록 조회.
        수정: searchDlvPolcListOpenApi → searchDlvPolcInfoListOpenApi (롯데홈쇼핑 담당자 확인)
        """
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "searchDlvPolcInfoListOpenApi.lotte",
            "GET",
            {"subscriptionId": cert_key},
        )

    async def register_delivery_policy(
        self, policy_data: dict[str, Any]
    ) -> dict[str, Any]:
        """배송비정책 등록."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "registApiDlvPolcInfo.lotte",
            "POST",
            {"subscriptionId": cert_key, **policy_data},
        )

    async def search_return_places(self) -> dict[str, Any]:
        """출고지/반품배송지 목록 조회.
        수정: searchDlvPlcListOpenApi → searchReturnListOpenApi (롯데홈쇼핑 담당자 확인)
        """
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "searchReturnListOpenApi.lotte",
            "GET",
            {"subscriptionId": cert_key},
        )

    async def register_delivery_place(
        self, place_data: dict[str, Any]
    ) -> dict[str, Any]:
        """출고지/반품배송지 등록. (권한 부여 완료: 037800LT)"""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "registDlvpOpenApi.lotte",
            "POST",
            {"subscriptionId": cert_key, **place_data},
        )

    async def search_goods_article_codes(
        self, artc_cd: str = ""
    ) -> dict[str, Any]:
        """품목별 항목코드정보 조회.
        수정: searchGoodsArtcOpenApi → searchGoodsArtcItemCdListOpenApi (롯데홈쇼핑 담당자 확인)
        """
        cert_key = await self._ensure_auth()
        params: dict[str, Any] = {"subscriptionId": cert_key}
        if artc_cd:
            params["artc_cd"] = artc_cd
        return await self._call_api(
            "searchGoodsArtcItemCdListOpenApi.lotte",
            "GET",
            params,
        )

    # ------------------------------------------------------------------
    # 상품 CRUD
    # ------------------------------------------------------------------

    async def register_goods(self, goods_data: dict[str, Any]) -> dict[str, Any]:
        """신규상품등록."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "registApiGoodsInfo.lotte",
            "POST",
            {"subscriptionId": cert_key, **goods_data},
        )

    async def update_new_goods(
        self, goods_req_no: str, goods_data: dict[str, Any]
    ) -> dict[str, Any]:
        """신규상품수정 (승인 전)."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "upateApiNewGoodsInfo.lotte",
            "POST",
            {"subscriptionId": cert_key, "goods_req_no": goods_req_no, **goods_data},
        )

    async def update_display_goods(
        self, goods_no: str, goods_data: dict[str, Any]
    ) -> dict[str, Any]:
        """전시상품수정 (승인 후)."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "upateApiDisplayGoodsInfo.lotte",
            "POST",
            {"subscriptionId": cert_key, "goods_no": goods_no, **goods_data},
        )

    async def update_sale_status(
        self, goods_no: str, sale_stat_cd: str = "20"
    ) -> dict[str, Any]:
        """판매상태 변경. sale_stat_cd: 10=판매진행, 20=품절, 30=영구중단."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "updateGoodsSaleStat.lotte",
            "POST",
            {
                "subscriptionId": cert_key,
                "goods_no": goods_no,
                "sale_stat_cd": sale_stat_cd,
            },
        )

    # ------------------------------------------------------------------
    # 재고
    # ------------------------------------------------------------------

    async def update_stock(
        self, goods_no: str, item_no: str, inv_qty: int
    ) -> dict[str, Any]:
        """재고수정."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "registStock.lotte",
            "POST",
            {
                "subscriptionId": cert_key,
                "goods_no": goods_no,
                "item_no": item_no,
                "inv_qty": inv_qty,
            },
        )

    async def search_stock(self, goods_no: str = "") -> dict[str, Any]:
        """재고 목록 조회."""
        cert_key = await self._ensure_auth()
        return await self._call_api(
            "searchStockList.lotte",
            "GET",
            {"subscriptionId": cert_key, "goods_no": goods_no},
        )


class LotteApiError(Exception):
    """롯데홈쇼핑 API 오류."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.lotte_msg = message
        super().__init__(f"[{code}] {message}")

"""GS샵 제휴 API V3 클라이언트 - httpx 기반.

proxy-server.mjs의 GS샵 관련 로직을 Python으로 포팅.
AES256-CBC 토큰 생성, 상품 등록/수정, 기초정보 조회, 프로모션 등을 지원한다.

인증 방식:
- supCd (헤더): 협력사코드
- token (헤더): AES256_CBC(yyyyMMddHHmmss + supCd, aesKey) → Base64
- IV: key 앞 16글자 UTF-8
- key: UTF-8 인코딩 후 32바이트 (부족하면 0패딩, 초과하면 자름)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from backend.utils.logger import logger


class GsShopClient:
    """GS샵 제휴 API V3 클라이언트."""

    TEST_BASE = "https://atwithgs-api.gsshop.com"
    PROD_BASE = "https://withgs-api.gsshop.com"

    def __init__(
        self,
        sup_cd: str,
        aes_key: str,
        sub_sup_cd: str = "",
        env: str = "dev",
    ) -> None:
        self.sup_cd = sup_cd
        self.aes_key = aes_key
        self.sub_sup_cd = sub_sup_cd
        self.env = env

    @property
    def base_url(self) -> str:
        return self.PROD_BASE if self.env == "prod" else self.TEST_BASE

    # ------------------------------------------------------------------
    # AES256 Token generation
    # ------------------------------------------------------------------

    def _generate_token(self) -> str:
        """GSSHOP V3 인증 토큰 생성.

        proxy-server.mjs ``generateGsToken()`` 포팅.
        token = AES256_CBC(yyyyMMddHHmmss + supCd, aesKey) → Base64
        """
        now = datetime.now(tz=timezone.utc)
        sysdate = now.strftime("%Y%m%d%H%M%S")
        plain_text = sysdate + self.sup_cd

        # key: UTF-8 인코딩 후 32바이트 맞춤
        key_bytes = self.aes_key.encode("utf-8")
        key_buf = bytearray(32)
        key_buf[: min(len(key_bytes), 32)] = key_bytes[: min(len(key_bytes), 32)]
        key_buf = bytes(key_buf)

        # IV: key 앞 16글자 UTF-8
        iv = self.aes_key[:16].encode("utf-8")

        # AES-256-CBC with PKCS7 padding
        padder = PKCS7(128).padder()
        padded_data = padder.update(plain_text.encode("utf-8")) + padder.finalize()

        cipher = Cipher(algorithms.AES(key_buf), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded_data) + encryptor.finalize()

        import base64

        return base64.b64encode(encrypted).decode("ascii")

    # ------------------------------------------------------------------
    # Low-level API caller
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        path: str,
        method: str = "GET",
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """GS샵 V3 API 공통 호출.

        proxy-server.mjs ``callGsApi()`` 포팅.
        """
        token = self._generate_token()
        url = self.base_url + path
        if params:
            qs = urlencode({k: v for k, v in params.items() if v})
            if qs:
                url = f"{url}?{qs}"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "supCd": self.sup_cd,
            "token": token,
        }

        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                resp = await client.post(
                    url,
                    headers=headers,
                    json=body if body else {},
                )
            elif method == "PUT":
                resp = await client.put(
                    url,
                    headers=headers,
                    json=body if body else {},
                )
            else:
                raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

            text = resp.text
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"raw": text}

            logger.info(
                f"[GS샵V3] {method} {path} -> {resp.status_code} "
                f"{data.get('resultCode', '')}"
            )

            if not resp.is_success:
                raise GsShopApiError(
                    code=resp.status_code,
                    message=(
                        data.get("message")
                        or data.get("msg")
                        or text[:120]
                    ),
                    data=data,
                )

            return {"success": True, "data": data, "status": resp.status_code}

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def check_auth(self) -> dict[str, Any]:
        """인증 확인 (MDID 조회로 검증) - proxy-server.mjs /api/gsshop/auth/check 포팅."""
        if not self.sup_cd or not self.aes_key:
            return {
                "success": False,
                "authenticated": False,
                "message": "supCd와 aesKey가 필요합니다.",
            }
        try:
            result = await self._call_api(
                "/api/v3/products/getSupMdidList.gs", "GET"
            )
            env_label = "운영" if self.env == "prod" else "테스트"
            return {
                "success": True,
                "authenticated": True,
                "env": self.env,
                "message": f"인증 성공 ({env_label})",
                "data": result.get("data"),
            }
        except GsShopApiError as exc:
            return {
                "success": False,
                "authenticated": False,
                "message": str(exc),
                "code": exc.code,
            }

    # ------------------------------------------------------------------
    # 기초정보 조회
    # ------------------------------------------------------------------

    async def get_brands(
        self,
        brand_nm: Optional[str] = None,
        from_dtm: Optional[str] = None,
        to_dtm: Optional[str] = None,
    ) -> dict[str, Any]:
        """브랜드 조회.

        brand_nm이 주어지면 이름 검색, 아니면 변경분 배치 조회.
        """
        if brand_nm is not None:
            return await self._call_api(
                "/api/v3/products/getPrdBrandList",
                "GET",
                params={"brandNm": brand_nm},
            )
        params: dict[str, str] = {}
        if from_dtm:
            params["fromDtm"] = from_dtm
        if to_dtm:
            params["toDtm"] = to_dtm
        return await self._call_api(
            "/SupSendBrandInfo.gs", "GET", params=params
        )

    async def get_categories(
        self, sect_sts: str = "A", shop_attr_cd: str = ""
    ) -> dict[str, Any]:
        """전시매장(GS 카테고리) 조회."""
        params: dict[str, str] = {}
        if sect_sts:
            params["sectSts"] = sect_sts
        if shop_attr_cd:
            params["shopAttrCd"] = shop_attr_cd
        return await self._call_api(
            "/api/v3/products/getAllSectList", "GET", params=params
        )

    async def get_product_categories(self) -> dict[str, Any]:
        """상품분류코드 전체 조회 (1일 1회 배치용)."""
        return await self._call_api("/SupSendPrdClsInfo.gs", "GET")

    async def get_delivery_places(
        self,
        sup_addr_cd: str = "",
        addr_gbn_nm: str = "",
        dirdlv_relsp_yn: str = "",
        dirdlv_retp_yn: str = "",
    ) -> dict[str, Any]:
        """출고지/반송지 전체 조회."""
        params: dict[str, str] = {}
        if sup_addr_cd:
            params["supAddrCd"] = sup_addr_cd
        if addr_gbn_nm:
            params["addrGbnNm"] = addr_gbn_nm
        if dirdlv_relsp_yn:
            params["dirdlvRelspYn"] = dirdlv_relsp_yn
        if dirdlv_retp_yn:
            params["dirdlvRetpYn"] = dirdlv_retp_yn
        return await self._call_api(
            "/api/v3/products/getSupAddrList.gs", "GET", params=params
        )

    async def register_delivery_place(
        self, addr_data: dict[str, Any]
    ) -> dict[str, Any]:
        """출고지/반송지 등록."""
        return await self._call_api(
            "/api/v3/supAddrReg.gs", "POST", body=addr_data
        )

    async def update_delivery_place(
        self, addr_data: dict[str, Any]
    ) -> dict[str, Any]:
        """출고지/반송지 수정."""
        return await self._call_api(
            "/api/v3/supAddrMod.gs", "POST", body=addr_data
        )

    async def get_md_list(
        self,
        sub_sup_check_yn: str = "N",
        sub_sup_cd: str = "",
        prc_mod_auth_yn: str = "A",
        prd_nm_mod_auth_yn: str = "A",
        descd_mod_auth_yn: str = "A",
    ) -> dict[str, Any]:
        """협력사 MDID 조회 (V1.0.1)."""
        params: dict[str, str] = {
            "prcModAuthYn": prc_mod_auth_yn,
            "prdNmModAuthYn": prd_nm_mod_auth_yn,
            "descdModAuthYn": descd_mod_auth_yn,
            "subSupCheckYn": sub_sup_check_yn,
        }
        if sub_sup_cd:
            params["subSupCd"] = sub_sup_cd
        return await self._call_api(
            "/api/v3/products/getSupMdidList.gs", "GET", params=params
        )

    # ------------------------------------------------------------------
    # 상품 등록/수정
    # ------------------------------------------------------------------

    async def register_goods(self, product_data: dict[str, Any]) -> dict[str, Any]:
        """상품 등록."""
        return await self._call_api(
            "/api/v3/products", "POST", body=product_data
        )

    async def update_goods_base_info(
        self, sup_prd_cd: str, body_data: dict[str, Any]
    ) -> dict[str, Any]:
        """기본부가정보 수정."""
        return await self._call_api(
            f"/api/v3/products/{sup_prd_cd}/base-info", "POST", body=body_data
        )

    async def update_goods_price(
        self,
        sup_prd_cd: str,
        prd_prc_info: dict[str, Any],
    ) -> dict[str, Any]:
        """가격 수정."""
        return await self._call_api(
            f"/api/v3/products/{sup_prd_cd}/price",
            "POST",
            body={"subSupCd": self.sub_sup_cd, "prdPrcInfo": prd_prc_info},
        )

    async def update_sale_status(
        self,
        sup_prd_cd: str,
        sale_end_dtm: str,
        attr_sale_end_st_mod_yn: str = "Y",
    ) -> dict[str, Any]:
        """판매상태 변경."""
        return await self._call_api(
            f"/api/v3/products/{sup_prd_cd}/sale-status",
            "POST",
            body={
                "saleEndDtm": sale_end_dtm,
                "attrSaleEndStModYn": attr_sale_end_st_mod_yn,
            },
        )

    async def update_images(
        self,
        sup_prd_cd: str,
        prd_content_list_url: str = "",
        mobile_banner_img_url: str = "",
    ) -> dict[str, Any]:
        """이미지 수정."""
        return await self._call_api(
            f"/api/v3/products/{sup_prd_cd}/images",
            "POST",
            body={
                "prdCntntListCntntUrlNm": prd_content_list_url,
                "mobilBannerImgUrl": mobile_banner_img_url,
            },
        )

    async def update_attributes(
        self,
        sup_prd_cd: str,
        attr_prd_list: list[dict[str, Any]],
        prd_typ_cd: str = "",
        sub_sup_cd: str = "",
    ) -> dict[str, Any]:
        """속성(옵션) 수정."""
        return await self._call_api(
            f"/api/v3/products/{sup_prd_cd}/attributes",
            "POST",
            body={
                "prdTypCd": prd_typ_cd,
                "subSupCd": sub_sup_cd or self.sub_sup_cd,
                "attrPrdList": attr_prd_list,
            },
        )

    async def get_goods(
        self, sup_prd_cd: str, search_itm_cd: str = "ALL"
    ) -> dict[str, Any]:
        """상품 상세 조회 (MD승인 완료 상품만)."""
        return await self._call_api(
            "/api/v3/getPrdInfo.gs",
            "GET",
            params={
                "supCd": self.sup_cd,
                "supPrdCd": sup_prd_cd,
                "searchItmCd": search_itm_cd,
            },
        )

    async def get_approve_status(self, sup_prd_cd: str) -> dict[str, Any]:
        """상품 승인상태 조회.

        prdStCd: R=승인요청, F=반려, N=대기, Y=판매중, E=종료, T=품절, D=완전종료
        """
        return await self._call_api(
            "/api/v3/getPrdAprvInfo.gs",
            "GET",
            params={"supCd": self.sup_cd, "supPrdCd": sup_prd_cd},
        )

    # ------------------------------------------------------------------
    # 프로모션
    # ------------------------------------------------------------------

    async def get_promotions(
        self,
        from_dtm: str,
        to_dtm: str,
        pmo_apply_st: str = "ALL",
        prd_cd: str = "",
        prd_nm: str = "",
        brand_cd: str = "",
        rows_per_page: int = 100,
        page_idx: int = 1,
    ) -> dict[str, Any]:
        """프로모션 목록 조회."""
        params: dict[str, str] = {
            "fromDtm": from_dtm,
            "toDtm": to_dtm,
            "pmoApplySt": pmo_apply_st,
            "rowsPerPage": str(rows_per_page),
            "pageIdx": str(page_idx),
        }
        if prd_cd:
            params["prdCd"] = prd_cd
        if prd_nm:
            params["prdNm"] = prd_nm
        if brand_cd:
            params["brandCd"] = brand_cd
        return await self._call_api(
            "/api/v3/getPromotionList.gs", "GET", params=params
        )

    async def approve_promotion(
        self,
        salepro_agree_doc_no: str,
        pmo_req_no: str,
        prd_cd: str,
        aprv_st_cd: str,
        aprv_ret_rsn: str = "",
    ) -> dict[str, Any]:
        """프로모션 승인/반려 처리. aprv_st_cd: 30=승인, 40=반려."""
        body: dict[str, Any] = {
            "saleproAgreeDocNo": salepro_agree_doc_no,
            "pmoReqNo": pmo_req_no,
            "prdCd": prd_cd,
            "aprvStCd": aprv_st_cd,
        }
        if aprv_ret_rsn:
            body["aprvRetRsn"] = aprv_ret_rsn
        return await self._call_api(
            "/api/v3/modifyPromotionStatus.gs", "POST", body=body
        )


class GsShopApiError(Exception):
    """GS샵 API 오류."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.gs_data = data or {}
        super().__init__(f"[{code}] {message}")

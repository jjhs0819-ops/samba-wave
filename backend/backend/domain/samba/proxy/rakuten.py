"""라쿠텐 RMS API 클라이언트 - 상품 등록/수정.

인증 방식: ESA (Encoded Service Authentication)
- Authorization: ESA {Base64(serviceSecret:licenseKey)}
- RMS 2.0 JSON API 우선, 실패 시 1.0 XML 폴백
"""

from __future__ import annotations

import base64
import re
from typing import Any, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx

from backend.utils.logger import logger


class RakutenClient:
    """라쿠텐 RMS API 클라이언트."""

    BASE_URL = "https://api.rms.rakuten.co.jp"

    def __init__(
        self,
        service_secret: str,
        license_key: str,
    ) -> None:
        self.service_secret = service_secret
        self.license_key = license_key

    # ------------------------------------------------------------------
    # ESA 인증 헤더 생성
    # ------------------------------------------------------------------

    def _auth_header(self) -> str:
        """ESA 방식 인증 헤더 값 생성.

        serviceSecret:licenseKey 를 Base64 인코딩하여 반환.
        """
        raw = f"{self.service_secret}:{self.license_key}"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        return f"ESA {encoded}"

    # ------------------------------------------------------------------
    # 공통 API 호출
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any] | str] = None,
        content_type: str = "application/json",
        params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """공통 API 호출.

        JSON 또는 XML body 모두 지원.
        """
        url = f"{self.BASE_URL}{path}"
        headers = {
            "Authorization": self._auth_header(),
            "Content-Type": f"{content_type}; charset=utf-8",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                if isinstance(body, str):
                    # XML 문자열 전송
                    resp = await client.post(
                        url, headers=headers, content=body.encode("utf-8")
                    )
                else:
                    resp = await client.post(url, headers=headers, json=body or {})
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=body or {})
            elif method == "PATCH":
                resp = await client.patch(url, headers=headers, json=body or {})
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")

            # 응답 파싱
            try:
                data = resp.json()
            except Exception:
                data = {"raw": resp.text}

            logger.info(f"[라쿠텐] {method} {path} → {resp.status_code}")

            if not resp.is_success:
                msg = ""
                if isinstance(data, dict):
                    # RMS 2.0 에러 구조
                    errors = data.get("errors", [])
                    if errors:
                        msg = "; ".join(
                            e.get("message", "") or e.get("code", "") for e in errors
                        )
                    else:
                        msg = data.get("message", "") or data.get("error", "")
                if not msg:
                    msg = resp.text[:300]
                raise RakutenApiError(f"HTTP {resp.status_code}: {msg}")

            return data

    # ------------------------------------------------------------------
    # 상품 데이터 변환
    # ------------------------------------------------------------------

    @staticmethod
    def transform_product(
        product: dict[str, Any],
        category_id: str = "",
        account_settings: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """SambaCollectedProduct → 라쿠텐 RMS 2.0 상품 등록 데이터 변환.

        라쿠텐 RMS Item API 2.0 (JSON) 형식 기준.
        """
        # 관리번호: 영숫자+하이픈만 허용 (최대 32자)
        product_id = str(product.get("id", "") or product.get("site_product_id", ""))
        item_url = re.sub(r"[^a-zA-Z0-9\-]", "", product_id)[:32]
        if not item_url:
            # ID가 없거나 영숫자가 아닌 경우 해시 기반 생성
            import hashlib

            item_url = hashlib.md5(
                str(product.get("name", "")).encode("utf-8")
            ).hexdigest()[:16]

        # 이미지 처리 (최대 20장, RMS 2.0 기준)
        images_raw = product.get("images") or []
        images: dict[str, Any] = {}
        for idx, url in enumerate(images_raw[:20], start=1):
            images[f"imageUrl{idx}"] = url

        # 상세 설명 HTML
        detail_html = (
            product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>"
        )

        # 판매가격 (엔화 변환은 정책 레이어에서 처리)
        sale_price = int(product.get("sale_price", 0))

        # 장르 ID (라쿠텐 카테고리)
        genre_id = int(category_id) if category_id and str(category_id).isdigit() else 0

        # 재고 수량
        options = product.get("options") or []
        total_stock = sum(opt.get("stock", 0) for opt in options) if options else 999

        payload: dict[str, Any] = {
            "itemUrl": item_url,
            "itemName": (product.get("name", "") or "")[:255],
            "itemPrice": sale_price,
            "genreId": genre_id,
            "catalogIdExemptionReason": 5,  # 해당없음
            "itemDescription": detail_html,
            "images": images,
            "itemInventory": {
                "inventoryType": 1 if not options else 2,  # 1=통합재고, 2=옵션별
                "inventories": [],
            },
        }

        # 옵션/재고 설정
        if options:
            for opt in options:
                opt_name = opt.get("name", "") or opt.get("size", "") or "기본"
                opt_stock = opt.get("stock", 999)
                payload["itemInventory"]["inventories"].append(
                    {
                        "inventoryCount": opt_stock,
                        "optionName": opt_name,
                        "isRestDisplayFlag": True,
                        "normalDeliveryDateId": 1000,
                    }
                )
        else:
            payload["itemInventory"]["inventories"].append(
                {
                    "inventoryCount": total_stock,
                    "isRestDisplayFlag": True,
                    "normalDeliveryDateId": 1000,
                }
            )

        # 계정별 추가 설정 반영
        if account_settings:
            if account_settings.get("shipping_group_id"):
                payload["shippingGroupId"] = account_settings["shipping_group_id"]
            if account_settings.get("tax_rate"):
                payload["taxRate"] = account_settings["tax_rate"]

        return payload

    # ------------------------------------------------------------------
    # XML 폴백용 변환
    # ------------------------------------------------------------------

    @staticmethod
    def _to_xml_body(payload: dict[str, Any]) -> str:
        """RMS 1.0 XML 형식으로 변환 (폴백용).

        item/insert API는 XML 형식만 지원.
        """
        root = Element("request")
        item_insert = SubElement(root, "itemInsertRequest")
        item_el = SubElement(item_insert, "item")

        # 기본 필드 매핑
        field_map = {
            "itemUrl": "itemUrl",
            "itemName": "itemName",
            "itemPrice": "itemPrice",
            "genreId": "genreId",
            "catalogIdExemptionReason": "catalogIdExemptionReason",
            "itemDescription": "itemDescription",
        }
        for json_key, xml_key in field_map.items():
            if json_key in payload:
                el = SubElement(item_el, xml_key)
                el.text = str(payload[json_key])

        # 이미지
        images = payload.get("images", {})
        if images:
            for img_key, img_url in images.items():
                el = SubElement(item_el, img_key)
                el.text = str(img_url)

        return tostring(root, encoding="unicode", xml_declaration=False)

    # ------------------------------------------------------------------
    # 상품 등록 (JSON 2.0 우선, XML 1.0 폴백)
    # ------------------------------------------------------------------

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        """상품 등록.

        RMS 2.0 JSON API 우선 시도, 실패 시 1.0 XML 폴백.
        """
        manage_number = payload.get("itemUrl", "")
        if not manage_number:
            raise RakutenApiError("itemUrl(관리번호)이 필요합니다")

        # 2.0 JSON API 시도
        try:
            result = await self._call_api(
                "POST",
                f"/es/2.0/items/manage-numbers/{manage_number}",
                body=payload,
                content_type="application/json",
            )
            logger.info(f"[라쿠텐] 상품 등록 성공 (2.0 JSON): {manage_number}")
            return {"success": True, "data": result, "api_version": "2.0"}
        except RakutenApiError as e:
            logger.warning(f"[라쿠텐] 2.0 JSON 등록 실패, XML 폴백 시도: {e}")

        # 1.0 XML 폴백
        xml_body = self._to_xml_body(payload)
        result = await self._call_api(
            "POST",
            "/es/1.0/item/insert",
            body=xml_body,
            content_type="application/xml",
        )
        logger.info(f"[라쿠텐] 상품 등록 성공 (1.0 XML 폴백): {manage_number}")
        return {"success": True, "data": result, "api_version": "1.0"}

    # ------------------------------------------------------------------
    # 상품 수정
    # ------------------------------------------------------------------

    async def update_product(
        self, manage_number: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """상품 수정 (RMS 2.0 PATCH)."""
        result = await self._call_api(
            "PATCH",
            f"/es/2.0/items/manage-numbers/{manage_number}",
            body=payload,
            content_type="application/json",
        )
        logger.info(f"[라쿠텐] 상품 수정 성공: {manage_number}")
        return {"success": True, "data": result}

    # ------------------------------------------------------------------
    # 상품 삭제
    # ------------------------------------------------------------------

    async def delete_product(self, manage_number: str) -> dict[str, Any]:
        """상품 삭제 (RMS 2.0 DELETE)."""
        result = await self._call_api(
            "DELETE",
            f"/es/2.0/items/manage-numbers/{manage_number}",
        )
        logger.info(f"[라쿠텐] 상품 삭제 성공: {manage_number}")
        return {"success": True, "data": result}

    # ------------------------------------------------------------------
    # 상품 조회
    # ------------------------------------------------------------------

    async def get_product(self, manage_number: str) -> dict[str, Any]:
        """상품 조회 (RMS 2.0 GET)."""
        return await self._call_api(
            "GET",
            f"/es/2.0/items/manage-numbers/{manage_number}",
        )


class RakutenApiError(Exception):
    """라쿠텐 API 에러."""

    pass

"""쿠팡 마켓 플러그인.

기존 dispatcher._handle_coupang 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class CoupangPlugin(MarketPlugin):
    market_type = "coupang"
    policy_key = "쿠팡"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """쿠팡은 비숫자 카테고리(경로 문자열)도 허용 — resolve_category_code 로 동적 조회."""
        return category_id

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 쿠팡 API 포맷 변환."""
        from backend.domain.samba.proxy.coupang import CoupangClient

        return CoupangClient.transform_product(
            product,
            category_id,
            return_center_code=kwargs.get("return_center_code", ""),
            outbound_shipping_place_code=kwargs.get("outbound_shipping_place_code", ""),
        )

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """쿠팡 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.coupang import CoupangClient

        access_key = creds.get("accessKey", "")
        secret_key = creds.get("secretKey", "")
        vendor_id = creds.get("vendorId", "")

        # account 필드에서 보완
        if account:
            access_key = access_key or getattr(account, "api_key", "") or ""
            secret_key = secret_key or getattr(account, "api_secret", "") or ""
            vendor_id = vendor_id or getattr(account, "seller_id", "") or ""

        if not access_key or not secret_key:
            return {
                "success": False,
                "message": "쿠팡 Access Key/Secret Key가 없습니다.",
            }

        client = CoupangClient(access_key, secret_key, vendor_id)

        # 카테고리 코드가 숫자가 아니면 쿠팡 API로 동적 조회
        if category_id and not str(category_id).isdigit():
            resolved = await client.resolve_category_code(category_id)
            category_id = str(resolved) if resolved else ""

        # vendorUserId: Wing 로그인 ID (seller_id 사용)
        vendor_user_id = ""
        if account:
            vendor_user_id = getattr(account, "seller_id", "") or ""

        # 반품지 코드 조회 (API에서 동적 획득)
        return_center_code = ""
        rc_content: list = []
        try:
            rc_result = await client._call_api(
                "GET",
                f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/returnShippingCenters",
            )
            rc_data = rc_result.get("data", {})
            rc_content = rc_data.get("content", []) if isinstance(rc_data, dict) else []
            if rc_content:
                rc = rc_content[0]
                return_center_code = rc.get("returnCenterCode", "")
        except Exception:
            pass

        # 출고지 코드 조회
        outbound_code = ""
        try:
            ob_result = await client._call_api(
                "GET",
                "/v2/providers/marketplace_openapi/apis/api/v1/vendor/shipping-place/outbound",
                params={"pageNum": "1", "pageSize": "10"},
            )
            ob_content = (
                ob_result.get("content", []) if isinstance(ob_result, dict) else []
            )
            if ob_content:
                outbound_code = str(ob_content[0].get("outboundShippingPlaceCode", ""))
        except Exception:
            pass

        # AS 전화번호 주입은 base._apply_market_settings 에서 처리됨
        data = CoupangClient.transform_product(
            product,
            category_id,
            return_center_code=return_center_code,
            outbound_shipping_place_code=outbound_code,
        )
        data["vendorId"] = vendor_id
        data["vendorUserId"] = vendor_user_id or vendor_id

        # 반품지 실제 주소 정보 덮어쓰기
        if return_center_code and rc_content:
            addrs = rc_content[0].get("placeAddresses", [])
            if addrs:
                addr = addrs[0]
                data["returnZipCode"] = addr.get("returnZipCode", "")
                data["returnAddress"] = addr.get("returnAddress", "")
                data["returnAddressDetail"] = addr.get("returnAddressDetail", "")
                data["companyContactNumber"] = addr.get("companyContactNumber", "")

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        if existing_no:
            result = await client.update_product(existing_no, data)
            return {
                "success": True,
                "message": "쿠팡 수정 성공",
                "data": {"sellerProductId": existing_no},
            }
        else:
            result = await client.register_product(data)

            # 쿠팡 응답에서 sellerProductId 추출 (data 필드에 숫자로 반환)
            seller_product_id = ""
            if isinstance(result, dict):
                inner = result.get("data", {})
                if isinstance(inner, dict):
                    seller_product_id = str(inner.get("data", ""))
                elif inner:
                    seller_product_id = str(inner)

            return {
                "success": True,
                "message": "쿠팡 등록 성공",
                "data": {"sellerProductId": seller_product_id}
                if seller_product_id
                else result,
            }

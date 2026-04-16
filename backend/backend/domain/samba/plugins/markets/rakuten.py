"""라쿠텐 마켓 플러그인.

기존 dispatcher._handle_rakuten 로직을 플러그인 구조로 추출.
ESA 인증 기반 라쿠텐 RMS API 연동 (JSON 2.0 우선, XML 1.0 폴백).
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class RakutenPlugin(MarketPlugin):
    market_type = "rakuten"
    policy_key = "라쿠텐"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """RakutenClient.transform_product 위임."""
        from backend.domain.samba.proxy.rakuten import RakutenClient

        settings = kwargs.get("account_settings", {})
        return RakutenClient.transform_product(product, category_id, settings)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """라쿠텐 상품 등록/수정."""
        from backend.domain.samba.proxy.rakuten import RakutenClient, RakutenApiError

        # apiKey = serviceSecret, apiSecret = licenseKey
        service_secret = creds.get("apiKey", "")
        license_key = creds.get("apiSecret", "")

        # account 객체에서 폴백
        if account:
            if not service_secret:
                service_secret = getattr(account, "api_key", "") or ""
            if not license_key:
                license_key = getattr(account, "api_secret", "") or ""

        if not service_secret or not license_key:
            return {
                "success": False,
                "message": "라쿠텐 serviceSecret/licenseKey가 없습니다.",
                "error_type": "auth_failed",
            }

        client = RakutenClient(service_secret, license_key)
        settings = (account.additional_fields or {}) if account else {}
        payload = RakutenClient.transform_product(product, category_id, settings)
        manage_number = payload.get("itemUrl") or product.get("id") or ""

        try:
            if existing_no:
                result = await client.update_product(existing_no, payload)
            else:
                result = await client.register_product(payload, manage_number)
            return {"success": True, "product_no": manage_number, "data": result}
        except Exception as e:
            logger.error(
                f"[라쿠텐] {'등록 실패' if isinstance(e, RakutenApiError) else '예외'}: {e}"
            )
            return {
                "success": False,
                "message": str(e),
                "error_type": self._classify_error(e),
            }

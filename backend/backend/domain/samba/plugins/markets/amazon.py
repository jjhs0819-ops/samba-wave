"""아마존 마켓 플러그인.

기존 dispatcher._handle_amazon 로직을 플러그인 구조로 추출.
LWA OAuth 기반 아마존 SP-API Listings 연동.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class AmazonPlugin(MarketPlugin):
  market_type = "amazon"
  policy_key = "아마존"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """AmazonClient.transform_product 위임."""
    from backend.domain.samba.proxy.amazon import AmazonClient

    settings = kwargs.get("account_settings", {})
    return AmazonClient.transform_product(product, category_id, settings)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """아마존 상품 등록/수정."""
    from backend.domain.samba.proxy.amazon import AmazonClient, AmazonApiError

    # account 객체에서 인증 정보 추출
    refresh_token = creds.get("accessToken", "")
    client_id = creds.get("clientId", "")
    client_secret = creds.get("clientSecret", "")
    seller_id = creds.get("storeId", "")
    region = creds.get("region", "fe")

    # account 객체에서 폴백
    if account:
      if not refresh_token:
        refresh_token = getattr(account, "api_key", "") or ""
      if not client_secret:
        client_secret = getattr(account, "api_secret", "") or ""
      if not seller_id:
        seller_id = getattr(account, "seller_id", "") or ""

    if not refresh_token or not client_id or not client_secret:
      return {"success": False, "message": "아마존 Refresh Token/Client ID/Secret이 없습니다.", "error_type": "auth_failed"}

    client = AmazonClient(refresh_token, client_id, client_secret, seller_id, region)
    settings = (account.additional_fields or {}) if account else {}
    payload = AmazonClient.transform_product(product, category_id, settings)
    sku = product.get("site_product_id") or product.get("id") or ""

    try:
      if existing_no:
        result = await client.update_product(existing_no, payload)
      else:
        result = await client.register_product(payload, sku)
      return {"success": True, "data": result, "productNo": sku}
    except Exception as e:
      logger.error(f"[아마존] {'등록 실패' if isinstance(e, AmazonApiError) else '예외'}: {e}")
      return {"success": False, "message": str(e), "error_type": self._classify_error(e)}

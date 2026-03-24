"""토스 마켓 플러그인.

기존 dispatcher._handle_toss 로직을 플러그인 구조로 추출.
HMAC-SHA256 인증 기반 토스 커머스 API 연동.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class TossPlugin(MarketPlugin):
  market_type = "toss"
  policy_key = "토스"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """TossClient.transform_product 위임."""
    from backend.domain.samba.proxy.toss import TossClient

    settings = kwargs.get("account_settings", {})
    return TossClient.transform_product(product, category_id, settings)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """토스 상품 등록/수정."""
    from backend.domain.samba.proxy.toss import TossClient, TossApiError

    access_key = creds.get("apiKey", "")
    secret_key = creds.get("apiSecret", "")

    # account 객체에서 폴백
    if account:
      if not access_key:
        access_key = getattr(account, "api_key", "") or ""
      if not secret_key:
        secret_key = getattr(account, "api_secret", "") or ""

    if not access_key or not secret_key:
      return {"success": False, "message": "토스 API Key/Secret이 없습니다.", "error_type": "auth_failed"}

    client = TossClient(access_key, secret_key)
    settings = (account.additional_fields or {}) if account else {}
    payload = TossClient.transform_product(product, category_id, settings)

    try:
      if existing_no:
        result = await client.update_product(existing_no, payload)
      else:
        result = await client.register_product(payload)
      product_no = str(result.get("productId") or result.get("productNo") or result.get("id") or "")
      return {"success": True, "data": result, "productNo": product_no}
    except TossApiError as e:
      logger.error(f"[토스] 등록 실패: {e}")
      return {"success": False, "message": str(e), "error_type": "schema_changed"}
    except httpx.TimeoutException:
      return {"success": False, "message": "토스 API 타임아웃", "error_type": "network"}
    except Exception as e:
      logger.error(f"[토스] 예외: {e}")
      return {"success": False, "message": str(e), "error_type": "unknown"}

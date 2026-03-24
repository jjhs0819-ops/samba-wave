"""바이마(BUYMA) 마켓 플러그인.

기존 dispatcher._handle_buyma 로직을 플러그인 구조로 추출.
바이마는 공개 API가 없으므로 CSV 생성 방식으로 운영.
인증 불필요 — _load_auth 오버라이드.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class BuymaPlugin(MarketPlugin):
  market_type = "buyma"
  policy_key = "바이마"
  required_fields = ["name", "sale_price"]

  async def _load_auth(self, session, account) -> dict | None:
    """바이마는 인증 불필요 — 항상 빈 dict 반환.

    CSV 생성 방식이므로 API 인증이 없다.
    account의 additional_fields를 settings로 전달.
    """
    settings: dict[str, Any] = {}
    if account:
      extras = account.additional_fields or {}
      if extras.get("storeId"):
        settings["storeId"] = extras["storeId"]
      # 바이마 계정별 설정 (구매지, 발송지 등)
      for key in ("buyingCountry", "shippingCountry", "deliveryMethod", "deliveryDays"):
        if extras.get(key):
          settings[key] = extras[key]
    # 빈 dict라도 반환 (None이면 base에서 인증 실패 처리)
    return settings if settings else {"_no_auth": True}

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """BuymaClient.transform_product 위임."""
    from backend.domain.samba.proxy.buyma import BuymaClient

    settings = kwargs.get("account_settings", {})
    return BuymaClient.transform_product(product, category_id, settings)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """바이마 상품 등록 — CSV 행 데이터 반환 (API 없음)."""
    from backend.domain.samba.proxy.buyma import BuymaClient

    settings = creds if creds and "_no_auth" not in creds else {}
    client = BuymaClient(seller_id=settings.get("storeId", ""))

    try:
      result = await client.register_product(product, category_id)
      return {
        "success": True,
        "data": result,
        "productNo": product.get("id") or "",
        "message": result.get("message", ""),
      }
    except Exception as e:
      logger.error(f"[바이마] CSV 생성 실패: {e}")
      return {"success": False, "message": str(e), "error_type": "unknown"}

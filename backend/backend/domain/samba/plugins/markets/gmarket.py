"""지마켓 마켓 플러그인 (스텁)."""

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class GMarketMarketPlugin(MarketPlugin):
  """지마켓 판매처 플러그인."""

  market_type = "gmarket"
  policy_key = "지마켓"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    return {}

  async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
    return {"success": False, "message": "지마켓 판매처 API 연동이 아직 구현되지 않았습니다."}

"""옥션 마켓 플러그인 (스텁)."""

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class AuctionPlugin(MarketPlugin):
  """옥션 마켓 플러그인."""

  market_type = "auction"
  policy_key = "옥션"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    return {}

  async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
    return {"success": False, "message": "옥션 API 연동이 아직 구현되지 않았습니다."}

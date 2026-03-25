"""플레이오토 마켓 플러그인 (스텁)."""

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class PlayAutoPlugin(MarketPlugin):
    """플레이오토 마켓 플러그인.

    솔루션 연동형 — 플레이오토 API를 통해 다수 마켓에 일괄 등록.
    """

    market_type = "playauto"
    policy_key = "플레이오토"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "플레이오토 API 연동이 아직 구현되지 않았습니다."}

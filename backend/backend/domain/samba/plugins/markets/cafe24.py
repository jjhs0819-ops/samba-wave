"""카페24 마켓 플러그인 (스텁)."""

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class Cafe24Plugin(MarketPlugin):
    """카페24 마켓 플러그인.

    자사몰 솔루션 — 카페24 API를 통해 상품 등록/수정/삭제.
    """

    market_type = "cafe24"
    policy_key = "카페24"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "카페24 API 연동이 아직 구현되지 않았습니다."}

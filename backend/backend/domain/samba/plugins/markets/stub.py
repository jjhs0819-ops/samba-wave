"""미구현 마켓 스텁 플러그인."""

from backend.domain.samba.plugins.market_base import MarketPlugin
from typing import Any


class EbayPlugin(MarketPlugin):
    market_type = "ebay"
    policy_key = "eBay"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "eBay API 연동이 아직 구현되지 않았습니다."}


class LazadaPlugin(MarketPlugin):
    market_type = "lazada"
    policy_key = "Lazada"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "Lazada API 연동이 아직 구현되지 않았습니다."}


class Qoo10Plugin(MarketPlugin):
    market_type = "qoo10"
    policy_key = "Qoo10"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "Qoo10 API 연동이 아직 구현되지 않았습니다."}


class ShopeePlugin(MarketPlugin):
    market_type = "shopee"
    policy_key = "Shopee"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "Shopee API 연동이 아직 구현되지 않았습니다."}


class ShopifyPlugin(MarketPlugin):
    market_type = "shopify"
    policy_key = "Shopify"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "Shopify API 연동이 아직 구현되지 않았습니다."}


class ZoomPlugin(MarketPlugin):
    market_type = "zoom"
    policy_key = "Zum(줌)"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return {}

    async def execute(self, session, product: dict, creds: dict, category_id: str, account, existing_no: str) -> dict[str, Any]:
        return {"success": False, "message": "Zum(줌) API 연동이 아직 구현되지 않았습니다."}

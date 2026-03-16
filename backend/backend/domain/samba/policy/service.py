"""SambaWave Policy service - 가격정책 + 마진 계산."""

import math
from typing import Any, Dict, List, Optional

from backend.domain.samba.policy.model import SambaPolicy
from backend.domain.samba.policy.repository import SambaPolicyRepository


class SambaPolicyService:
    def __init__(self, repo: SambaPolicyRepository):
        self.repo = repo

    async def list_policies(self, skip: int = 0, limit: int = 50) -> List[SambaPolicy]:
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_policy(self, policy_id: str) -> Optional[SambaPolicy]:
        return await self.repo.get_async(policy_id)

    async def create_policy(self, data: Dict[str, Any]) -> SambaPolicy:
        if "pricing" not in data or data["pricing"] is None:
            data["pricing"] = {
                "shippingCost": 0,
                "marginRate": 15,
                "marginAmount": 0,
                "useRangeMargin": True,
                "rangeMargins": [
                    {"min": 0, "max": 50000, "rate": 15, "amount": None},
                    {"min": 50000, "max": 150000, "rate": 14, "amount": None},
                    {"min": 150000, "max": 9999999999, "rate": 13, "amount": None},
                ],
                "extraCharge": 4000,
                "minMarginAmount": 7000,
                "discountRate": 0,
                "discountAmount": 0,
            }
        return await self.repo.create_async(**data)

    async def update_policy(self, policy_id: str, data: Dict[str, Any]) -> Optional[SambaPolicy]:
        return await self.repo.update_async(policy_id, **data)

    async def delete_policy(self, policy_id: str) -> bool:
        return await self.repo.delete_async(policy_id)

    async def calculate_market_price(
        self, policy_id: str, cost: float, fee_rate: float = 0
    ) -> int:
        policy = await self.repo.get_async(policy_id)
        if not policy or not policy.pricing:
            return math.ceil(cost * 1.15)

        pricing = policy.pricing
        price = cost

        # 국제운송료
        price += pricing.get("shippingCost", 0)

        # 마진 계산
        margin_rate = pricing.get("marginRate", 15)
        if pricing.get("useRangeMargin") and pricing.get("rangeMargins"):
            margin_rate = self._calculate_range_margin(cost, pricing["rangeMargins"])

        if margin_rate > 0:
            price = price / (1 - margin_rate / 100)
        if pricing.get("marginAmount", 0) > 0:
            price += pricing["marginAmount"]

        # 추가 요금
        price += pricing.get("extraCharge", 0)

        # 최소 마진 보장
        profit = price - cost
        min_margin = pricing.get("minMarginAmount", 0)
        if min_margin > 0 and profit < min_margin:
            price = cost + min_margin

        # 마켓 수수료 반영
        if fee_rate > 0:
            price = price / (1 - fee_rate / 100)

        # 할인
        if pricing.get("discountRate", 0) > 0:
            price *= (1 - pricing["discountRate"] / 100)
        if pricing.get("discountAmount", 0) > 0:
            price -= pricing["discountAmount"]

        return math.ceil(price)

    @staticmethod
    def _calculate_range_margin(cost: float, range_margins: List[Dict]) -> float:
        for r in range_margins:
            max_val = r.get("max") or 9999999999
            if cost >= r.get("min", 0) and cost < max_val:
                return r.get("rate", 15)
        return 15

    async def get_price_preview(
        self, policy_id: str, cost: float, fee_rate: float = 0
    ) -> Dict[str, Any]:
        market_price = await self.calculate_market_price(policy_id, cost, fee_rate)
        profit = market_price - cost
        profit_rate = round((profit / market_price) * 100, 1) if market_price > 0 else 0
        return {
            "cost": cost,
            "market_price": market_price,
            "profit": profit,
            "profit_rate": profit_rate,
        }

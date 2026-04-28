"""SambaWave Policy service."""

import math
from typing import Any, Dict, List, Optional

from backend.domain.samba.exchange_rate_service import convert_cost_by_source_site
from backend.domain.samba.policy.model import SambaPolicy
from backend.domain.samba.policy.repository import SambaPolicyRepository


class SambaPolicyService:
    def __init__(self, repo: SambaPolicyRepository):
        self.repo = repo

    async def list_policies(self, skip: int = 0, limit: int = 50) -> List[SambaPolicy]:
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

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

    async def update_policy(
        self, policy_id: str, data: Dict[str, Any]
    ) -> Optional[SambaPolicy]:
        return await self.repo.update_async(policy_id, **data)

    async def delete_policy(self, policy_id: str) -> bool:
        return await self.repo.delete_async(policy_id)

    async def calculate_market_price(
        self,
        policy_id: str,
        cost: float,
        fee_rate: float = 0,
        source_site: str = "",
        tenant_id: str | None = None,
        is_point_restricted: Optional[bool] = None,
    ) -> int:
        policy = await self.repo.get_async(policy_id)
        if not policy or not policy.pricing:
            return math.ceil(cost * 1.15)

        pricing = policy.pricing
        cost_info = await convert_cost_by_source_site(
            self.repo.session, cost, source_site, tenant_id
        )
        effective_cost = cost_info["convertedCost"]
        price = effective_cost

        price += pricing.get("shippingCost", 0)

        margin_rate = pricing.get("marginRate", 15)
        if pricing.get("useRangeMargin") and pricing.get("rangeMargins"):
            margin_rate = self._calculate_range_margin(
                effective_cost, pricing["rangeMargins"]
            )

        if margin_rate > 0:
            price = price / (1 - margin_rate / 100)
        if pricing.get("marginAmount", 0) > 0:
            price += pricing["marginAmount"]

        if source_site:
            site_margin = pricing.get("sourceSiteMargins", {}).get(source_site, {})
            # pointOnly=true일 때는 적립금 사용 가능 상품(is_point_restricted=False)만 추가 마진 적용
            # is_point_restricted=True(불가) 또는 None(미수집)이면 추가 마진 스킵
            point_only = bool(site_margin.get("pointOnly"))
            apply_site_margin = (not point_only) or (is_point_restricted is False)
            if apply_site_margin:
                if site_margin.get("marginRate", 0) > 0:
                    price += effective_cost * site_margin["marginRate"] / 100
                if site_margin.get("marginAmount", 0) > 0:
                    price += site_margin["marginAmount"]

        price += pricing.get("extraCharge", 0)

        profit = price - effective_cost
        min_margin = pricing.get("minMarginAmount", 0)
        if min_margin > 0 and profit < min_margin:
            price = effective_cost + min_margin

        if fee_rate > 0:
            price = price / (1 - fee_rate / 100)

        if pricing.get("discountRate", 0) > 0:
            price *= 1 - pricing["discountRate"] / 100
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
        self,
        policy_id: str,
        cost: float,
        fee_rate: float = 0,
        source_site: str = "",
        tenant_id: str | None = None,
        is_point_restricted: Optional[bool] = None,
    ) -> Dict[str, Any]:
        cost_info = await convert_cost_by_source_site(
            self.repo.session, cost, source_site, tenant_id
        )
        effective_cost = cost_info["convertedCost"]
        market_price = await self.calculate_market_price(
            policy_id,
            cost,
            fee_rate,
            source_site,
            tenant_id,
            is_point_restricted=is_point_restricted,
        )
        profit = market_price - effective_cost
        profit_rate = round((profit / market_price) * 100, 1) if market_price > 0 else 0
        return {
            "cost": cost,
            "effective_cost": effective_cost,
            "currency": cost_info.get("currency"),
            "exchange_applied": cost_info.get("exchangeApplied", False),
            "exchange_rate": cost_info.get("rateApplied"),
            "market_price": market_price,
            "profit": profit,
            "profit_rate": profit_rate,
        }

"""SambaWave Analytics service - cross-domain statistics (ported from js/modules/analytics.js)."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List

from backend.domain.samba.channel.repository import SambaChannelRepository
from backend.domain.samba.order.repository import SambaOrderRepository
from backend.domain.samba.product.repository import SambaProductRepository


class SambaAnalyticsService:
    def __init__(
        self,
        order_repo: SambaOrderRepository,
        product_repo: SambaProductRepository,
        channel_repo: SambaChannelRepository,
    ):
        self.order_repo = order_repo
        self.product_repo = product_repo
        self.channel_repo = channel_repo

    # ==================== Today ====================

    async def get_today_stats(self) -> Dict[str, Any]:
        """오늘 기준 매출/주문/수익 통계."""
        now = datetime.now(UTC)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._compute_stats_for_period(start_of_day, now)

    # ==================== Date Range ====================

    async def get_stats_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """기간별 매출/주문/수익 통계."""
        return await self._compute_stats_for_period(start_date, end_date)

    # ==================== By Channel ====================

    async def get_sales_by_channel(self) -> List[Dict[str, Any]]:
        """채널별 매출 통계."""
        all_orders = await self.order_repo.list_async()
        all_channels = await self.channel_repo.list_async()

        channel_map: Dict[str, str] = {ch.id: ch.name for ch in all_channels}

        agg: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"sales": 0.0, "orders": 0, "profit": 0.0}
        )

        for order in all_orders:
            ch_id = order.channel_id or "unknown"
            ch_name = channel_map.get(ch_id, order.channel_name or "기타")
            key = ch_id

            agg[key]["channel_name"] = ch_name
            agg[key]["sales"] += order.sale_price * order.quantity
            agg[key]["orders"] += 1
            agg[key]["profit"] += order.profit

        result = list(agg.values())
        result.sort(key=lambda x: x["sales"], reverse=True)
        return result

    # ==================== By Product ====================

    async def get_sales_by_product(self) -> List[Dict[str, Any]]:
        """상품별 매출 통계."""
        all_orders = await self.order_repo.list_async()

        agg: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"sales": 0.0, "orders": 0, "profit": 0.0, "units": 0}
        )

        for order in all_orders:
            p_id = order.product_id or "unknown"
            p_name = order.product_name or "기타"

            agg[p_id]["product_name"] = p_name
            agg[p_id]["sales"] += order.sale_price * order.quantity
            agg[p_id]["orders"] += 1
            agg[p_id]["profit"] += order.profit
            agg[p_id]["units"] += order.quantity

        result = list(agg.values())
        result.sort(key=lambda x: x["sales"], reverse=True)
        return result

    # ==================== Daily Trend ====================

    async def get_daily_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """일별 매출 트렌드."""
        all_orders = await self.order_repo.list_async()
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days)

        daily: Dict[str, Dict[str, Any]] = {}

        # 빈 날짜 초기화
        for i in range(days):
            date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            daily[date] = {"date": date, "sales": 0.0, "orders": 0, "profit": 0.0}

        for order in all_orders:
            if order.created_at < cutoff:
                continue
            date_str = order.created_at.strftime("%Y-%m-%d")
            if date_str not in daily:
                daily[date_str] = {"date": date_str, "sales": 0.0, "orders": 0, "profit": 0.0}

            daily[date_str]["sales"] += order.sale_price * order.quantity
            daily[date_str]["orders"] += 1
            daily[date_str]["profit"] += order.profit

        result = list(daily.values())
        result.sort(key=lambda x: x["date"])
        return result

    # ==================== Monthly Comparison ====================

    async def get_monthly_comparison(self) -> List[Dict[str, Any]]:
        """월별 매출 비교."""
        all_orders = await self.order_repo.list_async()

        monthly: Dict[str, Dict[str, Any]] = {}

        for order in all_orders:
            month_str = order.created_at.strftime("%Y-%m")
            if month_str not in monthly:
                monthly[month_str] = {
                    "month": month_str,
                    "sales": 0.0,
                    "orders": 0,
                    "profit": 0.0,
                }

            monthly[month_str]["sales"] += order.sale_price * order.quantity
            monthly[month_str]["orders"] += 1
            monthly[month_str]["profit"] += order.profit

        result = list(monthly.values())
        result.sort(key=lambda x: x["month"])
        return result

    # ==================== KPI Summary ====================

    async def get_kpi_summary(self) -> Dict[str, Any]:
        """종합 KPI 요약."""
        today = await self.get_today_stats()
        channels = await self.get_sales_by_channel()
        products = await self.get_sales_by_product()

        all_orders = await self.order_repo.list_async()
        all_products = await self.product_repo.list_async()
        all_channels = await self.channel_repo.list_async()

        total_sales = sum(o.sale_price * o.quantity for o in all_orders)
        total_profit = sum(o.profit for o in all_orders)

        return {
            "today": today,
            "overall": {
                "total_sales": total_sales,
                "total_orders": len(all_orders),
                "total_profit": total_profit,
                "avg_order_value": total_sales / len(all_orders) if all_orders else 0,
                "profit_rate": (total_profit / total_sales * 100) if total_sales > 0 else 0,
            },
            "top_channels": channels[:5],
            "top_products": products[:5],
            "total_products": len(all_products),
            "total_channels": len(all_channels),
        }

    # ==================== Order Status Stats ====================

    async def get_order_status_stats(self) -> Dict[str, int]:
        """주문 상태별 건수."""
        all_orders = await self.order_repo.list_async()

        status_counts: Dict[str, int] = {
            "pending": 0,
            "shipped": 0,
            "delivered": 0,
            "cancelled": 0,
            "returned": 0,
        }

        for order in all_orders:
            status = order.status
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts[status] = status_counts.get(status, 0) + 1

        return status_counts

    # ==================== Internal ====================

    async def _compute_stats_for_period(
        self, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """기간 내 주문으로 통계 계산."""
        all_orders = await self.order_repo.list_async()

        filtered = [
            o for o in all_orders
            if start <= o.created_at <= end
        ]

        total_sales = sum(o.sale_price * o.quantity for o in filtered)
        total_profit = sum(o.profit for o in filtered)
        total_orders = len(filtered)

        return {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "total_profit": total_profit,
            "avg_order_value": total_sales / total_orders if total_orders > 0 else 0,
            "profit_rate": (total_profit / total_sales * 100) if total_sales > 0 else 0,
        }

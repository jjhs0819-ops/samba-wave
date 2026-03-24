"""스토어케어 서비스."""

from .model import StoreCareSchedule, StoreCarePurchase
from .repository import StoreCareScheduleRepository, StoreCarePurchaseRepository


class StoreCareService:
    def __init__(
        self,
        schedule_repo: StoreCareScheduleRepository,
        purchase_repo: StoreCarePurchaseRepository,
    ):
        self.schedules = schedule_repo
        self.purchases = purchase_repo

    # ── 스케줄 CRUD ──

    async def list_schedules(self, tenant_id: str | None = None):
        """활성 스케줄 목록 조회."""
        return await self.schedules.list_active(tenant_id)

    async def create_schedule(self, data: dict) -> StoreCareSchedule:
        """스케줄 생성."""
        return await self.schedules.create_async(**data)

    async def update_schedule(self, schedule_id: str, data: dict):
        """스케줄 수정."""
        return await self.schedules.update_async(schedule_id, **data)

    async def delete_schedule(self, schedule_id: str):
        """스케줄 삭제."""
        return await self.schedules.delete_async(schedule_id)

    async def toggle_schedule(self, schedule_id: str) -> StoreCareSchedule | None:
        """스케줄 일시정지/재개 토글."""
        s = await self.schedules.get_async(schedule_id)
        if not s:
            return None
        new_status = "paused" if s.status != "paused" else "scheduled"
        await self.schedules.update_async(schedule_id, status=new_status)
        return await self.schedules.get_async(schedule_id)

    # ── 구매 이력 ──

    async def list_purchases(
        self,
        limit: int = 50,
        tenant_id: str | None = None,
        market_type: str | None = None,
    ):
        """최근 구매 이력 조회."""
        return await self.purchases.list_recent(limit, tenant_id, market_type)

    async def create_purchase(self, data: dict) -> StoreCarePurchase:
        """구매 이력 생성."""
        return await self.purchases.create_async(**data)

    async def today_stats(self, tenant_id: str | None = None):
        """오늘 가구매 통계."""
        return await self.purchases.today_stats(tenant_id)

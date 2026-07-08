"""스토어케어 리포지토리."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.shared.base_repository import BaseRepository
from .model import (
    StoreCareSchedule,
    StoreCarePurchase,
    StoreCareMarketMetric,
    StoreCareSavedProduct,
)

UTC = timezone.utc


class StoreCareScheduleRepository(BaseRepository[StoreCareSchedule]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, StoreCareSchedule)

    async def list_active(
        self, tenant_id: str | None = None
    ) -> list[StoreCareSchedule]:
        """활성 스케줄 목록 조회."""
        stmt = select(StoreCareSchedule).where(StoreCareSchedule.is_active == True)
        if tenant_id:
            stmt = stmt.where(StoreCareSchedule.tenant_id == tenant_id)
        stmt = stmt.order_by(StoreCareSchedule.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class StoreCarePurchaseRepository(BaseRepository[StoreCarePurchase]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, StoreCarePurchase)

    async def list_recent(
        self,
        limit: int = 50,
        tenant_id: str | None = None,
        market_type: str | None = None,
    ) -> list[StoreCarePurchase]:
        """최근 구매 이력 조회."""
        stmt = select(StoreCarePurchase)
        if tenant_id:
            stmt = stmt.where(StoreCarePurchase.tenant_id == tenant_id)
        if market_type:
            stmt = stmt.where(StoreCarePurchase.market_type == market_type)
        stmt = stmt.order_by(StoreCarePurchase.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def today_stats(self, tenant_id: str | None = None) -> dict:
        """오늘 가구매 통계."""
        from datetime import date

        today_start = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=UTC
        )

        stmt = select(
            func.count().label("total"),
            func.count()
            .filter(StoreCarePurchase.status == "completed")
            .label("success"),
            func.count().filter(StoreCarePurchase.status == "failed").label("failed"),
            func.coalesce(
                func.sum(StoreCarePurchase.amount).filter(
                    StoreCarePurchase.status == "completed"
                ),
                0,
            ).label("total_amount"),
        ).where(StoreCarePurchase.created_at >= today_start)
        if tenant_id:
            stmt = stmt.where(StoreCarePurchase.tenant_id == tenant_id)

        row = (await self.session.execute(stmt)).one()
        return {
            "total": row.total,
            "success": row.success,
            "failed": row.failed,
            "total_amount": row.total_amount,
        }


class StoreCareMarketMetricRepository(BaseRepository[StoreCareMarketMetric]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, StoreCareMarketMetric)

    async def list_latest_per_market(
        self, tenant_id: str | None = None
    ) -> list[StoreCareMarketMetric]:
        """마켓+계정별 최신 스냅샷 1건씩 (collected_at 내림차순 dedup).

        계정별 점수 — 11번가 여러 셀러계정(나디/소경/…) 등 계정마다 1건.
        account_id 없는(계정미지정) 스냅샷은 market_type 단독 키(빈 계정)로 유지.
        """
        stmt = select(StoreCareMarketMetric)
        if tenant_id:
            stmt = stmt.where(StoreCareMarketMetric.tenant_id == tenant_id)
        stmt = stmt.order_by(StoreCareMarketMetric.collected_at.desc())
        rows = list((await self.session.execute(stmt)).scalars().all())
        latest: dict[tuple[str, str], StoreCareMarketMetric] = {}
        for r in rows:
            key = (r.market_type, r.account_id or "")
            if key not in latest:
                latest[key] = r
        return list(latest.values())


class StoreCareSavedProductRepository(BaseRepository[StoreCareSavedProduct]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, StoreCareSavedProduct)

    async def list_by_tenant(
        self, tenant_id: str | None = None
    ) -> list[StoreCareSavedProduct]:
        """테넌트의 저장 상품 목록 (최신순)."""
        stmt = select(StoreCareSavedProduct)
        if tenant_id:
            stmt = stmt.where(StoreCareSavedProduct.tenant_id == tenant_id)
        stmt = stmt.order_by(StoreCareSavedProduct.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

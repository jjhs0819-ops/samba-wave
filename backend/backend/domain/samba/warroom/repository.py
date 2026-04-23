"""SambaWave 모니터링 이벤트 저장소."""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.warroom.model import SambaMonitorEvent


class SambaMonitorEventRepository(BaseRepository[SambaMonitorEvent]):
    def __init__(self, session):
        super().__init__(session, SambaMonitorEvent)

    async def list_recent(self, limit: int = 50) -> List[SambaMonitorEvent]:
        """최근 이벤트 조회 (created_at DESC)."""
        stmt = (
            select(SambaMonitorEvent)
            .order_by(SambaMonitorEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_type_since(
        self,
        since: datetime,
    ) -> Dict[str, int]:
        """특정 시각 이후 event_type별 카운트."""
        stmt = (
            select(
                SambaMonitorEvent.event_type,
                func.count(SambaMonitorEvent.id),
            )
            .where(SambaMonitorEvent.created_at >= since)
            .group_by(SambaMonitorEvent.event_type)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def list_by_severity(
        self,
        severity: str,
        limit: int = 20,
    ) -> List[SambaMonitorEvent]:
        """심각도별 최근 이벤트 조회."""
        stmt = (
            select(SambaMonitorEvent)
            .where(SambaMonitorEvent.severity == severity)
            .order_by(SambaMonitorEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_type(
        self,
        event_type: str,
        limit: int = 50,
    ) -> List[SambaMonitorEvent]:
        """이벤트 타입별 최근 이벤트 조회."""
        stmt = (
            select(SambaMonitorEvent)
            .where(SambaMonitorEvent.event_type == event_type)
            .order_by(SambaMonitorEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_latest_per_site(
        self,
        event_type: str,
        per_site_limit: int = 2,
    ) -> List[SambaMonitorEvent]:
        """이벤트 타입별 source_site당 최신 N건 조회."""
        from sqlalchemy import literal_column

        row_num = (
            func.row_number()
            .over(
                partition_by=SambaMonitorEvent.source_site,
                order_by=SambaMonitorEvent.created_at.desc(),
            )
            .label("rn")
        )

        subq = (
            select(SambaMonitorEvent.id, row_num).where(
                SambaMonitorEvent.event_type == event_type,
                SambaMonitorEvent.source_site.is_not(None),
            )
        ).subquery()

        stmt = (
            select(SambaMonitorEvent)
            .join(subq, SambaMonitorEvent.id == subq.c.id)
            .where(literal_column("rn") <= per_site_limit)
            .order_by(SambaMonitorEvent.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_changes_per_site(
        self,
        event_types: List[str],
        per_site_limit: int = 5,
    ) -> List[SambaMonitorEvent]:
        """소싱처·이벤트타입별 최신 N건 조회 (price_changed/sold_out 등)."""
        from sqlalchemy import literal_column

        row_num = (
            func.row_number()
            .over(
                partition_by=[
                    SambaMonitorEvent.source_site,
                    SambaMonitorEvent.event_type,
                ],
                order_by=SambaMonitorEvent.created_at.desc(),
            )
            .label("rn")
        )

        subq = (
            select(SambaMonitorEvent.id, row_num).where(
                SambaMonitorEvent.event_type.in_(event_types),
                SambaMonitorEvent.source_site.is_not(None),
            )
        ).subquery()

        stmt = (
            select(SambaMonitorEvent)
            .join(subq, SambaMonitorEvent.id == subq.c.id)
            .where(literal_column("rn") <= per_site_limit)
            .order_by(
                SambaMonitorEvent.source_site,
                SambaMonitorEvent.event_type,
                SambaMonitorEvent.created_at.desc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent_changes_for_markets(
        self,
        event_types: List[str],
        limit: int = 300,
    ) -> List[SambaMonitorEvent]:
        """판매처 fan-out 용 — 최근 가격변동/품절 이벤트 조회 (product_id 보유분만)."""
        stmt = (
            select(SambaMonitorEvent)
            .where(
                SambaMonitorEvent.event_type.in_(event_types),
                SambaMonitorEvent.product_id.is_not(None),
            )
            .order_by(SambaMonitorEvent.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def cleanup_old(self, before: datetime) -> int:
        """오래된 이벤트 정리."""
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(SambaMonitorEvent).where(SambaMonitorEvent.created_at < before)
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    async def count_hourly_since(
        self,
        event_type: str,
        since: datetime,
    ) -> List[Dict[str, Any]]:
        """시간대별 이벤트 카운트 (차트용)."""
        from sqlalchemy import extract

        stmt = (
            select(
                extract("hour", SambaMonitorEvent.created_at).label("hour"),
                func.count(SambaMonitorEvent.id).label("cnt"),
            )
            .where(
                SambaMonitorEvent.event_type == event_type,
                SambaMonitorEvent.created_at >= since,
            )
            .group_by("hour")
            .order_by("hour")
        )
        result = await self.session.execute(stmt)
        return [{"hour": int(row[0]), "count": row[1]} for row in result.all()]

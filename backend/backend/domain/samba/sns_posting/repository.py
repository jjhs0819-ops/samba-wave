"""SambaWave SNS 포스팅 repository."""

from typing import List, Optional

from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.sns_posting.model import (
    SambaSnKeywordGroup,
    SambaSnsAutoConfig,
    SambaSnsPost,
    SambaWpSite,
)


class SambaWpSiteRepository(BaseRepository[SambaWpSite]):
    """워드프레스 사이트 연결 repository."""

    def __init__(self, session):
        super().__init__(session, SambaWpSite)

    async def list_active(self, tenant_id: Optional[str] = None) -> List[SambaWpSite]:
        """활성화된 사이트 목록 조회."""
        kwargs = {"status": "active", "order_by": "created_at", "order_by_desc": True}
        if tenant_id is not None:
            kwargs["tenant_id"] = tenant_id
        return await self.filter_by_async(**kwargs)

    async def find_by_url(self, site_url: str) -> Optional[SambaWpSite]:
        """URL로 사이트 조회."""
        stmt = select(SambaWpSite).where(SambaWpSite.site_url == site_url)
        result = await self.session.execute(stmt)
        return result.scalars().first()


class SambaSnKeywordGroupRepository(BaseRepository[SambaSnKeywordGroup]):
    """이슈 검색 키워드 그룹 repository."""

    def __init__(self, session):
        super().__init__(session, SambaSnKeywordGroup)

    async def list_active(
        self, tenant_id: Optional[str] = None
    ) -> List[SambaSnKeywordGroup]:
        """활성화된 키워드 그룹 목록 조회."""
        kwargs = {"is_active": True, "order_by": "created_at", "order_by_desc": True}
        if tenant_id is not None:
            kwargs["tenant_id"] = tenant_id
        return await self.filter_by_async(**kwargs)

    async def list_by_category(self, category: str) -> List[SambaSnKeywordGroup]:
        """카테고리별 키워드 그룹 조회."""
        return await self.filter_by_async(
            category=category, order_by="created_at", order_by_desc=True
        )


class SambaSnsPostRepository(BaseRepository[SambaSnsPost]):
    """SNS 포스팅 이력 repository."""

    def __init__(self, session):
        super().__init__(session, SambaSnsPost)

    async def list_by_status(self, status: str, limit: int = 50) -> List[SambaSnsPost]:
        """상태별 포스트 목록 조회."""
        return await self.filter_by_async(
            status=status,
            limit=limit,
            order_by="created_at",
            order_by_desc=True,
        )

    async def list_by_site(
        self, wp_site_id: str, skip: int = 0, limit: int = 50
    ) -> List[SambaSnsPost]:
        """사이트별 포스트 목록 조회."""
        return await self.filter_by_async(
            wp_site_id=wp_site_id,
            skip=skip,
            limit=limit,
            order_by="created_at",
            order_by_desc=True,
        )

    async def count_today(self, wp_site_id: str) -> int:
        """오늘 발행된 포스트 수 조회."""
        from datetime import date, datetime, timezone

        from sqlalchemy import func

        today_start = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        stmt = (
            select(func.count())
            .select_from(SambaSnsPost)
            .where(SambaSnsPost.wp_site_id == wp_site_id)
            .where(SambaSnsPost.status == "published")
            .where(SambaSnsPost.published_at >= today_start)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class SambaSnsAutoConfigRepository(BaseRepository[SambaSnsAutoConfig]):
    """SNS 자동 포스팅 설정 repository."""

    def __init__(self, session):
        super().__init__(session, SambaSnsAutoConfig)

    async def find_by_site(self, wp_site_id: str) -> Optional[SambaSnsAutoConfig]:
        """사이트별 자동 포스팅 설정 조회."""
        return await self.find_by_async(wp_site_id=wp_site_id)

    async def list_running(self) -> List[SambaSnsAutoConfig]:
        """실행 중인 자동 포스팅 설정 목록 조회."""
        return await self.filter_by_async(is_running=True)

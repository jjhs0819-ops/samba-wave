"""SambaWave Collector repository."""

from typing import List, Optional

from sqlalchemy import or_
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.collector.model import SambaCollectedProduct, SambaSearchFilter


class SambaSearchFilterRepository(BaseRepository[SambaSearchFilter]):
    def __init__(self, session):
        super().__init__(session, SambaSearchFilter)

    async def list_by_site(self, source_site: str) -> List[SambaSearchFilter]:
        return await self.filter_by_async(
            source_site=source_site, order_by="created_at", order_by_desc=True
        )


class SambaCollectedProductRepository(BaseRepository[SambaCollectedProduct]):
    def __init__(self, session):
        super().__init__(session, SambaCollectedProduct)

    async def search(self, query: str, limit: int = 100) -> List[SambaCollectedProduct]:
        lower_q = f"%{query.lower()}%"
        stmt = (
            select(SambaCollectedProduct)
            .where(
                or_(
                    SambaCollectedProduct.name.ilike(lower_q),
                    SambaCollectedProduct.brand.ilike(lower_q),
                    SambaCollectedProduct.source_site.ilike(lower_q),
                )
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> List[SambaCollectedProduct]:
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )

    async def list_by_filters(
        self,
        status: str | None = None,
        source_site: str | None = None,
    ) -> List[SambaCollectedProduct]:
        """status, source_site 조합 필터링."""
        kwargs: dict = {"order_by": "created_at", "order_by_desc": True}
        if status:
            kwargs["status"] = status
        if source_site:
            kwargs["source_site"] = source_site
        return await self.filter_by_async(**kwargs)

    async def list_by_filter(
        self, search_filter_id: str, skip: int = 0, limit: int = 50
    ) -> List[SambaCollectedProduct]:
        return await self.filter_by_async(
            search_filter_id=search_filter_id,
            skip=skip,
            limit=limit,
            order_by="created_at",
            order_by_desc=True,
        )

    async def find_by_site_product_id(
        self, source_site: str, site_product_id: str
    ) -> Optional[SambaCollectedProduct]:
        return await self.find_by_async(
            source_site=source_site, site_product_id=site_product_id
        )

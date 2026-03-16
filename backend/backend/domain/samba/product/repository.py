"""SambaWave Product repository."""

from typing import List, Optional

from sqlalchemy import or_
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.product.model import SambaProduct


class SambaProductRepository(BaseRepository[SambaProduct]):
    def __init__(self, session):
        super().__init__(session, SambaProduct)

    async def search(self, query: str, limit: int = 100) -> List[SambaProduct]:
        lower_q = f"%{query.lower()}%"
        stmt = (
            select(SambaProduct)
            .where(
                or_(
                    SambaProduct.name.ilike(lower_q),
                    SambaProduct.source_url.ilike(lower_q),
                    SambaProduct.source_site.ilike(lower_q),
                    SambaProduct.brand.ilike(lower_q),
                )
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> List[SambaProduct]:
        return await self.filter_by_async(status=status, order_by="created_at", order_by_desc=True)

    async def list_by_source_site(
        self, source_site: str, skip: int = 0, limit: int = 50
    ) -> List[SambaProduct]:
        return await self.filter_by_async(
            source_site=source_site, skip=skip, limit=limit,
            order_by="created_at", order_by_desc=True,
        )

    async def find_by_site_product_id(
        self, source_site: str, site_product_id: str
    ) -> Optional[SambaProduct]:
        return await self.find_by_async(
            source_site=source_site, site_product_id=site_product_id
        )

"""SambaWave Product repository."""

from typing import List

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
        return await self.filter_by_async(
            status=status, order_by="created_at", order_by_desc=True
        )

"""SambaWave Collector repository."""

from typing import List

from sqlalchemy import or_
from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.collector.model import (
    SambaCollectedProduct,
    SambaSearchFilter,
)


class SambaSearchFilterRepository(BaseRepository[SambaSearchFilter]):
    def __init__(self, session):
        super().__init__(session, SambaSearchFilter)


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
        self, search_filter_id: str, skip: int = 0, limit: int = 10000
    ) -> List[SambaCollectedProduct]:
        """필터에 속한 전체 상품 조회 (정책 전파 등에 사용)."""
        return await self.filter_by_async(
            search_filter_id=search_filter_id,
            skip=skip,
            limit=limit,
            order_by="created_at",
            order_by_desc=True,
        )

    async def get_registered_name_keys(self, tenant_id: str) -> tuple[set, set]:
        """마켓 등록된 상품의 (name_set, (source_site, site_product_id)_set) 반환."""
        from sqlalchemy import cast, String

        stmt = select(
            SambaCollectedProduct.name,
            SambaCollectedProduct.source_site,
            SambaCollectedProduct.site_product_id,
        ).where(
            SambaCollectedProduct.tenant_id == tenant_id,
            SambaCollectedProduct.registered_accounts.isnot(None),
            cast(SambaCollectedProduct.registered_accounts, String) != "null",
            cast(SambaCollectedProduct.registered_accounts, String) != "[]",
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        name_set = {(r[0] or "").strip() for r in rows if r[0]}
        key_set = {(r[1], r[2]) for r in rows if r[1] and r[2]}
        return name_set, key_set

    async def find_duplicates(self, tenant_id: str) -> list:
        """마켓 등록 상품과 동일 name인 상품 전체 반환 (소싱처 무관)."""
        from sqlalchemy import cast, String

        # 마켓 등록된 상품의 name 서브쿼리
        registered_names_sq = (
            select(SambaCollectedProduct.name)
            .where(
                SambaCollectedProduct.tenant_id == tenant_id,
                SambaCollectedProduct.registered_accounts.isnot(None),
                cast(SambaCollectedProduct.registered_accounts, String) != "null",
                cast(SambaCollectedProduct.registered_accounts, String) != "[]",
            )
            .distinct()
        ).subquery()

        stmt = (
            select(SambaCollectedProduct)
            .where(
                SambaCollectedProduct.tenant_id == tenant_id,
                SambaCollectedProduct.name.in_(select(registered_names_sq.c.name)),
            )
            .order_by(
                SambaCollectedProduct.name,
                SambaCollectedProduct.created_at,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_update_by_filter(self, search_filter_id: str, **kwargs) -> int:
        """search_filter_id에 해당하는 모든 상품을 한 번의 쿼리로 업데이트."""
        from sqlalchemy import update

        stmt = (
            update(SambaCollectedProduct)
            .where(SambaCollectedProduct.search_filter_id == search_filter_id)
            .values(**kwargs)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount

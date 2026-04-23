"""eBay 매핑 Repository."""

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.ebay_mapping.model import SambaEbayMapping


class SambaEbayMappingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find(self, category: str, kr_value: str) -> Optional[SambaEbayMapping]:
        """카테고리+한글값으로 매핑 1건 조회."""
        stmt = select(SambaEbayMapping).where(
            SambaEbayMapping.category == category,
            SambaEbayMapping.kr_value == kr_value,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_category(
        self, category: Optional[str] = None
    ) -> list[SambaEbayMapping]:
        """카테고리별 매핑 리스트 조회 (없으면 전체)."""
        stmt = select(SambaEbayMapping)
        if category:
            stmt = stmt.where(SambaEbayMapping.category == category)
        stmt = stmt.order_by(SambaEbayMapping.category, SambaEbayMapping.kr_value)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        category: str,
        kr_value: str,
        en_value: str,
        source: str = "manual",
    ) -> SambaEbayMapping:
        """매핑 upsert. 이미 있으면 source가 'manual'일 때만 덮어쓴다."""
        existing = await self.find(category, kr_value)
        if existing:
            # manual은 기존 값 덮어쓰기, ai/default는 manual이 우선
            if source == "manual" or existing.source == "default":
                existing.en_value = en_value
                existing.source = source
                from datetime import datetime, timezone

                existing.updated_at = datetime.now(tz=timezone.utc)
                self.session.add(existing)
                await self.session.flush()
            return existing

        row = SambaEbayMapping(
            category=category,
            kr_value=kr_value,
            en_value=en_value,
            source=source,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, mapping_id: str) -> bool:
        """매핑 삭제."""
        stmt = select(SambaEbayMapping).where(SambaEbayMapping.id == mapping_id)
        result = await self.session.execute(stmt)
        row = result.scalars().first()
        if not row:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def count_all(self) -> int:
        """전체 매핑 개수."""
        stmt = select(SambaEbayMapping)
        result = await self.session.execute(stmt)
        return len(list(result.scalars().all()))

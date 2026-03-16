"""SambaWave Category repository."""

from typing import Optional

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.category.model import SambaCategoryMapping, SambaCategoryTree


class SambaCategoryMappingRepository(BaseRepository[SambaCategoryMapping]):
    def __init__(self, session):
        super().__init__(session, SambaCategoryMapping)

    async def find_mapping(
        self, source_site: str, source_category: str
    ) -> Optional[SambaCategoryMapping]:
        return await self.find_by_async(
            source_site=source_site, source_category=source_category
        )


class SambaCategoryTreeRepository(BaseRepository[SambaCategoryTree]):
    def __init__(self, session):
        super().__init__(session, SambaCategoryTree)

    async def get_by_site(self, site_name: str) -> Optional[SambaCategoryTree]:
        """Get category tree by site_name (primary key)."""
        return await self.find_by_async(site_name=site_name)

    async def delete_by_site(self, site_name: str) -> bool:
        """Delete category tree by site_name."""
        entity = await self.get_by_site(site_name)
        if not entity:
            return False
        await self.session.delete(entity)
        await self.session.commit()
        return True

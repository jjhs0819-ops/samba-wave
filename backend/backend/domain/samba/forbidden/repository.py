"""SambaWave Forbidden word repository."""

from typing import List

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.forbidden.model import SambaForbiddenWord, SambaSettings


class SambaForbiddenWordRepository(BaseRepository[SambaForbiddenWord]):
    def __init__(self, session):
        super().__init__(session, SambaForbiddenWord)

    async def list_by_type(self, type: str) -> List[SambaForbiddenWord]:
        return await self.filter_by_async(
            type=type, order_by="created_at", order_by_desc=True
        )

    async def list_active(self, type: str) -> List[SambaForbiddenWord]:
        return await self.filter_by_async(
            type=type, is_active=True, order_by="created_at", order_by_desc=True
        )


class SambaSettingsRepository(BaseRepository[SambaSettings]):
    def __init__(self, session):
        super().__init__(session, SambaSettings)

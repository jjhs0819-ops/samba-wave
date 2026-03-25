"""테넌트 리포지토리."""

from backend.domain.shared.base_repository import BaseRepository
from .model import SambaTenant


class SambaTenantRepository(BaseRepository[SambaTenant]):
    def __init__(self, session):
        super().__init__(session, SambaTenant)

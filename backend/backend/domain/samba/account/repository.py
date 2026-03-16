"""SambaWave Account repository."""

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.account.model import SambaMarketAccount


class SambaMarketAccountRepository(BaseRepository[SambaMarketAccount]):
    def __init__(self, session):
        super().__init__(session, SambaMarketAccount)

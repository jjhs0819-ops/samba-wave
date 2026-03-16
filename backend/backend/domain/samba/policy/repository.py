"""SambaWave Policy repository."""

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.policy.model import SambaPolicy


class SambaPolicyRepository(BaseRepository[SambaPolicy]):
    def __init__(self, session):
        super().__init__(session, SambaPolicy)

"""SambaWave Channel repository."""

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.channel.model import SambaChannel


class SambaChannelRepository(BaseRepository[SambaChannel]):
    def __init__(self, session):
        super().__init__(session, SambaChannel)

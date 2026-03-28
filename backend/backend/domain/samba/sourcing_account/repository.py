"""소싱처 계정 Repository."""

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.sourcing_account.model import SambaSourcingAccount


class SambaSourcingAccountRepository(BaseRepository[SambaSourcingAccount]):
    def __init__(self, session):
        super().__init__(session, SambaSourcingAccount)

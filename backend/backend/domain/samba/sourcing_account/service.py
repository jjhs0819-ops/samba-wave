"""소싱처 계정 Service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain.samba.sourcing_account.model import (
    SambaSourcingAccount,
    SUPPORTED_SOURCING_SITES,
)
from backend.domain.samba.sourcing_account.repository import SambaSourcingAccountRepository
from backend.utils.logger import logger


class SambaSourcingAccountService:
    def __init__(self, repo: SambaSourcingAccountRepository):
        self.repo = repo

    async def list_accounts(
        self, site_name: Optional[str] = None, skip: int = 0, limit: int = 100,
    ) -> List[SambaSourcingAccount]:
        if site_name:
            return await self.repo.filter_by_async(
                site_name=site_name, order_by="created_at", order_by_desc=True,
            )
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_account(self, account_id: str) -> Optional[SambaSourcingAccount]:
        return await self.repo.get_async(account_id)

    async def create_account(self, data: Dict[str, Any]) -> SambaSourcingAccount:
        return await self.repo.create_async(**data)

    async def update_account(
        self, account_id: str, data: Dict[str, Any],
    ) -> Optional[SambaSourcingAccount]:
        data["updated_at"] = datetime.now(timezone.utc)
        return await self.repo.update_async(account_id, **data)

    async def delete_account(self, account_id: str) -> bool:
        return await self.repo.delete_async(account_id)

    async def toggle_active(self, account_id: str) -> Optional[SambaSourcingAccount]:
        account = await self.repo.get_async(account_id)
        if not account:
            return None
        return await self.repo.update_async(account_id, is_active=not account.is_active)

    async def update_balance(
        self, account_id: str, balance: float,
    ) -> Optional[SambaSourcingAccount]:
        """잔액 업데이트."""
        return await self.repo.update_async(
            account_id,
            balance=balance,
            balance_updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def get_supported_sites() -> List[Dict[str, str]]:
        return SUPPORTED_SOURCING_SITES

"""소싱처 계정 Service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain.samba.sourcing_account.model import (
    SambaSourcingAccount,
    SUPPORTED_SOURCING_SITES,
)
from backend.domain.samba.sourcing_account.repository import (
    SambaSourcingAccountRepository,
)


class SambaSourcingAccountService:
    def __init__(self, repo: SambaSourcingAccountRepository):
        self.repo = repo

    async def list_accounts(
        self,
        site_name: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[SambaSourcingAccount]:
        if site_name:
            return await self.repo.filter_by_async(
                site_name=site_name,
                order_by="created_at",
                order_by_desc=True,
            )
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_account(self, account_id: str) -> Optional[SambaSourcingAccount]:
        return await self.repo.get_async(account_id)

    async def create_account(self, data: Dict[str, Any]) -> SambaSourcingAccount:
        return await self.repo.create_async(**data)

    async def update_account(
        self,
        account_id: str,
        data: Dict[str, Any],
    ) -> Optional[SambaSourcingAccount]:
        from backend.utils.masking import (
            drop_masked_secret_fields,
            sanitize_top_level_secrets,
        )

        # 클라이언트가 GET 응답의 마스킹값(****XXXX)을 그대로 돌려보낼 때
        # 진짜 password/secret 값을 덮어쓰는 사고를 차단.
        # 최상위 password 컬럼 + additional_fields 내부 민감 키 모두 가드.
        data = sanitize_top_level_secrets(data)
        if "additional_fields" in data and isinstance(data["additional_fields"], dict):
            cleaned_incoming = drop_masked_secret_fields(data["additional_fields"])
            existing = await self.repo.get_async(account_id)
            if existing:
                existing_af = existing.additional_fields or {}
                if isinstance(existing_af, dict):
                    data["additional_fields"] = {
                        **existing_af,
                        **cleaned_incoming,
                    }
                else:
                    data["additional_fields"] = cleaned_incoming
            else:
                data["additional_fields"] = cleaned_incoming
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
        self,
        account_id: str,
        balance: float,
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

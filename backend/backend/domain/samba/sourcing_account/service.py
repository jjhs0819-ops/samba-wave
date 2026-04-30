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

    async def set_login_default(
        self,
        account_id: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[SambaSourcingAccount]:
        """자동로그인 기본 계정으로 지정 — 같은 site_name의 다른 계정은 모두 false로 강제.

        라디오 버튼 동작 (사이트당 1개만 true). tenant_id가 주어지면 같은 테넌트 범위로 한정.
        """
        account = await self.repo.get_async(account_id)
        if not account:
            return None

        # 같은 site_name의 다른 계정 모두 is_login_default=false 처리
        # (tenant_id가 None이면 NULL tenant 범위, 아니면 해당 tenant 범위)
        from sqlalchemy import update as sa_update
        from backend.domain.samba.sourcing_account.model import SambaSourcingAccount

        stmt = (
            sa_update(SambaSourcingAccount)
            .where(SambaSourcingAccount.site_name == account.site_name)
            .where(SambaSourcingAccount.id != account_id)
        )
        if tenant_id is not None:
            stmt = stmt.where(SambaSourcingAccount.tenant_id == tenant_id)
        else:
            stmt = stmt.where(SambaSourcingAccount.tenant_id.is_(None))

        stmt = stmt.values(
            is_login_default=False, updated_at=datetime.now(timezone.utc)
        )
        await self.repo.session.execute(stmt)

        # 대상 계정만 true로 설정
        return await self.repo.update_async(account_id, is_login_default=True)

    async def get_login_default(
        self,
        site_name: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[SambaSourcingAccount]:
        """site_name + tenant_id로 자동로그인 기본 계정 조회 (확장앱 fetch용)."""
        from sqlalchemy import or_, select as sa_select
        from backend.domain.samba.sourcing_account.model import SambaSourcingAccount

        stmt = sa_select(SambaSourcingAccount).where(
            SambaSourcingAccount.site_name == site_name,
            SambaSourcingAccount.is_login_default.is_(True),
            SambaSourcingAccount.is_active.is_(True),
        )
        if tenant_id is not None:
            stmt = stmt.where(
                or_(
                    SambaSourcingAccount.tenant_id == tenant_id,
                    SambaSourcingAccount.tenant_id.is_(None),
                )
            )
        result = await self.repo.session.execute(stmt)
        return result.scalars().first()

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

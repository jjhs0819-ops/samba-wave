"""테넌트 서비스."""

from .repository import SambaTenantRepository
from .model import SambaTenant


class SambaTenantService:
    def __init__(self, repo: SambaTenantRepository):
        self.repo = repo

    async def create_tenant(self, data: dict) -> SambaTenant:
        return await self.repo.create_async(**data)

    async def get_tenant(self, tenant_id: str) -> SambaTenant | None:
        return await self.repo.get_async(tenant_id)

    async def list_tenants(self, skip: int = 0, limit: int = 50):
        return await self.repo.list_async(skip=skip, limit=limit)

    async def update_tenant(self, tenant_id: str, data: dict):
        return await self.repo.update_async(tenant_id, **data)

"""SambaWave Product service."""

from typing import Any, Dict, List, Optional

from backend.domain.samba.product.model import SambaProduct
from backend.domain.samba.product.repository import SambaProductRepository


class SambaProductService:
    def __init__(self, repo: SambaProductRepository):
        self.repo = repo

    async def list_products(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> List[SambaProduct]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_product(self, product_id: str) -> Optional[SambaProduct]:
        return await self.repo.get_async(product_id)

    async def create_product(self, data: Dict[str, Any]) -> SambaProduct:
        return await self.repo.create_async(**data)

    async def update_product(
        self, product_id: str, data: Dict[str, Any]
    ) -> Optional[SambaProduct]:
        return await self.repo.update_async(product_id, **data)

    async def delete_product(self, product_id: str) -> bool:
        return await self.repo.delete_async(product_id)

    async def search_products(self, query: str, limit: int = 100) -> List[SambaProduct]:
        return await self.repo.search(query, limit)

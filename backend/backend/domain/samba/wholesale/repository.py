"""SambaWave Wholesale repository - 도매몰 상품 데이터 접근 계층."""

from typing import List, Optional

from sqlmodel import select

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.wholesale.model import SambaWholesaleProduct


class SambaWholesaleProductRepository(BaseRepository[SambaWholesaleProduct]):
    """도매몰 상품 repository."""

    def __init__(self, session):
        super().__init__(session, SambaWholesaleProduct)

    async def list_by_source_mall(
        self, source_mall: str
    ) -> List[SambaWholesaleProduct]:
        """도매몰 구분으로 상품 목록 조회."""
        return await self.filter_by_async(
            source_mall=source_mall, order_by="collected_at", order_by_desc=True
        )

    async def find_by_product_id(
        self, source_mall: str, product_id: str
    ) -> Optional[SambaWholesaleProduct]:
        """도매몰 + 상품 ID로 단건 조회 (중복 수집 방지용)."""
        stmt = (
            select(SambaWholesaleProduct)
            .where(
                SambaWholesaleProduct.source_mall == source_mall,
                SambaWholesaleProduct.product_id == product_id,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_stock_status(
        self, stock_status: str
    ) -> List[SambaWholesaleProduct]:
        """재고 상태로 상품 목록 조회."""
        return await self.filter_by_async(
            stock_status=stock_status, order_by="collected_at", order_by_desc=True
        )

    async def list_by_tenant(self, tenant_id: str) -> List[SambaWholesaleProduct]:
        """테넌트 ID로 상품 목록 조회."""
        return await self.filter_by_async(
            tenant_id=tenant_id, order_by="collected_at", order_by_desc=True
        )

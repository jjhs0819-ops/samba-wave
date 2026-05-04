"""SambaWave Tetris 정책 배치 repository."""

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.shared.base_repository import BaseRepository
from backend.domain.samba.tetris.model import SambaTetrisAssignment


class SambaTetrisRepository(BaseRepository[SambaTetrisAssignment]):
    """테트리스 배치 리포지토리."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SambaTetrisAssignment)

    async def list_by_tenant(
        self,
        tenant_id: Optional[str],
    ) -> list[SambaTetrisAssignment]:
        """테넌트 기준으로 전체 배치 목록 조회 (마켓 계정 + 순서 정렬)."""
        stmt = (
            select(SambaTetrisAssignment)
            .where(SambaTetrisAssignment.tenant_id == tenant_id)
            .order_by(
                SambaTetrisAssignment.market_account_id,
                SambaTetrisAssignment.position_order,
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_existing(
        self,
        tenant_id: Optional[str],
        source_site: str,
        brand_name: str,
        market_account_id: str,
    ) -> Optional[SambaTetrisAssignment]:
        """동일한 소싱처·브랜드·계정 조합 배치가 이미 존재하는지 확인."""
        return await self.find_by_async(
            tenant_id=tenant_id,
            source_site=source_site,
            brand_name=brand_name,
            market_account_id=market_account_id,
        )

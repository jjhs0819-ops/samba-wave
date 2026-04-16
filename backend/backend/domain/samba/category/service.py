"""SambaWave Category service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.samba.category.model import SambaCategoryTree
from backend.domain.samba.category.repository import (
    SambaCategoryMappingRepository,
    SambaCategoryTreeRepository,
)
from backend.domain.samba.category.mapping_service import CategoryMappingMixin
from backend.domain.samba.category.sync_service import CategorySyncMixin
from backend.domain.samba.category.suggestion_service import CategorySuggestionMixin
from backend.domain.samba.category.seed_service import CategorySeedMixin

logger = logging.getLogger(__name__)


class SambaCategoryService(
    CategoryMappingMixin,
    CategorySyncMixin,
    CategorySuggestionMixin,
    CategorySeedMixin,
):
    def __init__(
        self,
        mapping_repo: SambaCategoryMappingRepository,
        tree_repo: SambaCategoryTreeRepository,
    ):
        self.mapping_repo = mapping_repo
        self.tree_repo = tree_repo

    # ==================== Category Tree ====================

    async def get_category_tree(self, site_name: str) -> Optional[SambaCategoryTree]:
        return await self.tree_repo.get_by_site(site_name)

    async def save_category_tree(
        self, site_name: str, data: Dict[str, Any]
    ) -> SambaCategoryTree:
        existing = await self.tree_repo.get_by_site(site_name)
        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC)
            self.tree_repo.session.add(existing)
            await self.tree_repo.session.commit()
            await self.tree_repo.session.refresh(existing)
            return existing
        return await self.tree_repo.create_async(site_name=site_name, **data)

    async def delete_category_tree(self, site_name: str) -> bool:
        return await self.tree_repo.delete_by_site(site_name)

    # ==================== Market Registration Check ====================

    async def check_market_registered(
        self,
        mapping_ids: List[str],
        market: str,
        session: "AsyncSession",
    ) -> int:
        """매핑 대상 카테고리의 상품이 해당 마켓에 실제 등록되어 있는지 확인.

        registered_accounts 필드 기준으로 판단 (실제 등록 상태 추적).
        Returns: 등록된 상품 수
        """
        from sqlmodel import select
        from backend.domain.samba.collector.model import SambaCollectedProduct
        from backend.domain.samba.account.model import SambaMarketAccount

        # 1) 매핑 조회 → source_site + source_category 쌍 수집
        target_cats: set[tuple[str, str]] = set()
        for mid in mapping_ids:
            m = await self.mapping_repo.get_async(mid)
            if m:
                target_cats.add((m.source_site, m.source_category))

        if not target_cats:
            return 0

        # 2) 해당 마켓 계정 ID 조회
        stmt_acc = select(SambaMarketAccount.id).where(
            SambaMarketAccount.market_type == market
        )
        acc_result = await session.execute(stmt_acc)
        account_ids = set(r[0] for r in acc_result.all())
        if not account_ids:
            return 0

        # 3) 상품의 registered_accounts에 해당 마켓 계정이 있는지 확인
        # OOM 방지: 전체 상품을 메모리에 올리지 않고 SQL 필터로 범위 축소
        target_sites = {site for site, _ in target_cats}
        stmt = select(
            SambaCollectedProduct.source_site,
            SambaCollectedProduct.category,
            SambaCollectedProduct.category1,
            SambaCollectedProduct.category2,
            SambaCollectedProduct.category3,
            SambaCollectedProduct.category4,
            SambaCollectedProduct.registered_accounts,
        ).where(
            SambaCollectedProduct.source_site.in_(target_sites),
            SambaCollectedProduct.registered_accounts.isnot(None),
        )
        result = await session.execute(stmt)
        count = 0
        for row in result.all():
            site = row.source_site or ""
            cats = [row.category1, row.category2, row.category3, row.category4]
            cats = [c for c in cats if c]
            if not cats and row.category:
                cats = [c.strip() for c in row.category.split(">") if c.strip()]
            leaf = " > ".join(cats)
            if (site, leaf) not in target_cats:
                continue
            # registered_accounts에 해당 마켓 계정이 있는지 확인
            reg_accs = row.registered_accounts or []
            if any(aid in account_ids for aid in reg_accs):
                count += 1
        return count

"""미구현 소싱처 스텁 플러그인."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class GenericStubPlugin(SourcingPlugin):
    """미구현 소싱처 공통 스텁.

    직접 인스턴스화하지 않음 — 개별 소싱처 스텁의 base.
    """

    site_name = "_STUB"
    concurrency = 5

    async def search(self, keyword: str, **filters) -> list[dict]:
        return []

    async def get_detail(self, site_product_id: str) -> dict:
        return {}

    async def refresh(self, product) -> "RefreshResult":
        from backend.domain.samba.collector.refresher import RefreshResult

        return RefreshResult(
            product_id=getattr(product, "id", ""),
            error=f"{self.site_name} 소싱처 갱신 미구현",
        )

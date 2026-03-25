"""패션플러스 소싱처 플러그인 (스텁)."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
  from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class FashionPlusPlugin(SourcingPlugin):
  """패션플러스 소싱처 플러그인."""

  site_name = "FASHIONPLUS"
  concurrency = 3
  request_interval = 0.5

  async def search(self, keyword: str, **filters) -> list[dict]:
    return []

  async def get_detail(self, site_product_id: str) -> dict:
    return {}

  async def refresh(self, product) -> "RefreshResult":
    from backend.domain.samba.collector.refresher import RefreshResult
    return RefreshResult(
      product_id=getattr(product, "id", ""),
      error="FASHIONPLUS 소싱처 갱신 미구현",
    )

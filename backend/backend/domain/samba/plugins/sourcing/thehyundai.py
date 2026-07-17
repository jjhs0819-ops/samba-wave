"""더현대Hi (hi.thehyundai.com) 소싱처 플러그인.

로컬-only 운영 — 환경변수 ENABLE_THEHYUNDAI=1 일 때만 플러그인 등록.
미설정 시 클래스 자체를 모듈에서 제거 → discover_plugins() 가 못 찾음 →
SOURCING_PLUGINS dict 에 미등록 → 모든 운영 코드 경로가 자연 차단됨.

구현 방식: 순수 httpx 직접 호출 (MUSINSA 패턴). 확장앱 큐 위임 불필요
(인증/UA/Referer/Cookie 일체 불필요, 모든 GET 익명 200).

핵심 기능:
- search(): keyword/URL/카테고리/브랜드 검색 (searchType=NCP_PRODUCT 필수)
- get_detail(): detail + 조건부 uitmStckList + maxBnftList 머지
- refresh(): RefreshResult 전 필드 채움. new_cost = 카드즉시할인 반영 최저가 (SSG 선례)
- scan_categories(): searchFilterInfo 1회로 4단계 트리 평탄화
- discover_brands(): brandList → operBrndCd (canonical key) 추출
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Optional

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class TheHyundaiPlugin(SourcingPlugin):
    """더현대Hi 소싱처 플러그인.

    concurrency=3, request_interval=0 (전 사이트 0 정책, 차단 시 _site_intervals 자동 backoff).
    사이클당 호출: detail + maxBnftList + (uitmCombYn="1" 시) uitmStckList = 2~3 hop.
    """

    site_name = "THEHYUNDAI"
    concurrency = 3
    request_interval = 0

    async def search(self, keyword: str, **filters: Any) -> list[dict]:
        """키워드/URL/카테고리/브랜드 검색."""
        from backend.domain.samba.proxy.thehyundai_sourcing import (
            TheHyundaiSourcingClient,
        )

        client = TheHyundaiSourcingClient()
        return await self.safe_call(client.search_products(keyword, **filters))

    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 — detail + (uitmCombYn=="1") uitmStckList + maxBnftList 머지."""
        from backend.domain.samba.proxy.thehyundai_sourcing import (
            TheHyundaiSourcingClient,
        )

        client = TheHyundaiSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """오토튠 사이클 — RefreshResult 전 필드 채움."""
        from backend.domain.samba.proxy.thehyundai_sourcing import (
            TheHyundaiSourcingClient,
        )

        client = TheHyundaiSourcingClient()
        return await client.refresh_product(product)

    async def scan_categories(
        self,
        keyword: str,
        *,
        brand_ids: Optional[list[str]] = None,
        selected_brands: Optional[list[str]] = None,
        brand_total: int = 0,
        log_fn: Optional[Callable[[str], None]] = None,
        proxy_urls: Optional[list[str]] = None,
        **_unused: Any,
    ) -> dict:
        """카테고리 트리 스캔 — searchFilterInfo 1회 호출 → 4단계 평탄화."""
        from backend.domain.samba.proxy.thehyundai_sourcing import (
            TheHyundaiSourcingClient,
        )

        client = TheHyundaiSourcingClient()
        return await client.scan_categories(
            keyword,
            brand_ids=brand_ids,
            selected_brands=selected_brands,
            brand_total=brand_total,
            log_fn=log_fn,
            proxy_urls=proxy_urls,
        )

    async def discover_brands(self, keyword: str) -> dict:
        """브랜드 디렉토리 — brandList → {name, value=operBrndCd, count}."""
        from backend.domain.samba.proxy.thehyundai_sourcing import (
            TheHyundaiSourcingClient,
        )

        client = TheHyundaiSourcingClient()
        return await self.safe_call(client.discover_brands(keyword))


# ──────────────────────────────────────────────────────────────
# env var gate — 로컬-only 운영 핵심 안전장치 #1
# ──────────────────────────────────────────────────────────────
# ENABLE_THEHYUNDAI=1 미설정 시 클래스 자체 제거 → discover_plugins() 가
# dir(mod) 에서 TheHyundaiPlugin 을 찾지 못함 → SOURCING_PLUGINS["THEHYUNDAI"]
# 자체가 존재 안 함 → 운영 환경에서 모든 호출 경로 차단.

if os.getenv("ENABLE_THEHYUNDAI") != "1":
    del TheHyundaiPlugin
    logger.info(
        "[plugin] THEHYUNDAI 비활성 (ENABLE_THEHYUNDAI != 1) — 로컬-only 운영 가드"
    )
else:
    logger.info("[plugin] THEHYUNDAI 활성 (ENABLE_THEHYUNDAI=1)")

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class SourcingPlugin(ABC):
    """소싱처 플러그인 기본 클래스.
    새 소싱처 추가 시 search(), get_detail(), refresh() 3개 구현.
    """

    site_name: str
    concurrency: int = 5
    request_interval: float = 0

    def _get_semaphore(self):
        """동시성 제어용 세마포어 반환."""
        import asyncio

        if not hasattr(self, "_sem"):
            self._sem = asyncio.Semaphore(self.concurrency)
        return self._sem

    async def safe_call(self, coro):
        """동시성 제어 + 요청 간 딜레이."""
        import asyncio

        async with self._get_semaphore():
            if self.request_interval > 0:
                await asyncio.sleep(self.request_interval)
            return await coro

    @abstractmethod
    async def search(self, keyword: str, **filters) -> list[dict]:
        """키워드 검색."""
        ...

    @abstractmethod
    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 조회."""
        ...

    @abstractmethod
    async def refresh(self, product) -> "RefreshResult":
        """상품 정보 갱신."""
        ...

    async def test_auth(self) -> bool:
        """인증 테스트 — 기본은 항상 성공."""
        return True

    async def scan_categories(self, keyword: str, **kwargs) -> dict:
        """카테고리 스캔 — 지원하지 않는 소싱처는 빈 결과 반환."""
        return {"categories": [], "total": 0, "groupCount": 0}

    async def discover_brands(self, keyword: str) -> dict:
        """브랜드 탐색 — 지원하지 않는 소싱처는 빈 결과 반환."""
        return {"brands": [], "total": 0}

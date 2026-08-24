"""29CM (www.29cm.co.kr) 소싱처 플러그인.

구현 방식: curl_cffi 직접 호출 (NAVERSTORE 패턴). httpx 는 전 API 403 이다.

원가(최대혜택가)는 로그인 쿠키가 있어야 계산한다. 계정 등급/자격에 따라 받을 수
있는 쿠폰이 달라지기 때문이다(실측: 익명 2장 vs 로그인 1장). 쿠키는 소싱처 계정
관리에 등록된 자동로그인 계정(is_login_default=True)에서 가져온다 — 무신사와 동일.
"""

import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class TwentyNineCMPlugin(SourcingPlugin):
    """29CM 소싱처 플러그인.

    concurrency=3, request_interval=0 (전 사이트 0 정책).
    Cloudflare 뒤에 있어 차단 시 refresher 의 _site_intervals 자동 backoff 에 맡긴다.
    """

    site_name = "29CM"
    concurrency = 3
    request_interval = 0

    async def _client(self):
        """로그인 쿠키를 실은 클라이언트. 쿠키 없으면 빈 쿠키로 동작(원가 제외)."""
        from backend.domain.samba.proxy.twentyninecm import TwentyNineCMClient

        return TwentyNineCMClient(await get_29cm_cookie())

    async def search(self, keyword: str, **filters: Any) -> list[dict]:
        """키워드/브랜드/카테고리 검색."""
        client = await self._client()
        return await self.safe_call(client.search_products(keyword, **filters))

    async def get_detail(self, site_product_id: str) -> dict:
        """상품 상세 — 상세 + (쿠키 보유 시) 쿠폰 병합."""
        client = await self._client()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """오토튠 사이클 — 쿠키 없으면 29CM_AUTH_MISSING 으로 원가 갱신 차단."""
        client = await self._client()
        return await client.refresh_product(product)

    async def scan_categories(
        self,
        keyword: str = "",
        *,
        log_fn: Optional[Callable[[str], None]] = None,
        **_unused: Any,
    ) -> dict:
        """카테고리 트리 스캔 — category-groups/tree 1회 호출."""
        client = await self._client()
        return await client.scan_categories(keyword, log_fn=log_fn)

    async def discover_brands(self, keyword: str) -> dict:
        """브랜드 탐색 — 검색 결과 기반 집계."""
        client = await self._client()
        return await self.safe_call(client.discover_brands(keyword))

    async def test_auth(self) -> bool:
        """쿠키 인증 테스트 — 로그인 계정 조회 성공 여부."""
        client = await self._client()
        return await client.test_auth()


async def get_29cm_cookie() -> str:
    """자동로그인계정(is_login_default=True)의 29CM 쿠키 반환.

    원가 계산의 단일 진실 — 계정마다 쿠폰 자격이 달라 계정을 섞으면 원가가 흔들린다.
    쿠키 만료(cookie_expired=True)나 미설정이면 빈 문자열 → 호출부가 원가 갱신 차단.
    """
    try:
        from backend.db.orm import get_read_session
        from backend.domain.samba.sourcing_account.repository import (
            SambaSourcingAccountRepository,
        )
        from backend.domain.samba.sourcing_account.service import (
            SambaSourcingAccountService,
        )

        async with get_read_session() as session:
            svc = SambaSourcingAccountService(SambaSourcingAccountRepository(session))
            acc = await svc.get_login_default("29CM")
            if not acc:
                return ""
            af = acc.additional_fields or {}
            if af.get("cookie_expired"):
                return ""
            return af.get("twentyninecm_cookie", "") or ""
    except Exception as e:
        logger.warning(f"[29CM] 쿠키 조회 실패(무시): {e}")
        return ""

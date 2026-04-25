"""네이버스토어 소싱처 플러그인 — 내부 JSON API 기반."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class NaverStorePlugin(SourcingPlugin):
    """네이버스토어 소싱처 플러그인.

    내부 JSON API를 활용하여 스토어 상품 목록 및 상세를 수집한다.

    concurrency=3: 병렬 3개 (스마트스토어 API 안정적)
    request_interval=0.3: 요청 간 300ms 딜레이
    """

    site_name = "NAVERSTORE"
    concurrency = 3
    request_interval = 0.3

    async def search(self, keyword: str, **filters) -> list[dict]:
        """네이버스토어 상품 검색.

        keyword가 URL인 경우 → 해당 스토어의 상품 목록 조회
        keyword가 일반 텍스트인 경우 → 현재 미지원
        """
        from backend.domain.samba.proxy.naverstore_sourcing import (
            NaverStoreSourcingClient,
        )

        client = NaverStoreSourcingClient()

        # URL이면 스토어 상품 목록 조회
        if "smartstore.naver.com" in keyword or "brand.naver.com" in keyword:
            page = filters.get("page", 1)
            size = filters.get("size", 40)
            sort = filters.get("sort", "POPULAR")
            result = await self.safe_call(
                client.get_store_products(
                    keyword,
                    page=page,
                    page_size=size,
                    sort_type=sort,
                )
            )
            return result.get("products", []) if isinstance(result, dict) else []

        logger.warning(
            f"[NAVERSTORE] 키워드 검색은 스토어 URL을 입력해주세요: {keyword}"
        )
        return []

    async def get_detail(self, site_product_id: str, **kwargs) -> dict:
        """네이버스토어 상품 상세 조회.

        Args:
            site_product_id: 상품 URL 또는 채널상품ID
            **kwargs: channel_uid (선택)
        """
        from backend.domain.samba.proxy.naverstore_sourcing import (
            NaverStoreSourcingClient,
        )

        client = NaverStoreSourcingClient()
        channel_uid = kwargs.get("channel_uid")
        cookies = kwargs.get("cookies")
        return await self.safe_call(
            client.get_product_detail(
                site_product_id, channel_uid=channel_uid, cookies=cookies
            )
        )

    async def browse_store(
        self,
        store_url: str,
        page: int = 1,
        page_size: int = 40,
        sort: str = "POPULAR",
    ) -> dict[str, Any]:
        """스토어 상품 목록 조회.

        Args:
            store_url: 스마트스토어 URL
            page: 페이지 번호
            page_size: 페이지당 상품 수
            sort: 정렬 (POPULAR, RECENT, LOW_PRICE, HIGH_PRICE, REVIEW)

        Returns:
            {"products": [...], "totalCount": int, "page": int, ...}
        """
        from backend.domain.samba.proxy.naverstore_sourcing import (
            NaverStoreSourcingClient,
        )

        client = NaverStoreSourcingClient()
        return await self.safe_call(
            client.get_store_products(
                store_url,
                page=page,
                page_size=page_size,
                sort_type=sort,
            )
        )

    async def refresh(self, product, **kwargs) -> "RefreshResult":
        """가격/재고 갱신 — 상세 API 재조회로 최신 데이터 추출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.naverstore_sourcing import (
            NaverStoreSourcingClient,
        )

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )
        source_url = getattr(product, "source_url", "") or getattr(
            product, "sourceUrl", ""
        )

        lookup_key = source_url if source_url else site_product_id
        if not lookup_key:
            return RefreshResult(
                product_id=product_id,
                error="네이버스토어 상품 ID/URL 없음",
            )

        try:
            client = NaverStoreSourcingClient()
            cookies = kwargs.get("cookies") if kwargs else None
            detail = await self.safe_call(
                client.get_product_detail(lookup_key, cookies=cookies)
            )

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"네이버스토어 상세 조회 실패: {lookup_key}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isSoldOut", False)

            # 옵션 데이터 변환
            new_options = None
            raw_combos = detail.get("optionCombinations", [])
            if raw_combos:
                new_options = [
                    {
                        "name": combo.get("displayName", ""),
                        "price": combo.get("additionalPrice", 0),
                        "stock": combo.get("stockQuantity", 0),
                        "isSoldOut": combo.get("isSoldOut", False),
                    }
                    for combo in raw_combos
                ]

            from backend.domain.samba.collector.refresher import (
                count_stock_transitions,
            )

            old_options_ns = getattr(product, "options", None) or []
            _stock_changes = count_stock_transitions(old_options_ns, new_options or [])
            old_sale = getattr(product, "sale_price", 0) or 0
            old_status = getattr(product, "sale_status", "in_stock")
            new_sale_status = "sold_out" if is_sold_out else "in_stock"
            changed = (float(new_sale_price or 0) != float(old_sale or 0)) or (
                new_sale_status != old_status
            )

            return RefreshResult(
                product_id=product_id,
                new_sale_price=(float(new_sale_price) if new_sale_price else None),
                new_original_price=(
                    float(new_original_price) if new_original_price else None
                ),
                new_sale_status=new_sale_status,
                new_options=new_options,
                new_images=detail.get("images"),
                changed=changed,
                stock_changed=_stock_changes > 0,
            )

        except Exception as e:
            logger.error(f"[NAVERSTORE] 갱신 실패: {lookup_key} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"네이버스토어 갱신 실패: {e}",
            )

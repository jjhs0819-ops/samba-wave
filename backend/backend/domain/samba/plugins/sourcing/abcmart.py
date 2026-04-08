"""ABC마트 소싱처 플러그인.

ABC마트와 그랜드스테이지는 동일 도메인(www.a-rt.com)의 동일 구조 사이트이므로,
ABC마트 검색 시 그랜드스테이지 상품도 함께 수집하여 반환한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class AbcMartPlugin(SourcingPlugin):
    """ABC마트 소싱처 플러그인.

    search() 호출 시 ABC마트 + 그랜드스테이지 양쪽을 병렬 검색하여
    결과를 병합해 반환한다 (교차 수집).

    concurrency=3: 두 사이트 동시 요청을 고려한 세마포어
    request_interval=0.5: 요청 간 500ms 딜레이
    """

    site_name = "ABCmart"
    concurrency = 3
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """ABC마트 + 그랜드스테이지 병렬 검색 후 결과 병합.

        두 사이트의 결과를 합쳐 중복(siteProductId 기준)을 제거한 뒤 반환한다.
        """
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        abc_client = ARTSourcingClient(channel=None)  # ABC마트
        gs_client = ARTSourcingClient(channel="10002")  # 그랜드스테이지

        page = filters.get("page", 1)
        size = filters.get("size", 40)

        abc_results, gs_results = await asyncio.gather(
            self.safe_call(abc_client.search_products(keyword, page=page, size=size)),
            self.safe_call(gs_client.search_products(keyword, page=page, size=size)),
            return_exceptions=True,
        )

        # 예외 발생 시 빈 리스트로 대체
        if isinstance(abc_results, Exception):
            logger.warning(f"[ABCmart] 검색 실패 (ABC마트): {abc_results}")
            abc_results = []
        if isinstance(gs_results, Exception):
            logger.warning(f"[ABCmart] 검색 실패 (그랜드스테이지): {gs_results}")
            gs_results = []

        # 중복 제거 (ABC마트 우선, 동일 prdtNo는 첫 번째 것만 유지)
        seen: set[str] = set()
        merged: list[dict] = []
        for item in list(abc_results) + list(gs_results):
            pid = item.get("siteProductId") or item.get("goodsNo", "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            merged.append(item)

        logger.info(
            f"[ABCmart] 검색 병합 완료: '{keyword}' "
            f"ABC마트 {len(abc_results)}개 + 그랜드스테이지 {len(gs_results)}개 "
            f"→ 총 {len(merged)}개"
        )
        return merged

    async def scan_categories(self, keyword: str) -> dict:
        """ABC마트 + 그랜드스테이지 카테고리 스캔 후 병합."""
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        abc_client = ARTSourcingClient(channel=None)  # ABC마트
        gs_client = ARTSourcingClient(channel="10002")  # 그랜드스테이지

        abc_result, gs_result = await asyncio.gather(
            self.safe_call(abc_client.scan_categories(keyword)),
            self.safe_call(gs_client.scan_categories(keyword)),
            return_exceptions=True,
        )

        if isinstance(abc_result, Exception):
            logger.warning(f"[ABCmart] 카테고리 스캔 실패 (ABC마트): {abc_result}")
            abc_result = {"categories": [], "total": 0, "groupCount": 0}
        if isinstance(gs_result, Exception):
            logger.warning(
                f"[ABCmart] 카테고리 스캔 실패 (그랜드스테이지): {gs_result}"
            )
            gs_result = {"categories": [], "total": 0, "groupCount": 0}

        # 카테고리 병합 (같은 path는 count 합산)
        merged: dict[str, dict] = {}
        for cat in abc_result.get("categories", []) + gs_result.get("categories", []):
            path = cat.get("path", "")
            if path in merged:
                merged[path]["count"] += cat.get("count", 0)
            else:
                merged[path] = {**cat}

        categories = sorted(merged.values(), key=lambda x: -x.get("count", 0))
        total = sum(c.get("count", 0) for c in categories)

        logger.info(
            f"[ABCmart] 카테고리 스캔 병합 완료: '{keyword}' "
            f"→ {len(categories)}개 카테고리, 총 {total}건"
        )
        return {
            "categories": list(categories),
            "total": total,
            "groupCount": len(categories),
        }

    async def get_detail(self, site_product_id: str) -> dict:
        """ABC마트 상품 상세 조회."""
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        client = ARTSourcingClient(channel=None)
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고/상세 갱신 — ARTSourcingClient 직접 API 호출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="ABCmart 상품 ID 없음",
            )

        try:
            client = ARTSourcingClient(channel=None)
            detail = await self.safe_call(
                client.get_product_detail(site_product_id, refresh_only=True)
            )

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"ABCmart 상세 조회 실패: {site_product_id}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isOutOfStock", False)
            best_benefit_price = detail.get("bestBenefitPrice", 0)

            # API에서 쿠폰+멤버십 모두 계산하므로 확장앱 불필요
            logger.info(
                f"[ABCmart] API 최대혜택가: {site_product_id} → {best_benefit_price:,}원, "
                f"옵션={len(detail.get('options', []))}개"
            )

            # 옵션 데이터 변환
            new_options = None
            raw_options = detail.get("options", [])
            if raw_options:
                new_options = [
                    {
                        "name": opt.get("name", ""),
                        "price": opt.get("price", 0),
                        "stock": 0 if opt.get("isSoldOut") else opt.get("stock", 1),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status="sold_out" if is_sold_out else "in_stock",
                new_options=new_options,
                new_images=detail.get("images"),
                new_free_shipping=detail.get("freeShipping"),
                changed=True,
            )

        except Exception as e:
            logger.error(f"[ABCmart] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"ABCmart 갱신 실패: {e}",
            )

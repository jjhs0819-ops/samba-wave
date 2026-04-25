"""그랜드스테이지 소싱처 플러그인.

그랜드스테이지와 ABC마트는 동일 도메인(www.a-rt.com)의 동일 구조 사이트이므로,
그랜드스테이지 검색 시 ABC마트 상품도 함께 수집하여 반환한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class GrandStagePlugin(SourcingPlugin):
    """그랜드스테이지 소싱처 플러그인.

    search() 호출 시 그랜드스테이지 + ABC마트 양쪽을 병렬 검색하여
    결과를 병합해 반환한다 (교차 수집).

    concurrency=3: 두 사이트 동시 요청을 고려한 세마포어
    request_interval=0.5: 요청 간 500ms 딜레이
    """

    site_name = "GrandStage"
    concurrency = 3
    request_interval = 0.5

    async def search(self, keyword: str, **filters) -> list[dict]:
        """그랜드스테이지 + ABC마트 병렬 검색 후 결과 병합.

        두 사이트의 결과를 합쳐 중복(siteProductId 기준)을 제거한 뒤 반환한다.
        """
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        gs_client = ARTSourcingClient(channel="10002")  # 그랜드스테이지
        abc_client = ARTSourcingClient(channel=None)  # ABC마트

        page = filters.get("page", 1)
        size = filters.get("size", 40)

        gs_results, abc_results = await asyncio.gather(
            self.safe_call(gs_client.search_products(keyword, page=page, size=size)),
            self.safe_call(abc_client.search_products(keyword, page=page, size=size)),
            return_exceptions=True,
        )

        # 예외 발생 시 빈 리스트로 대체
        if isinstance(gs_results, Exception):
            logger.warning(f"[GrandStage] 검색 실패 (그랜드스테이지): {gs_results}")
            gs_results = []
        if isinstance(abc_results, Exception):
            logger.warning(f"[GrandStage] 검색 실패 (ABC마트): {abc_results}")
            abc_results = []

        # 중복 제거 (그랜드스테이지 우선, 동일 prdtNo는 첫 번째 것만 유지)
        seen: set[str] = set()
        merged: list[dict] = []
        for item in list(gs_results) + list(abc_results):
            pid = item.get("siteProductId") or item.get("goodsNo", "")
            if pid and pid in seen:
                continue
            if pid:
                seen.add(pid)
            merged.append(item)

        logger.info(
            f"[GrandStage] 검색 병합 완료: '{keyword}' "
            f"그랜드스테이지 {len(gs_results)}개 + ABC마트 {len(abc_results)}개 "
            f"→ 총 {len(merged)}개"
        )
        return merged

    async def get_detail(self, site_product_id: str) -> dict:
        """그랜드스테이지 상품 상세 조회."""
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        client = ARTSourcingClient(channel="10002")
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — 상세 페이지 재조회로 최신 데이터 추출."""
        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.abcmart import ARTSourcingClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="GrandStage 상품 ID 없음",
            )

        try:

            async def _fetch(channel: str | None) -> dict:
                _client = ARTSourcingClient(channel=channel)
                return await self.safe_call(
                    _client.get_product_detail(site_product_id, refresh_only=True)
                )

            detail = await _fetch("10002")

            # GrandStage 채널 응답이 비거나 sale_price=0이면 ABCmart 채널 폴백
            _needs_fallback = (
                not detail
                or detail.get("__product_not_found__")
                or int(detail.get("salePrice", 0) or 0) <= 0
            )
            if _needs_fallback:
                logger.info(
                    f"[GrandStage] 채널 폴백: {site_product_id} (10002 → 10001)"
                )
                _alt = await _fetch(None)
                if _alt and not _alt.get("__product_not_found__"):
                    if int(_alt.get("salePrice", 0) or 0) > 0:
                        detail = _alt

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"GrandStage 상세 조회 실패: {site_product_id}",
                )
            if detail.get("__product_not_found__"):
                logger.warning(
                    f"[GrandStage] 소싱처 삭제 감지(판매종료) — 품절 처리: {site_product_id}"
                )
                return RefreshResult(
                    product_id=product_id,
                    new_sale_status="sold_out",
                    changed=True,
                    deleted_from_source=True,
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isOutOfStock", False)
            best_benefit_price = detail.get("bestBenefitPrice", 0)
            # 옵션 데이터 변환
            new_options = None
            raw_options = detail.get("options", [])
            if raw_options:
                new_options = [
                    {
                        "name": opt.get("name", ""),
                        "price": opt.get("price", 0),
                        "stock": 0
                        if opt.get("isSoldOut")
                        else (opt.get("stock") or 99),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            from backend.domain.samba.collector.refresher import (
                count_stock_transitions,
            )

            old_options_gs = getattr(product, "options", None) or []
            _stock_changes = count_stock_transitions(old_options_gs, new_options or [])
            old_sale = getattr(product, "sale_price", 0) or 0
            old_status = getattr(product, "sale_status", "in_stock")
            new_sale_status = "sold_out" if is_sold_out else "in_stock"
            changed = (float(new_sale_price or 0) != float(old_sale or 0)) or (
                new_sale_status != old_status
            )

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status=new_sale_status,
                new_options=new_options,
                new_images=detail.get("images"),
                new_free_shipping=detail.get("freeShipping"),
                changed=changed,
                stock_changed=_stock_changes > 0,
            )

        except Exception as e:
            logger.error(f"[GrandStage] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"GrandStage 갱신 실패: {e}",
            )

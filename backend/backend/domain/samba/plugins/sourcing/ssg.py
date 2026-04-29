"""SSG(신세계몰) 소싱처 플러그인."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class SSGPlugin(SourcingPlugin):
    """SSG 소싱처 플러그인.

    SSG(신세계몰)는 robots.txt가 엄격하므로 보수적 간격으로 요청한다.
    bestBenefitPrice(최대혜택가)를 new_cost에 반영하여
    정책 적용 시 실질 매입가 기준으로 마진 계산이 가능하다.

    concurrency=1: 차단 강도가 높아 동시 1개만 요청
    request_interval=1.0: 요청 간 1초 딜레이 (보수적)
    """

    site_name = "SSG"
    concurrency = 1
    request_interval = 1.0

    async def search(self, keyword: str, **filters) -> list[dict]:
        """SSG 키워드 검색."""
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        client = SSGSourcingClient()
        page = filters.get("page", 1)
        size = filters.get("size", 40)
        return await self.safe_call(
            client.search_products(keyword, page=page, size=size, **filters)
        )

    async def scan_categories(
        self,
        keyword: str,
        *,
        selected_brands: list[str] | None = None,
        brand_ids: list[str] | None = None,
        brand_total: int = 0,
        log_fn=None,
        proxy_urls: list[str] | None = None,
    ) -> dict:
        """SSG 카테고리 스캔 — categoryFilter 트리 플래튼 또는 상품 샘플링."""
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        client = SSGSourcingClient()
        return await client.scan_categories(
            keyword,
            selected_brands=selected_brands,
            brand_ids=brand_ids,
            brand_total=brand_total,
            log_fn=log_fn,
            proxy_urls=proxy_urls,
        )

    async def discover_brands(self, keyword: str) -> dict:
        """SSG 브랜드 탐색 — brandFilter에서 브랜드 목록 추출."""
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        client = SSGSourcingClient()
        return await client.discover_brands(keyword)

    async def get_detail(self, site_product_id: str) -> dict:
        """SSG 상품 상세 조회."""
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        client = SSGSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — SSG 서버사이드 차단 우회를 위해 확장앱 SourcingQueue 위임."""
        import asyncio

        from backend.domain.samba.collector.refresher import RefreshResult
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
        from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="SSG 상품 ID 없음",
            )

        try:
            client = SSGSourcingClient()
            detail: dict = {}

            # SSG는 서버사이드 직접 HTTP 차단 → 확장앱 위임 (worker.py 동일 패턴)
            # 타임아웃 60초: 병렬 처리(3개 탭) + reCAPTCHA/AJAX 지연을 감안해 충분한 여유 확보
            # 호출 컨텍스트에 따라 owner 분기:
            #   - manual(상품관리 업데이트 버튼) → owner_device_id="" (어느 PC든 처리 가능)
            #   - autotune/transmit → None(=오토튠 글로벌 owner) → 실행 PC 1대만 처리
            #     → 모든 PC 확장앱이 동시에 SSG 탭 여는 현상 방지
            from backend.domain.samba.collector.refresher import (
                _current_refresh_source,
            )

            _owner = "" if _current_refresh_source.get() == "manual" else None
            _req_id, _future = SourcingQueue.add_detail_job(
                "SSG", site_product_id, owner_device_id=_owner
            )
            _ext_result = await asyncio.wait_for(_future, timeout=60)

            if isinstance(_ext_result, dict) and _ext_result.get("success"):
                _html = _ext_result.get("html", "")
                if _html:
                    detail = (
                        client._parse_result_item_obj(_html, site_product_id, True)
                        or {}
                    )
                # _parse_result_item_obj 실패 시 (dept.ssg.com AJAX 로드): resultItemObj 폴백
                if not detail:
                    _ext_obj = _ext_result.get("resultItemObj", {})
                    _item_nm = _ext_obj.get("itemNm", "")
                    if _item_nm and _html:
                        _opts = client._parse_select_options(_html)
                        _sold = (
                            all(o.get("isSoldOut", False) for o in _opts)
                            if _opts
                            else False
                        )
                        _sell = int(_ext_obj.get("sellprc", 0) or 0)
                        _best = int(_ext_obj.get("bestAmt", 0) or 0) or _sell
                        for _opt in _opts:
                            if not _opt.get("price"):
                                _opt["price"] = _sell
                        detail = {
                            "salePrice": _sell,
                            "originalPrice": _sell,
                            "bestBenefitPrice": _best,
                            "options": _opts,
                            "isOutOfStock": _sold,
                            "isSoldOut": _sold,
                        }
                # domOptions(JS 렌더링 후 DOM 파싱) 또는 uitemOptions로 실재고 보정
                _uitem_opts = _ext_result.get("uitemOptions", [])
                _dom_opts = _ext_result.get("domOptions", [])
                if detail.get("options"):
                    if _dom_opts:
                        # DOM 파싱 결과 우선 — "남은수량 N" 실재고 반영
                        _dom_map = {o["name"]: o for o in _dom_opts if o.get("name")}
                        for _opt in detail["options"]:
                            _dom = _dom_map.get(_opt.get("name", ""))
                            if _dom:
                                if _dom.get("isSoldOut"):
                                    _opt["isSoldOut"] = True
                                    _opt["stock"] = 0
                                elif _dom.get("stock") is not None:
                                    _opt["isSoldOut"] = False
                                    _opt["stock"] = _dom["stock"]
                    elif _uitem_opts:
                        # DOM 파싱 없을 때 uitemOptions의 usablInvQty 폴백
                        _stock_map = {
                            o["name"]: o for o in _uitem_opts if o.get("name")
                        }
                        for _opt in detail["options"]:
                            _u = _stock_map.get(_opt.get("name", ""))
                            if _u:
                                _qty = _u.get("usablInvQty", 0)
                                _opt["isSoldOut"] = _qty == 0
                                _opt["stock"] = _qty if _qty > 0 else 0

            if not detail:
                return RefreshResult(
                    product_id=product_id,
                    error=f"SSG 상세 조회 실패 (확장앱 미응답 또는 파싱 실패): {site_product_id}",
                )

            new_sale_price = detail.get("salePrice", 0)
            new_original_price = detail.get("originalPrice", 0)
            is_sold_out = detail.get("isOutOfStock", False) or detail.get(
                "isSoldOut", False
            )

            # bestBenefitPrice → new_cost (실질 매입가)
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
                        else (opt.get("stock") if opt.get("stock") is not None else 99),
                        "isSoldOut": opt.get("isSoldOut", False),
                    }
                    for opt in raw_options
                ]

            # 변동/재고변동 정확 판정 — 옵션별 0 경계 전환을 stock_changed로 인정
            from backend.domain.samba.collector.refresher import (
                count_stock_transitions,
            )

            old_options_ssg = getattr(product, "options", None) or []
            _stock_changes = count_stock_transitions(old_options_ssg, new_options or [])
            old_sale = getattr(product, "sale_price", 0) or 0
            old_status = getattr(product, "sale_status", "in_stock")
            new_sale_status = "sold_out" if is_sold_out else "in_stock"
            changed = (float(new_sale_price or 0) != float(old_sale or 0)) or (
                new_sale_status != old_status
            )

            # 수집 시점 retry 경로 버그로 name/brand 가 빈 문자열인 상품 백필용.
            # detail 에서 추출한 값을 RefreshResult 에 담아 enrich 가 조건부 적용.
            _det_name = detail.get("name") or detail.get("itemNm") or None
            _det_brand = detail.get("brand") or detail.get("repBrandNm") or None
            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status=new_sale_status,
                new_options=new_options,
                new_name=_det_name,
                new_brand=_det_brand,
                new_images=detail.get("images"),
                new_detail_images=detail.get("detailImages"),
                new_free_shipping=detail.get("freeShipping"),
                new_same_day_delivery=detail.get("sameDayDelivery"),
                changed=changed,
                stock_changed=_stock_changes > 0,
            )

        except asyncio.TimeoutError:
            logger.warning(
                f"[SSG] 갱신 타임아웃 60초 (큐 적체/미연결): {site_product_id}"
            )
            return RefreshResult(
                product_id=product_id,
                error=f"SSG 갱신 타임아웃 60초 (확장앱 큐 적체 또는 미연결): {site_product_id}",
            )
        except Exception as e:
            logger.error(f"[SSG] 갱신 실패: {site_product_id} — {e}")
            return RefreshResult(
                product_id=product_id,
                error=f"SSG 갱신 실패: {e}",
            )

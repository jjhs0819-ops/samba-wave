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
            # owner_device_id 미전달 → SourcingQueue가 _autotune_owner_device_id(글로벌) 폴백 →
            # 오토튠 가동 중에는 실행 개시 PC 확장앱에서만 탭이 열리고 다른 PC 는 로그만 보게 됨.
            # 이전엔 owner_device_id="" 로 강제해 어떤 PC든 탭이 열리는 누수가 있었으나
            # "실행 개시 PC 만 창" 요구사항과 충돌하여 제거함(2026-04-29).
            # SourcingQueue는 requestId 단위 단일 resolver라 콜백 중복 자체는 없음.
            _req_id, _future = SourcingQueue.add_detail_job("SSG", site_product_id)
            # 타임아웃 150s: 확장앱 슬롯 2개 × 아이템당 ~45s = 3배치 = 135s + 여유
            _ext_result = await asyncio.wait_for(_future, timeout=150)

            if isinstance(_ext_result, dict) and _ext_result.get("success"):
                _html = _ext_result.get("html", "")
                if _html:
                    detail = (
                        client._parse_result_item_obj(_html, site_product_id, True)
                        or {}
                    )
                # resultItemObj.sellprc/bestAmt = AJAX 실시간 값 (script 텍스트 파싱보다 정확)
                # _parse_result_item_obj가 성공해도 _extract_dept_sale_price/card 가격은
                # script 템플릿의 다른 상품 가격을 잡을 수 있으므로 항상 덮어씌운다.
                _rob = _ext_result.get("resultItemObj", {})
                _rob_sell = int(_rob.get("sellprc", 0) or 0)
                _rob_best = int(_rob.get("bestAmt", 0) or 0)
                _dom_card = int(_ext_result.get("domCardPrice", 0) or 0)
                if detail and _rob_sell > 0:
                    detail["salePrice"] = _rob_sell
                    # domCardPrice(DOM 직접 추출 카드혜택가) 최우선 — bestAmt 없는 상품 보정
                    if _dom_card > 0:
                        detail["bestBenefitPrice"] = _dom_card
                    elif not int(detail.get("bestBenefitPrice", 0) or 0):
                        detail["bestBenefitPrice"] = _rob_best or _rob_sell
                    _rob_orig = int(_rob.get("norprc", 0) or _rob.get("orgPrc", 0) or 0)
                    if _rob_orig > 0:
                        detail["originalPrice"] = _rob_orig

                # _parse_result_item_obj 실패 시 (dept.ssg.com AJAX 로드): resultItemObj 폴백
                if not detail:
                    _ext_obj = _ext_result.get("resultItemObj", {})
                    _item_nm = _ext_obj.get("itemNm", "")
                    if _item_nm and _html:
                        _opts = client._parse_layered_select_options(_html)
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
                    _has_layered_uitem_names = any(
                        "/" in str(o.get("name", "")) for o in _uitem_opts
                    )
                    _has_layered_detail_names = any(
                        "/" in str(o.get("name", "")) for o in detail["options"]
                    )
                    if (
                        _uitem_opts
                        and _has_layered_uitem_names
                        and (
                            not _has_layered_detail_names
                            or len(detail["options"]) < len(_uitem_opts)
                        )
                    ):
                        _price_fallback = int(detail.get("salePrice", 0) or 0)
                        detail["options"] = [
                            {
                                "name": _opt.get("name", ""),
                                "price": int(_opt.get("price", 0) or 0)
                                or _price_fallback,
                                "stock": _opt.get("usablInvQty", 0),
                                "isSoldOut": _opt.get("isSoldOut", False),
                            }
                            for _opt in _uitem_opts
                            if _opt.get("name")
                        ]
                    if _dom_opts:
                        # DOM 파싱 결과 우선 — "남은수량 N" 실재고 반영
                        _dom_map = {o["name"]: o for o in _dom_opts if o.get("name")}
                        if not any(
                            _name in _dom_map
                            for _name in (
                                _opt.get("name", "") for _opt in detail["options"]
                            )
                        ):
                            _prefixes = {
                                _name.split("/", 1)[0]
                                for _name in (
                                    _opt.get("name", "") for _opt in detail["options"]
                                )
                                if "/" in _name
                            }
                            if len(_prefixes) == 1:
                                _prefix = next(iter(_prefixes))
                                _dom_map = {
                                    f"{_prefix}/{_name}": _opt
                                    for _name, _opt in _dom_map.items()
                                }
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
                    _has_saleable_option = any(
                        (not _opt.get("isSoldOut", False))
                        and (_opt.get("stock") or 0) > 0
                        for _opt in detail["options"]
                    )
                    if _has_saleable_option:
                        detail["isOutOfStock"] = False
                        detail["isSoldOut"] = False
                    elif all(
                        _opt.get("isSoldOut", False) for _opt in detail["options"]
                    ):
                        detail["isOutOfStock"] = True
                        detail["isSoldOut"] = True

            if not detail:
                _ext_msg = ""
                if isinstance(_ext_result, dict) and not _ext_result.get("success"):
                    _ext_msg = (_ext_result.get("message") or "").strip()
                    if _ext_result.get("blocked"):
                        _ext_msg = "SSG 차단됨 (reCAPTCHA) — 잠시 후 재시도 해주세요"
                return RefreshResult(
                    product_id=product_id,
                    error=_ext_msg
                    or f"SSG 상세 조회 실패 (확장앱 미응답 또는 파싱 실패): {site_product_id}",
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
                        **{k: v for k, v in opt.items() if not str(k).startswith("_")},
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

            return RefreshResult(
                product_id=product_id,
                new_sale_price=float(new_sale_price) if new_sale_price else None,
                new_original_price=float(new_original_price)
                if new_original_price
                else None,
                new_cost=float(best_benefit_price) if best_benefit_price else None,
                new_sale_status=new_sale_status,
                new_options=new_options,
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

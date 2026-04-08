"""롯데ON 소싱처 플러그인."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing_base import SourcingPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)

# 롯데ON 소싱처 적응형 인터벌 상태
_lotteon_interval: float = 0.5  # 현재 인터벌 (초)
_lotteon_consecutive_errors: int = 0  # 연속 차단 횟수
_lotteon_safe_interval: float = 999.0  # 차단 없는 최소 인터벌 기록

# sitmNo 인메모리 캐시 — HTML 폴백 시 추출하여 다음 사이클부터 pbf 빠른경로 사용
# {site_product_id: sitmNo} 형태, 프로세스 수명 동안 유지
_sitm_no_cache: dict[str, str] = {}


class LotteonSourcingPlugin(SourcingPlugin):
    """롯데ON 소싱처 플러그인.

    JSON-LD(schema.org Product) 마크업을 우선 파싱하여 정확도가 높다.
    bestBenefitPrice(최대혜택가)를 new_cost에 반영하여
    정책 적용 시 실질 매입가 기준으로 마진 계산이 가능하다.

    concurrency=4: pbf API는 부하가 적어 동시 4건 처리
    request_interval=0.3: 요청 간 300ms 딜레이 (pbf 빠른경로 기준)
    """

    site_name = "LOTTEON"
    concurrency = 4
    request_interval = 0.3

    async def search(self, keyword: str, **filters) -> list[dict]:
        """롯데ON 키워드 검색."""
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        page = filters.get("page", 1)
        size = filters.get("size", 40)
        return await self.safe_call(
            client.search_products(keyword, page=page, size=size, **filters)
        )

    async def get_detail(self, site_product_id: str) -> dict:
        """롯데ON 상품 상세 조회."""
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        return await self.safe_call(client.get_product_detail(site_product_id))

    async def scan_categories(
        self,
        keyword: str,
        *,
        selected_brands: list[str] | None = None,
        max_scan: int = 20,
    ) -> dict:
        """롯데ON 카테고리 스캔 — 검색 결과에서 카테고리 분포 집계.

        safe_call() 미사용: scan_categories() 내부에서 asyncio.Semaphore(3)으로
        직접 동시성을 제어하므로 외부 세마포어 래핑이 불필요하다.
        """
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        return await client.scan_categories(
            keyword, selected_brands=selected_brands, max_scan=max_scan
        )

    async def discover_brands(self, keyword: str) -> dict:
        """롯데ON 키워드 검색 → 발견된 브랜드 목록 반환 (사용자 선택용)."""
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        return await client.discover_brands(keyword)

    async def _fetch_pbf_refresh(self, sitm_no: str) -> dict:
        """pbf API 직접 호출로 refresh용 데이터 취득 (HTML 파싱 스킵).

        Args:
          sitm_no: 롯데ON sitmNo (LE1220156946_1321122096 형태)

        Returns:
          refresh용 detail dict (빈 dict이면 실패)
        """
        from backend.domain.samba.proxy.lotteon_sourcing import LotteonSourcingClient

        client = LotteonSourcingClient()
        pbf = await client.fetch_pbf_standalone(sitm_no)
        if not pbf:
            return {}
        return self._parse_pbf_to_detail(pbf)

    def _parse_pbf_to_detail(self, pbf: dict) -> dict:
        """pbf API 응답 → refresh용 detail dict 변환.

        get_product_detail()이 반환하는 dict와 동일한 키 구조로 변환한다.
        """
        price_info = pbf.get("priceInfo") or {}
        sl_prc = int(price_info.get("slPrc", 0) or 0)
        immd_dc = int(price_info.get("immdDcAplyTotAmt", 0) or 0)
        adtn_dc = int(price_info.get("adtnDcAplyTotAmt", 0) or 0)

        if immd_dc > 0 or adtn_dc > 0:
            # PBF에 할인 정보 있음 → 최대혜택가 계산
            best_benefit = sl_prc - immd_dc - adtn_dc if sl_prc > 0 else 0
            if best_benefit <= 0 or best_benefit >= sl_prc:
                best_benefit = sl_prc
        else:
            # PBF에 할인 정보 없음 → slPrc가 정상가(할인 전)일 수 있어
            # bestBenefitPrice를 None으로 설정하여 HTML 폴백 유도
            best_benefit = None

        # 재고
        stck = pbf.get("stckInfo") or {}
        stk_qty = stck.get("stkQty")
        is_out = stk_qty is not None and stk_qty == 0

        # 옵션
        opt_info = pbf.get("optionInfo") or {}
        option_groups = opt_info.get("optionList") or []
        options: list[dict] = []
        if option_groups:
            primary = option_groups[0]
            for opt in primary.get("options", []):
                label = opt.get("label", "").strip()
                if not label:
                    continue
                disabled = bool(opt.get("disabled", False))
                options.append(
                    {
                        "name": label,
                        "price": sl_prc,
                        "stock": 0 if disabled else (stk_qty or 1),
                        "isSoldOut": disabled,
                    }
                )
            if len(option_groups) >= 2:
                options = []
                for g1 in option_groups[0].get("options", []):
                    for g2 in option_groups[1].get("options", []):
                        dis = g1.get("disabled", False) or g2.get("disabled", False)
                        label = f"{g1.get('label', '')} / {g2.get('label', '')}".strip(
                            " /"
                        )
                        options.append(
                            {
                                "name": label,
                                "price": sl_prc,
                                "stock": 0 if dis else (stk_qty or 1),
                                "isSoldOut": bool(dis),
                            }
                        )

        return {
            "salePrice": sl_prc,
            "bestBenefitPrice": best_benefit,
            "isOutOfStock": is_out,
            "isSoldOut": is_out,
            "saleStatus": "sold_out" if is_out else "in_stock",
            "options": options,
        }

    async def refresh(self, product) -> "RefreshResult":
        """가격/재고 갱신 — sitmNo 있으면 pbf 직접, 없으면 상세 페이지 재조회.

        무신사 수준의 에러 처리 및 적응형 인터벌 조정을 포함한다:
        - 45초 타임아웃
        - RateLimitError 차단 감지 → 인터벌 2배 증가 (최대 30초)
        - 연속 5회 차단 시 전체 중단
        - retry_after 있으면 대기 후 1회 재시도
        - 성공 시 인터벌 점진 복원
        - 가격/재고 상태 변동 판정
        """
        global _lotteon_interval, _lotteon_consecutive_errors, _lotteon_safe_interval

        from backend.domain.samba.collector.refresher import RefreshResult, _log_refresh
        from backend.domain.samba.proxy.lotteon_sourcing import (
            LotteonSourcingClient,
            RateLimitError,
        )

        _idx = getattr(product, "_refresh_idx", 0)
        _total = getattr(product, "_refresh_total", 0)

        product_id = getattr(product, "id", "")
        site_product_id = getattr(product, "site_product_id", "") or getattr(
            product, "siteProductId", ""
        )

        if not site_product_id:
            return RefreshResult(
                product_id=product_id,
                error="롯데ON 상품 ID 없음",
            )

        client = LotteonSourcingClient()
        detail = None

        # sitmNo 빠른경로: product 객체 → 인메모리 캐시 순서로 조회
        # extra_data는 autotune에서 defer() 처리되어 접근 불가 (greenlet 에러)
        # 인메모리 캐시만 사용
        sitm_no = (
            getattr(product, "sitmNo", "")
            or getattr(product, "sitm_no", "")
            or _sitm_no_cache.get(site_product_id, "")
        )

        try:
            if sitm_no:
                # HTML 파싱 없이 pbf API 직접 호출
                raw = await asyncio.wait_for(
                    self._fetch_pbf_refresh(sitm_no),
                    timeout=20,
                )
                if raw:
                    # PBF에서 할인 정보를 못 가져온 경우(bestBenefitPrice=None)
                    # HTML 상세 페이지로 폴백하여 정확한 최대혜택가 확인
                    if raw.get("bestBenefitPrice") is None:
                        logger.debug(
                            f"[LOTTEON] PBF 할인 미반영, HTML 폴백: {site_product_id}"
                        )
                        html_detail = await asyncio.wait_for(
                            client.get_product_detail(site_product_id),
                            timeout=45,
                        )
                        if html_detail:
                            # HTML에서 재고/옵션은 PBF가 더 정확하므로 병합
                            for k in (
                                "isOutOfStock",
                                "isSoldOut",
                                "saleStatus",
                                "options",
                            ):
                                if k in raw and raw[k] is not None:
                                    html_detail[k] = raw[k]
                            detail = html_detail
                        else:
                            detail = raw
                    else:
                        detail = raw
                    logger.debug(
                        f"[LOTTEON] refresh 빠른경로 성공: {site_product_id} (sitmNo={sitm_no})"
                    )
                else:
                    # pbf 실패 → 기존 방식 폴백
                    logger.debug(
                        f"[LOTTEON] pbf 빠른경로 실패, 폴백: {site_product_id}"
                    )
                    detail = await asyncio.wait_for(
                        client.get_product_detail(site_product_id),
                        timeout=45,
                    )
            else:
                detail = await asyncio.wait_for(
                    client.get_product_detail(site_product_id),
                    timeout=45,
                )
                # HTML 폴백 성공 시 sitmNo 추출 → 인메모리 캐시 저장
                # 다음 사이클부터 pbf 빠른경로 사용
                if detail:
                    _extracted_sitm = detail.get("sitmNo", "")
                    if _extracted_sitm and site_product_id:
                        _sitm_no_cache[site_product_id] = _extracted_sitm
                        logger.info(
                            f"[LOTTEON] sitmNo 캐시 저장: {site_product_id} → {_extracted_sitm}"
                        )
            # 성공 → 인터벌 점진 복원 (최소 0.3초까지)
            _lotteon_interval = max(0.3, _lotteon_interval - 0.3)
            _lotteon_consecutive_errors = 0
            if _lotteon_interval <= _lotteon_safe_interval:
                _lotteon_safe_interval = _lotteon_interval

        except RateLimitError as e:
            # 차단 → 인터벌 2배 증가 (최대 30초)
            _lotteon_interval = min(30.0, _lotteon_interval * 2)
            _lotteon_consecutive_errors += 1
            _log_refresh(
                "LOTTEON",
                product_id,
                getattr(product, "name", ""),
                f"차단 HTTP {e.status} (연속 {_lotteon_consecutive_errors}회, 인터벌→{_lotteon_interval:.1f}s)",
                level="warning",
                idx=_idx,
                total=_total,
            )

            # 연속 5회 이상이면 해당 소싱처 전체 일시 중단
            if _lotteon_consecutive_errors >= 5:
                _log_refresh(
                    "LOTTEON",
                    product_id,
                    getattr(product, "name", ""),
                    f"연속 {_lotteon_consecutive_errors}회 차단 — 일시 중단",
                    level="error",
                    idx=_idx,
                    total=_total,
                )
                return RefreshResult(
                    product_id=product_id,
                    error=f"차단 감지: HTTP {e.status} (연속 {_lotteon_consecutive_errors}회, "
                    f"인터벌 {_lotteon_interval}초)",
                )

            # retry_after 있으면 대기 후 1회 재시도
            if e.retry_after > 0:
                logger.warning(
                    f"[LOTTEON] {site_product_id} 차단({e.status}), {e.retry_after}초 후 재시도"
                )
                await asyncio.sleep(e.retry_after)
                try:
                    detail = await client.get_product_detail(site_product_id)
                    _lotteon_consecutive_errors = 0
                    _log_refresh(
                        "LOTTEON",
                        product_id,
                        getattr(product, "name", ""),
                        f"재시도 성공 (대기 {e.retry_after}s 후)",
                        idx=_idx,
                        total=_total,
                    )
                except Exception:
                    _log_refresh(
                        "LOTTEON",
                        product_id,
                        getattr(product, "name", ""),
                        f"재시도 실패: HTTP {e.status}",
                        level="error",
                        idx=_idx,
                        total=_total,
                    )
                    return RefreshResult(
                        product_id=product_id,
                        error=f"차단 후 재시도 실패: HTTP {e.status}",
                    )
            else:
                return RefreshResult(
                    product_id=product_id, error=f"차단: HTTP {e.status}"
                )

        except asyncio.TimeoutError:
            # 45초 안에 응답 없음 → 건너뛰기
            _log_refresh(
                "LOTTEON",
                product_id,
                getattr(product, "name", ""),
                "응답 없음 (45초 타임아웃) — 건너뜀",
                level="warning",
                idx=_idx,
                total=_total,
            )
            return RefreshResult(
                product_id=product_id, error="응답 없음: 45초 타임아웃"
            )

        except Exception as e:
            logger.error(f"[LOTTEON] 갱신 실패: {site_product_id} — {e}")
            _log_refresh(
                "LOTTEON",
                product_id,
                getattr(product, "name", ""),
                f"실패 — {e}",
                level="error",
                idx=_idx,
                total=_total,
            )
            return RefreshResult(product_id=product_id, error=f"롯데ON API 오류: {e}")

        if not detail:
            return RefreshResult(
                product_id=product_id,
                error=f"롯데ON 상세 조회 실패: {site_product_id}",
            )

        # ── qapi 프로모션가 보정 ──
        # pbf API의 slPrc는 정가(할인 전)를 반환하므로,
        # qapi 검색의 priceInfo[type=final]로 실제 프로모션가를 조회하여 보정
        _pbf_sale = detail.get("salePrice") or 0
        _name = getattr(product, "name", "") or ""
        try:
            from backend.domain.samba.proxy.lotteon_sourcing import (
                LotteonSourcingClient as _QClient,
            )

            _qapi_price = await _QClient().fetch_qapi_price(site_product_id)
            if _qapi_price:
                _final = _qapi_price.get("final", 0)
                _original = _qapi_price.get("original", 0)
                _card_pct = _qapi_price.get("card_discount", 0)
                if _final > 0 and _final < _pbf_sale:
                    detail["salePrice"] = _final
                    detail["bestBenefitPrice"] = (
                        round(_final * (1 - _card_pct / 100))
                        if _card_pct > 0
                        else _final
                    )
                    if _original > 0:
                        detail["originalPrice"] = _original
                    logger.info(
                        f"[LOTTEON] qapi 프로모션가 보정: {site_product_id} "
                        f"pbf={_pbf_sale:,} → final={_final:,}, "
                        f"benefit={detail['bestBenefitPrice']:,}"
                    )
        except Exception as e:
            logger.debug(
                f"[LOTTEON] qapi 프로모션가 조회 실패: {site_product_id} — {e}"
            )

        # ── 데이터 추출 ──
        new_sale_price = detail.get("salePrice") or 0
        new_original_price = detail.get("originalPrice") or 0
        best_benefit_price = detail.get("bestBenefitPrice")
        if best_benefit_price is not None and best_benefit_price <= 0:
            best_benefit_price = None

        is_sold_out = detail.get("isOutOfStock", False) or detail.get(
            "isSoldOut", False
        )
        new_sale_status = "sold_out" if is_sold_out else "in_stock"

        # 옵션 데이터 변환
        new_options = None
        raw_options = detail.get("options") or []
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

        # ── 변동 판정 ──
        old_sale = getattr(product, "sale_price", 0) or 0
        old_status = getattr(product, "sale_status", "in_stock")
        changed = new_sale_price != old_sale or new_sale_status != old_status

        # 옵션 재고 변동 건수
        old_options = getattr(product, "options", None) or []
        _stock_changes = 0
        if new_options and old_options:
            old_stock_map = {o.get("name", ""): o.get("stock", 0) for o in old_options}
            for o in new_options:
                if o.get("stock", 0) != old_stock_map.get(o.get("name", ""), 0):
                    _stock_changes += 1

        # ── 갱신 로그 ──
        _name = getattr(product, "name", "") or ""
        _prod_label = f"{_name} ({site_product_id})" if site_product_id else _name
        _status_label = "전송" if (changed or _stock_changes > 0) else "스킵"
        _log_refresh(
            "LOTTEON",
            product_id,
            _prod_label,
            f"{_status_label} [원가 {int(old_sale):,}→{int(new_sale_price):,}, "
            f"상태 {old_status}→{new_sale_status}, 재고변동 {_stock_changes}건]",
            idx=_idx,
            total=_total,
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
            new_images=detail.get("images") or None,
            new_detail_images=detail.get("detailImages") or None,
            new_free_shipping=detail.get("freeShipping"),
            new_same_day_delivery=detail.get("sameDayDelivery"),
            changed=changed,
            stock_changed=_stock_changes > 0,
        )

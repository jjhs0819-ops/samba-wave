"""소싱처별 가격/재고 재수집 모듈.

서버에서 직접 HTTP 요청으로 최신 가격/품절 상태를 추출한다.
KREAM은 확장앱 큐(KreamClient.collect_queue)를 통해 자동 수집.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.utils.logger import logger

# 소싱처당 동시 요청 제한 (기본값)
CONCURRENCY_PER_SITE = 5
# 소싱처별 동시 요청 수 (개별 설정)
SITE_CONCURRENCY: dict[str, int] = {
    "MUSINSA": 8,
}
# 소싱처별 기본 인터벌 (초)
SITE_BASE_INTERVAL: dict[str, float] = {
    "MUSINSA": 0.5,
}
# 소싱처별 최소 인터벌 (초)
SITE_MIN_INTERVAL: dict[str, float] = {
    "MUSINSA": 0.3,
}
# 소싱처별 인터벌 복원 스텝 (성공 시 감소량)
SITE_INTERVAL_STEP: dict[str, float] = {
    "MUSINSA": 0.2,
}
# KREAM 확장앱 대기 타임아웃 (초)
KREAM_TIMEOUT = 90
# 소싱처별 적응형 인터벌 관리
_site_intervals: dict[str, float] = {}
_site_consecutive_errors: dict[str, int] = {}
# 소싱처별 안전 인터벌 기록 (차단 안 당하는 최소값)
_site_safe_intervals: dict[str, float] = {}

# ── 실시간 로그 링 버퍼 (최대 300건) ──
_refresh_log_buffer: deque[Dict[str, Any]] = deque(maxlen=300)


def _log_refresh(
    site: str,
    product_id: str,
    product_name: str = "",
    message: str = "",
    level: str = "info",
) -> None:
    """갱신 로그를 링 버퍼에 추가."""
    _refresh_log_buffer.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "site": site,
        "product_id": product_id,
        "name": product_name[:40] if product_name else "",
        "msg": message,
        "level": level,
    })


def get_refresh_logs(since_idx: int = 0) -> tuple[List[Dict[str, Any]], int]:
    """로그 조회. since_idx 이후 로그만 반환 + 현재 인덱스."""
    logs = list(_refresh_log_buffer)
    current_idx = len(logs)
    if since_idx > 0 and since_idx < current_idx:
        return logs[since_idx:], current_idx
    if since_idx >= current_idx:
        return [], current_idx
    return logs, current_idx


def get_site_intervals_info() -> Dict[str, Any]:
    """사이트별 인터벌 정보 (워룸 표시용)."""
    return {
        "intervals": dict(_site_intervals),
        "errors": dict(_site_consecutive_errors),
        "safe_intervals": dict(_site_safe_intervals),
        "concurrency": dict(SITE_CONCURRENCY),
        "base_intervals": dict(SITE_BASE_INTERVAL),
        "min_intervals": dict(SITE_MIN_INTERVAL),
    }


@dataclass
class RefreshResult:
    """단일 상품 갱신 결과."""
    product_id: str
    new_sale_price: Optional[float] = None
    new_original_price: Optional[float] = None
    new_cost: Optional[float] = None
    new_sale_status: str = "in_stock"  # in_stock / sold_out
    new_options: Optional[list] = None
    new_images: Optional[list] = None
    new_detail_images: Optional[list] = None
    new_material: Optional[str] = None
    new_color: Optional[str] = None
    new_free_shipping: Optional[bool] = None
    new_same_day_delivery: Optional[bool] = None
    changed: bool = False
    needs_extension: bool = False
    error: Optional[str] = None
    warnings: list = field(default_factory=list)


@dataclass
class BulkRefreshResult:
    """벌크 갱신 요약."""
    total: int = 0
    refreshed: int = 0
    changed: int = 0
    sold_out: int = 0
    retransmitted: int = 0
    needs_extension: list = field(default_factory=list)
    errors: int = 0


async def refresh_product(product: Any) -> RefreshResult:
    """소싱처에서 최신 가격/재고 재수집."""
    source_site = getattr(product, "source_site", "")

    # 소싱처별 파서 선택
    parser = SITE_PARSERS.get(source_site)
    if not parser:
        return RefreshResult(
            product_id=product.id,
            error=f"지원하지 않는 소싱처: {source_site}",
        )

    try:
        result = await parser(product)
        return result
    except Exception as e:
        logger.error(f"[refresher] {product.id} ({source_site}) 갱신 실패: {e}")
        return RefreshResult(
            product_id=product.id,
            error=str(e),
        )


# ── 무신사 파서 ──

async def _get_musinsa_cookie() -> str:
    """DB에서 무신사 쿠키 조회."""
    try:
        from backend.db.orm import get_read_session
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select
        async with get_read_session() as session:
            result = await session.execute(
                select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
            )
            row = result.scalar_one_or_none()
            return (row.value if row and row.value else "") or ""
    except Exception:
        return ""


async def _parse_musinsa(product: Any) -> RefreshResult:
    """무신사 상품 가격/재고 재수집 (MusinsaClient 활용)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError

    site_product_id = getattr(product, "site_product_id", None)
    if not site_product_id:
        return RefreshResult(product_id=product.id, error="site_product_id 없음")

    cookie = await _get_musinsa_cookie()
    client = MusinsaClient(cookie)
    warnings: list[str] = []

    try:
        detail = await client.get_goods_detail(site_product_id)
        # 성공 → 인터벌 점진 복원
        base = SITE_BASE_INTERVAL.get("MUSINSA", 1.0)
        min_iv = SITE_MIN_INTERVAL.get("MUSINSA", base)
        step = SITE_INTERVAL_STEP.get("MUSINSA", 0.5)
        prev_interval = _site_intervals.get("MUSINSA", base)
        new_interval = max(min_iv, prev_interval - step)
        _site_intervals["MUSINSA"] = new_interval
        _site_consecutive_errors["MUSINSA"] = 0
        # 차단 안 당하는 최소 인터벌 기록
        if new_interval <= _site_safe_intervals.get("MUSINSA", 999):
            _site_safe_intervals["MUSINSA"] = new_interval
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"조회 성공 (인터벌 {new_interval:.1f}s)",
        )
    except RateLimitError as e:
        # 차단 → 인터벌 2배 증가 (최대 30초)
        current = _site_intervals.get("MUSINSA", 1.0)
        _site_intervals["MUSINSA"] = min(30.0, current * 2)
        _site_consecutive_errors["MUSINSA"] = _site_consecutive_errors.get("MUSINSA", 0) + 1
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"차단 HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, 인터벌→{_site_intervals['MUSINSA']:.1f}s)",
            level="warning",
        )

        # 연속 5회 이상이면 해당 소싱처 전체 일시 중단
        if _site_consecutive_errors["MUSINSA"] >= 5:
            _log_refresh(
                "MUSINSA", product.id,
                getattr(product, "name", ""),
                f"연속 {_site_consecutive_errors['MUSINSA']}회 차단 — 일시 중단",
                level="error",
            )
            return RefreshResult(
                product_id=product.id,
                error=f"차단 감지: HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, "
                      f"인터벌 {_site_intervals['MUSINSA']}초)",
            )

        # Retry-After가 있으면 대기 후 1회 재시도
        if e.retry_after > 0:
            logger.warning(f"[refresher] {site_product_id} 차단({e.status}), {e.retry_after}초 후 재시도")
            await asyncio.sleep(e.retry_after)
            try:
                detail = await client.get_goods_detail(site_product_id)
                _site_consecutive_errors["MUSINSA"] = 0
                _log_refresh(
                    "MUSINSA", product.id,
                    getattr(product, "name", ""),
                    f"재시도 성공 (대기 {e.retry_after}s 후)",
                )
            except Exception:
                _log_refresh(
                    "MUSINSA", product.id,
                    getattr(product, "name", ""),
                    f"재시도 실패: HTTP {e.status}",
                    level="error",
                )
                return RefreshResult(product_id=product.id, error=f"차단 후 재시도 실패: HTTP {e.status}")
        else:
            return RefreshResult(product_id=product.id, error=f"차단: HTTP {e.status}")
    except Exception as e:
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"API 오류: {e}",
            level="error",
        )
        return RefreshResult(product_id=product.id, error=f"무신사 API 오류: {e}")

    new_sale_price = detail.get("salePrice", 0) or 0
    new_original_price = detail.get("originalPrice", 0) or 0
    new_cost = detail.get("bestBenefitPrice")
    if new_cost is not None and new_cost <= 0:
        new_cost = None
    new_sale_status = detail.get("saleStatus", "in_stock")
    new_options = detail.get("options")

    # 부분 성공 경고: 주요 필드 누락 감지
    if new_sale_price == 0 and new_original_price == 0:
        warnings.append("salePrice/originalPrice 모두 0 — 무신사 API 구조 변경 가능성")
    if detail.get("name") is None or detail.get("name") == "":
        warnings.append("goodsNm 필드 누락 — 무신사 API 구조 변경 가능성")

    # 경고가 있으면 모니터링 이벤트 발행 (fire-and-forget)
    if warnings:
        try:
            from backend.domain.samba.warroom.model import SambaMonitorEvent
            # 서비스 레이어 없이 직접 로그 — 세션이 없으므로 로그만 남김
            logger.warning(f"[refresher] API 구조 변경 감지: {warnings}")
        except Exception:
            pass

    # 변동 판정
    old_sale = getattr(product, "sale_price", 0) or 0
    old_original = getattr(product, "original_price", 0) or 0
    old_cost = getattr(product, "cost", None)
    old_status = getattr(product, "sale_status", "in_stock")

    changed = (
        new_sale_price != old_sale
        or new_original_price != old_original
        or new_cost != old_cost
        or new_sale_status != old_status
    )

    if changed:
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"변동 감지: 가격 {old_sale}→{new_sale_price}, 상태 {old_status}→{new_sale_status}",
        )

    # 이미지/소재/색상 (빈 값이 아닌 경우만 업데이트)
    new_images = detail.get("images") or None
    new_detail_images = detail.get("detailImages") or None
    new_material = detail.get("material") or None
    new_color = detail.get("color") or None

    return RefreshResult(
        product_id=product.id,
        new_sale_price=new_sale_price,
        new_original_price=new_original_price,
        new_cost=new_cost,
        new_sale_status=new_sale_status,
        new_options=new_options,
        new_images=new_images,
        new_detail_images=new_detail_images,
        new_material=new_material,
        new_color=new_color,
        new_free_shipping=detail.get("freeShipping", False),
        new_same_day_delivery=detail.get("sameDayDelivery", False),
        changed=changed,
        warnings=warnings,
    )


# ── KREAM 파서 (확장앱 큐 방식) ──

async def _parse_kream(product: Any) -> RefreshResult:
    """KREAM 상품 가격/재고 재수집 — 확장앱 큐를 통한 자동 수집.

    흐름:
    1. KreamClient.collect_queue에 job 등록
    2. 확장앱이 폴링으로 job을 가져감
    3. 확장앱이 KREAM 탭 열어서 데이터 수집
    4. 확장앱이 collect-result로 결과 전달
    5. asyncio.Future로 결과 수신
    """
    import uuid
    from backend.domain.samba.proxy.kream import KreamClient

    site_product_id = getattr(product, "site_product_id", None)
    if not site_product_id:
        return RefreshResult(product_id=product.id, error="site_product_id 없음")

    request_id = str(uuid.uuid4())
    url = f"https://kream.co.kr/products/{site_product_id}"

    # 큐에 job 등록
    KreamClient.collect_queue.append({
        "requestId": request_id,
        "productId": site_product_id,
        "url": url,
    })
    logger.info(f"[KREAM 갱신] 큐 등록: {site_product_id} ({request_id})")
    _log_refresh(
        "KREAM", product.id,
        getattr(product, "name", ""),
        f"확장앱 큐 등록: {site_product_id}",
    )

    # Future 생성 — 확장앱이 결과를 전달하면 resolve됨
    loop = asyncio.get_event_loop()
    future: asyncio.Future[Any] = loop.create_future()
    KreamClient.collect_resolvers[request_id] = future

    try:
        result = await asyncio.wait_for(future, timeout=KREAM_TIMEOUT)
    except asyncio.TimeoutError:
        KreamClient.collect_resolvers.pop(request_id, None)
        _log_refresh(
            "KREAM", product.id,
            getattr(product, "name", ""),
            f"확장앱 타임아웃 ({KREAM_TIMEOUT}초)",
            level="warning",
        )
        return RefreshResult(
            product_id=product.id,
            needs_extension=True,
            error=f"KREAM 확장앱 타임아웃 ({KREAM_TIMEOUT}초)",
        )

    # 결과 파싱
    if not isinstance(result, dict):
        return RefreshResult(product_id=product.id, error="KREAM 결과 형식 오류")

    ext_product = result.get("product", result)
    if not ext_product.get("success", True) if "success" in result else True:
        return RefreshResult(
            product_id=product.id,
            error=result.get("message", "KREAM 수집 실패"),
        )

    # 확장앱이 반환한 데이터에서 가격/옵션 추출
    new_options = ext_product.get("options", [])
    new_sale_price = ext_product.get("salePrice", 0) or 0
    new_original_price = ext_product.get("originalPrice", 0) or 0

    # 품절 판정: 재고 있는 옵션이 하나도 없으면 품절
    in_stock_count = sum(1 for o in new_options if o.get("stock", 0) > 0)
    new_sale_status = "sold_out" if (new_options and in_stock_count == 0) else "in_stock"

    # 변동 판정
    old_sale = getattr(product, "sale_price", 0) or 0
    old_original = getattr(product, "original_price", 0) or 0
    old_status = getattr(product, "sale_status", "in_stock")

    changed = (
        new_sale_price != old_sale
        or new_original_price != old_original
        or new_sale_status != old_status
    )

    msg = (
        f"완료: 가격 {old_sale}→{new_sale_price}, 상태 {old_status}→{new_sale_status}"
        + (", 변동 감지" if changed else "")
    )
    _log_refresh(
        "KREAM", product.id,
        getattr(product, "name", ""),
        msg,
    )
    logger.info(
        f"[KREAM 갱신] 완료: {site_product_id} "
        f"가격 {old_sale}→{new_sale_price}, 상태 {old_status}→{new_sale_status}, "
        f"변동={'Y' if changed else 'N'}"
    )

    return RefreshResult(
        product_id=product.id,
        new_sale_price=new_sale_price,
        new_original_price=new_original_price,
        new_sale_status=new_sale_status,
        new_options=new_options,
        changed=changed,
    )


# ── 범용 HTTP 파서 (ABCmart, Nike 등 — 현재 stub) ──

async def _parse_generic_stub(product: Any) -> RefreshResult:
    """범용 스텁 파서 — 실제 파싱은 소싱처별 HTML 구조에 맞게 확장 예정."""
    return RefreshResult(
        product_id=product.id,
        new_sale_price=getattr(product, "sale_price", 0),
        new_original_price=getattr(product, "original_price", 0),
        new_cost=getattr(product, "cost", None),
        new_sale_status=getattr(product, "sale_status", "in_stock"),
        changed=False,
    )


# 소싱처별 파서 매핑
SITE_PARSERS: dict[str, Any] = {
    "MUSINSA": _parse_musinsa,
    "KREAM": _parse_kream,
    "ABCmart": _parse_generic_stub,
    "Nike": _parse_generic_stub,
    "Adidas": _parse_generic_stub,
    "GrandStage": _parse_generic_stub,
    "OKmall": _parse_generic_stub,
    "LOTTEON": _parse_generic_stub,
    "GSShop": _parse_generic_stub,
    "ElandMall": _parse_generic_stub,
    "SSF": _parse_generic_stub,
    "FashionPlus": _parse_generic_stub,
}


async def refresh_products_bulk(
    products: List[Any],
) -> tuple[List[RefreshResult], BulkRefreshResult]:
    """여러 상품을 소싱처별로 그룹핑 후 병렬 갱신.

    소싱처당 동시 요청 수를 CONCURRENCY_PER_SITE로 제한한다.
    """
    if not products:
        return [], BulkRefreshResult()

    # 소싱처별 그룹핑
    by_site: dict[str, list] = {}
    for p in products:
        site = getattr(p, "source_site", "unknown")
        by_site.setdefault(site, []).append(p)

    all_results: List[RefreshResult] = []
    summary = BulkRefreshResult(total=len(products))

    async def _process_site(site: str, items: list) -> List[RefreshResult]:
        concurrency = SITE_CONCURRENCY.get(site, CONCURRENCY_PER_SITE)
        base_interval = SITE_BASE_INTERVAL.get(site, 1.0)
        sem = asyncio.Semaphore(concurrency)
        results = []

        async def _limited(p: Any) -> RefreshResult:
            async with sem:
                r = await refresh_product(p)
                # 소싱처별 적응형 인터벌 (기본값은 소싱처별 base_interval)
                interval = _site_intervals.get(site, base_interval)
                await asyncio.sleep(interval)
                return r

        tasks = [_limited(p) for p in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r if isinstance(r, RefreshResult)
            else RefreshResult(product_id="unknown", error=str(r))
            for r in results
        ]

    # 소싱처별 병렬 실행
    site_tasks = [_process_site(site, items) for site, items in by_site.items()]
    site_results = await asyncio.gather(*site_tasks)

    for results in site_results:
        for r in results:
            all_results.append(r)
            if r.error:
                summary.errors += 1
            elif r.needs_extension:
                summary.needs_extension.append(r.product_id)
            else:
                summary.refreshed += 1
                if r.changed:
                    summary.changed += 1
                if r.new_sale_status == "sold_out":
                    summary.sold_out += 1

    return all_results, summary

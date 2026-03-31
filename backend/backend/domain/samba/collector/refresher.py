"""소싱처별 가격/재고 재수집 모듈.

서버에서 직접 HTTP 요청으로 최신 가격/품절 상태를 추출한다.
KREAM은 확장앱 큐(KreamClient.collect_queue)를 통해 자동 수집.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.utils.logger import logger

# 환경: Cloud Run이면 동시 요청 높게, 로컬이면 낮게
import os
_IS_CLOUD = os.getenv("K_SERVICE") is not None  # Cloud Run 자동 설정 환경변수

# 소싱처당 동시 요청 제한 (기본값)
CONCURRENCY_PER_SITE = 10 if _IS_CLOUD else 5
# 소싱처별 동시 요청 수 (개별 설정)
SITE_CONCURRENCY: dict[str, int] = {
    "MUSINSA": 40 if _IS_CLOUD else 10,  # 워커 8→4 축소로 메모리 여유 확보
    "SSG": 3 if _IS_CLOUD else 1,
    "LOTTEON": 5 if _IS_CLOUD else 2,
    "FashionPlus": 10 if _IS_CLOUD else 3,
}
# 소싱처별 기본 인터벌 (초)
SITE_BASE_INTERVAL: dict[str, float] = {
    "MUSINSA": 1.0,
    "SSG": 1.0,
    "LOTTEON": 0.5,
}
# 소싱처별 최소 인터벌 (초)
SITE_MIN_INTERVAL: dict[str, float] = {
    "MUSINSA": 1.0,
    "SSG": 0.5,
    "LOTTEON": 0.3,
}
# 소싱처별 인터벌 복원 스텝 (성공 시 감소량)
SITE_INTERVAL_STEP: dict[str, float] = {
    "MUSINSA": 0.2,
    "SSG": 0.5,
    "LOTTEON": 0.3,
}
# KREAM 확장앱 대기 타임아웃 (초)
KREAM_TIMEOUT = 90
# 소싱처별 적응형 인터벌 관리 (기능별 격리)
# 키 형식: "MUSINSA" (워룸/갱신), "MUSINSA_collect" (수집)
_site_intervals: dict[str, float] = {}
_site_consecutive_errors: dict[str, int] = {}
# 소싱처별 안전 인터벌 기록 (차단 안 당하는 최소값)
_site_safe_intervals: dict[str, float] = {}


def get_interval_key(site: str, feature: str = "refresh") -> str:
    """기능별 인터벌 키 생성. 수집/갱신/워룸이 서로 간섭하지 않도록 격리."""
    if feature == "refresh":
        return site  # 기존 호환
    return f"{site}_{feature}"
# 벌크 갱신용 캐시 (배치 시작 시 1회 조회)
_bulk_musinsa_cache: dict[str, Any] = {}


async def _prepare_musinsa_cache() -> None:
    """MUSINSA 벌크 갱신 전 쿠키 1회 캐싱.

    등급할인율은 상품 API의 memberGrade.discountRate에서 직접 추출하므로
    별도 회원 API 호출 불필요 (새 멤버십 시스템).
    """
    cookie = await _get_musinsa_cookie()
    _bulk_musinsa_cache["cookie"] = cookie
    _bulk_musinsa_cache["grade_rate"] = 0


# ── 벌크 갱신 취소 플래그 ──
_bulk_cancel_requested = False

def request_bulk_cancel():
    """벌크 갱신 즉시 중단 요청."""
    global _bulk_cancel_requested
    _bulk_cancel_requested = True

def clear_bulk_cancel():
    """벌크 갱신 취소 플래그 초기화."""
    global _bulk_cancel_requested
    _bulk_cancel_requested = False

def is_bulk_cancelled() -> bool:
    return _bulk_cancel_requested

# ── 실시간 로그 링 버퍼 (최대 300건) ──
_refresh_log_buffer: deque[Dict[str, Any]] = deque(maxlen=300)
_refresh_log_total: int = 0  # 누적 카운터 (밀려나도 증가만)


def _log_refresh(
    site: str,
    product_id: str,
    product_name: str = "",
    message: str = "",
    level: str = "info",
    idx: int = 0,
    total: int = 0,
    source: str = "autotune",
) -> None:
    """갱신 로그를 링 버퍼에 추가. 오토튠 로그만 저장, 나머지(transmit/manual)는 버림."""
    current_source = _current_refresh_source.get()
    if current_source != "autotune":
        return
    source = current_source
    global _refresh_log_total
    now = datetime.now(timezone.utc)
    kst = now + timedelta(hours=9)
    ts_str = kst.strftime("%H:%M:%S")
    prefix = f"[{idx}/{total}] " if idx and total else ""
    name_label = f"{product_name[:40]}: " if product_name else ""
    full_msg = f"[{ts_str}] {prefix}{name_label}{message}"
    _refresh_log_buffer.append({
        "ts": now.isoformat(),
        "site": site,
        "product_id": product_id,
        "name": "",
        "msg": full_msg,
        "level": level,
        "source": source,
    })
    _refresh_log_total += 1


def get_refresh_logs(since_idx: int = 0, source_filter: str = "") -> tuple[List[Dict[str, Any]], int]:
    """로그 조회. since_idx 이후 로그만 반환 + 누적 인덱스.
    source_filter: "autotune"이면 오토튠 로그만, ""이면 전체.
    """
    global _refresh_log_total
    buf_len = len(_refresh_log_buffer)
    buf_start = _refresh_log_total - buf_len

    if since_idx >= _refresh_log_total:
        return [], _refresh_log_total
    if since_idx <= buf_start:
        logs = list(_refresh_log_buffer)
    else:
        offset = since_idx - buf_start
        logs = list(_refresh_log_buffer)[offset:]

    if source_filter:
        logs = [l for l in logs if l.get("source") == source_filter]
    return logs, _refresh_log_total


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
    stock_changed: bool = False
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


# async 컨텍스트별 격리 (전역 변수 레이스 컨디션 방지)
_current_refresh_source: contextvars.ContextVar[str] = contextvars.ContextVar("_current_refresh_source", default="autotune")

async def refresh_product(product: Any, idx: int = 0, total: int = 0, source: str = "autotune") -> RefreshResult:
    """소싱처에서 최신 가격/재고 재수집. source: autotune | transmit | manual"""
    token = _current_refresh_source.set(source)
    try:
        return await _refresh_product_inner(product, idx, total)
    finally:
        _current_refresh_source.reset(token)


async def _refresh_product_inner(product: Any, idx: int = 0, total: int = 0) -> RefreshResult:
    source_site = getattr(product, "source_site", "")

    # 소싱처 플러그인 우선 호출
    from backend.domain.samba.plugins import SOURCING_PLUGINS

    plugin = SOURCING_PLUGINS.get(source_site)
    if plugin:
        product._refresh_idx = idx
        product._refresh_total = total
        try:
            result = await plugin.refresh(product)
        except Exception as e:
            logger.error(f"[refresher] {product.id} ({source_site}) 플러그인 갱신 실패: {e}")
            return RefreshResult(
                product_id=product.id,
                error=str(e),
            )
        # 레거시 파서(무신사/KREAM)는 자체 로그 → 여기서 안 찍음
        if source_site not in ("MUSINSA", "KREAM") and not result.error:
            _name = getattr(product, "name", "") or ""
            _sid = getattr(product, "site_product_id", "") or ""
            _label = f"{_name} ({_sid})" if _sid else _name
            _status = "전송" if (result.changed or result.stock_changed) else "스킵"
            _ra = getattr(product, "registered_accounts", None) or []
            _mn = getattr(product, "market_product_nos", None) or {}
            _mi = ""
            if _ra and _mn:
                _ps = [str(_mn.get(a, "")) for a in _ra if _mn.get(a)]
                if _ps:
                    _mi = f" → {','.join(_ps)}"
            _old_p = getattr(product, "sale_price", 0) or 0
            _new_p = result.new_sale_price if result.new_sale_price is not None else _old_p
            _log_refresh(
                source_site, product.id, _label,
                f"{_status}{_mi} [원가 {int(_old_p):,}>{int(_new_p):,}]",
                idx=idx, total=total,
            )
        return result

    # 레거시 폴백 — 소싱처별 파서 선택
    parser = SITE_PARSERS.get(source_site)
    if not parser:
        return RefreshResult(
            product_id=product.id,
            error=f"지원하지 않는 소싱처: {source_site}",
        )

    # idx/total을 thread-local에 임시 저장 (파서에서 접근)
    product._refresh_idx = idx
    product._refresh_total = total

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
    """DB에서 무신사 쿠키 조회 — collector_common 공통 함수 위임."""
    from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie
    return await get_musinsa_cookie()


async def _parse_musinsa(product: Any) -> RefreshResult:
    """무신사 상품 가격/재고 재수집 (MusinsaClient 활용)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError

    _idx = getattr(product, "_refresh_idx", 0)
    _total = getattr(product, "_refresh_total", 0)

    site_product_id = getattr(product, "site_product_id", None)
    if not site_product_id:
        return RefreshResult(product_id=product.id, error="site_product_id 없음")

    cookie = _bulk_musinsa_cache.get("cookie") or await _get_musinsa_cookie()
    client = MusinsaClient(cookie)
    cached_grade_rate = _bulk_musinsa_cache.get("grade_rate")
    warnings: list[str] = []
    # 방어적 초기화: RateLimitError 재시도 경로에서 UnboundLocalError 방지
    detail = None

    try:
        detail = await asyncio.wait_for(
            client.get_goods_detail(
                site_product_id,
                member_grade_rate=cached_grade_rate,
                refresh_only=True,
            ),
            timeout=45,
        )
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
        pass  # 로그는 변동 판정 후 출력
    except RateLimitError as e:
        # 차단 → 인터벌 2배 증가 (최대 30초)
        current = _site_intervals.get("MUSINSA", 1.0)
        _site_intervals["MUSINSA"] = min(30.0, current * 2)
        _site_consecutive_errors["MUSINSA"] = _site_consecutive_errors.get("MUSINSA", 0) + 1
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"차단 HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, 인터벌→{_site_intervals['MUSINSA']:.1f}s)",
            level="warning", idx=_idx, total=_total,
        )

        # 연속 5회 이상이면 해당 소싱처 전체 일시 중단
        if _site_consecutive_errors["MUSINSA"] >= 5:
            _log_refresh(
                "MUSINSA", product.id,
                getattr(product, "name", ""),
                f"연속 {_site_consecutive_errors['MUSINSA']}회 차단 — 일시 중단",
                level="error", idx=_idx, total=_total,
            )
            return RefreshResult(
                product_id=product.id,
                error=f"차단 감지: HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, "
                      f"인터벌 {_site_intervals['MUSINSA']}초)",
            )

        # Retry-After가 있으면 대기 후 1회 재시도 (상한 60초)
        if e.retry_after > 0:
            capped_wait = min(e.retry_after, 60)
            logger.warning(f"[refresher] {site_product_id} 차단({e.status}), {capped_wait}초 후 재시도 (원본 Retry-After={e.retry_after})")
            await asyncio.sleep(capped_wait)
            try:
                detail = await client.get_goods_detail(
                    site_product_id,
                    member_grade_rate=cached_grade_rate,
                    refresh_only=True,
                )
                _site_consecutive_errors["MUSINSA"] = 0
            except Exception:
                _log_refresh(
                    "MUSINSA", product.id,
                    getattr(product, "name", ""),
                    f"재시도 실패: HTTP {e.status}",
                    level="error", idx=_idx, total=_total,
                )
                return RefreshResult(product_id=product.id, error=f"차단 후 재시도 실패: HTTP {e.status}")
        else:
            return RefreshResult(product_id=product.id, error=f"차단: HTTP {e.status}")
    except asyncio.TimeoutError:
        # 45초 안에 응답 없음 → 건너뛰기
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            "응답 없음 (45초 타임아웃) — 건너뜀",
            level="warning", idx=_idx, total=_total,
        )
        return RefreshResult(product_id=product.id, error="응답 없음: 45초 타임아웃")
    except Exception as e:
        _log_refresh(
            "MUSINSA", product.id,
            getattr(product, "name", ""),
            f"실패 — {e}",
            level="error", idx=_idx, total=_total,
        )
        return RefreshResult(product_id=product.id, error=f"무신사 API 오류: {e}")

    # detail이 None이면 예기치 않은 경로 — 안전하게 에러 반환
    if detail is None:
        return RefreshResult(product_id=product.id, error="상품 상세 조회 결과 없음")

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
        or new_sale_status != old_status
    )

    # 옵션 재고 변동 건수
    old_options = getattr(product, "options", None) or []
    _stock_changes = 0
    if new_options and old_options:
        old_stock_map = {(o.get("name", "") or o.get("size", "")): o.get("stock", 0) for o in old_options}
        for o in new_options:
            key = o.get("name", "") or o.get("size", "")
            if o.get("stock", 0) != old_stock_map.get(key, 0):
                _stock_changes += 1

    # 상품명 (품번) 형태 + 마켓/계정 정보
    _brand = getattr(product, "brand", "") or ""
    _name = getattr(product, "name", "") or ""
    _prod_label = f"{_brand} {_name} ({site_product_id})" if site_product_id else f"{_brand} {_name}"
    _prod_label = _prod_label.strip()
    _status = "전송" if (changed or _stock_changes > 0) else "스킵"
    # 마켓상품번호 + 계정 정보 조합
    _market_info = ""
    _reg_accounts = getattr(product, "registered_accounts", None) or []
    _market_nos = getattr(product, "market_product_nos", None) or {}
    if _reg_accounts and _market_nos:
        _parts = []
        for _acc_id in _reg_accounts:
            _mno = _market_nos.get(_acc_id, "")
            if _mno:
                _parts.append(str(_mno))
        if _parts:
            _market_info = f" → {','.join(_parts)}"
    _log_refresh(
        "MUSINSA", product.id, _prod_label,
        f"{_status}{_market_info} [원가 {int(old_sale):,}>{int(new_sale_price):,}, 판매가 {int(old_cost or old_sale):,}>{int(new_cost or new_sale_price):,}, 재고변동 {_stock_changes}건]",
        idx=_idx, total=_total,
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
        stock_changed=_stock_changes > 0,
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

    # 마켓 정보
    _reg_accounts = getattr(product, "registered_accounts", None) or []
    _market_nos = getattr(product, "market_product_nos", None) or {}
    _minfo = ""
    if _reg_accounts and _market_nos:
        _mparts = [str(_market_nos.get(a, "")) for a in _reg_accounts if _market_nos.get(a)]
        if _mparts:
            _minfo = f" → {','.join(_mparts)}"
    msg = (
        f"완료{_minfo}: 가격 {old_sale}→{new_sale_price}, 상태 {old_status}→{new_sale_status}"
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

def _has_stock_diff(old_options: list | None, new_options: list | None) -> bool:
    """옵션 재고 변동 여부 판별."""
    if not old_options or not new_options:
        return False
    old_map = {(o.get("name", "") or o.get("size", "")): o.get("stock", 0) for o in old_options}
    for o in new_options:
        key = o.get("name", "") or o.get("size", "")
        if o.get("stock", 0) != old_map.get(key, 0):
            return True
    return False


async def _parse_fashionplus(product: Any) -> RefreshResult:
    """패션플러스 가격/재고 갱신 — 검색 API + 상세 페이지."""
    from backend.domain.samba.proxy.fashionplus import FashionPlusClient

    pid = getattr(product, "site_product_id", "")
    if not pid:
        return RefreshResult(product_id=product.id, error="site_product_id 없음")

    client = FashionPlusClient()
    try:
        detail = await client.get_detail(pid)
    except Exception as e:
        return RefreshResult(product_id=product.id, error=f"상세 조회 실패: {e}")

    new_sale = detail.get("sale_price", 0) or 0
    new_orig = detail.get("original_price", 0) or new_sale
    new_images = detail.get("images") or None
    shipping_fee = detail.get("shipping_fee", 0) or 0
    new_cost = new_sale + shipping_fee

    old_sale = getattr(product, "sale_price", 0) or 0
    old_cost = getattr(product, "cost", 0) or 0
    changed = (new_sale != old_sale) or (new_cost != old_cost)

    logger.info(
        f"[패션플러스 갱신] {pid}: "
        f"원가 {old_cost}→{new_cost}, 판매가 {old_sale}→{new_sale}, 배송비 {shipping_fee}"
    )
    new_options = detail.get("options") or None
    return RefreshResult(
        product_id=product.id,
        new_sale_price=new_sale,
        new_original_price=new_orig,
        new_cost=new_cost,
        new_options=new_options,
        changed=changed,
        stock_changed=bool(new_options and _has_stock_diff(getattr(product, "options", None), new_options)),
    )


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
    "FashionPlus": _parse_fashionplus,
}


async def refresh_products_bulk(
    products: List[Any],
    source: str = "autotune",
    max_concurrency: int | None = None,
) -> tuple[List[RefreshResult], BulkRefreshResult]:
    """여러 상품을 소싱처별로 그룹핑 후 병렬 갱신.

    소싱처당 동시 요청 수를 CONCURRENCY_PER_SITE로 제한한다.
    max_concurrency: 지정 시 SITE_CONCURRENCY 대신 이 값 사용
    source: autotune | manual | transmit — 로그 출처 태그
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
        # 소싱처별 카운터 (번호 건너뜀 방지)
        _counter = {"i": 0}
        _site_total = len(items)
        # 소싱처별 사전 캐싱 (배치 시작 시 1회)
        if site == "MUSINSA":
            await _prepare_musinsa_cache()
        concurrency = max_concurrency if max_concurrency else SITE_CONCURRENCY.get(site, CONCURRENCY_PER_SITE)
        base_interval = SITE_BASE_INTERVAL.get(site, 1.0)
        sem = asyncio.Semaphore(concurrency)
        results = []

        async def _limited(p: Any) -> RefreshResult:
            async with sem:
                # 취소 요청 시 즉시 중단
                if _bulk_cancel_requested:
                    return RefreshResult(product_id=getattr(p, "id", "unknown"), error="cancelled")
                _counter["i"] += 1
                try:
                    r = await asyncio.wait_for(
                        refresh_product(p, idx=_counter["i"], total=_site_total, source=source),
                        timeout=60,
                    )
                except asyncio.TimeoutError:
                    _log_refresh(
                        site, getattr(p, "id", "unknown"),
                        getattr(p, "name", ""),
                        "전체 처리 타임아웃 (60초) — 건너뜀",
                        level="warning",
                    )
                    r = RefreshResult(product_id=getattr(p, "id", "unknown"), error="전체 처리 타임아웃: 60초")
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

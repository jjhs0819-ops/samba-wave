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


from backend.utils.logger import logger

# 환경: Cloud Run이면 동시 요청 높게, 로컬이면 낮게
import os

_IS_CLOUD = os.getenv("K_SERVICE") is not None  # Cloud Run 자동 설정 환경변수

# 소싱처당 동시 요청 제한 (기본값)
CONCURRENCY_PER_SITE = 10 if _IS_CLOUD else 5
# 소싱처별 동시 요청 수 (개별 설정)
SITE_CONCURRENCY: dict[str, int] = {
    "MUSINSA": 20 if _IS_CLOUD else 10,  # 워커 8→4 축소로 메모리 여유 확보
    "KREAM": 5 if _IS_CLOUD else 2,
    "DANAWA": 5 if _IS_CLOUD else 2,
    "FashionPlus": 10 if _IS_CLOUD else 3,
    "Nike": 5 if _IS_CLOUD else 2,
    "Adidas": 5 if _IS_CLOUD else 2,
    "ABCmart": 5 if _IS_CLOUD else 2,
    "GrandStage": 5 if _IS_CLOUD else 2,
    "REXMONDE": 5 if _IS_CLOUD else 2,
    # owner deviceId 필터링 적용 후 실행 PC 1대만 처리 → 큐 적체 방지 위해
    # 동시 2건 + 3초 간격으로 통일 (SSG/LOTTEON 공통)
    "SSG": 2,
    "LOTTEON": 2,
    "GSShop": 5 if _IS_CLOUD else 2,
    "ElandMall": 5 if _IS_CLOUD else 2,
    "SSF": 5 if _IS_CLOUD else 2,
    "NAVERSTORE": 5 if _IS_CLOUD else 2,
}
# 소싱처별 기본 인터벌 (초)
SITE_BASE_INTERVAL: dict[str, float] = {
    "MUSINSA": 1.0,
    "KREAM": 1.0,
    "DANAWA": 1.0,
    "FashionPlus": 1.0,
    "Nike": 1.0,
    "Adidas": 1.0,
    "ABCmart": 1.0,
    "GrandStage": 1.0,
    "REXMONDE": 1.0,
    # 실행 PC 1대 처리 기준 큐 적체 방지 (동시 2건 × 3초 간격 = 초당 0.67건 큐잉)
    "SSG": 3.0,
    "LOTTEON": 3.0,
    "GSShop": 1.0,
    "ElandMall": 1.0,
    "SSF": 1.0,
    "NAVERSTORE": 0.5,
}
# 소싱처별 최소 인터벌 (초)
SITE_MIN_INTERVAL: dict[str, float] = {
    "MUSINSA": 0,
    "KREAM": 0,
    "DANAWA": 0,
    "FashionPlus": 0,
    "Nike": 0,
    "Adidas": 0,
    "ABCmart": 0,
    "GrandStage": 0,
    "REXMONDE": 0,
    "SSG": 0,
    "LOTTEON": 0,
    "GSShop": 0,
    "ElandMall": 0,
    "SSF": 0,
    "NAVERSTORE": 0,
}
# 소싱처별 인터벌 복원 스텝 (성공 시 감소량)
SITE_INTERVAL_STEP: dict[str, float] = {
    "MUSINSA": 0.2,
    "KREAM": 0.3,
    "DANAWA": 0.3,
    "FashionPlus": 0.3,
    "Nike": 0.3,
    "Adidas": 0.3,
    "ABCmart": 0.3,
    "GrandStage": 0.3,
    "REXMONDE": 0.3,
    "SSG": 0.5,
    "LOTTEON": 0.3,
    "GSShop": 0.3,
    "ElandMall": 0.3,
    "SSF": 0.3,
    "NAVERSTORE": 0.3,
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
    """MUSINSA 벌크 갱신 전 쿠키 캐싱 (로테이션 지원).

    등급할인율은 상품 API의 memberGrade.discountRate에서 직접 추출하므로
    별도 회원 API 호출 불필요 (새 멤버십 시스템).
    """
    cookies = await _get_musinsa_cookies()
    _bulk_musinsa_cache["cookies"] = cookies
    # 사이클 간 로테이션 상태 유지 (첫 호출 시만 초기화)
    if "cookie_idx" not in _bulk_musinsa_cache:
        _bulk_musinsa_cache["cookie_idx"] = 0
        _bulk_musinsa_cache["cookie_usage"] = 0
    _bulk_musinsa_cache["cookie"] = (
        cookies[_bulk_musinsa_cache["cookie_idx"] % len(cookies)] if cookies else ""
    )
    _bulk_musinsa_cache["grade_rate"] = 0
    logger.info(
        f"[쿠키 캐싱] 쿠키 {len(cookies)}개 로드, 현재 인덱스 {_bulk_musinsa_cache.get('cookie_idx', 0)}, 사용량 {_bulk_musinsa_cache.get('cookie_usage', 0)}"
    )


# IP 로테이션: 프록시 목록 순환 (동시요청 수 기준으로 교대)
IP_ROTATE_EVERY = 20
# 사이트별 독립 카운터 (무신사·ABCmart 등 소싱처 병렬 실행 시 각각 20건 단위로 로테이션)
_ip_rotate_counters: dict[str, int] = {}
_ip_rotate_idxs: dict[str, int] = {}
_ip_rotate_labels: dict[str, str] = {}
_ip_rotate_totals: dict[str, int] = {}
# 하위호환 — 무신사 전용 단일 변수 (내부에서 딕셔너리로 위임)
_ip_rotate_counter = 0
_ip_rotate_idx = 0
_ip_rotate_label: str = ""
_ip_rotate_total = 0


# DB 프록시 캐시 (autotune 용도)
_db_proxy_cache: list[str] | None = None
_db_proxy_cache_ts: float = 0


def _load_db_proxies_for_autotune() -> list[str]:
    """DB proxy_config에서 autotune/both 활성 프록시 URL 목록 반환 (5분 캐시)."""
    global _db_proxy_cache, _db_proxy_cache_ts
    import time

    now = time.monotonic()
    if _db_proxy_cache is not None and now - _db_proxy_cache_ts < 300:
        return _db_proxy_cache

    try:
        import asyncio
        from sqlmodel import select
        from backend.db.orm import get_read_session
        from backend.domain.samba.forbidden.model import SambaSettings

        async def _fetch():
            async with get_read_session() as session:
                result = await session.execute(
                    select(SambaSettings).where(SambaSettings.key == "proxy_config")
                )
                row = result.scalar_one_or_none()
                if not row or not row.value:
                    return []
                return [
                    p["url"]
                    for p in row.value
                    if p.get("enabled")
                    and p.get("url")
                    and "autotune" in (p.get("purposes") or [])
                ]

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 이미 이벤트 루프가 돌고 있으면 동기로는 불가 → 캐시 반환
            return _db_proxy_cache or []
        urls = loop.run_until_complete(_fetch())
    except Exception:
        urls = []

    _db_proxy_cache = urls
    _db_proxy_cache_ts = now
    return urls


def invalidate_db_proxy_cache():
    """DB 프록시 캐시 무효화 — 설정 변경 시 호출."""
    global _db_proxy_cache, _db_proxy_cache_ts
    _db_proxy_cache = None
    _db_proxy_cache_ts = 0


def _get_rotated_proxy(site: str = "MUSINSA") -> str | None:
    """메인 IP + 프록시 목록을 N건 단위로 순환. DB 프록시 우선, 없으면 환경변수 폴백.

    site 파라미터로 소싱처별 독립 카운터를 관리한다.
    """
    global _ip_rotate_counters, _ip_rotate_idxs, _ip_rotate_labels, _ip_rotate_totals
    global _refresh_log_total
    from backend.core.config import settings

    # DB 프록시 우선
    db_proxies = _load_db_proxies_for_autotune()
    if db_proxies:
        proxies = db_proxies
    else:
        # 환경변수 폴백
        proxy_urls = settings.proxy_urls
        if not proxy_urls:
            return None
        proxies = [p.strip() for p in proxy_urls.split(",") if p.strip()]
    if not proxies:
        return None
    # 프록시만 사용 (메인 IP 제외)
    pool: list[str | None] = proxies

    # 사이트별 카운터 초기화
    if site not in _ip_rotate_counters:
        _ip_rotate_counters[site] = 0
        _ip_rotate_idxs[site] = 0
        _ip_rotate_labels[site] = ""
        _ip_rotate_totals[site] = 0

    _ip_rotate_counters[site] += 1
    _ip_rotate_totals[site] += 1
    if _ip_rotate_counters[site] >= IP_ROTATE_EVERY or _ip_rotate_labels[site] == "":
        _ip_rotate_counters[site] = 0
        if _ip_rotate_labels[site] != "":
            _ip_rotate_idxs[site] = (_ip_rotate_idxs[site] + 1) % len(pool)
        selected = pool[_ip_rotate_idxs[site]]
        label = (
            "main"
            if selected is None
            else (
                selected.split("@")[-1]
                if "@" in selected
                else f"proxy-{_ip_rotate_idxs[site]}"
            )
        )
        _from = _ip_rotate_totals[site]
        _to = _from + IP_ROTATE_EVERY - 1
        _ip_rotate_labels[site] = label
        _msg = f"IP -> {label} ({_from}~{_to}건)"
        logger.info(f"[autotune][{site}] {_msg}")
        now = datetime.now(timezone.utc)
        kst = now + timedelta(hours=9)
        _refresh_log_buffer.append(
            {
                "ts": now.isoformat(),
                "site": site,
                "product_id": "",
                "name": "",
                "msg": f"[{kst.strftime('%H:%M:%S')}] {_msg}",
                "level": "info",
                "source": "autotune",
            }
        )
        _refresh_log_total += 1
    return pool[_ip_rotate_idxs[site]]


# 쿠키 로테이션: 100건마다 다음 쿠키로 전환
COOKIE_ROTATE_EVERY = 100


def _rotate_musinsa_cookie() -> str:
    """벌크 갱신 중 쿠키 로테이션. 100건마다 다음 쿠키로 전환."""
    cookies = _bulk_musinsa_cache.get("cookies", [])
    if not cookies:
        return _bulk_musinsa_cache.get("cookie", "")
    _bulk_musinsa_cache["cookie_usage"] = _bulk_musinsa_cache.get("cookie_usage", 0) + 1
    if _bulk_musinsa_cache["cookie_usage"] >= COOKIE_ROTATE_EVERY:
        _bulk_musinsa_cache["cookie_usage"] = 0
        idx = (_bulk_musinsa_cache.get("cookie_idx", 0) + 1) % len(cookies)
        _bulk_musinsa_cache["cookie_idx"] = idx
        _bulk_musinsa_cache["cookie"] = cookies[idx]
        logger.info(f"[쿠키 로테이션] 쿠키 {idx + 1}/{len(cookies)}로 전환")
    return _bulk_musinsa_cache.get("cookie", "")


# ── 벌크 갱신 취소 플래그 (source별 분리) ──
_cancel_flags: Dict[str, bool] = {"autotune": False, "manual": False, "transmit": False}


def request_bulk_cancel(source: str = "autotune"):
    """특정 source의 벌크 갱신 즉시 중단 요청."""
    _cancel_flags[source] = True


def request_bulk_cancel_all():
    """모든 source의 벌크 갱신 즉시 중단 요청 (서버 종료 등)."""
    for k in _cancel_flags:
        _cancel_flags[k] = True


def clear_bulk_cancel(source: str = "autotune"):
    """특정 source의 취소 플래그 초기화."""
    _cancel_flags[source] = False


def is_bulk_cancelled(source: str = "autotune") -> bool:
    return _cancel_flags.get(source, False)


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
    prefix = f"[{idx:,}/{total:,}] " if idx and total else ""
    site_tag = f"[{site}] " if site else ""
    name_label = f"{product_name[:80]}: " if product_name else ""
    full_msg = f"[{ts_str}] {prefix}{site_tag}{name_label}{message}"
    _refresh_log_buffer.append(
        {
            "ts": now.isoformat(),
            "site": site,
            "product_id": product_id,
            "name": "",
            "msg": full_msg,
            "level": level,
            "source": source,
        }
    )
    _refresh_log_total += 1


def clear_refresh_logs() -> None:
    """로그 버퍼 초기화."""
    global _refresh_log_total
    _refresh_log_buffer.clear()
    _refresh_log_total = 0


def get_refresh_logs(
    since_idx: int = 0, source_filter: str = ""
) -> tuple[List[Dict[str, Any]], int]:
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


async def set_site_base_interval(site: str, interval: float) -> None:
    """소싱처 기본 인터벌 동적 변경 (초). DB에 동기적으로 저장."""
    SITE_BASE_INTERVAL[site] = interval
    # 현재 적응형 인터벌도 함께 갱신
    _site_intervals[site] = interval
    # DB에 영속화 (await로 저장 보장)
    await _persist_intervals_to_db()


async def _persist_intervals_to_db() -> None:
    """현재 SITE_BASE_INTERVAL을 DB에 저장."""
    try:
        from backend.db.orm import get_write_session
        from backend.api.v1.routers.samba.proxy import _set_setting

        async with get_write_session() as session:
            await _set_setting(session, "autotune_intervals", dict(SITE_BASE_INTERVAL))
            await session.commit()
    except Exception as e:
        logger.warning("[오토튠] 인터벌 DB 저장 실패: %s", e)


async def load_site_intervals_from_db() -> None:
    """서버 시작 시 DB에서 저장된 인터벌을 로드하여 SITE_BASE_INTERVAL에 반영."""
    try:
        from backend.db.orm import get_read_session
        from backend.api.v1.routers.samba.proxy import _get_setting

        async with get_read_session() as session:
            saved = await _get_setting(session, "autotune_intervals")
        if saved and isinstance(saved, dict):
            for site, val in saved.items():
                if isinstance(val, (int, float)) and 0 <= val <= 60:
                    SITE_BASE_INTERVAL[site] = float(val)
                    _site_intervals[site] = float(val)
    except Exception:
        pass  # 로드 실패 시 기본값 유지


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
    # 소싱처 보조 API(쿠폰/혜택) 실패로 가격 데이터가 불확실한 경우 True
    # True이면 오토튠에서 cost 업데이트 및 전송을 보류함
    price_uncertain: bool = False
    # 소싱처에서 상품 자체가 삭제되어 품절 처리된 경우 True (품절 이벤트 reason 구분용)
    deleted_from_source: bool = False


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
_current_refresh_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_refresh_source", default="autotune"
)


async def refresh_product(
    product: Any, idx: int = 0, total: int = 0, source: str = "autotune"
) -> RefreshResult:
    """소싱처에서 최신 가격/재고 재수집. source: autotune | transmit | manual"""
    token = _current_refresh_source.set(source)
    try:
        return await _refresh_product_inner(product, idx, total)
    finally:
        _current_refresh_source.reset(token)


async def _refresh_product_inner(
    product: Any, idx: int = 0, total: int = 0
) -> RefreshResult:
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
            logger.error(
                f"[refresher] {product.id} ({source_site}) 플러그인 갱신 실패: {e}"
            )
            return RefreshResult(
                product_id=product.id,
                error=str(e),
            )

        # LOTTEON: benefits API(혜택가) + option/mapping API(재고) 모두
        # 플러그인 refresh()에서 처리 완료 — 확장앱 불필요

        # 오토튠 컨텍스트에서는 콜백이 로그 담당 → 범용 로그 스킵
        if not result.error and _current_refresh_source.get() != "autotune":
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
            _new_p = (
                result.new_sale_price if result.new_sale_price is not None else _old_p
            )
            _log_refresh(
                source_site,
                product.id,
                _label,
                f"{_status}{_mi} [원가 {int(_old_p):,}>{int(_new_p):,}]",
                idx=idx,
                total=total,
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


async def _get_musinsa_cookies() -> list[str]:
    """DB에서 무신사 쿠키 목록 조회 (musinsa_cookies JSON 배열 또는 musinsa_cookie 단일)."""
    try:
        from backend.db.orm import get_read_session
        from backend.domain.samba.forbidden.model import SambaSettings
        from sqlmodel import select as _sel
        import json

        async with get_read_session() as session:
            # 먼저 복수 쿠키 키 확인
            result = await session.execute(
                _sel(SambaSettings).where(SambaSettings.key == "musinsa_cookies")
            )
            row = result.scalar_one_or_none()
            if row and row.value:
                val = json.loads(row.value) if isinstance(row.value, str) else row.value
                if isinstance(val, list) and val:
                    return [c for c in val if c]
            # 없으면 단일 쿠키 폴백
            cookie = await _get_musinsa_cookie()
            return [cookie] if cookie else []
    except Exception:
        cookie = await _get_musinsa_cookie()
        return [cookie] if cookie else []


async def _parse_musinsa(product: Any) -> RefreshResult:
    """무신사 상품 가격/재고 재수집 (MusinsaClient 활용)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError

    _idx = getattr(product, "_refresh_idx", 0)
    _total = getattr(product, "_refresh_total", 0)

    site_product_id = getattr(product, "site_product_id", None)
    if not site_product_id:
        return RefreshResult(product_id=product.id, error="site_product_id 없음")

    # 벌크 모드면 로테이션 쿠키, 아니면 단일 쿠키
    if _bulk_musinsa_cache.get("cookies"):
        cookie = _rotate_musinsa_cookie()
    else:
        cookie = _bulk_musinsa_cache.get("cookie") or await _get_musinsa_cookie()
    # 오토튠이면 메인↔프록시 IP 로테이션
    _proxy = (
        _get_rotated_proxy() if _current_refresh_source.get() == "autotune" else None
    )
    client = MusinsaClient(cookie, proxy_url=_proxy)
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
        # 성공 → 인터벌 점진 복원 (사용자 설정 base_interval을 하한으로 사용)
        base = SITE_BASE_INTERVAL.get("MUSINSA", 1.0)
        step = SITE_INTERVAL_STEP.get("MUSINSA", 0.5)
        prev_interval = _site_intervals.get("MUSINSA", base)
        new_interval = max(base, prev_interval - step)
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
        _site_consecutive_errors["MUSINSA"] = (
            _site_consecutive_errors.get("MUSINSA", 0) + 1
        )
        _log_refresh(
            "MUSINSA",
            product.id,
            getattr(product, "name", ""),
            f"차단 HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, 인터벌→{_site_intervals['MUSINSA']:.1f}s)",
            level="warning",
            idx=_idx,
            total=_total,
        )

        # 연속 5회 이상이면 해당 소싱처 전체 일시 중단
        if _site_consecutive_errors["MUSINSA"] >= 5:
            _log_refresh(
                "MUSINSA",
                product.id,
                getattr(product, "name", ""),
                f"연속 {_site_consecutive_errors['MUSINSA']}회 차단 — 일시 중단",
                level="error",
                idx=_idx,
                total=_total,
            )
            return RefreshResult(
                product_id=product.id,
                error=f"차단 감지: HTTP {e.status} (연속 {_site_consecutive_errors['MUSINSA']}회, "
                f"인터벌 {_site_intervals['MUSINSA']}초)",
            )

        # Retry-After가 있으면 대기 후 1회 재시도 (상한 60초)
        if e.retry_after > 0:
            capped_wait = min(e.retry_after, 60)
            logger.warning(
                f"[refresher] {site_product_id} 차단({e.status}), {capped_wait}초 후 재시도 (원본 Retry-After={e.retry_after})"
            )
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
                    "MUSINSA",
                    product.id,
                    getattr(product, "name", ""),
                    f"재시도 실패: HTTP {e.status}",
                    level="error",
                    idx=_idx,
                    total=_total,
                )
                return RefreshResult(
                    product_id=product.id, error=f"차단 후 재시도 실패: HTTP {e.status}"
                )
        else:
            return RefreshResult(product_id=product.id, error=f"차단: HTTP {e.status}")
    except asyncio.TimeoutError:
        # 45초 안에 응답 없음 → 건너뛰기
        _log_refresh(
            "MUSINSA",
            product.id,
            getattr(product, "name", ""),
            "응답 없음 (45초 타임아웃) — 건너뜀",
            level="warning",
            idx=_idx,
            total=_total,
        )
        return RefreshResult(product_id=product.id, error="응답 없음: 45초 타임아웃")
    except Exception as e:
        _err_brand = getattr(product, "brand", "") or ""
        _err_name = getattr(product, "name", "") or ""
        _err_spid = getattr(product, "site_product_id", "") or ""
        _err_label = (
            f"{_err_brand} {_err_name} ({_err_spid})".strip()
            if _err_spid
            else f"{_err_brand} {_err_name}".strip()
        )
        _err_msg = str(e).strip() or type(e).__name__
        if "상품 데이터 없음" in _err_msg:
            # 소싱처 영구 삭제 → 기존 sold_out 플로우와 동일하게 처리
            _log_refresh(
                "MUSINSA",
                product.id,
                _err_label,
                "소싱처 삭제 감지(상품 없음) — 품절 처리",
                level="warning",
                idx=_idx,
                total=_total,
            )
            return RefreshResult(
                product_id=product.id,
                new_sale_status="sold_out",
                changed=True,  # 상태 변경이므로 변동으로 처리 (수동갱신 sold_out 플로우 진입)
                deleted_from_source=True,
            )
        _log_refresh(
            "MUSINSA",
            product.id,
            _err_label,
            f"실패 — {_err_msg}",
            level="error",
            idx=_idx,
            total=_total,
        )
        return RefreshResult(
            product_id=product.id, error=f"무신사 API 오류: {_err_msg}"
        )

    # detail이 None이면 예기치 않은 경로 — 안전하게 에러 반환
    if detail is None:
        _log_refresh(
            "MUSINSA",
            product.id,
            getattr(product, "name", ""),
            "상세 조회 결과 없음",
            level="warning",
            idx=_idx,
            total=_total,
        )
        return RefreshResult(product_id=product.id, error="상품 상세 조회 결과 없음")

    # 결과 처리 전체를 보호 — 예외 발생 시에도 로그 출력
    try:
        return _process_musinsa_detail(
            product, detail, site_product_id, warnings, _idx, _total, _proxy
        )
    except Exception as _proc_e:
        _log_refresh(
            "MUSINSA",
            product.id,
            getattr(product, "name", ""),
            f"처리 오류: {_proc_e}",
            level="error",
            idx=_idx,
            total=_total,
        )
        logger.error(f"[refresher] {product.id} 결과 처리 실패: {_proc_e}")
        return RefreshResult(product_id=product.id, error=f"결과 처리 오류: {_proc_e}")


def _process_musinsa_detail(
    product, detail, site_product_id, warnings, _idx, _total, _proxy=None
) -> RefreshResult:
    """무신사 상세 결과 처리 — 변동 판정 + 로그."""

    new_sale_price = detail.get("salePrice", 0) or 0
    new_original_price = detail.get("originalPrice", 0) or 0
    new_cost = detail.get("bestBenefitPrice")
    if new_cost is not None and new_cost <= 0:
        new_cost = None
    new_sale_status = detail.get("saleStatus", "in_stock")
    new_options = detail.get("options")

    # 품절 상품인데 API가 가격 0 반환 → 기존 가격 보존
    if new_sale_status == "sold_out" and new_sale_price == 0:
        old_sp = getattr(product, "sale_price", 0) or 0
        if old_sp > 0:
            new_sale_price = old_sp
            logger.info(
                f"[refresher] {site_product_id} 품절+가격0 → 기존 판매가 {old_sp:,} 보존"
            )
    if new_sale_status == "sold_out" and new_original_price == 0:
        old_op = getattr(product, "original_price", 0) or 0
        if old_op > 0:
            new_original_price = old_op
    # 품절 시 원가도 기존값 보존
    if new_sale_status == "sold_out" and new_cost is None:
        old_cost = getattr(product, "cost", None)
        if old_cost and old_cost > 0:
            new_cost = old_cost

    # 품절 상품 옵션 가격 0 → 기존 옵션 가격 보존
    if new_sale_status == "sold_out" and new_options:
        all_zero = all((o.get("price", 0) or 0) == 0 for o in new_options)
        if all_zero:
            old_opts = getattr(product, "options", None) or []
            old_price_map = {
                (o.get("name", "") or o.get("size", "")): o.get("price", 0)
                for o in old_opts
                if (o.get("price", 0) or 0) > 0
            }
            if old_price_map:
                for o in new_options:
                    key = o.get("name", "") or o.get("size", "")
                    if key in old_price_map:
                        o["price"] = old_price_map[key]
                logger.info(
                    f"[refresher] {site_product_id} 품절+옵션가격0 → 기존 옵션 가격 복원"
                )

    # 부분 성공 경고: 주요 필드 누락 감지
    if new_sale_price == 0 and new_original_price == 0:
        warnings.append("salePrice/originalPrice 모두 0 — 무신사 API 구조 변경 가능성")
    if detail.get("name") is None or detail.get("name") == "":
        warnings.append("goodsNm 필드 누락 — 무신사 API 구조 변경 가능성")

    # 경고가 있으면 모니터링 이벤트 발행 (fire-and-forget)
    if warnings:
        try:
            # 서비스 레이어 없이 직접 로그 — 세션이 없으므로 로그만 남김
            logger.warning(f"[refresher] API 구조 변경 감지: {warnings}")
        except Exception:
            pass

    # 변동 판정
    old_sale = getattr(product, "sale_price", 0) or 0
    old_original = getattr(product, "original_price", 0) or 0
    old_cost = getattr(product, "cost", None)
    old_status = getattr(product, "sale_status", "in_stock")

    _old_cost_int = int(old_cost) if old_cost else 0
    _new_cost_int = int(new_cost) if new_cost else 0
    cost_changed = new_cost is not None and _new_cost_int != _old_cost_int
    changed = (
        new_sale_price != old_sale or new_sale_status != old_status or cost_changed
    )

    # 옵션 재고 변동 건수 — 품절↔리스탁 전환 + 수량 델타 모두 카운트
    # (소싱처 무관 공통 기준 — 신규 소싱처도 자동 포함)
    old_options = getattr(product, "options", None) or []
    _stock_changes = 0
    if new_options and old_options:
        old_stock_map = {
            (o.get("name", "") or o.get("size", "")): o.get("stock", 0)
            for o in old_options
        }
        for o in new_options:
            key = o.get("name", "") or o.get("size", "")
            old_stock = old_stock_map.get(key, 0) or 0
            new_stock = o.get("stock", 0) or 0
            was_soldout = old_stock <= 0
            is_soldout = new_stock <= 0 or o.get("isSoldOut", False)
            _transition = was_soldout != is_soldout
            _qty_delta = (old_stock or 0) != (new_stock or 0)
            if _transition or _qty_delta:
                _stock_changes += 1
                if _transition:
                    logger.info(
                        "[재고변동감지] %s %s: DB=%s(sold=%s) → API=%s(sold=%s)",
                        site_product_id,
                        key,
                        old_stock,
                        was_soldout,
                        new_stock,
                        is_soldout,
                    )
    else:
        if not old_options and new_options:
            logger.warning(
                "[재고변동] %s DB옵션없음(len=%d), API옵션=%d개",
                site_product_id,
                len(old_options),
                len(new_options),
            )
        elif not new_options:
            logger.warning("[재고변동] %s API옵션없음", site_product_id)

    # 상품명 (품번) 형태 + 마켓/계정 정보
    _brand = getattr(product, "brand", "") or ""
    _name = getattr(product, "name", "") or ""
    _prod_label = (
        f"{_brand} {_name} ({site_product_id})"
        if site_product_id
        else f"{_brand} {_name}"
    )
    _prod_label = _prod_label.strip()
    # 로그는 콜백(_on_result)에서 통합 출력 — refresher에서는 생략

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
        price_uncertain=bool(detail.get("price_uncertain")),
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
    KreamClient.collect_queue.append(
        {
            "requestId": request_id,
            "productId": site_product_id,
            "url": url,
        }
    )
    logger.info(f"[KREAM 갱신] 큐 등록: {site_product_id} ({request_id})")
    _log_refresh(
        "KREAM",
        product.id,
        getattr(product, "name", ""),
        f"확장앱 큐 등록: {site_product_id}",
    )

    # Future 생성 — 확장앱이 결과를 전달하면 resolve됨
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    KreamClient.collect_resolvers[request_id] = future

    try:
        result = await asyncio.wait_for(future, timeout=KREAM_TIMEOUT)
    except asyncio.TimeoutError:
        KreamClient.collect_resolvers.pop(request_id, None)
        _log_refresh(
            "KREAM",
            product.id,
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
    new_sale_status = (
        "sold_out" if (new_options and in_stock_count == 0) else "in_stock"
    )

    # 변동 판정
    old_sale = getattr(product, "sale_price", 0) or 0
    old_original = getattr(product, "original_price", 0) or 0
    old_status = getattr(product, "sale_status", "in_stock")

    changed = (
        new_sale_price != old_sale
        or new_original_price != old_original
        or new_sale_status != old_status
    )

    # 옵션 재고 변동 — 품절↔리스탁 전환 + 수량 델타 모두 카운트
    old_options = getattr(product, "options", None) or []
    _stock_changes = 0
    if new_options and old_options:
        old_stock_map = {
            (o.get("name", "") or o.get("size", "")): o.get("stock", 0)
            for o in old_options
        }
        for o in new_options:
            key = o.get("name", "") or o.get("size", "")
            old_stock = old_stock_map.get(key, 0) or 0
            new_stock = o.get("stock", 0) or 0
            was_soldout = old_stock <= 0
            is_soldout = new_stock <= 0
            if was_soldout != is_soldout or (old_stock or 0) != (new_stock or 0):
                _stock_changes += 1

    # 마켓 정보
    _reg_accounts = getattr(product, "registered_accounts", None) or []
    _market_nos = getattr(product, "market_product_nos", None) or {}
    _minfo = ""
    if _reg_accounts and _market_nos:
        _mparts = [
            str(_market_nos.get(a, "")) for a in _reg_accounts if _market_nos.get(a)
        ]
        if _mparts:
            _minfo = f" → {','.join(_mparts)}"
    msg = (
        f"완료{_minfo}: 가격 {old_sale}→{new_sale_price}, 상태 {old_status}→{new_sale_status}"
        + (", 변동 감지" if changed else "")
    )
    _log_refresh(
        "KREAM",
        product.id,
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
        stock_changed=_stock_changes > 0,
    )


# ── 범용 HTTP 파서 (ABCmart, Nike 등 — 현재 stub) ──


def _has_stock_diff(old_options: list | None, new_options: list | None) -> bool:
    """옵션 재고 변동 여부 판별."""
    if not old_options or not new_options:
        return False
    old_map = {
        (o.get("name", "") or o.get("size", "")): o.get("stock", 0) for o in old_options
    }
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
    # 옵션 기반 품절 판정: 모든 옵션 재고 0이면 sold_out
    is_sold_out = False
    if new_options:
        is_sold_out = all(
            (opt.get("stock", 0) if isinstance(opt, dict) else 0) <= 0
            for opt in new_options
        )
    new_sale_status = "sold_out" if is_sold_out else "in_stock"
    return RefreshResult(
        product_id=product.id,
        new_sale_price=new_sale,
        new_original_price=new_orig,
        new_cost=new_cost,
        new_sale_status=new_sale_status,
        new_options=new_options,
        changed=changed,
        stock_changed=bool(
            new_options
            and _has_stock_diff(getattr(product, "options", None), new_options)
        ),
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
    "REXMONDE": _parse_generic_stub,
    "LOTTEON": _parse_generic_stub,
    "GSShop": _parse_generic_stub,
    "ElandMall": _parse_generic_stub,
    "SSF": _parse_generic_stub,
    "FashionPlus": _parse_fashionplus,
}


async def refresh_products_bulk(
    products: List[Any],
    source: str = "autotune",
    max_concurrency: dict[str, int] | int | None = None,
    on_result: Any = None,
) -> tuple[List[RefreshResult], BulkRefreshResult]:
    """여러 상품을 소싱처별로 그룹핑 후 병렬 갱신.

    소싱처당 동시 요청 수를 CONCURRENCY_PER_SITE로 제한한다.
    max_concurrency: int 지정 시 전체 소싱처 동일 적용, dict 지정 시 소싱처별 오버라이드
    source: autotune | manual | transmit — 로그 출처 태그
    on_result: 각 상품 갱신 완료 시 호출되는 콜백 (product, result) → 즉시 전송 등
    """
    if not products:
        return [], BulkRefreshResult()

    # 시작 시 해당 source의 취소 플래그 초기화
    clear_bulk_cancel(source)

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
        if isinstance(max_concurrency, dict):
            concurrency = max_concurrency.get(
                site, SITE_CONCURRENCY.get(site, CONCURRENCY_PER_SITE)
            )
        elif max_concurrency:
            concurrency = max_concurrency
        else:
            concurrency = SITE_CONCURRENCY.get(site, CONCURRENCY_PER_SITE)
        base_interval = SITE_BASE_INTERVAL.get(site, 1.0)
        sem = asyncio.Semaphore(concurrency)
        results = []

        async def _limited(p: Any) -> RefreshResult:
            async with sem:
                # 취소 요청 시 즉시 중단 (자기 source만 체크)
                if _cancel_flags.get(source, False):
                    return RefreshResult(
                        product_id=getattr(p, "id", "unknown"), error="cancelled"
                    )
                _counter["i"] += 1
                _idx = _counter["i"]
                try:
                    r = await asyncio.wait_for(
                        refresh_product(p, idx=_idx, total=_site_total, source=source),
                        timeout=60,
                    )
                except asyncio.TimeoutError:
                    _log_refresh(
                        site,
                        getattr(p, "id", "unknown"),
                        getattr(p, "name", ""),
                        "전체 처리 타임아웃 (60초) — 건너뜀",
                        level="warning",
                    )
                    r = RefreshResult(
                        product_id=getattr(p, "id", "unknown"),
                        error="전체 처리 타임아웃: 60초",
                    )
                # 실패 시 1회 재시도 (오토튠만)
                if r.error and source == "autotune":
                    interval = max(0.1, _site_intervals.get(site, base_interval))
                    await asyncio.sleep(interval)
                    try:
                        r = await asyncio.wait_for(
                            refresh_product(
                                p, idx=_idx, total=_site_total, source=source
                            ),
                            timeout=60,
                        )
                        if not r.error:
                            _rb = getattr(p, "brand", "") or ""
                            _rn = getattr(p, "name", "") or ""
                            _rs = getattr(p, "site_product_id", "") or ""
                            _rl = (
                                f"{_rb} {_rn} ({_rs})".strip()
                                if _rs
                                else f"{_rb} {_rn}".strip()
                            )
                            _log_refresh(
                                site,
                                getattr(p, "id", "unknown"),
                                _rl,
                                "재시도 성공",
                                idx=_idx,
                                total=_site_total,
                            )
                    except asyncio.TimeoutError:
                        pass  # 재시도도 실패 → 원래 에러 유지
                # 에러 건도 로그에 표시 (on_result 콜백 전)
                if r.error and source == "autotune":
                    _rb = getattr(p, "brand", "") or ""
                    _rn = getattr(p, "name", "") or ""
                    _rs = getattr(p, "site_product_id", "") or ""
                    _rl = (
                        f"{_rb} {_rn} ({_rs})".strip()
                        if _rs
                        else f"{_rb} {_rn}".strip()
                    )
                    _err_short = (r.error or "")[:60]
                    _log_refresh(
                        site,
                        getattr(p, "id", "unknown"),
                        _rl,
                        f"실패: {_err_short}",
                        level="warning",
                        idx=_idx,
                        total=_site_total,
                    )
                # 콜백 호출 (리프레시 직후 즉시 전송 등)
                if on_result and not r.error:
                    try:
                        await on_result(p, r, _idx, _site_total)
                    except Exception as cb_err:
                        logger.warning("[오토튠] on_result 콜백 오류: %s", cb_err)
                # 소싱처별 적응형 인터벌 (기본값은 소싱처별 base_interval, 최소 0.1초)
                interval = max(0.1, _site_intervals.get(site, base_interval))
                await asyncio.sleep(interval)
                return r

        tasks = [_limited(p) for p in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r
            if isinstance(r, RefreshResult)
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

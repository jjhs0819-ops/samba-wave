"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, case, update as sa_update
from sqlalchemy.orm import defer
from sqlmodel import select

from backend.api.v1.routers.samba.collector_common import (
    _trim_history,
)
from backend.domain.samba.exchange_rate_service import convert_cost_by_source_site

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collector", tags=["samba-collector"])


# ══════════════════════════════════════════════════════════════
# 오토튠 백그라운드 루프 (무한 반복)
# ══════════════════════════════════════════════════════════════

_autotune_task: Optional[asyncio.Task] = None
_autotune_running_event = threading.Event()  # 스레드 간 동기화
_autotune_last_tick: Optional[str] = None
_autotune_cycle_count = 0
_autotune_restart_count = 0  # 사이클 재시작 횟수 추적

# 소싱처별 품절 서킷브레이커
SOLDOUT_BREAK_THRESHOLD = 10  # 연속 품절 N개 → 해당 소싱처 중단
_site_consecutive_soldout: dict[str, int] = {}  # {소싱처: 연속 품절 수}
_site_breaker_tripped: dict[str, bool] = {}  # {소싱처: 중단 여부}

# 원가 상승 확인 대기 — 소싱처 보조 API(쿠폰/혜택) 실패 시 1사이클 확인 후 전송
# {product_id: pending_cost}: 이전 사이클에서 감지된 원가 상승값 보관
_pending_cost_increase: dict[str, float] = {}

# 소싱처별 독립 루프 관리
_site_tasks: dict[str, asyncio.Task] = {}  # 소싱처별 asyncio 태스크
_site_cycle_counts: dict[str, int] = {}  # 소싱처별 누적 사이클 수
_site_last_ticks: dict[str, str] = {}  # 소싱처별 마지막 tick 시간
_site_empty_hits: dict[str, int] = {}  # 소싱처별 연속 빈 products 횟수
SITE_EMPTY_SKIP_THRESHOLD = 3  # N회 연속 빈 결과 시 해당 소싱처 60초 제외
_site_empty_skip_until: dict[str, float] = {}  # {소싱처: 제외 해제 시각(time.time())}

# Watchdog — stuck 감지/복구
_site_heartbeats: dict[str, float] = {}  # {소싱처: time.time()}
STUCK_TIMEOUT_SECONDS = 300  # 5분간 heartbeat 없으면 stuck 판정
MAX_RESTART_COUNT = 50  # 코디네이터 재시작 상한선

# 단일 상품 오토튠 필터 (설정 시 해당 상품만 갱신)
_autotune_target_ids: Optional[set] = None


# 등급 분류 기준 기간 (일)
CLASSIFY_WINDOW_DAYS = 7

# 오토튠 필터 설정 키 (samba_settings)
AUTOTUNE_FILTER_SOURCES_KEY = "autotune_enabled_sources"
AUTOTUNE_FILTER_MARKETS_KEY = "autotune_enabled_markets"
AUTOTUNE_PRIORITY_ENABLED_KEY = "autotune_priority_enabled"


async def _classify_products(session) -> dict[str, int]:
    """마켓등록상품 대상 hot/warm/cold 자동 분류 (벌크 SQL 3건).

    hot  = 최근 7일 주문 있음 AND 가격/재고 변동 있음
    warm = 최근 7일 가격/재고 변동 있음 (주문 없음)
    cold = 나머지 (마켓등록상품 한정)
    """
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from backend.domain.samba.order.model import SambaOrder

    log = logging.getLogger("autotune")
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLASSIFY_WINDOW_DAYS)

    # 마켓등록상품 공통 조건 (collector_common에서 통합 관리)
    from backend.api.v1.routers.samba.collector_common import (
        build_market_registered_conditions,
    )

    registered_cond = build_market_registered_conditions(_CP)

    # 최근 7일 주문이 있는 product_id 서브쿼리
    order_subq = (
        select(SambaOrder.product_id)
        .where(SambaOrder.created_at >= cutoff)
        .where(SambaOrder.product_id != None)
        .distinct()
    )

    # 가격/재고 변동 조건: price_changed_at이 7일 이내
    has_changes = _CP.price_changed_at >= cutoff

    # 1단계: 마켓등록상품 전체 → cold
    stmt_cold = (
        sa_update(_CP)
        .where(*registered_cond)
        .where(_CP.monitor_priority != "cold")
        .values(monitor_priority="cold")
    )
    r_cold = await session.execute(stmt_cold)

    # 2단계: 변동 있는 상품 → warm
    stmt_warm = (
        sa_update(_CP)
        .where(*registered_cond, has_changes)
        .values(monitor_priority="warm")
    )
    r_warm = await session.execute(stmt_warm)

    # 3단계: 변동 + 주문 있는 상품 → hot
    stmt_hot = (
        sa_update(_CP)
        .where(*registered_cond, has_changes)
        .where(_CP.id.in_(order_subq))
        .values(monitor_priority="hot")
    )
    r_hot = await session.execute(stmt_hot)

    await session.commit()

    counts = {"hot": r_hot.rowcount, "warm": r_warm.rowcount, "cold": r_cold.rowcount}
    log.info(
        "[오토튠] 등급 분류 완료 — hot %d, warm %d, cold %d",
        counts["hot"],
        counts["warm"],
        counts["cold"],
    )
    return counts


async def _site_autotune_loop(site: str):
    """소싱처별 독립 오토튠 루프 — 작업 완료 즉시 다음 사이클 재시작."""
    log = logging.getLogger("autotune")
    log.info("[오토튠][%s] 소싱처 루프 시작", site)

    try:
        while _autotune_running_event.is_set():
            try:
                # Watchdog heartbeat 갱신
                _site_heartbeats[site] = time.time()

                from backend.domain.samba.emergency import is_emergency_stopped

                if is_emergency_stopped():
                    await asyncio.sleep(5)
                    continue

                # 서킷브레이커 확인
                if _site_breaker_tripped.get(site):
                    log.info("[오토튠][%s] 서킷브레이커 작동 중 — 대기", site)
                    await asyncio.sleep(30)
                    continue

                from backend.db.orm import get_write_session

                async with get_write_session() as session:
                    from backend.domain.samba.collector.refresher import (
                        refresh_products_bulk,
                    )
                    from backend.domain.samba.collector.repository import (
                        SambaCollectedProductRepository,
                    )
                    from backend.domain.samba.collector.model import (
                        SambaCollectedProduct as _CP,
                    )
                    from backend.domain.samba.warroom.service import SambaMonitorService

                    now = datetime.now(timezone.utc)
                    repo = SambaCollectedProductRepository(session)

                    # 이 소싱처 상품만 조회
                    from backend.api.v1.routers.samba.collector_common import (
                        build_market_registered_conditions,
                    )
                    from backend.api.v1.routers.samba.proxy import _get_setting

                    market_cond = build_market_registered_conditions(_CP)

                    _priority_enabled = await _get_setting(
                        session, AUTOTUNE_PRIORITY_ENABLED_KEY
                    )
                    _use_priority = (
                        _priority_enabled
                        if isinstance(_priority_enabled, bool)
                        else True
                    )

                    if _use_priority:
                        priority_order = case(
                            (_CP.monitor_priority == "hot", 0),
                            (_CP.monitor_priority == "warm", 1),
                            else_=2,
                        )
                        _order_clause = (
                            priority_order,
                            _CP.last_refreshed_at.asc().nullsfirst(),
                        )
                    else:
                        _order_clause = (_CP.last_refreshed_at.asc().nullsfirst(),)

                    _where = [
                        *market_cond,
                        _CP.applied_policy_id != None,
                        _CP.source_site == site,
                    ]
                    # 단일 상품 오토튠 필터
                    if _autotune_target_ids:
                        _where.append(_CP.id.in_(_autotune_target_ids))
                    stmt = (
                        select(_CP)
                        .where(*_where)
                        .order_by(*_order_clause)
                        .options(
                            defer(_CP.detail_html),
                            defer(_CP.detail_images),
                            defer(_CP.images),
                            defer(_CP.extra_data),
                        )
                    )
                    result = await session.exec(stmt)
                    _seen_ids: set[str] = set()
                    products = []
                    for p in result.all():
                        if p.id not in _seen_ids:
                            _seen_ids.add(p.id)
                            products.append(p)

                    if products:
                        filtered_count = len(products)

                        # 결과 처리에 필요한 서비스 사전 초기화
                        import backend.domain.samba.collector.refresher as _ref_mod
                        from backend.domain.samba.shipment.service import (
                            calc_market_price,
                        )
                        from backend.domain.samba.policy.repository import (
                            SambaPolicyRepository,
                        )
                        from backend.domain.samba.account.repository import (
                            SambaMarketAccountRepository,
                        )
                        from backend.domain.samba.shipment.dispatcher import (
                            delete_from_market,
                        )
                        from backend.domain.samba.emergency import is_emergency_stopped

                        product_map: dict[str, object] = {p.id: p for p in products}
                        _policy_cache: dict[str, object] = {}
                        _account_cache: dict[str, object] = {}
                        account_repo = SambaMarketAccountRepository(session)
                        policy_repo = SambaPolicyRepository(session)

                        # 판매처 필터 사전 로드
                        _enabled_markets = await _get_setting(
                            session, AUTOTUNE_FILTER_MARKETS_KEY
                        )
                        _market_filter_active = bool(
                            _enabled_markets and isinstance(_enabled_markets, list)
                        )

                        # 계정 사전 로드
                        _all_account_ids: set[str] = set()
                        for _p in products:
                            if _p.registered_accounts:
                                _all_account_ids.update(_p.registered_accounts)
                        if _all_account_ids:
                            from backend.domain.samba.account.model import (
                                SambaMarketAccount,
                            )

                            _acc_stmt = select(SambaMarketAccount).where(
                                SambaMarketAccount.id.in_(list(_all_account_ids))
                            )
                            _acc_result = await session.exec(_acc_stmt)
                            for _acc in _acc_result.all():
                                _account_cache[_acc.id] = _acc

                        retransmitted = 0
                        deleted_count = 0
                        price_changed_count = 0
                        _all_price_pids: set[str] = set()
                        _all_stock_pids: set[str] = set()
                        _cycle_deleted_pids: set[str] = (
                            set()
                        )  # 사이클 중 삭제된 상품 ID
                        _session_lock = asyncio.Lock()
                        _synced_count = 0

                        def _log_line(site, pid, msg, level="info"):
                            """오토튠 통합 로그 (한 줄)."""
                            _kst_now = (
                                datetime.now(timezone.utc) + timedelta(hours=9)
                            ).strftime("%H:%M:%S")
                            _ref_mod._refresh_log_buffer.append(
                                {
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                    "site": site,
                                    "product_id": pid,
                                    "name": "",
                                    "msg": f"[{_kst_now}] {msg}",
                                    "level": level,
                                    "source": "autotune",
                                }
                            )
                            _ref_mod._refresh_log_total += 1

                        async def _partial_update(pid: str, vals: dict):
                            """last_sent_data를 건드리지 않는 partial UPDATE."""
                            from backend.domain.samba.collector.model import (
                                SambaCollectedProduct as _PU_CP,
                            )

                            vals["updated_at"] = datetime.now(timezone.utc)
                            stmt = (
                                sa_update(_PU_CP).where(_PU_CP.id == pid).values(**vals)
                            )
                            await session.execute(stmt)
                            await session.commit()

                        async def _on_result(product, r, idx=0, total=0):
                            """리프레시 직후 호출 — DB 업데이트 + 즉시 마켓 전송."""
                            nonlocal \
                                retransmitted, \
                                deleted_count, \
                                price_changed_count, \
                                _cycle_deleted_pids, \
                                _synced_count

                            async with _session_lock:
                                # heartbeat 갱신 — Watchdog stuck 오판 방지
                                _site_heartbeats[product.source_site or "UNKNOWN"] = (
                                    time.time()
                                )

                                if (
                                    not _autotune_running_event.is_set()
                                    or is_emergency_stopped()
                                ):
                                    return

                                site = product.source_site or "UNKNOWN"
                                _prod_name = (product.name or "")[:40]
                                _site_pid = product.site_product_id or ""
                                _name_part = f"[{site}] {_prod_name}"
                                _prod_label = (
                                    f"{_name_part} ({_site_pid})"
                                    if _site_pid
                                    else _name_part
                                )
                                _idx_prefix = (
                                    f"[{idx:,}/{total:,}] " if idx and total else ""
                                )

                                # 원가: 항상 최신 계산값 사용
                                if r.new_cost is not None:
                                    _cur_cost = r.new_cost
                                else:
                                    _cur_cost = product.cost or product.sale_price or 0
                                _cost_int = int(_cur_cost) if _cur_cost else 0

                                # DB 업데이트 준비 — 실제 처리 시점 기록 (사이클 시작 now 아님)
                                updates: dict = {
                                    "last_refreshed_at": datetime.now(timezone.utc),
                                    "refresh_error_count": 0,
                                }
                                snapshot: dict = {
                                    "date": now.isoformat(),
                                    "source": "autotune",
                                    "sale_price": r.new_sale_price
                                    if r.new_sale_price is not None
                                    else product.sale_price,
                                    "original_price": r.new_original_price
                                    if r.new_original_price is not None
                                    else product.original_price,
                                    "cost": r.new_cost
                                    if r.new_cost is not None
                                    else product.cost,
                                    "sale_status": r.new_sale_status,
                                    "changed": r.changed,
                                }
                                # 옵션: 신규 수집 우선, 없으면 기존 DB 옵션 폴백
                                # 품절인데 new_options 없으면 기존 옵션의 재고를 0으로 처리
                                _snap_options = r.new_options
                                if not _snap_options and product.options:
                                    if r.new_sale_status == "sold_out":
                                        _snap_options = [
                                            {**o, "stock": 0}
                                            if isinstance(o, dict)
                                            else o
                                            for o in product.options
                                        ]
                                    else:
                                        _snap_options = product.options
                                if _snap_options:
                                    snapshot["options"] = _snap_options
                                history = list(product.price_history or [])
                                history.insert(0, snapshot)
                                updates["price_history"] = _trim_history(history)

                                # 가격/옵션 필드는 변동 여부와 무관하게 항상 DB 반영
                                # (changed=False여도 cost만 바뀔 수 있음 → 전송 시 DB 읽으므로 필수)
                                if r.new_sale_price is not None:
                                    updates["sale_price"] = r.new_sale_price
                                if r.new_original_price is not None:
                                    updates["original_price"] = r.new_original_price
                                if r.new_cost is not None:
                                    updates["cost"] = r.new_cost
                                if r.new_options is not None:
                                    updates["options"] = r.new_options
                                elif (
                                    r.new_sale_status == "sold_out" and product.options
                                ):
                                    # new_options 없지만 품절 → 기존 옵션 재고를 0으로 강제 업데이트
                                    updates["options"] = [
                                        {**o, "stock": 0} if isinstance(o, dict) else o
                                        for o in product.options
                                    ]
                                updates["sale_status"] = r.new_sale_status
                                # cost 변경도 price_changed_at에 반영 (warm/hot 분류 기준)
                                if (
                                    r.changed
                                    or r.stock_changed
                                    or (
                                        r.new_cost is not None
                                        and r.new_cost
                                        != (getattr(product, "cost", None) or 0)
                                    )
                                ):
                                    updates["price_changed_at"] = now

                                # 품절 → 서킷브레이커 + 즉시 마켓삭제
                                if r.new_sale_status == "sold_out":
                                    _site_consecutive_soldout[site] = (
                                        _site_consecutive_soldout.get(site, 0) + 1
                                    )
                                    if (
                                        _site_consecutive_soldout[site]
                                        >= SOLDOUT_BREAK_THRESHOLD
                                    ):
                                        _site_breaker_tripped[site] = True
                                        log.error(
                                            "[오토튠] 서킷브레이커 작동! %s 연속 %d개 품절",
                                            site,
                                            _site_consecutive_soldout[site],
                                        )
                                        await _partial_update(r.product_id, updates)
                                        return
                                    if not getattr(product, "lock_delete", False):
                                        product_dict = product.model_dump()
                                        _ok_del_ids: list[str] = []
                                        for _del_acc_id in (
                                            product.registered_accounts or []
                                        ):
                                            _del_acc = _account_cache.get(_del_acc_id)
                                            if not _del_acc:
                                                continue
                                            m_nos = product.market_product_nos or {}
                                            if _del_acc.market_type == "smartstore":
                                                pno = m_nos.get(
                                                    f"{_del_acc_id}_origin", ""
                                                ) or m_nos.get(_del_acc_id, "")
                                            else:
                                                pno = m_nos.get(_del_acc_id, "")
                                            pd = {
                                                **product_dict,
                                                "market_product_no": {
                                                    _del_acc.market_type: pno
                                                },
                                            }
                                            _del_label = f"{_del_acc.market_name}({_del_acc.seller_id or '-'})"
                                            try:
                                                dr = await delete_from_market(
                                                    session,
                                                    _del_acc.market_type,
                                                    pd,
                                                    account=_del_acc,
                                                )
                                                if dr.get("success"):
                                                    deleted_count += 1
                                                    _ok_del_ids.append(_del_acc_id)
                                                    _log_line(
                                                        site,
                                                        r.product_id,
                                                        f"{_idx_prefix}{_prod_label}: 품절 → {_del_label} 마켓삭제 완료 [원가 {_cost_int:,}]",
                                                    )
                                                else:
                                                    log.warning(
                                                        "[오토튠] %s → %s 마켓삭제 실패: %s",
                                                        r.product_id,
                                                        _del_acc.market_type,
                                                        dr.get("message"),
                                                    )
                                            except Exception as e:
                                                log.error(
                                                    "[오토튠] %s → 마켓삭제 오류: %s",
                                                    r.product_id,
                                                    e,
                                                )
                                        # 삭제 성공한 계정 → registered_accounts/market_product_nos 정리
                                        if _ok_del_ids:
                                            _cycle_deleted_pids.add(r.product_id)
                                            _orig_reg = list(
                                                product.registered_accounts or []
                                            )
                                            _orig_mnos = dict(
                                                product.market_product_nos or {}
                                            )
                                            _new_reg = [
                                                a
                                                for a in _orig_reg
                                                if a not in _ok_del_ids
                                            ]
                                            _new_mnos = {
                                                k: v
                                                for k, v in _orig_mnos.items()
                                                if not any(
                                                    k == d or k.startswith(f"{d}_")
                                                    for d in _ok_del_ids
                                                )
                                            }
                                            updates["registered_accounts"] = (
                                                _new_reg if _new_reg else []
                                            )
                                            updates["market_product_nos"] = (
                                                _new_mnos if _new_mnos else {}
                                            )
                                            if not _new_reg:
                                                updates["status"] = "collected"
                                    await _partial_update(r.product_id, updates)
                                    _site_consecutive_soldout[site] = 0
                                    return
                                else:
                                    _site_consecutive_soldout[site] = 0

                                # ═══ 가격 불확실성 방어 (2계층) ═══
                                _skip_price = False

                                # 계층1: 소싱처 보조 API 부분실패 → 가격 데이터 불확실
                                if getattr(r, "price_uncertain", False):
                                    _skip_price = True
                                    log.warning(
                                        "[오토튠][가격불확실] %s: "
                                        "API 부분실패 → 가격갱신/전송 보류 "
                                        "(수집원가=%s, DB원가=%s)",
                                        _prod_label,
                                        _cost_int,
                                        int(product.cost or 0),
                                    )

                                # 계층2: 원가 3%+ 상승 시 1사이클 확인 대기 (범용)
                                elif (
                                    r.new_cost is not None
                                    and product.cost
                                    and product.cost > 0
                                    and r.new_cost > product.cost * 1.03
                                ):
                                    _prev = _pending_cost_increase.get(r.product_id)
                                    if _prev is None or (
                                        abs(_prev - r.new_cost) / r.new_cost > 0.01
                                    ):
                                        _pending_cost_increase[r.product_id] = (
                                            r.new_cost
                                        )
                                        _skip_price = True
                                        log.info(
                                            "[오토튠][가격상승확인] %s: "
                                            "원가 %s→%s (+%.1f%%) "
                                            "→ 다음 사이클 재확인 대기",
                                            _prod_label,
                                            int(product.cost),
                                            int(r.new_cost),
                                            (r.new_cost - product.cost)
                                            / product.cost
                                            * 100,
                                        )
                                    else:
                                        # 2사이클 연속 동일 상승 → 진짜 가격변동
                                        _pending_cost_increase.pop(r.product_id, None)
                                        log.info(
                                            "[오토튠][가격상승확정] %s: "
                                            "원가 상승 확인됨 (%s→%s)",
                                            _prod_label,
                                            int(product.cost),
                                            int(r.new_cost),
                                        )
                                else:
                                    # 원가 유지 또는 하락 → pending 제거
                                    _pending_cost_increase.pop(r.product_id, None)

                                # 가격 보류 시: DB cost 업데이트 스킵 + 전송 스킵
                                if _skip_price:
                                    updates.pop("cost", None)
                                    if getattr(r, "price_uncertain", False):
                                        snapshot["price_uncertain"] = True
                                    await _partial_update(r.product_id, updates)
                                    return

                                # DB 먼저 업데이트 (전송 전에 최신 데이터 반영)
                                await _partial_update(r.product_id, updates)

                                # ★ 마켓별 최종 판매가 비교 → 전송 판정
                                new_cost = _cur_cost
                                reg_accounts = product.registered_accounts or []
                                # 판매처 필터 적용 (market_type 기준)
                                if _market_filter_active:
                                    reg_accounts = [
                                        a
                                        for a in reg_accounts
                                        if (
                                            _account_cache.get(a)
                                            and getattr(
                                                _account_cache[a], "market_type", ""
                                            )
                                            in _enabled_markets
                                        )
                                    ]
                                last_sent = product.last_sent_data or {}

                                if product.applied_policy_id:
                                    if product.applied_policy_id not in _policy_cache:
                                        _policy_cache[
                                            product.applied_policy_id
                                        ] = await policy_repo.get_async(
                                            product.applied_policy_id
                                        )
                                    policy = _policy_cache[product.applied_policy_id]
                                else:
                                    policy = None

                                _tx_actions: list[
                                    str
                                ] = []  # 전송 예정 액션 (_fire_transmit에서 결과와 함께 출력)
                                _nontx_actions: list[
                                    str
                                ] = []  # 비전송 액션 (즉시 출력)
                                _transmit_queue: list[
                                    tuple
                                ] = []  # (pid, items, acc_id, label, action_text)

                                for acc_id in reg_accounts:
                                    if acc_id not in _account_cache:
                                        _account_cache[
                                            acc_id
                                        ] = await account_repo.get_async(acc_id)
                                    acc = _account_cache[acc_id]
                                    if not acc:
                                        continue
                                    acc_label = (
                                        f"{acc.market_name}({acc.seller_id or '-'})"
                                    )
                                    market_type = acc.market_type or ""

                                    if policy and policy.pricing:
                                        cost_info = await convert_cost_by_source_site(
                                            session,
                                            new_cost,
                                            site,
                                            getattr(product, "tenant_id", None),
                                        )
                                        expected_price = calc_market_price(
                                            cost_info["convertedCost"],
                                            policy.pricing,
                                            market_type,
                                            policy.market_policies,
                                            source_site=site,
                                        )
                                    else:
                                        expected_price = int(new_cost)

                                    acc_last = last_sent.get(acc_id, {})
                                    last_price = (
                                        (int(acc_last.get("sale_price", 0)) // 100)
                                        * 100
                                        if acc_last
                                        else 0
                                    )

                                    # 가격 변동 → 전송 예약
                                    # 스마트스토어: 300원 올림 (25% 역산 시 100원 단위 보장)
                                    import math as _m

                                    if market_type == "smartstore":
                                        expected_price = (
                                            _m.ceil(expected_price / 300) * 300
                                        )
                                    else:
                                        expected_price = (expected_price // 100) * 100

                                    # 가격 이상치 방어: 원가 < 정상가 5%이면 재전송 차단
                                    _orig_p = getattr(product, "original_price", 0) or 0
                                    _price_blocked = (
                                        _orig_p > 0
                                        and new_cost > 0
                                        and new_cost < _orig_p * 0.05
                                    )
                                    if _price_blocked:
                                        _nontx_actions.append(
                                            f"가격방어 차단 (원가 {int(new_cost):,}"
                                            f" < 정상가 {int(_orig_p):,}의 5%)"
                                        )
                                        log.error(
                                            "[오토튠][가격방어] %s: 원가 이상치 → "
                                            "재전송 차단 (원가=%s, 정상가=%s)",
                                            _prod_label,
                                            int(new_cost),
                                            int(_orig_p),
                                        )
                                    # 계정별 전송 아이템 수집 (가격+재고 합산 후 단일 전송)
                                    _acc_items: list[str] = []
                                    _acc_action_parts: list[str] = []

                                    if (
                                        expected_price != last_price
                                        and not _price_blocked
                                    ):
                                        price_changed_count += 1
                                        _all_price_pids.add(r.product_id)
                                        _price_action_txt = f"가격변동 {last_price:,}→{expected_price:,} → {acc_label}"
                                        _acc_items.append("price")
                                        _acc_action_parts.append(_price_action_txt)
                                    elif expected_price == last_price:
                                        # 가격 동일 스킵 — 다중 마켓 디버그 로그
                                        if len(reg_accounts) > 1:
                                            _last_cost_sent = (
                                                int(acc_last.get("cost", 0) or 0)
                                                if acc_last
                                                else 0
                                            )
                                            log.info(
                                                "[오토튠][가격스킵] %s %s: "
                                                "expected=%s==last=%s, "
                                                "cost_now=%s, cost_sent=%s",
                                                _prod_label,
                                                acc_label,
                                                expected_price,
                                                last_price,
                                                int(new_cost),
                                                _last_cost_sent,
                                            )

                                    # 재고 변동 → last_sent_data 옵션 vs API 옵션 비교
                                    _sent_opts = (
                                        acc_last.get("options") if acc_last else None
                                    )
                                    _api_opts = r.new_options
                                    _stock_diff = False
                                    _stock_changes_acc = 0
                                    # 디버그: 첫 3개 상품만 로그
                                    if idx <= 3:
                                        log.info(
                                            "[재고디버그] %s api_opts=%s, sent_opts=%s, acc=%s",
                                            r.product_id,
                                            len(_api_opts) if _api_opts else _api_opts,
                                            "있음" if _sent_opts else "없음",
                                            acc_id[:20],
                                        )
                                    if _sent_opts is None and _api_opts is not None:
                                        # 기준값 없음 → 첫 1회 무조건 전송
                                        _stock_diff = True
                                        _stock_changes_acc = (
                                            len(_api_opts) if _api_opts else 0
                                        )
                                    elif _api_opts and _sent_opts:
                                        _sent_map = {
                                            (
                                                o.get("name", "") or o.get("size", "")
                                            ): o.get("stock", 0)
                                            for o in _sent_opts
                                        }
                                        for _o in _api_opts:
                                            _k = _o.get("name", "") or _o.get(
                                                "size", ""
                                            )
                                            _ss = _sent_map.get(_k, 0) or 0
                                            _ns = _o.get("stock", 0) or 0
                                            if (_ss <= 0) != (_ns <= 0):
                                                _stock_diff = True
                                                _stock_changes_acc += 1
                                    if _stock_diff:
                                        _all_stock_pids.add(r.product_id)
                                        _stock_action_txt = f"재고전송({_stock_changes_acc}건) → {acc_label}"
                                        _acc_items.append("stock")
                                        _acc_action_parts.append(_stock_action_txt)

                                    # 가격+재고 합산 단일 전송 (충돌 방지)
                                    if _acc_items:
                                        retransmitted += 1
                                        _combined_action_txt = " + ".join(
                                            _acc_action_parts
                                        )
                                        _tx_actions.append(_combined_action_txt)
                                        _transmit_queue.append(
                                            (
                                                r.product_id,
                                                _acc_items,
                                                acc_id,
                                                f"{_prod_label}",
                                                _combined_action_txt,
                                            )
                                        )

                                # 통합 한 줄 로그 (전송 전에 즉시 출력)
                                # 원가 변동: 마지막 전송 시 원가 vs 현재 원가 비교
                                _prev_costs = [
                                    int(last_sent.get(a, {}).get("cost", 0) or 0)
                                    for a in reg_accounts
                                    if last_sent.get(a)
                                ]
                                _prev_cost = (
                                    _prev_costs[0] if _prev_costs else _cost_int
                                )
                                if _prev_cost != _cost_int:
                                    _cost_str = f"원가변동 {_prev_cost:,}→{_cost_int:,}"
                                else:
                                    _cost_str = f"원가 {_cost_int:,}"
                                _sc = "Y" if r.product_id in _all_stock_pids else "0"
                                _tail = f" [{_cost_str}, 재고변동 {_sc}]"
                                # 비전송 액션(가격방어 차단 등)은 즉시 출력
                                # 전송 예정 액션은 _fire_transmit에서 결과와 함께 출력
                                if _nontx_actions:
                                    _log_line(
                                        site,
                                        r.product_id,
                                        f"{_idx_prefix}{_prod_label}: {' | '.join(_nontx_actions)}{_tail}",
                                    )
                                elif not _tx_actions:
                                    # 전송 예정 액션도 없으면 스킵
                                    _log_line(
                                        site,
                                        r.product_id,
                                        f"{_idx_prefix}{_prod_label}: 스킵{_tail}",
                                    )

                            # lock 밖: fire-and-forget 전송 (백그라운드 태스크)
                            for (
                                _tx_pid,
                                _tx_items,
                                _tx_acc,
                                _tx_label,
                                _tx_action_text,
                            ) in _transmit_queue:

                                async def _fire_transmit(
                                    _pid=_tx_pid,
                                    _items=_tx_items,
                                    _acc=_tx_acc,
                                    _label=_tx_label,
                                    _site=site,
                                    _action_text=_tx_action_text,
                                    _idx_pfx=_idx_prefix,
                                    _t=_tail,
                                ):
                                    nonlocal _synced_count
                                    # 세마포어를 여기서 획득하면 안 됨
                                    # — start_update → _dispatch_one 내부에서 동일 세마포어를
                                    #   다시 획득하므로 데드락 발생 (Semaphore(1) 비재진입)
                                    try:
                                        async with get_write_session() as _tx_s:
                                            from backend.domain.samba.shipment.repository import (
                                                SambaShipmentRepository as _FRepo,
                                            )
                                            from backend.domain.samba.shipment.service import (
                                                SambaShipmentService as _FSvc,
                                            )

                                            _svc = _FSvc(_FRepo(_tx_s), _tx_s)
                                            _tx_result = await _svc.start_update(
                                                [_pid],
                                                _items,
                                                [_acc],
                                                skip_unchanged=False,
                                                skip_refresh=True,
                                            )
                                            await _tx_s.commit()

                                        # 결과 검증: start_update는 실패 시 예외 없이 dict로 반환
                                        _tx_res_list = _tx_result.get("results", [])
                                        _tx_ok = any(
                                            r.get("status") in ("success", "completed")
                                            for r in _tx_res_list
                                            if isinstance(r, dict)
                                        )
                                        if _tx_ok:
                                            _synced_count += 1
                                            _log_line(
                                                _site,
                                                _pid,
                                                f"{_idx_pfx}{_label}: {_action_text} 전송완료{_t}",
                                            )
                                        else:
                                            _fail_info = []
                                            for r in _tx_res_list:
                                                if isinstance(r, dict):
                                                    _e = r.get(
                                                        "transmit_error"
                                                    ) or r.get("error", "")
                                                    if _e:
                                                        _fail_info.append(str(_e)[:200])
                                            _log_line(
                                                _site,
                                                _pid,
                                                f"{_idx_pfx}{_label}: {_action_text} 전송실패(검증): {_fail_info[0] if _fail_info else '결과없음'}{_t}",
                                                "error",
                                            )
                                    except Exception as _fe:
                                        _log_line(
                                            _site,
                                            _pid,
                                            f"{_idx_pfx}{_label}: {_action_text} 전송실패: {str(_fe)[:200]}{_t}",
                                            "error",
                                        )
                                    await asyncio.sleep(0.3)

                                asyncio.create_task(_fire_transmit())

                        # DB 세션 복구 — 갱신 전 연결 확인
                        try:
                            from sqlmodel import text as _txt

                            await session.execute(_txt("SELECT 1"))
                        except Exception:
                            log.warning("[오토튠] 세션 만료 — rollback 후 재연결")
                            try:
                                await session.rollback()
                            except Exception:
                                pass

                        # ③ 소싱처별 병렬 갱신 + 결과 즉시 처리 (콜백)
                        results, summary = await refresh_products_bulk(
                            products,
                            max_concurrency={"MUSINSA": 2},
                            on_result=_on_result,
                        )

                        # _pending_cost_increase 고아 정리
                        # (이번 사이클에 포함되지 않은 상품의 pending 항목 제거)
                        _cycle_pids = set(product_map.keys())
                        _orphan_pids = [
                            k for k in _pending_cost_increase if k not in _cycle_pids
                        ]
                        for _ok in _orphan_pids:
                            _pending_cost_increase.pop(_ok, None)

                        # 에러 결과 후처리 (콜백에서 처리 안 된 에러 건)
                        for r in results:
                            if r.error and r.error != "cancelled":
                                _ep = product_map.get(r.product_id)
                                if _ep:
                                    try:
                                        await repo.update_async(
                                            r.product_id,
                                            refresh_error_count=(
                                                _ep.refresh_error_count or 0
                                            )
                                            + 1,
                                            last_refreshed_at=now,
                                        )
                                    except Exception:
                                        pass

                        # ④ 즉시전송으로 전환 — _pending_syncs 일괄 처리 제거됨

                        # 사이클 완료 로그 — 에러 유형별 분류
                        _err_count = sum(1 for r in results if r.error)
                        _ok_count = len(results) - _err_count
                        _no_pid_count = sum(
                            1
                            for r in results
                            if r.error and "site_product_id" in r.error
                        )
                        _blocked_count = sum(
                            1 for r in results if r.error and "차단" in r.error
                        )
                        _timeout_count = sum(
                            1
                            for r in results
                            if r.error
                            and ("타임아웃" in r.error or "Timeout" in r.error)
                        )
                        _other_err = (
                            _err_count - _no_pid_count - _blocked_count - _timeout_count
                        )
                        _now = datetime.now(timezone.utc)
                        _kst = _now + timedelta(hours=9)
                        # 에러 상세 문자열 구성
                        _err_parts = []
                        if _no_pid_count:
                            _err_parts.append(f"ID없음 {_no_pid_count:,}")
                        if _blocked_count:
                            _err_parts.append(f"차단 {_blocked_count:,}")
                        if _timeout_count:
                            _err_parts.append(f"타임아웃 {_timeout_count:,}")
                        if _other_err > 0:
                            _err_parts.append(f"기타 {_other_err:,}")
                        _err_detail = (
                            f" ({', '.join(_err_parts)})" if _err_parts else ""
                        )
                        _ref_mod._refresh_log_buffer.append(
                            {
                                "ts": _now.isoformat(),
                                "site": site,
                                "product_id": "",
                                "name": "",
                                "msg": f"[{_kst.strftime('%H:%M:%S')}] -- [{site}] 사이클 완료: {_ok_count:,}건 성공, {_err_count:,}건 실패{_err_detail} / 총 {len(results):,}건, 가격전송 {len(_all_price_pids):,}건, 재고전송 {len(_all_stock_pids):,}건, 동기 {_synced_count:,}건, 마켓삭제 {deleted_count:,}건 --",
                                "level": "info",
                                "source": "autotune",
                            }
                        )
                        _ref_mod._refresh_log_total += 1
                        log.info(
                            "[오토튠] 사이클 완료: %d성공, %d실패%s / %d건",
                            _ok_count,
                            _err_count,
                            _err_detail,
                            len(results),
                        )

                        # ★ 품절 잔존 상품 마켓삭제 재시도
                        # sale_status="sold_out"인데 registered_accounts가 남아있는 상품
                        try:
                            _soldout_where = [
                                *market_cond,
                                _CP.sale_status == "sold_out",
                                _CP.lock_delete != True,
                                _CP.source_site == site,
                            ]
                            # 사이클 중 이미 삭제된 상품 제외
                            if _cycle_deleted_pids:
                                _soldout_where.append(
                                    _CP.id.not_in(list(_cycle_deleted_pids))
                                )
                            _soldout_retry_stmt = (
                                select(_CP).where(*_soldout_where).limit(50)
                            )
                            _soldout_result = await session.exec(_soldout_retry_stmt)
                            _soldout_products = _soldout_result.all()

                            if _soldout_products:
                                log.info(
                                    "[오토튠] 품절 잔존 마켓삭제 재시도: %d건",
                                    len(_soldout_products),
                                )
                                # 재시도용 계정 캐시 보충
                                _retry_acc_ids: set[str] = set()
                                for _sp in _soldout_products:
                                    if _sp.registered_accounts:
                                        _retry_acc_ids.update(_sp.registered_accounts)
                                _missing_acc_ids = _retry_acc_ids - set(
                                    _account_cache.keys()
                                )
                                if _missing_acc_ids:
                                    from backend.domain.samba.account.model import (
                                        SambaMarketAccount,
                                    )

                                    _retry_acc_stmt = select(SambaMarketAccount).where(
                                        SambaMarketAccount.id.in_(
                                            list(_missing_acc_ids)
                                        )
                                    )
                                    _retry_acc_result = await session.exec(
                                        _retry_acc_stmt
                                    )
                                    for _ra in _retry_acc_result.all():
                                        _account_cache[_ra.id] = _ra

                                for _sp in _soldout_products:
                                    _sp_dict = _sp.model_dump()
                                    _sp_reg = list(_sp.registered_accounts or [])
                                    _sp_mnos = dict(_sp.market_product_nos or {})
                                    _sp_deleted_ids: list[str] = []

                                    for _del_acc_id in _sp_reg:
                                        _del_acc = _account_cache.get(_del_acc_id)
                                        if not _del_acc:
                                            continue
                                        _m_nos = _sp.market_product_nos or {}
                                        if _del_acc.market_type == "smartstore":
                                            _pno = _m_nos.get(
                                                f"{_del_acc_id}_origin", ""
                                            ) or _m_nos.get(_del_acc_id, "")
                                        else:
                                            _pno = _m_nos.get(_del_acc_id, "")
                                        _pd = {
                                            **_sp_dict,
                                            "market_product_no": {
                                                _del_acc.market_type: _pno
                                            },
                                        }
                                        _del_label = f"{_del_acc.market_name}({_del_acc.seller_id or '-'})"
                                        try:
                                            _dr = await delete_from_market(
                                                session,
                                                _del_acc.market_type,
                                                _pd,
                                                account=_del_acc,
                                            )
                                            if _dr.get("success"):
                                                deleted_count += 1
                                                _sp_deleted_ids.append(_del_acc_id)
                                                _log_line(
                                                    _sp.source_site or "",
                                                    _sp.id,
                                                    f"{_sp.name or _sp.id}: 품절잔존 → {_del_label} 마켓삭제 완료",
                                                )
                                            else:
                                                log.warning(
                                                    "[오토튠] 품절잔존 %s → %s 마켓삭제 실패: %s",
                                                    _sp.id,
                                                    _del_acc.market_type,
                                                    _dr.get("message"),
                                                )
                                        except Exception as _del_err:
                                            log.error(
                                                "[오토튠] 품절잔존 %s → 마켓삭제 오류: %s",
                                                _sp.id,
                                                _del_err,
                                            )

                                    # 삭제 성공한 계정 정리
                                    if _sp_deleted_ids:
                                        _new_reg = [
                                            a
                                            for a in _sp_reg
                                            if a not in _sp_deleted_ids
                                        ]
                                        _new_mnos = {
                                            k: v
                                            for k, v in _sp_mnos.items()
                                            if not any(
                                                k == did or k.startswith(f"{did}_")
                                                for did in _sp_deleted_ids
                                            )
                                        }
                                        _cleanup: dict = {
                                            "registered_accounts": _new_reg
                                            if _new_reg
                                            else [],
                                            "market_product_nos": _new_mnos
                                            if _new_mnos
                                            else {},
                                        }
                                        if not _new_reg:
                                            _cleanup["status"] = "collected"
                                        await repo.update_async(_sp.id, **_cleanup)

                                try:
                                    await asyncio.wait_for(session.commit(), timeout=30)
                                except Exception as _retry_commit_err:
                                    log.error(
                                        "[오토튠] 품절잔존 commit 실패: %s",
                                        _retry_commit_err,
                                    )
                                    try:
                                        await asyncio.wait_for(
                                            session.rollback(), timeout=10
                                        )
                                    except Exception:
                                        pass
                        except Exception as _retry_err:
                            log.error(
                                "[오토튠] 품절잔존 재시도 오류: %s",
                                _retry_err,
                                exc_info=True,
                            )

                        # 이벤트 발행 (별도 세션)
                        _ended = datetime.now(timezone.utc)
                        _duration_sec = round((_ended - now).total_seconds(), 1)
                        _rate = (
                            round(filtered_count / _duration_sec, 1)
                            if _duration_sec > 0
                            else 0
                        )
                        try:
                            async with get_write_session() as ev_session:
                                monitor = SambaMonitorService(ev_session)
                                await monitor.emit(
                                    "scheduler_tick",
                                    "info",
                                    summary=f"오토튠[{site}] — 대상 {filtered_count:,}건, 갱신 {summary.refreshed:,}건 (성공 {_ok_count:,}, 실패 {_err_count:,}{_err_detail}) | {_duration_sec:,}초, {_rate:,}건/초",
                                    source_site=site,
                                    detail={
                                        "total": filtered_count,
                                        "refreshed": summary.refreshed,
                                        "ok": _ok_count,
                                        "errors": _err_count,
                                        "no_pid": _no_pid_count,
                                        "blocked": _blocked_count,
                                        "timeouts": _timeout_count,
                                        "other_errors": _other_err,
                                        "price_transmit": len(_all_price_pids),
                                        "stock_transmit": len(_all_stock_pids),
                                        "sold_out": summary.sold_out,
                                        "retransmitted": retransmitted,
                                        "synced": _synced_count,
                                        "deleted": deleted_count,
                                        "started_at": now.isoformat(),
                                        "ended_at": _ended.isoformat(),
                                        "duration_sec": _duration_sec,
                                        "rate": _rate,
                                    },
                                )
                                await ev_session.commit()
                            log.info(
                                "[오토튠] 이벤트 발행 완료 (%s초, %s건/초)",
                                _duration_sec,
                                _rate,
                            )
                        except Exception as ev_err:
                            log.error("[오토튠] 이벤트 발행 실패: %s", ev_err)

                        # commit
                        try:
                            await asyncio.wait_for(session.commit(), timeout=30)
                        except (asyncio.TimeoutError, Exception) as commit_err:
                            log.error(
                                "[오토튠] 결과 commit 실패 (무시하고 진행): %s",
                                commit_err,
                            )
                            _ref_mod._refresh_log_buffer.append(
                                {
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                    "site": "",
                                    "product_id": "",
                                    "name": "",
                                    "msg": f"[{(datetime.now(timezone.utc) + timedelta(hours=9)).strftime('%H:%M:%S')}] 결과 commit 실패: {type(commit_err).__name__}: {str(commit_err)[:100]}",
                                    "level": "error",
                                    "source": "autotune",
                                }
                            )
                            _ref_mod._refresh_log_total += 1
                            try:
                                await asyncio.wait_for(session.rollback(), timeout=10)
                            except Exception:
                                pass

                        log.info(
                            "[오토튠] tick 완료: 대상 %d, 갱신 %d, 가격전송 %d, 재고전송 %d, 동기 %d, 삭제 %d",
                            filtered_count,
                            summary.refreshed,
                            len(_all_price_pids),
                            len(_all_stock_pids),
                            _synced_count,
                            deleted_count,
                        )
                    else:
                        _site_empty_hits[site] = _site_empty_hits.get(site, 0) + 1
                        if _site_empty_hits[site] >= SITE_EMPTY_SKIP_THRESHOLD:
                            _site_empty_skip_until[site] = time.time() + 60
                            log.info(
                                "[오토튠][%s] 대상 상품 없음 (%d회 연속) — 60초 제외",
                                site,
                                _site_empty_hits[site],
                            )
                            _site_empty_hits[site] = 0
                        else:
                            log.info("[오토튠][%s] 대상 상품 없음 — 루프 종료", site)
                        break

                    _site_empty_hits[site] = 0  # 정상 사이클 → 카운터 리셋
                    _site_cycle_counts[site] = _site_cycle_counts.get(site, 0) + 1
                    _site_last_ticks[site] = now.isoformat()
                    log.info(
                        "[오토튠][%s] 사이클 완료 (누적 %d회) — 즉시 재시작",
                        site,
                        _site_cycle_counts.get(site, 0),
                    )

            except asyncio.CancelledError:
                if not _autotune_running_event.is_set():
                    log.info("[오토튠][%s] 루프 취소됨 (정상 종료)", site)
                    break
                # Watchdog에 의해 _site_tasks에서 제거된 경우 → 좀비 루프 방지 종료
                _my_task = _site_tasks.get(site)
                if _my_task is not asyncio.current_task():
                    log.info(
                        "[오토튠][%s] Watchdog에 의해 교체됨 — 좀비 루프 방지 종료",
                        site,
                    )
                    break
                try:
                    import backend.domain.samba.collector.refresher as _ref_cancel

                    _now_cancel = datetime.now(timezone.utc)
                    _kst_cancel = _now_cancel + timedelta(hours=9)
                    _ref_cancel._refresh_log_buffer.append(
                        {
                            "ts": _now_cancel.isoformat(),
                            "site": site,
                            "product_id": "",
                            "name": "",
                            "msg": f"[{_kst_cancel.strftime('%H:%M:%S')}] !! [{site}] CancelledError — 사이클 재시작",
                            "level": "error",
                            "source": "autotune",
                        }
                    )
                    _ref_cancel._refresh_log_total += 1
                except Exception:
                    pass
                await asyncio.sleep(2)
            except Exception as e:
                log.error(
                    "[오토튠][%s] tick 오류: %s",
                    site,
                    e,
                    exc_info=True,
                )
                try:
                    import backend.domain.samba.collector.refresher as _ref_err

                    _now_err = datetime.now(timezone.utc)
                    _kst_err = _now_err + timedelta(hours=9)
                    _ref_err._refresh_log_buffer.append(
                        {
                            "ts": _now_err.isoformat(),
                            "site": site,
                            "product_id": "",
                            "name": "",
                            "msg": f"[{_kst_err.strftime('%H:%M:%S')}] !! [{site}] tick 오류: {type(e).__name__}: {str(e)[:100]}",
                            "level": "error",
                            "source": "autotune",
                        }
                    )
                    _ref_err._refresh_log_total += 1
                except Exception:
                    pass
                await asyncio.sleep(2)

    finally:
        log.info("[오토튠][%s] 소싱처 루프 종료", site)


async def _autotune_loop():
    """오토튠 코디네이터 — 소싱처별 독립 루프 생성/관리.

    공통 작업(등급 분류, 쿠키 갱신)을 수행하고
    소싱처별 독립 태스크를 생성한다.
    각 소싱처는 자기 작업이 끝나면 즉시 다음 사이클을 시작한다.
    """
    global _autotune_last_tick, _autotune_cycle_count, _autotune_restart_count
    log = logging.getLogger("autotune")
    log.info("[오토튠] 코디네이터 시작")

    try:
        while _autotune_running_event.is_set():
            try:
                # 이전 취소/비상정지 플래그 잔존 방지
                from backend.domain.samba.collector.refresher import clear_bulk_cancel

                clear_bulk_cancel()
                from backend.domain.samba.emergency import (
                    clear_emergency_stop,
                    is_emergency_stopped as _is_es,
                )

                if _is_es():
                    clear_emergency_stop()
                    log.info("[오토튠] 잔존 비상정지 해제")

                from backend.db.orm import get_write_session

                # 공통 사전 작업 (분류, 쿠키)
                async with get_write_session() as session:
                    from backend.domain.samba.collector.model import (
                        SambaCollectedProduct as _CP,
                    )
                    from backend.api.v1.routers.samba.proxy import _get_setting

                    # 롯데ON 쿠키 갱신
                    from backend.domain.samba.proxy.lotteon_sourcing import (
                        set_lotteon_cookie,
                    )

                    _lt_cookie = await _get_setting(session, "lotteon_cookie")
                    if _lt_cookie:
                        set_lotteon_cookie(str(_lt_cookie))

                    # 등급 분류
                    _priority_enabled = await _get_setting(
                        session, AUTOTUNE_PRIORITY_ENABLED_KEY
                    )
                    _use_priority = (
                        _priority_enabled
                        if isinstance(_priority_enabled, bool)
                        else True
                    )
                    if _use_priority:
                        try:
                            await _classify_products(session)
                        except Exception as cls_err:
                            log.warning("[오토튠] 등급 분류 실패: %s", cls_err)

                    # 활성 소싱처 목록 파악
                    from backend.api.v1.routers.samba.collector_common import (
                        build_market_registered_conditions,
                    )

                    market_cond = build_market_registered_conditions(_CP)

                    _enabled_sources = await _get_setting(
                        session, AUTOTUNE_FILTER_SOURCES_KEY
                    )

                    site_stmt = select(func.distinct(_CP.source_site)).where(
                        *market_cond,
                        _CP.applied_policy_id != None,
                        _CP.source_site != None,
                        _CP.source_site != "",
                    )
                    site_result = await session.execute(site_stmt)
                    active_sites = [r[0] for r in site_result.all() if r[0]]

                    # 소싱처 필터 적용
                    if _enabled_sources and isinstance(_enabled_sources, list):
                        active_sites = [
                            s for s in active_sites if s in _enabled_sources
                        ]

                    # 서킷브레이커 제외
                    active_sites = [
                        s for s in active_sites if not _site_breaker_tripped.get(s)
                    ]

                    # 연속 빈 결과 소싱처 일시 제외
                    _now_skip = time.time()
                    active_sites = [
                        s
                        for s in active_sites
                        if _now_skip >= _site_empty_skip_until.get(s, 0)
                    ]

                # 소싱처별 독립 루프 태스크 생성
                _newly_spawned = []
                for _site in active_sites:
                    existing = _site_tasks.get(_site)
                    if existing and not existing.done():
                        continue
                    task = asyncio.create_task(
                        _site_autotune_loop(_site),
                        name=f"autotune-{_site}",
                    )
                    _site_tasks[_site] = task
                    _newly_spawned.append(_site)

                if _newly_spawned:
                    log.info(
                        "[오토튠] 소싱처 루프 시작: %s (활성 %d개)",
                        ", ".join(_newly_spawned),
                        len([t for t in _site_tasks.values() if not t.done()]),
                    )

                # 완료된 태스크 정리
                for _s in list(_site_tasks.keys()):
                    if _site_tasks[_s].done():
                        try:
                            _site_tasks[_s].result()
                        except asyncio.CancelledError:
                            pass
                        except Exception as _te:
                            log.error(
                                "[오토튠] %s 소싱처 루프 예외 종료: %s",
                                _s,
                                _te,
                            )
                        del _site_tasks[_s]

                # Watchdog — stuck 소싱처 루프 강제 재시작
                _now_ts = time.time()
                for _s, _t in list(_site_tasks.items()):
                    if _t.done():
                        continue
                    _last_hb = _site_heartbeats.get(_s, _now_ts)
                    if _now_ts - _last_hb > STUCK_TIMEOUT_SECONDS:
                        log.warning(
                            "[오토튠][%s] stuck 감지 (%.0f초 무응답) — 강제 재시작",
                            _s,
                            _now_ts - _last_hb,
                        )
                        _t.cancel()
                        del _site_tasks[_s]
                        _site_heartbeats.pop(_s, None)

                # 전역 통계 갱신
                _autotune_cycle_count = sum(_site_cycle_counts.values())
                _ticks = [v for v in _site_last_ticks.values() if v]
                if _ticks:
                    _autotune_last_tick = max(_ticks)

                # 30초 대기 (1초 단위로 중지 확인)
                for _ in range(30):
                    if not _autotune_running_event.is_set():
                        break
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                if not _autotune_running_event.is_set():
                    log.info("[오토튠] 코디네이터 취소 (정상 종료)")
                    break
                _autotune_restart_count += 1
                if _autotune_restart_count >= MAX_RESTART_COUNT:
                    log.error(
                        "[오토튠] 재시작 상한(%d회) 도달 — 코디네이터 중단",
                        MAX_RESTART_COUNT,
                    )
                    break
                log.warning(
                    "[오토튠] CancelledError — 코디네이터 재시작 (누적 %d회)",
                    _autotune_restart_count,
                )
                await asyncio.sleep(2)
            except Exception as e:
                _autotune_restart_count += 1
                if _autotune_restart_count >= MAX_RESTART_COUNT:
                    log.error(
                        "[오토튠] 재시작 상한(%d회) 도달 — 코디네이터 중단",
                        MAX_RESTART_COUNT,
                    )
                    break
                log.error(
                    "[오토튠] 코디네이터 오류 (누적 %d회): %s",
                    _autotune_restart_count,
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(5)

    finally:
        # 모든 소싱처 태스크 종료
        for _s, _t in list(_site_tasks.items()):
            if not _t.done():
                _t.cancel()
        _site_tasks.clear()
        _autotune_running_event.clear()
        log.info("[오토튠] 코디네이터 종료 — running event 해제")


class AutotuneStartRequest(BaseModel):
    target_product_no: Optional[str] = None


async def _save_autotune_state(enabled: bool):
    """DB에 오토튠 ON/OFF 상태 저장."""
    try:
        from backend.db.orm import get_write_session
        from backend.api.v1.routers.samba.proxy import _set_setting

        async with get_write_session() as session:
            await _set_setting(session, "autotune_enabled", enabled)
            await session.commit()
    except Exception as e:
        logger.warning(f"[오토튠] 상태 저장 실패: {e}")


async def auto_start_if_enabled():
    """서버 시작 시 DB에서 오토튠 상태 확인 → ON이면 자동 시작.

    전송 Job이 존재하면 완료될 때까지 대기 후 시작 (OOM 방지).
    """
    try:
        # 저장된 인터벌 설정 복원
        from backend.domain.samba.collector.refresher import load_site_intervals_from_db

        await load_site_intervals_from_db()

        from backend.db.orm import get_read_session
        from backend.api.v1.routers.samba.proxy import _get_setting

        async with get_read_session() as session:
            enabled = await _get_setting(session, "autotune_enabled")
        if enabled:
            # 전송 Job 존재 시 대기 (OOM 방지 — 전송과 동시 실행 차단)
            from backend.db.orm import get_read_session as _get_rs
            from sqlalchemy import text as _st

            for _wait in range(12):  # 최대 60초 대기
                async with _get_rs() as _s:
                    _r = await _s.execute(
                        _st(
                            "SELECT count(*) FROM samba_jobs "
                            "WHERE status IN ('pending', 'running') "
                            "AND job_type = 'transmit'"
                        )
                    )
                    _tx_count = _r.scalar() or 0
                if _tx_count == 0:
                    break
                logger.info(
                    "[오토튠] 전송 Job %d건 진행 중 — 시작 대기 (%d/12)",
                    _tx_count,
                    _wait + 1,
                )
                await asyncio.sleep(5)

            global _autotune_task, _autotune_cycle_count
            from backend.domain.samba.collector.refresher import clear_bulk_cancel

            if not _autotune_running_event.is_set():
                _autotune_running_event.set()
                _autotune_cycle_count = 0
                _site_cycle_counts.clear()
                _site_last_ticks.clear()
                _site_tasks.clear()
                _site_empty_hits.clear()
                _site_empty_skip_until.clear()
                clear_bulk_cancel()
                _autotune_task = asyncio.create_task(_autotune_loop())
                logger.info("[오토튠] 서버 시작 — DB 설정에 따라 자동 시작")
    except Exception as e:
        logger.warning(f"[오토튠] 자동 시작 실패: {e}")


class RefreshOneRequest(BaseModel):
    product_no: str


@router.post("/autotune/refresh-one")
async def autotune_refresh_one(body: RefreshOneRequest):
    """단일 상품 오토튠 갱신 — 상품번호로 검색 후 1건 갱신."""
    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from backend.domain.samba.collector.refresher import refresh_products_bulk
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    pno = body.product_no.strip()
    if not pno:
        return {"ok": False, "error": "상품번호를 입력해주세요"}

    async with get_write_session() as session:
        repo = SambaCollectedProductRepository(session)

        # 1) id 검색
        product = await repo.get_async(pno)

        # 2) site_product_id 검색
        if not product:
            stmt = select(_CP).where(_CP.site_product_id == pno).limit(1)
            result = await session.execute(stmt)
            product = result.scalars().first()

        # 3) market_product_nos 값 검색 (JSON 내부 value 매칭)
        if not product:
            from sqlalchemy import cast, String

            stmt = (
                select(_CP)
                .where(cast(_CP.market_product_nos, String).contains(pno))
                .limit(5)
            )
            result = await session.execute(stmt)
            candidates = list(result.scalars().all())
            for c in candidates:
                nos = c.market_product_nos or {}
                if pno in str(nos.values()):
                    product = c
                    break

        if not product:
            return {"ok": False, "error": f"'{pno}' 상품을 찾을 수 없습니다"}

        # 갱신 실행
        results, summary = await refresh_products_bulk([product], source="manual")

        now = datetime.now(timezone.utc)
        kst_now = now + timedelta(hours=9)
        ts_str = kst_now.strftime("%H:%M:%S")
        r = results[0] if results else None
        detail_text = "갱신 실패"
        status = "error"
        site = getattr(product, "source_site", "") or ""
        brand = getattr(product, "brand", "") or ""
        name = (getattr(product, "name", "") or "")[:50]

        if r and not r.error:
            old_price = product.sale_price or 0
            new_price = r.new_sale_price if r.new_sale_price is not None else old_price
            old_status = getattr(product, "sale_status", "in_stock")
            changes: list[str] = []
            if new_price != old_price:
                changes.append(f"가격 ₩{int(old_price):,}→₩{int(new_price):,}")
            if r.new_sale_status and r.new_sale_status != old_status:
                changes.append(f"상태 {old_status}→{r.new_sale_status}")
            if r.stock_changed:
                changes.append("재고변동")

            if changes:
                detail_text = " / ".join(changes)
                status = "changed"
            else:
                detail_text = "변동 없음"
                status = "unchanged"

            # DB 업데이트
            from backend.api.v1.routers.samba.collector_common import _trim_history

            updates: dict = {
                "last_refreshed_at": now,
                "refresh_error_count": 0,
            }

            # 가격이력 스냅샷 — 변동 여부와 관계없이 항상 기록
            snapshot: dict = {
                "date": now.isoformat(),
                "source": "refresh-one",
                "sale_price": r.new_sale_price
                if r.new_sale_price is not None
                else product.sale_price,
                "original_price": r.new_original_price
                if r.new_original_price is not None
                else product.original_price,
                "cost": r.new_cost if r.new_cost is not None else product.cost,
                "sale_status": r.new_sale_status,
                "changed": r.changed,
            }
            # 옵션: 신규 수집 우선, 없으면 기존 DB 옵션 폴백
            _snap_options = r.new_options
            if not _snap_options and product.options:
                _snap_options = product.options
            if _snap_options:
                snapshot["options"] = _snap_options
            history = list(product.price_history or [])
            history.insert(0, snapshot)
            updates["price_history"] = _trim_history(history)

            # 옵션은 항상 갱신
            if r.new_options is not None:
                updates["options"] = r.new_options
            updates["sale_status"] = r.new_sale_status
            if r.changed:
                if r.new_sale_price is not None:
                    updates["sale_price"] = r.new_sale_price
                if r.new_original_price is not None:
                    updates["original_price"] = r.new_original_price
                if r.new_cost is not None:
                    updates["cost"] = r.new_cost
            await repo.update_async(product.id, **updates)
            await session.commit()
        elif r and r.error:
            detail_text = r.error[:80]

        # 오토튠 로그 버퍼에 직접 추가 → 실시간 로그 패널에 표시
        from backend.domain.samba.collector.refresher import (
            _refresh_log_buffer,
        )
        import backend.domain.samba.collector.refresher as _rfr

        site_tag = f"[{site}] " if site else ""
        log_msg = f"[{ts_str}] [단일갱신] {site_tag}{brand} {name}: {detail_text}"
        _refresh_log_buffer.append(
            {
                "ts": now.isoformat(),
                "site": site,
                "product_id": product.id,
                "name": name,
                "msg": log_msg,
                "level": "info" if status != "error" else "warning",
                "source": "autotune",
            }
        )
        _rfr._refresh_log_total += 1

        return {"ok": True}


@router.post("/autotune/start")
async def autotune_start(
    body: AutotuneStartRequest = AutotuneStartRequest(),
    request: Request = None,
):
    """오토튠 무한 루프 시작 — 메인 이벤트 루프에서 실행."""
    # 티어 제한 체크 — 오토튠 접근 권한
    try:
        from backend.db.orm import get_read_session
        from backend.domain.samba.tenant.middleware import (
            check_autotune_access,
        )

        if request:
            async with get_read_session() as session:
                # JWT에서 tenant_id 추출 시도
                auth_header = request.headers.get("Authorization") or ""
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1]
                    try:
                        from backend.core.config import settings
                        import jwt as _jwt

                        payload = _jwt.decode(
                            token,
                            settings.jwt_secret_key,
                            algorithms=[settings.jwt_algorithm],
                        )
                        user_id = payload.get("sub", "")
                        if user_id:
                            from backend.domain.samba.user.model import SambaUser

                            stmt = select(SambaUser).where(SambaUser.id == user_id)
                            result = (await session.execute(stmt)).scalars().first()
                            tid = getattr(result, "tenant_id", None) if result else None
                            if tid:
                                await check_autotune_access(tid, session)
                    except Exception:
                        pass  # 인증 실패 시 기존 동작 유지
    except Exception:
        pass  # 모듈 로드 실패 시 기존 동작 유지

    global \
        _autotune_task, \
        _autotune_cycle_count, \
        _autotune_restart_count, \
        _autotune_target_ids
    from backend.domain.samba.collector.refresher import clear_bulk_cancel

    if _autotune_running_event.is_set():
        return {"ok": True, "status": "already_running"}

    # 단일 상품 오토튠: 상품번호 → 내부 ID 변환
    _autotune_target_ids = None
    if body.target_product_no:
        pno = body.target_product_no.strip()
        if pno:
            from backend.db.orm import get_read_session
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as _CP,
            )
            from sqlalchemy import cast, String

            async with get_read_session() as session:
                # id 검색
                stmt = select(_CP.id).where(_CP.id == pno).limit(1)
                row = (await session.execute(stmt)).scalar()
                if not row:
                    # site_product_id 검색
                    stmt = select(_CP.id).where(_CP.site_product_id == pno).limit(1)
                    row = (await session.execute(stmt)).scalar()
                if not row:
                    # market_product_nos 값 검색
                    stmt = (
                        select(_CP.id, _CP.market_product_nos)
                        .where(cast(_CP.market_product_nos, String).contains(pno))
                        .limit(5)
                    )
                    rows = (await session.execute(stmt)).all()
                    for r in rows:
                        nos = r[1] or {}
                        if pno in str(nos.values()):
                            row = r[0]
                            break
                if not row:
                    return {
                        "ok": False,
                        "error": f"'{pno}' 상품을 찾을 수 없습니다",
                    }
                _autotune_target_ids = {row}

    _autotune_running_event.set()
    _autotune_cycle_count = 0
    _autotune_restart_count = 0
    _site_cycle_counts.clear()
    _site_last_ticks.clear()
    _site_tasks.clear()
    _site_heartbeats.clear()
    _site_empty_hits.clear()
    _site_empty_skip_until.clear()
    clear_bulk_cancel()
    _autotune_task = asyncio.create_task(_autotune_loop())
    if not body.target_product_no:
        await _save_autotune_state(True)
    return {"ok": True, "status": "started", "target": "registered"}


@router.post("/autotune/stop")
async def autotune_stop():
    """오토튠 무한 루프 정지 — 진행 중인 갱신도 즉시 중단."""
    global _autotune_task
    from backend.domain.samba.collector.refresher import request_bulk_cancel

    if not _autotune_running_event.is_set():
        return {"ok": True, "status": "already_stopped"}
    _autotune_running_event.clear()
    request_bulk_cancel("autotune")  # 오토튠 갱신만 즉시 중단
    # 소싱처별 태스크 전부 취소
    for _st in list(_site_tasks.values()):
        if not _st.done():
            _st.cancel()
    _site_tasks.clear()
    _site_empty_hits.clear()
    _site_empty_skip_until.clear()
    if _autotune_task and not _autotune_task.done():
        _autotune_task.cancel()
    _autotune_task = None
    await _save_autotune_state(False)
    return {"ok": True, "status": "stopped"}


@router.get("/autotune/status")
async def autotune_status():
    """오토튠 상태 조회 — 24h 갱신 수는 DB 기반."""
    from backend.db.orm import get_read_session
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP2

    tripped = {
        site: count
        for site, count in _site_consecutive_soldout.items()
        if _site_breaker_tripped.get(site)
    }

    # DB 기반 24h 갱신 수 (서버 재시작해도 유지)
    refreshed_24h = 0
    try:
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_read_session() as rs:
            cnt_stmt = select(func.count(_CP2.id)).where(
                _CP2.last_refreshed_at >= since_24h
            )
            refreshed_24h = (await rs.execute(cnt_stmt)).scalar() or 0
    except Exception:
        refreshed_24h = 0

    # 소싱처별 인터벌 정보
    from backend.domain.samba.collector.refresher import get_site_intervals_info

    intervals_info = get_site_intervals_info()

    # 등급 분류 ON/OFF
    priority_enabled = True
    try:
        from backend.api.v1.routers.samba.proxy import _get_setting

        async with get_read_session() as rs2:
            _pv = await _get_setting(rs2, AUTOTUNE_PRIORITY_ENABLED_KEY)
        priority_enabled = _pv if isinstance(_pv, bool) else True
    except Exception:
        pass

    # 소싱처별 활성 루프 정보 + heartbeat
    _now_hb = time.time()
    _active_site_loops = {
        s: {
            "running": not t.done(),
            "cycles": _site_cycle_counts.get(s, 0),
            "heartbeat_ago": round(_now_hb - _site_heartbeats.get(s, _now_hb)),
        }
        for s, t in _site_tasks.items()
    }

    return {
        "running": _autotune_running_event.is_set()
        and _autotune_task is not None
        and not _autotune_task.done(),
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "restart_count": _autotune_restart_count,
        "max_restart": MAX_RESTART_COUNT,
        "refreshed_count": refreshed_24h,
        "target": "registered",
        "breaker_tripped": tripped,
        "site_intervals": intervals_info.get("base_intervals", {}),
        "priority_enabled": priority_enabled,
        "site_loops": _active_site_loops,
        "stuck_timeout": STUCK_TIMEOUT_SECONDS,
    }


class AutotuneIntervalRequest(BaseModel):
    site: str
    interval: float  # 초


@router.post("/autotune/interval")
async def autotune_update_interval(body: AutotuneIntervalRequest):
    """소싱처별 오토튠 인터벌 동적 변경 (초 단위)."""
    from backend.domain.samba.collector.refresher import set_site_base_interval

    if body.interval < 0 or body.interval > 60:
        return {"ok": False, "error": "인터벌은 0~60초 범위만 가능합니다"}
    await set_site_base_interval(body.site, body.interval)
    logger.info("[오토튠] 인터벌 변경: %s → %.1f초", body.site, body.interval)
    return {"ok": True, "site": body.site, "interval": body.interval}


@router.post("/autotune/breaker-reset")
async def autotune_breaker_reset(site: str = ""):
    """소싱처별 서킷브레이커 수동 해제. site 미지정 시 전체 해제."""
    if site:
        _site_breaker_tripped.pop(site, None)
        _site_consecutive_soldout.pop(site, None)
        logger.info("[오토튠] 서킷브레이커 해제: %s", site)
        return {"ok": True, "reset": site}
    else:
        _site_breaker_tripped.clear()
        _site_consecutive_soldout.clear()
        _pending_cost_increase.clear()
        logger.info("[오토튠] 서킷브레이커 전체 해제 (pending 가격 상승 초기화 포함)")
        return {"ok": True, "reset": "all"}


# ── 등급 분류(hot/warm/cold) ON/OFF ──


@router.get("/autotune/priority")
async def autotune_get_priority():
    """등급 분류 ON/OFF 상태 조회."""
    from backend.db.orm import get_read_session
    from backend.api.v1.routers.samba.proxy import _get_setting

    async with get_read_session() as session:
        val = await _get_setting(session, AUTOTUNE_PRIORITY_ENABLED_KEY)
    enabled = val if isinstance(val, bool) else True
    return {"ok": True, "priority_enabled": enabled}


class AutotunePriorityRequest(BaseModel):
    enabled: bool


@router.post("/autotune/priority")
async def autotune_set_priority(body: AutotunePriorityRequest):
    """등급 분류 ON/OFF 설정 변경."""
    from backend.db.orm import get_write_session
    from backend.api.v1.routers.samba.proxy import _set_setting

    async with get_write_session() as session:
        await _set_setting(session, AUTOTUNE_PRIORITY_ENABLED_KEY, body.enabled)
        await session.commit()
    label = "ON" if body.enabled else "OFF"
    logger.info("[오토튠] 등급 분류 %s", label)
    return {"ok": True, "priority_enabled": body.enabled}


# ── 오토튠 필터 (소싱처 / 판매처 선택) ──


class AutotuneFilterRequest(BaseModel):
    enabled_sources: Optional[list[str]] = None
    enabled_markets: Optional[list[str]] = None


@router.get("/autotune/filters")
async def autotune_get_filters():
    """오토튠 필터 설정 + 실제 존재하는 소싱처/판매처(마켓 단위) 목록 반환."""
    import json as _json

    from backend.db.orm import get_read_session
    from backend.api.v1.routers.samba.proxy import _get_setting
    from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
    from backend.domain.samba.account.model import SambaMarketAccount
    from sqlalchemy import distinct

    async with get_read_session() as session:
        # 현재 저장된 필터
        saved_sources = await _get_setting(session, AUTOTUNE_FILTER_SOURCES_KEY)
        saved_markets = await _get_setting(session, AUTOTUNE_FILTER_MARKETS_KEY)

        # 실제 수집된 소싱처 목록 (상품이 존재하는 것만)
        src_stmt = select(distinct(_CP.source_site)).where(
            _CP.source_site != None, _CP.source_site != ""
        )
        src_result = await session.execute(src_stmt)
        available_sources = sorted([r[0] for r in src_result.all() if r[0]])

        # 등록된 상품의 registered_accounts → 계정 ID 수집
        reg_stmt = select(_CP.registered_accounts).where(
            _CP.status == "registered",
            _CP.registered_accounts.isnot(None),
        )
        reg_result = await session.execute(reg_stmt)
        _acc_ids: set[str] = set()
        for row in reg_result.all():
            val = row[0]
            if not val:
                continue
            # JSON 컬럼이 문자열로 반환될 수 있음
            if isinstance(val, str):
                try:
                    val = _json.loads(val)
                except Exception:
                    continue
            if isinstance(val, list):
                _acc_ids.update(str(a) for a in val if a)

        # 계정 → market_type 매핑 후 중복 제거 (마켓 단위)
        available_markets: list[str] = []
        if _acc_ids:
            acc_stmt = select(distinct(SambaMarketAccount.market_type)).where(
                SambaMarketAccount.id.in_(list(_acc_ids))
            )
            acc_result = await session.execute(acc_stmt)
            available_markets = sorted([r[0] for r in acc_result.all() if r[0]])

    return {
        "enabled_sources": saved_sources if isinstance(saved_sources, list) else None,
        "enabled_markets": saved_markets if isinstance(saved_markets, list) else None,
        "available_sources": available_sources,
        "available_markets": available_markets,
    }


@router.put("/autotune/filters")
async def autotune_set_filters(body: AutotuneFilterRequest):
    """오토튠 소싱처/판매처 필터 저장. None이면 전체 허용(필터 해제)."""
    from backend.db.orm import get_write_session
    from backend.api.v1.routers.samba.proxy import _set_setting

    async with get_write_session() as session:
        await _set_setting(session, AUTOTUNE_FILTER_SOURCES_KEY, body.enabled_sources)
        await _set_setting(session, AUTOTUNE_FILTER_MARKETS_KEY, body.enabled_markets)
        await session.commit()

    logger.info(
        "[오토튠] 필터 저장 — 소싱처: %s, 판매처: %s",
        body.enabled_sources if body.enabled_sources else "전체",
        f"{len(body.enabled_markets)}개" if body.enabled_markets else "전체",
    )
    return {
        "ok": True,
        "enabled_sources": body.enabled_sources,
        "enabled_markets": body.enabled_markets,
    }

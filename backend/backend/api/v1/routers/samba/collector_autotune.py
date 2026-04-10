"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, case, update as sa_update
from sqlalchemy.orm import defer
from sqlmodel import select

from backend.api.v1.routers.samba.collector_common import (
    _trim_history,
)

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

# 소싱처별 독립 루프 관리
_site_tasks: dict[str, asyncio.Task] = {}  # 소싱처별 asyncio 태스크
_site_cycle_counts: dict[str, int] = {}  # 소싱처별 누적 사이클 수
_site_last_ticks: dict[str, str] = {}  # 소싱처별 마지막 tick 시간


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
    import logging

    log = logging.getLogger("autotune")
    log.info("[오토튠][%s] 소싱처 루프 시작", site)

    try:
        while _autotune_running_event.is_set():
            try:
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

                    stmt = (
                        select(_CP)
                        .where(
                            *market_cond,
                            _CP.applied_policy_id != None,
                            _CP.sale_status != "sold_out",
                            _CP.source_site == site,
                        )
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
                        # 사이클 중 감지된 전송 요청을 수집 (fire-and-forget 대신)
                        _pending_syncs: list[tuple] = []

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

                        async def _on_result(product, r, idx=0, total=0):
                            """리프레시 직후 호출 — DB 업데이트 + 즉시 마켓 전송."""
                            nonlocal \
                                retransmitted, \
                                deleted_count, \
                                price_changed_count, \
                                _cycle_deleted_pids

                            async with _session_lock:
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

                                # 원가: DB 보존 로직과 일치시킴
                                # (확장앱 혜택가가 더 낮으면 DB는 기존값 보존)
                                if r.new_cost is not None:
                                    _old_cost_for_compare = (
                                        getattr(product, "cost", None) or 0
                                    )
                                    if (
                                        _old_cost_for_compare > 0
                                        and _old_cost_for_compare < r.new_cost
                                    ):
                                        _cur_cost = _old_cost_for_compare
                                    else:
                                        _cur_cost = r.new_cost
                                else:
                                    _cur_cost = product.cost or product.sale_price or 0
                                _cost_int = int(_cur_cost) if _cur_cost else 0
                                # 재고변동 건수
                                _stock_changes = 0
                                if r.stock_changed and r.new_options:
                                    _old_opts = product.options or []
                                    _old_stock_map = {
                                        (o.get("name", "") or o.get("size", "")): o.get(
                                            "stock", 0
                                        )
                                        for o in _old_opts
                                    }
                                    for _o in r.new_options:
                                        _k = _o.get("name", "") or _o.get("size", "")
                                        _os = _old_stock_map.get(_k, 0) or 0
                                        _ns = _o.get("stock", 0) or 0
                                        if (_os <= 0) != (_ns <= 0):
                                            _stock_changes += 1

                                # DB 업데이트 준비
                                updates: dict = {
                                    "last_refreshed_at": now,
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
                                _snap_options = r.new_options
                                if not _snap_options and product.options:
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
                                    _old_cost = getattr(product, "cost", None) or 0
                                    # 기존 원가가 더 낮으면(확장앱 혜택가) 보존
                                    if not (_old_cost > 0 and _old_cost < r.new_cost):
                                        updates["cost"] = r.new_cost
                                if r.new_options is not None:
                                    updates["options"] = r.new_options
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
                                        await repo.update_async(r.product_id, **updates)
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
                                    await repo.update_async(r.product_id, **updates)
                                    _site_consecutive_soldout[site] = 0
                                    return
                                else:
                                    _site_consecutive_soldout[site] = 0

                                # DB 먼저 업데이트 (전송 전에 최신 데이터 반영)
                                await repo.update_async(r.product_id, **updates)

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

                                _actions: list[str] = []
                                _transmit_queue: list[
                                    tuple
                                ] = []  # (pid, items, acc_id, label)

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
                                        expected_price = calc_market_price(
                                            new_cost,
                                            policy.pricing,
                                            market_type,
                                            policy.market_policies,
                                        )
                                    else:
                                        expected_price = int(new_cost)

                                    acc_last = last_sent.get(acc_id, {})
                                    last_price = (
                                        int(acc_last.get("sale_price", 0))
                                        if acc_last
                                        else 0
                                    )

                                    # 가격 변동 → 전송 예약
                                    if expected_price != last_price:
                                        price_changed_count += 1
                                        _all_price_pids.add(r.product_id)
                                        retransmitted += 1
                                        _actions.append(
                                            f"가격전송 {last_price:,}→{expected_price:,} → {acc_label}"
                                        )
                                        _transmit_queue.append(
                                            (
                                                r.product_id,
                                                ["price"],
                                                acc_id,
                                                f"{_prod_label}",
                                            )
                                        )

                                    # 재고 변동 → 전송 예약
                                    if r.stock_changed:
                                        _all_stock_pids.add(r.product_id)
                                        retransmitted += 1
                                        _actions.append(f"재고전송 → {acc_label}")
                                        _transmit_queue.append(
                                            (
                                                r.product_id,
                                                ["stock"],
                                                acc_id,
                                                f"{_prod_label}",
                                            )
                                        )

                                # 통합 한 줄 로그 (전송 전에 즉시 출력)
                                _old_cost_int = int(
                                    product.cost or product.sale_price or 0
                                )
                                _cost_str = (
                                    f"{_old_cost_int:,}→{_cost_int:,}"
                                    if _old_cost_int != _cost_int
                                    else f"{_cost_int:,}"
                                )
                                _tail = f" [원가 {_cost_str}, 재고변동 {_stock_changes:,}건]"
                                if _actions:
                                    _log_line(
                                        site,
                                        r.product_id,
                                        f"{_idx_prefix}{_prod_label}: {' | '.join(_actions)}{_tail}",
                                    )
                                else:
                                    _log_line(
                                        site,
                                        r.product_id,
                                        f"{_idx_prefix}{_prod_label}: 스킵{_tail}",
                                    )

                            # lock 밖: 전송 큐에 수집 (사이클 후 일괄 처리)
                            for _tx_args in _transmit_queue:
                                _pending_syncs.append(_tx_args)

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

                        # ④ 가격/재고 동기 — 전송잡 미실행 시에만 순차 처리
                        _synced_count = 0
                        if _pending_syncs:
                            from sqlmodel import text as _sync_txt

                            _tx_check = await session.execute(
                                _sync_txt(
                                    "SELECT count(*) FROM samba_jobs "
                                    "WHERE status IN ('pending', 'running') "
                                    "AND job_type = 'transmit'"
                                )
                            )
                            _tx_job_count = _tx_check.scalar() or 0
                            if _tx_job_count > 0:
                                log.info(
                                    "[오토튠] 전송잡 %d건 실행 중 — 가격/재고 동기 %d건 스킵 (잡이 처리)",
                                    _tx_job_count,
                                    len(_pending_syncs),
                                )
                            else:
                                _sync_total = len(_pending_syncs)
                                log.info(
                                    "[오토튠] 가격/재고 동기 시작: %d건", _sync_total
                                )
                                _sync_sem = asyncio.Semaphore(2)

                                async def _do_sync(s_pid, s_items, s_acc_id, s_label):
                                    async with _sync_sem:
                                        try:
                                            async with get_write_session() as tx_s:
                                                from backend.domain.samba.shipment.repository import (
                                                    SambaShipmentRepository as _SyncRepo,
                                                )
                                                from backend.domain.samba.shipment.service import (
                                                    SambaShipmentService as _SyncSvc,
                                                )

                                                _svc = _SyncSvc(_SyncRepo(tx_s), tx_s)
                                                await _svc.start_update(
                                                    [s_pid],
                                                    s_items,
                                                    [s_acc_id],
                                                    skip_unchanged=False,
                                                )
                                                await tx_s.commit()
                                        except Exception as _se:
                                            _s_site = getattr(
                                                product_map.get(s_pid),
                                                "source_site",
                                                "UNKNOWN",
                                            )
                                            _log_line(
                                                _s_site,
                                                s_pid,
                                                f"{s_label} 동기실패: {str(_se)[:80]}",
                                                "error",
                                            )
                                        # API 429 방지 딜레이
                                        await asyncio.sleep(0.5)

                                # 동시 2개씩 순차 처리
                                for _chunk_start in range(0, len(_pending_syncs), 10):
                                    _chunk = _pending_syncs[
                                        _chunk_start : _chunk_start + 10
                                    ]
                                    await asyncio.gather(
                                        *[_do_sync(*a) for a in _chunk],
                                        return_exceptions=True,
                                    )
                                    _synced_count += len(_chunk)
                                    # 비상정지 체크
                                    if is_emergency_stopped():
                                        log.info("[오토튠] 비상정지 — 동기 중단")
                                        break
                                log.info(
                                    "[오토튠] 가격/재고 동기 완료: %d/%d건",
                                    _synced_count,
                                    _sync_total,
                                )
                            _pending_syncs.clear()

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
                        log.info("[오토튠][%s] 대상 상품 없음 — 루프 종료", site)
                        break

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
    import logging

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
                        _CP.sale_status != "sold_out",
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
                log.warning(
                    "[오토튠] CancelledError — 코디네이터 재시작 (누적 %d회)",
                    _autotune_restart_count,
                )
                await asyncio.sleep(2)
            except Exception as e:
                _autotune_restart_count += 1
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
    pass


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
                clear_bulk_cancel()
                _autotune_task = asyncio.create_task(_autotune_loop())
                logger.info("[오토튠] 서버 시작 — DB 설정에 따라 자동 시작")
    except Exception as e:
        logger.warning(f"[오토튠] 자동 시작 실패: {e}")


@router.post("/autotune/start")
async def autotune_start(body: AutotuneStartRequest = AutotuneStartRequest()):
    """오토튠 무한 루프 시작 — 메인 이벤트 루프에서 실행."""
    global _autotune_task, _autotune_cycle_count, _autotune_restart_count
    from backend.domain.samba.collector.refresher import clear_bulk_cancel

    if _autotune_running_event.is_set():
        return {"ok": True, "status": "already_running"}
    _autotune_running_event.set()
    _autotune_cycle_count = 0
    _autotune_restart_count = 0
    _site_cycle_counts.clear()
    _site_last_ticks.clear()
    _site_tasks.clear()
    clear_bulk_cancel()
    _autotune_task = asyncio.create_task(_autotune_loop())
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
    request_bulk_cancel()  # 벌크 갱신 즉시 중단
    # 소싱처별 태스크 전부 취소
    for _st in list(_site_tasks.values()):
        if not _st.done():
            _st.cancel()
    _site_tasks.clear()
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

    # 소싱처별 활성 루프 정보
    _active_site_loops = {
        s: {"running": not t.done(), "cycles": _site_cycle_counts.get(s, 0)}
        for s, t in _site_tasks.items()
    }

    return {
        "running": _autotune_running_event.is_set()
        and _autotune_task is not None
        and not _autotune_task.done(),
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "restart_count": _autotune_restart_count,
        "refreshed_count": refreshed_24h,
        "target": "registered",
        "breaker_tripped": tripped,
        "site_intervals": intervals_info.get("base_intervals", {}),
        "priority_enabled": priority_enabled,
        "site_loops": _active_site_loops,
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
        logger.info("[오토튠] 서킷브레이커 전체 해제")
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

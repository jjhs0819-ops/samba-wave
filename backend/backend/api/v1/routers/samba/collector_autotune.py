"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, case, update as sa_update
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

# 소싱처별 품절 서킷브레이커
SOLDOUT_BREAK_THRESHOLD = 10  # 연속 품절 N개 → 해당 소싱처 중단
_site_consecutive_soldout: dict[str, int] = {}  # {소싱처: 연속 품절 수}
_site_breaker_tripped: dict[str, bool] = {}  # {소싱처: 중단 여부}


# 등급 분류 기준 기간 (일)
CLASSIFY_WINDOW_DAYS = 7

# 연속 무변동 스킵 설정
SKIP_AFTER_NO_CHANGE = 5  # 연속 N회 변동 없으면 스킵
SKIP_CYCLES = 3  # 스킵 사이클 수
_no_change_count: dict[str, int] = {}  # {상품ID: 연속 무변동 횟수}
_skip_remaining: dict[str, int] = {}  # {상품ID: 남은 스킵 사이클}


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


async def _autotune_loop():
    """오토튠 무한 루프 — tick 완료 즉시 다음 tick 시작.

    대상: 마켓등록상품만 (registered_accounts + market_product_nos 존재)
    순서: hot → warm → cold (소싱처별 병렬, 등급순 정렬)
    품절: 마켓 삭제(DELETE) → DB 삭제 (서킷브레이커: 소싱처별 연속 10건)
    """
    global _autotune_last_tick, _autotune_cycle_count
    import logging

    log = logging.getLogger("autotune")
    log.info("[오토튠] 루프 시작")

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
                    log.info("[오토튠] 잔존 비상정지 해제 — 사이클 계속")

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

                    # ① 등급 자동 분류 (매 사이클) — 실패해도 사이클 계속
                    try:
                        await _classify_products(session)
                    except Exception as cls_err:
                        log.warning(
                            "[오토튠] 등급 분류 실패 (무시하고 진행): %s", cls_err
                        )

                    # ② 마켓등록상품만 조회 + hot→warm→cold 정렬
                    priority_order = case(
                        (_CP.monitor_priority == "hot", 0),
                        (_CP.monitor_priority == "warm", 1),
                        else_=2,
                    )
                    # 마켓등록상품 공통 조건 (collector_common에서 통합 관리)
                    from backend.api.v1.routers.samba.collector_common import (
                        build_market_registered_conditions,
                    )

                    market_cond = build_market_registered_conditions(_CP)
                    stmt = (
                        select(_CP)
                        .where(
                            *market_cond,
                            # 정책 적용 + 품절 아님
                            _CP.applied_policy_id != None,
                            # sale_status 기준 품절 제외
                            _CP.sale_status != "sold_out",
                        )
                        .order_by(
                            priority_order, _CP.last_refreshed_at.asc().nullsfirst()
                        )
                    )
                    result = await session.exec(stmt)
                    # ID 기준 중복 제거 (동일 상품 2회 이상 처리 방지)
                    _seen_ids: set[str] = set()
                    products = []
                    for p in result.all():
                        if p.id not in _seen_ids:
                            _seen_ids.add(p.id)
                            products.append(p)

                    # 서킷브레이커 걸린 소싱처 상품 제외
                    if products:
                        before_filter = len(products)
                        products = [
                            p
                            for p in products
                            if not _site_breaker_tripped.get(p.source_site)
                        ]
                        skipped_by_breaker = before_filter - len(products)
                        if skipped_by_breaker > 0:
                            tripped_sites = [
                                s for s, v in _site_breaker_tripped.items() if v
                            ]
                            log.warning(
                                "[오토튠] 서킷브레이커 작동 중 — %s (%d개 제외)",
                                ", ".join(tripped_sites),
                                skipped_by_breaker,
                            )

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
                        from backend.domain.samba.shipment.repository import (
                            SambaShipmentRepository,
                        )
                        from backend.domain.samba.shipment.service import (
                            SambaShipmentService,
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

                        ship_repo = SambaShipmentRepository(session)
                        ship_svc = SambaShipmentService(ship_repo, session)

                        retransmitted = 0
                        deleted_count = 0
                        price_changed_count = 0
                        _all_price_pids: set[str] = set()
                        _all_stock_pids: set[str] = set()
                        _session_lock = asyncio.Lock()

                        async def _fire_transmit(pid, items, acc_id, label):
                            """별도 세션으로 마켓 전송 (fire-and-forget)."""
                            try:
                                async with get_write_session() as tx_session:
                                    from backend.domain.samba.shipment.repository import (
                                        SambaShipmentRepository as _TxShipRepo,
                                    )
                                    from backend.domain.samba.shipment.service import (
                                        SambaShipmentService as _TxShipSvc,
                                    )

                                    tx_svc = _TxShipSvc(
                                        _TxShipRepo(tx_session), tx_session
                                    )
                                    await tx_svc.start_update(
                                        [pid],
                                        items,
                                        [acc_id],
                                        skip_unchanged=False,
                                        skip_refresh=True,
                                    )
                                    await tx_session.commit()
                            except Exception as e:
                                _log_line(
                                    "MUSINSA",
                                    pid,
                                    f"{label} 전송실패: {str(e)[:80]}",
                                    "error",
                                )
                                log.error(
                                    "[오토튠] 전송실패 (%s, %s): %s", pid, acc_id, e
                                )

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
                            nonlocal retransmitted, deleted_count, price_changed_count

                            async with _session_lock:
                                if (
                                    not _autotune_running_event.is_set()
                                    or is_emergency_stopped()
                                ):
                                    return

                                site = product.source_site or "UNKNOWN"
                                _brand = (product.brand or "")[:10]
                                _prod_name = (product.name or "")[:30]
                                _site_pid = product.site_product_id or ""
                                _name_part = f"{_brand} {_prod_name}".strip()
                                _prod_label = (
                                    f"{_name_part} ({_site_pid})"
                                    if _site_pid
                                    else _name_part
                                )
                                _idx_prefix = (
                                    f"[{idx}/{total}] " if idx and total else ""
                                )

                                # 원가 표시용
                                _cur_cost = (
                                    r.new_cost
                                    if r.new_cost is not None
                                    else (product.cost or product.sale_price or 0)
                                )
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
                                if r.new_options:
                                    snapshot["options"] = r.new_options
                                history = list(product.price_history or [])
                                history.insert(0, snapshot)
                                updates["price_history"] = _trim_history(history)

                                if r.changed:
                                    if r.new_sale_price is not None:
                                        updates["sale_price"] = r.new_sale_price
                                    if r.new_original_price is not None:
                                        updates["original_price"] = r.new_original_price
                                    if r.new_cost is not None:
                                        updates["cost"] = r.new_cost
                                    if r.new_options is not None:
                                        updates["options"] = r.new_options
                                    updates["sale_status"] = r.new_sale_status
                                    updates["price_changed_at"] = now
                                elif r.stock_changed:
                                    if r.new_options is not None:
                                        updates["options"] = r.new_options
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
                                _tail = f" [원가 {_cost_int:,}, 재고변동 {_stock_changes}건]"
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

                                # 연속 무변동 카운터 — 마켓 전송 기준
                                _any_transmitted = len(_actions) > 0
                                if _any_transmitted or r.stock_changed:
                                    _no_change_count.pop(r.product_id, None)
                                    _skip_remaining.pop(r.product_id, None)
                                else:
                                    cnt = _no_change_count.get(r.product_id, 0) + 1
                                    _no_change_count[r.product_id] = cnt
                                    if cnt >= SKIP_AFTER_NO_CHANGE:
                                        _skip_remaining[r.product_id] = SKIP_CYCLES
                                        _no_change_count[r.product_id] = 0

                            # lock 밖: fire-and-forget 전송 (별도 세션, 완료 대기 안 함)
                            for _tx_args in _transmit_queue:
                                asyncio.create_task(_fire_transmit(*_tx_args))

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
                            products, max_concurrency=2, on_result=_on_result
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
                                "site": "MUSINSA",
                                "product_id": "",
                                "name": "",
                                "msg": f"[{_kst.strftime('%H:%M:%S')}] -- 사이클 완료: {_ok_count:,}건 성공, {_err_count:,}건 실패{_err_detail} / 총 {len(results):,}건, 가격전송 {len(_all_price_pids):,}건, 재고전송 {len(_all_stock_pids):,}건, 삭제 {deleted_count:,}건 --",
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
                            _soldout_retry_stmt = (
                                select(_CP)
                                .where(
                                    *market_cond,
                                    _CP.sale_status == "sold_out",
                                    _CP.lock_delete != True,
                                )
                                .limit(50)
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
                                    summary=f"오토튠 — 대상 {filtered_count:,}건, 갱신 {summary.refreshed:,}건 (성공 {_ok_count:,}, 실패 {_err_count:,}{_err_detail}) | {_duration_sec:,}초, {_rate:,}건/초",
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
                            "[오토튠] tick 완료: 대상 %d, 갱신 %d, 가격전송 %d, 재고전송 %d, 삭제 %d",
                            filtered_count,
                            summary.refreshed,
                            len(_all_price_pids),
                            len(_all_stock_pids),
                            deleted_count,
                        )
                    else:
                        await asyncio.sleep(5)

                    _autotune_last_tick = now.isoformat()
                    _autotune_cycle_count += 1

            except asyncio.CancelledError:
                if not _autotune_running_event.is_set():
                    log.info("[오토튠] 루프 취소됨 (정상 종료)")
                    break
                # running 상태인데 CancelledError → 일시적 취소, 루프 계속
                log.warning(
                    "[오토튠] CancelledError 발생했으나 running 상태 — 사이클 재시작"
                )
                await asyncio.sleep(2)
            except Exception as e:
                log.error("[오토튠] tick 오류: %s", e, exc_info=True)
                # 오토튠 실시간 로그에도 에러 표시 (이모지 제거 — cp949 에러 방지)
                try:
                    import backend.domain.samba.collector.refresher as _ref_err

                    _now_err = datetime.now(timezone.utc)
                    _kst_err = _now_err + timedelta(hours=9)
                    _ref_err._refresh_log_buffer.append(
                        {
                            "ts": _now_err.isoformat(),
                            "site": "MUSINSA",
                            "product_id": "",
                            "name": "",
                            "msg": f"[{_kst_err.strftime('%H:%M:%S')}] tick 오류: {type(e).__name__}: {str(e)[:100]}",
                            "level": "error",
                            "source": "autotune",
                        }
                    )
                    _ref_err._refresh_log_total += 1
                except Exception:
                    pass  # 로그 실패가 루프를 죽이면 안 됨
                # 에러 후 즉시 다음 사이클 시작 (새 세션으로)
                await asyncio.sleep(2)

    finally:
        # 어떤 이유로든 루프 종료 시 running event 해제 (유령 상태 방지)
        _autotune_running_event.clear()
        log.info("[오토튠] 루프 종료 — running event 해제")


class AutotuneStartRequest(BaseModel):
    target: str = "registered"  # 하위 호환용 (무시됨, 항상 마켓등록상품만)


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
    """서버 시작 시 DB에서 오토튠 상태 확인 → ON이면 자동 시작."""
    try:
        from backend.db.orm import get_read_session
        from backend.api.v1.routers.samba.proxy import _get_setting

        async with get_read_session() as session:
            enabled = await _get_setting(session, "autotune_enabled")
        if enabled:
            global _autotune_task, _autotune_cycle_count
            from backend.domain.samba.collector.refresher import clear_bulk_cancel

            if not _autotune_running_event.is_set():
                _autotune_running_event.set()
                _autotune_cycle_count = 0
                clear_bulk_cancel()
                _autotune_task = asyncio.create_task(_autotune_loop())
                logger.info("[오토튠] 서버 시작 — DB 설정에 따라 자동 시작")
    except Exception as e:
        logger.warning(f"[오토튠] 자동 시작 실패: {e}")


@router.post("/autotune/start")
async def autotune_start(body: AutotuneStartRequest = AutotuneStartRequest()):
    """오토튠 무한 루프 시작 — 메인 이벤트 루프에서 실행."""
    global _autotune_task, _autotune_cycle_count
    from backend.domain.samba.collector.refresher import clear_bulk_cancel

    if _autotune_running_event.is_set():
        return {"ok": True, "status": "already_running"}
    _autotune_running_event.set()
    _autotune_cycle_count = 0
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

    return {
        "running": _autotune_running_event.is_set()
        and _autotune_task is not None
        and not _autotune_task.done(),
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "refreshed_count": refreshed_24h,
        "target": "registered",
        "breaker_tripped": tripped,
    }


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

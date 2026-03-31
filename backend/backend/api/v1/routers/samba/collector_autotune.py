"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, func, case, update as sa_update
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
    from backend.api.v1.routers.samba.collector_common import build_market_registered_conditions
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
    log.info("[오토튠] 등급 분류 완료 — hot %d, warm %d, cold %d", counts["hot"], counts["warm"], counts["cold"])
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
            # 이전 취소 플래그 잔존 방지
            from backend.domain.samba.collector.refresher import clear_bulk_cancel
            clear_bulk_cancel()

            from backend.db.orm import get_write_session
            async with get_write_session() as session:
                from backend.domain.samba.collector.refresher import refresh_products_bulk
                from backend.domain.samba.collector.repository import SambaCollectedProductRepository
                from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
                from backend.domain.samba.warroom.service import SambaMonitorService

                now = datetime.now(timezone.utc)
                repo = SambaCollectedProductRepository(session)

                # ① 등급 자동 분류 (매 사이클) — 실패해도 사이클 계속
                try:
                    await _classify_products(session)
                except Exception as cls_err:
                    log.warning("[오토튠] 등급 분류 실패 (무시하고 진행): %s", cls_err)

                # ② 마켓등록상품만 조회 + hot→warm→cold 정렬
                priority_order = case(
                    (_CP.monitor_priority == "hot", 0),
                    (_CP.monitor_priority == "warm", 1),
                    else_=2,
                )
                # 마켓등록상품 공통 조건 (collector_common에서 통합 관리)
                from backend.api.v1.routers.samba.collector_common import build_market_registered_conditions
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
                    .order_by(priority_order, _CP.last_refreshed_at.asc().nullsfirst())
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
                    products = [p for p in products if not _site_breaker_tripped.get(p.source_site)]
                    skipped_by_breaker = before_filter - len(products)
                    if skipped_by_breaker > 0:
                        tripped_sites = [s for s, v in _site_breaker_tripped.items() if v]
                        log.warning("[오토튠] 서킷브레이커 작동 중 — %s (%d개 제외)", ", ".join(tripped_sites), skipped_by_breaker)

                if products:
                    filtered_count = len(products)
                    # ③ 소싱처별 병렬 갱신
                    results, summary = await refresh_products_bulk(products, max_concurrency=2)

                    # 사이클 완료 로그
                    _err_count = sum(1 for r in results if r.error)
                    _ok_count = len(results) - _err_count
                    _timeout_count = sum(1 for r in results if r.error and "Timeout" in r.error)
                    from backend.domain.samba.collector.refresher import _refresh_log_buffer, _refresh_log_total as _rlt
                    import backend.domain.samba.collector.refresher as _ref_mod
                    _now = datetime.now(timezone.utc)
                    _kst = _now + timedelta(hours=9)
                    _ref_mod._refresh_log_buffer.append({
                        "ts": _now.isoformat(), "site": "MUSINSA", "product_id": "", "name": "",
                        "msg": f"[{_kst.strftime('%H:%M:%S')}] -- 사이클 완료: {_ok_count}건 성공, {_err_count}건 실패 (타임아웃 {_timeout_count}건) / 총 {len(results)}건 --",
                        "level": "info", "source": "autotune",
                    })
                    _ref_mod._refresh_log_total += 1
                    log.info("[오토튠] 사이클 완료: %d성공, %d실패 (타임아웃 %d) / %d건", _ok_count, _err_count, _timeout_count, len(results))

                    # 상품 딕셔너리 사전 구축 (N+1 쿼리 방지)
                    product_map: dict[str, object] = {p.id: p for p in products}

                    # DB 업데이트 + 마켓별 최종 판매가 비교 → 재전송 판정
                    from backend.domain.samba.shipment.service import calc_market_price
                    from backend.domain.samba.policy.repository import SambaPolicyRepository
                    from backend.domain.samba.account.repository import SambaMarketAccountRepository

                    # 정책/계정 캐시 (배치 1회 조회)
                    _policy_cache: dict[str, object] = {}
                    _account_cache: dict[str, object] = {}
                    account_repo = SambaMarketAccountRepository(session)
                    policy_repo = SambaPolicyRepository(session)

                    # 계정 사전 로드: 모든 상품의 registered_accounts에서 account_id 수집
                    _all_account_ids: set[str] = set()
                    for _p in products:
                        if _p.registered_accounts:
                            _all_account_ids.update(_p.registered_accounts)
                    if _all_account_ids:
                        from backend.domain.samba.account.model import SambaMarketAccount
                        _acc_stmt = select(SambaMarketAccount).where(SambaMarketAccount.id.in_(list(_all_account_ids)))
                        _acc_result = await session.exec(_acc_stmt)
                        for _acc in _acc_result.all():
                            _account_cache[_acc.id] = _acc

                    # 재전송 대상: 가격/재고 분리
                    price_retransmit_by_account: dict[str, list[str]] = {}
                    stock_retransmit_by_account: dict[str, list[str]] = {}
                    soldout_ids: list[str] = []
                    price_changed_count = 0

                    for r in results:
                        from backend.domain.samba.emergency import is_emergency_stopped
                        if not _autotune_running_event.is_set() or is_emergency_stopped():
                            log.info("[오토튠] 중단 감지 — 결과 처리 즉시 중단")
                            break
                        if r.error or r.needs_extension:
                            if r.error and r.error != "cancelled":
                                # 사전 구축된 딕셔너리에서 조회 (N+1 제거)
                                product = product_map.get(r.product_id)
                                if product:
                                    await repo.update_async(
                                        r.product_id,
                                        refresh_error_count=(product.refresh_error_count or 0) + 1,
                                        last_refreshed_at=now,
                                    )
                            continue

                        # 사전 구축된 딕셔너리에서 조회 (N+1 제거)
                        product = product_map.get(r.product_id)
                        if not product:
                            continue

                        site = product.source_site or "UNKNOWN"

                        # DB 업데이트 준비
                        updates: dict = {
                            "last_refreshed_at": now,
                            "refresh_error_count": 0,
                        }

                        snapshot: dict = {
                            "date": now.isoformat(),
                            "source": "autotune",
                            "sale_price": r.new_sale_price if r.new_sale_price is not None else product.sale_price,
                            "original_price": r.new_original_price if r.new_original_price is not None else product.original_price,
                            "cost": r.new_cost if r.new_cost is not None else product.cost,
                            "sale_status": r.new_sale_status,
                            "changed": r.changed,
                        }
                        if r.new_options:
                            snapshot["options"] = r.new_options
                        history = list(product.price_history or [])
                        history.insert(0, snapshot)
                        updates["price_history"] = _trim_history(history)

                        # 소싱처 원가 변동 → DB 반영
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
                            # is_sold_out 제거 → sale_status로 통일
                            updates["price_changed_at"] = now
                        elif r.stock_changed:
                            if r.new_options is not None:
                                updates["options"] = r.new_options
                            updates["price_changed_at"] = now

                        # 품절 → 서킷브레이커 + 삭제 대상
                        if r.new_sale_status == "sold_out":
                            _site_consecutive_soldout[site] = _site_consecutive_soldout.get(site, 0) + 1
                            if _site_consecutive_soldout[site] >= SOLDOUT_BREAK_THRESHOLD:
                                _site_breaker_tripped[site] = True
                                log.error("[오토튠] 서킷브레이커 작동! %s 연속 %d개 품절 → %s 중단", site, _site_consecutive_soldout[site], site)
                                await repo.update_async(r.product_id, **updates)
                                continue
                            soldout_ids.append(r.product_id)
                            await repo.update_async(r.product_id, **updates)
                            _site_consecutive_soldout[site] = 0
                            continue
                        else:
                            _site_consecutive_soldout[site] = 0

                        # ★ 마켓별 최종 판매가 비교 — 원가/정책/수수료 무엇이든 바뀌면 재전송
                        new_cost = r.new_cost if r.new_cost is not None else (product.cost or product.sale_price or 0)
                        reg_accounts = product.registered_accounts or []
                        last_sent = product.last_sent_data or {}

                        if product.applied_policy_id:
                            if product.applied_policy_id not in _policy_cache:
                                _policy_cache[product.applied_policy_id] = await policy_repo.get_async(product.applied_policy_id)
                            policy = _policy_cache[product.applied_policy_id]
                        else:
                            policy = None

                        for acc_id in reg_accounts:
                            if acc_id not in _account_cache:
                                _account_cache[acc_id] = await account_repo.get_async(acc_id)
                            acc = _account_cache[acc_id]
                            if not acc:
                                continue
                            market_type = acc.market_type or ""

                            # 정책 적용 후 마켓 최종 판매가 계산
                            if policy and policy.pricing:
                                expected_price = calc_market_price(
                                    new_cost,
                                    policy.pricing,
                                    market_type,
                                    policy.market_policies,
                                )
                            else:
                                expected_price = int(new_cost)

                            # 마지막 전송 가격과 비교
                            acc_last = last_sent.get(acc_id, {})
                            last_price = int(acc_last.get("sale_price", 0)) if acc_last else 0

                            # 가격 변동 → 가격 전송 대상
                            if expected_price != last_price:
                                price_retransmit_by_account.setdefault(acc_id, []).append(r.product_id)
                                price_changed_count += 1
                            # 재고 변동(품절↔리스탁) → 재고 전송 대상
                            if r.stock_changed:
                                stock_retransmit_by_account.setdefault(acc_id, []).append(r.product_id)

                        await repo.update_async(r.product_id, **updates)

                        # 연속 무변동 카운터 업데이트
                        if r.changed or r.stock_changed:
                            # 변동 감지 → 카운터 초기화, 스킵 해제
                            _no_change_count.pop(r.product_id, None)
                            _skip_remaining.pop(r.product_id, None)
                        else:
                            # 변동 없음 → 카운터 증가
                            cnt = _no_change_count.get(r.product_id, 0) + 1
                            _no_change_count[r.product_id] = cnt
                            if cnt >= SKIP_AFTER_NO_CHANGE:
                                _skip_remaining[r.product_id] = SKIP_CYCLES
                                _no_change_count[r.product_id] = 0

                    await session.commit()

                    # ④ 마켓 반영: 가격전송 / 재고전송 / 품절 마켓삭제
                    retransmitted = 0
                    deleted_count = 0
                    _all_price_pids = set()
                    for pids in price_retransmit_by_account.values():
                        _all_price_pids.update(pids)
                    _all_stock_pids = set()
                    for pids in stock_retransmit_by_account.values():
                        _all_stock_pids.update(pids)
                    has_work = bool(_all_price_pids) or bool(_all_stock_pids) or bool(soldout_ids)
                    if has_work:
                        from backend.domain.samba.shipment.repository import SambaShipmentRepository
                        from backend.domain.samba.shipment.service import SambaShipmentService

                        ship_repo = SambaShipmentRepository(session)
                        ship_svc = SambaShipmentService(ship_repo, session)

                        # 가격 변동 → 가격만 전송
                        for acc_id, pids in price_retransmit_by_account.items():
                            try:
                                await ship_svc.start_update(pids, ["price"], [acc_id], skip_unchanged=False)
                                retransmitted += len(pids)
                            except Exception as e:
                                log.error("[오토튠] 가격전송 실패 (%s, %d건): %s", acc_id, len(pids), e)

                        # 재고 변동(품절↔리스탁) → 재고만 전송
                        for acc_id, pids in stock_retransmit_by_account.items():
                            try:
                                await ship_svc.start_update(pids, ["stock"], [acc_id], skip_unchanged=False)
                                retransmitted += len(pids)
                            except Exception as e:
                                log.error("[오토튠] 재고전송 실패 (%s, %d건): %s", acc_id, len(pids), e)

                        # 품절 → 마켓 삭제(DELETE) + DB 삭제
                        import asyncio as _aio
                        from backend.domain.samba.shipment.dispatcher import delete_from_market

                        _del_targets: list[tuple] = []
                        _del_pids: set[str] = set()
                        for pid in soldout_ids:
                            # 사전 구축된 딕셔너리에서 조회 (N+1 제거)
                            product = product_map.get(pid)
                            if not product:
                                continue
                            if getattr(product, "lock_delete", False):
                                log.info("[오토튠] %s 품절이지만 lock_delete=True, 삭제 건너뜀", pid)
                                continue
                            _del_pids.add(pid)
                            product_dict = product.model_dump()
                            if product.registered_accounts:
                                for account_id in product.registered_accounts:
                                    # 사전 로드된 계정 캐시에서 조회 (N+1 제거)
                                    account = _account_cache.get(account_id)
                                    if not account:
                                        continue
                                    m_nos = product.market_product_nos or {}
                                    # 스마트스토어: originProductNo 우선
                                    if account.market_type == "smartstore":
                                        pno = m_nos.get(f"{account_id}_origin", "") or m_nos.get(account_id, "")
                                    else:
                                        pno = m_nos.get(account_id, "")
                                    pd = {**product_dict, "market_product_no": {account.market_type: pno}}
                                    _del_targets.append((pid, pd, account_id, account))

                        _sem = _aio.Semaphore(5)
                        async def _at_del(pid: str, pd: dict, acc: object) -> None:
                            async with _sem:
                                try:
                                    r = await delete_from_market(session, acc.market_type, pd, account=acc)  # type: ignore[union-attr]
                                    if r.get("success"):
                                        log.info("[오토튠] %s → %s 마켓삭제 완료", pid, acc.market_type)  # type: ignore[union-attr]
                                    else:
                                        log.warning("[오토튠] %s → %s 마켓삭제 실패: %s", pid, acc.market_type, r.get("message"))  # type: ignore[union-attr]
                                except Exception as e:
                                    log.error("[오토튠] %s → 마켓삭제 오류: %s", pid, e)

                        if _del_targets:
                            await _aio.gather(*[_at_del(pid, pd, acc) for pid, pd, _, acc in _del_targets])

                        # DB 삭제 안 함 — 품절 상품은 마켓삭제만, DB는 사용자가 수동 삭제
                        deleted_count = len(_del_pids)
                        if _del_pids:
                            log.info("[오토튠] 품절 상품 %d건 마켓삭제 완료 (DB 유지)", deleted_count)

                        await session.commit()

                    monitor = SambaMonitorService(session)
                    await monitor.emit(
                        "scheduler_tick", "info",
                        summary=f"오토튠 — 대상 {filtered_count}건, 갱신 {summary.refreshed}건, 가격전송 {len(_all_price_pids)}건, 재고전송 {len(_all_stock_pids)}건, 삭제 {deleted_count}건",
                        detail={
                            "total": filtered_count,
                            "refreshed": summary.refreshed,
                            "price_transmit": len(_all_price_pids),
                            "stock_transmit": len(_all_stock_pids),
                            "sold_out": summary.sold_out,
                            "retransmitted": retransmitted,
                            "deleted": deleted_count,
                        },
                    )
                    await session.commit()
                    log.info("[오토튠] tick 완료: 대상 %d, 갱신 %d, 가격전송 %d, 재고전송 %d, 삭제 %d", filtered_count, summary.refreshed, len(_all_price_pids), len(_all_stock_pids), deleted_count)
                else:
                    await asyncio.sleep(5)

                _autotune_last_tick = now.isoformat()
                _autotune_cycle_count += 1

        except asyncio.CancelledError:
            log.info("[오토튠] 루프 취소됨")
            break
        except Exception as e:
            log.error("[오토튠] tick 오류: %s", e, exc_info=True)
            # 오토튠 실시간 로그에도 에러 표시
            from backend.domain.samba.collector.refresher import _log_refresh
            _log_refresh("MUSINSA", "", "", f"❌ tick 오류 — {type(e).__name__}: {str(e)[:100]}", level="error")
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

    tripped = {site: count for site, count in _site_consecutive_soldout.items() if _site_breaker_tripped.get(site)}

    # DB 기반 24h 갱신 수 (서버 재시작해도 유지)
    refreshed_24h = 0
    try:
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        async with get_read_session() as rs:
            cnt_stmt = select(func.count(_CP2.id)).where(_CP2.last_refreshed_at >= since_24h)
            refreshed_24h = (await rs.execute(cnt_stmt)).scalar() or 0
    except Exception:
        refreshed_24h = 0

    return {
        "running": _autotune_running_event.is_set() and _autotune_task is not None and not _autotune_task.done(),
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

"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, func, cast, case, update as sa_update, String as _StrType
from sqlalchemy.dialects.postgresql import JSONB
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
_autotune_running = False
_autotune_last_tick: Optional[str] = None
_autotune_cycle_count = 0
_autotune_refreshed_count = 0  # 오토튠에서 갱신한 상품 수 (24시간 표시용)

# 소싱처별 품절 서킷브레이커
SOLDOUT_BREAK_THRESHOLD = 10  # 연속 품절 N개 → 해당 소싱처 중단
_site_consecutive_soldout: dict[str, int] = {}  # {소싱처: 연속 품절 수}
_site_breaker_tripped: dict[str, bool] = {}  # {소싱처: 중단 여부}

# 등급 분류 기준 기간 (일)
CLASSIFY_WINDOW_DAYS = 7


def _is_market_registered(cp: object) -> bool:
    """마켓등록상품 판별 — registered_accounts + market_product_nos 모두 있어야 함."""
    ra = getattr(cp, "registered_accounts", None)
    mn = getattr(cp, "market_product_nos", None)
    if not ra or not mn:
        return False
    if isinstance(ra, list) and len(ra) == 0:
        return False
    if isinstance(mn, dict) and len(mn) == 0:
        return False
    return True


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

    # 마켓등록상품 조건 (collector.py의 market_registered 필터와 동일)
    registered_cond = [
        _CP.registered_accounts.isnot(None),
        cast(_CP.registered_accounts, _StrType) != 'null',
        cast(_CP.registered_accounts, _StrType) != '[]',
        _CP.market_product_nos.isnot(None),
        cast(_CP.market_product_nos, _StrType) != 'null',
        cast(_CP.market_product_nos, _StrType) != '{}',
    ]

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
    global _autotune_running, _autotune_last_tick, _autotune_cycle_count, _autotune_refreshed_count
    import logging
    log = logging.getLogger("autotune")
    log.info("[오토튠] 루프 시작")

    while _autotune_running:
        try:
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
                stmt = (
                    select(_CP)
                    .where(
                        # 마켓등록상품만 (collector.py market_registered 필터와 동일)
                        _CP.registered_accounts.isnot(None),
                        cast(_CP.registered_accounts, _StrType) != 'null',
                        cast(_CP.registered_accounts, _StrType) != '[]',
                        _CP.market_product_nos.isnot(None),
                        cast(_CP.market_product_nos, _StrType) != 'null',
                        cast(_CP.market_product_nos, _StrType) != '{}',
                        # 정책 적용 + 품절 아님
                        _CP.applied_policy_id != None,
                        or_(_CP.is_sold_out == None, _CP.is_sold_out == False),
                    )
                    .order_by(priority_order)
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
                    results, summary = await refresh_products_bulk(products)
                    _autotune_refreshed_count += len(results)

                    # DB 업데이트 + 변동/품절 추적
                    changed_ids: list[str] = []
                    stock_changed_ids: list[str] = []
                    soldout_ids: list[str] = []

                    for r in results:
                        # 건별 중단 체크
                        if not _autotune_running:
                            log.info("[오토튠] 중단 요청 감지 — 결과 처리 중단")
                            break

                        if r.error:
                            product = await repo.get_async(r.product_id)
                            if product:
                                await repo.update_async(
                                    r.product_id,
                                    refresh_error_count=(product.refresh_error_count or 0) + 1,
                                    last_refreshed_at=now,
                                )
                            continue
                        if r.needs_extension:
                            continue

                        product = await repo.get_async(r.product_id)
                        if not product:
                            continue

                        site = product.source_site or "UNKNOWN"

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
                            updates["is_sold_out"] = r.new_sale_status == "sold_out"
                            # 가격/재고 변동 시각 기록 (등급 분류 기준)
                            updates["price_changed_at"] = now
                            old_price = product.sale_price or 0
                            new_price = r.new_sale_price or 0
                            if new_price != old_price:
                                updates["price_before_change"] = old_price
                            # 품절 → 서킷브레이커 + 삭제 대상
                            if r.new_sale_status == "sold_out":
                                _site_consecutive_soldout[site] = _site_consecutive_soldout.get(site, 0) + 1
                                if _site_consecutive_soldout[site] >= SOLDOUT_BREAK_THRESHOLD:
                                    _site_breaker_tripped[site] = True
                                    log.error("[오토튠] 서킷브레이커 작동! %s 연속 %d개 품절 → %s 중단", site, _site_consecutive_soldout[site], site)
                                    continue
                                soldout_ids.append(r.product_id)
                            else:
                                _site_consecutive_soldout[site] = 0
                                changed_ids.append(r.product_id)
                        elif r.stock_changed:
                            if r.new_options is not None:
                                updates["options"] = r.new_options
                            # 재고 변동도 변동 시각 기록 (등급 분류 기준)
                            updates["price_changed_at"] = now
                            _site_consecutive_soldout[site] = 0
                            stock_changed_ids.append(r.product_id)
                        else:
                            _site_consecutive_soldout[site] = 0

                        await repo.update_async(r.product_id, **updates)

                    await session.commit()

                    # ④ 마켓 반영: 변동 → 재전송, 품절 → 마켓삭제 → DB삭제
                    retransmitted = 0
                    deleted_count = 0
                    if changed_ids or stock_changed_ids or soldout_ids:
                        from backend.domain.samba.shipment.repository import SambaShipmentRepository
                        from backend.domain.samba.shipment.service import SambaShipmentService

                        ship_repo = SambaShipmentRepository(session)
                        ship_svc = SambaShipmentService(ship_repo, session)

                        # 가격/재고 변동 → 계정별로 묶어서 배치 재전송
                        _all_retransmit = list(set(changed_ids) | set(stock_changed_ids))
                        _rt_groups: dict[str, list[str]] = {}
                        for pid in _all_retransmit:
                            product = await repo.get_async(pid)
                            if product and product.registered_accounts:
                                acc_key = ",".join(sorted(product.registered_accounts))
                                _rt_groups.setdefault(acc_key, []).append(pid)
                        for acc_key, pids in _rt_groups.items():
                            acc_ids = acc_key.split(",")
                            try:
                                await ship_svc.start_update(pids, [], acc_ids, skip_unchanged=False)
                                retransmitted += len(pids)
                            except Exception as e:
                                log.error("[오토튠] 재전송 실패 (%d건): %s", len(pids), e)

                        # 품절 → 마켓 삭제(DELETE) + DB 삭제
                        import asyncio as _aio
                        from backend.domain.samba.shipment.dispatcher import delete_from_market
                        from backend.domain.samba.account.repository import SambaMarketAccountRepository
                        account_repo = SambaMarketAccountRepository(session)

                        _del_targets: list[tuple] = []
                        _del_pids: set[str] = set()
                        for pid in soldout_ids:
                            product = await repo.get_async(pid)
                            if not product:
                                continue
                            if getattr(product, "lock_delete", False):
                                log.info("[오토튠] %s 품절이지만 lock_delete=True, 삭제 건너뜀", pid)
                                continue
                            _del_pids.add(pid)
                            product_dict = product.model_dump()
                            if product.registered_accounts:
                                for account_id in product.registered_accounts:
                                    account = await account_repo.get_async(account_id)
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

                        # DB 일괄 삭제
                        if _del_pids:
                            from sqlalchemy import delete as sa_delete
                            from sqlmodel import col
                            from backend.domain.samba.collector.model import SambaCollectedProduct
                            await session.exec(sa_delete(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(list(_del_pids))))  # type: ignore[arg-type]
                            deleted_count = len(_del_pids)
                            log.info("[오토튠] 품절 상품 %d건 마켓삭제+DB삭제 완료", deleted_count)

                        await session.commit()

                    monitor = SambaMonitorService(session)
                    await monitor.emit(
                        "scheduler_tick", "info",
                        summary=f"오토튠 — 대상 {filtered_count}건, 갱신 {summary.refreshed}건, 재전송 {retransmitted}건, 삭제 {deleted_count}건",
                        detail={
                            "total": filtered_count,
                            "refreshed": summary.refreshed,
                            "changed": summary.changed,
                            "sold_out": summary.sold_out,
                            "retransmitted": retransmitted,
                            "deleted": deleted_count,
                        },
                    )
                    await session.commit()
                    log.info("[오토튠] tick 완료: 대상 %d, 갱신 %d, 재전송 %d, 삭제 %d", filtered_count, summary.refreshed, retransmitted, deleted_count)
                else:
                    await asyncio.sleep(5)

                _autotune_last_tick = now.isoformat()
                _autotune_cycle_count += 1

        except asyncio.CancelledError:
            log.info("[오토튠] 루프 취소됨")
            break
        except Exception as e:
            log.error("[오토튠] tick 오류: %s", e, exc_info=True)
            # 에러 후 즉시 다음 사이클 시작 (새 세션으로)
            await asyncio.sleep(2)

    log.info("[오토튠] 루프 종료")


class AutotuneStartRequest(BaseModel):
    target: str = "registered"  # 하위 호환용 (무시됨, 항상 마켓등록상품만)


@router.post("/autotune/start")
async def autotune_start(body: AutotuneStartRequest = AutotuneStartRequest()):
    """오토튠 무한 루프 시작 — 마켓등록상품만 대상."""
    global _autotune_task, _autotune_running, _autotune_cycle_count, _autotune_refreshed_count
    from backend.domain.samba.collector.refresher import clear_bulk_cancel
    if _autotune_running:
        return {"ok": True, "status": "already_running"}
    _autotune_running = True
    _autotune_cycle_count = 0
    _autotune_refreshed_count = 0
    clear_bulk_cancel()  # 이전 취소 플래그 초기화
    _autotune_task = asyncio.create_task(_autotune_loop())
    return {"ok": True, "status": "started", "target": "registered"}


@router.post("/autotune/stop")
async def autotune_stop():
    """오토튠 무한 루프 정지 — 진행 중인 갱신도 즉시 중단."""
    global _autotune_task, _autotune_running
    from backend.domain.samba.collector.refresher import request_bulk_cancel
    if not _autotune_running:
        return {"ok": True, "status": "already_stopped"}
    _autotune_running = False
    request_bulk_cancel()  # 벌크 갱신 즉시 중단
    if _autotune_task and not _autotune_task.done():
        _autotune_task.cancel()
    _autotune_task = None
    return {"ok": True, "status": "stopped"}


@router.get("/autotune/status")
async def autotune_status():
    """오토튠 상태 조회."""
    tripped = {site: count for site, count in _site_consecutive_soldout.items() if _site_breaker_tripped.get(site)}
    return {
        "running": _autotune_running,
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "refreshed_count": _autotune_refreshed_count,
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

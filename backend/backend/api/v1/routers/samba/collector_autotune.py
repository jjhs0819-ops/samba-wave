"""SambaWave Collector — 자동조율(오토튠) 엔드포인트."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_
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
_autotune_target = "all"  # all / registered / unregistered


async def _autotune_loop():
    """오토튠 무한 루프 — tick 완료 즉시 다음 tick 시작."""
    global _autotune_running, _autotune_last_tick, _autotune_cycle_count
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

                # target 기반으로 직접 상품 조회 (스케줄러 우회)
                stmt = select(_CP)
                if _autotune_target == "registered":
                    stmt = stmt.where(_CP.registered_accounts != None, _CP.status == "registered")
                elif _autotune_target == "unregistered":
                    stmt = stmt.where(or_(_CP.registered_accounts == None, _CP.status != "registered"))
                # 정책 적용된 상품만 + 품절 제외
                stmt = stmt.where(_CP.applied_policy_id != None)
                stmt = stmt.where(or_(_CP.is_sold_out == None, _CP.is_sold_out == False))
                result = await session.exec(stmt)
                products = list(result.all())
                candidates = products  # 로그용

                if products:
                    filtered_count = len(products)
                    results, summary = await refresh_products_bulk(products)

                    # DB 업데이트 + 변동/품절 추적
                    changed_ids: list[str] = []
                    stock_changed_ids: list[str] = []
                    soldout_ids: list[str] = []

                    for r in results:
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
                            old_price = product.sale_price or 0
                            new_price = r.new_sale_price or 0
                            if new_price != old_price:
                                updates["price_before_change"] = old_price
                                updates["price_changed_at"] = now
                            # 품절이면 soldout, 아니면 가격변동으로 추적
                            if r.new_sale_status == "sold_out":
                                soldout_ids.append(r.product_id)
                            else:
                                changed_ids.append(r.product_id)
                        # 재고만 변동 (가격은 동일)
                        elif r.stock_changed:
                            if r.new_options is not None:
                                updates["options"] = r.new_options
                            stock_changed_ids.append(r.product_id)

                        await repo.update_async(r.product_id, **updates)

                    await session.commit()

                    # 마켓 반영: 가격변동 → 재전송, 재고변동 → 재전송, 품절 → 마켓삭제+DB삭제
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

                        # 품절 → 마켓 판매중지 + DB 삭제
                        import asyncio as _aio
                        from backend.domain.samba.shipment.dispatcher import delete_from_market
                        from backend.domain.samba.account.repository import SambaMarketAccountRepository
                        account_repo = SambaMarketAccountRepository(session)

                        # 1단계: 삭제 대상 수집
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
                                    pd = {**product_dict, "market_product_no": {account.market_type: m_nos.get(account_id, "")}}
                                    _del_targets.append((pid, pd, account_id, account))

                        # 2단계: 마켓 판매중지 병렬 (5개씩)
                        _sem = _aio.Semaphore(5)
                        async def _at_del(pid: str, pd: dict, acc: object) -> None:
                            async with _sem:
                                try:
                                    r = await delete_from_market(session, acc.market_type, pd, account=acc)  # type: ignore[union-attr]
                                    if r.get("success"):
                                        log.info("[오토튠] %s → %s 판매중지 완료", pid, acc.market_type)  # type: ignore[union-attr]
                                    else:
                                        log.warning("[오토튠] %s → %s 판매중지 실패: %s", pid, acc.market_type, r.get("message"))  # type: ignore[union-attr]
                                except Exception as e:
                                    log.error("[오토튠] %s → 마켓 삭제 오류: %s", pid, e)

                        if _del_targets:
                            await _aio.gather(*[_at_del(pid, pd, acc) for pid, pd, _, acc in _del_targets])

                        # 3단계: DB 일괄 삭제
                        if _del_pids:
                            from sqlalchemy import delete as sa_delete
                            from sqlmodel import col
                            from backend.domain.samba.collector.model import SambaCollectedProduct
                            await session.exec(sa_delete(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(list(_del_pids))))  # type: ignore[arg-type]
                            deleted_count = len(_del_pids)
                            log.info("[오토튠] 품절 상품 %d건 일괄 삭제 완료", deleted_count)

                        await session.commit()

                    monitor = SambaMonitorService(session)
                    await monitor.emit(
                        "scheduler_tick", "info",
                        summary=f"오토튠({_autotune_target}) — 대상 {filtered_count}건, {summary.refreshed}건 갱신, 재전송 {retransmitted}건, 품절삭제 {deleted_count}건",
                        detail={
                            "target": _autotune_target,
                            "total": filtered_count,
                            "refreshed": summary.refreshed,
                            "changed": summary.changed,
                            "sold_out": summary.sold_out,
                            "retransmitted": retransmitted,
                            "deleted": deleted_count,
                        },
                    )
                    await session.commit()
                    log.info("[오토튠] tick 완료: 대상 %d, 갱신 %d, 재전송 %d, 품절삭제 %d", filtered_count, summary.refreshed, retransmitted, deleted_count)
                else:
                    # 갱신 대상 없으면 5초 대기 후 재확인
                    await asyncio.sleep(5)

                _autotune_last_tick = now.isoformat()
                _autotune_cycle_count += 1

        except asyncio.CancelledError:
            log.info("[오토튠] 루프 취소됨")
            break
        except Exception as e:
            log.error("[오토튠] tick 오류: %s", e, exc_info=True)
            # 에러 시 10초 대기 후 재시도
            await asyncio.sleep(10)

    log.info("[오토튠] 루프 종료")


class AutotuneStartRequest(BaseModel):
    target: str = "all"  # all / registered / unregistered


@router.post("/autotune/start")
async def autotune_start(body: AutotuneStartRequest = AutotuneStartRequest()):
    """오토튠 무한 루프 시작."""
    global _autotune_task, _autotune_running, _autotune_cycle_count, _autotune_target
    if _autotune_running:
        return {"ok": True, "status": "already_running"}
    _autotune_running = True
    _autotune_cycle_count = 0
    _autotune_target = body.target
    _autotune_task = asyncio.create_task(_autotune_loop())
    return {"ok": True, "status": "started", "target": body.target}


@router.post("/autotune/stop")
async def autotune_stop():
    """오토튠 무한 루프 정지."""
    global _autotune_task, _autotune_running
    if not _autotune_running:
        return {"ok": True, "status": "already_stopped"}
    _autotune_running = False
    if _autotune_task and not _autotune_task.done():
        _autotune_task.cancel()
    _autotune_task = None
    return {"ok": True, "status": "stopped"}


@router.get("/autotune/status")
async def autotune_status():
    """오토튠 상태 조회."""
    return {
        "running": _autotune_running,
        "last_tick": _autotune_last_tick,
        "cycle_count": _autotune_cycle_count,
        "target": _autotune_target,
    }

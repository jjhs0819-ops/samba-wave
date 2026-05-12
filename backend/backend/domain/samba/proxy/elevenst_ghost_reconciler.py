"""11번가 prdNo 누락 매핑 자동 진단.

매일 1회 모든 활성 11번가 계정에 대해:
1. registered_accounts에 계정 id는 있지만 market_product_nos에 prdNo가 없는 상품 탐지
2. sellerPrdCd(=samba product.id)로 11번가 sellerprodcode API 역조회
3. 살아있음/판매종료/미존재로 분류
4. 임계치 초과 시 samba_monitor_event 기록 + WARN 로그
5. ELEVENST_AUTO_CLEAN_MISSING=1 환경변수 켜져 있을 때만 실제 정리 (기본은 알림만)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select

from backend.db.orm import get_write_session
from backend.shutdown_state import is_shutting_down


logger = logging.getLogger("backend.elevenst.ghost_reconciler")

RUN_INTERVAL_SECONDS = 24 * 3600
INITIAL_DELAY_SECONDS = 60 * 30
ALERT_THRESHOLD = 10
MAX_CHECK_PER_ACCOUNT = 2000
THROTTLE_SECONDS = 0.4
AUTO_CLEAN = os.environ.get("ELEVENST_AUTO_CLEAN_MISSING", "").lower() in (
    "1",
    "true",
    "yes",
)
DEAD_STATS = {"104", "105", "106", "108"}


async def _fetch_active_accounts() -> list[dict[str, Any]]:
    async with get_write_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, account_label, api_key, additional_fields "
                        "FROM samba_market_account "
                        "WHERE market_type='11st' AND is_active=true"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def _extract_api_key(acc: dict[str, Any]) -> str:
    af = acc.get("additional_fields") or {}
    if isinstance(af, dict):
        v = af.get("apiKey")
        if v:
            return str(v)
    return str(acc.get("api_key") or "").strip()


async def _log_monitor_event(
    account_id: str,
    account_label: str,
    total_missing: int,
    alive: int,
    dead: int,
    not_found: int,
) -> None:
    """samba_monitor_event에 알림 기록."""
    try:
        from backend.domain.samba.warroom.model import SambaMonitorEvent

        async with get_write_session() as session:
            session.add(
                SambaMonitorEvent(
                    event_type="elevenst_missing_prdno_detected",
                    severity="warning"
                    if total_missing < ALERT_THRESHOLD
                    else "critical",
                    market_type="11st",
                    summary=f"11번가 {account_label} prdNo 누락 매핑 {total_missing}건 감지",
                    detail={
                        "account_id": account_id,
                        "account_label": account_label,
                        "total_missing": total_missing,
                        "alive": alive,
                        "dead": dead,
                        "not_found": not_found,
                        "auto_clean_enabled": AUTO_CLEAN,
                    },
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"[elevenst_ghost] monitor_event 기록 스킵: {e}")


async def _reconcile_one_account(acc: dict[str, Any]) -> dict[str, Any]:
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.elevenst import (
        ElevenstApiError,
        ElevenstClient,
        ElevenstRateLimitError,
    )

    label = acc["account_label"]
    account_id = acc["id"]
    api_key = _extract_api_key(acc)
    if not api_key:
        return {"account_label": label, "skipped": "no api_key"}

    # 대상 수집: registered_accounts에 이 계정 있고 market_product_nos에 prdNo 없는 상품
    async with get_write_session() as session:
        prod_q = (
            select(SambaCollectedProduct)
            .where(SambaCollectedProduct.registered_accounts.op("@>")([account_id]))
            .limit(MAX_CHECK_PER_ACCOUNT)
        )
        products = (await session.execute(prod_q)).scalars().all()

    targets: list[dict[str, Any]] = []
    for p in products:
        nos = p.market_product_nos or {}
        v = nos.get(account_id)
        prd_no = ""
        if isinstance(v, str):
            prd_no = v.strip()
        elif isinstance(v, dict):
            prd_no = str(v.get("prdNo") or v.get("productNo") or "").strip()
        if not prd_no:
            targets.append({"product_id": str(p.id), "name": (p.name or "")[:60]})

    if not targets:
        logger.info(f"[elevenst_ghost] OK {label} prdNo 누락 없음")
        return {
            "account_label": label,
            "total_missing": 0,
            "alive": 0,
            "dead": 0,
            "not_found": 0,
        }

    client = ElevenstClient(api_key)
    alive: list[dict[str, str]] = []
    dead: list[dict[str, str]] = []
    not_found: list[dict[str, str]] = []
    failed = 0

    for t in targets:
        try:
            info = await client.find_by_seller_code(t["product_id"])
        except ElevenstRateLimitError:
            logger.warning(f"[elevenst_ghost] {label} rate limit, 중단")
            break
        except (ElevenstApiError, Exception) as e:
            logger.debug(f"[elevenst_ghost] {label} 조회 실패 {t['product_id']}: {e}")
            failed += 1
            await asyncio.sleep(THROTTLE_SECONDS)
            continue

        entry = {
            "product_id": t["product_id"],
            "name": t["name"],
            "prd_no": info.get("prd_no", ""),
            "sel_stat_cd": info.get("sel_stat_cd", ""),
        }
        if not info.get("found"):
            not_found.append(entry)
        elif info.get("sel_stat_cd") in DEAD_STATS:
            dead.append(entry)
        else:
            alive.append(entry)

        await asyncio.sleep(THROTTLE_SECONDS)

    total_missing = len(alive) + len(dead) + len(not_found)

    severity = "WARN" if total_missing < ALERT_THRESHOLD else "CRIT"
    if total_missing > 0:
        logger.warning(
            f"[elevenst_ghost] {severity} {label} 누락={total_missing} "
            f"(alive={len(alive)} dead={len(dead)} not_found={len(not_found)} failed={failed})"
        )
        await _log_monitor_event(
            account_id, label, total_missing, len(alive), len(dead), len(not_found)
        )

        if AUTO_CLEAN:
            cleaned = await _auto_clean(account_id, api_key, alive, dead, not_found)
            logger.warning(
                f"[elevenst_ghost] {label} AUTO_CLEAN 완료 recovered={cleaned['recovered']} db_cleared={cleaned['db_cleared']}"
            )
    else:
        logger.info(f"[elevenst_ghost] OK {label} 누락 없음 (failed={failed})")

    return {
        "account_label": label,
        "total_missing": total_missing,
        "alive": len(alive),
        "dead": len(dead),
        "not_found": len(not_found),
        "failed": failed,
    }


async def _auto_clean(
    account_id: str,
    api_key: str,
    alive: list[dict[str, str]],
    dead: list[dict[str, str]],
    not_found: list[dict[str, str]],
) -> dict[str, int]:
    """AUTO_CLEAN=on 일 때만 호출. 살아있음은 판매중지+DB정리, 죽음/미존재는 DB만 정리."""
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.elevenst import (
        ElevenstApiError,
        ElevenstClient,
        ElevenstRateLimitError,
    )

    client = ElevenstClient(api_key)
    recovered = 0
    db_cleared = 0

    # 살아있는 케이스: prdNo 저장 → 판매중지 → DB 정리
    for item in alive:
        pid = item["product_id"]
        prd_no = item["prd_no"]
        if not prd_no:
            continue
        try:
            async with get_write_session() as session:
                prod = await session.get(SambaCollectedProduct, pid)
                if prod is None:
                    continue
                nos = dict(prod.market_product_nos or {})
                nos[account_id] = prd_no
                prod.market_product_nos = nos
                flag_modified(prod, "market_product_nos")
                session.add(prod)
                await session.commit()
            await client.delete_product(prd_no)
            recovered += 1
            async with get_write_session() as session:
                prod = await session.get(SambaCollectedProduct, pid)
                if prod is None:
                    continue
                nos2 = dict(prod.market_product_nos or {})
                for k in (account_id, f"{account_id}_origin"):
                    nos2.pop(k, None)
                prod.market_product_nos = nos2
                flag_modified(prod, "market_product_nos")
                regs = [a for a in (prod.registered_accounts or []) if a != account_id]
                prod.registered_accounts = regs
                flag_modified(prod, "registered_accounts")
                session.add(prod)
                await session.commit()
            db_cleared += 1
        except ElevenstRateLimitError:
            logger.warning("[elevenst_ghost] auto_clean rate limit, 중단")
            break
        except ElevenstApiError as e:
            msg = str(e)
            if "삭제된 상품" in msg or "존재하지 않는 상품" in msg:
                dead.append(item)
            else:
                logger.debug(f"[elevenst_ghost] auto_clean stopdisplay 실패 {pid}: {e}")
        except Exception as e:
            logger.debug(f"[elevenst_ghost] auto_clean 예외 {pid}: {e}")
        await asyncio.sleep(THROTTLE_SECONDS)

    # 죽음 + 미존재: DB만 정리
    for bucket in (dead, not_found):
        for item in bucket:
            pid = item["product_id"]
            try:
                async with get_write_session() as session:
                    prod = await session.get(SambaCollectedProduct, pid)
                    if prod is None:
                        continue
                    nos2 = dict(prod.market_product_nos or {})
                    changed = False
                    for k in (account_id, f"{account_id}_origin"):
                        if k in nos2:
                            nos2.pop(k, None)
                            changed = True
                    if changed:
                        prod.market_product_nos = nos2
                        flag_modified(prod, "market_product_nos")
                    regs_old = list(prod.registered_accounts or [])
                    if account_id in regs_old:
                        prod.registered_accounts = [
                            a for a in regs_old if a != account_id
                        ]
                        flag_modified(prod, "registered_accounts")
                        changed = True
                    if changed:
                        session.add(prod)
                        await session.commit()
                        db_cleared += 1
            except Exception as e:
                logger.debug(f"[elevenst_ghost] auto_clean DB정리 예외 {pid}: {e}")

    return {"recovered": recovered, "db_cleared": db_cleared}


async def reconcile_all_accounts_once() -> list[dict[str, Any]]:
    """1회 실행 — 수동 트리거/테스트용."""
    results: list[dict[str, Any]] = []
    accounts = await _fetch_active_accounts()
    logger.info(f"[elevenst_ghost] 대상 11번가 계정 {len(accounts)}개")
    for acc in accounts:
        try:
            r = await _reconcile_one_account(acc)
            results.append(r)
        except Exception as e:
            logger.exception(f"[elevenst_ghost] {acc.get('account_label')} 실패: {e}")
            results.append({"account_label": acc.get("account_label"), "error": str(e)})
    return results


async def ghost_reconciler_loop() -> None:
    """24시간 주기 백그라운드 루프 — lifecycle에서 create_task 로 기동."""
    logger.info(
        f"[elevenst_ghost] 시작 — interval=24h, auto_clean={AUTO_CLEAN}, "
        f"first_run_in={INITIAL_DELAY_SECONDS}s"
    )
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while not is_shutting_down():
        try:
            await reconcile_all_accounts_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[elevenst_ghost] cycle 실패: {e}")
        slept = 0
        while slept < RUN_INTERVAL_SECONDS and not is_shutting_down():
            await asyncio.sleep(min(30, RUN_INTERVAL_SECONDS - slept))
            slept += 30

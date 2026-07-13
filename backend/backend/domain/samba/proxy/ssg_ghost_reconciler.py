"""SSG 판매마켓 역방향 유령 정리.

"삼바엔 없는데 SSG엔 살아있는" 유령상품을 찾아 판매종료한다.
(유령 = 삼바에서 삭제됐으나 SSG엔 판매중으로 남아 주문받고 취소 유발)

매일 1회(또는 엔드포인트 수동 호출) 모든 활성 SSG 계정에 대해:
1. SSG 판매중(sellStatCd != 90) 상품 전량 나열 (getItemList.ssg 페이징)
2. 각 항목의 splVenItemId(= 삼바 수집상품 id = SambaCollectedProduct.id)가
   삼바 DB에 상품으로 존재하는지 대조
3. 존재하지 않으면 유령 → 임계치 초과 시 samba_monitor_event 기록
4. SSG_AUTO_CLEAN_GHOSTS=1 이거나 엔드포인트 dry_run=false 이면
   delete_product(itemId)로 영구판매중지(sellStatCd=90) 실행

판정 앵커를 market_product_nos 가 아닌 splVenItemId ↔ DB product.id 로 잡는다:
SSG splVenItemId 는 등록 시 삼바 상품 id 를 넣은 안정키라, "삼바에 그 상품이
존재하는가"를 직접 확인해 오삭제 위험을 최소화한다(삼바에 물건이 있으면 절대
유령으로 판정하지 않음).

esmplus_ghost_reconciler 패턴을 따름 (마켓 전량 나열 → DB에 없으면 유령 → END).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import bindparam, text

from backend.db.orm import get_write_session
from backend.shutdown_state import is_shutting_down


logger = logging.getLogger("backend.ssg.ghost_reconciler")

RUN_INTERVAL_SECONDS = 24 * 3600
INITIAL_DELAY_SECONDS = 60 * 45  # 부팅 45분 뒤 첫 실행 (다른 reconciler와 시차 분산)
ALERT_THRESHOLD = 20
DELETE_THROTTLE_SECONDS = 0.4
AUTO_CLEAN = os.environ.get("SSG_AUTO_CLEAN_GHOSTS", "").lower() in (
    "1",
    "true",
    "yes",
)


async def _fetch_active_ssg_accounts() -> list[dict[str, Any]]:
    """활성 SSG 계정 전체 조회 (ssg_status_reconciler 헬퍼 재사용)."""
    from backend.domain.samba.proxy.ssg_status_reconciler import (
        _fetch_active_accounts,
    )

    return await _fetch_active_accounts()


def _extract_api_key(acc: dict[str, Any]) -> str:
    from backend.domain.samba.proxy.ssg_status_reconciler import (
        _extract_api_key as _e,
    )

    return _e(acc)


def _extract_site_no(acc: dict[str, Any]) -> str:
    af = acc.get("additional_fields") or {}
    if isinstance(af, dict):
        v = af.get("storeId") or af.get("siteNo")
        if v:
            return str(v)
    return "6004"


def _build_ssg_client(acc: dict[str, Any]):
    from backend.domain.samba.proxy.ssg import SSGClient

    api_key = _extract_api_key(acc)
    if not api_key:
        return None
    return SSGClient(api_key, site_no=_extract_site_no(acc))


async def _scan_ssg_market(client) -> tuple[dict[str, tuple[str, str]], int, int]:
    """SSG 판매중(90 제외) 나열 → {splVenItemId: (itemId, itemNm)}.

    splVenItemId 가 없는 항목은 대조 불가라 유령 판정에서 제외(스킵 카운트만).
    반환: (live_map, market_total, no_splven_count)
    """
    items = await client.list_live_items()
    live: dict[str, tuple[str, str]] = {}
    no_splven = 0
    for it in items:
        if str(it.get("sellStatCd") or "") == "90":
            continue
        iid = str(it.get("itemId") or "").strip()
        if not iid:
            continue
        sv = str(it.get("splVenItemId") or "").strip()
        if not sv:
            no_splven += 1
            continue
        live[sv] = (iid, str(it.get("itemNm") or ""))
    return live, len(items), no_splven


async def _fetch_existing_product_ids(candidate_ids) -> set[str]:
    """candidate splVenItemId 중 삼바 DB(samba_collected_product)에 존재하는 id set.

    id 는 ULID 전역 유니크라 tenant 필터 없이 존재 여부만 확인.
    """
    ids = [str(x) for x in candidate_ids if x]
    if not ids:
        return set()
    found: set[str] = set()
    async with get_write_session() as session:
        for i in range(0, len(ids), 1000):
            chunk = ids[i : i + 1000]
            rows = (
                await session.execute(
                    text(
                        "SELECT id FROM samba_collected_product WHERE id IN :ids"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"ids": chunk},
                )
            ).all()
            found.update(str(r[0]) for r in rows)
    return found


async def _log_monitor_event(
    account_id: str,
    account_label: str,
    ghost_count: int,
    market_total: int,
) -> None:
    try:
        from backend.domain.samba.warroom.model import SambaMonitorEvent

        async with get_write_session() as session:
            session.add(
                SambaMonitorEvent(
                    event_type="ssg_ghost_detected",
                    severity="warning" if ghost_count < ALERT_THRESHOLD else "critical",
                    market_type="ssg",
                    summary=(
                        f"SSG {account_label} 유령상품 {ghost_count}개 감지 "
                        f"(삼바 미존재·SSG 판매중)"
                    ),
                    detail={
                        "account_id": account_id,
                        "account_label": account_label,
                        "market_type": "ssg",
                        "ghosts": ghost_count,
                        "market_total": market_total,
                        "auto_clean_enabled": AUTO_CLEAN,
                    },
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"[ssg_ghost] monitor_event 기록 스킵: {e}")


async def _reconcile_one_account(
    acc: dict[str, Any],
    dry_run: bool | None = None,
    max_delete: int = 100000,
) -> dict[str, Any]:
    """한 SSG 계정 유령 진단(+선택적 종료).

    dry_run=None 이면 AUTO_CLEAN 환경변수를 따름. dry_run=True 진단만,
    dry_run=False 실제 종료.
    """
    account_id = str(acc["id"])
    label = str(acc.get("account_label") or account_id)
    do_clean = (not dry_run) if dry_run is not None else AUTO_CLEAN

    client = _build_ssg_client(acc)
    if client is None:
        logger.info(f"[ssg_ghost] {label} apiKey 없음 — 스킵")
        return {"account_id": account_id, "skipped": "no_apikey"}

    # 마켓 전량 나열
    try:
        live_map, market_total, no_splven = await _scan_ssg_market(client)
    except Exception as e:
        logger.exception(f"[ssg_ghost] {label} 마켓 나열 실패: {e}")
        return {"account_id": account_id, "account_label": label, "error": str(e)}

    splven_ids = set(live_map.keys())
    existing = await _fetch_existing_product_ids(splven_ids)
    ghost_splven = splven_ids - existing

    # 등록경쟁 가드: 나열~판정 사이(수십 초)에 새로 등록된 상품을
    # 유령으로 오판하지 않도록 후보만 DB 재확인.
    if ghost_splven:
        existing2 = await _fetch_existing_product_ids(ghost_splven)
        ghost_splven = ghost_splven - existing2

    ghosts = sorted(
        (live_map[s][0], s, live_map[s][1]) for s in ghost_splven
    )  # (itemId, splVenItemId, itemNm)

    result: dict[str, Any] = {
        "account_id": account_id,
        "account_label": label,
        "market_total": market_total,
        "live_matched": len(splven_ids),
        "no_splven_skipped": no_splven,
        "db_existing": len(existing),
        "ghost_count": len(ghost_splven),
        "dry_run": not do_clean,
        "ghost_sample": [
            {"itemId": i, "splVenItemId": s, "itemNm": n[:30]}
            for i, s, n in ghosts[:20]
        ],
        "deleted": [],
        "failed": [],
    }

    if not ghost_splven:
        logger.info(
            f"[ssg_ghost] {label} 유령 없음 "
            f"(market={market_total} live={len(splven_ids)} no_splven={no_splven})"
        )
        return result

    sev = "WARN" if len(ghost_splven) < ALERT_THRESHOLD else "CRIT"
    logger.warning(
        f"[ssg_ghost] {sev} {label} 유령={len(ghost_splven)} "
        f"market={market_total} db_existing={len(existing)}"
    )
    await _log_monitor_event(account_id, label, len(ghost_splven), market_total)

    if not do_clean:
        return result

    # 실제 종료 (sellStatCd=90). 멱등이라 이미 90이어도 안전.
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for iid, _sv, _nm in ghosts[:max_delete]:
        try:
            await client.delete_product(iid)
            deleted.append(iid)
        except Exception as e:
            failed.append({"itemId": iid, "error": str(e)[:200]})
        await asyncio.sleep(DELETE_THROTTLE_SECONDS)

    result["deleted"] = deleted
    result["failed"] = failed
    logger.info(f"[ssg_ghost] {label} 종료완료={len(deleted)} 실패={len(failed)}")
    return result


async def reconcile_all_accounts_once() -> dict[str, Any]:
    """1회 전 계정 진단 실행 (24h 루프 / 수동 트리거 공용)."""
    accounts = await _fetch_active_ssg_accounts()
    if not accounts:
        logger.info("[ssg_ghost] 활성 SSG 계정 없음 — 스킵")
        return {"accounts": [], "total_ghosts": 0, "total_deleted": 0}

    results: list[dict[str, Any]] = []
    for acc in accounts:
        try:
            r = await _reconcile_one_account(acc)
            results.append(r)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[ssg_ghost] 계정 진단 실패 {acc.get('id')}: {e}")
            results.append({"account_id": acc.get("id"), "error": str(e)})

    total_ghosts = sum(int(r.get("ghost_count") or 0) for r in results)
    total_deleted = sum(len(r.get("deleted") or []) for r in results)
    logger.info(
        f"[ssg_ghost] 완료 auto_clean={AUTO_CLEAN} "
        f"total_ghosts={total_ghosts} total_deleted={total_deleted}"
    )
    return {
        "accounts": results,
        "total_ghosts": total_ghosts,
        "total_deleted": total_deleted,
    }


async def ghost_reconciler_loop() -> None:
    """24시간 주기 백그라운드 루프 — lifecycle에서 create_task 로 기동."""
    logger.info(
        f"[ssg_ghost] 시작 — interval=24h auto_clean={AUTO_CLEAN} "
        f"first_run_in={INITIAL_DELAY_SECONDS}s"
    )
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while not is_shutting_down():
        try:
            await reconcile_all_accounts_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[ssg_ghost] cycle 실패(다음 cycle에 재시도): {e}")
        slept = 0
        while slept < RUN_INTERVAL_SECONDS and not is_shutting_down():
            await asyncio.sleep(min(60, RUN_INTERVAL_SECONDS - slept))
            slept += 60

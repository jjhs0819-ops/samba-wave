"""ESMPlus(지마켓/옥션) 유령상품 일일 자동 진단.

매일 1회 모든 활성 gmarket/auction 계정에 대해:
1. ESMPlus API(search_products 전체 페이징)로 마켓 등록 상품 목록 수집
2. DB registered_accounts에 계정이 있는 상품의 market_product_nos 와 diff
3. 마켓에 있지만 DB 에서 추적되지 않는 상품(orphan) 감지
4. 임계치 초과 시 samba_monitor_event 기록 → 상품관리 배너 노출
5. ESM_AUTO_CLEAN_GHOSTS=1 환경변수 켜져 있으면 자동 판매중지+삭제 (기본=진단만)

판매중지 후 삭제하는 2단계 절차: ESM 은 판매중 상품 직접 삭제 불가.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy import text

from backend.db.orm import get_write_session
from backend.shutdown_state import is_shutting_down


logger = logging.getLogger("backend.esm.ghost_reconciler")

RUN_INTERVAL_SECONDS = 24 * 3600
INITIAL_DELAY_SECONDS = 60 * 35  # 부팅 35분 뒤 첫 실행 (다른 reconciler와 분산)
ALERT_THRESHOLD = 20
PAGE_THROTTLE_SECONDS = 2.5  # 30/min 제한 → 2.5s 간격
MAX_PAGES = 200  # 계정당 최대 200페이지(10,000건) 스캔
AUTO_CLEAN = os.environ.get("ESM_AUTO_CLEAN_GHOSTS", "").lower() in (
    "1",
    "true",
    "yes",
)


async def _fetch_active_esm_accounts() -> list[dict[str, Any]]:
    """활성 gmarket/auction 계정 전체 조회."""
    async with get_write_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, account_label, seller_id, additional_fields, market_type "
                        "FROM samba_market_account "
                        "WHERE market_type IN ('gmarket', 'auction') AND is_active = true"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


async def _build_esm_client(acc: dict[str, Any]):
    """계정 정보로 ESMPlusClient 생성."""
    from backend.domain.samba.proxy.esmplus import (
        ESMPlusClient,
        resolve_esm_credentials,
    )

    site = acc["market_type"]  # "gmarket" or "auction"

    class _Stub:
        def __init__(self, af: dict) -> None:
            self.additional_fields = af

    stub = _Stub(acc.get("additional_fields") or {})
    async with get_write_session() as session:
        hosting_id, secret_key = await resolve_esm_credentials(session, stub)

    if not hosting_id or not secret_key:
        return None

    seller_id = str(acc.get("seller_id") or "").strip()
    if not seller_id:
        return None

    return ESMPlusClient(hosting_id, secret_key, seller_id, site=site)


async def _scan_market_goods(client) -> set[str]:
    """ESMPlus 마켓에 등록된 goodsNo 전체 수집 (페이지 throttle 적용)."""
    goods_nos: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        if page > 1:
            await asyncio.sleep(PAGE_THROTTLE_SECONDS)
        try:
            r = await client.search_products({"pageIndex": page, "pageSize": 50})
        except Exception as e:
            logger.warning(f"[esm_ghost] 스캔 중단 page={page}: {e}")
            break
        items = r.get("items") or []
        if not items:
            break
        for it in items:
            master = str(it.get("goodsNo") or "").strip()
            if master and master not in ("0", "0.0"):
                goods_nos.add(master)
            # siteGoodsNo 도 추가 (DB 저장 값이 siteGoodsNo 인 경우 커버)
            site_key = client.cfg["siteKey"].lower()
            sno = str((it.get("siteGoodsNo") or {}).get(site_key) or "").strip()
            if sno and sno not in ("0", "0.0"):
                goods_nos.add(sno)
        if len(items) < 50:
            break
    return goods_nos


async def _fetch_db_tracked_nos(account_id: str) -> set[str]:
    """DB에서 이 account_id 로 추적 중인 market_product_nos 값 **전부** 수집.

    market_product_nos 에는 계정당 여러 키가 저장된다:
      {aid}(평문) / {aid}_master(ESM goodsNo) / {aid}_site(siteGoodsNo) / {aid}_pid / {aid}_origin
    _scan_market_goods 는 goodsNo(master)+siteGoodsNo 를 둘 다 수집하므로, 추적분도
    프리픽스로 시작하는 **모든 키의 값**을 모아야 정상 상품 master 가 orphan 으로 오분류돼
    삭제되는 사고를 막는다 (#656 — 평문키만 봐서 _master/_site 만 있는 상품 전멸 위험).

    주의:
    - jsonb_each_text 는 object 가 아닌 값(null/array)에 호출 시 에러 → jsonb_typeof 가드 필수
      (market_product_nos 는 null 2만+, array 100+ 존재 실측). raw SQL 함정.
    - LIKE 프리픽스의 '_' 는 와일드카드라 ESCAPE 로 리터럴화 (오버매칭 차단).
    - registered_accounts @> 조건 제거 — 배열 마크 어긋난 행(번호는 있으나 배열 누락)도
      추적분에 포함해 보수적으로 오삭제 방지.
    - '__claiming__' 등 __ 표식값 제외.
    """
    like_prefix = (
        account_id.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"
    )
    async with get_write_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT kv.value AS no "
                    "FROM samba_collected_product p, "
                    "     jsonb_each_text(p.market_product_nos::jsonb) kv "
                    "WHERE jsonb_typeof(p.market_product_nos::jsonb) = 'object' "
                    "  AND kv.key LIKE :pfx ESCAPE '\\' "
                    "  AND kv.value NOT LIKE '\\_\\_%' ESCAPE '\\'"
                ).bindparams(pfx=like_prefix)
            )
        ).all()
    return {str(r[0]) for r in rows if r[0]}


async def _log_monitor_event(
    account_id: str,
    account_label: str,
    market_type: str,
    orphans: int,
    market_total: int,
) -> None:
    try:
        from backend.domain.samba.warroom.model import SambaMonitorEvent

        async with get_write_session() as session:
            session.add(
                SambaMonitorEvent(
                    event_type="esm_ghost_detected",
                    severity="warning" if orphans < ALERT_THRESHOLD else "critical",
                    market_type=market_type,
                    summary=(
                        f"ESM({market_type}) {account_label} 유령상품 {orphans}개 감지"
                    ),
                    detail={
                        "account_id": account_id,
                        "account_label": account_label,
                        "market_type": market_type,
                        "ghosts": orphans,
                        "market_total": market_total,
                        "auto_clean_enabled": AUTO_CLEAN,
                    },
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"[esm_ghost] monitor_event 기록 스킵: {e}")


async def _stop_and_delete(client, goods_no: str) -> str:
    """판매중지 후 삭제. 결과: 'deleted' | 'failed:<사유>'"""
    try:
        await client.update_sell_status(
            goods_no,
            {"IsSell": {"Gmkt": False, "Iac": False}},
        )
        await asyncio.sleep(2.0)
    except Exception as e:
        logger.warning(f"[esm_ghost] 판매중지 실패 goodsNo={goods_no}: {e}")
    try:
        await client.delete_product(goods_no)
        return "deleted"
    except Exception as e:
        return f"failed:{e}"


async def _reconcile_one_account(acc: dict[str, Any]) -> dict[str, Any]:
    account_id = str(acc["id"])
    label = str(acc.get("account_label") or account_id)
    market_type = str(acc.get("market_type") or "")

    client = await _build_esm_client(acc)
    if client is None:
        logger.info(f"[esm_ghost] {label} 클라이언트 생성 실패 — 스킵")
        return {"account_id": account_id, "skipped": "no_credentials"}

    # 마켓 전체 상품 스캔
    try:
        market_nos = await _scan_market_goods(client)
    except Exception as e:
        logger.exception(f"[esm_ghost] {label} 마켓 스캔 실패: {e}")
        return {"account_id": account_id, "error": str(e)}

    market_total = len(market_nos)

    # DB 추적 번호 수집
    db_nos = await _fetch_db_tracked_nos(account_id)

    # orphan = 마켓에 있지만 DB 에서 추적 안 됨
    orphans = market_nos - db_nos
    orphan_count = len(orphans)

    result: dict[str, Any] = {
        "account_id": account_id,
        "account_label": label,
        "market_type": market_type,
        "market_total": market_total,
        "db_tracked": len(db_nos),
        "orphan_count": orphan_count,
        "deleted": [],
        "delete_failed": [],
    }

    if orphan_count == 0:
        logger.info(f"[esm_ghost] {label} 유령상품 없음 (market={market_total})")
        return result

    severity = "WARN" if orphan_count < ALERT_THRESHOLD else "CRIT"
    logger.warning(
        f"[esm_ghost] {severity} {label}({market_type}) "
        f"유령={orphan_count} market={market_total} db={len(db_nos)}"
    )

    await _log_monitor_event(account_id, label, market_type, orphan_count, market_total)

    if not AUTO_CLEAN:
        return result

    # AUTO_CLEAN=1 일 때만 실제 삭제
    deleted: list[str] = []
    failed: list[str] = []
    for gno in list(orphans):
        res = await _stop_and_delete(client, gno)
        if res == "deleted":
            deleted.append(gno)
        else:
            failed.append(f"{gno}:{res}")
        await asyncio.sleep(PAGE_THROTTLE_SECONDS)

    result["deleted"] = deleted
    result["delete_failed"] = failed
    logger.info(f"[esm_ghost] {label} 삭제완료={len(deleted)} 실패={len(failed)}")
    return result


async def reconcile_all_accounts_once() -> dict[str, Any]:
    """1회 전 계정 진단 실행. 수동 트리거/테스트용."""
    accounts = await _fetch_active_esm_accounts()
    if not accounts:
        logger.info("[esm_ghost] 활성 ESM 계정 없음 — 스킵")
        return {"accounts": [], "total_orphans": 0, "total_deleted": 0}

    results: list[dict[str, Any]] = []
    for acc in accounts:
        try:
            r = await _reconcile_one_account(acc)
            results.append(r)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[esm_ghost] 계정 진단 실패 {acc.get('id')}: {e}")
            results.append({"account_id": acc.get("id"), "error": str(e)})

    total_orphans = sum(int(r.get("orphan_count") or 0) for r in results)
    total_deleted = sum(len(r.get("deleted") or []) for r in results)
    logger.info(
        f"[esm_ghost] 완료 auto_clean={AUTO_CLEAN} "
        f"total_orphans={total_orphans} total_deleted={total_deleted}"
    )
    return {
        "accounts": results,
        "total_orphans": total_orphans,
        "total_deleted": total_deleted,
    }


async def ghost_reconciler_loop() -> None:
    """24시간 주기 백그라운드 루프 — lifecycle에서 create_task 로 기동."""
    logger.info(
        f"[esm_ghost] 시작 — interval=24h auto_clean={AUTO_CLEAN} "
        f"first_run_in={INITIAL_DELAY_SECONDS}s"
    )
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while not is_shutting_down():
        try:
            await reconcile_all_accounts_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[esm_ghost] cycle 실패(다음 cycle에 재시도): {e}")
        slept = 0
        while slept < RUN_INTERVAL_SECONDS and not is_shutting_down():
            await asyncio.sleep(min(60, RUN_INTERVAL_SECONDS - slept))
            slept += 60

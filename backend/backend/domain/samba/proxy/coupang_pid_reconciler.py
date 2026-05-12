"""쿠팡 노출상품ID(productId) / 옵션ID(vendorItemId) 백필 reconciler.

문제: 쿠팡 register API 응답에는 sellerProductId 만 오고, 등록 직후
get_product 호출 시점에는 임시저장 상태라 productId/vendorItemId 가 null 인 경우가 있음.
이 두 값이 없으면 "쿠팡 판매페이지" 버튼이 잘못된 sellerProductId 로 vp/products URL 을
만들어 404 페이지로 이동함.

해결: 30분 주기로 노출ID(_pid) 가 비어있는 쿠팡 등록상품만 골라 GET 으로 재조회하여
productId/vendorItemId 를 받으면 DB 에 채움. 이미 채워진 건은 다음 사이클부터 자동 제외.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import cast, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select

from backend.db.orm import get_write_session
from backend.shutdown_state import is_shutting_down


logger = logging.getLogger("backend.coupang.pid_reconciler")

RUN_INTERVAL_SECONDS = 30 * 60  # 30분 주기
INITIAL_DELAY_SECONDS = 60 * 5  # 부팅 후 5분 뒤 첫 실행
MAX_CHECK_PER_ACCOUNT = 50  # 1사이클당 계정별 최대 50건 (쿠팡 호출 제한 고려)
THROTTLE_SECONDS = 0.5  # GET 호출 간격


async def _fetch_active_coupang_accounts() -> list[dict[str, Any]]:
    async with get_write_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, account_label, api_key, api_secret, seller_id, "
                        "additional_fields "
                        "FROM samba_market_account "
                        "WHERE market_type='coupang' AND is_active=true"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def _extract_credentials(acc: dict[str, Any]) -> tuple[str, str, str]:
    af = acc.get("additional_fields") or {}
    if not isinstance(af, dict):
        af = {}
    access_key = str(af.get("accessKey") or acc.get("api_key") or "").strip()
    secret_key = str(af.get("secretKey") or acc.get("api_secret") or "").strip()
    vendor_id = str(af.get("vendorId") or acc.get("seller_id") or "").strip()
    return access_key, secret_key, vendor_id


async def _reconcile_one_account(acc: dict[str, Any]) -> dict[str, Any]:
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.coupang import CoupangApiError, CoupangClient

    label = acc["account_label"]
    account_id = acc["id"]
    access_key, secret_key, vendor_id = _extract_credentials(acc)
    if not access_key or not secret_key:
        return {"account_label": label, "skipped": "no credentials"}

    # _pid 가 비어있는(또는 키 자체가 없는) 쿠팡 등록상품 선별
    # registered_accounts @> [account_id] 인 상품 중
    # market_product_nos -> account_id 는 있고 market_product_nos -> account_id+'_pid' 는 비어있음
    pid_key = f"{account_id}_pid"
    async with get_write_session() as session:
        stmt = (
            select(SambaCollectedProduct)
            .where(
                SambaCollectedProduct.registered_accounts.op("@>")(
                    cast([account_id], JSONB)
                )
            )
            .where(
                text(
                    "(samba_collected_product.market_product_nos ->> :acc_id) "
                    "IS NOT NULL"
                )
            )
            .where(
                text(
                    "COALESCE("
                    "samba_collected_product.market_product_nos ->> :pid_key, '') = ''"
                )
            )
            .params(acc_id=account_id, pid_key=pid_key)
            .limit(MAX_CHECK_PER_ACCOUNT)
        )
        products = (await session.execute(stmt)).scalars().all()

    if not products:
        logger.info(f"[coupang_pid] OK {label} 백필 대상 없음")
        return {"account_label": label, "checked": 0, "filled": 0, "still_empty": 0}

    client = CoupangClient(access_key, secret_key, vendor_id)
    filled = 0
    still_empty = 0
    failed = 0

    for prod in products:
        nos = prod.market_product_nos or {}
        seller_product_id = str(nos.get(account_id) or "").strip()
        if not seller_product_id or not seller_product_id.isdigit():
            continue

        try:
            gr = await client.get_product(seller_product_id)
        except CoupangApiError as e:
            logger.debug(
                f"[coupang_pid] {label} GET 실패 spid={seller_product_id}: {e}"
            )
            failed += 1
            await asyncio.sleep(THROTTLE_SECONDS)
            continue
        except Exception as e:
            logger.debug(
                f"[coupang_pid] {label} GET 예외 spid={seller_product_id}: {e}"
            )
            failed += 1
            await asyncio.sleep(THROTTLE_SECONDS)
            continue

        inner = gr.get("data", gr) if isinstance(gr, dict) else {}
        product_id = ""
        vendor_item_id = ""
        if isinstance(inner, dict):
            _pid = inner.get("productId")
            if _pid:
                product_id = str(_pid)
            _items = inner.get("items") or []
            if _items and isinstance(_items[0], dict):
                _vid = _items[0].get("vendorItemId")
                if _vid:
                    vendor_item_id = str(_vid)

        if not product_id:
            still_empty += 1
            await asyncio.sleep(THROTTLE_SECONDS)
            continue

        # DB 업데이트
        try:
            async with get_write_session() as session:
                latest = await session.get(SambaCollectedProduct, prod.id)
                if latest is None:
                    continue
                nos2 = dict(latest.market_product_nos or {})
                nos2[pid_key] = product_id
                if vendor_item_id:
                    nos2[f"{account_id}_vid"] = vendor_item_id
                latest.market_product_nos = nos2
                flag_modified(latest, "market_product_nos")
                session.add(latest)
                await session.commit()
            filled += 1
        except Exception as e:
            logger.warning(
                f"[coupang_pid] {label} DB 업데이트 실패 spid={seller_product_id}: {e}"
            )

        await asyncio.sleep(THROTTLE_SECONDS)

    if filled or still_empty:
        logger.info(
            f"[coupang_pid] {label} 체크={len(products)} 채움={filled} "
            f"여전히 없음={still_empty} 실패={failed}"
        )

    return {
        "account_label": label,
        "checked": len(products),
        "filled": filled,
        "still_empty": still_empty,
        "failed": failed,
    }


async def reconcile_all_accounts_once() -> list[dict[str, Any]]:
    """1회 실행 — 수동 트리거/테스트용."""
    results: list[dict[str, Any]] = []
    accounts = await _fetch_active_coupang_accounts()
    logger.info(f"[coupang_pid] 대상 쿠팡 계정 {len(accounts)}개")
    for acc in accounts:
        try:
            r = await _reconcile_one_account(acc)
            results.append(r)
        except Exception as e:
            logger.exception(f"[coupang_pid] {acc.get('account_label')} 실패: {e}")
            results.append({"account_label": acc.get("account_label"), "error": str(e)})
    return results


async def pid_reconciler_loop() -> None:
    """30분 주기 백그라운드 루프 — lifecycle 에서 create_task 로 기동."""
    logger.info(
        f"[coupang_pid] 시작 — interval={RUN_INTERVAL_SECONDS}s, "
        f"first_run_in={INITIAL_DELAY_SECONDS}s"
    )
    await asyncio.sleep(INITIAL_DELAY_SECONDS)
    while not is_shutting_down():
        try:
            await reconcile_all_accounts_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[coupang_pid] cycle 실패: {e}")
        slept = 0
        while slept < RUN_INTERVAL_SECONDS and not is_shutting_down():
            await asyncio.sleep(min(30, RUN_INTERVAL_SECONDS - slept))
            slept += 30

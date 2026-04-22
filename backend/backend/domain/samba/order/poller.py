"""주문 자동 폴링 — 새 주문 감지 시 카카오톡 알림 발송."""

import asyncio
import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

ORDER_POLL_INTERVAL = int(os.environ.get("ORDER_POLL_INTERVAL_SECONDS", str(30 * 60)))


async def _fetch_new_order_numbers(session) -> dict[str, list[str]]:
    """각 마켓 계정에서 최근 1일치 주문 번호를 조회하고, DB에 없는 신규 건만 반환."""
    from sqlalchemy import text as _text
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount

    result = await session.exec(
        select(SambaMarketAccount).where(SambaMarketAccount.is_active == True)  # noqa: E712
    )
    accounts = result.all()

    new_by_market: dict[str, list[str]] = defaultdict(list)

    for account in accounts:
        market_type = account.market_type
        extras = account.additional_fields or {}
        label = account.market_name or market_type

        try:
            raw_order_numbers: list[str] = []

            if market_type == "smartstore":
                from backend.domain.samba.proxy.smartstore import SmartStoreClient

                client_id = extras.get("clientId", "") or account.api_key or ""
                client_secret = (
                    extras.get("clientSecret", "") or account.api_secret or ""
                )
                if not client_id or not client_secret:
                    continue
                client = SmartStoreClient(client_id, client_secret)
                raw_orders = await client.get_orders(days=1)
                for ro in raw_orders:
                    po = ro.get("productOrder", ro)
                    oid = po.get("productOrderId", "")
                    if oid:
                        raw_order_numbers.append(oid)

            elif market_type == "lotteon":
                from backend.domain.samba.proxy.lotteon import LotteonClient

                vendor_id = extras.get("vendorId", "") or account.seller_id or ""
                api_key = extras.get("apiKey", "") or account.api_key or ""
                if not vendor_id or not api_key:
                    continue
                client = LotteonClient(vendor_id, api_key)
                raw_orders = await client.get_delivery_orders(days=1)
                for ro in raw_orders:
                    oid = str(ro.get("ordNo", "") or ro.get("order_number", ""))
                    if oid:
                        raw_order_numbers.append(oid)

            else:
                continue

            if not raw_order_numbers:
                continue

            # DB에 이미 있는 order_number 필터링
            rows = await session.execute(
                _text(
                    "SELECT order_number FROM samba_order "
                    "WHERE order_number = ANY(:nums) AND channel_id = :cid"
                ),
                {"nums": raw_order_numbers, "cid": account.id},
            )
            existing = {r[0] for r in rows}
            fresh = [n for n in raw_order_numbers if n not in existing]

            if fresh:
                new_by_market[label].extend(fresh)
                logger.info("[주문폴러] %s: 신규 주문 %d건 감지", label, len(fresh))

        except Exception as exc:
            logger.warning("[주문폴러] %s 조회 실패: %s", label, exc)

    return dict(new_by_market)


async def start_order_poller() -> None:
    """백그라운드 주문 폴링 루프 (lifecycle.py에서 asyncio.create_task로 실행)."""
    from backend.db.orm import get_write_session
    from backend.utils.kakao_notify import send_kakao_message

    # 서버 완전 기동 대기
    await asyncio.sleep(60)
    logger.info("[주문폴러] 시작 (간격: %d초)", ORDER_POLL_INTERVAL)

    while True:
        try:
            async with get_write_session() as session:
                new_by_market = await _fetch_new_order_numbers(session)

            if new_by_market:
                total = sum(len(v) for v in new_by_market.values())
                lines = [f"🛒 새 주문 {total}건 감지"]
                for market, nums in new_by_market.items():
                    lines.append(f"  {market}: {len(nums)}건")
                lines.append("\n동기화 버튼을 눌러 주문을 확인하세요.")
                await send_kakao_message("\n".join(lines))

        except asyncio.CancelledError:
            logger.info("[주문폴러] 종료")
            return
        except Exception as exc:
            logger.warning("[주문폴러] 오류 발생: %s", exc)

        await asyncio.sleep(ORDER_POLL_INTERVAL)

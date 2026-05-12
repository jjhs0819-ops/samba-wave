"""lastChangedType 생략 호출 검증 — 이종영 productOrderId 포함 여부."""

import asyncio
import sys

sys.path.insert(0, "/app/backend")

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from backend.db.orm import get_read_session
from backend.domain.samba.proxy.smartstore import SmartStoreClient


TARGET = "2026051197491491"


async def main():
    async with get_read_session() as session:
        row = await session.execute(
            text(
                """
                SELECT additional_fields->>'clientId' AS cid,
                       additional_fields->>'clientSecret' AS csec
                FROM samba_market_account
                WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
                """
            )
        )
        rec = row.fetchone()
        cid, csec = rec

    client = SmartStoreClient(cid, csec)

    kst = timezone(timedelta(hours=9))
    # 1) 5일 윈도우
    since_5d = (datetime.now(kst) - timedelta(days=5)).strftime(
        "%Y-%m-%dT%H:%M:%S.000+09:00"
    )
    # 2) 어제 윈도우 (코드의 recent_str)
    since_1d = (datetime.now(kst) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.000+09:00"
    )

    for label, since_str in [("5일", since_5d), ("1일", since_1d)]:
        print(f"\n=== {label} 윈도우 lastChangedType 생략 호출 (since={since_str}) ===")
        try:
            result = await client._call_api(
                "GET",
                "/v1/pay-order/seller/product-orders/last-changed-statuses",
                params={"lastChangedFrom": since_str},
            )
        except Exception as e:
            print(f"ERROR: {e}")
            continue

        data = result.get("data", result) if isinstance(result, dict) else {}
        statuses = (
            (data.get("lastChangeStatuses") or data.get("lastChangedStatuses") or [])
            if isinstance(data, dict)
            else []
        )
        print(f"총 응답: {len(statuses)}건")
        ids = [s.get("productOrderId") for s in statuses if s.get("productOrderId")]
        in_resp = TARGET in ids
        print(f"이종영({TARGET}) 포함: {in_resp}")
        if in_resp:
            for s in statuses:
                if s.get("productOrderId") == TARGET:
                    print(f"  → 이벤트 상세: {s}")
                    break
        # 처음 10개 productOrderId 출력
        print(f"응답 productOrderId 샘플: {ids[:10]}")


asyncio.run(main())

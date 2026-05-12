"""last-changed-statuses 응답 raw 전체 구조 확인 + 이종영 productOrderId 탐색."""

import asyncio
import json
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
        cid, csec = row.fetchone()

    client = SmartStoreClient(cid, csec)
    kst = timezone(timedelta(hours=9))

    # 가장 좁은 윈도우 — 이종영 결제시점 직전 (5/11 10:00 KST)
    since_str = "2026-05-11T10:00:00.000+09:00"
    print(f"=== since={since_str} (이종영 결제 12분 전부터) ===")
    result = await client._call_api(
        "GET",
        "/v1/pay-order/seller/product-orders/last-changed-statuses",
        params={"lastChangedFrom": since_str},
    )
    print("응답 raw (전체):")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:4000])

    data = result.get("data", result) if isinstance(result, dict) else {}
    statuses = (
        data.get("lastChangeStatuses") or data.get("lastChangedStatuses") or []
    ) if isinstance(data, dict) else []
    ids = [s.get("productOrderId") for s in statuses]
    print(f"\n→ 응답 productOrderId 전체 ({len(ids)}건): {ids}")
    print(f"→ 이종영 포함: {TARGET in ids}")

    # 응답 dict 키 출력 (페이지네이션 확인)
    if isinstance(data, dict):
        print(f"\n→ data 최상위 키: {list(data.keys())}")
        for k in ("more", "moreData", "nextPage", "pageToken", "page", "totalCount", "count"):
            if k in data:
                print(f"   {k}: {data[k]}")

    # 만약 more=true 라면 nextPage 또는 lastChangedFrom 증가 호출
    if isinstance(data, dict) and (data.get("more") or data.get("moreData")):
        print("\n=== more=true — nextPage 호출 시도 ===")
        # 가장 마지막 productOrderId의 lastChangedDate 이후로 재호출
        if statuses:
            last_changed = statuses[-1].get("lastChangedDate", "")
            print(f"마지막 lastChangedDate: {last_changed}")
            if last_changed:
                result2 = await client._call_api(
                    "GET",
                    "/v1/pay-order/seller/product-orders/last-changed-statuses",
                    params={"lastChangedFrom": last_changed},
                )
                data2 = result2.get("data", result2) if isinstance(result2, dict) else {}
                statuses2 = (
                    data2.get("lastChangeStatuses") or data2.get("lastChangedStatuses") or []
                )
                ids2 = [s.get("productOrderId") for s in statuses2]
                print(f"2페이지 응답 ({len(ids2)}건): {ids2}")
                print(f"2페이지에 이종영 포함: {TARGET in ids2}")


asyncio.run(main())

"""이종영 주문 DB 재확인 + 각 lastChangedType별 포함 여부 점검."""

import asyncio
import sys
sys.path.insert(0, "/app/backend")

from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from backend.db.orm import get_read_session
from backend.domain.samba.proxy.smartstore import SmartStoreClient


TARGET = "2026051197491491"


async def main():
    # 1) DB 재확인
    async with get_read_session() as session:
        rows = await session.execute(
            text(
                "SELECT id, order_number, customer_name, shipping_status, channel_name, "
                "paid_at, created_at FROM samba_order WHERE order_number = :on"
            ),
            {"on": TARGET},
        )
        recs = rows.fetchall()
        print(f"DB samba_order order_number={TARGET}: {len(recs)}건")
        for r in recs:
            print(f"  {dict(r._mapping)}")

        # 2) 가디 인증 가져오기
        a = await session.execute(text("""
            SELECT additional_fields->>'clientId' AS cid,
                   additional_fields->>'clientSecret' AS csec
            FROM samba_market_account
            WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
        """))
        cid, csec = a.fetchone()

    client = SmartStoreClient(cid, csec)
    kst = timezone(timedelta(hours=9))

    # 3) 각 lastChangedType별 호출하여 포함 여부 점검
    since = (datetime.now(kst) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
    print(f"\nsince = {since}")
    print("=" * 80)
    # 코드의 13개 + 새로 발견된 정확 값들
    types_to_test = [
        "PAYED", "PURCHASE_DECIDED", "DISPATCHED", "CLAIM_REQUESTED",
        "CLAIM_COMPLETED", "DELIVERY_ADDRESS_CHANGED", "PLACE_ORDER_CONFIRM",
        "OK", "PLACE_ORDER",
    ]
    found_in = []
    for t in types_to_test:
        try:
            r = await client._call_api(
                "GET",
                "/v1/pay-order/seller/product-orders/last-changed-statuses",
                params={"lastChangedFrom": since, "lastChangedType": t},
            )
            d = r.get("data", r) if isinstance(r, dict) else {}
            sl = d.get("lastChangeStatuses") or d.get("lastChangedStatuses") or []
            ids = [s.get("productOrderId") for s in sl]
            inside = TARGET in ids
            print(f"[{t}] {len(ids)}건, 이종영 포함={inside}")
            if inside:
                found_in.append(t)
                for s in sl:
                    if s.get("productOrderId") == TARGET:
                        print(f"   → {s}")
                        break
        except Exception as e:
            print(f"[{t}] ERROR: {str(e)[:100]}")
        import asyncio as _a
        await _a.sleep(0.5)

    print(f"\n→ 이종영이 포함된 type: {found_in}")

    # 4) type 생략 호출
    print("\n=== lastChangedType 생략 ===")
    r = await client._call_api(
        "GET",
        "/v1/pay-order/seller/product-orders/last-changed-statuses",
        params={"lastChangedFrom": since},
    )
    d = r.get("data", r) if isinstance(r, dict) else {}
    sl = d.get("lastChangeStatuses") or d.get("lastChangedStatuses") or []
    ids = [s.get("productOrderId") for s in sl]
    inside = TARGET in ids
    print(f"총 {len(ids)}건, 이종영 포함={inside}")
    if inside:
        for s in sl:
            if s.get("productOrderId") == TARGET:
                print(f"  → lastChangedType={s.get('lastChangedType')}, lastChangedDate={s.get('lastChangedDate')}")
                break


asyncio.run(main())

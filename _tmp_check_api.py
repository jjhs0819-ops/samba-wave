"""가디 인증으로 스마트스토어 last-changed-statuses 직접 호출 — 이종영 productOrderId 누락 여부 검증."""

import asyncio
import sys
sys.path.insert(0, '/app/backend')

from datetime import datetime, timedelta, timezone
from backend.domain.samba.proxy.smartstore import SmartStoreClient
from backend.db.orm import get_read_session
from sqlalchemy import text


TARGET_PRODUCT_ORDER_ID = "2026051197491491"
TARGET_ORDER_ID = "2026051143770661"


async def main():
    # 1) 가디 계정 인증 조회
    async with get_read_session() as session:
        row = await session.execute(text("""
            SELECT id, additional_fields->>'clientId' AS cid,
                   additional_fields->>'clientSecret' AS csec
            FROM samba_market_account
            WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
        """))
        rec = row.fetchone()
        if not rec:
            print("가디 계정 없음")
            return
        acc_id, cid, csec = rec
        print(f"가디 account_id={acc_id}, has_cid={bool(cid)}, has_csec={bool(csec)}")

    if not cid or not csec:
        print("인증정보 누락")
        return

    client = SmartStoreClient(cid, csec)

    # 2) 직접 last-changed-statuses 호출 — 13 types
    kst = timezone(timedelta(hours=9))
    since_str = (datetime.now(kst) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
    change_types = [
        "PAYED", "DELIVERING", "DELIVERED", "PURCHASE_DECIDED", "EXCHANGED",
        "CANCELED", "RETURNED", "CANCEL_REQUEST", "CANCEL_DONE",
        "RETURN_REQUEST", "RETURN_DONE", "EXCHANGE_REQUEST", "EXCHANGE_DONE",
    ]

    all_ids: dict[str, list[str]] = {}  # productOrderId -> [type, ...]
    print(f"\nlastChangedFrom = {since_str}")
    print("=" * 80)
    for ct in change_types:
        try:
            result = await client._call_api(
                "GET",
                "/v1/pay-order/seller/product-orders/last-changed-statuses",
                params={"lastChangedFrom": since_str, "lastChangedType": ct},
            )
        except Exception as e:
            print(f"[{ct}] ERROR: {e}")
            await asyncio.sleep(1.0)
            continue
        data = result.get("data", result) if isinstance(result, dict) else {}
        statuses = (data.get("lastChangeStatuses") or data.get("lastChangedStatuses") or []) if isinstance(data, dict) else []
        ids = [s.get("productOrderId") for s in statuses if s.get("productOrderId")]
        print(f"[{ct}] {len(ids)}건")
        for pid in ids:
            all_ids.setdefault(pid, []).append(ct)
        await asyncio.sleep(1.0)

    print("\n" + "=" * 80)
    print(f"TOTAL unique productOrderIds: {len(all_ids)}")
    target_in = TARGET_PRODUCT_ORDER_ID in all_ids
    print(f"이종영 productOrderId {TARGET_PRODUCT_ORDER_ID} 포함여부: {target_in}")
    if target_in:
        print(f"  → lastChangedType: {all_ids[TARGET_PRODUCT_ORDER_ID]}")

    # 3) 직접 상세 조회 — 권한 문제인지 확인
    print("\n" + "=" * 80)
    print(f"product-orders/query 로 직접 조회 시도:")
    try:
        detail = await client._call_api(
            "POST",
            "/v1/pay-order/seller/product-orders/query",
            body={"productOrderIds": [TARGET_PRODUCT_ORDER_ID]},
        )
        import json
        print(json.dumps(detail, ensure_ascii=False, default=str)[:2000])
    except Exception as e:
        print(f"ERROR: {e}")


asyncio.run(main())

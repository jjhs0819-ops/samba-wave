"""PlayAuto OrderCode vs DB order_number 직접 비교."""
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

os.environ.setdefault(
    "PLAYAUTO_PROXY_URL",
    "http://smart-zhej55fgrt0k:keGU2DZxflfM3QJj@119.206.200.126:6014",
)

from sqlalchemy import text

from backend.db.orm import get_read_session
from backend.domain.samba.proxy.playauto import PlayAutoClient

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        extras_row = (
            await s.execute(
                text("SELECT additional_fields FROM samba_market_account WHERE id = :aid"),
                {"aid": PA_ACCOUNT_ID},
            )
        ).fetchone()
        extras = extras_row[0] or {}
        api_key = extras.get("apiKey", "")

        # DB 미등록 주문 최근 7일 order_number
        db_orders = (
            await s.execute(
                text(
                    "SELECT order_number, paid_at FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND created_at >= NOW() - INTERVAL '7 days' "
                    "LIMIT 30"
                )
            )
        ).fetchall()
        db_map = {r[0]: r[1] for r in db_orders}
        print(f"DB 미등록 최근 7일 order_number {len(db_map)}건:")
        for k, v in list(db_map.items())[:5]:
            print(f"  {k!r} paid_at={v}")

    # PlayAuto API 최근 10일 폴링
    client = PlayAutoClient(api_key=api_key)
    try:
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=500, page=1)
    finally:
        await client.close()

    print(f"\nPlayAuto API 10일 결과: {len(orders)}건")

    # 공백포함 OrderCode 20개 샘플
    space_codes = [o.get("OrderCode", "") for o in orders if " " in o.get("OrderCode", "")]
    print(f"\n공백포함 OrderCode {len(space_codes)}건 샘플:")
    for c in space_codes[:10]:
        print(f"  {c!r}")

    # DB 매칭 시도
    pa_code_set = {o.get("OrderCode", "") for o in orders}
    matched = [k for k in db_map if k in pa_code_set]
    print(f"\nDB vs PlayAuto OrderCode 매칭: {len(matched)}건")

    # 미매칭 DB 주문 형식 vs PA 주문 OrderCode 형식 비교
    unmatched_sample = [k for k in db_map if k not in pa_code_set][:3]
    print(f"\n미매칭 DB order_number 예시: {unmatched_sample}")
    print(f"PA OrderCode 예시 (10개): {list(pa_code_set)[:10]}")

    # 모든 필드에서 찾기 (OrderCode 말고 다른 필드도 확인)
    if unmatched_sample:
        target = unmatched_sample[0]
        print(f"\n타겟 {target!r} 모든 PA 필드에서 검색:")
        for o in orders:
            for k, v in o.items():
                if str(v) == target:
                    print(f"  발견! 필드={k} OrderCode={o.get('OrderCode')}")
                    break


asyncio.run(main())

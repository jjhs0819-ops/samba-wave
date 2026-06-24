"""PlayAuto 주문 API 응답 필드 확인."""
import asyncio
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

os.environ.setdefault(
    "PLAYAUTO_PROXY_URL",
    "http://smart-zhej55fgrt0k:keGU2DZxflfM3QJj@119.206.200.126:6014",
)

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402
from backend.domain.samba.proxy.playauto import PlayAutoClient  # noqa: E402

PA_ACCOUNT_ID = "ma_01KP0919YA061YX5PHH25KWJAK"


async def main() -> None:
    async with get_read_session() as s:
        row = (
            await s.execute(
                text("SELECT additional_fields FROM samba_market_account WHERE id = :aid"),
                {"aid": PA_ACCOUNT_ID},
            )
        ).fetchone()
        extras = row[0] or {}
        api_key = extras.get("apiKey", "")

    client = PlayAutoClient(api_key=api_key)
    try:
        from datetime import UTC, datetime, timedelta

        start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=1, page=1)
    finally:
        await client.close()

    if not orders:
        print("응답 없음")
        return

    first = orders[0]
    print(f"응답 키 목록: {list(first.keys())}")
    print()
    for k, v in first.items():
        print(f"  {k}: {str(v)[:80]!r}")

    # order_number로 쓰이는 키 찾기
    print("\n--- order_number 후보 (OrderNo/OrderNumber/ord_no 등) ---")
    candidates = [k for k in first.keys() if "order" in k.lower() or "no" in k.lower()]
    for k in candidates:
        print(f"  {k}: {str(first.get(k, ''))[:80]!r}")

    # DB에 저장된 order_number 형식 확인
    async with get_read_session() as s:
        sample = (
            await s.execute(
                text(
                    "SELECT order_number FROM samba_order "
                    "WHERE source = 'playauto' AND order_number IS NOT NULL "
                    "LIMIT 3"
                )
            )
        ).fetchall()
    print(f"\nDB 저장 order_number 샘플: {[r[0] for r in sample]}")


asyncio.run(main())

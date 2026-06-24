"""PlayAuto 주문 응답 전체 필드 확인 — MasterCode='110511' 주문의 raw JSON."""
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
from backend.domain.samba.proxy.playauto import PlayAutoApiError, PlayAutoClient

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
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=5, page=1)
    finally:
        await client.close()

    print(f"응답 {len(orders)}건")

    for i, o in enumerate(orders[:3]):
        print(f"\n=== 주문 {i+1} ===")
        for k, v in o.items():
            print(f"  {k}: {str(v)!r}")


asyncio.run(main())

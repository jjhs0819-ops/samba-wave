"""GS이숍 주문의 raw 필드 + MasterCode 확인."""
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
        orders = await client.get_orders(start_date=start_date, count=500, page=1)
    finally:
        await client.close()

    # GS이숍 주문만 추출
    gs_orders = [o for o in orders if o.get("SiteName") == "GS이숍"]
    print(f"GS이숍 주문: {len(gs_orders)}건 / 전체 {len(orders)}건")

    # MasterCode 분포
    from collections import Counter
    mc_dist = Counter(o.get("MasterCode", "") for o in gs_orders)
    print(f"GS이숍 MasterCode 분포 (상위 10):")
    for mc, cnt in mc_dist.most_common(10):
        print(f"  {mc!r}: {cnt}건")

    # GS이숍 첫 3건 raw 필드
    print("\n=== GS이숍 주문 샘플 3건 ===")
    for i, o in enumerate(gs_orders[:3]):
        print(f"\n--- 주문 {i+1} ---")
        for k, v in o.items():
            if v:
                print(f"  {k}: {str(v)!r}")

    # 현대H몰 MasterCode 분포 비교
    h_orders = [o for o in orders if o.get("SiteName") == "현대H몰"]
    h_mc = Counter(o.get("MasterCode", "")[:5] for o in h_orders)
    print(f"\n현대H몰 MasterCode 접두어 분포: {dict(h_mc.most_common(5))}")


asyncio.run(main())

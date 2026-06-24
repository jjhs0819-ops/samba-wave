"""GS이숍 신발끈 미등록 주문 MasterCode 확인."""
import asyncio
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

TARGET_KEYWORDS = ["신발끈", "헤어밴드", "신발 끈"]


async def main() -> None:
    async with get_read_session() as s:
        row = (
            await s.execute(
                text("SELECT additional_fields FROM samba_market_account WHERE id = :aid"),
                {"aid": PA_ACCOUNT_ID},
            )
        ).fetchone()
        api_key = (row[0] or {}).get("apiKey", "")

    client = PlayAutoClient(api_key=api_key)
    try:
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=500, page=1)
    finally:
        await client.close()

    # 신발끈/헤어밴드 주문 MasterCode
    targets = [
        o for o in orders
        if any(kw in (o.get("ProdName", "") or "") for kw in TARGET_KEYWORDS)
    ]
    print(f"신발끈/헤어밴드 관련 PlayAuto 주문: {len(targets)}건")
    for o in targets[:5]:
        print(f"  MC={o.get('MasterCode')!r} ProdCode={o.get('ProdCode')!r}")
        print(f"  ProdName={o.get('ProdName', '')[:60]!r}")

    # product_id='1124164322019' 주문의 MasterCode
    prod_ids = {"1124164322019", "1124164322012", "1118886308006"}
    matched = [o for o in orders if o.get("ProdCode", "") in prod_ids]
    print(f"\nproduct_id 직접매칭: {len(matched)}건")
    for o in matched:
        print(f"  MC={o.get('MasterCode')!r} ProdCode={o.get('ProdCode')!r}")

    # MasterCode AM인덱스에 있는지
    all_mc = list({o.get("MasterCode", "") for o in targets if o.get("MasterCode", "").startswith("AM")})
    if all_mc:
        async with get_read_session() as s:
            found = (
                await s.execute(
                    text(
                        "SELECT (market_product_nos->>:kid) mc, id "
                        "FROM samba_collected_product "
                        "WHERE market_product_nos ? :kid "
                        "AND (market_product_nos->>:kid) = ANY(:mcs)"
                    ),
                    {"kid": PA_ACCOUNT_ID, "mcs": all_mc},
                )
            ).fetchall()
            print(f"\nAM인덱스에서 찾은 CP: {len(found)}개 / {len(all_mc)}개")


asyncio.run(main())

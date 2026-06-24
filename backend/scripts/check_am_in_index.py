"""GS이숍 주문의 AM코드가 DB AM인덱스에 있는지 확인 + 미등록 원인 분석."""
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

    # PlayAuto 10일 폴링
    client = PlayAutoClient(api_key=api_key)
    try:
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=500, page=1)
    finally:
        await client.close()

    # GS이숍 AM코드 수집
    gs_am_codes = [
        (o.get("OrderCode", ""), o.get("MasterCode", ""), o.get("ProdCode", ""))
        for o in orders
        if o.get("SiteName") == "GS이숍" and o.get("MasterCode", "").startswith("AM")
    ]
    print(f"GS이숍 AM코드 있는 주문: {len(gs_am_codes)}건")

    # AM인덱스에서 확인
    async with get_read_session() as s:
        am_codes = [mc for _, mc, _ in gs_am_codes[:20]]
        rows = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->>:kid) AS am_code, cp.id "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->>:kid) = ANY(:ams)"
                ),
                {"kid": PA_ACCOUNT_ID, "ams": am_codes},
            )
        ).fetchall()
        found_map = {r[0]: r[1] for r in rows}
        print(f"AM인덱스에서 찾은 CP: {len(found_map)}개 / {len(am_codes)}개")

        # 찾은 것과 못 찾은 것 비교
        for oc, mc, pc in gs_am_codes[:5]:
            cp_id = found_map.get(mc)
            print(f"  OrderCode={oc!r} MasterCode={mc!r} ProdCode={pc!r} → CP={str(cp_id)[:20] if cp_id else '없음'}")

        # 미등록 주문 DB 확인 (GS이숍 형식 order_number = 공백포함)
        db_gs = (
            await s.execute(
                text(
                    "SELECT order_number, collected_product_id "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND order_number LIKE '% %' "
                    "AND created_at >= NOW() - INTERVAL '10 days' "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        print(f"\n최근 10일 GS이숍 형식(공백포함) 주문 DB: {len(db_gs)}건")
        linked = sum(1 for r in db_gs if r[1])
        print(f"  linked: {linked}건 / 미등록: {len(db_gs)-linked}건")

        # 최근 10일 GS이숍 형식 미등록 주문과 PlayAuto OrderCode 비교
        db_gs_unlinked = {r[0] for r in db_gs if not r[1]}
        gs_oc_set = {oc for oc, _, _ in gs_am_codes}
        common = db_gs_unlinked & gs_oc_set
        print(f"  PlayAuto GS이숍 OrderCode와 DB 미등록 교집합: {len(common)}건")
        for oc in list(common)[:3]:
            mc = next((mc for oc2, mc, _ in gs_am_codes if oc2 == oc), "?")
            cp_id = found_map.get(mc)
            print(f"    {oc!r} MasterCode={mc!r} → CP={str(cp_id)[:20] if cp_id else '없음'}")


asyncio.run(main())

"""10일 폴링에서 16건 매칭된 주문들의 MasterCode가 DB에 있는지 확인."""
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

        # DB 미등록 주문 최근 7일
        db_orders = (
            await s.execute(
                text(
                    "SELECT order_number, product_id FROM samba_order "
                    "WHERE source='playauto' AND collected_product_id IS NULL "
                    "AND created_at >= NOW() - INTERVAL '7 days'"
                )
            )
        ).fetchall()
        db_map = {r[0]: r[1] for r in db_orders}
        print(f"DB 최근 7일 미등록: {len(db_map)}건")

    # PlayAuto API 10일 폴링
    client = PlayAutoClient(api_key=api_key)
    try:
        start_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y%m%d")
        orders = await client.get_orders(start_date=start_date, count=500, page=1)
    finally:
        await client.close()

    # DB와 매칭
    matched = []
    for o in orders:
        oc = o.get("OrderCode", "")
        if oc in db_map:
            mc = o.get("MasterCode") or o.get("SellerCode") or ""
            matched.append({
                "order_no": oc,
                "product_id": db_map[oc],
                "master_code": mc,
                "site": o.get("SiteName", ""),
            })

    print(f"OrderCode 매칭: {len(matched)}건")
    for m in matched[:10]:
        print(f"  order_no={m['order_no']!r} product_id={m['product_id']!r}")
        print(f"    MasterCode={m['master_code']!r} site={m['site']}")

    if not matched:
        return

    # AM코드 인덱스에서 찾기
    async with get_read_session() as s:
        am_rows = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->>:kid) AS am_code, cp.id "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->>:kid) LIKE 'AM%'"
                ),
                {"kid": PA_ACCOUNT_ID},
            )
        ).fetchall()
        am_index = {r[0]: r[1] for r in am_rows}

        print(f"\nAM코드 인덱스 {len(am_index):,}개")
        for m in matched:
            mc = m["master_code"]
            cp_id = am_index.get(mc)
            print(f"  MasterCode={mc!r} → CP={str(cp_id)[:20] if cp_id else '없음'}")

        # 없는 AM코드들의 ProdName 기반 CP 검색
        no_cp = [m for m in matched if m["master_code"] and not am_index.get(m["master_code"])]
        if no_cp:
            print(f"\nAM코드 인덱스에 없는 {len(no_cp)}건 - CP 이름 기반 검색 시도:")
            for m in no_cp[:5]:
                # product_id로 CP 찾기 (style_code 포함 검색)
                cp_by_pid = (
                    await s.execute(
                        text(
                            "SELECT id, name, style_code FROM samba_collected_product "
                            "WHERE style_code = :pid OR name LIKE :pname LIMIT 3"
                        ),
                        {"pid": m["product_id"], "pname": f"%{m['product_id']}%"},
                    )
                ).fetchall()
                print(f"  product_id={m['product_id']!r} → style_code/name 검색: {len(cp_by_pid)}건")
                for c in cp_by_pid:
                    print(f"    CP={c[0]} name={str(c[1])[:40]} style={c[2]}")


asyncio.run(main())

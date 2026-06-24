"""ProdName 끝 숫자가 CP site_product_id인지 검증."""
import asyncio
import os
import re
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
# PlayAuto ProdName 끝 숫자 패턴: 공백+숫자 (최소 5자리)
GOODS_NO_RE = re.compile(r"\s+(\d{5,})$")


def extract_goods_no(prod_name: str) -> str:
    m = GOODS_NO_RE.search(prod_name.strip())
    return m.group(1) if m else ""


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

    # AM코드로 CP 찾은 GS이숍 주문에서 ProdName 끝 숫자 추출
    gs_am = [
        (o.get("OrderCode", ""), o.get("MasterCode", ""), o.get("ProdCode", ""), o.get("ProdName", ""))
        for o in orders
        if o.get("SiteName") == "GS이숍" and o.get("MasterCode", "").startswith("AM")
    ]

    print(f"GS이숍 AM코드 주문 {len(gs_am)}건")
    print(f"\nProdName 끝 숫자 패턴:")
    goods_no_samples = []
    for oc, mc, pc, pn in gs_am[:10]:
        gn = extract_goods_no(pn)
        goods_no_samples.append((oc, mc, gn))
        print(f"  ProdName={pn!r}")
        print(f"    → goods_no={gn!r}")

    # CP site_product_id 확인 (AM코드로 찾은 CP들)
    async with get_read_session() as s:
        am_codes = [mc for _, mc, _, _ in gs_am[:10]]
        cp_rows = (
            await s.execute(
                text(
                    "SELECT (cp.market_product_nos->>:kid) AS am_code, "
                    "cp.id, cp.site_product_id, cp.source_site "
                    "FROM samba_collected_product cp "
                    "WHERE cp.market_product_nos ? :kid "
                    "AND (cp.market_product_nos->>:kid) = ANY(:ams)"
                ),
                {"kid": PA_ACCOUNT_ID, "ams": am_codes},
            )
        ).fetchall()
        am_to_cp = {r[0]: (r[1], r[2], r[3]) for r in cp_rows}

        print(f"\nCP site_product_id vs ProdName 끝 숫자:")
        for oc, mc, gn in goods_no_samples:
            cp_info = am_to_cp.get(mc)
            if cp_info:
                cp_id, spid, src = cp_info
                match = str(spid) == gn
                print(f"  MC={mc!r}")
                print(f"    CP={cp_id} site_product_id={spid!r} source={src}")
                print(f"    goods_no={gn!r} → {'✓ 일치' if match else '✗ 불일치'}")

        # 전체 비교 통계
        matched = sum(
            1 for oc, mc, gn in goods_no_samples
            if gn and am_to_cp.get(mc) and str(am_to_cp[mc][1]) == gn
        )
        total = sum(1 for _, _, gn in goods_no_samples if gn and am_to_cp.get(_))
        print(f"\n일치율: {matched}/{total}")


asyncio.run(main())

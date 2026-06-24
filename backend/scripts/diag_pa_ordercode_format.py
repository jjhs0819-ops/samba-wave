"""PlayAuto OrderCode 형식 확인 + 두 번째 계정 확인."""
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

from sqlalchemy import text

from backend.db.orm import get_read_session
from backend.domain.samba.proxy.playauto import PlayAutoClient

# 두 PlayAuto 계정
PA_ACCOUNTS = [
    "ma_01KP0919YA061YX5PHH25KWJAK",  # roaterydg
    # 다른 계정이 있는지 조회
]


async def main() -> None:
    async with get_read_session() as s:
        # 모든 PlayAuto 계정 조회
        accts = (
            await s.execute(
                text(
                    "SELECT id, additional_fields, account_label "
                    "FROM samba_market_account "
                    "WHERE market_type = 'playauto'"
                )
            )
        ).fetchall()
        print(f"PlayAuto 계정 {len(accts)}개:")
        for a in accts:
            extras = a[1] or {}
            print(f"  id={a[0]} label={a[2]}")

        # DB 미등록 주문 order_number 샘플 (최근 7일)
        samples = (
            await s.execute(
                text(
                    "SELECT order_number, channel_id FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "AND created_at >= NOW() - INTERVAL '7 days' "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        target_order_nos = {r[0] for r in samples}
        print(f"\nDB 최근 7일 미등록 order_number 샘플:")
        for r in samples:
            print(f"  {r[0]!r}")

    # 두 번째 계정 포함해서 모든 계정 폴링
    for acct in accts:
        extras = acct[1] or {}
        if isinstance(extras, str):
            extras = json.loads(extras)
        api_key = extras.get("apiKey", "")
        if not api_key:
            print(f"\n{acct[2]}: api_key 없음, 스킵")
            continue

        print(f"\n=== 계정: {acct[2]} ===")
        client = PlayAutoClient(api_key=api_key)
        try:
            from datetime import UTC, datetime, timedelta

            # 7일만 폴링해서 빠르게 확인
            start_date = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y%m%d")
            orders = await client.get_orders(start_date=start_date, count=100, page=1)
        finally:
            await client.close()

        if not orders:
            print("주문 없음")
            continue

        print(f"응답 {len(orders)}건")

        # OrderCode 형식 분포
        code_formats: dict[str, int] = {}
        for o in orders[:50]:
            oc = o.get("OrderCode", "")
            if " " in oc:
                fmt = "공백포함"
            elif "_" in oc:
                fmt = "언더바형"
            elif oc.isdigit():
                fmt = "숫자형"
            else:
                fmt = f"기타({oc[:10]})"
            code_formats[fmt] = code_formats.get(fmt, 0) + 1
        print(f"OrderCode 형식: {code_formats}")

        # 미등록 order_number와 매칭되는 게 있는지
        matched = [o for o in orders if o.get("OrderCode", "") in target_order_nos]
        print(f"DB 미등록 주문과 매칭: {len(matched)}건")
        if matched:
            print(f"  예시: OrderCode={matched[0].get('OrderCode')} MasterCode={matched[0].get('MasterCode')}")

        # SiteName 분포
        sites: dict[str, int] = {}
        for o in orders:
            s = o.get("SiteName", "?")
            sites[s] = sites.get(s, 0) + 1
        print(f"SiteName 분포: {dict(sorted(sites.items(), key=lambda x: -x[1])[:5])}")


asyncio.run(main())

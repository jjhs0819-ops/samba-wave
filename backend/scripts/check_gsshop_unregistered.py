"""GSSHOP 플레이오토 미등록 주문 진단 — product_id / style_code DB 존재 여부."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # 미등록 GSSHOP 플레이오토 주문 샘플
        orders = (
            await s.execute(
                text(
                    "SELECT o.id, o.product_id, o.product_name, o.channel_id "
                    "FROM samba_order o "
                    "JOIN samba_market_account ma ON ma.id = o.channel_id "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND ma.market_type = 'gsshop' "
                    "LIMIT 10"
                )
            )
        ).fetchall()

        print(f"미등록 GSSHOP 플레이오토 주문 샘플 {len(orders)}건:")
        product_ids = []
        for r in orders:
            print(f"  id={r[0]} product_id={r[1]!r} name={str(r[2] or '')[:60]}")
            if r[1]:
                product_ids.append(str(r[1]))

        if not product_ids:
            print("product_id 없는 주문만 존재")
            return

        # product_id 가 market_product_nos 에 있는지 확인
        ph = ", ".join(f"'{p}'" for p in product_ids[:10])
        cp_rows = (
            await s.execute(
                text(
                    f"SELECT id, source_site, site_product_id, name, style_code "
                    f"FROM samba_collected_product "
                    f"WHERE market_product_nos::text LIKE ANY(ARRAY[{', '.join(['%' + p + '%' for p in product_ids[:5]])}])"
                )
            )
        ).fetchall()
        print(f"\nmarket_product_nos 히트: {len(cp_rows)}건")

        # style_code 직접 확인 (LM3EN0S, SL0WCCDX081 등)
        test_codes = ["LM3EN0S", "SL0WCCDX081", "LE1217201615", "BRWT"]
        sc_rows = (
            await s.execute(
                text(
                    "SELECT id, style_code, source_site, name "
                    "FROM samba_collected_product "
                    "WHERE style_code = ANY(:t)"
                ),
                {"t": test_codes},
            )
        ).fetchall()
        print(f"\nstyle_code 히트 (LM3EN0S/SL0WCCDX081/LE1217201615): {len(sc_rows)}건")
        for r in sc_rows:
            print(f"  {r}")

        # GSSHOP site_product_id 확인
        gsshop_cps = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_collected_product "
                    "WHERE source_site = 'gsshop'"
                )
            )
        ).scalar()
        print(f"\nDB GSSHOP 수집 상품 수: {gsshop_cps:,}개")


asyncio.run(main())

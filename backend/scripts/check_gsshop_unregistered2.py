"""GSSHOP 플레이오토 미등록 주문 — product_id 패턴 및 style_code 존재 확인."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # 미등록 플레이오토 주문 샘플 (channel 필터 없이)
        orders = (
            await s.execute(
                text(
                    "SELECT o.id, o.product_id, o.sales_channel_alias, o.product_name "
                    "FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND o.product_name IS NOT NULL "
                    "ORDER BY o.created_at DESC "
                    "LIMIT 15"
                )
            )
        ).fetchall()

        print(f"미등록 플레이오토 주문 샘플 {len(orders)}건:")
        for r in orders:
            print(
                f"  product_id={r[1]!r:20s} alias={str(r[2] or '')[:20]:20s} "
                f"name={str(r[3] or '')[:50]}"
            )

        # style_code 직접 확인
        test_codes = ["LM3EN0S", "SL0WCCDX081", "LE1217201615"]
        sc_rows = (
            await s.execute(
                text(
                    "SELECT id, style_code, source_site "
                    "FROM samba_collected_product "
                    "WHERE style_code = ANY(:t)"
                ),
                {"t": test_codes},
            )
        ).fetchall()
        print(f"\nstyle_code 히트 {test_codes}: {len(sc_rows)}건")
        for r in sc_rows:
            print(f"  {r}")

        # channel_alias 분포 (어떤 마켓에서 미등록이 많은지)
        dist = (
            await s.execute(
                text(
                    "SELECT sales_channel_alias, COUNT(*) as cnt "
                    "FROM samba_order "
                    "WHERE source = 'playauto' AND collected_product_id IS NULL "
                    "GROUP BY sales_channel_alias "
                    "ORDER BY cnt DESC LIMIT 10"
                )
            )
        ).fetchall()
        print("\n미등록 채널별 분포:")
        for r in dist:
            print(f"  {str(r[0] or '(없음)'):<30s} {r[1]:,}건")


asyncio.run(main())

"""최근 10일 미등록 PlayAuto 주문 원인 분석."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session


async def main() -> None:
    async with get_read_session() as s:
        # 채널별 미등록
        ch_rows = (
            await s.execute(
                text(
                    "SELECT channel_name, COUNT(*) cnt "
                    "FROM samba_order "
                    "WHERE source='playauto' "
                    "AND created_at >= NOW() - INTERVAL '10 days' "
                    "AND collected_product_id IS NULL "
                    "GROUP BY channel_name ORDER BY cnt DESC"
                )
            )
        ).fetchall()
        print("채널별 미등록:")
        for r in ch_rows:
            print(f"  {r[0]!r}: {r[1]}건")

        # product_name 샘플
        samples = (
            await s.execute(
                text(
                    "SELECT product_name, product_id, order_number "
                    "FROM samba_order "
                    "WHERE source='playauto' "
                    "AND created_at >= NOW() - INTERVAL '10 days' "
                    "AND collected_product_id IS NULL "
                    "LIMIT 10"
                )
            )
        ).fetchall()
        print("\n미등록 샘플:")
        for r in samples:
            print(f"  order_no={r[2]!r}")
            print(f"  product_name={str(r[0])[:80]!r}")
            print(f"  product_id={r[1]!r}")
            print()


asyncio.run(main())

"""고아 참조 주문(collected_product_id 있지만 CP 없음) → NULL 정리."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_read_session, get_write_session


async def main() -> None:
    async with get_read_session() as s:
        # 분포 확인
        dist = (
            await s.execute(
                text(
                    "SELECT source, COUNT(*) cnt "
                    "FROM samba_order o "
                    "WHERE o.collected_product_id IS NOT NULL "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM samba_collected_product cp WHERE cp.id = o.collected_product_id"
                    ") "
                    "GROUP BY source ORDER BY cnt DESC"
                )
            )
        ).fetchall()
        print("고아 참조 source 분포:")
        for r in dist:
            print(f"  {r[0]!r}: {r[1]:,}건")

        total = sum(r[1] for r in dist)
        print(f"  합계: {total:,}건")

    # NULL 처리
    async with get_write_session() as s:
        result = await s.execute(
            text(
                "UPDATE samba_order o "
                "SET collected_product_id = NULL, updated_at = NOW() "
                "WHERE o.collected_product_id IS NOT NULL "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM samba_collected_product cp WHERE cp.id = o.collected_product_id"
                ")"
            )
        )
        await s.commit()
        print(f"\n완료: {result.rowcount:,}건 NULL 처리")

    async with get_read_session() as s:
        r = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order o "
                    "WHERE o.collected_product_id IS NOT NULL "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM samba_collected_product cp WHERE cp.id = o.collected_product_id"
                    ")"
                )
            )
        ).scalar()
        print(f"잔여 고아 참조: {r:,}건")


asyncio.run(main())

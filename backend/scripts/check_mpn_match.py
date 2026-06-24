"""PlayAuto 미등록 주문 product_id → market_product_nos 실제 매칭 확인."""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_read_session  # noqa: E402


async def main() -> None:
    async with get_read_session() as s:
        # 미등록 주문 product_id 전체
        pids_rows = (
            await s.execute(
                text(
                    "SELECT DISTINCT product_id FROM samba_order "
                    "WHERE source = 'playauto' "
                    "AND collected_product_id IS NULL "
                    "AND product_id IS NOT NULL AND product_id != ''"
                )
            )
        ).fetchall()
        pids = [str(r[0]).strip() for r in pids_rows]
        print(f"미등록 unique product_id: {len(pids):,}개")
        print(f"  예시: {pids[:5]}")

        # market_product_nos 에서 이 값들 매칭
        # jsonb_typeof='object' 필터로 null/array row 제외
        hit = (
            await s.execute(
                text(
                    "SELECT COUNT(DISTINCT cp.id) "
                    "FROM samba_collected_product cp, "
                    "     jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value = ANY(:pids)"
                ),
                {"pids": pids},
            )
        ).scalar()
        print(f"\nmarket_product_nos 히트 CP 수: {hit:,}건")

        # 샘플
        sample = (
            await s.execute(
                text(
                    "SELECT kv.value AS product_no, cp.id, cp.name "
                    "FROM samba_collected_product cp, "
                    "     jsonb_each_text(cp.market_product_nos) kv "
                    "WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "AND kv.value = ANY(:pids) "
                    "LIMIT 10"
                ),
                {"pids": pids[:200]},
            )
        ).fetchall()
        print(f"\n히트 샘플:")
        for r in sample:
            print(f"  product_no={r[0]} → {str(r[2] or '')[:50]}")

        # 매칭 가능 주문 수
        hit_orders = (
            await s.execute(
                text(
                    "SELECT COUNT(*) FROM samba_order o "
                    "WHERE o.source = 'playauto' "
                    "AND o.collected_product_id IS NULL "
                    "AND EXISTS ("
                    "  SELECT 1 FROM samba_collected_product cp, "
                    "  jsonb_each_text(cp.market_product_nos) kv "
                    "  WHERE jsonb_typeof(cp.market_product_nos) = 'object' "
                    "  AND kv.value = o.product_id"
                    ")"
                )
            )
        ).scalar()
        print(f"\n매칭 가능한 미등록 주문 수: {hit_orders:,}건")


asyncio.run(main())

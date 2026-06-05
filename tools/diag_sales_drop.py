"""유입 감소 뿌리 — 라이브 등록상품 일별 스냅샷 + sold_out/restock net 추이."""

import asyncio

from sqlalchemy import text

from backend.db.orm import get_read_session


async def main() -> None:
    async with get_read_session() as s:
        # 스냅샷 스키마
        cols = (
            (
                await s.execute(
                    text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name='samba_daily_registered_snapshot' ORDER BY ordinal_position"
                    )
                )
            )
            .mappings()
            .all()
        )
        print("=== 스냅샷 컬럼 ===")
        for c in cols:
            print(f"  {c['column_name']} ({c['data_type']})")

        print("\n=== 최근 14행 (전체) ===")
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT * FROM samba_daily_registered_snapshot "
                        "ORDER BY 1 DESC LIMIT 14"
                    )
                )
            )
            .mappings()
            .all()
        )
        for r in rows:
            print("  " + " | ".join(f"{k}={v}" for k, v in r.items()))

        # sold_out vs restock 일별 net (재고 침식 속도)
        print("\n=== sold_out / restock 일별 (KST) — net 품절 ===")
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT (created_at + interval '9 hours')::date AS d, "
                        "COUNT(*) FILTER (WHERE event_type='sold_out') AS so, "
                        "COUNT(*) FILTER (WHERE event_type='restock') AS rs "
                        "FROM samba_monitor_event "
                        "WHERE event_type IN ('sold_out','restock') "
                        "AND created_at >= NOW() - interval '9 days' "
                        "GROUP BY d ORDER BY d"
                    )
                )
            )
            .mappings()
            .all()
        )
        for r in rows:
            net = r["so"] - r["rs"]
            print(f"{r['d']} | 품절 {r['so']:>5} | 재입고 {r['rs']:>5} | net품절 {net:>+6}")


if __name__ == "__main__":
    asyncio.run(main())

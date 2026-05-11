"""최종 빈 칸 카운트."""

import asyncio, asyncpg, json
from collections import defaultdict
from backend.core.config import settings

TARGETS = ["11st", "auction", "coupang", "gmarket", "lotteon", "smartstore", "ssg"]


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        rows = await conn.fetch(
            "SELECT id, source_site, target_mappings FROM samba_category_mapping"
        )
        per_market = defaultdict(int)
        rows_with_empty = 0
        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                tm = json.loads(tm)
            if not isinstance(tm, dict):
                tm = {}
            empty = []
            for mk in TARGETS:
                v = tm.get(mk)
                if not isinstance(v, str) or not v.strip():
                    per_market[mk] += 1
                    empty.append(mk)
            if empty:
                rows_with_empty += 1
        print(f"전체 매핑 행: {len(rows)}")
        print(f"빈 칸 있는 행: {rows_with_empty}")
        print(f"총 빈 칸: {sum(per_market.values())}")
        print("\n[마켓별 잔여 빈 칸]")
        for m in TARGETS:
            print(f"  {m}: {per_market[m]}")
    finally:
        await conn.close()


asyncio.run(main())

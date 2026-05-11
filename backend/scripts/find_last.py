"""마지막 잔여 1행."""

import asyncio
import asyncpg
import json
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
            "SELECT id, source_site, source_category, target_mappings FROM samba_category_mapping"
        )
        for r in rows:
            tm = r["target_mappings"]
            if isinstance(tm, str):
                tm = json.loads(tm)
            if not isinstance(tm, dict):
                tm = {}
            empty = [
                mk
                for mk in TARGETS
                if not (isinstance(tm.get(mk), str) and tm.get(mk).strip())
            ]
            if empty:
                print(
                    f"{r['id']} | {r['source_site']} | {r['source_category']} | 빈: {empty}"
                )
    finally:
        await conn.close()


asyncio.run(main())

"""트리에서 캔들/인센스/디퓨저 leaf 검색."""

import asyncio
import asyncpg
import json
from backend.core.config import settings


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
        for site in ("auction", "gmarket", "smartstore", "ssg"):
            r = await conn.fetchrow(
                "SELECT cat1, cat2 FROM samba_category_tree WHERE site_name=$1", site
            )
            if not r:
                continue
            c1 = r["cat1"]
            if isinstance(c1, str):
                c1 = json.loads(c1)
            paths = []
            if isinstance(c1, list):
                paths = [c for c in c1 if isinstance(c, str)]
            print(f"\n=== {site} ===")
            for p in paths:
                if "캔들" in p or "인센스" in p or "디퓨저" in p or "방향제" in p:
                    print(f"  {p}")
    finally:
        await conn.close()


asyncio.run(main())

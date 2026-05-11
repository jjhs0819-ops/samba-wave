"""마지막 1칸."""

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
        rec = await conn.fetchrow(
            "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
            "cm_01KR5BCP04RKRKTWHK9FKKBPX7",
        )
        tm = rec["target_mappings"]
        if isinstance(tm, str):
            tm = json.loads(tm)
        if not isinstance(tm, dict):
            tm = {}
        tm["ssg"] = "신세계몰메인매장 > 모자/장갑/ACC > 양말/스타킹/ACC > 양말"
        await conn.execute(
            "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
            json.dumps(tm, ensure_ascii=False),
            "cm_01KR5BCP04RKRKTWHK9FKKBPX7",
        )
        print("OK")
    finally:
        await conn.close()


asyncio.run(main())

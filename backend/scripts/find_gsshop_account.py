"""GS샵 계정/supCd 찾기 스크립트."""
import asyncio, json, sys
sys.path.insert(0, "/app/backend")

import asyncpg
from backend.core.config import settings as cfg


async def main():
    conn = await asyncpg.connect(
        host=cfg.write_db_host, port=cfg.write_db_port,
        database=cfg.write_db_name, user=cfg.write_db_user,
        password=cfg.write_db_password, ssl=False,
    )

    # 테이블 목록에서 account/channel 관련 검색
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename ILIKE '%account%' ORDER BY tablename"
    )
    print("=== account 관련 테이블 ===")
    for t in tables:
        print(f"  {t['tablename']}")

    # samba_settings 전체 키 목록 (gs 관련 + store 관련)
    rows = await conn.fetch(
        "SELECT key FROM samba_settings WHERE key ILIKE '%store%' ORDER BY key"
    )
    print(f"\n=== store 관련 samba_settings 키: {len(rows)}개 ===")
    for r in rows:
        print(f"  {r['key']}")

    await conn.close()


asyncio.run(main())

"""프로덕션 DB에 monitor_event 인덱스 2개를 CONCURRENTLY로 생성하고
alembic_version을 최신 head로 stamp.

env.py가 async 엔진+명시 commit이라 autocommit_block 마이그레이션이
AssertionError로 실패하므로, 인덱스만 직접 SQL로 적용한다.
"""

import asyncio

import asyncpg

from backend.core.config import settings


INDEX_SQLS = [
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sme_event_site_created_at_desc
    ON samba_monitor_event (event_type, source_site, created_at DESC)
    """,
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sme_created_at_desc
    ON samba_monitor_event (created_at DESC)
    """,
]

NEW_HEAD = "zzzzzzzzzzzzzz_monitor_created_at_idx"


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        for sql in INDEX_SQLS:
            print(f"[INFO] running: {sql.strip()[:80]}...")
            await conn.execute(sql)
            print("[OK] done")

        rows = await conn.fetch("SELECT version_num FROM alembic_version")
        print(f"[INFO] current alembic versions: {[r['version_num'] for r in rows]}")

        await conn.execute("UPDATE alembic_version SET version_num = $1", NEW_HEAD)
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
        print(f"[OK] alembic_version → {[r['version_num'] for r in rows]}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

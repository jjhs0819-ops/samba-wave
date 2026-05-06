"""samba_collected_product VACUUM ANALYZE 강제 실행"""
import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )
    # VACUUM은 트랜잭션 밖에서 실행해야 함
    await conn.execute("VACUUM ANALYZE samba_collected_product")
    print("VACUUM ANALYZE 완료")

    stats = await conn.fetchrow("""
        SELECT n_live_tup, n_dead_tup,
               round(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 1) as bloat_pct,
               last_vacuum, last_analyze
        FROM pg_stat_user_tables
        WHERE relname = 'samba_collected_product'
    """)
    print(f"live={stats['n_live_tup']} dead={stats['n_dead_tup']} bloat={stats['bloat_pct']}%")
    print(f"last_vacuum={stats['last_vacuum']}")
    print(f"last_analyze={stats['last_analyze']}")

    await conn.close()


asyncio.run(main())

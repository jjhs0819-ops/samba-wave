"""samba_settings에서 잘못 저장된 store_* 설정값 삭제."""
import asyncio, sys
sys.path.insert(0, '/app/backend')
import asyncpg
from backend.core.config import settings

BAD_KEYS = [
    'store_smartstore',
    'store_toss',
    'store_lottehome',
    'store_gsshop',
    'store_ssg',
    'store_lotteon',
    'store_coupang',
    'store_11st',
    'store_gmarket',
    'store_auction',
]

async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    print('=== 현재 store_* 설정값 조회 ===')
    rows = await conn.fetch("""
        SELECT key, value::text
        FROM samba_settings
        WHERE key = ANY($1)
        ORDER BY key
    """, BAD_KEYS)

    if not rows:
        print('삭제할 레코드 없음.')
        await conn.close()
        return

    for r in rows:
        print(f"  {r['key']}: {r['value'][:80]}...")

    print(f'\n총 {len(rows)}개 삭제...')
    deleted = await conn.execute("""
        DELETE FROM samba_settings
        WHERE key = ANY($1)
    """, BAD_KEYS)
    print(f'완료: {deleted}')
    await conn.close()

asyncio.run(main())

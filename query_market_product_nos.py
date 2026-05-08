"""ABCmart 상품 오토튠 대상 여부 확인 스크립트."""
import asyncio, asyncpg, sys, os
sys.path.insert(0, '/app/backend')
os.chdir('/app/backend')
from backend.core.config import settings

async def main():
    conn = await asyncpg.connect(
        host=getattr(settings, 'DB_HOST', '172.18.0.2'),
        port=getattr(settings, 'DB_PORT', 5432),
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        ssl=False,
    )
    try:
        rows = await conn.fetch("""
            SELECT
                source_site,
                COUNT(*) as total,
                COUNT(applied_policy_id) as with_policy,
                COUNT(CASE WHEN registered_accounts IS NOT NULL
                           AND jsonb_array_length(registered_accounts) > 0
                           THEN 1 END) as with_market,
                COUNT(CASE WHEN applied_policy_id IS NOT NULL
                           AND registered_accounts IS NOT NULL
                           AND jsonb_array_length(registered_accounts) > 0
                           THEN 1 END) as autotune_eligible
            FROM samba_collected_product
            WHERE source_site IN ('ABCmart', 'GrandStage', 'SSG', 'LOTTEON')
            GROUP BY source_site
            ORDER BY source_site
        """)
        print("=== 소싱처별 오토튠 대상 상품 통계 ===")
        for r in rows:
            print(f"{r['source_site']:12} | 전체:{r['total']:5} | 정책적용:{r['with_policy']:5} | 마켓등록:{r['with_market']:5} | 오토튠대상:{r['autotune_eligible']:5}")
    finally:
        await conn.close()

asyncio.run(main())

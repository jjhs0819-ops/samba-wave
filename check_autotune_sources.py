"""오토튠 활성 소싱처별 최근 갱신 상품 샘플 추출"""

import asyncio
import asyncpg
import sys

sys.path.insert(0, "/app/backend")
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
        ssl=False,
    )

    # 1) 최근 1시간 내 갱신된 상품의 소싱처 분포 (오토튠이 작동 중인 소싱처)
    print("=== 최근 1시간 내 last_refreshed_at 갱신된 상품 소싱처 분포 ===")
    rows = await conn.fetch("""
        SELECT source_site, COUNT(*) as cnt, MAX(last_refreshed_at) as last_at
        FROM samba_collected_product
        WHERE last_refreshed_at > NOW() - INTERVAL '1 hour'
        GROUP BY source_site
        ORDER BY cnt DESC
    """)
    for r in rows:
        print(f"  {r['source_site']:20s}  cnt={r['cnt']:6d}  last={r['last_at']}")

    # 2) 소싱처별 무작위 5개씩 (최근 1시간 갱신 상품 중)
    print(
        "\n=== 소싱처별 무작위 5개 샘플 (cost / sale_price / source_url / site_product_id) ==="
    )
    sources = [r["source_site"] for r in rows[:6]]  # 상위 6개
    for src in sources:
        print(f"\n--- {src} ---")
        sample = await conn.fetch(
            """
            SELECT id, name, source_site, site_product_id, source_url,
                   cost, sale_price, original_price, sale_status,
                   last_refreshed_at
            FROM samba_collected_product
            WHERE source_site = $1
              AND last_refreshed_at > NOW() - INTERVAL '1 hour'
            ORDER BY RANDOM()
            LIMIT 5
        """,
            src,
        )
        for s in sample:
            print(
                f"  id={s['id']}  spid={s['site_product_id']}  cost={s['cost']}  sale={s['sale_price']}  orig={s['original_price']}  status={s['sale_status']}"
            )
            print(f"    name={s['name'][:60] if s['name'] else ''}")
            print(f"    url={s['source_url']}")

    await conn.close()


asyncio.run(main())

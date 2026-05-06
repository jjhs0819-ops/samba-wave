"""filters/tree 쿼리 성능 측정"""
import asyncio
import asyncpg
import time
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

    # 1. leaf filter IDs 개수 확인
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM samba_search_filter WHERE is_folder = FALSE"
    )
    print(f"leaf 필터 수: {count}")

    # leaf IDs 가져오기
    leaf_ids = await conn.fetch(
        "SELECT id FROM samba_search_filter WHERE is_folder = FALSE LIMIT 500"
    )
    ids = [str(r[0]) for r in leaf_ids]
    print(f"쿼리에 사용할 ID 수: {len(ids)}")

    # 2. 현재 쿼리 (registered_accounts 패턴) 성능 측정
    in_clause = ",".join(f"'{i}'" for i in ids)
    print("\n=== 현재 쿼리 (registered_accounts 패턴) ===")
    t0 = time.time()
    rows = await conn.fetch(f"""
        SELECT
            search_filter_id,
            COUNT(*) AS cnt,
            COUNT(*) FILTER (
                WHERE registered_accounts IS NOT NULL
                  AND jsonb_array_length(registered_accounts) > 0
                  AND market_product_nos IS NOT NULL
                  AND market_product_nos != '{{}}'::jsonb
            ) AS market_registered,
            COUNT(*) FILTER (WHERE tags @> '["__ai_tagged__"]'::jsonb) AS ai_tagged,
            COUNT(*) FILTER (WHERE tags @> '["__ai_image__"]'::jsonb) AS ai_image,
            COUNT(*) FILTER (
                WHERE tags IS NOT NULL AND jsonb_array_length(tags) > 0
            ) AS tag_applied,
            COUNT(*) FILTER (WHERE applied_policy_id IS NOT NULL) AS policy_applied
        FROM samba_collected_product
        WHERE search_filter_id IN ({in_clause})
        GROUP BY search_filter_id
    """)
    t1 = time.time()
    print(f"  결과: {len(rows)}행, 소요: {t1-t0:.2f}초")

    # 3. 개선 쿼리 (is_unregistered 패턴) 성능 측정
    print("\n=== 개선 쿼리 (is_unregistered 패턴) ===")
    t2 = time.time()
    rows2 = await conn.fetch(f"""
        SELECT
            search_filter_id,
            COUNT(*) AS cnt,
            COUNT(*) FILTER (WHERE is_unregistered = FALSE) AS market_registered,
            COUNT(*) FILTER (WHERE tags @> '["__ai_tagged__"]'::jsonb) AS ai_tagged,
            COUNT(*) FILTER (WHERE tags @> '["__ai_image__"]'::jsonb) AS ai_image,
            COUNT(*) FILTER (
                WHERE tags IS NOT NULL AND jsonb_array_length(tags) > 0
            ) AS tag_applied,
            COUNT(*) FILTER (WHERE applied_policy_id IS NOT NULL) AS policy_applied
        FROM samba_collected_product
        WHERE search_filter_id IN ({in_clause})
        GROUP BY search_filter_id
    """)
    t3 = time.time()
    print(f"  결과: {len(rows2)}행, 소요: {t3-t2:.2f}초")

    # 4. EXPLAIN
    print("\n=== EXPLAIN ===")
    plan = await conn.fetch(f"""
        EXPLAIN (FORMAT TEXT)
        SELECT search_filter_id, COUNT(*)
        FROM samba_collected_product
        WHERE search_filter_id IN ({in_clause})
        GROUP BY search_filter_id
    """)
    for r in plan[:6]:
        print(f"  {r[0]}")

    await conn.close()


asyncio.run(main())

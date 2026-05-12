"""5067947 상품의 registered_accounts / market_product_nos 어긋남 진단 + 전체 보정 영향 dry-run."""

import asyncio
import json

import asyncpg

from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.read_db_host,
        port=settings.read_db_port,
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )

    # 0) id 컬럼 타입 확인
    col_info = await conn.fetchrow(
        """
        SELECT data_type FROM information_schema.columns
        WHERE table_name='samba_collected_product' AND column_name='id'
        """
    )
    print(f"id 컬럼 타입: {col_info['data_type']}")

    # 1) 문제 상품 단건 조회 — id / site_product_id 양쪽 시도
    row = await conn.fetchrow(
        """
        SELECT id, name, source_site, brand, site_product_id,
               registered_accounts,
               market_product_nos,
               (last_sent_data IS NOT NULL) AS has_last_sent,
               sale_status
        FROM samba_collected_product
        WHERE id::text = '5067947' OR site_product_id = '5067947'
        LIMIT 1
        """
    )
    print("=" * 80)
    print("[1] 단건 진단 — 5067947")
    print("=" * 80)
    if not row:
        print("상품 없음")
    else:
        print(f"name={row['name']}")
        print(f"source_site={row['source_site']}  brand={row['brand']}")
        print(
            f"sale_status={row['sale_status']}  has_last_sent_data={row['has_last_sent']}"
        )
        ra = row["registered_accounts"]
        mpn = row["market_product_nos"]
        print(
            f"registered_accounts(type={type(ra).__name__})="
            f"{json.dumps(ra if not isinstance(ra, str) else json.loads(ra), ensure_ascii=False)}"
        )
        print(
            f"market_product_nos(type={type(mpn).__name__})="
            f"{json.dumps(mpn if not isinstance(mpn, str) else json.loads(mpn), ensure_ascii=False, indent=2)}"
        )

    # 2) 전체 어긋남 영향 dry-run
    print()
    print("=" * 80)
    print(
        "[2] 전체 어긋남 dry-run — market_product_nos 키와 registered_accounts 불일치"
    )
    print("=" * 80)

    # market_product_nos에서 _origin 접미사 제외한 키들의 truthy 집합 vs registered_accounts
    rows = await conn.fetch(
        """
        WITH derived AS (
          SELECT
            id,
            COALESCE(
              (
                SELECT jsonb_agg(DISTINCT k ORDER BY k)
                FROM jsonb_object_keys(market_product_nos) k
                WHERE k NOT LIKE '%\\_origin' ESCAPE '\\'
                  AND market_product_nos -> k IS NOT NULL
                  AND market_product_nos -> k <> 'null'::jsonb
                  AND market_product_nos -> k <> '""'::jsonb
              ),
              '[]'::jsonb
            ) AS derived_accs,
            CASE
              WHEN jsonb_typeof(registered_accounts) = 'array' THEN registered_accounts
              ELSE '[]'::jsonb
            END AS current_accs
          FROM samba_collected_product
          WHERE market_product_nos IS NOT NULL
            AND jsonb_typeof(market_product_nos) = 'object'
        )
        SELECT
          COUNT(*) AS total_with_mpn,
          COUNT(*) FILTER (
            WHERE NOT (derived_accs @> current_accs AND current_accs @> derived_accs)
          ) AS mismatch_rows,
          COUNT(*) FILTER (
            WHERE jsonb_array_length(derived_accs) > jsonb_array_length(current_accs)
          ) AS missing_in_current,
          COUNT(*) FILTER (
            WHERE jsonb_array_length(current_accs) > jsonb_array_length(derived_accs)
          ) AS extra_in_current
        FROM derived
        """
    )
    r = rows[0]
    print(f"market_product_nos 보유 상품: {r['total_with_mpn']:,}")
    print(f"  └ 어긋난 행:        {r['mismatch_rows']:,}")
    print(f"     ├ A칸에 빠진(derived>current): {r['missing_in_current']:,}")
    print(f"     └ A칸에 잔여(current>derived): {r['extra_in_current']:,}")

    # 3) 어긋난 행 샘플 5개
    print()
    print("[3] 어긋난 행 샘플 (5건)")
    print("-" * 80)
    samples = await conn.fetch(
        """
        WITH derived AS (
          SELECT
            id, name, source_site,
            COALESCE(
              (
                SELECT jsonb_agg(DISTINCT k ORDER BY k)
                FROM jsonb_object_keys(market_product_nos) k
                WHERE k NOT LIKE '%\\_origin' ESCAPE '\\'
                  AND market_product_nos -> k IS NOT NULL
                  AND market_product_nos -> k <> 'null'::jsonb
                  AND market_product_nos -> k <> '""'::jsonb
              ),
              '[]'::jsonb
            ) AS derived_accs,
            CASE
              WHEN jsonb_typeof(registered_accounts) = 'array' THEN registered_accounts
              ELSE '[]'::jsonb
            END AS current_accs
          FROM samba_collected_product
          WHERE market_product_nos IS NOT NULL
            AND jsonb_typeof(market_product_nos) = 'object'
        )
        SELECT id, name, source_site, derived_accs, current_accs
        FROM derived
        WHERE NOT (derived_accs @> current_accs AND current_accs @> derived_accs)
        ORDER BY id DESC
        LIMIT 5
        """
    )
    for s in samples:
        print(f"  id={s['id']}  site={s['source_site']}  name={s['name'][:40]}")
        print(f"    derived={s['derived_accs']}  current={s['current_accs']}")

    await conn.close()


asyncio.run(main())

"""3단계 진단 — 5067947 상품이 어떤 transmit 잡들에 어떻게 들어갔는지 추적."""

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

    # 0) 상품 정보 — id, updated_at, A칸/B칸
    print("=" * 80)
    print("[0] 상품 5067947 (site_product_id 기준) 기본 정보")
    print("=" * 80)
    prod = await conn.fetchrow(
        """
        SELECT id, name, source_site, BTRIM(brand) AS brand,
               site_product_id, registered_accounts, market_product_nos,
               updated_at, created_at
        FROM samba_collected_product
        WHERE site_product_id = '5067947' AND source_site = 'MUSINSA'
        LIMIT 1
        """
    )
    if not prod:
        print("상품 없음")
        await conn.close()
        return
    pid = prod["id"]
    print(f"id={pid}")
    print(f"name={prod['name']}")
    print(f"brand={prod['brand']}  site={prod['source_site']}")
    print(f"created_at={prod['created_at']}  updated_at={prod['updated_at']}")
    ra = prod["registered_accounts"]
    mpn = prod["market_product_nos"]
    print(f"registered_accounts={ra if not isinstance(ra, str) else json.loads(ra)}")
    print(f"market_product_nos={mpn if not isinstance(mpn, str) else json.loads(mpn)}")

    # unclehg 계정 ID 확인
    print()
    print("=" * 80)
    print("[1] unclehg 계정 식별")
    print("=" * 80)
    cols = await conn.fetch(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name='samba_market_account'
        ORDER BY ordinal_position
        """
    )
    col_names = [c["column_name"] for c in cols]
    print(f"  samba_market_account 컬럼: {col_names}")
    # ma_01KQBJGJ0QGMZ5THS89RQ4VK47 으로 unclehg 매칭
    acct_row = await conn.fetchrow(
        "SELECT * FROM samba_market_account WHERE id = $1",
        "ma_01KQBJGJ0QGMZ5THS89RQ4VK47",
    )
    if acct_row:
        print(f"  계정 row: {dict(acct_row)}")

    # 2) 이 상품이 들어간 transmit 잡 (최근 50건)
    print()
    print("=" * 80)
    print(f"[2] {pid} 가 포함된 transmit 잡 (최근 50건)")
    print("=" * 80)
    jobs = await conn.fetch(
        """
        SELECT id, status, created_at, started_at, completed_at,
               (payload::jsonb)->>'origin' AS origin,
               (payload::jsonb)->>'source_site' AS source_site,
               (payload::jsonb)->>'brand_name' AS brand_name,
               (payload::jsonb)->>'target_account_ids' AS target_account_ids,
               jsonb_array_length((payload::jsonb)->'product_ids') AS pid_count
        FROM samba_jobs
        WHERE job_type = 'transmit'
          AND (payload::jsonb)->'product_ids' @> to_jsonb($1::text)
        ORDER BY created_at DESC
        LIMIT 50
        """,
        pid,
    )
    if not jobs:
        print("  포함된 잡 없음 — payload 구조가 다를 수 있음")
    for j in jobs:
        print(
            f"  job={j['id']}  status={j['status']}  origin={j['origin']}  "
            f"site={j['source_site']}/{j['brand_name']}  "
            f"accts={j['target_account_ids']}  "
            f"pids={j['pid_count']}"
        )
        print(
            f"    created={j['created_at']}  started={j['started_at']}  done={j['completed_at']}"
        )

    # 3) 동일 (MUSINSA, 게스언더웨어, *) transmit 잡 — 최근 100건
    print()
    print("=" * 80)
    print("[3] MUSINSA/게스언더웨어 transmit 잡 (최근 100건) — 중복 생성 여부")
    print("=" * 80)
    same_key_jobs = await conn.fetch(
        """
        SELECT id, status, created_at,
               (payload::jsonb)->>'origin' AS origin,
               (payload::jsonb)->>'target_account_ids' AS target_account_ids,
               jsonb_array_length((payload::jsonb)->'product_ids') AS pid_count,
               ((payload::jsonb)->'product_ids') @> to_jsonb($1::text) AS contains_5067947
        FROM samba_jobs
        WHERE job_type = 'transmit'
          AND (payload::jsonb)->>'source_site' = 'MUSINSA'
          AND (payload::jsonb)->>'brand_name' = '게스언더웨어'
        ORDER BY created_at DESC
        LIMIT 100
        """,
        pid,
    )
    same_count_by_acct: dict[str, int] = {}
    for j in same_key_jobs:
        accts_text = j["target_account_ids"] or "?"
        same_count_by_acct[accts_text] = same_count_by_acct.get(accts_text, 0) + 1
        print(
            f"  job={j['id']}  status={j['status']}  origin={j['origin']}  "
            f"accts={accts_text}  pids={j['pid_count']}  "
            f"contains_5067947={j['contains_5067947']}  created={j['created_at']}"
        )
    print()
    print("  계정별 잡 개수:")
    for k, v in same_count_by_acct.items():
        print(f"    {k}: {v}")

    # 4) pending_transmit_keys 매칭 검증 — DB에 저장된 target_account_ids 포맷 확인
    print()
    print("=" * 80)
    print("[4] target_account_ids 포맷 — 코드 비교용 (acct_key=f'[\"id\"]')")
    print("=" * 80)
    sample = await conn.fetch(
        """
        SELECT DISTINCT (payload::jsonb)->>'target_account_ids' AS accts
        FROM samba_jobs
        WHERE job_type IN ('transmit', 'delete_market')
          AND status IN ('pending', 'running')
        LIMIT 10
        """
    )
    for s in sample:
        print(f"  저장 포맷: {repr(s['accts'])}")

    await conn.close()


asyncio.run(main())

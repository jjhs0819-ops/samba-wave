"""1단계: 백업 테이블 + 마켓 삭제 큐 테이블 생성

- samba_collected_product_dup_backup_20260510: 삭제 대상 28,093 row 전체 복제
- samba_dedupe_market_delete_queue: 마켓 삭제 호출 대상 1,878건 적재
"""
import asyncio
import asyncpg
from backend.core.config import settings


RANK_SQL = """
WITH dup_keys AS (
  SELECT COALESCE(tenant_id, '__NULL__') AS tk, source_site, site_product_id
  FROM samba_collected_product
  WHERE site_product_id IS NOT NULL AND site_product_id <> ''
  GROUP BY COALESCE(tenant_id, '__NULL__'), source_site, site_product_id
  HAVING COUNT(*) > 1
),
ranked AS (
  SELECT cp.*,
         CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
              THEN jsonb_array_length(cp.registered_accounts) ELSE 0 END AS reg_cnt_x,
         ROW_NUMBER() OVER (
           PARTITION BY COALESCE(cp.tenant_id, '__NULL__'), cp.source_site, cp.site_product_id
           ORDER BY
             (CASE WHEN jsonb_typeof(cp.registered_accounts) = 'array'
                    AND jsonb_array_length(cp.registered_accounts) > 0
                   THEN 1 ELSE 0 END) DESC,
             (
               SELECT COUNT(*) FROM jsonb_each(
                 CASE WHEN jsonb_typeof(cp.last_sent_data::jsonb) = 'object'
                      THEN cp.last_sent_data::jsonb ELSE '{}'::jsonb END
               ) e
               WHERE (e.value->>'sale_price') ~ '^[0-9]+(\\.[0-9]+)?$'
                 AND (e.value->>'sale_price')::numeric > 0
             ) DESC,
             cp.updated_at DESC NULLS LAST,
             cp.created_at ASC NULLS LAST,
             cp.id ASC
         ) AS rnk_x
  FROM samba_collected_product cp
  JOIN dup_keys d
    ON COALESCE(cp.tenant_id, '__NULL__') = d.tk
   AND cp.source_site = d.source_site
   AND cp.site_product_id = d.site_product_id
)
SELECT * FROM ranked
"""


async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )

    # 안전 — 이미 백업 테이블 있으면 중단
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE tablename='samba_collected_product_dup_backup_20260510'"
    )
    if exists:
        print("이미 백업 테이블 존재 — 중단")
        await conn.close()
        return

    print("=== 1) 백업 테이블 생성 ===")
    # CTAS — 삭제 대상 row 전체 복제 (rnk > 1)
    async with conn.transaction():
        await conn.execute(
            f"""
            CREATE TABLE samba_collected_product_dup_backup_20260510 AS
            SELECT *, NOW() AS backup_at
            FROM ({RANK_SQL}) t
            WHERE rnk_x > 1
            """
        )
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM samba_collected_product_dup_backup_20260510"
        )
        print(f"  백업 row: {cnt:,}개")
        await conn.execute(
            "CREATE INDEX ix_dupbk_id ON samba_collected_product_dup_backup_20260510(id)"
        )

    print("\n=== 2) 마켓 삭제 큐 테이블 생성 ===")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS samba_dedupe_market_delete_queue (
          queue_id BIGSERIAL PRIMARY KEY,
          collected_product_id TEXT NOT NULL,
          source_site TEXT NOT NULL,
          site_product_id TEXT NOT NULL,
          account_id TEXT NOT NULL,
          market_type TEXT NOT NULL,
          market_product_no TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INT NOT NULL DEFAULT 0,
          last_error TEXT,
          processed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_dedupe_q_status ON samba_dedupe_market_delete_queue(status)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_dedupe_q_cpid ON samba_dedupe_market_delete_queue(collected_product_id)"
    )

    # 큐 적재 — Python 단에서 케이스 2/mixed 분류 후 INSERT
    print("\n=== 3) 케이스 2/mixed 분류 후 큐 적재 ===")
    rows = await conn.fetch(
        f"""
        WITH r AS ({RANK_SQL})
        SELECT id, tenant_id, source_site, site_product_id, market_product_nos, rnk_x AS rnk, reg_cnt_x AS reg_cnt
        FROM r
        WHERE COALESCE(tenant_id, '__NULL__') || '|' || source_site || '|' || site_product_id IN (
            SELECT COALESCE(tenant_id, '__NULL__') || '|' || source_site || '|' || site_product_id
            FROM r
            WHERE rnk_x > 1 AND reg_cnt_x > 0
        )
        ORDER BY source_site, site_product_id, rnk_x
        """
    )

    # account_id → market_type 매핑 캐시
    accs = await conn.fetch("SELECT id, market_type FROM samba_market_account")
    market_type_map = {a['id']: a['market_type'] for a in accs}

    import json
    def pmpn(v):
        if v is None: return {}
        if isinstance(v, dict): return v
        if isinstance(v, str):
            try: return json.loads(v)
            except Exception: return {}
        return {}

    groups = {}
    for r in rows:
        key = (r['tenant_id'], r['source_site'], r['site_product_id'])
        groups.setdefault(key, []).append(r)

    queue_rows = []
    for key, rs in groups.items():
        keep = next((x for x in rs if x['rnk'] == 1), None)
        dels = [x for x in rs if x['rnk'] > 1 and x['reg_cnt'] > 0]
        if not keep or not dels:
            continue
        keep_mpn = {k: str(v) for k, v in pmpn(keep['market_product_nos']).items()
                    if not k.endswith('_origin') and v}
        for d in dels:
            d_mpn = {k: str(v) for k, v in pmpn(d['market_product_nos']).items()
                     if not k.endswith('_origin') and v}
            for acc, mpn in d_mpn.items():
                # keep_mpn과 다르면 마켓 삭제 대상
                if keep_mpn.get(acc) != mpn:
                    mt = market_type_map.get(acc, 'unknown')
                    queue_rows.append((d['id'], d['source_site'], d['site_product_id'], acc, mt, mpn))

    print(f"  큐 적재 대상: {len(queue_rows):,}건")
    if queue_rows:
        await conn.executemany(
            """
            INSERT INTO samba_dedupe_market_delete_queue
              (collected_product_id, source_site, site_product_id, account_id, market_type, market_product_no)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            queue_rows,
        )
    qcnt = await conn.fetchval("SELECT COUNT(*) FROM samba_dedupe_market_delete_queue")
    print(f"  큐 row: {qcnt:,}개")

    # 마켓별 통계
    by_mt = await conn.fetch(
        "SELECT market_type, COUNT(*) AS c FROM samba_dedupe_market_delete_queue GROUP BY market_type ORDER BY c DESC"
    )
    print("\n  마켓별 분포:")
    for r in by_mt:
        print(f"    {r['market_type']}: {r['c']:,}건")

    await conn.close()
    print("\n=== 1단계 완료 ===")
    print("다음 단계:")
    print("  step2: 마켓 삭제 큐 drain (외부 API 호출, 1,878건)")
    print("  step3: DB row 삭제 (백업된 28,093 row 본 삭제)")
    print("  step4: 유니크 인덱스 NULL-safe 재생성")


asyncio.run(main())

"""대상 상품의 등록 마켓/계정 분포 조사."""

import asyncio
from collections import Counter

import asyncpg
from backend.core.config import settings


async def main() -> None:
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )

    rows = await conn.fetch(
        """
        SELECT p.id,
               p.registered_accounts::text AS reg_txt,
               p.market_product_nos::text AS mnos_txt
        FROM samba_collected_product p
        WHERE p.source_site IN ('MUSINSA','무신사')
          AND p.options IS NOT NULL
          AND jsonb_typeof(p.options::jsonb) = 'array'
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(p.options::jsonb) o
            WHERE o->>'name' LIKE '%선택안함%'
          )
        LIMIT 5
        """
    )
    for r in rows:
        print(f"id={r['id']}")
        print(f"  registered_accounts: {r['reg_txt']}")
        print(f"  market_product_nos : {r['mnos_txt']}")
        print()

    # 계정별 분포
    acc_rows = await conn.fetch(
        """
        WITH t AS (
          SELECT jsonb_array_elements_text(p.registered_accounts::jsonb) AS acc_id
          FROM samba_collected_product p
          WHERE p.source_site IN ('MUSINSA','무신사')
            AND p.options IS NOT NULL
            AND jsonb_typeof(p.options::jsonb) = 'array'
            AND EXISTS (
              SELECT 1 FROM jsonb_array_elements(p.options::jsonb) o
              WHERE o->>'name' LIKE '%선택안함%'
            )
            AND p.registered_accounts IS NOT NULL
            AND jsonb_typeof(p.registered_accounts::jsonb) = 'array'
        )
        SELECT acc_id, count(*) AS c FROM t GROUP BY acc_id ORDER BY c DESC
        """
    )
    print(f"[계정별 등록건수 — 총 {len(acc_rows)}개 계정]")
    for r in acc_rows:
        # 계정 정보 조회
        acc = await conn.fetchrow(
            "SELECT market_type, market_name, seller_id FROM samba_market_account WHERE id = $1",
            r["acc_id"],
        )
        if acc:
            print(f"  {r['acc_id'][:12]}.. {acc['market_type']:>12} {acc['market_name']:>15} {acc['seller_id']:>30}  count={r['c']}")
        else:
            print(f"  {r['acc_id']}  count={r['c']}  (계정 없음)")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

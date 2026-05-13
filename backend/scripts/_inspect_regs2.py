"""registered_accounts 실제 구조 확인."""

import asyncio
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
        SELECT id, source_site, brand,
               registered_accounts::text AS reg_txt,
               market_product_nos::text AS mnos_txt
        FROM samba_collected_product
        WHERE source_site IN ('MUSINSA','무신사')
          AND options IS NOT NULL
          AND jsonb_typeof(options::jsonb) = 'array'
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(options::jsonb) o WHERE o->>'name' LIKE '%선택안함%')
        LIMIT 3
        """
    )
    print(f"[샘플] {len(rows)}건")
    for r in rows:
        print(f"\nid={r['id']} src={r['source_site']} brand={r['brand']}")
        print(f"  reg = {r['reg_txt']}")
        print(f"  mnos= {r['mnos_txt']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

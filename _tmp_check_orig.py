"""originalProductId(13355073551) 및 상품명으로 매칭 검색."""

import asyncio
import sys
sys.path.insert(0, "/app/backend")

from sqlalchemy import text
from backend.db.orm import get_read_session


async def main():
    async with get_read_session() as session:
        for pid in ["13355073551", "13414016965"]:
            print(f"\n=== product_id LIKE %{pid}% (samba_collected_product) ===")
            r = await session.execute(text("""
                SELECT id, name, source_site, source_url,
                       market_product_nos::text AS mpn_txt,
                       registered_accounts::text AS ra_txt
                FROM samba_collected_product
                WHERE market_product_nos::text LIKE CAST(:p AS text)
                LIMIT 5
            """), {"p": f"%{pid}%"})
            rows = r.fetchall()
            print(f"  {len(rows)}건")
            for row in rows:
                d = dict(row._mapping)
                print(f"  id={d['id']} site={d['source_site']} name={d['name'][:50] if d['name'] else None}")
                print(f"    url={d['source_url']}")
                print(f"    mpn={d['mpn_txt'][:200]}")
                print(f"    ra={d['ra_txt'][:100]}")

        print("\n=== name LIKE '나이키 FJ0736%' ===")
        r = await session.execute(text("""
            SELECT id, name, source_site, source_url,
                   market_product_nos::text AS mpn_txt,
                   registered_accounts::text AS ra_txt
            FROM samba_collected_product
            WHERE name LIKE '나이키 FJ0736%'
            LIMIT 5
        """))
        for row in r.fetchall():
            d = dict(row._mapping)
            print(f"  id={d['id']} site={d['source_site']}")
            print(f"    name={d['name']}")
            print(f"    url={d['source_url']}")
            print(f"    mpn={d['mpn_txt'][:200]}")
            print(f"    ra={d['ra_txt'][:100]}")


asyncio.run(main())

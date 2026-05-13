"""마스마룰즈 상품 옵션 구조 직접 조사."""

import asyncio
import json

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

    # 로그에서 본 site_product_id 들 조회
    ids = [
        "5008790616",
        "5008327885",
        "5003801852",
        "5000630656",
        "5008515410",
        "5008188696",
        "5000604927",
        "5000630408",
        "5012594257",
        "5001753523",
        "5000630434",
        "5004411751",
        "5015298896",
    ]
    rows = await conn.fetch(
        """
        SELECT id, site_product_id, name, brand, source_site,
               options::text AS options_txt,
               addon_options::text AS addon_txt,
               extra_data::text AS extra_txt
        FROM samba_collected_product
        WHERE site_product_id = ANY($1::text[])
        ORDER BY brand, id
        """,
        ids,
    )
    print(f"매칭: {len(rows)}건")
    for r in rows[:5]:
        print(f"\n--- id={r['id']} site={r['site_product_id']} brand={r['brand']} source={r['source_site']}")
        print(f"  name: {r['name']}")
        opts = r["options_txt"] or "null"
        addon = r["addon_txt"] or "null"
        extra = r["extra_txt"] or "null"
        print(f"  options: {opts[:400]}")
        print(f"  addon_options: {addon[:400]}")
        print(f"  extra_data: {extra[:400]}")

    # 전체 카운트도
    print("\n[대분류]")
    total_match = await conn.fetchval(
        "SELECT count(*) FROM samba_collected_product WHERE brand = '마스마룰즈'"
    )
    print(f"마스마룰즈 전체: {total_match}")

    # 검색필터 매핑 확인
    print("\n[검색필터 sf_01KRASAFGHK1TQC6VZDTEZ8P7C 의 상품 카운트]")
    sf_rows = await conn.fetch(
        """
        SELECT count(*) AS c FROM samba_collected_product
        WHERE search_filter_id = 'sf_01KRASAFGHK1TQC6VZDTEZ8P7C'
        """
    )
    for r in sf_rows:
        print(f"  count={r['c']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

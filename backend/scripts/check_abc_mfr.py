import asyncio
import asyncpg
from backend.core.config import settings


async def main():
    conn = await asyncpg.connect(
        host=settings.read_db_host,
        port=int(settings.read_db_port),
        user=settings.read_db_user,
        password=settings.read_db_password,
        database=settings.read_db_name,
        ssl=False,
    )
    # ABCmart 상품 manufacturer 값 분포
    rows = await conn.fetch(
        """
        SELECT manufacturer, COUNT(*) AS cnt
        FROM samba_collected_product
        WHERE source_site = 'ABCmart' AND manufacturer IS NOT NULL AND manufacturer <> ''
        GROUP BY manufacturer
        ORDER BY cnt DESC
        LIMIT 40
        """
    )
    print("=== ABCmart manufacturer 분포 (top 40) ===")
    for r in rows:
        v = r["manufacturer"]
        forbidden = [c for c in v if c in '\\*?"<>']
        flag = f" <<FORBIDDEN: {forbidden}>>" if forbidden else ""
        print(f"  cnt={r['cnt']:>5}  {v!r}{flag}")

    # 금지문자 포함된 manufacturer 모두
    print("\n=== 네이버 금지문자 포함 manufacturer (ABCmart) ===")
    rows = await conn.fetch(
        r"""
        SELECT manufacturer, COUNT(*) AS cnt
        FROM samba_collected_product
        WHERE source_site = 'ABCmart' AND manufacturer ~ '[\\*?"<>]'
        GROUP BY manufacturer
        ORDER BY cnt DESC
        LIMIT 30
        """
    )
    for r in rows:
        print(f"  cnt={r['cnt']:>5}  {r['manufacturer']!r}")

    await conn.close()


asyncio.run(main())

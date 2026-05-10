import asyncio, asyncpg
from backend.core.config import settings

async def m():
    c = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port,
        user=settings.write_db_user, password=settings.write_db_password,
        database=settings.write_db_name, ssl=False,
    )
    r = await c.fetch(
        "SELECT status, market_type, COUNT(*) AS c FROM samba_dedupe_market_delete_queue GROUP BY status, market_type ORDER BY status, market_type"
    )
    for x in r:
        print(f"  {x['status']:<25} {x['market_type']:<12} {x['c']:>5}")
    await c.close()

asyncio.run(m())

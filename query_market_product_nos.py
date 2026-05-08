import asyncio
import asyncpg
import sys
sys.path.insert(0, '/app/backend')
from backend.core.config import settings

PRODUCT_ID = 'cp_01KMXZ4R978KXSVQKANNCT291E'
ACCOUNT_ID = 'ma_01KQBJGJ0QGMZ5THS89RQ4VK47'

async def main():
    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=settings.use_db_ssl,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    cp = await conn.fetchrow(
        "SELECT id, status, registered_accounts, market_product_nos FROM samba_collected_product WHERE id = $1",
        PRODUCT_ID
    )
    if cp:
        import json
        reg = cp['registered_accounts'] or []
        nos = cp['market_product_nos'] or {}
        print(f"status: {cp['status']}")
        print(f"registered_accounts: {reg}")
        print(f"ACCOUNT_ID 포함 여부: {ACCOUNT_ID in str(reg)}")
        print(f"market_product_nos[account]: {nos.get(ACCOUNT_ID, 'NONE')}")

    await conn.close()

asyncio.run(main())

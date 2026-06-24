"""lottehome_credentials (tenant-scoped) password/agncNo 수정."""
import asyncio, json, asyncpg
from backend.core.config import settings

async def main():
    c = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port, ssl=False,
        database=settings.write_db_name, user=settings.write_db_user,
        password=settings.write_db_password
    )
    row = await c.fetchrow(
        "SELECT value FROM samba_settings WHERE key='lottehome_credentials' AND tenant_id IS NOT NULL"
    )
    if row:
        val = json.loads(row['value']) if isinstance(row['value'], str) else dict(row['value'])
        print('before:', {k: v for k, v in val.items() if k in ['password', 'agncNo', 'userId']})
        val.pop('password', None)
        if val.get('agncNo') == '037800LT':
            val['agncNo'] = '01032087310'
        await c.execute(
            "UPDATE samba_settings SET value=CAST($1 AS json) WHERE key='lottehome_credentials' AND tenant_id IS NOT NULL",
            json.dumps(val)
        )
        print('완료:', {k: v for k, v in val.items() if k in ['agncNo', 'userId']})
    await c.close()

asyncio.run(main())

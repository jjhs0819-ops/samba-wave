"""samba_sourcing_account.password 개인정보 제거."""
import asyncio, asyncpg
from backend.core.config import settings

async def main():
    c = await asyncpg.connect(
        host=settings.write_db_host, port=settings.write_db_port, ssl=False,
        database=settings.write_db_name, user=settings.write_db_user,
        password=settings.write_db_password
    )
    rows = await c.fetch(
        "SELECT id, site_name, account_label, username, password FROM samba_sourcing_account WHERE password ILIKE '%gemini0674%'"
    )
    print(f'대상: {len(rows)}개')
    for r in rows:
        print(f'  {r["site_name"]}/{r["account_label"]} ({r["username"]}): {r["password"]!r}')

    result = await c.execute(
        "UPDATE samba_sourcing_account SET password='' WHERE password ILIKE '%gemini0674%'"
    )
    print(f'제거: {result}')
    await c.close()

asyncio.run(main())
